"""Finite schema-backed count/blank equivalence, real SQLite and Registry."""
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.business_request import bind
from app.business_request_delivery import (accept_result, canonical_sql_result, check_sql,
    RequestDeliveryError, assess_results, check_dedicated)
from app.business_sql import BusinessSQL
from app.cli_workspaces import import_workspace
from app.fact_arithmetic import sql_scalars, derive
from app.provenance import ScopeProof
from app.tool_registry import handle_tool


class RequestScalarEquivalenceTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.book=Path(temp.name)/'fictional.sqlite'
        import_workspace(Path(__file__).parent/'fixtures/example.xlsx',self.book)
        with closing(sqlite3.connect(self.book)) as db,db:
            db.execute('DELETE FROM invoices')
            db.executemany('INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?)',[
                ('C001',no,'2026-09-02','岚原服务有限公司','项目',amount,purpose,'')
                for no,amount,purpose in [('S-A',100,None),('S-B',200,''),('S-C',300,' \t'),('S-D',400,'已填')]])
        self.values={'company_id':['C001'],'periods':[(2026,9)],'year':[2026],'month':[9]}
        self.proof=ScopeProof('U002',self.values,dict.fromkeys(self.values,'controlled_read_scope'))
        self.before=self.book.read_bytes()
        self.addCleanup(self.unchanged)

    def unchanged(self):
        self.assertEqual(self.before,self.book.read_bytes())
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*),sum(amount_cents) FROM invoices').fetchone(),(4,1000))

    def requirement(self,blank=False,nonblank=False):
        text='C001 2026年9月统计'+('用途非空的' if nonblank else '用途为空的' if blank else '全部')+'发票张数。'
        target={'target_id':'i1','object':'invoices','company_ids':['C001'],'company_quote':'C001',
            'periods':[[2026,9]],'period_quote':'2026年9月','seller':{'mode':'none','quote':text[12:],'value':''},
            'filters':[{'field':'purpose','operator':'is_blank','value':False if nonblank else '',
                        'quote':'用途非空' if nonblank else '用途为空'}] if blank or nonblank else [],
            'metrics':[{'operation':'count','field':'*','quote':'张数'}],'group_by':[],'comparisons':[]}
        target['seller']['quote']='发票张数'
        return bind(json.dumps({'kind':'read','targets':[target],'unresolved':[]},ensure_ascii=False),
                    actor='U002',book=self.book,turn_id='scalar-shape',request=text)

    def raw(self,sql,request):
        with closing(BusinessSQL(self.book,'U002',self.proof,request=request.current_source.quote)) as workspace:
            workspace.business_request=request
            scope,data,_=workspace.query(sql)
        return {'status':'SUCCESS','data':data,'evidence':{'scope':scope,'query_scope':data.pop('query_scope'),'source':'current_sqlite'}}

    def registry(self,sql,request):
        with closing(BusinessSQL(self.book,'U002',self.proof,request=request.current_source.quote)) as workspace:
            return handle_tool('query_business_sql',json.dumps({'sql':sql}),'U002',self.book,
                provenance=self.proof,expected_scope=self.values,sql_workspace=workspace,business_request=request)

    def test_count_star_and_not_null_identity_share_facts_arithmetic_and_coverage(self):
        request=self.requirement();sql='SELECT COUNT(invoice_no) AS n FROM invoices';raw=self.raw(sql,request)
        # Preserve the original first-FAIL proof: raw field-specific count is not count(*).
        with self.assertRaises(RequestDeliveryError):check_sql(request,raw,'U002',self.book)
        star=self.registry('SELECT COUNT(*) AS n FROM invoices',request)
        accepted=self.registry(sql,request)
        self.assertEqual((star['status'],accepted['status']),('SUCCESS','SUCCESS'))
        self.assertEqual(accepted['data']['rows'],[(4,)])
        self.assertEqual(accepted['data']['sql'],sql)
        self.assertEqual(accepted['evidence']['query_scope']['sql_sha256'],sha256(sql.encode()).hexdigest())
        column=accepted['evidence']['query_scope']['columns'][0]
        self.assertEqual(column['kind'],'count_rows')
        self.assertEqual(column['original_attribution']['kind'],'count_nonnull')
        self.assertEqual(column['original_attribution']['field'],'invoice_no')
        self.assertEqual(accepted['evidence']['original_query_scope'],raw['evidence']['query_scope'])
        left=next(iter(sql_scalars(star,'star','').values()))[1]
        right=next(iter(sql_scalars(accepted,'identity','').values()))[1]
        self.assertEqual(left['metric'],right['metric'])
        self.assertIn('差额 0 张',derive({'op':'compare','left':'a','right':'b'},{'a':left,'b':right}))
        self.assertTrue(assess_results(request,[('query_business_sql',accepted)])['complete'])
        self.assertEqual(raw['evidence']['query_scope']['columns'][0]['kind'],'count_nonnull')

    def test_nullable_count_and_distinct_do_not_become_row_count(self):
        request=self.requirement()
        for sql in ('SELECT COUNT(purpose) AS n FROM invoices','SELECT COUNT(DISTINCT invoice_no) AS n FROM invoices'):
            with self.subTest(sql=sql):
                result=self.registry(sql,request)
                self.assertNotIn(result['status'],{'SUCCESS','NO_DATA'})
        raw=self.raw('SELECT COUNT(purpose) AS n FROM invoices',request)
        self.assertEqual(raw['data']['rows'],[(3,)])
        self.assertNotIn('purpose',raw['data']['read_version']['schema_constraints']['not_null_columns']['invoices'])

    def test_blank_and_not_blank_are_distinct_in_sql_and_dedicated_postfilter(self):
        request=self.requirement(blank=True)
        positive=self.registry('SELECT COUNT(*) AS n FROM invoices WHERE is_blank(purpose)',request)
        negative=self.registry('SELECT COUNT(*) AS n FROM invoices WHERE NOT is_blank(purpose)',request)
        self.assertEqual(positive['status'],'SUCCESS');self.assertEqual(positive['data']['rows'],[(3,)])
        self.assertEqual(negative['status'],'SCOPE_MISMATCH')
        self.assertIs(positive['evidence']['query_scope']['conditions'][0]['value'],True)
        # Same compiler is used for actual get_invoice result filtering.
        detail=replace(request,targets=(replace(request.targets[0],metrics=()),))
        def one(purpose):return {'status':'SUCCESS','data':{'purpose':purpose},
            'evidence':{'source':'current_sqlite','scope':{'company_id':'C001','year':2026,'month':9}}}
        self.assertEqual(check_dedicated(detail,'get_invoice',one(None),'U002',self.book)['status'],'SUCCESS')
        with self.assertRaises(RequestDeliveryError):check_dedicated(detail,'get_invoice',one('已填'),'U002',self.book)
        inverse=self.requirement(nonblank=True)
        inverse=replace(inverse,targets=(replace(inverse.targets[0],metrics=()),))
        false_sql=self.registry('SELECT COUNT(*) AS n FROM invoices WHERE NOT is_blank(purpose)',self.requirement(nonblank=True))
        self.assertEqual(false_sql['status'],'SUCCESS');self.assertEqual(false_sql['data']['rows'],[(1,)])
        self.assertEqual(check_dedicated(inverse,'get_invoice',one('已填'),'U002',self.book)['status'],'SUCCESS')
        with self.assertRaises(RequestDeliveryError):check_dedicated(inverse,'get_invoice',one(None),'U002',self.book)

    def test_schema_constraints_are_read_in_source_transaction_not_during_canonicalization(self):
        from app.stage2_schema import open_existing
        seen=[]
        def traced(*args,**kwargs):
            db=open_existing(*args,**kwargs)
            db.set_trace_callback(lambda sql:seen.append((sql,db.in_transaction)))
            return db
        with patch('app.business_sql.open_existing',side_effect=traced):
            raw=self.raw('SELECT COUNT(invoice_no) AS n FROM invoices',self.requirement())
        pragmas=[active for sql,active in seen if 'PRAGMA table_info(' in sql]
        self.assertEqual(pragmas,[True,True])
        with patch('sqlite3.connect',side_effect=AssertionError('No post-snapshot schema read')):
            canonical=canonical_sql_result(raw)
        self.assertEqual(canonical['evidence']['query_scope']['columns'][0]['kind'],'count_rows')
        self.assertEqual(raw['data']['read_version']['consistency'],'one_sqlite_read_transaction')

    def test_missing_or_tampered_snapshot_constraints_and_sql_hash_do_not_grant_equivalence(self):
        raw=self.raw('SELECT COUNT(invoice_no) AS n FROM invoices',self.requirement())
        for change in ('no_constraints','bad_schema_hash','bad_sql_hash'):
            broken=deepcopy(raw)
            if change=='no_constraints':broken['data']['read_version'].pop('schema_constraints')
            elif change=='bad_schema_hash':broken['data']['read_version']['schema_constraints']['sha256']='invalid'
            else:broken['evidence']['query_scope']['sql_sha256']='invalid'
            self.assertEqual(canonical_sql_result(broken)['evidence']['query_scope']['columns'][0]['kind'],'count_nonnull')

    def test_real_fresh_invoice_registry_uses_same_blank_filter_normalization(self):
        for number,nonblank,wanted in [('S-A',False,'SUCCESS'),('S-D',False,'SCOPE_MISMATCH'),
                                       ('S-D',True,'SUCCESS'),('S-A',True,'SCOPE_MISMATCH')]:
            with self.subTest(invoice=number,nonblank=nonblank):
                condition='用途非空' if nonblank else '用途为空'
                text='C001 2026年9月核对'+number+'发票明细，筛选'+condition+'。'
                target={'target_id':'i1','object':'invoices','company_ids':['C001'],'company_quote':'C001',
                    'periods':[[2026,9]],'period_quote':'2026年9月',
                    'seller':{'mode':'none','quote':'发票明细','value':''},
                    'filters':[{'field':'invoice_no','operator':'=','value':number,'quote':number},
                               {'field':'purpose','operator':'is_blank','value':False if nonblank else '',
                                'quote':condition}],
                    'metrics':[{'operation':'details','field':'*','quote':'发票明细'}],
                    'group_by':[],'comparisons':[]}
                req=bind(json.dumps({'kind':'read','targets':[target],'unresolved':[]},ensure_ascii=False),
                    actor='U002',book=self.book,turn_id='fresh',request=text)
                scope={**self.values,'invoice_no':[number]}
                proof=ScopeProof('U002',scope,dict.fromkeys(scope,'controlled_read_scope'))
                result=handle_tool('get_invoice',json.dumps({'company_id':'C001','invoice_no':number}),
                    'U002',self.book,provenance=proof,expected_scope=scope,business_request=req)
                self.assertEqual(result['status'],wanted,result)
                if wanted=='SUCCESS':self.assertEqual(result['data']['invoice_no'],number)
