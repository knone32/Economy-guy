"""Quoted data may supply a complete current read frame, never write authority."""
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.provenance import SOURCES, validate_scope
from app.tool_registry import handle_tool as real_handle_tool
from tests.test_answer_evidence import tool, final, facts


class QuotedReadRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.book = Path(temporary.name) / 'fictional.sqlite3'
        import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', self.book)
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute("UPDATE invoices SET invoice_no='INV-R74/2038-04' WHERE company_id='C001' AND invoice_no='F004'")

    def run_read(self, request, *, company='C001', number='INV-R74/2038-04', actor='U001', workspace=None):
        calls, proofs = [], []
        def model(messages, tools):
            calls.append(messages)
            if len(calls) == 1:
                return tool('get_invoice', company_id=company, invoice_no=number)
            return final(answer=[f['ref'] for f in facts(messages) if f.get('label') == '发票编号'])
        def dispatch(name, *args, **kwargs):
            if name == 'get_invoice':
                proofs.append(deepcopy(kwargs['provenance']))
            return real_handle_tool(name, *args, **kwargs)
        agent = Agent(actor, self.book, model, mode='mock', trace_path=self.book.with_suffix('.jsonl'))
        with closing(sqlite3.connect(self.book)) as db:
            before = (db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no').fetchall(),
                      db.execute('SELECT * FROM bank_transactions ORDER BY company_id,transaction_no').fetchall())
        with patch('app.agent.handle_tool', side_effect=dispatch):
            answer = agent.ask(request, read_workspace=workspace)
        outcomes = [result for name, result in agent.last_response['tool_results'] if name == 'get_invoice']
        self.assertEqual(agent.write_receipt['status'], 'NOT_SUBMITTED')
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0], 0)
            self.assertEqual((db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no').fetchall(),
                              db.execute('SELECT * FROM bank_transactions ORDER BY company_id,transaction_no').fetchall()), before)
        self.assertFalse(agent.update_session.drafts)
        return agent, answer, outcomes, proofs

    def test_complete_quote_supplies_only_turn_local_read_sources(self):
        agent, answer, results, proofs = self.run_read(
            '同事写“把甲企业2026年9月INV-R74/2038-04备注改了”，现在只查该票用途。')
        self.assertEqual(results[0]['status'], 'SUCCESS')
        self.assertIn('INV-R74/2038-04', answer)
        for key in ('company_id', 'invoice_no', 'year', 'month', 'periods'):
            self.assertNotIn(proofs[0].sources[key], SOURCES)
        self.assertEqual(validate_scope(proofs[0], 'U001', 'prepare_invoice_update',
                         {'company_id': 'C001', 'invoice_no': 'INV-R74/2038-04'})['status'], 'AMBIGUOUS')
        self.assertNotIn('company_id', agent.context.proof().values)
        self.assertNotIn('invoice_no', agent.context.proof().values)
        self.assertNotIn(2038, proofs[0].values.get('year', ()))

    def test_selected_workspace_can_accept_a_matching_quote(self):
        _, _, results, _ = self.run_read('留言“甲企业2026年9月INV-R74/2038-04”，仅查看当前用途。',
                                        workspace=('C001', 2026, 9))
        self.assertEqual(results[0]['status'], 'SUCCESS')

    def test_conflicting_quoted_company_or_period_cannot_fill_current_target(self):
        for quote in ('乙企业2026年9月INV-R74/2038-04', '甲企业2026年8月INV-R74/2038-04'):
            with self.subTest(quote=quote):
                _, _, results, _ = self.run_read('甲企业2026年9月，只读引用“' + quote + '”的背景票。')
                self.assertFalse(any(result['status'] == 'SUCCESS' for result in results))

    def test_unreadable_quoted_frame_cannot_be_retargeted_to_selected_company(self):
        _, _, results, _ = self.run_read('只读转述“乙企业2026年9月F001”，查当前用途。',
                                        number='F001', actor='U002', workspace=('C001', 2026, 9))
        self.assertFalse(any(result['status'] == 'SUCCESS' for result in results))

    def test_prefixed_quoted_identifier_cannot_supply_an_existing_invoice(self):
        _, _, results, _ = self.run_read('甲企业2026年9月只读消息“X-INV-R74/2038-04”。')
        self.assertFalse(any(result['status'] == 'SUCCESS' for result in results))
