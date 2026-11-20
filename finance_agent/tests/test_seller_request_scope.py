"""User-grounded seller identity checks before SQL cards or scalar evidence."""
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from app.business_sql import BusinessSQL, BusinessSQLError, TABLES
from app.sql_evidence import describe
from app.fact_arithmetic import sql_scalars, derive
from app.cli_workspaces import import_workspace
from app.provenance import ScopeProof


class SellerRequestScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.book = Path(temporary.name) / 'fictional.sqlite'
        import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', self.book)
        self.target = '青屿会展有限公司'
        self.other = '青屿设备有限公司'
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute('DELETE FROM invoices')
            for no, seller, cents in [('A', self.target, 179700), ('B', self.other, 900000)]:
                db.execute('INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?)',
                           ('C001', no, '2026-09-02', seller, '虚构项目', cents, '物料', ''))
        self.values = {'company_id': ['C001'], 'periods': [(2026, 9)]}

    def workspace(self, request):
        proof = ScopeProof('U002', self.values, dict.fromkeys(self.values, 'user_current'))
        workspace = BusinessSQL(self.book, 'U002', proof, request=request)
        self.addCleanup(workspace.close)
        return workspace

    def binding(self, mode, quote, value):
        return {'company_id': 'C001', 'periods': [{'year': 2026, 'month': 9}],
                'company_quote': 'C001', 'period_quote': '2026年9月',
                'seller': {'mode': mode, 'quote': quote, 'value': value}}

    def test_full_identity_rejects_broad_sql_before_rows_exist(self):
        w = self.workspace('C001 2026年9月，仅查销售方青屿会展有限公司的物料发票金额和张数。')
        with self.assertRaises(BusinessSQLError) as caught:
            w.query("SELECT COUNT(*), SUM(amount_cents) FROM invoices WHERE seller_name LIKE '%青屿%'")
        self.assertEqual(caught.exception.status, 'SCOPE_MISMATCH')

    def test_full_identity_accepts_exact_and_equivalent_like(self):
        for condition in ("seller_name='青屿会展有限公司'", "seller_name LIKE '%青屿会展%'",
                          "TRIM(seller_name) IN ('青屿会展有限公司')"):
            with self.subTest(condition=condition):
                w = self.workspace('C001 2026年9月，查销售方青屿会展有限公司。')
                _, data, _ = w.query('SELECT COUNT(*), SUM(amount_cents) FROM invoices WHERE ' + condition)
                self.assertEqual(data['rows'], [(1, 179700)])
                self.assertEqual(data['query_scope']['seller_requirement']['names'], [self.target])

    def test_explicit_contains_source_allows_cross_seller_aggregation(self):
        quote = '销售方名称包含青屿的所有销售方'
        w = self.workspace('C001 2026年9月，汇总' + quote + '的发票。')
        w.bind_read_scope(self.binding('contains', quote, '青屿'))
        _, data, _ = w.query("SELECT COUNT(*), SUM(amount_cents) FROM invoices WHERE seller_name LIKE '%青屿%'")
        self.assertEqual(data['rows'], [(2, 1079700)])
        self.assertEqual(set(data['query_scope']['seller_requirement']['names']), {self.target, self.other})

    def test_short_single_name_cannot_select_one_of_two(self):
        w = self.workspace('C001 2026年9月，查销售方青屿的发票。')
        with self.assertRaises(BusinessSQLError) as caught:
            w.bind_read_scope(self.binding('single', '销售方青屿', '青屿'))
        self.assertEqual(caught.exception.status, 'AMBIGUOUS')
        self.assertIn(self.target, str(caught.exception))
        self.assertIn(self.other, str(caught.exception))

    def test_model_contains_cannot_override_full_identity(self):
        quote = '销售方青屿会展有限公司'
        w = self.workspace('C001 2026年9月，查' + quote + '。')
        with self.assertRaises(BusinessSQLError):
            w.bind_read_scope(self.binding('contains', quote, '青屿'))

    def test_sql_predicate_cannot_supply_its_own_user_requirement(self):
        w = self.workspace('C001 2026年9月，查青屿。')
        with self.assertRaises(BusinessSQLError) as caught:
            w.query("SELECT SUM(amount_cents) FROM invoices WHERE seller_name='青屿会展有限公司'")
        self.assertIn(self.target, str(caught.exception))
        self.assertIn(self.other, str(caught.exception))

    def test_direct_python_without_user_requirement_preserves_sql_attribution_interface(self):
        w = self.workspace(None)
        _, data, _ = w.query("SELECT COUNT(*) FROM invoices WHERE seller_name LIKE '%青屿%'")
        self.assertEqual(data['rows'], [(2,)])
        self.assertNotIn('seller_requirement', data['query_scope'])

    def test_unrelated_unknown_projection_does_not_create_a_seller_requirement(self):
        w = self.workspace('C001 2026年9月，请列出票号。')
        _, data, _ = w.query('SELECT * FROM invoices WHERE 1=1')
        self.assertEqual(len(data['rows']), 2)
        self.assertNotIn('seller_requirement', data['query_scope'])

    def test_bank_query_stays_separate_from_invoice_seller_condition(self):
        w = self.workspace('C001 2026年9月，查青屿会展有限公司发票，另查银行流水。')
        _, data, _ = w.query('SELECT COUNT(*) FROM bank_transactions')
        self.assertEqual(len(data['rows']), 1)

    def test_missing_seller_predicate_is_not_target_total(self):
        w = self.workspace('C001 2026年9月，查青屿会展有限公司。')
        with self.assertRaises(BusinessSQLError):
            w.query('SELECT COUNT(*), SUM(amount_cents) FROM invoices')

    def test_same_date_target_disjunction_delivers_period_scalars_and_difference(self):
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute('INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?)',
                       ('C001', 'C', '2026-10-04', self.target, '虚构项目', 235700, '物料', ''))
        self.values['periods'].append((2026, 10))
        w = self.workspace('C001 2026年9月和10月，比较青屿会展有限公司金额和张数。')
        sql = ("SELECT substr(invoice_date,1,7) AS ym,COUNT(*) AS n,SUM(amount_cents) AS cents "
               "FROM invoices WHERE seller_name='青屿会展有限公司' AND "
               "(substr(invoice_date,1,7)='2026-09' OR substr(invoice_date,1,7)='2026-10') "
               "GROUP BY ym ORDER BY ym")
        scope, data, _ = w.query(sql)
        self.assertEqual(data['rows'], [('2026-09', 1, 179700), ('2026-10', 1, 235700)])
        result = {'status': 'SUCCESS', 'data': data, 'evidence': {
            'source': 'current_sqlite', 'scope': scope, 'query_scope': data['query_scope']}}
        facts = {key: fact for key, (_, fact) in sql_scalars(result, 'sql.result', '本轮') .items()}
        difference = derive({'op': 'subtract', 'left': 'cell.1.2', 'right': 'cell.0.2'}, facts)
        self.assertIn('560.00 元', difference)

    def test_disjunction_cannot_weaken_full_seller_identity(self):
        w = self.workspace('C001 2026年9月，查青屿会展有限公司。')
        with self.assertRaises(BusinessSQLError) as caught:
            w.query("SELECT SUM(amount_cents) FROM invoices WHERE "
                    "seller_name='青屿会展有限公司' OR seller_name='青屿设备有限公司'")
        self.assertEqual(caught.exception.status, 'SCOPE_MISMATCH')

    def test_only_identical_target_equality_unions_gain_attribution(self):
        snapshot = {'company_ids': ('C001',), 'periods': ((2026, 9), (2026, 10))}
        for condition in (
            "(seller_name='a' OR (seller_name IN ('b','c') OR seller_name='a'))",
            "(TRIM(seller_name)='a' OR TRIM(seller_name)='b')",
        ):
            with self.subTest(condition=condition):
                q = describe('SELECT COUNT(*) FROM invoices WHERE '+condition, ['n'], snapshot, TABLES, {'invoices'})
                self.assertEqual(q['status'], 'VERIFIED', q)
                self.assertEqual(len(q['conditions']), 1)
                self.assertEqual(q['conditions'][0]['operator'], 'IN')
        for condition in (
            "seller_name='a' OR purpose='b'",
            "seller_name='a' OR TRIM(seller_name)='b'",
            "seller_name='a' OR seller_name LIKE '%b%'",
            "seller_name='a' OR (seller_name='b' AND purpose='x')",
            "substr(invoice_date,1,7)='2026-09' OR substr(invoice_date,1,4)='2026'",
        ):
            with self.subTest(condition=condition):
                q = describe('SELECT COUNT(*) FROM invoices WHERE '+condition, ['n'], snapshot, TABLES, {'invoices'})
                self.assertEqual(q['status'], 'UNKNOWN', q)


if __name__ == '__main__':
    unittest.main()
