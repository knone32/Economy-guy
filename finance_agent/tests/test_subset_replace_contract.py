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


def envelope(value):return {'role':'assistant','content':json.dumps(value,ensure_ascii=False)}


class WithdrawalReplacementTests(unittest.TestCase):
    initial='甲企业有一张发票要补用途，我打算填「培训资料印制」。票号还在找。'
    amended='用途那项撤下，别动它。我其实是要补备注，内容填「已比对快递存根」。票号等我一下。'

    def setUp(self):
        from app.gui_delivery import demo_paths
        from app.gui_host import GuiHost
        self.tmp=TemporaryDirectory()
        self.addCleanup(lambda:(gc.collect(),self.tmp.cleanup()))
        self.book,sessions=demo_paths(Path(self.tmp.name)/'demo')
        self.q=deque()
        self.host=GuiHost(self.book,'U001',session_path=sessions,mode='mock',model=lambda *_:self.q.popleft())
        self.addCleanup(self.host.close)
        self.before=self.facts()
        self.q.extend([envelope({'kind':'legacy','field':'purpose','field_quote':'补用途',
            'matter_relation':'new','matter_quote':'甲企业有一张发票要补用途','reference_relation':'none',
            'reference_quote':'票号还在找','pending_change':{'field':'purpose','new_value':'培训资料印制',
                'source':{'kind':'current','quote':'培训资料印制'}}}),
            scope_tests.repair.tool({'company_id':'C001','field':'purpose','new_value':'培训资料印制'})])
        self.host.send(self.initial)

    def facts(self):
        with closing(sqlite3.connect(self.book)) as db:
            return {t:db.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in ('invoices','invoice_audit')}

    def tearDown(self):self.assertEqual(self.facts(),self.before)

    def route(self,relation='replace',exact=True,change=True):
        result={'kind':'legacy','turn_action':'continue','action_reason':'await_value','field':'remark',
            'field_quote':'我其实是要补备注','value_relation':relation,'value_quote':'用途那项撤下，别动它',
            'matter_relation':'continue','matter_quote':'我其实是要补备注' if exact else '我其实是要补备注……票号等我一下。',
            'reference_relation':'unclear','reference_quote':'票号等我一下'}
        if change:result['pending_change']={'field':'remark','new_value':'已比对快递存根',
            'source':{'kind':'current','quote':'补备注，内容填「已比对快递存根」'}}
        return result

    def assert_held(self,snapshot):
        state=self.host.host.agent.pending_intent
        self.assertEqual(state['change'],{})
        self.assertEqual(state['on_hold']['change']['field'],['purpose'])
        self.assertTrue(state.get('blocked_reason'))
        self.assertNotIn('field',(snapshot.get('pending') or {}).get('known',{}))
        self.assertFalse(snapshot.get('preview'))

    def test_original_forged_quote_rejected_and_old_values_cannot_resume_with_ticket_only(self):
        self.q.append(envelope(self.route('withdraw',exact=False)))
        view=self.host.send(self.amended);self.assert_held(view)
        self.assertEqual(self.host.host.agent.last_response['execution']['actual_tool_calls'],0)
        self.q.extend([envelope({'kind':'legacy','value_relation':'keep','value_quote':'F009',
            'matter_relation':'continue','matter_quote':'F009'}),scope_tests.repair.tool({'invoice_no':'F009'})])
        view=self.host.send('F009')
        self.assertNotIn('new_value',(view.get('pending') or {}).get('known',{}))
        self.assertFalse(view.get('preview'))

    def test_withdraw_and_supplied_new_value_is_contradictory_not_silent_value_loss(self):
        self.q.append(envelope(self.route('withdraw')))
        view=self.host.send(self.amended);self.assert_held(view)
        self.assertEqual(self.host.host.agent.last_response['execution']['actual_tool_calls'],0)

    def test_invalid_semantic_outputs_hold_old_change_without_overwriting_the_hold(self):
        self.q.append(scope_tests.repair.tool({'field':'purpose','new_value':'培训资料印制'}))
        self.assert_held(self.host.send(self.amended))
        self.q.append({'role':'assistant','content':'not JSON'})
        self.assert_held(self.host.send(self.amended))

    def test_replace_preserves_new_remark_then_bare_ticket_fresh_preview(self):
        self.q.extend([envelope(self.route()),envelope({'kind':'clarification','text':'请选票。','missing_fields':['invoice_no']})])
        view=self.host.send(self.amended)
        self.assertEqual(view['pending']['known']['field'],'remark')
        self.assertEqual(view['pending']['known']['new_value'],'已比对快递存根')
        self.q.extend([envelope({'kind':'legacy','value_relation':'keep','value_quote':'F009',
            'matter_relation':'continue','matter_quote':'F009'}),scope_tests.repair.tool({'invoice_no':'F009'})])
        view=self.host.send('F009')
        self.assertEqual(len(view['preview']['items']),1)
        self.assertEqual(view['preview']['items'][0]['new_value'],'已比对快递存根')
        out=self.host.cancel_preview(view['preview']['id'],context=view['context'])
        self.assertEqual(out['receipt']['status'],'CANCELLED')

    def test_conflicting_execution_holds_old_change_instead_of_continuing_it(self):
        self.q.extend([envelope(self.route()),scope_tests.repair.tool({'field':'purpose','new_value':'培训资料印制'})])
        view=self.host.send(self.amended)
        self.assert_held(view)
        self.assertEqual(self.host.host.agent.last_response['execution']['stop_reason'],'INVALID_ARGUMENTS')

    def test_withdraw_without_new_value_leaves_only_new_field_waiting(self):
        self.q.extend([envelope(self.route('withdraw',change=False)),
            envelope({'kind':'clarification','text':'请补内容。','missing_fields':['new_value']})])
        view=self.host.send('用途那项撤下，别动它。我其实是要补备注，内容稍后再给。票号等我一下。')
        self.assertEqual(view['pending']['known']['field'],'remark')
        self.assertNotIn('new_value',view['pending']['known'])
        self.assertFalse(view.get('preview'))


if __name__=='__main__':unittest.main()
