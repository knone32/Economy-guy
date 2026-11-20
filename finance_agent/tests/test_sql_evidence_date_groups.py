"""Date grouping evidence against independent fictional SQLite rows; no model/API."""
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from app.business_sql import BusinessSQL
from app.cli_workspaces import import_workspace
from app.fact_arithmetic import derive, sql_scalars
from app.provenance import ScopeProof


class DateGroupEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.book = Path(temporary.name) / 'fictional.sqlite3'
        import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', self.book)
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute('DELETE FROM invoices')
            for number, company, day, amount in (
                ('A1', 'C001', '2038-11-01', 12345),
                ('A2', 'C001', '2038-11-20', -345),
                ('A3', 'C001', '2038-12-01', 25000),
                ('B1', 'C002', '2038-11-02', 7000),
                ('B2', 'C002', '2038-12-11', -500),
            ):
                db.execute('INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?)',
                           (company, number, day, 'fictional', 'fictional', amount, '', ''))
        scope = {'company_id': ['C001', 'C002']}
        proof = ScopeProof('U001', scope, dict.fromkeys(scope, 'user_current'), annual_year=2038)
        self.workspace = BusinessSQL(self.book, 'U001', proof)
        self.addCleanup(self.workspace.close)

    def query(self, sql):
        snapshot, data, _ = self.workspace.query(sql)
        result = {'status': 'SUCCESS', 'data': data, 'evidence': {
            'source': 'current_sqlite', 'scope': snapshot, 'query_scope': data['query_scope']}}
        return data, {key: fact for key, (_, fact) in sql_scalars(result, 'parent', '授权三个月').items()}

    def test_month_group_expression_alias_and_ordinal_have_same_real_amounts(self):
        with closing(sqlite3.connect(self.book)) as db:
            truth = dict(db.execute('SELECT company_id || substr(invoice_date,1,7), SUM(amount_cents) '
                                    'FROM invoices GROUP BY company_id, substr(invoice_date,1,7)'))
        for group in ('company_id, substr(invoice_date,1,7)', 'company_id, period', '1, 2'):
            with self.subTest(group=group):
                data, facts = self.query('SELECT company_id, substr(invoice_date,1,7) AS period, '
                                        'SUM(amount_cents) AS total FROM invoices GROUP BY ' + group)
                self.assertEqual(data['query_scope']['status'], 'VERIFIED', data['query_scope'])
                self.assertEqual(len(facts), 4)
                actual = {}
                for fact in facts.values():
                    dimensions = fact['dimensions']
                    company, period = dimensions['company_id'], dimensions['invoice_date_month']
                    actual[company + period] = fact['value']
                    self.assertEqual(fact['scope']['company_ids'], (company,))
                    self.assertEqual(fact['scope']['periods'], ((2038, int(period[-2:])),))
                    self.assertEqual(fact['metric'], ('invoices', 'sum', 'amount_cents'))
                    self.assertEqual(fact['unit'], 'cents')
                    self.assertIn(period, fact['scope_text'])
                self.assertEqual(actual, truth)
                self.assertFalse(any('2038-10' in f['dimensions'].values() for f in facts.values()))

    def test_month_facts_can_compare_with_direction_and_exact_difference(self):
        _, facts = self.query("SELECT substr(invoice_date,1,7) AS period, SUM(amount_cents) AS total "
                              "FROM invoices WHERE company_id='C001' GROUP BY period ORDER BY period")
        left, right = facts
        text = derive({'op': 'compare', 'left': left, 'right': right}, facts)
        self.assertIsNotNone(text)
        self.assertIn('2038-11', text)
        self.assertIn('2038-12', text)
        self.assertIn('高于', text)
        self.assertIn('130.00 元', text)

    def test_year_group_keeps_only_authorized_months(self):
        scope = {'company_id': ['C001'], 'periods': [(2038, 10), (2038, 11), (2038, 12)]}
        self.workspace = BusinessSQL(self.book, 'U001', ScopeProof('U001', scope, dict.fromkeys(scope, 'user_current')))
        self.addCleanup(self.workspace.close)
        data, facts = self.query('SELECT substring(invoice_date,1,4) AS yr, SUM(amount_cents) AS total '
                                 'FROM invoices GROUP BY yr')
        self.assertEqual(data['query_scope']['status'], 'VERIFIED')
        fact, = facts.values()
        self.assertEqual(fact['value'], 37000)
        self.assertEqual(fact['dimensions']['invoice_date_year'], '2038')
        self.assertEqual(fact['scope']['periods'], ((2038, 10), (2038, 11), (2038, 12)))

    def test_unsupported_or_ungrouped_date_shapes_do_not_gain_metric_evidence(self):
        for projection, group in (
            ('substr(invoice_date,2,7)', '1'),
            ('substr(invoice_date,1,2)', '1'),
            ('substr(seller_name,1,7)', '1'),
            ('substr(invoice_date,1,7)', ''),
            ('substr(invoice_date,1,7)', 'company_id'),
            ('substr(invoice_date,1,7)', 'substr(invoice_date,1,4)'),
        ):
            with self.subTest(projection=projection, group=group):
                sql = f'SELECT {projection} AS period, SUM(amount_cents) AS total FROM invoices'
                data, facts = self.query(sql + (' GROUP BY ' + group if group else ''))
                self.assertEqual(data['query_scope']['status'], 'UNKNOWN')
                self.assertFalse(facts)

    def test_pagination_and_unknown_alias_never_create_complete_scalar_facts(self):
        data, facts = self.query('SELECT substr(invoice_date,1,7) AS period, SUM(amount_cents) AS total '
                                 'FROM invoices GROUP BY period LIMIT 1')
        self.assertEqual(data['query_scope']['status'], 'VERIFIED')
        self.assertFalse(data['query_scope']['query_set_complete'])
        self.assertFalse(facts)

    def test_source_field_precedes_conflicting_group_alias(self):
        data, facts = self.query('SELECT substr(invoice_date,1,7) AS company_id, SUM(amount_cents) AS total '
                                 'FROM invoices GROUP BY company_id')
        self.assertEqual(data['query_scope']['status'], 'UNKNOWN')
        self.assertFalse(facts)

    def test_date_bucket_does_not_relabel_count_as_money(self):
        _, facts = self.query('SELECT substr(invoice_date,1,7) AS period, COUNT(*) AS invoice_amount '
                              'FROM invoices GROUP BY period ORDER BY period')
        self.assertEqual([f['value'] for f in facts.values()], [3, 2])
        self.assertTrue(all(f['unit'] == 'count' for f in facts.values()))
        self.assertTrue(all(f['metric'] == ('invoices', 'count_rows', None) for f in facts.values()))

    def test_bank_transaction_dates_use_the_same_proven_group_path(self):
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute('DELETE FROM bank_transactions')
            for number, day, amount in (('TX1', '2038-11-02', 4000), ('TX2', '2038-12-02', -800)):
                db.execute('INSERT INTO bank_transactions VALUES (?,?,?,?,?,?,?)',
                           ('C001', number, day, '收入', amount, 'fictional', ''))
        data, facts = self.query("SELECT substr(transaction_date,1,7) AS period, SUM(amount_cents) AS total "
                                 "FROM bank_transactions WHERE company_id='C001' AND direction='收入' GROUP BY 1")
        self.assertEqual(data['query_scope']['status'], 'VERIFIED')
        self.assertEqual({f['dimensions']['transaction_date_month']: f['value'] for f in facts.values()},
                         {'2038-11': 4000, '2038-12': -800})
        self.assertTrue(all(f['metric'] == ('bank_transactions', 'sum', 'amount_cents') for f in facts.values()))
        # A grouping projection cannot use the other business object's date.
        self.assertEqual(data['query_scope']['columns'][0]['field'], 'transaction_date')

    def test_agent_entry_delivers_grouped_amounts_and_comparison(self):
        from app.agent import Agent
        from tests.test_answer_evidence import tool, final, facts
        calls = 0

        def model(messages, tools):
            nonlocal calls
            calls += 1
            if calls == 1:
                return tool('query_business_sql', sql=(
                    "SELECT substr(invoice_date,1,7) AS period, SUM(amount_cents) AS total "
                    "FROM invoices WHERE company_id='C001' GROUP BY period ORDER BY period"))
            amounts = [f['ref'] for f in facts(messages) if f.get('metric') == ['invoices', 'sum', 'amount_cents']]
            self.assertEqual(len(amounts), 2)
            return final(answer=[*amounts, {'op': 'compare', 'left': amounts[0], 'right': amounts[1]}])

        agent = Agent('U001', self.book, model, mode='mock', trace_path=self.book.with_suffix('.jsonl'))
        answer = agent.ask('C001 2038年全年发票按月合计金额，并比较11月与12月金额差额。')
        self.assertEqual(calls, 2)
        self.assertIn('120.00 元', answer)
        self.assertIn('250.00 元', answer)
        self.assertIn('130.00 元', answer)
        self.assertIn('2038-11', answer)
        self.assertIn('2038-12', answer)
        self.assertEqual(agent.last_response['delivery_source'], 'model_ordered_current_evidence')
