"""Local session isolation, recovery and preference confirmation on fictional data."""
from contextlib import closing
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx

from textual.widgets import Input

from app.agent import Agent, scripted_model
from app.cli_workspaces import import_workspace
from app.model_config import DEFAULT_TEMPLATE, add_profile
from app.preferences import manage_preference
from app.session_store import SessionStore
from app.stage2_schema import open_existing
from app.tui import AgentWorkspace
from app.tui_intent import edit_turn
from app.tui_preferences import open_preferences
from app.tui_screens import Approval, Choices
from tests import test_tui_p0 as pilot_helpers

FIXTURE = Path(__file__).parent / "fixtures" / "example.xlsx"
SCOPE = {"company_id":"C001","year":2026,"month":9}
QUESTION = "该月份发票有哪些用途是未填写的？"


class SessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.book = self.directory / "book.sqlite"
        self.store = self.directory / "sessions.sqlite"
        self.trace = self.directory / "turn.jsonl"
        import_workspace(FIXTURE, self.book)
        self.helper = pilot_helpers.P0Test()

    def app(self, replies=None):
        app = AgentWorkspace(self.book,DEFAULT_TEMPLATE,self.directory / "local.json",
                             model=scripted_model(replies) if replies else None,
                             session_path=self.store,trace_path=self.trace)
        app.mode = "mock"
        return app

    def log(self, app):
        return "".join(line.text for line in app.workspace_widget("#chat-log").lines)

    async def test_real_process_restart_rebuilds_semantics_and_requeries_current_data(self):
        program = """
import asyncio,sys
from pathlib import Path
from tests.test_p05_sessions import SessionTests,QUESTION
async def main():
    t=SessionTests()
    t.book,t.store,t.trace=map(Path,sys.argv[1:])
    t.directory=t.book.parent
    from tests import test_tui_p0 as h
    t.helper=h.P0Test()
    app=t.app()
    async with app.run_test(size=(90,26)) as pilot:
        await t.helper.sign_in(app,pilot)
        app.read_workspace=("C001",2026,9)
        app.remember_focus()
        await t.helper.send(app,pilot,QUESTION)
        await t.helper.await_state(pilot,lambda: bool(app.records) and not app.busy)
        assert app.records[-1][1][0]["tool"]=="check_missing_purpose"
        assert "5 张" in t.log(app) and "F002" in t.log(app)
asyncio.run(main())
"""
        proc = await asyncio.to_thread(subprocess.run,[sys.executable,"-c",program,str(self.book),str(self.store),str(self.trace)],
                                       capture_output=True,text=True,encoding="utf-8",timeout=35)
        self.assertEqual(proc.returncode,0,proc.stderr)
        with closing(open_existing(self.book)) as db, db:
            db.execute("UPDATE invoices SET purpose='资料打印' WHERE company_id='C001' AND invoice_no='F002'")
        app = self.app()
        async with app.run_test(size=(80,24)) as pilot:
            await self.helper.sign_in(app,pilot)
            self.assertIn(QUESTION,self.log(app))
            self.assertIn("5 张",self.log(app))
            self.assertIsNone(app.agent)
            self.assertEqual(app.read_workspace,("C001",2026,9))
            await self.helper.send(app,pilot,"刚才那几张缺用途的发票现在还剩多少？")
            await self.helper.await_state(pilot,lambda: bool(app.records) and not app.busy)
            self.assertIn("4 张",self.log(app))
            self.assertFalse(app.agent.update_session.drafts)
            self.assertFalse(app.agent.update_session.confirmations)
        trace = [json.loads(line) for line in self.trace.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(all(r["mode"]=="mock" for r in trace))
        self.assertFalse(any(r["event"]=="api.response" for r in trace))
        self.assertFalse(any(r["data"]["transport_bound"] for r in trace if r["event"]=="turn.started"))
        wire = [r["data"]["messages"] for r in trace if r["event"]=="model_input"][-2]
        history = next(json.loads(m["content"]) for m in wire if m.get("name")=="harness_history")
        self.assertEqual(history["turns"][0]["request"],QUESTION)
        self.assertNotIn("5 张",json.dumps(history,ensure_ascii=False))
        self.assertFalse(any(m.get("tool_calls") or m["role"]=="tool" for m in wire))

    async def test_live_sdk_wiring_receives_workspace_and_renders_missing_purpose(self):
        local = self.directory / "local.json"
        add_profile({"profile_name":"p05-flash","scope":"user","owner_user_id":"U001","provider":"deepseek",
                     "service_account_ref":"p05-fixture","model":"deepseek-flash","base_url":"https://api.deepseek.com",
                     "api_key_env":"P05_FIXTURE_API_KEY","protocol":"auto"}, "U001",template=DEFAULT_TEMPLATE,local=local)
        replies = iter([pilot_helpers.tool("check_missing_purpose",SCOPE),pilot_helpers.FINAL])
        observed = []
        def respond(_, request):
            wire = json.loads(request.content)
            scope = next(json.loads(m["content"])["read_workspace"]["scope"]
                         for m in wire["messages"] if m.get("name")=="context_data")
            observed.append(scope)
            return httpx.Response(200,json={"id":"p05-injected","created":1,"object":"chat.completion",
                "model":"deepseek-flash","choices":[{"index":0,"finish_reason":"stop",
                "message":{**next(replies),"reasoning_content":""}}],
                "usage":{"prompt_tokens":70,"completion_tokens":20,"total_tokens":90}})
        app = AgentWorkspace(self.book,DEFAULT_TEMPLATE,local,session_path=self.store,trace_path=self.trace)
        with (patch.dict(os.environ,{"FINANCE_MODEL_PROFILE":"p05-flash","P05_FIXTURE_API_KEY":"synthetic-only"}),
              patch.object(httpx.HTTPTransport,"handle_request",new=respond)):
            async with app.run_test(size=(90,26)) as pilot:
                await self.helper.sign_in(app,pilot)
                app.read_workspace=("C001",2026,9)
                await self.helper.send(app,pilot,QUESTION)
                await self.helper.await_state(pilot,lambda: bool(app.records) and not app.busy)
                self.assertIsNotNone(app.agent.transport)
                self.assertEqual(app.model_state()[0],"connected")
                self.assertEqual([c["tool"] for c in app.records[-1][1]],["check_missing_purpose"])
                self.assertIn("R002 v2.0",self.log(app))
                self.assertIn("2026-09",self.log(app))
                self.assertIn("F002",self.log(app))
        self.assertEqual(len(observed),2)
        self.assertTrue(all(scope["periods"]==[[2026,9]] and scope["company_id"]==["C001"] for scope in observed))
        trace = [json.loads(line) for line in self.trace.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(all(r["mode"]=="live" for r in trace))
        self.assertTrue(next(r["data"]["transport_bound"] for r in trace if r["event"]=="turn.started"))
        self.assertEqual(sum(r["event"]=="api.response" for r in trace),2)

    def test_identity_isolates_actor_copy_and_in_place_replacement(self):
        session = SessionStore(self.store,self.book,"U001")
        ident = session.chat
        session.begin("private user text","mock")
        with self.assertRaises(OSError):
            SessionStore(self.store,self.book,"U001")
        session.close()
        other = SessionStore(self.store,self.book,"U002")
        self.assertEqual(other.history()["turns"],[])
        other.close()
        copied = self.directory / "copy.sqlite"
        shutil.copyfile(self.book,copied)
        copied_store = SessionStore(self.store,copied,"U001")
        self.assertNotEqual(copied_store.chat,ident)
        self.assertEqual(copied_store.history()["turns"],[])
        copied_store.close()
        newer = self.directory / "newer.sqlite"
        import_workspace(FIXTURE,newer)
        with self.book.open("wb") as dest:
            dest.write(newer.read_bytes())
        new = SessionStore(self.store,self.book,"U001")
        self.addCleanup(new.close)
        self.assertNotEqual(new.chat,ident)
        self.assertEqual(new.history()["turns"],[])

    def test_mid_turn_replacement_pairs_each_call_without_dispatch(self):
        first = pilot_helpers.tool("check_missing_purpose",SCOPE,"first")
        second = pilot_helpers.tool("get_finance_summary",SCOPE,"second")
        first["tool_calls"].extend(second["tool_calls"])
        agent = Agent("U001",self.book,mode="mock",model=scripted_model([first]))
        checks = iter([None,ValueError("replaced")])
        def verify():
            error = next(checks)
            if error:
                raise error
        agent.workbook_guard = verify
        agent.ask("甲企业 2026-09 哪些发票缺用途？")
        paired = [(m["tool_call_id"],json.loads(m["content"])["status"])
                  for m in agent.messages if m["role"]=="tool"]
        self.assertEqual(paired,[("first","ERROR"),("second","DENIED")])
        self.assertEqual(agent.execution.actual_tools,0)

    async def test_recovery_reports_audit_without_replaying_and_new_chat_preserves_data(self):
        store = SessionStore(self.store,self.book,"U001")
        store.begin("中断查询","mock")
        turn = store.begin("旧修改","mock")
        agent = Agent("U001",self.book,mode="mock",
                      model=scripted_model([pilot_helpers.tool("prepare_invoice_update",pilot_helpers.EDIT)]))
        request = "把甲企业 F002 的用途改成资料打印。"
        agent.ask(request,**edit_turn(request,None))
        draft, = agent.update_session.drafts.values()
        store.checkpoint(turn,draft.request_id)
        self.assertEqual(agent.commit_update(draft.request_id,draft.fingerprint())["status"],"COMMITTED")
        store.close()
        app = self.app()
        async with app.run_test(size=(90,26)) as pilot:
            await self.helper.sign_in(app,pilot)
            self.assertIn("上次处理被中断",self.log(app))
            self.assertIn("核实上次提交",self.log(app))
            self.assertIsNone(app.agent)
            old_chat=app.conversation.chat
            app.request_new_chat()
            await self.helper.await_state(pilot,lambda: isinstance(app.screen,Approval) and app.screen.focused)
            await pilot.press("tab","enter")
            await self.helper.await_state(pilot,lambda: app.conversation.chat!=old_chat)
        with closing(open_existing(self.book,readonly=True)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM invoice_audit").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT purpose FROM invoices WHERE invoice_no='F002' AND company_id='C001'").fetchone()[0],
                             "资料打印")

    async def test_natural_personal_preference_requires_confirmation_and_survives_reopen(self):
        app = self.app([pilot_helpers.tool("manage_display_preference",{"action":"set","value":"简洁"}),pilot_helpers.FINAL])
        async with app.run_test(size=(90,26)) as pilot:
            await self.helper.sign_in(app,pilot)
            await self.helper.send(app,pilot,"以后回答尽量简洁一些。")
            await self.helper.await_state(pilot,lambda: isinstance(app.screen,Approval) and app.screen.focused)
            self.assertEqual(app.conversation.personal_detail(),"普通")
            await pilot.press("tab","enter")
            await self.helper.await_state(pilot,lambda: bool(app.records) and not app.busy)
            self.assertEqual(app.conversation.personal_detail(),"简洁")
            self.assertIn("偏好已保存并回读",self.log(app))
        reopened = self.app([pilot_helpers.FINAL])
        async with reopened.run_test(size=(80,24)) as pilot:
            await self.helper.sign_in(reopened,pilot)
            self.assertEqual(reopened.conversation.personal_detail(),"简洁")
            open_preferences(reopened)
            await self.helper.press_button(reopened,pilot,"#choice-0")
            await self.helper.await_state(pilot,lambda: isinstance(reopened.screen,Choices)
                                          and reopened.screen.title_text.startswith("个人回复习惯"))
            await self.helper.press_button(reopened,pilot,"#choice-2")
            await self.helper.await_state(pilot,lambda: isinstance(reopened.screen,Approval) and reopened.screen.focused)
            await pilot.press("escape")
            await self.helper.await_state(pilot,lambda: not isinstance(reopened.screen,Approval))
            self.assertEqual(reopened.conversation.personal_detail(),"简洁")
            await self.helper.press_button(reopened,pilot,"#choice-2")
            await self.helper.await_state(pilot,lambda: isinstance(reopened.screen,Approval) and reopened.screen.focused)
            await pilot.press("tab","enter")
            await self.helper.await_state(pilot,lambda: reopened.conversation.personal_detail()=="普通")

    async def test_enterprise_preference_settings_isolated_and_confirmed(self):
        app = self.app()
        async with app.run_test(size=(90,26)) as pilot:
            await self.helper.sign_in(app,pilot)
            open_preferences(app)
            await self.helper.press_button(app,pilot,"#choice-1")
            await self.helper.await_state(pilot,lambda: isinstance(app.screen,Choices)
                                          and app.screen.title_text=="选择可读企业")
            await self.helper.press_button(app,pilot,"#choice-0")
            await self.helper.await_state(pilot,lambda: isinstance(app.screen,Choices)
                                          and app.screen.title_text.startswith("企业偏好"))
            await self.helper.press_button(app,pilot,"#choice-0")
            await self.helper.await_state(pilot,lambda: bool(app.screen.query("#habit-name")))
            app.screen.query_one("#habit-name",Input).value="目录"
            app.screen.query_one("#habit-value",Input).value="日期和编号"
            await self.helper.press_button(app,pilot,"#habit-review")
            await self.helper.await_state(pilot,lambda: isinstance(app.screen,Approval) and app.screen.focused)
            self.assertEqual(manage_preference(self.book,"U001","C001","list")["data"],[])
            await pilot.press("tab","enter")
            await self.helper.await_state(pilot,lambda: bool(manage_preference(self.book,"U001","C001","list")["data"]))
            self.assertEqual(manage_preference(self.book,"U001","C002","list")["data"],[])
            self.assertEqual(manage_preference(self.book,"U002","C001","list")["data"],[])
            await self.helper.await_state(pilot,lambda: isinstance(app.screen,Choices)
                                          and app.screen.title_text.startswith("企业偏好"))
            await self.helper.press_button(app,pilot,"#choice-1")
            await self.helper.await_state(pilot,lambda: isinstance(app.screen,Choices)
                                          and app.screen.title_text.startswith("偏好 ·"))
            await self.helper.press_button(app,pilot,"#choice-1")
            await self.helper.await_state(pilot,lambda: bool(app.screen.query("#habit-value")))
            app.screen.query_one("#habit-value",Input).value="只显示编号"
            await self.helper.press_button(app,pilot,"#habit-review")
            await self.helper.await_state(pilot,lambda: isinstance(app.screen,Approval) and app.screen.focused)
            self.assertIn("日期和编号",app.screen.body)
            self.assertEqual(manage_preference(self.book,"U001","C001","get","目录")["data"]["value"],"日期和编号")
            await pilot.press("tab","enter")
            await self.helper.await_state(pilot,lambda: manage_preference(self.book,"U001","C001","get","目录")["data"]["value"]=="只显示编号")
            await self.helper.await_state(pilot,lambda: isinstance(app.screen,Choices)
                                          and app.screen.title_text.startswith("企业偏好"))
            await self.helper.press_button(app,pilot,"#choice-1")
            await self.helper.await_state(pilot,lambda: isinstance(app.screen,Choices)
                                          and app.screen.title_text.startswith("偏好 ·"))
            await self.helper.press_button(app,pilot,"#choice-2")
            await self.helper.await_state(pilot,lambda: isinstance(app.screen,Approval) and app.screen.focused)
            self.assertEqual(manage_preference(self.book,"U001","C001","get","目录")["status"],"SUCCESS")
            await pilot.press("tab","enter")
            await self.helper.await_state(pilot,lambda: manage_preference(self.book,"U001","C001","get","目录")["status"]=="NOT_FOUND")
