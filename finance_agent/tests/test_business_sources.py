"""Program contracts with scripted model decisions; NOT NLU or Live scores."""
from contextlib import closing
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from textual.widgets import Select

from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.invoice_batch import run_invoice_batch
from app.model_config import DEFAULT_TEMPLATE
from app.pending_transition import request_change, PendingRequestError
from app.tui import AgentWorkspace
from app.tui_screens import Approval
from tests.test_model_intent import call
from tests.test_sql_invoice_selection import snapshot
from tests.test_tui_p0 import FIXTURE
from tests import test_tui_p0


START = '乙企业2026年9月有一张票的用途要调整，请按“生产资料领用”来办，发票编号我稍后找给你。'
CORRECTION = '改一下要求：用途保持原状，只动备注，内容是“季度交接待核”。票号还没找到，仍先等我补。'
TARGET = '找着了，F006。照刚才改定的要求出正式预览，让我核对原值和新值。'


class BusinessSourceTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.book = Path(temp.name) / 'fixture.sqlite3'
        import_workspace(FIXTURE,self.book)
        self.before = snapshot(self.book)
        self.agent = Agent('U001',self.book,lambda *_:call('change_invoice',{}),
            mode='mock',trace_path=self.book.with_suffix('.jsonl'))

    def tearDown(self):
        self.assertEqual(snapshot(self.book),self.before,'No test approves a write')

    def ask(self,text,**args):
        self.agent.model = lambda *_:call('change_invoice',args)
        return self.agent.ask(text)

    def start(self):
        self.ask(START,company_id='C002',year=2026,month=9,field='purpose',new_value='生产资料领用')
        self.assertEqual(self.agent.pending_intent['change']['field'],['purpose'])

    def preview(self):
        plan = self.agent.last_response.get('invoice_change')
        self.assertIsNotNone(plan)
        seen=[]
        def reject(body):
            seen.append(body)
            return False
        run_invoice_batch(self.agent,plan['source_request'],plan,
            approve_batch=reject,approve_item=reject,
            checkpoint=lambda *_:self.fail('No confirmed transaction is allowed'))
        self.assertEqual(len(seen),1)
        return plan,seen[0]

    def test_public_live_correction_then_target_reaches_real_preview_without_write(self):
        self.start()
        self.ask(CORRECTION,company_id='C002',year=2026,month=9,field='remark',new_value='季度交接待核')
        state=deepcopy(self.agent.pending_intent)
        self.assertEqual(state['change'],{'field':['remark'],'new_value':['季度交接待核']})
        self.assertEqual(state['superseded']['change']['field'],['purpose'])
        origin=state['provenance']['new_value']; lo,hi=origin['span']
        self.assertEqual(CORRECTION[lo:hi],'季度交接待核')
        self.assertEqual(origin['message_sha256'],sha256(CORRECTION.encode()).hexdigest())
        with closing(sqlite3.connect(self.book)) as db:
            purpose,remark=db.execute("SELECT purpose,remark FROM invoices WHERE company_id=? AND invoice_no=?",('C002','F006')).fetchone()
        self.ask(TARGET,invoice_no='F006')
        plan,body=self.preview()
        self.assertEqual((plan['company_id'],plan['invoice_nos'],plan['field'],plan['new_value']),
                         ('C002',('F006',),'remark','季度交接待核'))
        self.assertIn('原值　'+remark,body); self.assertIn('新值　季度交接待核',body)
        self.assertIsNone(purpose)

    def test_rejected_replacement_cannot_leave_old_change_executable(self):
        self.start()
        reply=self.ask('旧的用途要求撤掉。备注内容稍后补。',relation='replace',field='remark',new_value='编造的新值')
        self.assertIn('新内容缺少',reply)
        self.assertNotIn('核对企业',reply)
        self.assertNotIn('new_value',self.agent.pending_intent['change'])
        self.ask('票号F006，先核对。',invoice_no='F006')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))
        self.assertEqual(self.agent.pending_intent['change'],{'field':['remark']})

    def test_replace_unknown_content_then_supply_it(self):
        self.start()
        self.ask('前一要求作废，改备注，内容稍后给。',relation='replace',field='remark')
        self.ask('是F006。',invoice_no='F006')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))
        self.ask('填写内容：“内部复核”；给我预览。',new_value='内部复核')
        self.assertEqual(self.preview()[0]['new_value'],'内部复核')

    def test_value_reference_can_cross_field_only_when_explicit(self):
        for ref in (False,True):
            self.agent.cancel_update(); self.start()
            args={'field':'remark'}
            if ref:args['value_ref']='previous'
            self.ask('用途不改；之前给的内容写进备注。',**args)
            self.ask('F006。',invoice_no='F006')
            if ref:
                self.assertEqual(self.preview()[0]['new_value'],'生产资料领用')
            else:self.assertIsNone(self.agent.last_response.get('invoice_change'))

    def test_resubmitted_old_value_requires_a_reference_and_never_auto_wins(self):
        self.start()
        self.ask('票号F006，新用途另定为“设备维护”，给我看预览。',
            invoice_no='F006',field='purpose',new_value='生产资料领用')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))
        self.assertNotIn('new_value',self.agent.pending_intent['change'])
        self.agent.cancel_update(); self.start()
        self.ask('票号F006，其余照上一要求。',invoice_no='F006',field='purpose',
            new_value='生产资料领用',value_ref='previous')
        self.assertEqual(self.preview()[0]['new_value'],'生产资料领用')

    def test_ambiguous_choices_suspend_and_do_not_select_first_or_last(self):
        self.start()
        self.ask('用途填“会议”还是备注填“待核”，我没决定，先别沿用原要求。',relation='clarify')
        self.assertEqual(self.agent.pending_intent['blocked_reason'],'ambiguous_business_choice')
        self.assertNotIn('new_value',self.agent.pending_intent['change'])
        self.ask('F006。',invoice_no='F006')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))

    def test_reading_quoted_modification_does_not_replace_existing_pending(self):
        self.start(); previous=deepcopy(self.agent.pending_intent)
        outputs=iter([call('get_invoice',{'company_id':'C001','invoice_no':'F010'}),
            {'role':'assistant','content':'{"kind":"information","text":"本次只查询现有记录。"}'}])
        self.agent.model=lambda *_:next(outputs)
        self.agent.ask('同事写的“备注改成加急归档”不等于我让你改。请核甲企业2026年9月F010的用途和备注现在各是什么，这次仅查询，不要发起变更。')
        self.assertEqual(self.agent.pending_intent,previous)
        self.assertIsNone(self.agent.last_response.get('invoice_change'))
        self.assertTrue(any(n=='get_invoice' and r['status']=='SUCCESS' for n,r in self.agent.last_response['tool_results']))

    def test_missing_value_unknown_parameters_and_wrong_slot_cannot_preview(self):
        for args in ({'field':'remark','new_value':'不存在的内容'},
                     {'field':'任意字段','new_value':'备注'},
                     {'field':'remark','new_value':'待核','confirmed':True}):
            self.agent.cancel_update(); self.start()
            self.ask('原用途要求作废；这次另办备注，细节未定。',**args)
            self.ask('F006。',invoice_no='F006')
            self.assertIsNone(self.agent.last_response.get('invoice_change'))
            self.assertNotIn('new_value',self.agent.pending_intent['change'])

    def test_company_object_period_and_permission_conflicts_stay_closed(self):
        for text,args in (
            ('甲企业F006。',{'company_id':'C002','invoice_no':'F006'}),
            ('F006。',{'invoice_no':'F010'}),
            ('在F002和F006中我还没选。',{'invoice_no':'F006'}),
            ('2025年8月或2026年9月，尚未决定。',{'year':2025,'month':9}),
            ('F012。',{'invoice_no':'F012'})):
            self.agent.cancel_update(); self.start(); self.ask(text,**args)
            self.assertIsNone(self.agent.last_response.get('invoice_change'))
            if args.get('year') == 2025:
                self.assertEqual(self.agent.pending_intent['scope']['periods'],[(2026,9)])
                self.assertEqual(self.agent.pending_intent['scope']['year'],[2026])
        denied=Agent('U002',self.book,lambda *_:call('change_invoice',{
            'company_id':'C001','field':'remark','new_value':'待核'}),mode='mock')
        denied.ask('甲企业备注填“待核”，还没票号。')
        self.assertIsNone(denied.pending_intent)

    def test_downstream_missing_invoice_does_not_resurrect_old_field(self):
        self.start()
        self.ask('改要求：备注填“复查”，票号F999。',field='remark',new_value='复查',invoice_no='F999')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))
        self.assertEqual(self.agent.pending_intent['change'],{'field':['remark'],'new_value':['复查']})
        self.ask('编号更正为F006。',invoice_no='F006')
        self.assertEqual(self.preview()[0]['field'],'remark')

    def test_read_pending_and_changed_actor_cannot_supply_change_sources(self):
        self.start(); previous=deepcopy(self.agent.pending_intent)
        for actor,book in (('U002',self.book),('U001',self.book.with_name('other.sqlite3'))):
            with self.assertRaises(PendingRequestError):
                request_change({},previous,actor=actor,book=book,current_id='other',
                    current_request='继续',business_continuation=True)
        previous.pop('business_action')
        state=request_change({},previous,actor='U001',book=self.book,current_id='other',
            current_request='我有一张票想改，细节还没提供。',business_continuation=True)
        self.assertFalse(state['scope']); self.assertFalse(state['change'])

    def test_cancel_and_clear_do_not_reuse_old_change(self):
        self.start(); self.agent.cancel_update()
        self.ask('F006。',invoice_no='F006')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))
        self.agent.cancel_update(); self.start()
        self.ask('用途不改了，备注清空。',relation='replace',field='remark',value_ref='clear')
        self.ask('F006。',invoice_no='F006')
        self.assertEqual(self.preview()[0]['new_value'],'')


class BusinessSourceWorkbenchTests(unittest.IsolatedAsyncioTestCase):
    """The actual workbench must mount its preview; only reject is exercised."""
    await_state=test_tui_p0.P0Test.await_state

    async def test_three_turn_correction_mounts_preview_and_rejects_without_write(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); book=root/'fixture.sqlite3'
            import_workspace(FIXTURE,book); before=snapshot(book)
            replies=iter([
                call('change_invoice',{'company_id':'C002','year':2026,'month':9,'field':'purpose','new_value':'生产资料领用'}),
                call('change_invoice',{'company_id':'C002','year':2026,'month':9,'field':'remark','new_value':'季度交接待核'}),
                call('change_invoice',{'invoice_no':'F006'})])
            app=AgentWorkspace(book,DEFAULT_TEMPLATE,root/'no-profiles.json',
                model=lambda *_:next(replies),trace_path=root/'trace.jsonl',session_path=root/'sessions.sqlite3')
            app.mode='mock'
            async with app.run_test(size=(150,42)) as pilot:
                app.screen.query_one('#login-user',Select).value='U001'
                await pilot.click('#sign-in')
                await self.await_state(pilot,lambda:app.user=='U001')
                for text in (START,CORRECTION):
                    count=len(app.records)
                    await test_tui_p0.P0Test.send(self,app,pilot,text)
                    await self.await_state(pilot,lambda:len(app.records)>count and not app.busy)
                    self.assertNotIsInstance(app.screen,Approval)
                await test_tui_p0.P0Test.send(self,app,pilot,TARGET)
                await self.await_state(pilot,lambda:isinstance(app.screen,Approval)
                    and app.screen.is_mounted and bool(app.screen.query('#cancel'))
                    and bool(app.screen.query('#approve')))
                self.assertIn('字段　备注',app.screen.body)
                self.assertIn('原值　两日住宿',app.screen.body)
                self.assertIn('新值　季度交接待核',app.screen.body)
                self.assertEqual(snapshot(book),before)
                app.screen.answer(False)
                await self.await_state(pilot,lambda:not app.busy)
            self.assertEqual(snapshot(book),before)


if __name__=='__main__':unittest.main()
