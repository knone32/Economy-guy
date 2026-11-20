"""Public read-unit wording, independent dispatch gate and explicit edit owner."""
from contextlib import closing
import json
import sqlite3
import unittest
from unittest.mock import patch
from app.agent import Agent
from app.provenance import ScopeProof
from tests import test_business_request_phase as fixtures


def call(identifier, name, **values):
    return {'id':identifier,'type':'function','function':{'name':name,'arguments':json.dumps(values)}}


class BusinessRequestEntryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BusinessRequestPhaseTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.book=self.fixture.book

    def test_money_display_words_cannot_bypass_independent_requirements(self):
        for phrase in ('金额以元显示','金额换成元','金额换算为元'):
            with self.subTest(phrase=phrase):
                seen=[];text=self.fixture.text+phrase+'。'
                def model(messages,tools):
                    seen.append((messages,tools))
                    return {'role':'assistant','content':json.dumps(self.fixture.requirement(),ensure_ascii=False)}
                a=Agent('U001',self.book,model,mode='mock',max_requests=1,
                        trace_path=self.fixture.root/(phrase+'.jsonl'))
                a.ask(text,task_note_from_request=True)
                self.assertEqual(len(seen),1);self.assertEqual(seen[0][1],[])
                self.assertEqual(json.loads(seen[0][0][1]['content'])['request'],text)
                self.assertIsNotNone(a.business_request)
                self.assertTrue(a.last_response['business_request_entry']['independent_preflight'])
                self.assertEqual(a.last_response['execution']['actual_tool_calls'],0)

    def test_disabling_early_switch_does_not_authorize_financial_dispatch(self):
        a=Agent('U001',self.book,lambda *_:None,mode='mock',trace_path=self.fixture.root/'gate.jsonl')
        a._business_contract_required=False
        for name,args in (('get_finance_summary',{'company_id':'C001','year':2026,'month':9}),
                          ('get_invoice',{'company_id':'C001','invoice_no':'F001'}),
                          ('query_business_sql',{'sql':'SELECT COUNT(*) FROM invoices'})):
            with self.subTest(name=name),patch('app.agent.handle_tool') as handler:
                result=a.dispatch_tool(name,json.dumps(args),'U001',self.book)
                self.assertEqual(result['status'],'DENIED');handler.assert_not_called()

    def test_current_explicit_edit_owner_only_reads_its_exact_invoice(self):
        a=Agent('U001',self.book,lambda *_:None,mode='mock',trace_path=self.fixture.root/'owner.jsonl')
        scope={'company_id':['C001'],'invoice_no':['F001'],'year':[2026],'month':[9],
               'field':['remark'],'new_value':['待核']}
        a.coordinator.begin('C001 2026年9月F001备注改为待核',True,edit_scope=scope)
        a._business_contract_required=False
        values={k:scope[k] for k in ('company_id','invoice_no','year','month')}
        proof=ScopeProof('U001',values,dict.fromkeys(values,'user_current'))
        result=a.dispatch_tool('get_invoice',json.dumps({'company_id':'C001','invoice_no':'F001'}),
                              'U001',self.book,provenance=proof)
        self.assertEqual(result['status'],'SUCCESS',result)
        basis=result['evidence']['read_basis']
        self.assertEqual(basis['kind'],'invoice_update_session')
        self.assertEqual(basis['turn_id'],a.update_session.turn_id)
        for name,args in (('get_invoice',{'company_id':'C001','invoice_no':'F002'}),
                          ('get_finance_summary',{'company_id':'C001','year':2026,'month':9})):
            with patch('app.agent.handle_tool') as handler:
                denied=a.dispatch_tool(name,json.dumps(args),'U001',self.book)
                self.assertEqual(denied['status'],'DENIED');handler.assert_not_called()
        a.coordinator.begin('新的普通问题',False)
        with patch('app.agent.handle_tool') as handler:
            denied=a.dispatch_tool('get_invoice',json.dumps({'company_id':'C001','invoice_no':'F001'}),
                                   'U001',self.book)
            self.assertEqual(denied['status'],'DENIED');handler.assert_not_called()

    def test_explicit_edit_fresh_read_and_prepare_keep_existing_confirmation_owner(self):
        scope={'company_id':['C001'],'invoice_no':['F001'],'year':[2026],'month':[9],
               'field':['remark'],'new_value':['待核']}
        replies=iter([
            {'role':'assistant','tool_calls':[call('fresh','get_invoice',company_id='C001',invoice_no='F001')]},
            {'role':'assistant','tool_calls':[call('prepare','prepare_invoice_update',company_id='C001',invoice_no='F001',field='remark',new_value='待核')]}])
        seen=[]
        def model(messages,tools):seen.append(tools);return next(replies)
        a=Agent('U001',self.book,model,mode='mock',trace_path=self.fixture.root/'edit-chain.jsonl')
        a.ask('C001 2026年9月F001备注改为待核',allow_prepare=True,edit_scope=scope)
        self.assertTrue(seen[0]);self.assertIsNone(a.business_request)
        self.assertEqual(a.last_response['execution']['stop_reason'],'WAITING_CONFIRMATION')
        self.assertEqual(len(a.update_session.drafts),1)
        read=next(r for name,r in a.last_response['tool_results'] if name=='get_invoice')
        self.assertEqual(read['evidence']['read_basis']['kind'],'invoice_update_session')
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)
            self.assertNotEqual(db.execute("SELECT remark FROM invoices WHERE company_id='C001' AND invoice_no='F001'").fetchone()[0],'待核')
