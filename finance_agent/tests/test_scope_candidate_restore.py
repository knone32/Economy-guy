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


if __name__=='__main__':unittest.main()
