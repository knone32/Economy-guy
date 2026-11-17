"""Exercise the compatibility chat's transition to a trusted invoice edit."""
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from textual.widgets import Select

from app.agent import Agent, scripted_model
from app.cli_chat import chat_loop, invoice_proposal_guidance
from app.cli_workspaces import import_workspace
from app.model_config import DEFAULT_TEMPLATE
from app.tui import AgentWorkspace
from app.tui_screens import Approval
from tests import test_tui_p0
from tests.test_unknown_cancel import EDIT, EDIT_TEXT, FINAL, FIXTURE, QUERY, TARGET, snapshot, tool


PROPOSAL = {
    "selection_id": "unresolved", "field": "purpose", "new_value": "资料打印", "mode": "item",
    "excluded_invoice_ids": [], "target_year": 2026, "target_month": 9,
}


class ConfirmEntryTests(unittest.IsolatedAsyncioTestCase):
    await_state = test_tui_p0.P0Test.await_state
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "isolated.db"
        import_workspace(FIXTURE, self.path)
        self.agent = Agent("U001", self.path, scripted_model([tool("propose_invoice_changes", PROPOSAL)]),
                           mode="mock", trace_path=self.path.with_suffix(".jsonl"))
        self.output = io.StringIO()
        self.prompts = []

    def chat(self, inputs):
        inputs = iter(inputs)

        def keyboard(prompt):
            self.prompts.append(prompt)
            return next(inputs)

        with patch("builtins.input", side_effect=keyboard), redirect_stdout(self.output):
            chat_loop(self.agent, None, {}, lambda value, **kw: json.dumps(value, ensure_ascii=False, **kw), None)

    def suggested_edit(self):
        text = self.output.getvalue()
        self.assertIn("本轮尚未提交", text)
        self.assertNotIn("等待人工确认", text)
        self.assertNotIn("WAITING_CONFIRMATION", text)
        commands = [line for line in text.splitlines() if line.startswith("/edit ")]
        self.assertEqual(commands, ["/edit " + EDIT_TEXT])
        self.assertFalse(self.agent.update_session.drafts)
        self.assertEqual(snapshot(self.path), (None, []))
        return commands[0]

    def test_batch_or_context_dependent_proposal_points_to_workbench(self):
        proposal = {"source_request": EDIT_TEXT, "invoice_nos": ("F002", "F003"), "company_id": "C001",
                    "new_value": "资料打印", "field": "purpose"}
        cases = (proposal, {**proposal, "invoice_nos": ("F002",), "source_request": "把它的用途改为资料打印"},
                 {**proposal, "invoice_nos": ("F002",), "rule_reference": {"rule_id": "R002"}})
        for case in cases:
            with self.subTest(case=case):
                notice = invoice_proposal_guidance(case)
                self.assertIn("同一账簿", notice)
                self.assertIn("python main.py tui", notice)
                self.assertIn("确认或取消", notice)
                self.assertNotIn("/edit ", notice)

    def test_proposal_gives_executable_edit_and_exit_leaves_no_audit(self):
        self.chat([EDIT_TEXT, "exit"])
        self.suggested_edit()
        self.assertEqual(self.prompts, ["你：", "你："])

    def test_follow_guidance_displays_a_fresh_draft_and_cancel_leaves_no_audit(self):
        def inputs():
            yield EDIT_TEXT
            command = self.suggested_edit()
            self.agent.model = scripted_model([tool("prepare_invoice_update", EDIT)])
            yield command
            draft, = self.agent.update_session.drafts.values()
            for field, expected in {"company_id": "C001", "invoice_no": "F002", "field": "purpose",
                                    "old_value": None, "new_value": "资料打印"}.items():
                self.assertEqual(getattr(draft, field), expected)
            self.assertIn("confirm " + draft.request_id, self.output.getvalue())
            yield "/cancel"
            self.assertEqual(self.agent.write_receipt["status"], "CANCELLED")
            yield "exit"

        self.chat(inputs())
        self.assertEqual(self.prompts, ["你：", "你：", "最终确认：", "你："])
        self.assertEqual(snapshot(self.path), (None, []))

    def test_follow_guidance_requires_final_confirmation_and_preserves_verified_commit(self):
        request = {}

        def inputs():
            yield EDIT_TEXT
            command = self.suggested_edit()
            self.agent.model = scripted_model([tool("prepare_invoice_update", EDIT)])
            yield command
            draft, = self.agent.update_session.drafts.values()
            request["id"] = draft.request_id
            self.assertEqual(snapshot(self.path), (None, []))
            yield "confirm " + draft.request_id
            self.assertTrue(self.agent.write_receipt["readback_verified"])
            self.assertEqual(self.agent.write_receipt["status"], "COMMITTED")
            yield "/cancel"
            self.assertEqual(self.agent.write_receipt["status"], "COMMITTED")
            self.agent.model = scripted_model([tool("get_invoice", TARGET), FINAL])
            yield QUERY
            self.assertEqual(self.agent.last_response["tool_results"][0][1]["data"]["purpose"], "资料打印")
            yield "exit"

        self.chat(inputs())
        self.assertEqual(snapshot(self.path), ("资料打印", [(request["id"], "COMMITTED")]))

    async def test_workbench_confirms_or_cancels_the_same_natural_proposal(self):
        app = AgentWorkspace(self.path, DEFAULT_TEMPLATE, self.path.with_name("no-profiles.json"),
                             model=scripted_model([tool("propose_invoice_changes", PROPOSAL)]),
                             trace_path=self.path.with_name("workbench.jsonl"),
                             session_path=self.path.with_name("sessions.sqlite3"))
        app.mode = "mock"
        async with app.run_test(size=(150, 42)) as pilot:
            app.screen.query_one("#login-user", Select).value = "U001"
            await pilot.click("#sign-in")
            await self.await_state(pilot, lambda: app.user == "U001")
            for confirmed in (False, True):
                records = len(app.records)
                if app.agent:
                    app.agent.model = scripted_model([tool("propose_invoice_changes", PROPOSAL)])
                await test_tui_p0.P0Test.send(self, app, pilot, EDIT_TEXT)
                await self.await_state(pilot, lambda: isinstance(app.screen, Approval))
                for value in ("C001", "F002", "用途", "原值", "新值", "资料打印"):
                    self.assertIn(value, app.screen.body)
                self.assertEqual(snapshot(self.path), (None, []))
                app.screen.answer(confirmed)
                await self.await_state(pilot, lambda: len(app.records) > records and not app.busy)
                if not confirmed:
                    self.assertEqual(snapshot(self.path), (None, []))
        value, audit = snapshot(self.path)
        self.assertEqual(value, "资料打印")
        self.assertEqual([status for _, status in audit], ["COMMITTED"])
