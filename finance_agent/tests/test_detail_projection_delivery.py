"""Raw detail facts survive a dispensable scalar display expression."""
from contextlib import closing
import json
import sqlite3
import unittest
from tests import test_business_request_delivery as fixtures
from app.tool_registry import handle_tool
from app.provenance import ScopeProof
from app.business_sql import BusinessSQL
from app.answer_evidence import catalog
from app.business_request_delivery import assess_selection


class DetailProjectionDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BusinessRequestDeliveryTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.book=self.fixture.book
        target=self.fixture.target.copy()
        target.update(metrics=[{'operation':'details','field':'*','quote':'发票明细'}],group_by=[])
        self.request=self.fixture.requirement(target,self.fixture.text.replace('发票金额与张数','发票明细'))
        self.proof=ScopeProof('U002',{'company_id':['C001'],'periods':[(2026,9),(2026,10)]},
                              {'company_id':'user_current','periods':'user_current'})

    def execute(self,where="seller_name='玄野服务有限公司' AND purpose='展会物料'",expression='ROUND(amount_cents/100.0,2)'):
        sql=f'SELECT *,{expression} AS display_amount FROM invoices WHERE {where} ORDER BY invoice_no'
        with closing(BusinessSQL(self.book,'U002',self.proof)) as workspace:
            result=handle_tool('query_business_sql',json.dumps({'sql':sql}), 'U002',self.book,
                               business_request=self.request,provenance=self.proof,sql_workspace=workspace)
        return sql,result

    def test_detail_keeps_original_rows_and_only_proven_columns(self):
        sql,result=self.execute()
        self.assertEqual(result['status'],'SUCCESS',result)
        self.assertEqual(result['data']['sql'],sql)
        self.assertNotIn('display_amount',result['data']['columns'])
        with closing(sqlite3.connect(self.book)) as db:
            truth=db.execute("SELECT * FROM invoices WHERE seller_name='玄野服务有限公司' AND purpose='展会物料' ORDER BY invoice_no").fetchall()
        self.assertEqual(list(map(tuple,result['data']['rows'])),truth)
        self.assertEqual(result['evidence']['query_scope']['row_shape'],'detail')
        projection=result['data']['request_projection']
        self.assertFalse(projection['source_projection_complete'])
        self.assertEqual(projection['source_column_indices'],list(range(8)))
        facts=catalog([('query_business_sql',result)],{},'detail-turn')
        result_ref=next(ref for ref,fact in facts.items() if fact['type']=='result')
        self.assertTrue(assess_selection(self.request,[result_ref],facts,[('query_business_sql',result)])['complete'])
        self.assertFalse(assess_selection(self.request,[],facts,[('query_business_sql',result)])['complete'])
        self.assertFalse(any(f.get('type')=='scalar' for f in facts.values()))

    def test_dropping_display_column_cannot_hide_broadened_seller_scope(self):
        _,result=self.execute("seller_name LIKE '%玄野%' AND purpose='展会物料'")
        self.assertNotEqual(result['status'],'SUCCESS')
        self.assertIsNone(result['data'])

    def test_unknown_row_effect_is_not_a_discardable_display_column(self):
        for expression in ('SUM(amount_cents)/100.0','ROW_NUMBER() OVER ()'):
            with self.subTest(expression=expression):
                _,result=self.execute(expression=expression)
                self.assertNotEqual(result['status'],'SUCCESS')
