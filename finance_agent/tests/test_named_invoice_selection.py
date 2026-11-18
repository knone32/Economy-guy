"""Recover a named invoice list only from verified reads in the same turn."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from textual.widgets import Select

from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.invoice_batch import run_invoice_batch
from app.model_config import DEFAULT_TEMPLATE
from app.tui import AgentWorkspace
from app.tui_screens import Approval
from app.updates import inspect_request
from tests import test_tui_p0
from tests.test_sql_invoice_selection import snapshot


LIVE_REQUEST = "请把 C002 2026年9月的发票 F006 和 F007 的备注都改为秋季培训费用待复核"
VALUE = "秋季培训费用待复核"
LIVE_KEYS = (("C002", "F006"), ("C002", "F007"))
LIVE_SQL = "SELECT company_id, invoice_no FROM invoices WHERE company_id = 'C002' AND invoice_no IN ('F006','F007')"


def tool_group(name, args):
    tools = [test_tui_p0.tool(name, value, f"{name}-{index}")["tool_calls"][0]
             for index, value in enumerate(args)]
    return {"role": "assistant", "tool_calls": tools}


def named_read_model(keys=LIVE_KEYS, *, value=VALUE, field="remark", excluded=(), selection_override=None, sql=None):
    rounds = iter(("read", "sql", "propose") if sql else ("read", "propose"))

    def model(messages, _tools):
        stage = next(rounds)
        if stage == "read":
            return tool_group("get_invoice", ({"company_id": c, "invoice_no": n} for c, n in keys))
        if stage == "sql":
            return tool_group("query_business_sql", ({"sql": sql},))
        selections = [data["selection_id"] for message in messages if message["role"] == "tool"
                      if (data := json.loads(message["content"]).get("data")) and data.get("selection_id")]
        count = 1 if sql else len(keys)
        selections = [selection_override] if selection_override else selections[-count:]
        return tool_group("propose_invoice_changes", (
            {"selection_id": selection, "field": field, "new_value": value, "mode": "batch",
             "excluded_invoice_ids": list(excluded), "target_year": 2026, "target_month": 9}
            for selection in selections
        ))

    return model


class NamedInvoiceSelectionTests(unittest.IsolatedAsyncioTestCase):
    await_state = test_tui_p0.P0Test.await_state

    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "official.db"
        import_workspace(test_tui_p0.FIXTURE, self.path)

    def ask(self, request=LIVE_REQUEST, *, user="U001", model=None, read_workspace=None):
        agent = Agent(user, self.path, model or named_read_model(), mode="mock",
                      trace_path=self.path.with_name("agent.jsonl"))
        agent.ask(request, read_workspace=read_workspace)
        return agent

    def test_live_order_recovers_one_preview_with_item_confirmation(self):
        before = snapshot(self.path)
        agent = self.ask()
        outcome = agent.last_response
        self.assertEqual([(name, result["status"]) for name, result in outcome["tool_results"]],
                         [("get_invoice", "SUCCESS"), ("get_invoice", "SUCCESS"),
                          ("propose_invoice_changes", "WAITING_CONFIRMATION"),
                          ("propose_invoice_changes", "DENIED")])
        proposal = outcome["invoice_change"]
        self.assertEqual((proposal["actor"], proposal["workbook"], proposal["turn"]),
                         ("U001", str(self.path), agent.trace_id))
        self.assertEqual((proposal["company_id"], proposal["year"], proposal["month"]), ("C002", 2026, 9))
        self.assertEqual((proposal["invoice_nos"], proposal["field"], proposal["new_value"], proposal["mode"]),
                         (("F006", "F007"), "remark", VALUE, "item"))
        self.assertFalse(agent.update_session.drafts)
        self.assertEqual(snapshot(self.path), before)

    def test_live_sql_selection_defaults_to_item_without_explicit_batch_request(self):
        for request, value in ((LIVE_REQUEST, VALUE), (LIVE_REQUEST.replace(VALUE, "“整批确认”"), "整批确认")):
            with self.subTest(request=request):
                agent = self.ask(request, model=named_read_model(value=value, sql=LIVE_SQL))
                response = agent.last_response
                self.assertEqual([(name, result["status"]) for name, result in response["tool_results"]],
                                 [("get_invoice", "SUCCESS"), ("get_invoice", "SUCCESS"),
                                  ("query_business_sql", "SUCCESS"), ("propose_invoice_changes", "WAITING_CONFIRMATION")])
                proposal = response["invoice_change"]
                self.assertEqual((proposal["invoice_nos"], proposal["new_value"], proposal["mode"]),
                                 (("F006", "F007"), value, "item"))
                self.assertFalse(agent.update_session.drafts)
        self.assertEqual(snapshot(self.path)[1], [])

    async def test_sql_workbench_shows_item_or_batch_only_as_requested(self):
        before = snapshot(self.path)
        app = AgentWorkspace(self.path, DEFAULT_TEMPLATE, self.path.with_name("no-profiles.json"),
                             model=named_read_model(sql=LIVE_SQL), trace_path=self.path.with_name("workbench.jsonl"),
                             session_path=self.path.with_name("sessions.sqlite3"))
        app.mode = "mock"
        async with app.run_test(size=(150, 42)) as pilot:
            app.screen.query_one("#login-user", Select).value = "U001"
            await pilot.click("#sign-in")
            await self.await_state(pilot, lambda: app.user == "U001")
            for suffix, title in (("", "逐张确认发票修改"), ("，整批确认", "确认整批发票修改")):
                records = len(app.records)
                if app.agent:
                    app.agent.model = named_read_model(sql=LIVE_SQL)
                await test_tui_p0.P0Test.send(self, app, pilot, LIVE_REQUEST + suffix)
                await self.await_state(pilot, lambda: isinstance(app.screen, Approval)
                                       and bool(app.screen.query("#approve"))
                                       and bool(app.screen.query("#cancel")))
                self.assertEqual(app.screen.title_text, title)
                self.assertIn("全部匹配 2 张", app.screen.body)
                self.assertEqual(snapshot(self.path), before)
                app.screen.answer(False)
                await self.await_state(pilot, lambda: len(app.records) > records and not app.busy)
                self.assertEqual(snapshot(self.path), before)

    def test_named_recovery_accepts_other_company_and_reversed_order(self):
        named = "请将 2026-09 的甲企业发票 F006、F004 的备注统一设置为差旅凭证待复核"
        keys = (("C001", "F004"), ("C001", "F006"))
        agent = self.ask(named, model=named_read_model(keys, value="差旅凭证待复核"))
        change = agent.last_response["invoice_change"]
        self.assertEqual((change["company_id"], change["invoice_nos"], change["mode"]),
                         ("C001", ("F004", "F006"), "item"))
        three = self.ask(named.replace("F006、F004", "F006、F004 和 F002 三张发票"),
                         model=named_read_model((*keys, ("C001", "F002")), value="差旅凭证待复核"))
        self.assertEqual(three.last_response["invoice_change"]["invoice_nos"], ("F002", "F004", "F006"))
        topic = "C002 2026年9月的 F006 和 F007，备注都填成秋季培训费用待复核。"
        topic_change = self.ask(topic).last_response["invoice_change"]
        self.assertEqual((topic_change["invoice_nos"], topic_change["new_value"], topic_change["mode"]),
                         (("F006", "F007"), VALUE, "item"))
        quoted = VALUE + "（但不含已作废）"
        literal = self.ask(LIVE_REQUEST.replace(VALUE, f"“{quoted}”"),
                           model=named_read_model(value=quoted)).last_response["invoice_change"]
        self.assertEqual(literal["new_value"], quoted)
        self.assertEqual(snapshot(self.path)[1], [])

    def test_explicit_batch_confirmation_and_exclusion_keep_user_scope(self):
        explicit = LIVE_REQUEST + "，排除 F008，整批确认"
        for sql in (None, LIVE_SQL):
            with self.subTest(sql=sql):
                agent = self.ask(explicit, model=named_read_model(excluded=("F008",), sql=sql))
                change = agent.last_response["invoice_change"]
                self.assertEqual((change["invoice_nos"], change["excluded"], change["mode"]),
                                 (("F006", "F007"), ("F008",), "batch"))
                self.assertFalse(agent.update_session.drafts)
        self.assertEqual(snapshot(self.path)[1], [])

    def test_incomplete_or_untrusted_reads_and_ambiguous_intent_do_not_preview(self):
        before = snapshot(self.path)
        controls = (
            ("one read", LIVE_REQUEST, "U001", named_read_model(LIVE_KEYS[:1]), None),
            ("unauthorized", LIVE_REQUEST, "U002", named_read_model(), None),
            ("no modify", LIVE_REQUEST.replace("C002", "C001").replace("F007", "F004"), "U002",
             named_read_model((("C001", "F006"), ("C001", "F004"))), None),
            ("extra invoice", LIVE_REQUEST, "U001", named_read_model((*LIVE_KEYS, ("C002", "F005"))), None),
            ("wrong company", LIVE_REQUEST, "U001", named_read_model((("C001", "F006"), LIVE_KEYS[1])), None),
            ("wrong date", LIVE_REQUEST.replace("9月", "8月"), "U001", named_read_model(), None),
            ("no date", LIVE_REQUEST.replace("2026年9月的", ""), "U001", named_read_model(), ("C002", 2026, 9)),
            ("no company", LIVE_REQUEST.replace("C002 ", ""), "U001", named_read_model(), ("C002", 2026, 9)),
            ("forged selection", LIVE_REQUEST, "U001", named_read_model(selection_override="another-turn-untrusted-selection"), None),
            ("wrong field", LIVE_REQUEST, "U001", named_read_model(field="purpose"), None),
            ("different value", LIVE_REQUEST, "U001", named_read_model(value="模型补写"), None),
            ("extra filter", LIVE_REQUEST.replace("的备注", "中金额超过1000元的备注"), "U001", named_read_model(), None),
            ("trailing condition", LIVE_REQUEST + "若审核通过", "U001",
             named_read_model(value=VALUE + "若审核通过"), None),
            ("parenthetical filter", LIVE_REQUEST + "（但不含已作废）", "U001",
             named_read_model(value=VALUE + "（但不含已作废）"), None),
            ("wrong exclusion", LIVE_REQUEST + "，排除 F008", "U001", named_read_model(), None),
        )
        for label, request, user, model, workspace in controls:
            with self.subTest(label=label):
                agent = self.ask(request, user=user, model=model, read_workspace=workspace)
                self.assertNotIn("invoice_change", agent.last_response)
                self.assertFalse(agent.update_session.drafts)
                self.assertEqual(snapshot(self.path), before)
        trace = self.path.with_name("agent.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("invoice_selection.recovered", trace)

    def test_selection_id_from_a_cancelled_turn_cannot_restore_a_new_batch(self):
        agent = self.ask()
        previous_id = agent.last_response["tool_results"][0][1]["data"]["selection_id"]
        previous_proposal = agent.last_response["invoice_change"]
        other = self.path.with_name("other.db")
        import_workspace(test_tui_p0.FIXTURE, other)
        other_agent = Agent("U001", other, mode="mock")
        other_agent.trace_id = agent.trace_id
        status, _ = run_invoice_batch(other_agent, LIVE_REQUEST, previous_proposal,
                                      approve_batch=None, approve_item=None, checkpoint=None)
        self.assertEqual(status, "DENIED")
        self.assertEqual(snapshot(other)[1], [])
        agent.cancel_update()
        agent.model = named_read_model(selection_override=previous_id)
        agent.ask(LIVE_REQUEST)
        self.assertEqual(agent.last_response["execution"]["stop_reason"], "AMBIGUOUS")
        self.assertNotIn("invoice_change", agent.last_response)
        self.assertFalse(agent.update_session.drafts)
        self.assertEqual(snapshot(self.path)[1], [])

    async def test_workbench_cancel_and_guided_item_confirm_verify_both_audits(self):
        before = snapshot(self.path)
        app = AgentWorkspace(self.path, DEFAULT_TEMPLATE, self.path.with_name("no-profiles.json"),
                             model=named_read_model(), trace_path=self.path.with_name("workbench.jsonl"),
                             session_path=self.path.with_name("sessions.sqlite3"))
        app.mode = "mock"
        async with app.run_test(size=(150, 42)) as pilot:
            app.screen.query_one("#login-user", Select).value = "U001"
            await pilot.click("#sign-in")
            await self.await_state(pilot, lambda: app.user == "U001")
            for approve in (False, True):
                records = len(app.records)
                if app.agent:
                    app.agent.model = named_read_model()
                await test_tui_p0.P0Test.send(self, app, pilot, LIVE_REQUEST)
                await self.await_state(pilot, lambda: isinstance(app.screen, Approval))
                first = app.screen
                self.assertEqual(first.title_text, "逐张确认发票修改")
                self.assertIn("全部匹配 2 张", first.body)
                self.assertIn("F006\n原值", first.body)
                self.assertIn("F007\n原值", first.body)
                self.assertEqual(snapshot(self.path), before)
                first.answer(approve)
                if approve:
                    await self.await_state(pilot, lambda: isinstance(app.screen, Approval) and app.screen is not first)
                    self.assertIn("第 2 / 2 张\nF007", app.screen.body)
                    self.assertEqual([row["invoice_no"] for row in snapshot(self.path)[1]], ["F006"])
                    app.screen.answer(True)
                await self.await_state(pilot, lambda: len(app.records) > records and not app.busy)
                if not approve:
                    self.assertEqual(snapshot(self.path), before)
        rows, audits = snapshot(self.path)
        self.assertEqual(rows, {**before[0], **{key: {**before[0][key], "remark": VALUE} for key in LIVE_KEYS}})
        self.assertEqual([(row["company_id"], row["invoice_no"]) for row in audits], list(LIVE_KEYS))
        self.assertEqual(len({row["request_id"] for row in audits}), 2)
        for row in audits:
            self.assertEqual((row["actor"], row["field"], row["status"]), ("U001", "remark", "COMMITTED"))
            readback = inspect_request(self.path, "U001", row["request_id"])
            self.assertEqual(readback["status"], "COMMITTED")
            self.assertEqual(readback["data"]["current_invoice"]["remark"], VALUE)
            self.assertEqual(readback["data"]["historical_commit"]["request_id"], row["request_id"])
