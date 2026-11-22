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
