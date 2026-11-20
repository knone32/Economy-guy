"""Pre-tool stage controls reuse Agent's single scheduler/transport path."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.request_budget import BudgetExceeded
from app.model_transport import ModelOutputTruncated


def tool(identifier,name,**args):
    return {'id':identifier,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}


class BusinessRequestPhaseTests(unittest.TestCase):
    def setUp(self):
        tmp=TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.book=self.root/'fictional.sqlite'
        import_workspace(Path(__file__).parent/'fixtures/example.xlsx',self.book)
        self.text='C001 2026年9月统计全部发票金额和张数。'

    def requirement(self):
        return {'kind':'read','targets':[{'target_id':'i1','object':'invoices','company_ids':['C001'],
          'company_quote':'C001','periods':[[2026,9]],'period_quote':'2026年9月',
          'seller':{'mode':'none','quote':'全部发票金额和张数','value':''},'filters':[],
          'metrics':[{'operation':'sum','field':'amount_cents','quote':'金额和张数'},
                     {'operation':'count','field':'*','quote':'金额和张数'}],
          'group_by':['period'],'comparisons':[]}],'unresolved':[]}

    def run_case(self,replies,*,text=None,max_requests=9):
        seen=[];iterator=iter(replies)
        def model(messages,tools):
            seen.append((messages,tools));value=next(iterator)
            if isinstance(value,Exception):raise value
            return value
        a=Agent('U001',self.book,model,mode='mock',trace_path=self.root/'trace.jsonl',max_requests=max_requests)
        with closing(sqlite3.connect(self.book)) as db:
            before=db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no').fetchall()
        with patch('app.agent.handle_tool',side_effect=AssertionError('No business dispatch during this control')) as handler:
            answer=a.ask(text or self.text)
        self.assertEqual(handler.call_count,0)
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(before,db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no').fetchall())
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)
        self.assertEqual(a.write_receipt['status'],'NOT_SUBMITTED')
        self.assertEqual(seen[0][1],[])
        payload=json.loads(seen[0][0][1]['content'])
        self.assertEqual(payload['request'],text or self.text)
        self.assertIn('business_definition',payload);self.assertNotIn('sql',payload)
        return a,answer,seen

    def paired(self,a):
        calls=[c['id'] for m in a.messages if m.get('role')=='assistant' for c in m.get('tool_calls') or []]
        results=[m['tool_call_id'] for m in a.messages if m.get('role')=='tool']
        self.assertCountEqual(calls,results)

    def test_greeting_reuses_original_general_reply_path(self):
        a,answer,seen=self.run_case([{'role':'assistant','content':json.dumps({'kind':'general','text':'你好，有什么可以帮你？'},ensure_ascii=False)}],text='你好')
        self.assertIn('你好',answer);self.assertEqual(len(seen),1);self.assertIsNone(a.business_request)

    def test_general_cannot_claim_current_book_amount_or_save(self):
        for text in ('C001已查出发票金额12345.67元。','已保存C001的备注修改。'):
            with self.subTest(text=text):
                a,answer,_=self.run_case([{'role':'assistant','content':json.dumps({'kind':'general','text':text},ensure_ascii=False)}])
                self.assertNotIn('12345.67',answer);self.assertNotIn('已保存C001',answer)
                self.assertEqual(a.last_response['execution']['stop_reason'],'UNVERIFIED_RESULT')

    def test_first_step_tool_calls_are_denied_and_all_ids_paired(self):
        calls=[tool('q','query_business_sql',sql='SELECT COUNT(*) FROM invoices'),
               tool('s','get_finance_summary',company_id='C001',year=2026,month=9)]
        a,answer,seen=self.run_case([{'role':'assistant','tool_calls':calls}])
        self.assertEqual(a.last_response['execution']['actual_tool_calls'],0)
        self.assertEqual(a.last_response['execution']['requested_tool_calls'],2);self.paired(a)

    def test_legacy_route_does_not_authorize_later_financial_read(self):
        a,answer,seen=self.run_case([{'role':'assistant','content':'{"kind":"legacy"}'},
            {'role':'assistant','tool_calls':[tool('q','get_finance_summary',company_id='C001',year=2026,month=9)]}])
        self.assertEqual(len(seen),2);self.assertNotIn('9622.06',answer);self.paired(a)
        self.assertFalse(any(r['status']=='SUCCESS' for _,r in a.last_response['tool_results']))

    def test_frozen_request_does_not_create_extra_hard_budget_slots(self):
        a,answer,seen=self.run_case([{'role':'assistant','content':json.dumps(self.requirement(),ensure_ascii=False)}],max_requests=1)
        self.assertEqual(len(seen),1);self.assertIsNotNone(a.business_request)
        self.assertEqual(a.last_response['execution']['model_requests'],1)
        self.assertEqual(a.last_response['execution']['actual_tool_calls'],0)

    def test_invalid_duplicate_and_truncated_semantic_input_never_dispatch(self):
        for content in ('invalid','{"kind":"general","kind":"legacy"}'):
            a,_,seen=self.run_case([{'role':'assistant','content':content}]);self.assertEqual(len(seen),1)
        a,_,seen=self.run_case([ModelOutputTruncated('mock')]);self.assertEqual(len(seen),1)

    def test_prehttp_budget_refusal_does_not_start_evidence_closing_request(self):
        a,_,seen=self.run_case([BudgetExceeded('token_reservation',before_http=True)])
        self.assertEqual(len(seen),1);self.assertIsNone(a.business_request)
        self.assertEqual(a.last_response['execution']['stop_reason'],'REQUEST_BUDGET_EXCEEDED')

    def test_frozen_read_cannot_reach_native_change_preview_or_partial_write_state(self):
        text='请核对C001 2026年9月 F001 当前备注是否为“待核”，不筛选销售方。'
        req=self.requirement();target=req['targets'][0]
        target['seller']={'mode':'none','quote':'不筛选销售方','value':''}
        target['filters']=[{'field':'invoice_no','operator':'=','value':'F001','quote':'F001'},
                           {'field':'remark','operator':'=','value':'待核','quote':'当前备注是否为“待核”'}]
        target['metrics']=[{'operation':'details','field':'*','quote':'当前备注'}];target['group_by']=[]
        generated={'role':'assistant','tool_calls':[tool('native-write','change_invoice',company_id='C001',
                   invoice_no='F001',year=2026,month=9,field='remark',new_value='待核')]}
        a,answer,seen=self.run_case([{'role':'assistant','content':json.dumps(req,ensure_ascii=False)},generated],text=text)
        self.assertEqual(len(seen),2);self.assert_pure_read_denial(a)

    def assert_pure_read_denial(self,a):
        self.assertEqual(a.last_response['execution']['stop_reason'],'DENIED')
        self.assertEqual(a.last_response['execution']['actual_tool_calls'],0)
        self.assertFalse(a.update_session.drafts);self.assertFalse(a.update_session.confirmations)
        self.assertIsNone(a.ticket_preview_candidate);self.assertIsNone(a.pending_intent)
        self.assertNotIn('invoice_change',a.last_response);self.paired(a)

    def test_read_frame_rejects_mixed_native_write_and_read_before_any_dispatch(self):
        generated={'role':'assistant','tool_calls':[tool('native-write','change_invoice',company_id='C001',invoice_no='F001',
            year=2026,month=9,field='remark',new_value='物料'),tool('query','get_finance_summary',company_id='C001',year=2026,month=9)]}
        a,_,_=self.run_case([{'role':'assistant','content':json.dumps(self.requirement(),ensure_ascii=False)},generated])
        self.assert_pure_read_denial(a)
        self.assertEqual(a.last_response['execution']['requested_tool_calls'],2)

    def test_true_legacy_write_owner_still_can_prepare_without_read_request(self):
        message={'role':'assistant','tool_calls':[tool('native','change_invoice',company_id='C001',invoice_no='F001',
            year=2026,month=9,field='remark',new_value='待核')]}
        seen=[]
        def model(messages,tools):seen.append(tools);return message
        a=Agent('U001',self.book,model,mode='mock',trace_path=self.root/'legacy-write.jsonl')
        a.ask('C001 2026年9月F001的备注改成“待核”。')
        self.assertIsNone(a.business_request);self.assertTrue(seen[0])
        self.assertEqual(a.last_response['execution']['stop_reason'],'WAITING_CONFIRMATION')
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)
            self.assertNotEqual(db.execute("SELECT remark FROM invoices WHERE company_id='C001' AND invoice_no='F001'").fetchone()[0],'待核')

    def test_frozen_read_does_not_accept_pending_or_duplicate_state_envelope(self):
        for content in ('{"kind":"information","text":"待核","pending_change":{"field":"remark","new_value":"待核"}}',
                        '{"kind":"information","pending_change":{},"pending_change":{"field":"remark","new_value":"待核"},"text":"x"}'):
            with self.subTest(content=content):
                a,_,_=self.run_case([{'role':'assistant','content':json.dumps(self.requirement(),ensure_ascii=False)},
                    {'role':'assistant','content':content}])
                self.assert_pure_read_denial(a)

    def test_dedicated_dispatch_uses_frozen_canonical_scope_without_mutating_context(self):
        from app.business_request import bind
        from app.provenance import ScopeProof
        a=Agent('U001',self.book,lambda *_:None,mode='mock',trace_path=self.root/'dispatch.jsonl')
        req=bind(json.dumps(self.requirement(),ensure_ascii=False),actor='U001',book=self.book,
                 turn_id=a.trace_id,request=self.text)
        a.business_request=req;a._business_contract_required=True
        a.trace_id='dedicated-turn'
        req=__import__('dataclasses').replace(req,turn_id=a.trace_id);a.business_request=req
        old=(dict(a.context.proof().values),dict(a.context.proof().sources))
        forged=ScopeProof('U001',{'company_id':['C002'],'periods':[(2026,10)]},
                          {'company_id':'user_current','periods':'user_current'})
        with patch('app.agent.handle_tool',return_value={'status':'NO_DATA'}) as handler:
            a.dispatch_tool('get_finance_summary',{'company_id':'C001','year':2026,'month':9},
                            provenance=forged)
        passed=handler.call_args.kwargs
        self.assertIs(passed['business_request'],req)
        self.assertEqual(passed['provenance'].values['company_id'],['C001'])
        self.assertEqual(passed['provenance'].values['periods'],[(2026,9)])
        self.assertEqual(set(passed['provenance'].sources.values()),{'controlled_read_scope'})
        self.assertEqual((dict(a.context.proof().values),dict(a.context.proof().sources)),old)

    def test_generator_invoice_argument_cannot_create_read_proof_and_wrong_turn_does_not_dispatch(self):
        from dataclasses import replace
        from app.business_request import bind
        a=Agent('U001',self.book,lambda *_:None,mode='mock',trace_path=self.root/'dispatch-id.jsonl')
        req=bind(json.dumps(self.requirement(),ensure_ascii=False),actor='U001',book=self.book,
                 turn_id=a.trace_id,request=self.text)
        a.trace_id='invoice-turn';req=replace(req,turn_id=a.trace_id)
        a.business_request=req;a._business_contract_required=True
        with patch('app.agent.handle_tool',return_value={'status':'NO_DATA'}) as handler:
            a.dispatch_tool('get_invoice',{'company_id':'C001','invoice_no':'INVENTED','year':2026,'month':9})
            self.assertNotIn('invoice_no',handler.call_args.kwargs['provenance'].values)
        a.business_request=replace(req,turn_id='other-turn')
        with patch('app.agent.handle_tool') as handler:
            result=a.dispatch_tool('get_invoice',{'company_id':'C001','invoice_no':'F001'})
            self.assertEqual(result['status'],'DENIED');handler.assert_not_called()

    def test_retired_previous_catalog_is_not_sent_to_semantic_model(self):
        from app.business_request import bind
        a=Agent('U001',self.book,lambda *_:self.fail('stale catalog must not enter model input'),
                mode='mock',trace_path=self.root/'retired.jsonl')
        a.business_request=bind(json.dumps(self.requirement(),ensure_ascii=False),actor='U001',book=self.book,
                              turn_id='previous',request=self.text)
        with closing(sqlite3.connect(self.book)) as db,db:
            db.execute("UPDATE invoices SET seller_name='新登记名称' WHERE company_id='C001'")
        answer=a.ask(self.text)
        self.assertEqual(a.last_response['execution']['model_requests'],1)
        self.assertNotIn('新登记名称',answer)

    def test_formal_tui_note_flag_does_not_bypass_independent_read_requirement(self):
        seen=[]
        def model(messages,tools):
            seen.append((messages,tools))
            self.assertEqual(tools,[])
            payload=json.loads(messages[1]['content'])
            self.assertEqual(payload['request'],self.text)
            self.assertIn('business_definition',payload)
            return {'role':'assistant','content':json.dumps(self.requirement(),ensure_ascii=False)}
        a=Agent('U001',self.book,model,mode='mock',trace_path=self.root/'formal-note.jsonl',max_requests=1)
        with patch('app.agent.handle_tool',side_effect=AssertionError('No execution before requirement')):
            a.ask(self.text,task_note_from_request=True)
        self.assertEqual(len(seen),1);self.assertIsNotNone(a.business_request)
        self.assertEqual(a.last_response['execution']['actual_tool_calls'],0)

    def test_explicit_task_owner_with_tui_note_flag_keeps_existing_preview_chain(self):
        text='保存 C001 2026-09 后续任务：下次核对缺失用途'
        seen=[]
        def model(messages,tools):
            seen.append((messages,tools));self.assertTrue(tools)
            return {'role':'assistant','tool_calls':[tool('task','manage_task',company_id='C001',
                action='create',task_id='',year=2026,month=9,note=text)]}
        a=Agent('U001',self.book,model,mode='mock',trace_path=self.root/'formal-task.jsonl',max_requests=1)
        a.ask(text,management='task',management_action='create',task_note_from_request=True)
        self.assertEqual(len(seen),1);self.assertIsNone(a.business_request)
        self.assertEqual(a.last_response['execution']['stop_reason'],'WAITING_CONFIRMATION')
        self.paired(a)
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0],0)

    def test_read_generator_only_sees_registered_result_contracts(self):
        from app.business_request_delivery import CAPABILITIES, SUPPORT_TOOLS
        seen=[]
        def model(messages,tools):
            seen.append(tools)
            return {'role':'assistant','content':json.dumps(self.requirement(),ensure_ascii=False)} if len(seen)==1 else {
                'role':'assistant','content':json.dumps({'kind':'information','text':'没有执行统计。'},ensure_ascii=False)}
        a=Agent('U001',self.book,model,mode='mock',trace_path=self.root/'visible-contracts.jsonl',max_requests=2)
        a.ask(self.text,task_note_from_request=True)
        self.assertEqual(len(seen),2);self.assertEqual(seen[0],[])
        names={t['function']['name'] for t in seen[1]}
        self.assertIn('query_business_sql',names)
        self.assertIn('get_finance_summary',names)
        self.assertTrue(names <= set(CAPABILITIES)|SUPPORT_TOOLS,names)
        self.assertNotIn('check_missing_purpose',names)

    def test_one_schema_restatement_uses_original_input_without_failed_body(self):
        bad={**self.requirement(),'type':'DO_NOT_FORWARD_SELECT_7'}
        a,_,seen=self.run_case([
            {'role':'assistant','content':json.dumps(bad)},
            {'role':'assistant','content':json.dumps(self.requirement())}],max_requests=2)
        self.assertEqual(len(seen),2);self.assertEqual(seen[1][1],[])
        self.assertNotIn('DO_NOT_FORWARD_SELECT_7',json.dumps(seen[1][0]))
        self.assertIsNotNone(a.business_request)
        self.assertEqual(a.last_response['execution']['model_requests'],2)
        self.assertEqual(a.last_response['execution']['actual_tool_calls'],0)

    def test_schema_restatement_has_one_attempt_and_needs_existing_budget_slot(self):
        bad={'role':'assistant','content':json.dumps({**self.requirement(),'type':'read'})}
        for count,replies in ((1,[bad]),(9,[bad,bad])):
            with self.subTest(max_requests=count):
                a,_,seen=self.run_case(replies,max_requests=count)
                self.assertEqual(len(seen),1 if count==1 else 2)
                self.assertIsNone(a.business_request)
                self.assertEqual(a.last_response['execution']['actual_tool_calls'],0)

    def test_duplicate_scope_and_semantic_ambiguity_do_not_restate_structure(self):
        duplicate='{"kind":"read","kind":"read","targets":[],"unresolved":[]}'
        mismatch=self.requirement();mismatch['targets'][0]['company_quote']='金额和张数'
        unresolved=self.requirement();unresolved['unresolved']=['i1.seller']
        for body in (duplicate,json.dumps(mismatch),json.dumps(unresolved)):
            with self.subTest(body=body):
                a,_,seen=self.run_case([{'role':'assistant','content':body}])
                self.assertEqual(len(seen),1)
                self.assertEqual(a.last_response['execution']['actual_tool_calls'],0)

    def test_schema_restatement_cannot_switch_to_legacy_route_or_modify_invoice(self):
        bad={'role':'assistant','content':json.dumps({**self.requirement(),'type':'read'})}
        for second in ({'role':'assistant','content':'{"kind":"legacy"}'},
                       {'role':'assistant','tool_calls':[tool('forbidden','change_invoice',company_id='C001')]}):
            with self.subTest(second=second):
                a,_,seen=self.run_case([bad,second])
                self.assertEqual(len(seen),2)
                self.assertEqual(a.last_response['execution']['actual_tool_calls'],0)
                self.paired(a)
                self.assertFalse(a.pending_edit)
