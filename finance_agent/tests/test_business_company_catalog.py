"""Company identity does not depend on financial-period enumeration; zero API."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from app.agent import Agent, scripted_model
from app.business_object_sources import amendment_sources
from app.cli_workspaces import import_workspace
from app.stage2_schema import open_existing
from tests.test_tui_p0 import FIXTURE, FINAL, tool


class BusinessCompanyCatalogTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.book = self.root / 'fictional.sqlite3'
        import_workspace(FIXTURE, self.book)

    def test_company_source_survives_missing_bank_table_and_real_query_returns_error(self):
        with closing(open_existing(self.book)) as db, db:
            db.execute('DROP TABLE bank_transactions')
        current, _, _ = amendment_sources('甲企业2026年金额', None, actor='U001', book=self.book)
        self.assertEqual(current['company_id'], ['C001'])
        agent = Agent('U001', self.book, scripted_model([
            tool('get_annual_finance_summary', {'company_id':'C001', 'year':2026}), FINAL]), mode='mock')
        answer = agent.ask('查甲企业2026年金额。')
        outcome = agent.last_response['tool_results'][0][1]
        self.assertEqual((outcome['status'], outcome['data']), ('ERROR', None))
        self.assertNotIn('0.00', answer)

    def test_identity_catalog_uses_read_acl_without_period_or_invoice_tables(self):
        from app.business_object_sources import readable_companies
        with closing(open_existing(self.book)) as db, db:
            db.execute('DROP TABLE bank_transactions')
            db.execute('DROP TABLE invoices')
        companies = readable_companies(self.book, 'U002')
        self.assertEqual([company['company_id'] for company in companies], ['C001'])
        self.assertEqual(set(companies[0]), {'company_id', 'name', 'short_name'})

    def test_broken_identity_catalog_raises_instead_of_claiming_empty_directory(self):
        from app.business_object_sources import readable_companies
        missing = self.root / 'missing.sqlite3'
        with self.assertRaises(sqlite3.OperationalError):
            readable_companies(missing, 'U001')
        self.assertFalse(missing.exists())
        # Deliberately corrupt only this temporary fixture's identity schema.
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute('DROP TABLE companies')
        with self.assertRaises(sqlite3.OperationalError):
            readable_companies(self.book, 'U001')


if __name__ == '__main__':
    unittest.main()
