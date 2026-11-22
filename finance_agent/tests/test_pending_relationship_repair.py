"""Program-only owner contracts. Scripted interpretation is not NLU/human approval."""
import copy,json,sqlite3,unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.intent_contract import BoundIntent
from app.invoice_action import change_invoice
from app.invoice_batch import run_invoice_batch
from app.pending_transition import request_change


def tool(args):
    return {'role':'assistant','tool_calls':[{'id':'proposal','type':'function',
        'function':{'name':'change_invoice','arguments':json.dumps(args,ensure_ascii=False)}}]}


class PendingRevisionRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.book=Path(self.tmp.name)/'fictional.sqlite'
        import_workspace(Path(__file__).parent/'fixtures/example.xlsx',self.book)
        self.agent=Agent('U001',self.book,lambda *_:{},mode='mock');self.agent.trace_id='turn'
        self.agent.context.display_ids=[]
        self.before=self.facts()
        self.pending=request_change({'company_id':'C001','field':'remark','new_value':'已与采购单核对'},None,
            actor='U001',book=self.book,current_id='initial',current_request='甲企业有张票仅把备注填“已与采购单核对”，票号稍后补。',business_continuation=True)
        # Exact execution proposal preserved in user ZIP trace.jsonl line 95.
        self.original={'company_id':'C001','year':2026,'month':9,'invoice_no':'F009',
            'field':'remark','new_value':'已与采购单核对','relation':'replace'}
    def tearDown(self):self.assertEqual(self.facts(),self.before)
    def facts(self):
        with closing(sqlite3.connect(self.book)) as db:return {t:db.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in ('invoices','invoice_audit')}
    def origin(self,text,relation='keep',field=None):
        return BoundIntent('amend','U001',str(self.book),self.agent.trace_id,text,
            {'field':field,'value_relation':relation},{'source':'independent_business_entry','field_quote':text if field else '', 'value_quote':text})
    def test_original_invalid_replace_preserves_active_remark_and_cancel_is_readonly(self):
        text='票号找到了，是F009，继续刚才的备注要求。';origin=self.origin(text)
        denied,state,proposal,reads=change_invoice(self.agent,self.original,self.pending,text,revision_origin=origin)
        self.assertEqual(denied['status'],'SCOPE_MISMATCH');self.assertIsNone(proposal);self.assertFalse(reads)
        self.assertEqual(set(denied['evidence']['conflicting_slots']),{'year','month'})
        self.assertEqual(state['change'],self.pending['change'])
        result,_,proposal,reads=change_invoice(self.agent,{'invoice_no':'F009'},state,text,revision_origin=origin)
        self.assertIsNotNone(proposal,result);self.assertEqual(proposal['field'],'remark');self.assertEqual(proposal['new_value'],'已与采购单核对')
        self.assertEqual(tuple(proposal['invoice_nos']),('F009',));self.assertEqual(reads[0][0],'get_invoice')
        status,_=run_invoice_batch(self.agent,proposal['source_request'],proposal,
            approve_item=lambda _:False,approve_batch=lambda *_:False,
            checkpoint=lambda *_:self.fail('Offline cancellation must never reach commit checkpoint'))
        self.assertIn(status,{'CANCELLED','NOT_SUBMITTED'})
    def test_unverified_execution_replace_cannot_change_effective_state(self):
        text='F009。';args={k:v for k,v in self.original.items() if k not in {'year','month'}}
        result,state,proposal,_=change_invoice(self.agent,args,self.pending,text)
        self.assertEqual(result['status'],'AMBIGUOUS');self.assertEqual(state['change'],self.pending['change']);self.assertIsNone(proposal)
        self.assertFalse(result['evidence']['business_state_updated'])
    def test_confirmed_withdrawal_and_field_replacement_never_revive_old_value(self):
        for relation,field,text in [('withdraw',None,'旧备注内容撤回，等我重新给内容。'),
                                    ('replace','purpose','改为填写用途，具体用途稍后给。')]:
            with self.subTest(relation=relation):
                args={**self.original,'field':field or 'remark'}
                result,state,proposal,_=change_invoice(self.agent,args,self.pending,text,revision_origin=self.origin(text,relation,field))
                self.assertIsNone(proposal);self.assertNotIn('new_value',state['change'])
                chosen='F009。';result,state,proposal,_=change_invoice(self.agent,{'invoice_no':'F009'},state,chosen,revision_origin=self.origin(chosen))
                self.assertIsNone(proposal);self.assertNotIn('new_value',state['change'])
    def test_confirmed_new_value_and_clear_survive_rejected_proposal(self):
        for relation,text,new in [('replace','备注换成“复核后归档”，编号稍后补。','复核后归档'),('clear','把备注明确清空，编号稍后补。','')]:
            with self.subTest(relation=relation):
                args={**self.original,'new_value':new};args.pop('invoice_no')
                result,state,proposal,_=change_invoice(self.agent,args,self.pending,text,revision_origin=self.origin(text,relation))
                self.assertIsNone(proposal);self.assertEqual(state['change'].get('new_value'),[new])
                chosen='F009。';result,_,proposal,_=change_invoice(self.agent,{'invoice_no':'F009'},state,chosen,revision_origin=self.origin(chosen))
                if proposal:self.assertEqual(proposal['new_value'],new)
    def test_agent_correction_uses_preproposal_state_and_independent_revision(self):
        for relation,text in [('keep','F009，继续刚才的备注。'),('withdraw','撤回旧备注，F009 仍等我给新内容。')]:
            with self.subTest(relation=relation):
                replies=iter([{'role':'assistant','content':json.dumps({'kind':'legacy','value_relation':relation,'value_quote':text},ensure_ascii=False)},
                    tool(self.original),tool({'invoice_no':'F009'})])
                agent=Agent('U001',self.book,lambda *_:next(replies),mode='mock');agent.restore_invoice_candidate(copy.deepcopy(self.pending))
                agent.ask(text)
                if relation=='keep':self.assertEqual(agent.last_response['invoice_change']['new_value'],'已与采购单核对')
                else:self.assertIsNone(agent.last_response.get('invoice_change'));self.assertNotIn('new_value',agent.pending_intent['change'])
    def test_independently_known_field_without_invoice_only_waits(self):
        text='甲企业有张票要改备注，具体哪张还没确定，内容也稍后补。'
        outcome,state,proposal,reads=change_invoice(self.agent,{},None,text,revision_origin=self.origin(text,'replace','remark'))
        self.assertEqual(outcome['status'],'WAITING_USER');self.assertEqual(state['change'],{'field':['remark']})
        self.assertEqual(state['provenance']['field']['kind'],'independent_business_field_intent')
        self.assertIsNone(proposal);self.assertEqual(reads,[])


class MatterOwnershipRepairTests(unittest.TestCase):
    setUp=PendingRevisionRepairTests.setUp
    tearDown=PendingRevisionRepairTests.tearDown
    facts=PendingRevisionRepairTests.facts
    origin=PendingRevisionRepairTests.origin
    def matter_origin(self,text,matter='continue',value='keep',field=None):
        origin=self.origin(text,value,field)
        return BoundIntent(origin.action,origin.actor,origin.workbook,origin.turn_id,origin.request,
            {**origin.target,'matter_relation':matter},{**origin.sources,'matter_quote':text})
    def seed_set(self):
        from app.business_sql import BusinessSQL
        from app.provenance import ScopeProof
        self.agent=Agent('U001',self.book,lambda *_:{},mode='mock');self.agent.trace_id='display-'+str(len(self.facts()['invoice_audit']))
        self.agent.context.display_ids=[]
        scope={'company_id':['C001'],'periods':[(2026,9)]}
        with closing(BusinessSQL(self.book,'U001',ScopeProof('U001',scope,dict.fromkeys(scope,'user_current')))) as db:
            actual,data,_=db.query("SELECT company_id,invoice_no,invoice_date,amount_cents,remark FROM invoices WHERE invoice_no IN ('F002','F004')")
        result={'ok':True,'status':'SUCCESS','data':data,'evidence':{'source':'current_sqlite','scope':actual,'query_scope':data.pop('query_scope')}}
        self.agent.record_query_display([('query_business_sql',result)])
        text='甲企业刚才这两张里选一张改备注为“集合内待核”，等我选票。'
        outcome,state,proposal,_=change_invoice(self.agent,{'field':'remark','new_value':'集合内待核'},None,text,
            revision_origin=self.matter_origin(text,value='replace',field='remark'))
        self.assertIsNone(proposal);self.assertIn('reference_collection',state)
        return state
    def test_gate_before_collection_and_continue_still_selects_only_original_member(self):
        state=self.seed_set();before=copy.deepcopy(state)
        text='另外新办甲企业F008，备注填“新事项”。'
        result,held,proposal,reads=change_invoice(self.agent,{'company_id':'C001','invoice_no':'F008','field':'remark','new_value':'新事项'},state,text,
            revision_origin=self.matter_origin(text,'new','replace','remark'))
        self.assertTrue(result['evidence']['matter_disposition_required']);self.assertEqual(held,before);self.assertIsNone(proposal);self.assertFalse(reads)
        unclear='F008。'
        result,held,proposal,reads=change_invoice(self.agent,{'invoice_no':'F008','relation':'replace'},state,unclear,
            revision_origin=self.origin(unclear))
        self.assertTrue(result['evidence']['matter_disposition_required']);self.assertEqual(held,before);self.assertFalse(reads)
        limited='就在这两张里的F008。'
        result,held,proposal,_=change_invoice(self.agent,{'invoice_no':'F008','relation':'replace'},state,limited,revision_origin=self.matter_origin(limited))
        self.assertEqual(result['status'],'AMBIGUOUS');self.assertIsNone(proposal)
        selected='选F004，沿用刚才的备注。'
        result,_,proposal,_=change_invoice(self.agent,{'invoice_no':'F004'},state,selected,revision_origin=self.matter_origin(selected))
        self.assertIsNotNone(proposal,result);self.assertEqual(tuple(proposal['invoice_nos']),('F004',));self.assertEqual(proposal['new_value'],'集合内待核')
        from app.references import invalidate_references
        invalidate_references(self.book,'U001')
        result,_,proposal,_=change_invoice(self.agent,{'invoice_no':'F004'},state,selected,revision_origin=self.matter_origin(selected))
        self.assertNotEqual(result['status'],'SUCCESS');self.assertIsNone(proposal)
    def test_original_store_disposition_then_new_preview_preserves_old_record(self):
        from app.session_store import SessionStore
        from app.session_host import SessionHost
        for disposition in ('pause','cancel'):
            with self.subTest(disposition=disposition):
                state=self.seed_set();store=SessionStore(Path(self.tmp.name)/(disposition+'.sqlite'),self.book,'U001')
                store.set_invoice_pending(state,state='ACTIVE');captured=[];replies=[]
                def model(*_):return replies.pop(0)
                host=SessionHost(store,lambda actor,book:Agent(actor,book,model,mode='mock'),confirm=lambda payload:(captured.append(payload) or False))
                try:
                    old_token=store.invoice_token
                    text='另外新办甲企业F008，备注填“新事项”。'
                    semantic={'role':'assistant','content':json.dumps({'kind':'legacy','field':'remark','field_quote':'备注填“新事项”',
                        'value_relation':'replace','value_quote':text,'matter_relation':'new','matter_quote':text},ensure_ascii=False)}
                    args={'company_id':'C001','invoice_no':'F008','field':'remark','new_value':'新事项'}
                    replies[:]=[semantic,tool(args)]
                    gated=host.send_message(text,expected=host.snapshot()['context']);self.assertFalse(captured);self.assertEqual(store.invoice_token[0],old_token[0])
                    if disposition=='pause':host.pause_current(expected=gated['context'])
                    else:host.cancel_current(expected=gated['context'])
                    with store.connection() as db:old=dict(db.execute('SELECT * FROM invoice_candidates WHERE id=?',(old_token[0],)).fetchone())
                    self.assertEqual(old['state'],'PAUSED' if disposition=='pause' else 'CANCELLED')
                    if disposition=='pause':self.assertTrue(any(row['id']==old_token[0] for row in store.list_invoice_candidates()))
                    replies[:]=[semantic,tool(args)]
                    view=host.send_message(text,expected=host.snapshot()['context']);self.assertEqual(len(captured),1,view)
                    preview=captured[0]['snapshot']['preview'];self.assertEqual(preview[0]['invoice_no'],'F008');self.assertEqual(preview[0]['new_value'],'新事项')
                    with store.connection() as db:retained=dict(db.execute('SELECT * FROM invoice_candidates WHERE id=?',(old_token[0],)).fetchone())
                    self.assertEqual(retained,old);self.assertNotEqual(store.invoice_token[0],old_token[0])
                finally:store.close()
