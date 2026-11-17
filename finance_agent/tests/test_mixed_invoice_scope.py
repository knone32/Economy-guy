"""Regression for mixed detail reads and a separate one-invoice change."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from textual.widgets import Select

from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.model_config import DEFAULT_TEMPLATE
from app.tui import AgentWorkspace, ChatLog
from app.tui_screens import Approval
from tests import test_tui_p0
from tests.test_named_invoice_selection import tool_group
from tests.test_sql_invoice_selection import snapshot


LIVE_REQUEST = "查一下乙企业 2026 年 9 月 F006 和 F007 的用途，再只把 F007 的备注改成「培训待复核」，用途别动。"
VALUE = "培训待复核"
B_PARAPHRASE = "麻烦先核对甲企业 2026-09 F005、F010 的用途，接着仅将 F010 的备注改为『期末打印单据待对照』，用途保持原样。"
B_VALUE = "期末打印单据待对照"


def mixed_model(*, company="C002", keys=("F006", "F007"), target="F007", field="remark",
                value=VALUE, excluded=(), rule_date=None):
    calls = iter(("read", "proposal"))

    def model(messages, _tools):
        if next(calls) == "read":
            return tool_group("get_invoice", ({"company_id": company, "invoice_no": invoice} for invoice in keys))
        evidence = [json.loads(msg["content"]).get("data") for msg in messages if msg["role"] == "tool"]
        selected = next(data for data in reversed(evidence) if data and data.get("invoice_no") == target)
        proposal = {
            "selection_id": selected["selection_id"], "field": field, "new_value": value, "mode": "item",
            "excluded_invoice_ids": list(excluded), "target_year": 2026, "target_month": 9,
        }
        if rule_date is not None:
            proposal["rule_business_date"] = rule_date
        return tool_group("propose_invoice_changes", (proposal,))

    return model


def b_paraphrase_model(excluded=("F005",), keys=("F005", "F010"), **options):
    return mixed_model(company="C001", keys=keys, target="F010", value=B_VALUE, excluded=excluded, **options)


class MixedInvoiceScopeTests(unittest.IsolatedAsyncioTestCase):
    await_state = test_tui_p0.P0Test.await_state

    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "fixture.db"
        import_workspace(test_tui_p0.FIXTURE, self.path)

    def agent(self, model=None):
        return Agent("U001", self.path, model or mixed_model(), mode="mock",
                     trace_path=self.path.with_name("agent.jsonl"))

    def assert_separated(self, response, company="C002", keys=("F006", "F007")):
        results = response["tool_results"]
        reads = [result for tool, result in results if tool == "get_invoice"]
        self.assertEqual({(result["data"]["company_id"], result["data"]["invoice_no"]) for result in reads},
                         {(company, invoice) for invoice in keys})
        self.assertTrue(all(result["status"] == "SUCCESS" and result["evidence"]["source"] == "current_sqlite"
                            and result["data"]["invoice_date"].startswith("2026-09") for result in reads))
        notice = response["chat_notice"]
        for invoice in keys:
            self.assertIn(f"{invoice} 的用途", notice)

    def test_live_tool_order_uses_f007_only_for_the_edit(self):
        before = snapshot(self.path)
        agent = self.agent()
        agent.ask(LIVE_REQUEST)
        response = agent.last_response
        self.assertEqual([(name, result["status"]) for name, result in response["tool_results"]],
                         [("get_invoice", "SUCCESS"), ("get_invoice", "SUCCESS"),
                          ("propose_invoice_changes", "WAITING_CONFIRMATION")])
        self.assert_separated(response)
        proposal = response["invoice_change"]
        self.assertEqual((proposal["company_id"], proposal["year"], proposal["month"], proposal["invoice_nos"],
                          proposal["field"], proposal["new_value"]), ("C002", 2026, 9, ("F007",), "remark", VALUE))
        self.assertEqual(proposal["source_request"], LIVE_REQUEST)
        self.assertEqual(snapshot(self.path), before)

    def test_alternate_wording_and_reversed_clauses_keep_the_same_scope(self):
        before = snapshot(self.path)
        for request in (
            "先核对 C002 2026-09 的 F007、F006 的用途，随后仅将 F007 的备注修改为“培训待复核”，用途不要改。",
            "仅把 F007 的备注改为“培训待复核”，用途保持原样；然后查一下 C002 2026年9月 F007、F006 的用途。",
            "看看乙企业 2026年9月的 F006、F007 的用途；仅修改 F007 的备注为「培训待复核」，用途不动。",
        ):
            with self.subTest(request=request):
                agent = self.agent(mixed_model(keys=("F007", "F006")))
                agent.ask(request)
                self.assert_separated(agent.last_response)
                proposal = agent.last_response["invoice_change"]
                self.assertEqual((proposal["invoice_nos"], proposal["field"], proposal["new_value"]),
                                 (("F007",), "remark", VALUE))
        other = self.agent(mixed_model(company="C001", keys=("F003", "F002"), target="F003"))
        other.ask("查看甲企业 2026-09 的 F003、F002 的用途，然后把 F003 的备注改成「培训待复核」，用途不动。")
        self.assert_separated(other.last_response, "C001", ("F002", "F003"))
        self.assertEqual((other.last_response["invoice_change"]["company_id"],
                          other.last_response["invoice_change"]["invoice_nos"]), ("C001", ("F003",)))
        self.assertEqual(snapshot(self.path), before)

    def test_missing_target_asks_for_invoice_after_both_reads(self):
        before = snapshot(self.path)
        agent = self.agent(mixed_model(target="F006"))
        agent.ask(LIVE_REQUEST.replace("只把 F007", "只把其中一张"))
        response = agent.last_response
        self.assert_separated(response)
        self.assertEqual(response["category"], "clarification")
        self.assertIn("请明确要修改", response["chat_notice"])
        self.assertIn("发票编号", response["chat_notice"])
        self.assertNotIn("invoice_change", response)
        self.assertFalse(agent.update_session.drafts)
        self.assertEqual(snapshot(self.path), before)

    def test_wrong_target_wrong_field_or_incomplete_read_cannot_preview(self):
        before = snapshot(self.path)
        for model in (mixed_model(target="F006"), mixed_model(field="purpose"), mixed_model(keys=("F007",))):
            agent = self.agent(model)
            agent.ask(LIVE_REQUEST)
            self.assertNotIn("invoice_change", agent.last_response)
            self.assertFalse(agent.update_session.drafts)
        unauthorized = Agent("U002", self.path, mixed_model(), mode="mock")
        unauthorized.ask(LIVE_REQUEST)
        self.assertEqual(unauthorized.last_response["execution"]["stop_reason"], "DENIED")
        self.assertNotIn("invoice_change", unauthorized.last_response)
        self.assertEqual(snapshot(self.path), before)

    def test_redundant_exclusions_do_not_bypass_scope_or_write_conditions(self):
        before = snapshot(self.path)
        cases = (
            ("write target excluded", B_PARAPHRASE, b_paraphrase_model(("F005", "F010")), "SCOPE_MISMATCH"),
            ("unrequested read excluded", B_PARAPHRASE, b_paraphrase_model(("F005", "F003")), "SCOPE_MISMATCH"),
            ("unverified read excluded", B_PARAPHRASE, b_paraphrase_model(keys=("F010",)), "AMBIGUOUS"),
            ("added rule date", B_PARAPHRASE, b_paraphrase_model(rule_date="2026-09-01"), "SCOPE_MISMATCH"),
            ("conditional assignment", B_PARAPHRASE.replace("用途保持原样", "仅限金额超过 1000 元"),
             b_paraphrase_model(), "WAITING_USER"),
        )
        for case, request, model, status in cases:
            with self.subTest(case=case):
                agent = self.agent(model)
                agent.ask(request)
                response = agent.last_response
                self.assertEqual(response["execution"]["stop_reason"], status)
                self.assertNotIn("invoice_change", response)
                self.assertFalse(agent.update_session.drafts)
        self.assertEqual(snapshot(self.path), before)

    async def test_b_live_paraphrase_previews_only_f010_and_cancels_without_writes(self):
        before = snapshot(self.path)
        app = AgentWorkspace(self.path, DEFAULT_TEMPLATE, self.path.with_name("no-profiles.json"),
                             model=b_paraphrase_model(), trace_path=self.path.with_name("b-paraphrase.jsonl"),
                             session_path=self.path.with_name("sessions.sqlite3"))
        app.mode = "mock"
        async with app.run_test(size=(150, 44)) as pilot:
            app.screen.query_one("#login-user", Select).value = "U001"
            await pilot.click("#sign-in")
            await self.await_state(pilot, lambda: app.user == "U001")
            await test_tui_p0.P0Test.send(self, app, pilot, B_PARAPHRASE)
            await self.await_state(pilot, lambda: isinstance(app.screen, Approval) or not app.busy)
            response = app.agent.last_response
            self.assertEqual([(name, result["status"]) for name, result in response["tool_results"]],
                             [("get_invoice", "SUCCESS"), ("get_invoice", "SUCCESS"),
                              ("propose_invoice_changes", "WAITING_CONFIRMATION")])
            self.assertIsInstance(app.screen, Approval)
            self.assert_separated(response, "C001", ("F005", "F010"))
            dialog = app.screen
            self.assertIn("C001 · 2026-09", dialog.body)
            self.assertIn("字段　备注", dialog.body)
            self.assertIn(f"第 1 / 1 张\nF010\n原值　月底资料整理\n新值　{B_VALUE}", dialog.body)
            self.assertNotIn("F005", dialog.body.splitlines())
            self.assertEqual(snapshot(self.path), before)
            dialog.answer(False)
            await self.await_state(pilot, lambda: len(app.records) and not app.busy)
            self.assertEqual(app.agent.write_receipt["status"], "CANCELLED")
            self.assertFalse(app.agent.update_session.drafts)
        self.assertEqual(snapshot(self.path), before)

    async def test_workbench_preview_is_one_remark_and_cancel_leaves_every_row_intact(self):
        before = snapshot(self.path)
        app = AgentWorkspace(self.path, DEFAULT_TEMPLATE, self.path.with_name("no-profiles.json"),
                             model=mixed_model(), trace_path=self.path.with_name("workbench.jsonl"),
                             session_path=self.path.with_name("sessions.sqlite3"))
        app.mode = "mock"
        async with app.run_test(size=(150, 44)) as pilot:
            app.screen.query_one("#login-user", Select).value = "U001"
            await pilot.click("#sign-in")
            await self.await_state(pilot, lambda: app.user == "U001")
            await test_tui_p0.P0Test.send(self, app, pilot, LIVE_REQUEST)
            await self.await_state(pilot, lambda: isinstance(app.screen, Approval))
            dialog = app.screen
            self.assertIn("C002 · 2026-09", dialog.body)
            self.assertIn("字段　备注", dialog.body)
            self.assertIn("第 1 / 1 张\nF007\n原值　（未填写）\n新值　培训待复核", dialog.body)
            self.assertNotIn("第 1 / 2 张", dialog.body)
            self.assertEqual(snapshot(self.path), before)
            dialog.answer(False)
            await self.await_state(pilot, lambda: len(app.records) and not app.busy)
            def chat_text():
                return "\n".join(str(getattr(entry, "renderable", entry))
                                 for entry in app.workspace_widget("#chat-log", ChatLog).entries)

            self.assertIn("F006 的用途", chat_text())
            self.assertIn("F007 的用途", chat_text())
            records = len(app.records)
            app.agent.model = mixed_model(target="F006")
            await test_tui_p0.P0Test.send(self, app, pilot, LIVE_REQUEST.replace("只把 F007", "只把其中一张"))
            await self.await_state(pilot, lambda: isinstance(app.screen, Approval) or
                                   (len(app.records) > records and not app.busy))
            self.assertNotIsInstance(app.screen, Approval)
            self.assertIn("请明确要修改的发票编号", chat_text())
            self.assert_separated(app.agent.last_response)
        self.assertEqual(snapshot(self.path), before)
