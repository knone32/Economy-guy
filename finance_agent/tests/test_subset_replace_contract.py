"""Two new failure chains only. Scripted/replayed replies are program evidence."""
import copy,gc,json,sqlite3,unittest
from collections import deque
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from app.agent import Agent
from app.context import ContextBuilder
from app.invoice_action import change_invoice
from app.references import display_collection
from tests import test_scope_candidate_restore as scope_tests


class CompletePeriodSubsetTests(unittest.TestCase):
    setUp=scope_tests.CrossMonthScopeTests.setUp
    tearDown=scope_tests.CrossMonthScopeTests.tearDown
    facts=scope_tests.CrossMonthScopeTests.facts
    displayed=scope_tests.CrossMonthScopeTests.displayed
    origin=scope_tests.CrossMonthScopeTests.origin

    def test_subset_keeps_actual_candidates_and_new_month_still_restricts_selection(self):
        self.agent.context.begin('甲企业2026年8月F015和2026年9月F003',1)
        self.displayed(((8,'F015'),(9,'F003')))
        words='就在这两张里挑九月那张，备注写成「部门已复核原件」。先记着，票号让我定。'
        self.agent.context.begin(words,2,explicit={'company_id':['C001'],'year':[2026],'month':[9],'periods':[[2026,9]]})
        self.assertEqual(display_collection(self.book,'U001',self.agent.context.display_ids)['status'],'SUCCESS')
        self.assertEqual(list(map(tuple,self.agent.context.scope['periods'])),[(2026,9)])
        outcome,state,proposal,reads=change_invoice(self.agent,{'company_id':'C001','year':2026,'month':9,
            'field':'remark','new_value':'部门已复核原件'},None,words,
            revision_origin=self.origin(words,'new','replace','remark'))
        self.assertEqual(outcome['status'],'WAITING_USER',outcome)
        self.assertFalse(reads);self.assertIsNone(proposal)
        for number,expected in [('F015','SCOPE_MISMATCH'),('F003','WAITING_CONFIRMATION')]:
            text='选'+number+'，沿用本次备注。'
            outcome,state,proposal,reads=change_invoice(self.agent,{'invoice_no':number},state,text,
                revision_origin=self.origin(text))
            self.assertEqual(outcome['status'],expected,outcome)
            if proposal:
                self.assertEqual(proposal['new_value'],'部门已复核原件')
            else:
                self.assertEqual(state['scope']['month'],[9])
                self.assertEqual(state['change']['new_value'],['部门已复核原件'])

    def test_period_pairs_do_not_become_cartesian_products(self):
        self.displayed(((8,'F015'),(9,'F003')))
        ctx=self.agent.context
        ctx.scope={'company_id':['C001'],'year':[2026,2027],'month':[8,9],'periods':[[2026,8],[2027,9]]}
        ctx.sources=dict.fromkeys(ctx.scope,'session_confirmed')
        ctx.begin('甲企业2026年9月的发票',2)
        self.assertEqual(display_collection(self.book,'U001',ctx.display_ids)['status'],'NOT_FOUND')


if __name__=='__main__':unittest.main()
