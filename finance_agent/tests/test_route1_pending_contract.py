"""Pending lifecycle and one bounded structure correction; actual fixture, no API."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.pending_transition import transition, contract_error, PendingTransitionError
from app.responses import request_scope, parse_final, final_structure_diagnostic
from tests.test_tui_p0 import FIXTURE
from tests.test_model_reply_scope import final
from tests.test_named_invoice_selection import tool_group
from tests.test_sql_invoice_selection import snapshot


REQUEST = '甲企业2026年9月F001、F009用途及备注先核对，稍后选一张备注填为「随票材料集中复核后归档」。'
VALUE = '随票材料集中复核后归档'


def waiting(action='create', request_id=None, scope=None):
    event = {'action': action, 'scope': scope or {'invoice_no': ['F001', 'F009']}}
    if request_id is not None:
        event['request_id'] = request_id
    return final('当前字段已核对，请确定要更新备注的票号。', 'information',
                 missing_fields=['invoice_no'], pending=event,
                 **({'pending_change': {'field': 'remark', 'new_value': VALUE}} if action == 'create' else {}))


class PendingContractTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'book.sqlite3'
        import_workspace(FIXTURE, self.path)

    def agent(self, model):
        return Agent('U001', self.path, model, mode='mock', trace_path=self.path.with_suffix('.jsonl'))

    def read(self, *numbers):
        return tool_group('get_invoice', ({'company_id': 'C001', 'invoice_no': n} for n in numbers))

    def test_explicit_information_create_then_replace_preserves_unmodified_slots(self):
        stage = iter(('read', 'create', 'read_all', 'replace'))
        def model(messages, tools):
            event = next(stage)
            if event == 'read': return self.read('F001', 'F009')
            if event == 'create': return waiting()
            if event == 'read_all': return self.read('F001', 'F003', 'F009')
            current = self.pending_from(messages)
            return waiting('replace', current['request_id'], {'invoice_no': ['F003', 'F009']})
        agent = self.agent(model)
        before = snapshot(self.path)
        agent.ask(REQUEST)
        self.assertEqual(agent.pending_intent['change']['new_value'], [VALUE])
        agent.ask('待选调整：F001移出，补入F003，F009仍保留；企业账期和原值不变。')
        pending = agent.pending_intent
        self.assertEqual(pending['scope']['invoice_no'], ['F003', 'F009'])
        self.assertEqual(pending['scope']['company_id'], ['C001'])
        self.assertEqual(pending['scope']['periods'], [(2026, 9)])
        self.assertEqual(pending['change']['new_value'], [VALUE])
        self.assertEqual(agent.last_response['execution']['stop_reason'], 'WAITING_USER')
        self.assertEqual(snapshot(self.path), before)

    @staticmethod
    def pending_from(messages):
        return next(json.loads(m['content'])['pending_request'] for m in reversed(messages)
                    if m.get('name') == 'context_data' and 'pending_request' in json.loads(m['content']))

    def test_missing_information_metadata_is_corrected_once_with_no_tools(self):
        observed = []
        replies = iter((self.read('F001', 'F009'), final('当前字段已查到。'), waiting()))
        def model(messages, tools):
            observed.append(list(tools))
            return next(replies)
        agent = self.agent(model)
        before = snapshot(self.path)
        agent.ask(REQUEST)
        self.assertEqual(len(observed), 3)
        self.assertTrue(observed[0])
        self.assertEqual(observed[2], [])
        self.assertEqual(agent.last_response['execution']['model_requests'], 3)
        self.assertEqual(agent.last_response['execution']['actual_tool_calls'], 2)
        self.assertIsNotNone(agent.pending_intent)
        self.assertEqual(snapshot(self.path), before)

    def test_failed_structure_correction_stops_without_looping(self):
        replies = iter((self.read('F001', 'F009'), final('当前字段已查到。'), final('仍没有元数据。')))
        agent = self.agent(lambda *_: next(replies))
        before = snapshot(self.path)
        agent.ask(REQUEST)
        self.assertEqual(agent.last_response['execution']['model_requests'], 3)
        self.assertEqual(agent.last_response['execution']['stop_reason'], 'INVALID_RESPONSE')
        self.assertIsNone(agent.pending_intent)
        self.assertEqual(snapshot(self.path), before)

    def test_correction_cannot_dispatch_business_tools(self):
        replies = iter((self.read('F001', 'F009'), final('当前字段已查到。'),
                        tool_group('prepare_invoice_update', ({'company_id': 'C001', 'invoice_no': 'F001',
                                                               'field': 'remark', 'new_value': '伪造'},))))
        agent = self.agent(lambda *_: next(replies))
        before = snapshot(self.path)
        agent.ask(REQUEST)
        self.assertEqual(agent.last_response['execution']['actual_tool_calls'], 2)
        self.assertFalse(agent.update_session.drafts)
        self.assertEqual(snapshot(self.path), before)

    def test_correction_uses_the_existing_single_completion_slot(self):
        replies = iter((self.read('F001'), self.read('F009'), final('当前字段已查到。'), waiting()))
        seen = []
        def model(messages, tools):
            seen.append(list(tools))
            return next(replies)
        agent = self.agent(model)
        agent.ask(REQUEST)
        self.assertEqual(agent.last_response['execution']['model_requests'], 4)
        self.assertEqual(agent.last_response['execution']['extensions'], 1)
        self.assertEqual(seen[-1], [])
        self.assertIsNotNone(agent.pending_intent)

    def test_hard_request_limit_is_not_raised_for_structure_correction(self):
        replies = iter((self.read('F001'), self.read('F009'), final('当前字段已查到。'), waiting()))
        agent = Agent('U001', self.path, lambda *_: next(replies), mode='mock',
                      max_requests=3, trace_path=self.path.with_suffix('.jsonl'))
        agent.ask(REQUEST)
        self.assertEqual(agent.last_response['execution']['model_requests'], 3)
        self.assertEqual(agent.last_response['execution']['stop_reason'], 'MODEL_LIMIT')
        self.assertIsNone(agent.pending_intent)

    def test_general_and_independent_query_do_not_consume_existing_pending(self):
        replies = iter((self.read('F001', 'F009'), waiting(), final('请您方便时补充。', 'general'),
                        self.read('F001'), final('F001当前备注是日常办公采购。', missing_fields=[])))
        agent = self.agent(lambda *_: next(replies))
        before = snapshot(self.path)
        agent.ask(REQUEST)
        pending = agent.pending_intent
        agent.ask('把「赶紧处理」改得客气些。')
        self.assertEqual(agent.pending_intent, pending)
        agent.ask('先查甲企业F001的备注。')
        self.assertEqual(agent.pending_intent, pending)
        self.assertEqual(agent.last_response['execution']['model_requests'], 2)
        self.assertEqual(agent.last_response.get('assistant_text'), 'F001当前备注是日常办公采购。')
        self.assertEqual(snapshot(self.path), before)

    def test_explicit_cancel_closes_only_the_pending_and_never_writes(self):
        replies = iter((self.read('F001', 'F009'), waiting()))
        agent = self.agent(lambda *_: next(replies))
        before = snapshot(self.path)
        agent.ask(REQUEST)
        current_id = agent.pending_intent['request_id']
        agent.model = lambda *_: final('已结束这项待补。', missing_fields=[],
                                      pending={'action': 'cancel', 'request_id': current_id})
        agent.ask('这项先作罢，账簿不用动。')
        self.assertIsNone(agent.pending_intent)
        self.assertEqual(agent.last_response['execution']['stop_reason'], 'CANCELLED')
        self.assertEqual(snapshot(self.path), before)

    def test_ordinary_invoice_query_has_no_fixed_extra_request(self):
        replies = iter((self.read('F001'), final('F001当前备注为日常办公采购。')))
        agent = self.agent(lambda *_: next(replies))
        agent.ask('甲企业F001当前备注是什么？')
        self.assertEqual(agent.last_response['execution']['model_requests'], 2)
        self.assertIsNone(agent.pending_intent)

    def test_declared_completion_is_not_semantically_proved(self):
        replies = iter((self.read('F001', 'F009'), final('当前字段已核对。', missing_fields=[])))
        agent = self.agent(lambda *_: next(replies))
        before = snapshot(self.path)
        agent.ask(REQUEST)
        # This is a recorded semantic limit, not evidence that the edit goal
        # succeeded: a syntactically legal [] is not independently understood.
        self.assertEqual(agent.last_response['execution']['model_requests'], 2)
        self.assertIsNone(agent.pending_intent)
        self.assertNotIn('invoice_change', agent.last_response)
        self.assertEqual(snapshot(self.path), before)

    def test_three_turn_selection_uses_original_value_and_stays_uncommitted(self):
        stage = iter(('read', 'create', 'reread', 'replace', 'selected', 'proposal'))
        def model(messages, tools):
            event = next(stage)
            if event == 'read': return self.read('F001', 'F009')
            if event == 'create': return waiting()
            if event == 'reread': return self.read('F003', 'F009')
            if event == 'replace': return waiting('replace', self.pending_from(messages)['request_id'], {'invoice_no': ['F003', 'F009']})
            if event == 'selected': return self.read('F003')
            pending = self.pending_from(messages)
            selected = next(json.loads(m['content'])['data'] for m in reversed(messages)
                            if m['role'] == 'tool' and json.loads(m['content']).get('data', {}).get('invoice_no') == 'F003')
            return tool_group('propose_invoice_changes', ({'selection_id': selected['selection_id'],
                'field': 'remark', 'new_value': VALUE, 'mode': 'item', 'excluded_invoice_ids': [],
                'pending_request_id': pending['request_id'],
                'write_scope': {'company_id': 'C001', 'year': 2026, 'month': 9, 'invoice_nos': ['F003']}},))
        agent = self.agent(model)
        before = snapshot(self.path)
        agent.ask(REQUEST)
        agent.ask('F001移出，补入F003，F009保留；企业账期和新备注原值保留。')
        agent.ask('选F003这一张，只预览备注，用途不变。')
        change = agent.last_response['invoice_change']
        self.assertEqual(change['invoice_nos'], ('F003',))
        self.assertEqual(change['new_value'], VALUE)
        self.assertEqual(agent.last_response['execution']['stop_reason'], 'WAITING_CONFIRMATION')
        self.assertEqual(snapshot(self.path), before)
        agent.cancel_update()
        self.assertEqual(snapshot(self.path), before)

    def test_stale_patch_and_source_expansion_are_rejected(self):
        args = dict(actor='U001', book=self.path, current_id='new', current_request=REQUEST,
                    current_scope=request_scope(REQUEST, True), missing_fields=['invoice_no'])
        initial = transition(None, {'action': 'create', 'scope': {'invoice_no': ['F001', 'F009']}}, **args)
        with self.assertRaises(PendingTransitionError):
            transition(initial, {'action': 'continue', 'request_id': 'stale'}, **args)
        with self.assertRaises(PendingTransitionError):
            transition(initial, {'action': 'replace', 'request_id': initial['request_id'],
                                 'scope': {'invoice_no': ['F999']}}, **args)

    def test_no_event_does_not_infer_subset_from_reads(self):
        args = dict(actor='U001', book=self.path, current_id='old', current_request=REQUEST,
                    current_scope=request_scope(REQUEST, True), missing_fields=['invoice_no'])
        initial = transition(None, {'action': 'create', 'scope': {'invoice_no': ['F001', 'F009']}}, **args)
        continued = transition(initial, {'action': 'continue', 'request_id': 'old'},
                               **{**args, 'current_id': 'new', 'current_request': '只检查F009当前值。'})
        self.assertEqual(continued['scope']['invoice_no'], ['F001', 'F009'])

    def test_current_explicit_invoice_cannot_be_widened_by_old_candidates(self):
        replies = iter((self.read('F001', 'F009'), waiting(), self.read('F009'),
                        final('未取得本轮指定票的结果。', missing_fields=[])))
        agent = self.agent(lambda *_: next(replies))
        agent.ask(REQUEST)
        agent.ask('现在仅查询甲企业F001的备注，不做修改。')
        outcomes = [r for name, r in agent.last_response['tool_results'] if name == 'get_invoice']
        self.assertTrue(outcomes)
        self.assertTrue(all(r['status'] != 'SUCCESS' for r in outcomes))

    def test_period_patch_updates_date_slots_as_one_joint_key(self):
        args = dict(actor='U001', book=self.path, current_id='old', current_request='2026年8月F001 F009',
                    current_scope={'year': [2026], 'month': [8], 'periods': [(2026, 8)], 'invoice_no': ['F001', 'F009']},
                    missing_fields=['invoice_no'])
        initial = transition(None, {'action': 'create', 'scope': {'invoice_no': ['F001', 'F009']}}, **args)
        result = transition(initial, {'action': 'replace', 'request_id': 'old', 'scope': {'periods': [[2026, 9]]}},
                            **{**args, 'current_id': 'new', 'current_scope': {'year': [2026], 'month': [9], 'periods': [(2026, 9)]}})
        self.assertEqual(result['scope']['month'], [9])
        self.assertEqual(result['scope']['year'], [2026])

    def test_unmentioned_cartesian_date_pair_is_rejected(self):
        args = dict(actor='U001', book=self.path, current_id='old', current_request='2025年8月F001 F009',
                    current_scope={'year': [2025], 'month': [8], 'periods': [(2025, 8)], 'invoice_no': ['F001', 'F009']},
                    missing_fields=['invoice_no'])
        initial = transition(None, {'action': 'create', 'scope': {'invoice_no': ['F001', 'F009']}}, **args)
        with self.assertRaises(PendingTransitionError):
            transition(initial, {'action': 'replace', 'request_id': 'old', 'scope': {'year': [2025], 'month': [9]}},
                       **{**args, 'current_id': 'new', 'current_scope': {'year': [2026], 'month': [9], 'periods': [(2026, 9)]}})

    def test_general_label_cannot_bypass_declared_waiting_contract(self):
        final = {'kind': 'general', 'text': '请补充票号。', 'missing_fields': ['invoice_no']}
        self.assertEqual(contract_error(final, True), 'pending_event_required_for_waiting')
        self.assertEqual(contract_error(final, False), 'pending_event_required_for_waiting')
        self.assertIsNone(contract_error({'kind': 'general', 'text': '客气说法。'}, True))

    def test_malformed_pending_final_gets_only_no_tool_correction(self):
        seen = []
        invalid = {'role': 'assistant', 'content': json.dumps({'kind': 'information', 'text': '请选票',
                   'missing_fields': ['invoice_no'], 'pending': {'action': 'create', 'scope': 'bad'}})}
        replies = iter((self.read('F001', 'F009'), invalid, waiting()))
        def model(messages, tools):
            seen.append(list(tools))
            return next(replies)
        agent = self.agent(model)
        agent.ask(REQUEST)
        self.assertEqual(len(seen), 3)
        self.assertEqual(seen[-1], [])
        self.assertIsNotNone(agent.pending_intent)
        self.assertEqual(agent.last_response['execution']['actual_tool_calls'], 2)

    def test_single_date_slot_amends_unique_prior_pair(self):
        args = dict(actor='U001', book=self.path, current_id='old', current_request='2026年9月F001 F009',
                    current_scope={'year': [2026], 'month': [9], 'periods': [(2026, 9)], 'invoice_no': ['F001', 'F009']},
                    missing_fields=['invoice_no'])
        initial = transition(None, {'action': 'create', 'scope': {'invoice_no': ['F001', 'F009']}}, **args)
        for patch, expected in [({'year': [2025]}, (2025, 9)), ({'month': [8]}, (2026, 8))]:
            with self.subTest(patch=patch):
                result = transition(initial, {'action': 'replace', 'request_id': 'old', 'scope': patch},
                                    **{**args, 'current_id': 'new', 'current_scope': patch})
                self.assertEqual(result['scope']['periods'], [expected])

    def test_cancel_cannot_also_declare_waiting_or_new_change(self):
        envelope = {'kind': 'information', 'text': '取消', 'missing_fields': ['invoice_no'],
                    'pending': {'action': 'cancel', 'request_id': 'old'}}
        self.assertEqual(contract_error(envelope, True), 'inconsistent_cancel_event')
        previous = {'actor': 'U001', 'workbook': str(self.path), 'request_id': 'old'}
        with self.assertRaises(PendingTransitionError):
            transition(previous, envelope['pending'], actor='U001', book=self.path, current_id='new',
                       current_request='取消', current_scope={}, missing_fields=['invoice_no'])

    def test_thinking_pending_correction_survives_third_turn(self):
        from app.thinking_protocol import ThinkingProtocol
        make_agent = self.agent
        def thinking_agent(model):
            buffered = []
            repaired = {'done': False}
            def private_model(messages, tools):
                reply = buffered.pop() if buffered else model(messages, tools)
                parsed = json.loads(reply['content']) if reply.get('content') else {}
                if parsed.get('pending', {}).get('action') == 'replace' and not repaired['done']:
                    repaired['done'] = True
                    buffered.append(reply)
                    reply = final('候选已更新，请继续选票。')
                return {**reply, 'reasoning_content': 'SYNTHETIC_PROTOCOL_BINDING'}
            agent = make_agent(private_model)
            agent.protocol = ThinkingProtocol('https://api.deepseek.com', 'deepseek-flash', bind_environment=False)
            return agent
        self.agent = thinking_agent
        try:
            self.test_three_turn_selection_uses_original_value_and_stays_uncommitted()
        finally:
            self.agent = make_agent

    def test_nested_change_is_rejected_with_exact_contract_path(self):
        text = json.dumps({'kind': 'information', 'text': '继续选票', 'missing_fields': ['invoice_no'],
                           'pending': {'action': 'replace', 'request_id': 'old',
                                       'pending_change': {'field': 'remark', 'new_value': VALUE}}})
        self.assertIsNone(parse_final(text))
        error = final_structure_diagnostic(text)
        self.assertEqual(error['path'], '$.pending')
        self.assertEqual(error['keys'], ['pending_change'])
        self.assertEqual(set(error['allowed_keys']), {'action', 'request_id', 'scope'})


if __name__ == '__main__':
    unittest.main()
