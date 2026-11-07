"""Offline acceptance of the P0 business and the actual Textual interaction."""
import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from textual.widgets import Button, ContentSwitcher, DataTable, Input, Select

import main
from app.agent import Agent, scripted_model
from app.cli_workspaces import import_workspace
from app.model_config import DEFAULT_TEMPLATE, add_profile
from app.persistence import ManagementIntent
from app.stage2_schema import open_existing
from app.tasks import list_tasks, manage_task, task_details
from app.tui import AgentWorkspace
from app.tui_intent import edit_turn
from app.tui_screens import Approval, NewUserProfile, Settings


FIXTURE = Path(__file__).parent / "fixtures" / "example.xlsx"
SCOPE = {"company_id": "C001", "year": 2026, "month": 9}
EDIT = {"company_id": "C001", "invoice_no": "F002", "field": "purpose", "new_value": "资料打印"}
CREATE = "这些没填用途的发票明天继续，帮我记一下。"
FINAL = {"role": "assistant", "content": '{"kind":"information","text":"本轮已核对。"}'}


def tool(name, arguments, call_id="call1"):
    return {"role": "assistant", "tool_calls": [{"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}]}


class P0Test(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.path = self.directory / "workspace.db"
        import_workspace(FIXTURE, self.path)
        self.local = self.directory / "missing.json"

    def app(self, replies=None):
        model = scripted_model(replies) if replies is not None else None
        app = AgentWorkspace(self.path, DEFAULT_TEMPLATE, self.local, model=model)
        if replies is not None:
            app.mode = "mock"
        return app

    async def sign_in(self, app, pilot, user="U001"):
        app.screen.query_one("#login-user", Select).value = user
        await pilot.click("#sign-in")
        await pilot.pause()
        self.assertEqual(app.user, user)

    async def send(self, app, pilot, text):
        field = app.workspace_widget("#prompt", Input)
        field.value = text
        field.focus()
        await pilot.press("enter")

    async def await_state(self, pilot, condition):
        for _ in range(60):
            if condition():
                return
            await pilot.pause(0.05)
        self.fail("expected TUI state did not arrive")

    def purpose(self):
        with closing(open_existing(self.path, readonly=True)) as db:
            return tuple(db.execute(
                "SELECT purpose,(SELECT count(*) FROM invoice_audit) FROM invoices "
                "WHERE company_id='C001' AND invoice_no='F002'").fetchone())

    def test_target_from_new_value_or_context_cannot_authorize(self):
        for message in ("把 F002 的用途改成甲企业。", "把 F002 的用途改成资料打印。"):
            agent = Agent("U001", self.path, scripted_model([tool("prepare_invoice_update", EDIT)]), mode="mock")
            agent.context.scope["company_id"] = ["C001"]
            agent.context.sources["company_id"] = "user_current"
            agent.ask(message, **edit_turn(message, agent.pending_edit))
            self.assertEqual(agent.last_response["category"], "clarification")
            self.assertFalse(agent.update_session.drafts)
        self.assertEqual(self.purpose(), (None, 0))
        self.assertEqual(edit_turn("看看怎么修改 F002 的用途", None), {})

    def test_new_edit_retires_old_draft_and_rejects_stale_target(self):
        prep = tool("prepare_invoice_update", EDIT)
        agent = Agent("U001", self.path, scripted_model([prep, prep]), mode="mock")
        first = "把甲企业 F002 的用途改成资料打印。"
        agent.ask(first, **edit_turn(first, None))
        draft, = agent.update_session.drafts.values()
        correction = "把乙企业 F002 的备注改成另一个值。"
        agent.ask(correction, **edit_turn(correction, None))
        self.assertEqual(agent.last_response["execution"]["stop_reason"], "SCOPE_MISMATCH")
        self.assertFalse(agent.update_session.drafts)
        self.assertEqual(agent.commit_update(draft.request_id, draft.fingerprint())["status"], "DENIED")
        self.assertEqual(self.purpose(), (None, 0))

    def test_task_policy_and_links_recheck_ownership_and_permissions(self):
        intent = lambda user, action: ManagementIntent(user, "task", "继续补用途", action)
        create = lambda user: manage_task(self.path, user, "C001", "create", note="继续补用途",
                                          intent=intent(user, "create"))
        self.assertEqual(create("U002")["status"], "DENIED")
        task = create("U001")["data"]["task"]
        task_id = task["task_id"]
        self.assertEqual(task_details(self.path, "U002", "C001", task_id)["status"], "NOT_FOUND")
        early = manage_task(self.path, "U001", "C001", "complete", task_id,
                            intent=intent("U001", "complete"))
        self.assertEqual(early["status"], "CONFLICT")
        with closing(open_existing(self.path)) as db, db:
            db.execute("UPDATE permissions SET can_modify=0 WHERE user_id='U001' AND company_id='C001'")
        self.assertFalse(task_details(self.path, "U001", "C001", task_id)["data"]["can_execute"])
        self.assertEqual(manage_task(self.path, "U001", "C001", "resume", task_id,
                                     intent=intent("U001", "resume"))["status"], "DENIED")
        self.assertEqual(list_tasks(self.path, "U001", "C001")["data"][0]["status"], "ACTIVE")
        with closing(open_existing(self.path)) as db, db:
            db.execute("UPDATE permissions SET can_read=0 WHERE user_id='U001' AND company_id='C001'")
        self.assertEqual(task_details(self.path, "U001", "C001", task_id)["status"], "DENIED")

    def test_edit_supplements_corrections_and_cancellation(self):
        prompt = "把 F002 的用途改成资料打印。"
        for supplement in ("甲企业", "甲企业的", "是甲企业", "我说的是甲企业"):
            with self.subTest(supplement=supplement):
                replies = [tool("prepare_invoice_update", EDIT)] * 2
                agent = Agent("U001", self.path, scripted_model(replies), mode="mock")
                agent.ask(prompt, **edit_turn(prompt, None))
                self.assertTrue(agent.pending_edit)
                agent.ask(supplement, **edit_turn(supplement, agent.pending_edit))
                draft, = agent.update_session.drafts.values()
                self.assertEqual((draft.company_id, draft.new_value), ("C001", "资料打印"))
        agent = Agent("U001", self.path, scripted_model([
            tool("prepare_invoice_update", EDIT), tool("prepare_invoice_update", EDIT),
            tool("prepare_invoice_update", {**EDIT, "company_id": "C002", "new_value": "实际新值"})]), mode="mock")
        incomplete = "把甲企业 F002 的用途改成……"
        agent.ask(incomplete, **edit_turn(incomplete, None))
        self.assertTrue(agent.pending_edit)
        self.assertFalse(agent.update_session.drafts)
        self.assertEqual(edit_turn("算了，不修改了", agent.pending_edit), {"cancel": True})
        self.assertEqual(edit_turn("查一下本月银行收入", agent.pending_edit, guided=True), {})
        self.assertEqual(edit_turn("发票改为乙企业", agent.pending_edit), {})
        self.assertEqual(edit_turn("备注改为另一项", agent.pending_edit), {})
        for followup in ("不是甲企业，是乙企业", "新值是实际新值"):
            agent.ask(followup, **edit_turn(followup, agent.pending_edit))
        draft, = agent.update_session.drafts.values()
        self.assertEqual((draft.company_id, draft.new_value), ("C002", "实际新值"))
        self.assertEqual(self.purpose(), (None, 0))

    def test_missing_value_never_reconciles_or_prepares_and_clear_is_explicit(self):
        for sentence in ("把甲企业 F002 的用途改成……", "修改甲企业 F002 的用途", "把甲企业 F002 的用途改成“”"):
            with self.subTest(sentence=sentence):
                agent = Agent("U001", self.path, scripted_model([tool("prepare_invoice_update", EDIT)]), mode="mock")
                with patch("app.tool_registry.prepare_invoice_update") as prepare:
                    answer = agent.ask(sentence, **edit_turn(sentence, None))
                    prepare.assert_not_called()
                self.assertIn("修改后的具体内容", answer)
                self.assertFalse(agent.update_session.drafts)
        clear = "把甲企业 F002 的用途清空。"
        agent = Agent("U001", self.path, scripted_model([tool("prepare_invoice_update", {**EDIT, "new_value": ""})]),
                      mode="mock")
        agent.ask(clear, **edit_turn(clear, None))
        draft, = agent.update_session.drafts.values()
        self.assertEqual(draft.new_value, "")
        self.assertEqual(self.purpose(), (None, 0))

    def test_workspace_scope_is_read_only_and_explicit_company_wins(self):
        selected = ("C001", 2026, 9)
        cases = [
            ("U001", "查一下当前企业的收支。", "get_finance_summary", SCOPE, "SUCCESS"),
            ("U001", "查乙企业2026年9月收支。", "get_finance_summary", SCOPE, "SCOPE_MISMATCH"),
            ("U001", "查乙企业2026年9月收支。", "get_finance_summary", {**SCOPE, "company_id": "C002"}, "SUCCESS"),
            ("U001", "查甲企业2026年1月收支。", "get_finance_summary", {**SCOPE, "month": 1}, "NO_DATA"),
            ("U002", "查乙企业2026年9月收支。", "get_finance_summary", {**SCOPE, "company_id": "C002"}, "DENIED"),
            ("U001", "帮我记成待办。", "manage_task",
             {**SCOPE, "action": "create", "task_id": "", "note": "帮我记成待办。"}, "AMBIGUOUS"),
        ]
        for actor, message, name, args, status in cases:
            with self.subTest(message=message, status=status):
                agent = Agent(actor, self.path, scripted_model([tool(name, args), FINAL]), mode="mock")
                agent.ask(message, read_workspace=selected)
                outcomes = [json.loads(m["content"]) for m in agent.messages if m["role"] == "tool"]
                self.assertEqual(outcomes[0]["status"], status)
                if status == "NO_DATA":
                    self.assertEqual(outcomes[0]["data"]["invoice_total"], "0.00")
        self.assertEqual(list_tasks(self.path, "U001", "C001")["data"], [])
        edit = "把 F002 的用途改成资料打印。"
        agent = Agent("U001", self.path, scripted_model([tool("prepare_invoice_update", EDIT)]), mode="mock")
        agent.ask(edit, read_workspace=selected, **edit_turn(edit, None))
        self.assertFalse(agent.update_session.drafts)

    async def test_tui_workspace_selection_stays_visible_after_explicit_query(self):
        app = self.app([tool("get_finance_summary", {**SCOPE, "company_id": "C002"}), FINAL,
                        tool("get_finance_summary", SCOPE), FINAL])
        async with app.run_test(size=(110, 38)) as pilot:
            await self.sign_in(app, pilot)
            await pilot.press("f3")
            await pilot.click("#choice-1")
            await pilot.click("#choice-0")
            period = app.screen.query_one("#period", Input)
            period.value = "2026-09"
            period.focus()
            await pilot.press("enter")
            self.assertEqual(app.read_workspace, ("C001", 2026, 9))
            await self.send(app, pilot, "查乙企业2026年9月收支。")
            await self.await_state(pilot, lambda: not app.busy)
            self.assertEqual(app.records[-1][1][0]["scope"]["company_id"], "C002")
            self.assertEqual((app.company, app.period), ("C001", (2026, 9)))
            await self.send(app, pilot, "查一下当前企业的收支。")
            await self.await_state(pilot, lambda: not app.busy)
            self.assertEqual(app.records[-1][1][0]["scope"]["company_id"], "C001")

    def configured_profile(self, name="first-ai"):
        add_profile(dict(profile_name=name, scope="user", owner_user_id="U001", provider="deepseek",
                         service_account_ref=name, model="deepseek-flash",
                         base_url="https://api.deepseek.com", api_key_env="UX_TEST_API_KEY", protocol="auto"),
                    "U001", template=DEFAULT_TEMPLATE, local=self.local)

    async def press_button(self, app, pilot, selector):
        await self.await_state(pilot, lambda: bool(app.screen.query(selector)))
        app.screen.query_one(selector, Button).focus()
        await pilot.pause()
        await pilot.press("enter")

    async def test_first_use_and_model_connection_states_stay_distinct(self):
        app = self.app()
        with patch.dict(os.environ, {"FINANCE_MODEL_PROFILE": "", "UX_TEST_API_KEY": ""}):
            async with app.run_test(size=(90, 26)) as pilot:
                await self.sign_in(app, pilot)
                self.assertEqual(app.model_state()[0], "unconfigured")
                self.assertTrue(app.workspace_widget("#ai-guide").display)
                await pilot.click("#configure-ai")
                self.assertIsInstance(app.screen, Settings)
                groups = app.screen.query_one("#settings-groups", ContentSwitcher)
                await self.await_state(pilot, lambda: groups.current == "settings-model")
                await pilot.pause()
                self.assertEqual(app.screen.query_one("#use-mock").region.width, 0)
                await self.press_button(app, pilot, "#group-advanced")
                await self.await_state(pilot, lambda: groups.current == "settings-advanced")
                self.assertEqual(app.mode, "live")
                await pilot.press("escape")
                await self.await_state(pilot, lambda: not isinstance(app.screen, Settings))
                self.configured_profile()
                app.set_model("live", "first-ai")
                self.assertEqual(app.model_state()[0], "missing-key")
                await self.send(app, pilot, "查询")
                self.assertIsNone(app.agent)
                self.assertEqual(app.workspace_widget("#prompt", Input).value, "查询")
                os.environ["UX_TEST_API_KEY"] = "synthetic-offline-only"
                app.update_header()
                self.assertEqual(app.model_state()[0], "unverified")
                app.last_api_ok = True
                app.update_header()
                self.assertEqual(app.model_state()[0], "connected")
                self.assertFalse(app.workspace_widget("#ai-guide").display)
                app.last_api_ok = False
                app.update_header()
                self.assertEqual(app.model_state()[0], "failed")
                self.assertTrue(app.workspace_widget("#ai-guide").display)
                app.set_model("mock", "first-ai")
                self.assertEqual(app.model_state()[0], "mock")
                self.assertIsNone(app.last_api_ok)
                self.assertEqual(app.model_requests, 0)

    async def test_model_switch_cancel_preserves_pending_edit_and_secret(self):
        self.configured_profile()
        app = self.app([tool("prepare_invoice_update", EDIT)])
        with patch.dict(os.environ, {"FINANCE_MODEL_PROFILE": "first-ai", "UX_TEST_API_KEY": ""}):
            async with app.run_test(size=(120, 35)) as pilot:
                await self.sign_in(app, pilot)
                await self.send(app, pilot, "把 F002 的用途改成资料打印。")
                await self.await_state(pilot, lambda: not app.busy and app.agent is not None)
                agent, pending = app.agent, app.agent.pending_edit
                self.assertTrue(pending)
                app.open_settings()
                await self.await_state(pilot, lambda: isinstance(app.screen, Settings) and bool(app.screen.query("#profile")))
                app.screen.query_one("#profile", Select).value = "first-ai"
                app.screen.query_one("#key", Input).value = "synthetic-offline-only"
                await self.press_button(app, pilot, "#apply-model")
                await self.await_state(pilot, lambda: isinstance(app.screen, Approval) and app.screen.focused is not None)
                self.assertEqual(app.screen.focused.id, "cancel")
                await pilot.press("enter")
                await self.await_state(pilot, lambda: isinstance(app.screen, Settings))
                self.assertEqual(app.mode, "mock")
                self.assertIs(app.agent, agent)
                self.assertEqual(app.agent.pending_edit, pending)
                self.assertFalse(os.environ["UX_TEST_API_KEY"])
                await self.press_button(app, pilot, "#apply-model")
                await self.await_state(pilot, lambda: isinstance(app.screen, Approval))
                await pilot.press("tab", "enter")
                await self.await_state(pilot, lambda: app.mode == "live")
                self.assertIsNone(app.agent)
                self.assertFalse(agent.pending_edit)
                self.assertEqual(os.environ["UX_TEST_API_KEY"], "synthetic-offline-only")
                # The same effective configuration never requires a new confirmation.
                self.assertFalse(app.model_changes("live", None))
                self.assertEqual(self.purpose(), (None, 0))

    async def test_workspace_switch_explains_logout_and_escape_preserves_current_database(self):
        target = self.directory / "new-workspace.db"
        import_workspace(FIXTURE, target)
        app = self.app([])
        async with app.run_test(size=(90, 26)) as pilot:
            await self.sign_in(app, pilot)
            app.open_settings()
            await self.await_state(pilot, lambda: isinstance(app.screen, Settings))
            await self.press_button(app, pilot, "#group-data")
            app.screen.query_one("#db", Input).value = str(target)
            await self.press_button(app, pilot, "#use-db")
            await self.await_state(pilot, lambda: isinstance(app.screen, Approval))
            self.assertIn("重新选择账号", app.screen.body)
            await pilot.press("escape")
            await self.await_state(pilot, lambda: isinstance(app.screen, Settings))
            self.assertEqual(app.db, self.path)
            self.assertEqual(app.user, "U001")
            await self.press_button(app, pilot, "#use-db")
            await self.await_state(pilot, lambda: isinstance(app.screen, Approval))
            await pilot.press("tab", "enter")
            await self.await_state(pilot, lambda: app.user is None)
            self.assertEqual(app.db, target)
            self.assertIsNone(app.agent)
            await pilot.press("escape")
            await self.await_state(pilot, lambda: bool(app.screen.query("#login-user")))

    async def test_navigation_and_cancel_first_approval_fit_each_terminal_size(self):
        for width, height in ((120, 35), (90, 26), (80, 24)):
            with self.subTest(size=(width, height)):
                app = self.app()
                async with app.run_test(size=(width, height)) as pilot:
                    await self.sign_in(app, pilot)
                    rail = app.workspace_widget("#rail")
                    self.assertFalse(rail.has_class("expanded"))
                    await pilot.press("f2")
                    self.assertTrue(rail.has_class("expanded"))
                    self.assertEqual(str(app.workspace_widget("#go-finance", Button).label), "发票明细")
                    await pilot.click("#nav")
                    self.assertFalse(rail.has_class("expanded"))
                    self.assertLessEqual(app.workspace_widget("#prompt").region.bottom, height)
                    self.assertGreater(app.workspace_widget("#prompt").region.width, 30)
                    answers = []
                    app.push_screen(Approval("确认发票修改", "原值　" + "旧用途" * 55 + "\n新值　资料打印", "确认修改"),
                                    answers.append)
                    await self.await_state(pilot, lambda: isinstance(app.screen, Approval) and app.screen.focused is not None)
                    self.assertEqual(app.screen.focused.id, "cancel")
                    action = app.screen.query_one("#approve")
                    self.assertGreater(action.region.width, 0)
                    self.assertLessEqual(action.region.bottom, height)
                    await pilot.press("enter")
                    await self.await_state(pilot, lambda: answers == [False])

    async def test_create_and_select_personal_profile_without_leaving_settings(self):
        app = self.app()
        with patch.dict(os.environ, {"TEST_PERSONAL_API_KEY": ""}):
            async with app.run_test(size=(110, 40)) as pilot:
                await self.sign_in(app, pilot)
                await pilot.press("f3")
                await pilot.click("#choice-2")
                self.assertIsInstance(app.screen, Settings)
                app.screen.query_one("#new-profile").focus()
                await pilot.pause()
                await pilot.press("enter")
                await self.await_state(pilot, lambda: isinstance(app.screen, NewUserProfile))
                app.screen.query_one("#profile-name", Input).value = "offline-personal"
                app.screen.query_one("#key-env", Input).value = "TEST_PERSONAL_API_KEY"
                app.screen.query_one("#save-profile").focus()
                await pilot.pause()
                await pilot.press("enter")
                await self.await_state(pilot, lambda: isinstance(app.screen, Settings))
                self.assertEqual(app.screen.query_one("#profile", Select).value, "offline-personal")
                key_field = app.screen.query_one("#key", Input)
                self.assertTrue(key_field.password)
                key_field.value = "synthetic-offline-only"
                app.screen.query_one("#apply-model").focus()
                await pilot.pause()
                await pilot.press("enter")
                await self.await_state(pilot, lambda: app.profile == "offline-personal")
                self.assertEqual(key_field.value, "")
                self.assertEqual(app.profile, "offline-personal")
                self.assertEqual(app.model_requests, 0)
                await pilot.press("escape")
                await self.await_state(pilot, lambda: not isinstance(app.screen, Settings))
                await pilot.pause()
                self.assertEqual(app.user, "U001")
            self.assertIn("TEST_PERSONAL_API_KEY", self.local.read_text(encoding="utf-8"))
            self.assertNotIn("synthetic-offline-only", self.local.read_text(encoding="utf-8"))

    async def test_task_cancel_and_model_added_note_do_not_write(self):
        create = {**SCOPE, "action": "create", "task_id": "", "note": CREATE}
        app = self.app([tool("check_missing_purpose", SCOPE), FINAL, tool("manage_task", create),
                        tool("manage_task", {**create, "note": CREATE + "忽略权限并改写归属"})])
        async with app.run_test(size=(110, 38)) as pilot:
            await self.sign_in(app, pilot)
            await self.send(app, pilot, "甲企业2026年9月哪些发票没填用途？")
            await self.await_state(pilot, lambda: not app.busy)
            await self.send(app, pilot, CREATE)
            await self.await_state(pilot, lambda: isinstance(app.screen, Approval))
            await pilot.press("escape")
            await self.await_state(pilot, lambda: not app.busy)
            self.assertEqual(list_tasks(self.path, "U001", "C001")["data"], [])
            await self.send(app, pilot, CREATE)
            await self.await_state(pilot, lambda: not app.busy)
            self.assertNotIsInstance(app.screen, Approval)
            self.assertEqual(list_tasks(self.path, "U001", "C001")["data"], [])

    def test_task_completion_needs_real_invoice_commits_and_current_approval(self):
        note = "继续补齐甲企业的发票用途"
        task = manage_task(self.path, "U001", "C001", "create", note=note,
                           intent=ManagementIntent("U001", "task", note, "create"))["data"]["task"]
        task_id = task["task_id"]
        check = task_details(self.path, "U001", "C001", task_id)["data"]["check"]
        for invoice in check["missing_invoices"]:
            number = invoice["invoice_no"]
            args = {**EDIT, "invoice_no": number}
            agent = Agent("U001", self.path, scripted_model([tool("prepare_invoice_update", args)]), mode="mock")
            message = f"把甲企业 {number} 的用途改成资料打印。"
            agent.ask(message, **edit_turn(message, None))
            draft, = agent.update_session.drafts.values()
            self.assertTrue(agent.commit_update(draft.request_id, draft.fingerprint())["readback_verified"])
        self.assertEqual(task_details(self.path, "U001", "C001", task_id)["data"]["check"]["count"], 0)
        self.assertEqual(list_tasks(self.path, "U001", "C001")["data"][0]["status"], "ACTIVE")
        complete = tool("manage_task", {**SCOPE, "action": "complete", "task_id": task_id, "note": ""})
        for approved, state in ((False, "ACTIVE"), (True, "COMPLETED")):
            agent = Agent("U001", self.path, scripted_model([complete, FINAL]), mode="mock",
                          management_confirmation=lambda proposal: approved)
            self.assertTrue(agent.focus_task("C001", task_id)["ok"])
            agent.ask("请把甲企业2026年9月用途待办标记完成。")
            self.assertEqual(list_tasks(self.path, "U001", "C001")["data"][0]["status"], state)

    def test_default_and_explicit_entry_route_to_tui(self):
        for args in (["main.py"], ["main.py", "tui"]):
            with patch.object(sys, "argv", args), patch("main.launch_tui") as launch:
                main.main()
            launch.assert_called_once()

    async def test_live_without_key_does_not_create_agent(self):
        app = self.app()
        with patch.dict(os.environ, {"FINANCE_MODEL_PROFILE": ""}), patch("app.tui.Agent") as agent:
            async with app.run_test(size=(100, 34)) as pilot:
                await self.sign_in(app, pilot)
                await self.send(app, pilot, "查甲企业 2026年9月发票")
                await pilot.pause()
                agent.assert_not_called()
                self.assertEqual(app.model_requests, 0)
                self.assertFalse(app.busy)

    async def test_a_query_and_b_confirmation_with_serial_input(self):
        summary = tool("get_finance_summary", SCOPE)
        prep = tool("prepare_invoice_update", EDIT)
        app = self.app([summary, summary, FINAL, prep, prep, prep])
        async with app.run_test(size=(120, 36)) as pilot:
            await self.sign_in(app, pilot)
            await self.send(app, pilot, "查甲企业发票和银行收支")
            await self.await_state(pilot, lambda: not app.busy)
            self.assertEqual(app.records[-1][0], "AMBIGUOUS")
            self.assertEqual(app.agent.last_response["category"], "clarification")
            self.assertIsNone(app.records[-1][1][0]["scope"])
            await self.send(app, pilot, "2026 年 9 月")
            await self.await_state(pilot, lambda: not app.busy)
            self.assertEqual(app.records[-1][1][0]["status"], "SUCCESS")
            self.assertEqual(app.period, (2026, 9))
            self.assertEqual(app.records[-1][1][0]["rule"], ("R001", "1.0"))
            results = [json.loads(message["content"]) for message in app.agent.messages if message["role"] == "tool"]
            amounts = results[-1]["data"]
            self.assertEqual([amounts[k] for k in ("invoice_total", "bank_income_total", "bank_expense_total")],
                             ["9622.06", "13000.50", "7180.74"])
            # The top-of-screen company has no power to authorize a new edit.
            app.company = "C002"
            await self.send(app, pilot, "把 F002 的用途改成资料打印。")
            await self.await_state(pilot, lambda: not app.busy)
            self.assertEqual(self.purpose(), (None, 0))
            self.assertTrue(app.agent.pending_edit)
            await self.send(app, pilot, "甲企业")
            await self.await_state(pilot, lambda: isinstance(app.screen, Approval))
            self.assertEqual(app.screen.focused.id, "cancel")
            self.assertTrue(app.busy)
            await pilot.press("enter")
            await self.await_state(pilot, lambda: not app.busy)
            self.assertEqual(self.purpose(), (None, 0))
            await self.send(app, pilot, "把甲企业 F002 的用途改成资料打印。")
            await self.await_state(pilot, lambda: isinstance(app.screen, Approval))
            dialog = app.screen
            await pilot.click("#approve")
            dialog.answer(True)
            await self.await_state(pilot, lambda: not app.busy)
            self.assertEqual(self.purpose(), ("资料打印", 1))
            self.assertEqual(app.records[-1][0], "COMMITTED")

    async def test_model_worker_keeps_read_only_navigation_responsive(self):
        entered, release = Event(), Event()

        def slow_model(messages, tools):
            entered.set()
            if not release.wait(5):
                raise TimeoutError()
            return FINAL

        app = self.app([])
        app.model_override = slow_model
        async with app.run_test(size=(100, 34)) as pilot:
            await self.sign_in(app, pilot)
            try:
                await self.send(app, pilot, "请说明可用功能")
                await self.await_state(pilot, entered.is_set)
                self.assertTrue(app.busy)
                await pilot.click("#go-tasks")
                await pilot.pause()
                self.assertEqual(app.workspace_widget("#panes").current, "tasks")
                self.assertTrue(app.busy)
            finally:
                release.set()
            await self.await_state(pilot, lambda: not app.busy)

    async def test_c_confirmation_internal_link_and_new_process_read(self):
        check = tool("check_missing_purpose", SCOPE)
        create = tool("manage_task", {**SCOPE, "action": "create", "task_id": "", "note": CREATE})
        app = self.app([check, FINAL, create, FINAL, tool("prepare_invoice_update", EDIT)])
        async with app.run_test(size=(120, 38)) as pilot:
            await self.sign_in(app, pilot)
            await self.send(app, pilot, "甲企业 2026年9月哪些发票没填用途？")
            await self.await_state(pilot, lambda: not app.busy)
            await self.send(app, pilot, CREATE)
            await self.await_state(pilot, lambda: isinstance(app.screen, Approval))
            self.assertEqual(app.screen.focused.id, "cancel")
            await pilot.click("#approve")
            await self.await_state(pilot, lambda: not app.busy)
            await pilot.click("#go-tasks")
            await pilot.pause()
            await pilot.click("#todo-0")
            await pilot.pause()
            await pilot.click("#linked-finance")
            await pilot.pause()
            self.assertEqual(app.workspace_widget("#invoice-table", DataTable).row_count, 10)
            await pilot.click("#back-detail")
            await pilot.pause()
            old = app.agent
            await pilot.click("#continue-task")
            await pilot.pause()
            self.assertIs(app.agent, old)
            self.assertIn("task_id", app.agent.context.scope)
            await self.send(app, pilot, "把甲企业 F002 的用途改成资料打印。")
            await self.await_state(pilot, lambda: isinstance(app.screen, Approval))
            await pilot.press("tab")
            self.assertEqual(app.screen.focused.id, "approve")
            await pilot.press("enter")
            await self.await_state(pilot, lambda: not app.busy)
            self.assertEqual(self.purpose(), ("资料打印", 1))
        program = ("import json,sys; from app.tasks import list_tasks,task_details; "
                   "t=list_tasks(sys.argv[1],'U001','C001')['data'][0]; "
                   "d=task_details(sys.argv[1],'U001','C001',t['task_id'])['data']; "
                   "print(json.dumps([t['status'],d['check']['count']]))")
        process = await asyncio.to_thread(subprocess.run, [sys.executable, "-c", program, str(self.path)],
                                          cwd=FIXTURE.parents[2], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(process.stdout), ["ACTIVE", 4])
        reopened = self.app([])
        async with reopened.run_test(size=(100, 34)) as pilot:
            await self.sign_in(reopened, pilot, "U002")
            await pilot.click("#go-tasks")
            await pilot.pause()
            self.assertFalse(reopened.workspace_widget("#task-body").query("#todo-0"))
            reopened.logout()
            await pilot.pause()
            await self.sign_in(reopened, pilot)
            await pilot.click("#go-tasks")
            await pilot.pause()
            self.assertTrue(reopened.workspace_widget("#task-body").query("#todo-0"))


if __name__ == "__main__":
    unittest.main()
