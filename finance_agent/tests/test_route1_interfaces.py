"""Focused route1 public-interface checks. Scripted model, actual fixture DB."""
import json
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from app.agent import Agent
from app.business_sql import _query_scope, _projection_units
from app.cli_workspaces import import_workspace
from app.context import ContextBuilder
from app.responses import request_scope, merge_pending_scope, reply_evidence_conflict
from app.scheduler import BudgetPolicy, TurnExecution
from app.stage2_schema import open_existing
from app.tui_intent import invoice_change_boundary, literal_single_invoice_edit
from tests.test_model_reply_scope import final
from tests.test_named_invoice_selection import tool_group
from tests.test_sql_invoice_selection import snapshot
from tests.test_tui_p0 import FIXTURE


class Route1Interfaces(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'test.sqlite3'
        import_workspace(FIXTURE, self.path)

    def agent(self, replies):
        replies = iter(replies)
        return Agent('U001', self.path, lambda *_: next(replies), mode='mock',
                     trace_path=self.path.with_suffix('.jsonl'))

    def test_scope_does_not_upgrade_quoted_payload(self):
        scope = request_scope('乙企业2026年9月 F009备注写「甲企业2025年8月 F011」', True)
        self.assertEqual(scope['company_id'], ['C002'])
        self.assertEqual(scope['invoice_no'], ['F009'])
        self.assertEqual(scope['periods'], [(2026, 9)])
        self.assertNotIn('month', request_scope('这一月'))

    def test_pending_replacement_retains_unchanged_slots(self):
        prior = request_scope('甲企业2026年9月 F002 F004 F009', True)
        merged = merge_pending_scope(prior, 'F002移出，F004和F009继续',
                                     {'invoice_no': ['F004', 'F009']})
        self.assertEqual(merged['company_id'], ['C001'])
        self.assertEqual(merged['periods'], [(2026, 9)])
        self.assertEqual(merged['invoice_no'], ['F004', 'F009'])
        with self.assertRaises(ValueError):
            merge_pending_scope(prior, '继续', {'invoice_no': ['F999']})

    def test_clear_is_a_typed_candidate_not_a_write(self):
        before = snapshot(self.path)
        self.assertTrue(invoice_change_boundary('甲企业 F010备注清空', 'remark', ''))
        self.assertFalse(invoice_change_boundary('备注不要清空', 'remark', ''))
        self.assertEqual(snapshot(self.path), before)

    def test_composite_literal_can_reconcile_same_value(self):
        edit = literal_single_invoice_edit('甲企业 F010，备注写「打印资料」；其他字段保留。')
        self.assertEqual(edit['invoice_no'], ['F010'])
        self.assertEqual(edit['new_value'], ['打印资料'])

    def test_range_and_in_scope_attribute_executed_filters(self):
        sql = ("SELECT COUNT(*) AS n, SUM(amount_cents) AS total FROM invoices "
               "WHERE company_id IN ('C001') AND invoice_date >= '2026-09-01' "
               "AND invoice_date < '2026-10-01'")
        query = _query_scope(sql, {'company_ids': ('C001',), 'periods': ((2026, 9),)}, {'invoices'}, 1)
        self.assertEqual(query['scope']['periods'], ((2026, 9),))
        self.assertEqual(_projection_units(sql, ('n', 'total')), ('count', 'cents'))
        self.assertEqual(_projection_units('SELECT COUNT(*) AS amount_cents FROM invoices', ('amount_cents',)), ('count',))
        self.assertIsNone(_query_scope('SELECT * FROM invoices WHERE amount_cents > 1 OR amount_cents < 3',
                                     {'company_ids': ('C001',), 'periods': ((2026, 9),)}, {'invoices'}, 1)['scope'])

    def test_guard_uses_actual_nested_summary_and_preserves_negative_control(self):
        outcome = {'status': 'SUCCESS', 'data': {}, 'evidence': {'source': 'current_sqlite',
                   'scope': {'company_id': 'C001'}, 'finance_summary': {'invoice_total': '10.20', 'bank_income_total': '12.50'}}}
        self.assertIsNone(reply_evidence_conflict('相差2.30元', [('list_invoices', outcome)], '比较'))
        self.assertEqual(reply_evidence_conflict('相差3.30元', [('list_invoices', outcome)], '比较'), 'unbound_reply_literals')

    def test_recent_native_read_rechecks_after_external_update(self):
        agent = self.agent([tool_group('get_invoice', ({'company_id': 'C001', 'invoice_no': 'F010'},)),
                            final('F010已经查到。'),
                            tool_group('get_invoice', ({'company_id': 'C001', 'invoice_no': 'F010'},)),
                            final('F010当前备注是外部更新。')])
        agent.ask('甲企业 F010的备注是什么')
        with closing(open_existing(self.path)) as connection:
            connection.execute("UPDATE invoices SET remark='外部更新' WHERE company_id='C001' AND invoice_no='F010'")
            connection.commit()
        agent.ask('那张的备注现在呢')
        reads = [r for n, r in agent.last_response['tool_results'] if n == 'get_invoice']
        self.assertEqual(reads[-1]['status'], 'SUCCESS')
        self.assertEqual(reads[-1]['data']['remark'], '外部更新')

    def test_restored_hints_are_keys_and_permission_filtered(self):
        context = ContextBuilder('U002', self.path)
        context.restore_query_hints([{'tools': ['get_invoice'], 'invoice_query': {'company_id': 'C002', 'invoice_no': 'F001'}}])
        self.assertEqual(context.recent_invoice_candidates([]), {})
        context.restore_query_hints([])
        self.assertIsNone(context.recent_invoice_query)

    def test_general_rewrite_does_not_become_waiting_for_sql(self):
        agent = self.agent([final('麻烦您方便时补充一下。', 'general')])
        before = snapshot(self.path)
        agent.ask('把这句话说得客气些：「赶紧补上」')
        self.assertNotEqual(agent.last_response['execution']['stop_reason'], 'WAITING_USER')
        self.assertIn('麻烦您', agent.last_response.get('assistant_text', ''))
        self.assertEqual(snapshot(self.path), before)

    def test_scope_correction_summary_is_not_an_unfinished_edit(self):
        agent = self.agent([tool_group('get_finance_summary', ({'company_id': 'C002', 'year': 2026, 'month': 9},)),
                            final('乙企业本期汇总已核对。')])
        agent.ask('主体换成乙企业，2026年9月仍看汇总，别改成发票明细。')
        self.assertEqual(agent.last_response['execution']['stop_reason'], 'ANSWERED')
        self.assertEqual(agent.last_response.get('assistant_text'), '乙企业本期汇总已核对。')

    def test_quoted_foreign_key_payload_does_not_pollute_preview_scope(self):
        from tests.test_mixed_invoice_scope import mixed_model
        value = '甲企业2025年8月 F011待核'
        agent = Agent('U001', self.path, mixed_model(company='C002', keys=('F009',), target='F009', value=value),
                      mode='mock', trace_path=self.path.with_suffix('.jsonl'))
        before = snapshot(self.path)
        agent.ask(f'乙企业2026年9月 F009的备注改成「{value}」。')
        self.assertEqual(agent.last_response['invoice_change']['invoice_nos'], ('F009',))
        self.assertEqual(agent.last_response['invoice_change']['company_id'], 'C002')
        self.assertEqual(snapshot(self.path), before)

    def test_composite_same_value_has_readonly_receipt(self):
        with closing(open_existing(self.path, readonly=True)) as connection:
            value = connection.execute("SELECT remark FROM invoices WHERE company_id='C001' AND invoice_no='F010'").fetchone()[0]
        agent = self.agent([tool_group('get_invoice', ({'company_id': 'C001', 'invoice_no': 'F010'},)),
                            final('当前值已经相同。')])
        before = snapshot(self.path)
        agent.ask(f'甲企业 F010的备注改成「{value}」；其他字段保留。')
        self.assertEqual(agent.write_receipt['status'], 'CURRENT_VALUE_MATCHES')
        self.assertEqual(snapshot(self.path), before)

    def test_information_style_rewrite_is_unverified_not_false_pending(self):
        agent = self.agent([final('麻烦您方便时补充一下。')])
        agent.ask('把这句话说得客气些：「赶紧补上」')
        self.assertNotEqual(agent.last_response['execution']['stop_reason'], 'WAITING_USER')
        self.assertIsNone(agent.pending_intent)

    def test_pending_replace_uses_existing_event_and_keeps_payload(self):
        stage = iter(('first_read', 'first_question', 'second_read', 'replacement'))
        def model(messages, _tools):
            event = next(stage)
            if event.endswith('read'):
                numbers = ('F002', 'F004', 'F009') if event == 'first_read' else ('F004', 'F009')
                return tool_group('get_invoice', ({'company_id': 'C001', 'invoice_no': n} for n in numbers))
            if event == 'first_question':
                return final('请确定其中哪张备注需要更新。', 'clarification', missing_fields=['invoice_no'],
                             pending_change={'field': 'remark', 'new_value': '票据待核'},
                             pending={'action': 'create', 'scope': {'invoice_no': ['F002', 'F004', 'F009']}})
            pending = next(json.loads(m['content'])['pending_request'] for m in reversed(messages)
                           if m.get('name') == 'context_data' and 'pending_request' in json.loads(m['content']))
            return final('F002移出，F004与F009仍待选。', 'clarification', missing_fields=['invoice_no'],
                         pending={'request_id': pending['request_id'], 'action': 'replace',
                                  'scope': {'invoice_no': ['F004', 'F009']}})
        agent = Agent('U001', self.path, model, mode='mock', trace_path=self.path.with_suffix('.jsonl'))
        before = snapshot(self.path)
        agent.ask('甲企业2026年9月 F002 F004 F009，选其中一张备注改成「票据待核」，稍后选。')
        agent.ask('F002移出，F004和F009继续待选。')
        self.assertEqual(agent.pending_intent['scope']['invoice_no'], ['F004', 'F009'])
        self.assertEqual(agent.pending_intent['scope']['company_id'], ['C001'])
        self.assertEqual(agent.pending_intent['scope']['periods'], [(2026, 9)])
        self.assertEqual(agent.pending_intent['change']['new_value'], ['票据待核'])
        self.assertEqual(snapshot(self.path), before)

    def test_final_read_completion_is_single_and_permission_checked(self):
        execution = TurnExecution(BudgetPolicy(), can_continue=lambda _: True)
        execution.allow_read_completion = True
        execution.model_requests, execution.progress = 3, 1
        execution.observed = [{'action': 'get_invoice', 'arguments': {'company_id': 'C001'}, 'source': 'current_sqlite'}]
        self.assertTrue(execution.start_request())
        self.assertEqual((execution.model_requests, execution.extensions, execution.block_limit), (4, 1, 4))
        self.assertFalse(execution.start_request())
        denied = TurnExecution(BudgetPolicy(), can_continue=lambda _: False)
        denied.allow_read_completion = True
        denied.model_requests, denied.progress, denied.observed = 3, 1, execution.observed
        self.assertFalse(denied.start_request())
        self.assertEqual(denied.stop_reason, 'NO_LEGAL_WORK')


if __name__ == '__main__':
    unittest.main()
