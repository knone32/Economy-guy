"""Optional read metadata cannot erase or invent a trusted current year."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.business_sql import BusinessSQL, BusinessSQLError
from app.cli_workspaces import import_workspace
from app.provenance import ScopeProof


class TrustedYearReadScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.book = Path(temporary.name) / 'fictional.sqlite'
        import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', self.book)
        self.binding = {'company_id': 'C001', 'periods': [{'year': 2026, 'month': 9}],
                        'company_quote': '甲企业', 'period_quote': '九月'}

    def workspace(self, values, sources, *, actor='U001'):
        workspace = BusinessSQL(self.book, actor, ScopeProof(actor, values, sources),
                                request='先看看甲企业九月的发票用途。')
        self.addCleanup(workspace.close)
        return workspace

    def test_redundant_sidecar_retains_existing_verified_year_and_identical_rows(self):
        values = {'company_id': ['C001'], 'periods': [(2026, 9)], 'year': [2026], 'month': [9]}
        workspace = self.workspace(values, dict.fromkeys(values, 'current_sqlite'))
        original_scope, original, _ = workspace.query('SELECT invoice_no, purpose FROM invoices ORDER BY invoice_no')
        workspace.bind_read_scope(self.binding)
        scope, actual, _ = workspace.query('SELECT invoice_no, purpose FROM invoices ORDER BY invoice_no')
        self.assertEqual(scope, original_scope)
        self.assertEqual(actual['rows'], original['rows'])
        self.assertTrue(actual['rows'])
        self.assertTrue(all(source == 'controlled_read_scope' for source in workspace.proof.sources.values()))

    def test_catalog_alone_does_not_supply_the_missing_year(self):
        workspace = self.workspace({'company_id': ['C001']}, {'company_id': 'user_current'})
        with self.assertRaises(BusinessSQLError) as raised:
            workspace.bind_read_scope(self.binding)
        self.assertEqual(raised.exception.status, 'AMBIGUOUS')

    def test_unverified_source_year_does_not_become_trusted(self):
        values = {'company_id': ['C001'], 'periods': [(2026, 9)]}
        workspace = self.workspace(values, {'company_id': 'user_current', 'periods': 'model_claimed'})
        with self.assertRaises(BusinessSQLError):
            workspace.bind_read_scope(self.binding)

    def test_multiple_trusted_years_do_not_choose_a_year_from_catalog(self):
        values = {'company_id': ['C001'], 'periods': [(2026, 9), (2027, 9)]}
        workspace = self.workspace(values, dict.fromkeys(values, 'user_current'))
        with self.assertRaises(BusinessSQLError) as raised:
            workspace.bind_read_scope(self.binding)
        self.assertEqual(raised.exception.status, 'AMBIGUOUS')

    def test_changed_target_or_explicit_year_conflict_remains_rejected(self):
        values = {'company_id': ['C001'], 'periods': [(2026, 9)]}
        workspace = self.workspace(values, dict.fromkeys(values, 'current_sqlite'))
        for binding in (
            {**self.binding, 'periods': [{'year': 2025, 'month': 9}]},
            {**self.binding, 'company_id': 'C002'},
        ):
            with self.subTest(binding=binding), self.assertRaises(BusinessSQLError):
                workspace.bind_read_scope(binding)


if __name__ == '__main__':
    unittest.main()
