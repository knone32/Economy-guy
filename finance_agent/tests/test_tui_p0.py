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

from textual.widgets import DataTable, Input, Select

import main
from app.agent import Agent, scripted_model
from app.cli_workspaces import import_workspace
from app.model_config import DEFAULT_TEMPLATE
from app.persistence import ManagementIntent
from app.stage2_schema import open_existing
from app.tasks import list_tasks, manage_task, task_details
from app.tui import AgentWorkspace
from app.tui_intent import edit_turn
from app.tui_screens import Approval


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
