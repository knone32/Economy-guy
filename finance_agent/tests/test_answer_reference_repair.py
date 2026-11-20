"""One existing-loop, tool-free correction of invalid current fact references."""
from contextlib import closing
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import app.agent as runtime
from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.request_budget import BudgetExceeded
from app.model_transport import ModelOutputTruncated
from tests.test_answer_evidence import facts, final


class AnswerReferenceRepairTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.book = Path(temporary.name) / 'fictional.sqlite3'
        import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', self.book)
        self.trace = self.book.with_suffix('.jsonl')

    def call(self, identifier, name, **args):
        return {'id': identifier, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}

    def run_case(self, behavior='good', *, max_requests=9, missing=False):
        self.seen, self.invalid_answer = [], None
        with closing(sqlite3.connect(self.book)) as db:
            before = db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no').fetchall()
            totals = dict(db.execute("SELECT substr(invoice_date,1,7),sum(amount_cents) FROM invoices "
                                     "WHERE company_id='C001' GROUP BY substr(invoice_date,1,7)"))
        def model(messages, tools):
            self.seen.append((messages, tools))
            stage = len(self.seen)
            if stage == 1:
                return {'role': 'assistant', 'tool_calls': [self.call(label, 'query_business_sql', sql=(
                    "SELECT SUM(amount_cents) AS total_cents FROM invoices WHERE invoice_date>="
                    f"'2026-{month:02d}-01' AND invoice_date<'2026-{month+1:02d}-01'"))
                    for label, month in (('aug', 8), ('sep', 9))]}
            if stage == 2:
                return {'role': 'assistant', 'tool_calls': [self.call('count', 'query_business_sql',
                    sql="SELECT COUNT(*) AS cnt FROM invoices WHERE invoice_date LIKE '2026-09-%'")]}
            catalog = facts(messages)
            results = [f['ref'] for f in catalog if f.get('type') == 'result']
            if stage == 3:
                self.invalid_answer = (['previous-turn:missing'] if missing else
                    [{'op': 'subtract', 'left': results[1], 'right': results[0]}])
                return final('已经保存全部修改。', answer=self.invalid_answer)
            self.assertEqual(stage, 4, 'At most one final reference correction is permitted')
            if behavior == 'invalid':
                return final('已经保存全部修改。', answer=self.invalid_answer)
            if behavior == 'tools':
                return {'role': 'assistant', 'tool_calls': [
                    self.call('forbidden-read', 'get_invoice', company_id='C001', invoice_no='F001'),
                    self.call('forbidden-write', 'change_invoice', company_id='C001', invoice_no='F001',
                              field='remark', new_value='must-not-save')]}
            if behavior == 'budget':
                raise BudgetExceeded('token_reservation')
            if behavior == 'truncated':
                raise ModelOutputTruncated('fixture truncated')
            money = [f['ref'] for f in catalog if f.get('type') == 'scalar'
                     and f.get('metric') == ['invoices', 'sum', 'amount_cents']]
            self.assertEqual(len(money), 2)
            return final(answer=[*money, {'op': 'subtract', 'left': money[1], 'right': money[0]}])
        agent = Agent('U001', self.book, model, mode='mock', trace_path=self.trace, max_requests=max_requests)
        with patch.object(runtime, 'handle_tool', wraps=runtime.handle_tool) as handler:
            answer = agent.ask('C001 2026年8月和9月，请查两个月发票金额、9月张数，并求9月减8月差额。')
            self.assertEqual(handler.call_count, 3, 'The correction must dispatch no further tools')
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no').fetchall(), before)
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0], 0)
        self.assertNotIn('已经保存全部修改', answer)
        self.assertEqual(agent.write_receipt['status'], 'NOT_SUBMITTED')
        self.assertFalse(agent.update_session.drafts)
        self.assertFalse(agent.update_session.confirmations)
        events = [json.loads(line) for line in self.trace.read_text(encoding='utf-8').splitlines()]
        return agent, answer, events, f"{Decimal(totals['2026-09']-totals['2026-08'])/100:.2f}"

    def test_three_tool_receipts_and_third_reply_can_use_existing_scheduler_extension(self):
        agent, answer, events, difference = self.run_case()
        self.assertEqual(len(self.seen), 4)
        self.assertEqual(self.seen[-1][1], [])
        self.assertEqual(agent.last_response['execution']['actual_tool_calls'], 3)
        self.assertEqual(agent.last_response['execution']['extensions'], 1)
        self.assertIn(difference, answer)
        self.assertIn('依据本轮两个父事实计算', answer)
        self.assertEqual(agent.last_response['delivery_source'], 'model_ordered_current_evidence')
        diagnostic = next(e['data'] for e in events if e['event'] == 'reply.references_repair_requested')
        self.assertTrue(any(i['reason'] == 'parent_type_mismatch' and i['actual_type'] == 'result'
                            for i in diagnostic['diagnostic']['issues']))

    def test_hard_max_three_never_sends_a_fourth_request(self):
        agent, _, events, _ = self.run_case(max_requests=3)
        self.assertEqual(len(self.seen), 3)
        self.assertEqual(agent.last_response['execution']['model_requests'], 3)
        self.assertEqual(agent.last_response['execution']['extensions'], 0)
        self.assertTrue(any(e['event'] == 'reply.references_not_repaired' for e in events))

    def test_second_invalid_answer_falls_back_without_repair_loop(self):
        agent, answer, events, _ = self.run_case('invalid')
        self.assertEqual(len(self.seen), 4)
        self.assertIn('未能完成最终事实引用', answer)
        self.assertNotEqual(agent.last_response.get('delivery_source'), 'model_ordered_current_evidence')
        self.assertEqual(sum(e['event'] == 'reply.references_repair_requested' for e in events), 1)

    def test_repair_tool_calls_are_paired_denied_and_never_dispatched(self):
        agent, _, _, _ = self.run_case('tools')
        self.assertEqual(len(self.seen), 4)
        denied = {m['tool_call_id']: json.loads(m['content']) for m in agent.messages
                  if m.get('tool_call_id') in {'forbidden-read', 'forbidden-write'}}
        self.assertEqual(set(denied), {'forbidden-read', 'forbidden-write'})
        self.assertTrue(all(value['status'] == 'DENIED' for value in denied.values()))

    def test_missing_reference_feedback_can_be_corrected_using_current_catalog(self):
        agent, answer, events, difference = self.run_case(missing=True)
        self.assertEqual(len(self.seen), 4)
        self.assertIn(difference, answer)
        diagnostic = next(e['data']['diagnostic'] for e in events if e['event'] == 'reply.references_repair_requested')
        self.assertTrue(any(i['reason'] == 'missing_reference' for i in diagnostic['issues']))

    def test_budget_refusal_during_correction_does_not_start_another_close_attempt(self):
        agent, _, events, _ = self.run_case('budget')
        self.assertEqual(len(self.seen), 4)
        self.assertEqual(agent.last_response['execution']['stop_reason'], 'REQUEST_BUDGET_EXCEEDED')
        self.assertFalse(any(e['event'] == 'budget.close_requested' for e in events))

    def test_truncated_correction_stops_and_preserves_actual_read_fallback(self):
        agent, answer, events, _ = self.run_case('truncated')
        self.assertEqual(len(self.seen), 4)
        self.assertEqual(agent.last_response['execution']['stop_reason'], 'OUTPUT_TRUNCATED')
        self.assertIn('未能完成最终事实引用', answer)
        self.assertTrue(any(e['event'] == 'reply.references_not_repaired' for e in events))
