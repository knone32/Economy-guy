"""Verify ordinary SQL invoice selections through the trusted workbench."""
import io
import json
import sqlite3
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from textual.widgets import Select

from app.agent import Agent
from app.business_sql import BusinessSQL
from app.cli_chat import chat_loop
from app.cli_workspaces import import_workspace
from app.model_config import DEFAULT_TEMPLATE
from app.provenance import ScopeProof
from app.tool_registry import handle_tool
from app.tui import AgentWorkspace
from app.tui_screens import Approval
from app.updates import inspect_request
from tests import test_tui_p0


SQL = ("SELECT company_id, invoice_no FROM invoices WHERE company_id='C001' "
       "AND invoice_date >= '2026-09-01' AND invoice_date < '2026-10-01' "
       "AND (invoice_no='F002' OR invoice_no='F003')")
REQUEST = "将 C001 2026年9月的 F002 和 F003 两张发票的备注均改为社区演练归档"
NEW_REMARK = "社区演练归档"
KEYS = (("C001", "F002"), ("C001", "F003"))


def ordinary_sql_model(sql=SQL):
    calls = iter((True, False))

    def model(messages, _tools):
        if next(calls):
            return test_tui_p0.tool("query_business_sql", {"sql": sql})
        response = next(item for item in reversed(messages) if item["role"] == "tool")
        data = json.loads(response["content"])["data"]
        return test_tui_p0.tool("propose_invoice_changes", {
            "selection_id": data["selection_id"], "field": "remark", "new_value": NEW_REMARK,
            "mode": "item", "excluded_invoice_ids": [], "target_year": 2026, "target_month": 9,
        })

    return model


def snapshot(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        invoices = {(row["company_id"], row["invoice_no"]): dict(row) for row in db.execute("SELECT * FROM invoices")}
        audit = [dict(row) for row in db.execute("SELECT * FROM invoice_audit ORDER BY rowid")]
        return invoices, audit


class OrdinarySqlSelectionTests(unittest.IsolatedAsyncioTestCase):
    await_state = test_tui_p0.P0Test.await_state

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "fixture.db"
        import_workspace(test_tui_p0.FIXTURE, self.path)

    def query(self, sql, *, user="U001", company="C001", path=None, workspace_actor=None):
        actor = workspace_actor or user
        values = {"company_id": [company], "periods": [(2026, 9)]}
        workspace = BusinessSQL(self.path, actor, ScopeProof(actor, values, dict.fromkeys(values, "user_current")))
        selections = {}
        try:
            result = handle_tool("query_business_sql", json.dumps({"sql": sql}), user, path or self.path,
                                 sql_workspace=workspace, invoice_selections=selections)
        finally:
            workspace.close()
        return result, selections

    def test_complete_filtered_keys_create_current_workbook_selection(self):
        for sql in (SQL, SQL + " AND 'SELECT' = 'SELECT'"):
            with self.subTest(sql=sql):
                result, selections = self.query(sql)
                self.assertEqual(result["status"], "SUCCESS")
                data = result["data"]
                self.assertEqual(set(data["rows"]), set(KEYS))
                self.assertFalse(data["truncated"])
                self.assertEqual(data["selection_scope"], [{"company_id": "C001", "period": "2026-09"}])
                keys, scope, source = selections[data["selection_id"]]
                self.assertEqual(set(keys), set(KEYS))
                self.assertEqual(scope["company_ids"], ("C001",))
                self.assertEqual(scope["periods"], ((2026, 9),))
                self.assertEqual(source, "query_business_sql")

    def test_limits_truncation_and_untrusted_scope_cannot_register_selection(self):
        limited, limited_selections = self.query(SQL + " LIMIT 1")
        self.assertEqual(limited["status"], "SUCCESS")
        self.assertEqual(len(limited["data"]["rows"]), 1)
        self.assertNotIn("selection_id", limited["data"])
        self.assertFalse(limited_selections)
        subquery, subquery_selections = self.query(SQL + " AND EXISTS (SELECT 1 FROM invoices)")
        self.assertEqual(subquery["status"], "SUCCESS")
        self.assertNotIn("selection_id", subquery["data"])
        self.assertFalse(subquery_selections)
        with patch("app.business_sql.MAX_RESULT_ROWS", 1):
            truncated, truncated_selections = self.query(SQL)
        self.assertTrue(truncated["data"]["truncated"])
        self.assertNotIn("selection_id", truncated["data"])
        self.assertFalse(truncated_selections)
        for sql, kwargs in (
            (SQL.replace("C001", "C002"), {"user": "U002", "company": "C002"}),
            (SQL, {"user": "U002", "workspace_actor": "U001"}),
            (SQL, {"path": self.path.with_name("other.db")}),
        ):
            with self.subTest(kwargs=kwargs):
                denied, denied_selections = self.query(sql, **kwargs)
                self.assertEqual(denied["status"], "DENIED")
                self.assertIsNone(denied["data"])
                self.assertFalse(denied_selections)

    def test_a_selection_missing_one_named_invoice_cannot_authorize_preview(self):
        agent = Agent("U001", self.path, ordinary_sql_model(SQL.replace(" OR invoice_no='F003'", "")), mode="mock")
        before = snapshot(self.path)
        agent.ask(REQUEST)
        self.assertEqual(agent.last_response["execution"]["stop_reason"], "SCOPE_MISMATCH")
        self.assertNotIn("invoice_change", agent.last_response)
        self.assertFalse(agent.update_session.drafts)
        self.assertEqual(snapshot(self.path), before)

    def test_compat_cli_exit_keeps_the_two_invoice_proposal_read_only(self):
        agent = Agent("U001", self.path, ordinary_sql_model(), mode="mock", trace_path=self.path.with_suffix(".jsonl"))
        before = snapshot(self.path)
        output = io.StringIO()
        with patch("builtins.input", side_effect=[REQUEST, "exit"]), redirect_stdout(output):
            chat_loop(agent, None, {}, json.dumps, None)
        self.assertEqual(agent.last_response["invoice_change"]["invoice_nos"], ("F002", "F003"))
        self.assertIn(" --db ", output.getvalue())
        self.assertNotIn("/edit ", output.getvalue())
        self.assertFalse(agent.update_session.drafts)
        self.assertEqual(snapshot(self.path), before)

    async def test_workbench_previews_cancels_and_confirms_only_the_two_sql_invoices(self):
        before, audit = snapshot(self.path)
        self.assertEqual(audit, [])
        app = AgentWorkspace(self.path, DEFAULT_TEMPLATE, self.path.with_name("no-profiles.json"),
                             model=ordinary_sql_model(), trace_path=self.path.with_name("workbench.jsonl"),
                             session_path=self.path.with_name("sessions.sqlite3"))
        app.mode = "mock"
        async with app.run_test(size=(150, 42)) as pilot:
            app.screen.query_one("#login-user", Select).value = "U001"
            await pilot.click("#sign-in")
            await self.await_state(pilot, lambda: app.user == "U001")
            for confirmed in (False, True):
                records = len(app.records)
                if app.agent:
                    app.agent.model = ordinary_sql_model()
                await test_tui_p0.P0Test.send(self, app, pilot, REQUEST)
                await self.await_state(pilot, lambda: isinstance(app.screen, Approval))
                self.assertIn("全部匹配 2 张", app.screen.body)
                self.assertIn("C001 · 2026-09", app.screen.body)
                self.assertIn("字段　备注", app.screen.body)
                preview = app.screen.body.split("全部匹配 2 张", 1)[1]
                self.assertEqual([line for line in preview.splitlines() if line.startswith("F")], ["F002", "F003"])
                self.assertEqual(snapshot(self.path), (before, []))
                first_dialog = app.screen
                first_dialog.answer(confirmed)
                if confirmed:
                    await self.await_state(pilot, lambda: isinstance(app.screen, Approval) and app.screen is not first_dialog)
                    self.assertIn("F003\n原值", app.screen.body)
                    self.assertEqual([row["invoice_no"] for row in snapshot(self.path)[1]], ["F002"])
                    app.screen.answer(True)
                await self.await_state(pilot, lambda: len(app.records) > records and not app.busy)
                if not confirmed:
                    self.assertEqual(snapshot(self.path), (before, []))

        after, audits = snapshot(self.path)
        expected = {**before, **{key: {**before[key], "remark": NEW_REMARK} for key in KEYS}}
        self.assertEqual(after, expected)
        self.assertEqual([(row["company_id"], row["invoice_no"]) for row in audits], list(KEYS))
        self.assertEqual(len({row["request_id"] for row in audits}), 2)
        for row in audits:
            key = (row["company_id"], row["invoice_no"])
            self.assertEqual((row["actor"], row["field"], row["old_value"], row["new_value"], row["status"]),
                             ("U001", "remark", before[key]["remark"], NEW_REMARK, "COMMITTED"))
            readback = inspect_request(self.path, "U001", row["request_id"])
            self.assertEqual(readback["status"], "COMMITTED")
            self.assertEqual(readback["data"]["current_invoice"]["remark"], NEW_REMARK)
            self.assertEqual(readback["data"]["historical_commit"]["request_id"], row["request_id"])
