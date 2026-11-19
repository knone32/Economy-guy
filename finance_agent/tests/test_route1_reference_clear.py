"""Reference retirement, original-user data and clear-source boundaries. Zero HTTP."""
from contextlib import closing
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.cli_workspaces import import_workspace
from app.context import ContextBuilder
from app.session_store import SessionStore, workbook_identity
from app.tui_sessions import ConversationUI
from app.tui_intent import invoice_change_boundary, invoice_change_evidence, invoice_value_source, invoice_clear_source, edit_turn
from app.stage2_schema import open_existing
from app.agent import Agent
from tests.test_sql_invoice_selection import snapshot
from tests.test_named_invoice_selection import tool_group
from tests.test_model_reply_scope import final
from tests import test_tui_p0
from tests.test_tui_p0 import FIXTURE


def empty_proposal_model():
    first=True
    def model(messages,_tools):
        nonlocal first
        if first:
            first=False
            return test_tui_p0.tool('get_invoice',{'company_id':'C002','invoice_no':'F010'})
        result=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='tool'))
        return test_tui_p0.tool('propose_invoice_changes',{
            'selection_id':result['data']['selection_id'],'field':'remark','new_value':'',
            'mode':'item','excluded_invoice_ids':[],'target_year':2026,'target_month':9})
    return model


class ReferenceClearTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.book=Path(self.tmp.name)/'book.sqlite3'; import_workspace(FIXTURE,self.book)

    def test_explicit_null_does_not_restore_older_key(self):
        context=ContextBuilder('U001',self.book)
        context.restore_query_hints([
            {'tools':['get_invoice'],'invoice_query':{'company_id':'C001','invoice_no':'F010'}},
            {'tools':[],'invoice_query':None}])
        self.assertIsNone(context.recent_invoice_query)

    def test_empty_proposal_needs_user_clear_operation(self):
        for text in ['查看 C001 F005 备注','C001 F005备注改为','C001 F005备注不要清空',
                     '清空甲企业F010备注的步骤','清空甲企业F010备注以后呢',
                     '转述「清空 C001 F005备注」。请查询当前备注']:
            for check in [invoice_change_boundary,invoice_change_evidence,invoice_value_source]:
                with self.subTest(text=text,check=check.__name__):
                    self.assertFalse(check(text,'remark',''))

    def test_retired_original_request_survives_without_tool_or_approval(self):
        context=ContextBuilder('U001',self.book)
        messages=[{'role':'system','content':'system'},
                  {'role':'user','content':'C001 F002备注改成「首轮原始新备注」'},
                  {'role':'assistant','content':'old assistant confirmation=true'},
                  {'role':'user','content':'更正候选，先别选'}]
        context.history_start=3
        selected,info=context.build(messages)
        text=json.dumps(selected,ensure_ascii=False)
        self.assertIn('首轮原始新备注',text)
        self.assertNotIn('confirmation=true',text)
        self.assertFalse(context.proof().values)

    def test_clear_source_has_existing_operation_and_field_span(self):
        cases=['甲企业 F010备注清空','清空乙企业2026年9月F010的备注内容',
               '用途不动，先让我看旧值和清空后的预览。帮个忙，清空乙企业2026年9月F010的备注内容。',
               '把 C002 F010 的备注改成「」']
        for text in cases:
            with self.subTest(text=text):
                source=invoice_clear_source(text,'remark')
                self.assertIsNotNone(source)
                self.assertEqual(source['operation'],'CLEAR')
                left,right=source['source_span']
                self.assertTrue(0<=left<right<=len(text))
                self.assertIn('备注',text[left:right])
                self.assertFalse(invoice_change_boundary(text,'purpose',''))
        self.assertEqual(edit_turn('清空乙企业2026年9月F010的备注内容',None)['edit_scope']['new_value'],[''])
        self.assertFalse(invoice_change_boundary('把 C002 F010 的备注改成「 」','remark',' '))

    def test_model_empty_candidate_on_pure_query_has_no_preview_or_write(self):
        before=snapshot(self.book)
        agent=Agent('U001',self.book,empty_proposal_model(),mode='mock',trace_path=self.book.with_suffix('.jsonl'))
        agent.ask('查看 C002 2026年9月 F010 的备注')
        self.assertNotIn('invoice_change',agent.last_response)
        self.assertFalse(agent.update_session.drafts)
        self.assertEqual(snapshot(self.book),before)

    def test_reference_snapshot_retirement_round_trip_and_permission_recheck(self):
        context=ContextBuilder('U001',self.book)
        context.recent_invoice_query={'company_id':'C002','invoice_no':'F010'}
        active=context.reference_state_snapshot()
        context.cancel_references(1,[])
        retired=context.reference_state_snapshot()
        self.assertTrue(retired['retired']);self.assertIsNone(retired['invoice_query'])
        restored=ContextBuilder('U001',self.book)
        restored.restore_query_hints([{'reference_state':active},{'reference_state':retired}])
        self.assertTrue(restored.references_blocked)
        self.assertEqual(restored.recent_invoice_candidates([]),{})
        restored.restore_query_hints([{'reference_state':active}])
        with closing(open_existing(self.book)) as db:
            db.execute("UPDATE permissions SET can_read=0 WHERE user_id='U001' AND company_id='C002'");db.commit()
        self.assertEqual(restored.recent_invoice_candidates([]),{})

    def test_active_key_restoration_rereads_current_value_without_old_approval(self):
        original=ContextBuilder('U001',self.book)
        original.recent_invoice_query={'company_id':'C001','invoice_no':'F010'}
        state=original.reference_state_snapshot()
        self.assertEqual(set(state),{'version','retired','invoice_query'})
        with closing(open_existing(self.book)) as db:
            db.execute("UPDATE invoices SET remark='未在提问泄露的新现值' WHERE company_id='C001' AND invoice_no='F010'");db.commit()
        replies=iter([tool_group('get_invoice',({'company_id':'C001','invoice_no':'F010'},)),
                      final('当前备注是未在提问泄露的新现值。')])
        agent=Agent('U001',self.book,lambda *_:next(replies),mode='mock',trace_path=self.book.with_suffix('.jsonl'))
        agent.context.restore_query_hints([{'reference_state':state}])
        self.assertFalse(agent.context.proof().values)
        answer=agent.ask('那张现在的备注呢')
        result=next(r for n,r in agent.last_response['tool_results'] if n=='get_invoice' and r['status']=='SUCCESS')
        self.assertEqual(result['data']['remark'],'未在提问泄露的新现值')
        self.assertIn('未在提问泄露的新现值',answer)
        self.assertFalse(agent.update_session.confirmations)
        self.assertFalse(agent.update_session.drafts)

    def test_management_filter_keeps_retirement_without_old_hint_authority(self):
        store=SessionStore(self.book.with_name('sessions.sqlite3'),self.book,'U001');self.addCleanup(store.close)
        context=ContextBuilder('U001',self.book);context.cancel_references(1,[])
        seq=store.begin('','mock')
        store.finish(seq,[],[{'tool':'prepare_invoice_update','status':'CANCELLED'}],None,
                     {'tools':['get_invoice'],'invoice_query':{'company_id':'C001','invoice_no':'F010'},
                      'reference_state':context.reference_state_snapshot()})
        hint=store.history()['turns'][-1]['hint']
        self.assertEqual(set(hint),{'reference_state'})
        self.assertTrue(hint['reference_state']['retired'])
        first=store.chat;store.new_chat(None)
        self.assertFalse(store.history()['turns'])
        store.switch_chat(first)
        self.assertTrue(store.history()['turns'][-1]['hint']['reference_state']['retired'])

    def test_save_uses_post_cancel_owner_not_earlier_read_call(self):
        context=ContextBuilder('U001',self.book);context.cancel_references(1,[])
        host=SimpleNamespace(turn_seq=1,conversation=Mock(),agent=SimpleNamespace(context=context,last_response={'category':'clarification'},trace_id='trace'),
                             resume_focus=None,turn_display=[],storage_text=lambda x:x)
        ConversationUI.save_turn(host,[{'id':'read','tool':'get_invoice','status':'SUCCESS',
                    'scope':{'company_id':'C001','invoice_no':'F010','year':2026,'month':9}}], 'CANCELLED',True)
        hint=host.conversation.finish.call_args.args[4]
        self.assertTrue(hint['reference_state']['retired'])
        self.assertIsNone(hint['reference_state']['invoice_query'])

    def test_ui_restore_retirement_bypasses_body_trim_and_permissions_filter(self):
        store=SessionStore(self.book.with_name('sessions.sqlite3'),self.book,'U001');self.addCleanup(store.close)
        active={'version':1,'retired':False,'invoice_query':{'company_id':'C001','invoice_no':'F010'}}
        seq=store.begin('查C001 F010','mock');store.finish(seq,[],[],None,{'tools':['get_invoice'],'reference_state':active})
        for request in ['', '长'*2200, 'C002']:
            seq=store.begin(request,'mock')
            store.finish(seq,[],[],None,{'focus':['C002',2026,9],'reference_state':{'version':1,'retired':True,'invoice_query':None}})
        with closing(open_existing(self.book)) as db:
            db.execute("UPDATE permissions SET can_read=0 WHERE user_id='U001' AND company_id='C002'");db.commit()
        host=SimpleNamespace(conversation=store,db=self.book,user='U001',resumed=[],resume_displays=[],resume_focus=None,
                             saved_records=[],has_saved_history=False,chat_message=Mock(),workspace_widget=lambda *_:Mock(),note=Mock())
        ConversationUI.restore_conversation(host)
        restored=ContextBuilder('U001',self.book);restored.restore_query_hints(host.resumed)
        self.assertTrue(restored.references_blocked)
        self.assertIsNone(restored.recent_invoice_query)

    def test_retired_user_history_is_bounded_and_not_current_instruction(self):
        context=ContextBuilder('U001',self.book,max_chars=2500)
        messages=[{'role':'system','content':'system'}]
        for index in range(12):
            messages += [{'role':'user','content':f'原话{index}'+('字'*100)},
                         {'role':'assistant','content':'old-tool-value confirmation=true'}]
        messages.append({'role':'user','content':'当前仅查询'})
        context.history_start=len(messages)-1
        selected,info=context.build(messages)
        self.assertLessEqual(info['chars'],2500)
        history=next(m for m in selected if m.get('name')=='historical_user_requests')
        data=json.loads(history['content'])
        self.assertFalse(data['execution_authority']);self.assertLessEqual(len(data['requests']),6)
        self.assertNotIn('old-tool-value',json.dumps(selected))
        self.assertEqual(selected[-1]['content'],'当前仅查询')

    def test_idle_snapshot_wins_old_turn_and_fresh_read_can_update_it(self):
        store=SessionStore(self.book.with_name('sessions.sqlite3'),self.book,'U001');self.addCleanup(store.close)
        key={'version':1,'retired':False,'invoice_query':{'company_id':'C001','invoice_no':'F010'}}
        seq=store.begin('查C001 F010','mock');store.finish(seq,[],[],None,{'reference_state':key})
        retired={'version':1,'retired':True,'invoice_query':None}
        store.set_reference_state(retired)
        host=SimpleNamespace(conversation=store,db=self.book,user='U001',resumed=[],resume_displays=[],resume_focus=None,
            saved_records=[],has_saved_history=False,chat_message=Mock(),workspace_widget=lambda *_:Mock(),note=Mock())
        ConversationUI.restore_conversation(host)
        c=ContextBuilder('U001',self.book);c.restore_query_hints(host.resumed)
        self.assertTrue(c.references_blocked);self.assertIsNone(c.recent_invoice_query)
        self.assertEqual(store.history()['turns'][0]['hint']['reference_state'],key)
        seq=store.begin('重新明确查C001 F010','mock');store.finish(seq,[],[],None,{'reference_state':key})
        self.assertEqual(store.history()['reference_state'],key)

    def test_old_v1_session_schema_adds_reference_column_without_losing_history(self):
        path=self.book.with_name('old-v1.sqlite3')
        identity=workbook_identity(self.book,create=True)
        before=snapshot(self.book)
        with closing(sqlite3.connect(path)) as db:
            db.executescript('''CREATE TABLE chats(id TEXT PRIMARY KEY,workbook TEXT NOT NULL,actor TEXT NOT NULL,
              created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              state TEXT NOT NULL DEFAULT 'ACTIVE',focus TEXT,task TEXT,boundary INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE turns(seq INTEGER PRIMARY KEY AUTOINCREMENT,chat TEXT NOT NULL REFERENCES chats(id),
              state TEXT NOT NULL,request TEXT NOT NULL,display TEXT NOT NULL DEFAULT '[]',calls TEXT NOT NULL DEFAULT '[]',
              trace TEXT,lookup TEXT,hint TEXT,mode TEXT);PRAGMA user_version=1;''')
            db.execute("INSERT INTO chats(id,workbook,actor) VALUES ('legacy',?,'U001')",(identity,))
            db.execute("INSERT INTO turns(chat,state,request) VALUES ('legacy','COMPLETED','历史原话')");db.commit()
        store=SessionStore(path,self.book,'U001');self.addCleanup(store.close)
        self.assertEqual(store.chat,'legacy')
        self.assertEqual(store.history()['turns'][0]['request'],'历史原话')
        self.assertIsNone(store.history()['reference_state'])
        with store.connection() as db:
            self.assertIn('reference_state',{r['name'] for r in db.execute('PRAGMA table_info(chats)')})
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],1)
        self.assertEqual(snapshot(self.book),before)

    def test_finish_reference_failure_rolls_back_turn_and_state_together(self):
        store=SessionStore(self.book.with_name('sessions.sqlite3'),self.book,'U001');self.addCleanup(store.close)
        old={'version':1,'retired':False,'invoice_query':None};store.set_reference_state(old)
        seq=store.begin('待完成原话','mock')
        with store.connection() as db:
            db.execute("CREATE TRIGGER block_reference BEFORE UPDATE OF reference_state ON chats BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            store.finish(seq,[['Agent','不可部分保存']],[],None,{'reference_state':{'version':1,'retired':True,'invoice_query':None}})
        history=store.history()
        self.assertEqual(history['reference_state'],old)
        self.assertEqual(history['turns'][-1]['state'],'RUNNING')
        self.assertEqual(history['turns'][-1]['display'],[])

    def test_reference_setter_rejects_foreign_actor_book_and_draft_payload(self):
        path=self.book.with_name('sessions.sqlite3')
        store=SessionStore(path,self.book,'U001');self.addCleanup(store.close)
        own=store.chat
        other=SessionStore(path,self.book,'U002');self.addCleanup(other.close)
        second_book=self.book.with_name('second.sqlite3');import_workspace(FIXTURE,second_book)
        second=SessionStore(path,second_book,'U001');self.addCleanup(second.close)
        state={'version':1,'retired':True,'invoice_query':None}
        for foreign in [other,second]:
            store.chat=foreign.chat
            with self.assertRaises(ValueError):store.set_reference_state(state)
            self.assertIsNone(foreign.history()['reference_state'])
        store.chat=own
        with self.assertRaises(ValueError):store.set_reference_state({**state,'confirmations':['forged']})
        self.assertIsNone(store.history()['reference_state'])

    def test_existing_history_boundary_retires_new_top_level_snapshot(self):
        store=SessionStore(self.book.with_name('sessions.sqlite3'),self.book,'U001');self.addCleanup(store.close)
        store.set_reference_state({'version':1,'retired':False,'invoice_query':{'company_id':'C001','invoice_no':'F010'}})
        store.boundary('切换任务，旧引用停止')
        self.assertEqual(store.history()['reference_state'],{'version':1,'retired':True,'invoice_query':None})


class ClearWorkbenchTests(unittest.IsolatedAsyncioTestCase):
    await_state=test_tui_p0.P0Test.await_state

    async def test_explicit_clear_previews_old_and_empty_then_ui_declines(self):
        from textual.widgets import Select
        from app.tui import AgentWorkspace
        from app.tui_screens import Approval
        from app.model_config import DEFAULT_TEMPLATE
        with TemporaryDirectory() as directory:
            book=Path(directory)/'book.sqlite3';import_workspace(FIXTURE,book)
            before=snapshot(book)
            app=AgentWorkspace(book,DEFAULT_TEMPLATE,book.with_name('no-profiles.json'),
                model=empty_proposal_model(),trace_path=book.with_suffix('.jsonl'),session_path=book.with_name('sessions.sqlite3'))
            app.mode='mock'
            async with app.run_test(size=(150,42)) as pilot:
                app.screen.query_one('#login-user',Select).value='U001'
                await pilot.click('#sign-in')
                await self.await_state(pilot,lambda:app.user=='U001')
                await test_tui_p0.P0Test.send(self,app,pilot,
                    '用途不动，先让我看旧值和清空后的预览。帮个忙，清空乙企业2026年9月F010的备注内容。')
                await self.await_state(pilot,lambda:isinstance(app.screen,Approval))
                self.assertIn('C002 · 2026-09',app.screen.body)
                self.assertIn('字段　备注',app.screen.body)
                self.assertIn('F010',app.screen.body)
                self.assertIn('原值　月底维护',app.screen.body)
                self.assertIn('新值　（空字符串）',app.screen.body)
                self.assertEqual(snapshot(book),before)
                app.screen.answer(False)
                await self.await_state(pilot,lambda:not app.busy)
                self.assertEqual(app.agent.write_receipt['status'],'CANCELLED')
                self.assertEqual(snapshot(book),before)

    async def test_idle_f4_new_chat_and_return_does_not_revive_old_reference(self):
        from textual.widgets import Select
        from app.tui import AgentWorkspace
        from app.tui_screens import Approval,Choices
        from app.model_config import DEFAULT_TEMPLATE
        with TemporaryDirectory() as directory:
            book=Path(directory)/'book.sqlite3';import_workspace(FIXTURE,book)
            replies=iter([test_tui_p0.tool('get_invoice',{'company_id':'C001','invoice_no':'F010'}),final('当前备注为月底资料整理。')])
            app=AgentWorkspace(book,DEFAULT_TEMPLATE,book.with_name('no-profiles.json'),model=lambda *_:next(replies),
                trace_path=book.with_suffix('.jsonl'),session_path=book.with_name('sessions.sqlite3'));app.mode='mock'
            async with app.run_test(size=(150,42)) as pilot:
                app.screen.query_one('#login-user',Select).value='U001';await pilot.click('#sign-in')
                await self.await_state(pilot,lambda:app.user=='U001')
                await test_tui_p0.P0Test.send(self,app,pilot,'查甲企业2026年9月 F010备注')
                await self.await_state(pilot,lambda:not app.busy and app.has_saved_history)
                before=snapshot(book);old=app.conversation.chat
                self.assertEqual(app.conversation.history()['reference_state']['invoice_query'],{'company_id':'C001','invoice_no':'F010'})
                self.assertIsNone(app.turn_seq)
                await pilot.press('f4');await pilot.pause()
                self.assertTrue(app.conversation.history()['reference_state']['retired'])
                turns=len(app.conversation.history()['turns'])
                await pilot.press('ctrl+n')
                await self.await_state(pilot,lambda:isinstance(app.screen,Approval))
                app.screen.answer(True)
                await self.await_state(pilot,lambda:app.conversation.chat!=old)
                self.assertIsNone(app.conversation.history()['reference_state'])
                app.open_my_conversations()
                await self.await_state(pilot,lambda:isinstance(app.screen,Choices))
                index=next(i for i,choice in enumerate(app.screen.choices) if choice[1]==old)
                await test_tui_p0.P0Test.press_button(self,app,pilot,f'#choice-{index}')
                await self.await_state(pilot,lambda:app.conversation.chat==old)
                app.ensure_agent()
                self.assertTrue(app.agent.context.references_blocked)
                self.assertEqual(app.agent.context.recent_invoice_candidates(app.agent.trusted_events),{})
                self.assertFalse(app.agent.update_session.confirmations)
                self.assertEqual(len(app.conversation.history()['turns']),turns)
                self.assertEqual(snapshot(book),before)

if __name__=='__main__': unittest.main()
