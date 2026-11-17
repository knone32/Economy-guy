"""Read-only invoice continuation and explicit cancellation through normal entry points."""
import io
import json
import sqlite3
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from textual.widgets import Select

from app.agent import Agent, scripted_model
from app.cli_chat import chat_loop
from app.cli_workspaces import import_workspace
from app.model_config import DEFAULT_TEMPLATE
from app.tui import AgentWorkspace, ChatLog
from tests import test_tui_p0


FIRST = {"company_id": "C001", "invoice_no": "F002"}
SECOND = {"company_id": "C001", "invoice_no": "F003"}
REQUEST = "查 C001 的 F002，然后再查 C001 的另一张发票。"
CLARIFY = {"role": "assistant", "content": json.dumps({
    "kind": "clarification", "text": "请提供第二张的发票编号。", "missing_fields": ["invoice_no"],
}, ensure_ascii=False)}
FINAL = test_tui_p0.FINAL
tool = test_tui_p0.tool


class QueryContinuityTests(unittest.IsolatedAsyncioTestCase):
    await_state = test_tui_p0.P0Test.await_state

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / "workbook.db"
        import_workspace(test_tui_p0.FIXTURE, self.path)

    def app(self, *replies):
        app = AgentWorkspace(self.path, DEFAULT_TEMPLATE, self.directory / "no-profiles.json",
                             model=scripted_model(replies), trace_path=self.directory / "workbench.jsonl",
                             session_path=self.directory / "sessions.sqlite3")
        app.mode = "mock"
        return app

    async def login(self, app, pilot):
        app.screen.query_one("#login-user", Select).value = "U001"
        await pilot.click("#sign-in")
        await self.await_state(pilot, lambda: app.user == "U001")

    async def ask(self, app, pilot, text):
        previous = app.agent.trace_id if app.agent else None
        await test_tui_p0.P0Test.send(self, app, pilot, text)
        await self.await_state(pilot, lambda: app.agent and app.agent.trace_id != previous and not app.busy)
        return app.agent.last_response

    def assert_zero_audit(self):
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM invoice_audit").fetchone(), (0,))

    async def test_workbench_shows_first_invoice_and_uses_pending_scope_for_bare_number(self):
        app = self.app(tool("get_invoice", FIRST), CLARIFY)
        async with app.run_test(size=(150, 42)) as pilot:
            await self.login(app, pilot)
            first = await self.ask(app, pilot, REQUEST)
            self.assertEqual(first["execution"]["stop_reason"], "WAITING_USER")
            self.assertIn("F002", first["chat_notice"])
            self.assertIn("第二张", first["chat_notice"])
            books = app.workspace_widget("#business-log", ChatLog).entries
            self.assertIn("F002", str(books[-1].renderable))
            self.assertEqual(app.agent.pending_intent["scope"], {"company_id": ["C001"]})
            self.assertEqual(app.agent.pending_intent["request"], REQUEST)

            model = Mock(side_effect=AssertionError("续查的企业应该来自可信追问状态"))
            app.agent.model = model
            duplicate = await self.ask(app, pilot, "F002")
            self.assertEqual(duplicate["execution"]["stop_reason"], "WAITING_USER")
            self.assertIn("另一张", duplicate["chat_notice"])
            self.assertIsNotNone(app.agent.pending_intent)
            followup = await self.ask(app, pilot, "F003")
            model.assert_not_called()
            self.assertIsNone(app.agent.pending_intent)
            self.assertEqual([outcome["status"] for _, outcome in followup["tool_results"]], ["SUCCESS"])
            data = followup["tool_results"][0][1]["data"]
            self.assertEqual({key: data[key] for key in SECOND}, SECOND)
            self.assertIn("F003", str(app.workspace_widget("#business-log", ChatLog).entries[-1].renderable))
            self.assertEqual(followup["execution"]["actual_tool_calls"], 1)
            self.assertEqual(app.records[-1][1][0]["arguments"], SECOND)
            self.assert_zero_audit()

        entries = [json.loads(line) for line in (self.directory / "workbench.jsonl").read_text(
            encoding="utf-8").splitlines()]
        event, = [entry["data"] for entry in entries if entry["event"] == "invoice.followup_read"]
        self.assertEqual(event["original_request"], REQUEST)
        self.assertEqual(event["arguments"], SECOND)
        self.assertEqual(event["provenance"]["sources"], {"company_id": "session_confirmed", "invoice_no": "user_current"})

    def test_followup_rechecks_current_read_permission(self):
        agent = Agent("U001", self.path, scripted_model([tool("get_invoice", FIRST), CLARIFY]), mode="mock")
        agent.ask(REQUEST)
        self.assertIsNotNone(agent.pending_intent)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE permissions SET can_read=0 WHERE user_id='U001' AND company_id='C001'")
        agent.model = Mock(side_effect=AssertionError("可信读取应直接复查权限"))
        agent.ask("F003")
        agent.model.assert_not_called()
        outcome = agent.last_response["tool_results"][0][1]
        self.assertEqual(outcome["status"], "DENIED")
        self.assertIsNone(outcome["data"])
        self.assert_zero_audit()

    def test_bare_number_without_pending_question_cannot_invent_a_company(self):
        agent = Agent("U001", self.path, scripted_model([tool("get_invoice", SECOND), FINAL]), mode="mock")
        agent.ask("F003")
        self.assertEqual(agent.last_response["tool_results"][0][1]["status"], "AMBIGUOUS")
        self.assert_zero_audit()

    async def test_workbench_cancel_retires_relative_invoice_and_allows_explicit_key(self):
        app = self.app(tool("get_invoice", FIRST), FINAL)
        async with app.run_test(size=(150, 42)) as pilot:
            await self.login(app, pilot)
            first = await self.ask(app, pilot, "查询 C001 的 F002 当前用途")
            self.assertEqual(first["tool_results"][0][1]["status"], "SUCCESS")
            for command in ("f4", "/cancel"):
                with self.subTest(command=command):
                    if command == "f4":
                        await pilot.press("f4")
                    else:
                        await test_tui_p0.P0Test.send(self, app, pilot, command)
                    self.assertIsNone(app.agent.context.recent_invoice_query)
                    model = Mock(return_value=tool("resolve_recent_invoice", {"source": "queried"}))
                    app.agent.model = model
                    relative = await self.ask(app, pilot, "刚才那张发票")
                    model.assert_not_called()
                    self.assertEqual(relative["category"], "reference_error")
                    self.assertIn("发票编号", relative["chat_notice"])
                    self.assertFalse(relative["tool_results"])
                    app.agent.model = scripted_model([tool("get_invoice", FIRST), FINAL])
                    explicit = await self.ask(app, pilot, "C001/F002")
                    self.assertEqual(explicit["tool_results"][0][1]["data"]["invoice_no"], "F002")
            self.assert_zero_audit()

    def test_cli_cancel_retires_relative_invoice_and_allows_explicit_key(self):
        agent = Agent("U001", self.path, scripted_model([tool("get_invoice", FIRST), FINAL]), mode="mock",
                      trace_path=self.directory / "cli.jsonl")
        output = io.StringIO()

        def keyboard():
            yield "查询 C001 的 F002 当前用途"
            self.assertEqual(agent.last_response["tool_results"][0][1]["status"], "SUCCESS")
            yield "/cancel"
            model = Mock(return_value=tool("get_invoice", FIRST))
            agent.model = model
            yield "刚才那张发票"
            model.assert_not_called()
            self.assertEqual(agent.last_response["category"], "reference_error")
            self.assertFalse(agent.last_response["tool_results"])
            agent.model = scripted_model([tool("get_invoice", FIRST), FINAL])
            yield "C001/F002"
            self.assertEqual(agent.last_response["tool_results"][0][1]["data"]["invoice_no"], "F002")
            yield "exit"

        inputs = keyboard()
        with patch("builtins.input", side_effect=lambda _prompt: next(inputs)), redirect_stdout(output):
            chat_loop(agent, None, {}, json.dumps, None)
        self.assertIn("发票编号", output.getvalue())
        self.assert_zero_audit()

    def test_cancel_retires_recent_modification_without_touching_commit_audit(self):
        edit = {**FIRST, "field": "purpose", "new_value": "资料打印"}
        agent = Agent("U001", self.path, scripted_model([tool("prepare_invoice_update", edit)]), mode="mock")
        agent.ask("把 C001 的 F002 用途改为资料打印", allow_prepare=True)
        draft, = agent.update_session.drafts.values()
        self.assertEqual(agent.commit_update(draft.request_id, draft.fingerprint())["status"], "COMMITTED")
        self.assertIn("modified", agent.context.recent_invoice_candidates(agent.trusted_events))
        self.assertEqual(agent.cancel_update()["status"], "COMMITTED")
        self.assertFalse(agent.context.recent_invoice_candidates(agent.trusted_events))
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as db:
            self.assertEqual(db.execute("SELECT request_id, status FROM invoice_audit").fetchall(),
                             [(draft.request_id, "COMMITTED")])
