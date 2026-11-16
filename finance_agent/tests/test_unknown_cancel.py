"""Regression at the real workbench and CLI boundaries for an unknown invoice commit."""
import io
import json
import sqlite3
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from textual.widgets import Select, Static

from app.agent import Agent, scripted_model
from app.cli_chat import chat_loop
from app.cli_workspaces import import_workspace
from app.model_config import DEFAULT_TEMPLATE
from app.tui import AgentWorkspace, ChatLog
from app.tui_screens import Approval
from tests import test_tui_p0


EDIT, FINAL, FIXTURE, tool = test_tui_p0.EDIT, test_tui_p0.FINAL, test_tui_p0.FIXTURE, test_tui_p0.tool

TARGET = {"company_id": "C001", "invoice_no": "F002"}
EDIT_TEXT = "把 C001 的 F002 用途改为资料打印"
RETRY_TEXT = "把 C001 的 F002 用途改为会议资料"
QUERY = "查询 C001 的 F002 当前用途"


def snapshot(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        value, = db.execute(
            "SELECT purpose FROM invoices WHERE company_id='C001' AND invoice_no='F002'").fetchone()
        return value, db.execute("SELECT request_id, status FROM invoice_audit ORDER BY rowid").fetchall()


class UnknownCancelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.path = self.directory / "workspace.db"
        import_workspace(FIXTURE, self.path)

    async def test_workbench_f4_keeps_unknown_and_blocks_both_retries(self):
        app = AgentWorkspace(self.path, DEFAULT_TEMPLATE, self.directory / "no-profiles.json",
                             model=scripted_model([tool("prepare_invoice_update", EDIT)]),
                             session_path=self.directory / "sessions.sqlite3")
        app.mode = "mock"
        async with app.run_test(size=(150, 42)) as pilot:
            app.screen.query_one("#login-user", Select).value = "U001"
            await pilot.click("#sign-in")
            await test_tui_p0.P0Test.await_state(self, pilot, lambda: app.user == "U001")
            await test_tui_p0.P0Test.send(self, app, pilot, "/edit " + EDIT_TEXT)
            await test_tui_p0.P0Test.await_state(self, pilot, lambda: isinstance(app.screen, Approval))
            draft, = app.agent.update_session.drafts.values()
            with patch("app.updates._readback", side_effect=sqlite3.OperationalError("readback failed")):
                app.screen.query_one("#approve").press()
                await test_tui_p0.P0Test.await_state(self, pilot, lambda: not app.busy)
            self.assertEqual(app.agent.write_receipt["status"], "UNKNOWN_OUTCOME")
            original = ("资料打印", [(draft.request_id, "COMMITTED")])
            self.assertEqual(snapshot(self.path), original)

            app.agent.model = scripted_model([tool("get_invoice", TARGET), FINAL])
            await test_tui_p0.P0Test.send(self, app, pilot, QUERY)
            await test_tui_p0.P0Test.await_state(self, pilot, lambda: not app.busy)
            cards = app.workspace_widget("#business-log", ChatLog).entries
            self.assertIn("资料打印", str(cards[-1].renderable))
            self.assertEqual(app.agent.write_receipt["status"], "UNKNOWN_OUTCOME")

            await pilot.press("f4")
            self.assertEqual(app.agent.write_receipt["status"], "UNKNOWN_OUTCOME")
            self.assertEqual(app.agent.write_receipt["request_id"], draft.request_id)
            note = str(app.workspace_widget("#chat-note", Static).renderable)
            self.assertIn(draft.request_id, note)
            self.assertNotIn("已取消当前未提交操作", note)

            proposal = {"selection_id": "unresolved", "field": "purpose", "new_value": "会议资料",
                        "mode": "item", "excluded_invoice_ids": [], "target_year": 2026, "target_month": 9}
            for request, reply in (("/edit " + RETRY_TEXT, tool("prepare_invoice_update", {**EDIT, "new_value": "会议资料"})),
                                   (RETRY_TEXT, tool("propose_invoice_changes", proposal))):
                app.agent.model = scripted_model([reply, FINAL])
                await test_tui_p0.P0Test.send(self, app, pilot, request)
                await test_tui_p0.P0Test.await_state(self, pilot, lambda: not app.busy or isinstance(app.screen, Approval))
                self.assertNotIsInstance(app.screen, Approval)
                self.assertFalse(app.agent.update_session.drafts)
                self.assertNotIn("invoice_change", app.agent.last_response)
                self.assertEqual(app.agent.write_receipt["request_id"], draft.request_id)
                self.assertEqual(snapshot(self.path), original)

            await test_tui_p0.P0Test.send(self, app, pilot, "/inspect-update")
            self.assertEqual(app.agent.write_receipt["status"], "COMMITTED")
            self.assertTrue(app.agent.write_receipt["readback_verified"])
            self.assertEqual(snapshot(self.path), original)
            await pilot.press("f4")
            self.assertEqual(app.agent.write_receipt["status"], "COMMITTED")

            app.agent.model = scripted_model([tool("prepare_invoice_update", {**EDIT, "new_value": "会议资料"})])
            await test_tui_p0.P0Test.send(self, app, pilot, "/edit " + RETRY_TEXT)
            await test_tui_p0.P0Test.await_state(self, pilot, lambda: isinstance(app.screen, Approval))
            app.screen.query_one("#cancel").press()
            await test_tui_p0.P0Test.await_state(self, pilot, lambda: not app.busy)
            self.assertEqual(snapshot(self.path), original)

    def test_cli_cancel_query_retry_and_reconcile(self):
        agent = Agent("U001", self.path, scripted_model([tool("prepare_invoice_update", EDIT)]), mode="mock",
                      trace_path=self.directory / "cli.jsonl")
        original = {}
        output = io.StringIO()

        def keyboard():
            yield "/edit " + EDIT_TEXT
            draft, = agent.update_session.drafts.values()
            original["id"] = draft.request_id
            with patch("app.updates._readback", side_effect=sqlite3.OperationalError("readback failed")):
                yield "confirm " + draft.request_id
                yield "/cancel"
                self.assertEqual(agent.write_receipt["status"], "UNKNOWN_OUTCOME")
                self.assertEqual(agent.write_receipt["request_id"], draft.request_id)
                agent.model = scripted_model([tool("get_invoice", TARGET), FINAL])
                yield QUERY
                self.assertEqual(agent.write_receipt["request_id"], draft.request_id)
                agent.model = scripted_model([tool("prepare_invoice_update", {**EDIT, "new_value": "会议资料"}), FINAL])
                yield "/edit " + RETRY_TEXT
                self.assertFalse(agent.update_session.drafts)
                self.assertFalse(agent.update_session.confirmations)
                self.assertEqual(agent.commit_update(draft.request_id, draft.fingerprint())["status"], "UNKNOWN_OUTCOME")
                yield "/inspect-update"
                self.assertEqual(agent.write_receipt["status"], "UNKNOWN_OUTCOME")
            yield "/inspect-update"
            yield "exit"

        inputs = keyboard()
        with patch("builtins.input", side_effect=lambda _prompt: next(inputs)), redirect_stdout(output):
            chat_loop(agent, SimpleNamespace(user="U001", mode="mock"), {}, json.dumps, None)
        self.assertNotIn('"status": "CANCELLED"', output.getvalue())
        self.assertEqual(output.getvalue().count("才提交，其余输入取消"), 1)
        self.assertEqual(agent.write_receipt["status"], "COMMITTED")
        self.assertEqual(agent.write_receipt["request_id"], original["id"])
        self.assertEqual(snapshot(self.path), ("资料打印", [(original["id"], "COMMITTED")]))

    def test_reconciliation_distinguishes_current_value_changed_from_missing_evidence(self):
        agent = Agent("U001", self.path, scripted_model([tool("prepare_invoice_update", EDIT)]), mode="mock")
        agent.ask(EDIT_TEXT, allow_prepare=True)
        draft, = agent.update_session.drafts.values()
        with patch("app.updates._readback", return_value={"status": "DENIED"}):
            self.assertEqual(agent.commit_update(draft.request_id, draft.fingerprint())["status"], "UNKNOWN_OUTCOME")
        with patch("app.write_coordination.inspect_request", return_value={"status": "NOT_FOUND"}) as lookup:
            self.assertEqual(agent.reconcile_update()["status"], "UNKNOWN_OUTCOME")
            lookup.assert_called_once_with(self.path, "U001", draft.request_id)
        self.assertEqual(agent.cancel_update()["request_id"], draft.request_id)

        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE invoices SET purpose='后来变更' WHERE company_id='C001' AND invoice_no='F002'")
        receipt = agent.reconcile_update()
        self.assertEqual(receipt["status"], "CURRENT_VALUE_CHANGED")
        self.assertEqual(receipt["request_id"], draft.request_id)
        self.assertFalse(receipt["readback_verified"])
        self.assertEqual(receipt["data"]["data"]["historical_commit"]["status"], "COMMITTED")
        self.assertFalse(receipt["data"]["data"]["current_matches"])
        self.assertEqual(snapshot(self.path), ("后来变更", [(draft.request_id, "COMMITTED")]))
