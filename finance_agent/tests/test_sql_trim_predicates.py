"""Strict SQLite default text TRIM predicate attribution; no model or API."""
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from app.business_sql import BusinessSQL, TABLES
from app.cli_workspaces import import_workspace
from app.fact_arithmetic import basis, derive, sql_scalars
from app.provenance import ScopeProof
from app.sql_evidence import describe

# Exact SQL publicly disclosed after R4; fixture rows below are independent.
DISCLOSED_SQL = "SELECT substr(invoice_date,1,7) AS ym, COUNT(*) AS cnt, SUM(amount_cents) AS total_cents FROM invoices WHERE company_id='C001' AND invoice_date >= '2026-09-01' AND invoice_date < '2026-11-01' AND seller_name LIKE '%漫桥会展%' AND TRIM(purpose)='展会物料' GROUP BY ym ORDER BY ym"


class TrimPredicateEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.book = Path(temporary.name) / 'fictional.sqlite3'
        import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', self.book)
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute('DELETE FROM invoices')
            for number, company, day, seller, amount, purpose in (
                ('A1', 'C001', '2026-09-02', '漫桥会展服务有限公司', 100000, ' 展会物料 '),
                ('A2', 'C001', '2026-09-23', '漫桥会展服务有限公司', 79700, '展会物料'),
                ('B1', 'C001', '2026-10-03', '漫桥会展服务有限公司', 200000, '展会物料 '),
                ('B2', 'C001', '2026-10-24', '漫桥会展服务有限公司', 35700, ' 展会物料'),
                ('N1', 'C001', '2026-10-04', '其他销售方', 999999, '展会物料'),
                ('N2', 'C001', '2026-10-05', '漫桥会展服务有限公司', 999999, '\t展会物料\t'),
                ('N3', 'C001', '2026-11-01', '漫桥会展服务有限公司', 999999, '展会物料'),
                ('N4', 'C002', '2026-10-01', '漫桥会展服务有限公司', 999999, '展会物料'),
            ):
                db.execute('INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?)',
                           (company, number, day, seller, '虚构项目', amount, purpose, ''))
        scope = {'company_id': ['C001'], 'periods': [(2026, 9), (2026, 10)]}
        proof = ScopeProof('U001', scope, dict.fromkeys(scope, 'user_current'))
        self.workspace = BusinessSQL(self.book, 'U001', proof)
        self.addCleanup(self.workspace.close)

    def query(self, sql):
        snapshot, data, _ = self.workspace.query(sql)
        result = {'status': 'SUCCESS', 'data': data, 'evidence': {
            'source': 'current_sqlite', 'scope': snapshot, 'query_scope': data['query_scope']}}
        facts = {key: fact for key, (_, fact) in sql_scalars(result, 'original.sql.result', '授权范围').items()}
        return data, facts

    def test_disclosed_sql_unchanged_binds_real_monthly_scalar_parents(self):
        data, facts = self.query(DISCLOSED_SQL)
        self.assertEqual(data['rows'], [('2026-09', 2, 179700), ('2026-10', 2, 235700)])
        query = data['query_scope']
        self.assertEqual(query['status'], 'VERIFIED', query)
        self.assertEqual(query['scope'], {'company_ids': ('C001',), 'periods': ((2026, 9), (2026, 10))})
        condition, = [c for c in query['conditions'] if c['field'] == 'purpose']
        self.assertEqual(condition, {'field': 'purpose', 'transform': 'trim_ascii_space', 'operator': '=', 'value': '展会物料'})
        self.assertIn('trim_ascii_space', basis(query))
        self.assertEqual(len(facts), 4)
        for row, month, amount in ((0, 9, 179700), (1, 10, 235700)):
            count, money = facts[f'cell.{row}.1'], facts[f'cell.{row}.2']
            self.assertEqual((count['unit'], count['value'], count['metric']), ('count', 2, ('invoices', 'count_rows', None)))
            self.assertEqual((money['unit'], money['value'], money['metric']), ('cents', amount, ('invoices', 'sum', 'amount_cents')))
            self.assertEqual(money['scope']['periods'], ((2026, month),))
            self.assertEqual(money['parent_ref'], 'original.sql.result')
            self.assertEqual(money['basis'], basis(query))
        comparison = derive({'op': 'compare', 'left': 'cell.1.2', 'right': 'cell.0.2'}, facts)
        difference = derive({'op': 'subtract', 'left': 'cell.1.2', 'right': 'cell.0.2'}, facts)
        self.assertIn('560.00 元', comparison)
        self.assertIn('560.00 元', difference)
        self.assertIsNone(derive({'op': 'subtract', 'left': 'cell.1.2', 'right': 'cell.0.1'}, facts))
        # A result container cannot stand in for either scalar parent.
        self.assertIsNone(derive({'op': 'compare', 'left': 'whole', 'right': 'cell.0.2'}, {**facts, 'whole': {'type': 'result'}}))

    def test_actual_text_fields_and_aliases_have_explicit_default_transform(self):
        snapshot = {'company_ids': ('C001',), 'periods': ((2026, 9),)}
        for table, columns in (('invoices', ('seller_name', 'item_name', 'purpose', 'remark')),
                               ('bank_transactions', ('direction', 'counterparty_name', 'remark'))):
            for column in columns:
                with self.subTest(table=table, column=column):
                    query = describe(f"SELECT COUNT(*) AS n FROM {table} AS t WHERE TRIM(t.{column}) IN ('x','y')", ['n'], snapshot, TABLES, {table})
                    self.assertEqual(query['status'], 'VERIFIED', query)
                    self.assertEqual(query['conditions'], [{'field': column, 'transform': 'trim_ascii_space', 'operator': 'IN', 'value': ['x', 'y']}])

    def test_nondefault_or_nontext_transforms_do_not_acquire_evidence(self):
        for expression in ('TRIM(company_id)', 'TRIM(invoice_no)', 'TRIM(invoice_date)', 'TRIM(amount_cents)',
                           "TRIM(purpose,' ')", 'LTRIM(purpose)', 'RTRIM(purpose)', 'TRIM(TRIM(purpose))',
                           'TRIM(UPPER(purpose))', 'LOWER(purpose)', 'TRIM(purpose COLLATE NOCASE)',
                           'TRIM(other.purpose)'):
            with self.subTest(expression=expression):
                query = describe(f"SELECT COUNT(*) FROM invoices WHERE {expression}='x'", ['n'],
                                 {'company_ids': ('C001',), 'periods': ((2026, 9),)}, TABLES, {'invoices'})
                self.assertEqual(query['status'], 'UNKNOWN')
                self.assertIsNone(basis(query))
        for expression in ('TRIM(transaction_no)', 'TRIM(transaction_date)'):
            query = describe(f"SELECT COUNT(*) FROM bank_transactions WHERE {expression}='x'", ['n'],
                             {'company_ids': ('C001',), 'periods': ((2026, 9),)}, TABLES, {'bank_transactions'})
            self.assertEqual(query['status'], 'UNKNOWN')

    def test_trim_cohort_cannot_be_confused_with_raw_across_months(self):
        _, trimmed = self.query(DISCLOSED_SQL)
        _, raw = self.query(DISCLOSED_SQL.replace('TRIM(purpose)', 'purpose'))
        self.assertNotEqual(trimmed['cell.1.2']['basis'], raw['cell.0.2']['basis'])
        self.assertIsNone(derive({'op': 'compare', 'left': 'trimmed', 'right': 'raw'},
                                 {'trimmed': trimmed['cell.1.2'], 'raw': raw['cell.0.2']}))

    def test_count_alias_is_never_a_monetary_metric(self):
        data, facts = self.query("SELECT COUNT(*) AS amount_cents FROM invoices WHERE TRIM(purpose)='展会物料'")
        self.assertEqual(data['query_scope']['status'], 'VERIFIED')
        fact, = facts.values()
        self.assertEqual(fact['unit'], 'count')
        self.assertEqual(fact['metric'], ('invoices', 'count_rows', None))

    def test_projection_transform_remains_unsupported(self):
        data, facts = self.query('SELECT TRIM(purpose) FROM invoices')
        self.assertEqual(data['query_scope']['status'], 'UNKNOWN')
        self.assertFalse(facts)
