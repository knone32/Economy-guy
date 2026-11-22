"""New scope/recovery boundaries only; program evidence, no model or approval."""
import copy,json,sqlite3,unittest
from contextlib import closing
from unittest.mock import patch
from app.agent import Agent
from app.intent_contract import BoundIntent
from app.invoice_action import change_invoice
from tests import test_pending_relationship_repair as repair


class CrossMonthScopeTests(unittest.TestCase):
    setUp=repair.PendingRevisionRepairTests.setUp
    tearDown=repair.PendingRevisionRepairTests.tearDown
    facts=repair.PendingRevisionRepairTests.facts

    def displayed(self, months=((8,'F011'),(9,'F001'))):
        from app.business_sql import BusinessSQL
        from app.provenance import ScopeProof
        results=[]
        for month,number in months:
            scope={'company_id':['C001'],'periods':[(2026,month)]}
            with closing(BusinessSQL(self.book,'U001',ScopeProof('U001',scope,dict.fromkeys(scope,'user_current')))) as db:
                sql=("SELECT company_id,invoice_no,invoice_date,amount_cents,remark FROM invoices "
                     f"WHERE company_id='C001' AND invoice_no='{number}' AND invoice_date>='2026-{month:02d}-01' "
                     f"AND invoice_date<'2026-{month+1:02d}-01'")
                actual,data,_=db.query(sql)
                results.append(('query_business_sql',{'ok':True,'status':'SUCCESS','data':data,
                    'evidence':{'source':'current_sqlite','scope':actual,'query_scope':data.pop('query_scope')}}))
        self.agent.trace_id='actual-two-month-display'
        self.agent.record_query_display(results)
        return results

    def origin(self,text,relation='continue',value='keep',field=None,reference='displayed'):
        return BoundIntent('amend','U001',str(self.book),self.agent.trace_id,text,
            {'matter_relation':relation,'value_relation':value,'field':field,'reference_relation':reference},
            {'source':'independent_business_entry','matter_quote':text,'value_quote':text,
             'field_quote':text if field else '', 'reference_quote':text})

    def waiting(self):
        self.displayed()
        text='只从刚才候选里的9月票中选一张，备注改成“跨月候选核对”，等我选票。'
        result,state,proposal,reads=change_invoice(self.agent,{'field':'remark','new_value':'跨月候选核对'},None,text,
            revision_origin=self.origin(text,'new','replace','remark'))
        self.assertEqual(result['status'],'WAITING_USER',result)
        self.assertEqual(state['scope']['periods'],[(2026,9)])
        self.assertEqual(state['change']['new_value'],['跨月候选核对'])
        self.assertNotIn('invoice_no',state['scope'])
        self.assertIn('reference_collection',state)
        self.assertFalse(reads);self.assertIsNone(proposal)
        return state

    def test_month_and_value_survive_then_wrong_month_is_rejected(self):
        state=self.waiting()
        text='选F011，备注沿用。'
        result,state,proposal,_=change_invoice(self.agent,{'invoice_no':'F011'},state,text,
            revision_origin=self.origin(text))
        self.assertEqual(result['status'],'SCOPE_MISMATCH')
        self.assertEqual(state['scope']['month'],[9])
        self.assertEqual(state['change']['new_value'],['跨月候选核对'])
        self.assertIsNone(proposal)
        text='那就选F001，仍用前面的备注。'
        result,_,proposal,reads=change_invoice(self.agent,{'invoice_no':'F001'},state,text,
            revision_origin=self.origin(text))
        self.assertIsNotNone(proposal,result)
        self.assertEqual(tuple(proposal['invoice_nos']),('F001',))
        self.assertEqual(proposal['new_value'],'跨月候选核对')
        self.assertEqual(reads[0][1]['data']['invoice_date'],'2026-09-01')


class MatterCandidateRestoreTests(unittest.TestCase):
    setUp=CrossMonthScopeTests.setUp
    tearDown=CrossMonthScopeTests.tearDown
    facts=CrossMonthScopeTests.facts
    displayed=CrossMonthScopeTests.displayed
    origin=CrossMonthScopeTests.origin
    waiting=CrossMonthScopeTests.waiting

    def host_with_paused_matter(self):
        from app.session_store import SessionStore
        from app.session_host import SessionHost
        state=self.waiting()
        store=SessionStore(self.book.parent/'sessions.sqlite',self.book,'U001')
        self.addCleanup(store.close)
        store.set_invoice_pending(state,state='ACTIVE')
        replies=[];previews=[]
        host=SessionHost(store,lambda actor,book:Agent(actor,book,lambda *_:replies.pop(0),mode='mock'),
            confirm=lambda payload:(previews.append(payload) or False))
        # A prior unapproved prepare has no right to survive pause/resume.
        from app.updates import prepare_invoice_update
        session=host.agent.update_session
        session.begin_turn('甲企业F001备注改为旧预览内容。',allow_prepare=True)
        prepared=prepare_invoice_update(self.book,session,'C001','F001','remark','旧预览内容')
        self.assertEqual(prepared['status'],'WAITING_CONFIRMATION')
        old=next(iter(session.drafts.values()))
        host.pause_current(expected=host.snapshot()['context'])
        self.assertFalse(session.drafts);self.assertFalse(session.confirmations)
        return host,store,state,replies,previews,old

    def test_resume_revalidates_own_set_and_new_selection_ignores_other_matter(self):
        from app.references import display_collection,get_invoice
        from app.updates import confirm_draft
        host,store,old_state,replies,previews,old=self.host_with_paused_matter()
        token=store.invoice_token
        host.new_conversation(expected=host.snapshot()['context'])
        self.agent=host.agent
        self.displayed(((8,'F012'),(9,'F004')))
        host.cancel_current(expected=host.snapshot()['context'])
        self.assertTrue(host.agent.context.references_blocked)
        with patch('app.references.get_invoice',wraps=get_invoice) as reread:
            view=host.resume_candidate(*token,expected=host.snapshot()['context'])
        read_keys={(call.args[2],call.args[3]) for call in reread.call_args_list}
        self.assertEqual(read_keys,{('C001','F001'),('C001','F011')})
        state=host.agent.pending_intent
        self.assertNotEqual(state['reference_collection'],old_state['reference_collection'])
        available=display_collection(self.book,'U001',**state['reference_collection'])
        self.assertEqual(available['status'],'SUCCESS')
        self.assertEqual({e['key']['invoice_no'] for e in available['data']},{'F001','F011'})
        self.assertTrue(host.agent.context.references_blocked,'Other historical references must stay blocked')
        self.assertEqual(state['scope']['month'],[9])
        self.assertFalse(host.agent.update_session.confirmations)
        self.assertFalse(confirm_draft(host.agent.update_session,old.request_id,old.fingerprint()))
        text='选F001，沿用本事项备注。'
        replies[:]=[{'role':'assistant','content':json.dumps({'kind':'legacy','turn_action':'continue',
            'action_reason':'continue_matter','matter_relation':'continue','matter_quote':text,
            'value_relation':'keep','value_quote':'沿用本事项备注',
            'reference_relation':'displayed','reference_quote':text},ensure_ascii=False)},repair.tool({'invoice_no':'F001'})]
        host.send_message(text,expected=view['context'])
        self.assertEqual(len(previews),1)
        row=previews[0]['snapshot']['preview'][0]
        self.assertEqual((row['invoice_no'],row['new_value']),('F001','跨月候选核对'))
        self.assertFalse(host.agent.update_session.confirmations)

    def test_changed_member_or_revoked_permission_does_not_resume(self):
        from app.references import display_collection
        host,store,state,_,_,_=self.host_with_paused_matter()
        token=store.invoice_token
        with store.connection() as db:
            before=dict(db.execute('SELECT * FROM invoice_candidates WHERE id=?',(token[0],)).fetchone())
        with closing(sqlite3.connect(self.book)) as db,db:
            db.execute("UPDATE invoices SET invoice_date='2026-10-01' WHERE company_id='C001' AND invoice_no='F001'")
        try:
            with self.assertRaises(ValueError):host.resume_candidate(*token,expected=host.snapshot()['context'])
            self.assertIsNone(host.agent.pending_intent)
            self.assertEqual(store.invoice_token,token)
            with store.connection() as db:
                self.assertEqual(dict(db.execute('SELECT * FROM invoice_candidates WHERE id=?',(token[0],)).fetchone()),before)
        finally:
            with closing(sqlite3.connect(self.book)) as db,db:
                db.execute("UPDATE invoices SET invoice_date='2026-09-01' WHERE company_id='C001' AND invoice_no='F001'")
        with closing(sqlite3.connect(self.book)) as db,db:
            db.execute("UPDATE permissions SET can_modify=0 WHERE user_id='U001' AND company_id='C001'")
        try:
            with self.assertRaises((ValueError,PermissionError)):
                host.resume_candidate(*token,expected=host.snapshot()['context'])
            self.assertIsNone(host.agent.pending_intent)
            self.assertEqual(store.invoice_token,token)
        finally:
            with closing(sqlite3.connect(self.book)) as db,db:
                db.execute("UPDATE permissions SET can_modify=1 WHERE user_id='U001' AND company_id='C001'")
        self.assertNotEqual(display_collection(self.book,'U001',**state['reference_collection'])['status'],'SUCCESS')
        # The new cross-file transaction must not leak rebound anchors when
        # persisting the candidate revision fails after anchor creation.
        with closing(sqlite3.connect(self.book)) as db:
            anchors_before=db.execute('SELECT COUNT(*) FROM reference_anchors').fetchone()[0]
        with store.connection() as db:
            db.execute("CREATE TRIGGER reject_resume BEFORE UPDATE ON invoice_candidates BEGIN SELECT RAISE(ABORT,'isolated persistence failure'); END")
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                host.resume_candidate(*token,expected=host.snapshot()['context'])
            self.assertEqual(store.invoice_token,token)
            with store.connection() as db:
                self.assertEqual(dict(db.execute('SELECT * FROM invoice_candidates WHERE id=?',(token[0],)).fetchone()),before)
            with closing(sqlite3.connect(self.book)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM reference_anchors').fetchone()[0],anchors_before)
            self.assertIsNone(host.agent.pending_intent)
        finally:
            with store.connection() as db:db.execute('DROP TRIGGER reject_resume')


if __name__=='__main__':unittest.main()
