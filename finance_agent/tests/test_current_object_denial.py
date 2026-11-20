"""Explicit unreadable objects veto fallback; zero API, fictional workbooks."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.agent import Agent, scripted_model
from app.business_object_sources import unreadable_company_mentions
from app.cli_workspaces import import_workspace
from app.stage2_schema import open_existing
from tests.test_sql_invoice_selection import snapshot
from tests.test_tui_p0 import FIXTURE, FINAL, tool


class CurrentObjectDenialTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.book = self.root / 'fictional.sqlite3'
        import_workspace(FIXTURE, self.book)
        with closing(open_existing(self.book)) as db, db:
            db.execute("UPDATE companies SET name='北湾数据中心',short_name='北湾' WHERE company_id='C002'")
        self.before = snapshot(self.book)

    def tearDown(self):
        self.assertEqual(snapshot(self.book), self.before)

    def test_missing_period_unreadable_summary_is_denied_before_model(self):
        for quote in ('C002', '北湾', '北湾数据中心'):
            with self.subTest(quote=quote):
                agent = Agent('U002', self.book, lambda *_: self.fail('No model before denied summary'), mode='mock')
                answer = agent.ask(f'查询{quote}的发票价税合计 银行收入和支出 并且说明统计依据',
                                   read_workspace=('C001', 2026, 9))
                self.assertEqual(agent.last_response['execution']['stop_reason'], 'DENIED')
                self.assertEqual(agent.last_response['execution']['model_requests'], 0)
                self.assertIn('权限', answer)
                self.assertIsNone(agent.pending_intent)

    def test_current_unreadable_company_cannot_fall_back_to_selected_company(self):
        for quote in ('C002', '北湾', '北湾数据中心'):
            for target in ('C001', 'C002'):
                with self.subTest(quote=quote, target=target):
                    agent = Agent('U002', self.book, scripted_model([
                        tool('get_finance_summary', {'company_id':target, 'year':2026, 'month':9}), FINAL]), mode='mock')
                    answer = agent.ask(f'查询{quote}的发票价税合计、银行收入和支出，2026年9月。',
                                       read_workspace=('C001', 2026, 9))
                    self.assertEqual(agent.last_response['execution']['stop_reason'], 'DENIED')
                    self.assertFalse(any(result['status'] == 'SUCCESS' for _, result in agent.last_response['tool_results']))
                    self.assertNotIn('9622.06', answer)

    def test_denied_analysis_neither_builds_fallback_snapshot_nor_executes_sql(self):
        sql = "SELECT COUNT(*) AS cnt FROM invoices WHERE company_id='C001'"
        agent = Agent('U002', self.book, scripted_model([tool('query_business_sql', {'sql':sql}), FINAL]), mode='mock')
        with patch('app.agent.BusinessSQL', side_effect=AssertionError('No fallback snapshot')):
            answer = agent.ask('分析北湾2026年9月的发票张数，说明数据来源。', read_workspace=('C001', 2026, 9))
        self.assertEqual(agent.last_response['tool_results'][0][1]['status'], 'DENIED')
        self.assertIn('权限', answer)
        self.assertNotIn('0 张', answer)

    def test_quote_constraints_are_internal_and_invisible_namesakes_do_not_deny_readable_names(self):
        text = '背景是“北湾F001”，当前只查甲企业。'
        self.assertEqual(unreadable_company_mentions(text, actor='U002', book=self.book), [])
        self.assertTrue(unreadable_company_mentions(text, actor='U002', book=self.book, include_quoted=True))
        with closing(open_existing(self.book)) as db, db:
            db.execute("UPDATE companies SET short_name='甲企业' WHERE company_id='C002'")
        self.assertEqual(unreadable_company_mentions('甲企业', actor='U002', book=self.book), [])

    def test_unknown_canonical_company_cannot_fall_back_to_a_selected_company(self):
        for identifier in ('C998', 'C999'):
            with self.subTest(identifier=identifier):
                agent = Agent('U002', self.book, scripted_model([
                    tool('get_finance_summary', {'company_id':'C001', 'year':2026, 'month':9}), FINAL]), mode='mock')
                answer = agent.ask(f'查询{identifier} 2026年9月的发票及银行收支。', read_workspace=('C001', 2026, 9))
                self.assertEqual(agent.last_response['execution']['stop_reason'], 'SCOPE_MISMATCH')
                self.assertFalse(any(r['status'] == 'SUCCESS' for _, r in agent.last_response['tool_results']))
                self.assertNotIn('9622.06', answer)


if __name__ == '__main__':
    unittest.main()
