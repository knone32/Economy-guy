"""Original native business context helps routing but grants no source or action."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from app.business_request import (bind, messages, native_pending_context, read_catalog,
    schema_restatement_messages, BusinessRequestError)
from app.business_sources import bind_request
from app.invoice_action import public_state


class NativeContextTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        from app.cli_workspaces import import_workspace
        self.book=Path(temp.name)/'fictional.sqlite'
        import_workspace(Path(__file__).parent/'fixtures/example.xlsx',self.book)
        self.original='C001 2026年9月有张发票，备注填“交接复核”，票号稍后补。'
        self.pending=bind_request({'company_id':'C001','year':2026,'month':9,'field':'remark','new_value':'交接复核'},
            None,actor='U001',book=self.book,current_id='private-native-id',current_request=self.original)
        self.catalog=read_catalog(self.book,'U001');self.before=self.book.read_bytes()
        self.addCleanup(self.unchanged)

    def unchanged(self):
        self.assertEqual(self.before,self.book.read_bytes())
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)

    def input(self,text,**kw):
        return messages(text,self.catalog,native_pending=self.pending,actor='U001',book=self.book,**kw)

    def test_native_summary_reuses_original_user_source_slots_and_missing_without_tokens(self):
        self.pending['provenance']['private_internal']={'sql':'SQL-SENTINEL','draft_id':'DRAFT-SENTINEL',
            'fingerprint':'FP-SENTINEL','approval':'APPROVAL-SENTINEL','tool_proposal':'TOOL-SENTINEL'}
        value=native_pending_context(self.pending,actor='U001',book=self.book)
        self.assertEqual(value['source']['quote'],self.original)
        self.assertEqual(value['known'],public_state(self.pending)['known'])
        self.assertEqual(value['missing_fields'],public_state(self.pending)['missing_fields'])
        encoded=json.dumps(value,ensure_ascii=False)
        for token in ('private-native-id','SQL-SENTINEL','DRAFT-SENTINEL','FP-SENTINEL','APPROVAL-SENTINEL','TOOL-SENTINEL'):
            self.assertNotIn(token,encoded)
        self.assertEqual(set(value),{'status','source','known','missing_fields'})
        self.assertNotIn('actor',value);self.assertNotIn('workbook',value)

    def test_current_continuation_and_new_query_share_same_independent_context_schema(self):
        for text in ('找到了，F001，继续原来那项办理。','C001 2026年10月统计全部发票张数。'):
            original=deepcopy(self.pending)
            result=self.input(text)
            self.assertEqual(len(result),2);self.assertEqual([m['role'] for m in result],['system','user'])
            payload=json.loads(result[1]['content'])
            self.assertEqual(set(payload),{'request','read_catalog','trusted_scope','previous_requirement','business_definition'})
            self.assertEqual(payload['request'],text)
            self.assertEqual(payload['trusted_scope']['native_invoice_candidate']['known']['new_value'],'交接复核')
            self.assertEqual(schema_restatement_messages(result)[:2],result)
            self.assertEqual(self.pending,original)
        # No model/second state owner is run by this input component.

    def test_summary_does_not_create_read_anchor_or_context_source(self):
        text='统计全部发票张数。';payload=json.loads(self.input(text)[1]['content'])
        target={'target_id':'i1','object':'invoices','company_ids':['C001'],'company_quote':'',
            'company_source':'context','periods':[[2026,9]],'period_quote':'','period_source':'context',
            'seller':{'mode':'none','quote':'全部发票张数','value':''},'filters':[],
            'metrics':[{'operation':'count','field':'*','quote':'张数'}],'group_by':[],'comparisons':[]}
        with self.assertRaises(BusinessRequestError):
            bind(json.dumps({'kind':'read','targets':[target],'unresolved':[]},ensure_ascii=False),
                actor='U001',book=self.book,turn_id='read',request=text,trusted_scope=payload['trusted_scope'])
        target.update(company_ids=[],periods=[],company_source='current',period_source='current')
        unresolved=bind(json.dumps({'kind':'read','targets':[target],'unresolved':[]},ensure_ascii=False),
                actor='U001',book=self.book,turn_id='read',request=text,trusted_scope=payload['trusted_scope'])
        self.assertIn('i1.company_id',unresolved.unresolved);self.assertIn('i1.periods',unresolved.unresolved)
        target['filters']=[{'field':'remark','operator':'=','value':'交接复核','quote':'',
            'source':{'kind':'context','key':'native_invoice_candidate.known.new_value'}}]
        with self.assertRaises(BusinessRequestError):
            bind(json.dumps({'kind':'read','targets':[target],'unresolved':[]},ensure_ascii=False),
                actor='U001',book=self.book,turn_id='read',request=text,trusted_scope=payload['trusted_scope'])

    def test_invalid_or_unavailable_old_state_is_omitted_without_blocking_fresh_request(self):
        invalids=[{},[],{**self.pending,'actor':'U002'},{**self.pending,'workbook':'INVALID-BOOK-SENTINEL'},
                  {**self.pending,'sql':'SQL-INVALID-SENTINEL'}]
        for bad in invalids:
            with self.subTest(state=bad):
                self.assertIsNone(native_pending_context(bad,actor='U001',book=self.book))
                result=messages('你好',self.catalog,native_pending=bad,actor='U001',book=self.book)
                payload=json.loads(result[1]['content'])
                self.assertEqual(payload['request'],'你好');self.assertNotIn('native_invoice_candidate',payload['trusted_scope'])
                self.assertNotIn('SQL-INVALID-SENTINEL',json.dumps(result,ensure_ascii=False))
        result=messages('新查询',self.catalog,native_pending=self.pending)
        self.assertNotIn('native_invoice_candidate',json.loads(result[1]['content'])['trusted_scope'])
        # U002 has current read but no modify permission in the official fixture.
        formerly_editable={**self.pending,'actor':'U002'}
        self.assertIsNone(native_pending_context(formerly_editable,actor='U002',book=self.book))

    def test_no_pending_is_byte_identical_and_does_not_read_candidate_service(self):
        from unittest.mock import patch
        plain=messages('你好',self.catalog,trusted_scope={'company_id':['C001']})
        with patch('app.business_sources.recover_candidate',side_effect=AssertionError('No pending read')):
            unchanged=messages('你好',self.catalog,trusted_scope={'company_id':['C001']},native_pending=None,actor='U001',book=self.book)
        self.assertEqual(plain,unchanged)

    def test_invalid_old_state_does_not_block_a_source_valid_new_read(self):
        bad=deepcopy(self.pending);bad.update(actor='U002',source_request='INVALID-OLD-SOURCE',request='INVALID-OLD-SOURCE')
        bad['change']={'field':['remark'],'new_value':['INVALID-OLD-VALUE']}
        text='C001 2026年10月统计全部发票张数。'
        result=messages(text,self.catalog,native_pending=bad,actor='U001',book=self.book)
        encoded=json.dumps(result,ensure_ascii=False)
        self.assertNotIn('INVALID-OLD-SOURCE',encoded);self.assertNotIn('INVALID-OLD-VALUE',encoded)
        payload=json.loads(result[1]['content'])
        target={'target_id':'i1','object':'invoices','company_ids':['C001'],'company_quote':'C001',
            'periods':[[2026,10]],'period_quote':'2026年10月',
            'seller':{'mode':'none','quote':'全部发票张数','value':''},'filters':[],
            'metrics':[{'operation':'count','field':'*','quote':'张数'}],'group_by':[],'comparisons':[]}
        req=bind(json.dumps({'kind':'read','targets':[target],'unresolved':[]},ensure_ascii=False),
            actor='U001',book=self.book,turn_id='new-read',request=text,trusted_scope=payload['trusted_scope'])
        self.assertFalse(req.unresolved)
        self.assertEqual(req.targets[0].periods,((2026,10),))
