"""Output attribution and SQL row effects are independent proof questions."""
import hashlib
import unittest
from app.business_sql import TABLES
from app.sql_evidence import describe


class ProjectionRowEffectTests(unittest.TestCase):
    scope={'company_ids':('C001',),'periods':((2026,9),)}

    def evidence(self,sql,columns,partial=True):
        return describe(sql,columns,self.scope,TABLES,{'invoices'},allow_partial_projection=partial)

    def test_row_detail_round_is_not_an_aggregate_and_is_not_a_money_fact(self):
        sql='SELECT invoice_no,amount_cents,ROUND(amount_cents/100.0,2) AS yuan FROM invoices'
        q=self.evidence(sql,['invoice_no','amount_cents','yuan'])
        self.assertEqual(q['status'],'VERIFIED',q)
        self.assertFalse(q['projection_complete'])
        self.assertEqual(q['columns'][2]['kind'],'unattributed')
        self.assertIsNone(q['columns'][2]['unit'])
        self.assertEqual(q['columns'][2]['row_effect'],'scalar')
        self.assertEqual(q['columns'][1]['unit'],'cents')
        self.assertEqual(q['row_shape'],'detail')
        self.assertTrue(q['row_shape_evidence']['preserves_filtered_source_rows'])
        self.assertEqual(q['sql_sha256'],hashlib.sha256(sql.encode()).hexdigest())
        self.assertEqual(self.evidence(sql,['invoice_no','amount_cents','yuan'],False)['status'],'UNKNOWN')

    def test_unknown_projection_columns_are_not_discarded_as_harmless(self):
        for projection in ('invoice_no,missing_value',
                           'invoice_no,ROUND(missing_value/100.0,2)',
                           'invoice_no,CASE WHEN purpose=\'物料\' THEN bad_column ELSE amount_cents END'):
            sql='SELECT '+projection+' FROM invoices'
            q=self.evidence(sql,['invoice_no','unknown'])
            self.assertEqual(q['status'],'UNKNOWN',q)

        q=self.evidence('SELECT ROUND(missing_value/100.0,2) AS x FROM invoices',['x'])
        self.assertEqual(q['status'],'UNKNOWN',q)

    def test_anonymous_aggregate_window_and_row_expansion_cannot_masquerade_as_detail(self):
        for expression in ('group_concat(purpose)','json_group_array(purpose)',
                           'custom_function(purpose)','ROW_NUMBER() OVER()',
                           'UNNEST(purpose)','EXPLODE(purpose)','GENERATE_SERIES(1,3)',
                           '(SELECT COUNT(*) FROM invoices)'):
            with self.subTest(expression=expression):
                q=self.evidence('SELECT invoice_no,'+expression+' AS x FROM invoices',['invoice_no','x'])
                self.assertEqual(q['status'],'UNKNOWN',q)

    def test_case_scalar_can_be_unproved_while_real_aggregate_stays_aggregate(self):
        sql="SELECT invoice_no,CASE WHEN purpose='物料' THEN amount_cents/100.0 ELSE 0 END AS shown FROM invoices"
        q=self.evidence(sql,['invoice_no','shown'])
        self.assertEqual(q['status'],'VERIFIED',q)
        self.assertEqual(q['row_shape'],'detail')
        self.assertFalse(q['projection_complete'])
        q=self.evidence('SELECT invoice_no,AVG(amount_cents) AS average FROM invoices',['invoice_no','average'])
        self.assertEqual(q['status'],'UNKNOWN',q)
        q=self.evidence('SELECT COUNT(*) AS n,AVG(amount_cents) AS average FROM invoices',['n','average'])
        self.assertEqual(q['status'],'VERIFIED',q)
        self.assertEqual(q['row_shape'],'aggregate')
        self.assertEqual(q['columns'][1]['row_effect'],'aggregate')
        self.assertFalse(q['row_shape_evidence']['preserves_filtered_source_rows'])

    def test_known_window_and_grouped_aggregate_are_classified_without_new_expression_facts(self):
        q=self.evidence('SELECT invoice_no,COUNT(*) OVER() AS n FROM invoices',['invoice_no','n'])
        self.assertEqual(q['status'],'VERIFIED',q)
        self.assertEqual(q['row_shape'],'window')
        self.assertTrue(q['row_shape_evidence']['preserves_filtered_source_rows'])
        q=self.evidence('SELECT purpose,COUNT(*) AS n FROM invoices GROUP BY purpose',['purpose','n'])
        self.assertEqual(q['status'],'VERIFIED',q)
        self.assertEqual(q['row_shape'],'grouped')
        q=self.evidence('SELECT DISTINCT purpose,ROUND(amount_cents/100.0,2) AS yuan FROM invoices',['purpose','yuan'])
        self.assertEqual(q['status'],'UNKNOWN',q)

    def test_real_registry_missing_identity_keeps_unproved_detail_as_capability_limit(self):
        from contextlib import closing
        from tempfile import TemporaryDirectory
        from pathlib import Path
        import json,sqlite3
        from app.business_request import bind
        from app.business_sql import BusinessSQL
        from app.cli_workspaces import import_workspace
        from app.provenance import ScopeProof
        from app.tool_registry import handle_tool
        with TemporaryDirectory() as temp:
            book=Path(temp)/'fictional.sqlite'
            import_workspace(Path(__file__).parent/'fixtures/example.xlsx',book)
            text='C001 2026年9月查看全部发票明细。'
            target={'target_id':'i1','object':'invoices','company_ids':['C001'],'company_quote':'C001',
                'periods':[[2026,9]],'period_quote':'2026年9月',
                'seller':{'mode':'none','quote':'全部发票明细','value':''},'filters':[],
                'metrics':[{'operation':'details','field':'*','quote':'发票明细'}],'group_by':[],'comparisons':[]}
            req=bind(json.dumps({'kind':'read','targets':[target],'unresolved':[]},ensure_ascii=False),
                     actor='U002',book=book,turn_id='detail-shape',request=text)
            values={'company_id':['C001'],'periods':[(2026,9)]}
            proof=ScopeProof('U002',values,dict.fromkeys(values,'controlled_read_scope'))
            sql='SELECT invoice_no,amount_cents,ROUND(amount_cents/100.0,2) AS yuan FROM invoices'
            before=book.read_bytes()
            with closing(BusinessSQL(book,'U002',proof,request=text)) as workspace:
                workspace.business_request=req
                _,raw,_=workspace.query(sql)
                self.assertEqual(raw['query_scope']['status'],'VERIFIED')
                self.assertEqual(raw['query_scope']['row_shape'],'detail')
                result=handle_tool('query_business_sql',json.dumps({'sql':sql}),'U002',book,
                                   sql_workspace=workspace,business_request=req)
            # Missing raw company/date identity must not gain complete-detail evidence.
            self.assertEqual(result['status'],'SQL_EVIDENCE_UNSUPPORTED',result)
            self.assertIsNone(result['data'])
            self.assertEqual(before,book.read_bytes())
            with closing(sqlite3.connect(book)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)
