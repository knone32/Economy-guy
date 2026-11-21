"""Finite SQL equivalents retain independent request and result checks."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from app.business_request import bind
from app.business_request_delivery import accept_result, assess_results, RequestDeliveryError
from app.business_sql import BusinessSQL, TABLES
from app.cli_workspaces import import_workspace
from app.provenance import ScopeProof
from app.sql_evidence import describe


class SQLPredicateEquivalenceTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.book = Path(temp.name) / 'fictional.sqlite'
        import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', self.book)
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute('DELETE FROM invoices')
            for no, amount, purpose in [('A', 12345, '校准服务'), ('B', 99800, '校准服务'),
                                        ('C', 800000, '其他用途'), ('D', 910000, '  ')]:
                db.execute('INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?)',
                    ('C001', no, '2026-09-03', '测试销售方', '项目', amount, purpose, ''))
        text = '查C001 2026年9月发票，用途为校准服务的金额合计。'
        target = {'target_id':'i', 'object':'invoices', 'company_ids':['C001'],
            'company_quote':'C001', 'periods':[[2026,9]], 'period_quote':'2026年9月',
            'seller':{'mode':'none','value':'','quote':'发票'},
            'filters':[{'field':'purpose','operator':'=','value':'校准服务','quote':'用途为校准服务'}],
            'metrics':[{'operation':'sum','field':'amount_cents','quote':'金额合计'}]}
        self.request = bind(json.dumps({'kind':'read','targets':[target],'unresolved':[]},ensure_ascii=False),
            actor='U002',book=self.book,turn_id='finite-equivalence',request=text)
        self.where = "FROM invoices WHERE company_id='C001' AND invoice_date LIKE '2026-09%'"

    def result(self, sql):
        values = {'company_id':['C001'], 'periods':[(2026,9)]}
        with closing(BusinessSQL(self.book,'U002',ScopeProof('U002',values,
                dict.fromkeys(values,'user_current')))) as work:
            work.business_request = self.request
            scope, data, _ = work.query(sql)
        return {'ok':True,'status':'SUCCESS','data':data,'evidence':{
            'source':'current_sqlite','scope':scope,'query_scope':data.pop('query_scope')}}

    def test_original_shape_delivers_requested_sum_without_extra_count(self):
        sql = ('SELECT company_id, COUNT(*) AS n, SUM(amount_cents) AS cents ' + self.where
               + " AND is_blank(purpose)=0 AND purpose='校准服务'")
        original = self.result(sql)
        accepted = accept_result(self.request,'query_business_sql',original,'U002',self.book)
        self.assertEqual(accepted['data']['rows'], [('C001',112145)])
        self.assertEqual(accepted['data']['sql'], sql)
        self.assertEqual(original['data']['columns'], ['company_id','n','cents'])
        self.assertTrue(assess_results(self.request,[('query_business_sql',accepted)])['complete'])

    def test_boolean_comparisons_normalize_only_exact_zero_or_one(self):
        snapshot={'company_ids':('C001',),'periods':((2026,9),)}
        for expression, expected in [('is_blank(purpose)=0',False),('0=is_blank(purpose)',False),
                ('is_blank(purpose)!=1',False),('is_blank(purpose)=1',True),('1=is_blank(purpose)',True)]:
            with self.subTest(expression=expression):
                evidence=describe('SELECT COUNT(*) AS n '+self.where+' AND '+expression,
                    ['n'],snapshot,TABLES,{'invoices'})
                self.assertEqual(evidence['status'],'VERIFIED',evidence)
                self.assertIn({'field':'purpose','operator':'is_blank','value':expected},evidence['conditions'])
        for expression in ('is_blank(purpose)=2',"is_blank(purpose)='0'"):
            self.assertEqual(describe('SELECT COUNT(*) AS n '+self.where+' AND '+expression,
                ['n'],snapshot,TABLES,{'invoices'})['status'],'UNKNOWN')

    def test_unconstrained_bare_dimension_stays_unproved(self):
        query=self.result('SELECT seller_name,SUM(amount_cents) AS cents '+self.where
                          + " AND purpose='校准服务'")['evidence']['query_scope']
        self.assertEqual(query['status'],'UNKNOWN')
        self.assertEqual(query['reason'],'ungrouped_column')

    def test_redundancy_does_not_erase_real_filter_changes_or_contradictions(self):
        for tail in (" AND is_blank(purpose)=1 AND purpose='校准服务'",
                     " AND is_blank(purpose)=0", " AND purpose='校准服务' AND amount_cents>50000"):
            with self.subTest(tail=tail),self.assertRaises(RequestDeliveryError):
                accept_result(self.request,'query_business_sql',self.result(
                    'SELECT SUM(amount_cents) AS cents '+self.where+tail),'U002',self.book)

    def test_empty_aggregate_bare_dimension_does_not_invent_group_identity(self):
        result=self.result('SELECT company_id,COUNT(*) AS n,SUM(amount_cents) AS cents '+self.where
            + " AND purpose='校准服务' AND invoice_no='ABSENT'")
        with self.assertRaises(RequestDeliveryError):
            accept_result(self.request,'query_business_sql',result,'U002',self.book)

    def test_blank_condition_rendering_keeps_verified_boolean_direction(self):
        from app.responses import render_query_conditions
        for value, expected in ((False,'用途已填写'), (True,'用途未填写'), ('','用途未填写')):
            self.assertEqual(render_query_conditions({'conditions':[
                {'field':'purpose','operator':'is_blank','value':value}]}), expected)
        self.assertNotIn('用途未填写',render_query_conditions({'conditions':[
            {'field':'purpose','operator':'is_blank','value':'unproved'}]}))


if __name__=='__main__':
    unittest.main()
