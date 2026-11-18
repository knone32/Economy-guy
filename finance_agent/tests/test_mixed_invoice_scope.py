"""Regression for mixed detail reads and a separate one-invoice change."""
import json
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from textual.widgets import Select

from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.model_config import DEFAULT_TEMPLATE
from app.stage2_schema import open_existing
from app.tui import AgentWorkspace, ChatLog
from app.tui_screens import Approval
from tests import test_tui_p0
from tests.test_named_invoice_selection import tool_group
from tests.test_sql_invoice_selection import snapshot


LIVE_REQUEST = "查一下乙企业 2026 年 9 月 F006 和 F007 的用途，再只把 F007 的备注改成「培训待复核」，用途别动。"
VALUE = "培训待复核"
B_PARAPHRASE = "麻烦先核对甲企业 2026-09 F005、F010 的用途，接着仅将 F010 的备注改为『期末打印单据待对照』，用途保持原样。"
B_VALUE = "期末打印单据待对照"
AMBIGUOUS_CHOICE = B_PARAPHRASE.replace("仅将 F010", "把其中一张")
MODEL_QUESTION = "请明确要修改的发票编号，你希望选哪张？"


def mixed_model(*, company="C002", keys=("F006", "F007"), target="F007", field="remark",
                value=VALUE, excluded=(), rule_date=None, year=2026, month=9):
    calls = iter(("read", "proposal"))

    def model(messages, _tools):
        if next(calls) == "read":
            return tool_group("get_invoice", ({"company_id": company, "invoice_no": invoice} for invoice in keys))
        evidence = [json.loads(msg["content"]).get("data") for msg in messages if msg["role"] == "tool"]
        selected = next(data for data in reversed(evidence) if data and data.get("invoice_no") == target)
        proposal = {
            "selection_id": selected["selection_id"], "field": field, "new_value": value, "mode": "item",
            "excluded_invoice_ids": list(excluded), "target_year": year, "target_month": month,
        }
        if rule_date is not None:
            proposal["rule_business_date"] = rule_date
        return tool_group("propose_invoice_changes", (proposal,))

    return model


def b_paraphrase_model(excluded=("F005",), keys=("F005", "F010"), **options):
    return mixed_model(company="C001", keys=keys, target="F010", value=B_VALUE, excluded=excluded, **options)


def question_model(company, numbers):
    stages = iter(("read", "question"))

    def model(_messages, _tools):
        if next(stages, "question") == "read":
            return tool_group("get_invoice", ({"company_id": company, "invoice_no": number} for number in numbers))
        return {"role": "assistant", "content": json.dumps({
            "kind": "clarification", "text": MODEL_QUESTION, "missing_fields": ["invoice_no"]},
            ensure_ascii=False)}

    return model


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

    def test_subject_first_edit_keeps_the_following_query_scope_separate(self):
        before = snapshot(self.path)
        cases = (
            ("乙企业2026年8月，F015的备注请写成「展会住宿凭证待归档」。"
             "F012和F015的用途也报一下，两张的用途都保持原样。",
             "C002", ("F012", "F015"), "F015", 8, "展会住宿凭证待归档"),
            ("甲企业2026年9月，F003的备注改为「资料待核」。"
             "F003、F004的用途也报一下，两张的用途都保持原样。",
             "C001", ("F003", "F004"), "F003", 9, "资料待核"),
        )
        for request, company, numbers, target, month, value in cases:
            with self.subTest(company=company, month=month, target=target):
                agent = self.agent(mixed_model(company=company, keys=numbers, target=target,
                                               month=month, value=value))
                agent.ask(request)
                response = agent.last_response
                reads = [r for name, r in response["tool_results"] if name == "get_invoice"]
                self.assertEqual({r["data"]["invoice_no"] for r in reads}, set(numbers))
                self.assertTrue(all(r["status"] == "SUCCESS" for r in reads))
                change = response["invoice_change"]
                self.assertEqual((change["company_id"], change["month"], change["invoice_nos"],
                                  change["field"], change["new_value"]),
                                 (company, month, (target,), "remark", value))
                self.assertEqual(change["source_request"], request)
                self.assertEqual(snapshot(self.path), before)

    def test_subject_first_edit_still_requires_the_right_target_field_and_all_reads(self):
        request = ("乙企业2026年8月，F015的备注请写成「展会住宿凭证待归档」。"
                   "F012和F015的用途也报一下，两张的用途都保持原样。")
        before = snapshot(self.path)
        cases = (
            ("wrong target", {}, {"target": "F012"}),
            ("wrong field", {}, {"field": "purpose"}),
            ("wrong value", {}, {"value": "模型自己添加的内容"}),
            ("incomplete reads", {}, {"keys": ("F015",)}),
            ("wrong period", {}, {"month": 9}),
            ("conflicting preserve", {"request": request.replace("用途都保持原样", "备注都保持原样")}, {}),
            ("conditional request", {"request": request + "仅限金额超过1000元时修改。"}, {}),
        )
        for label, change, model_options in cases:
            with self.subTest(label=label):
                options = dict(company="C002", keys=("F012", "F015"), target="F015",
                               value="展会住宿凭证待归档", month=8)
                options.update(model_options)
                agent = self.agent(mixed_model(**options))
                agent.ask(change.get("request", request))
                self.assertNotIn("invoice_change", agent.last_response)
                self.assertFalse(agent.update_session.drafts)
                self.assertEqual(snapshot(self.path), before)

    def test_quoted_choice_retains_scope_value_and_accepts_an_explicit_target_reply(self):
        before = snapshot(self.path)
        cases = (
            ("甲企业2026年8月的F017、F018，用途各是什么？"
             "复核标签「凭证归集待核」只加到这两笔中的一笔，写进备注栏。",
             "这次复核标记落在F018，F017保持原样。", "C001", ("F017", "F018"), 8,
             "F018", "remark", "凭证归集待核"),
            ("乙企业2026年9月的F001、F009，备注各是什么？"
             "新值「团队采购」只加到这两笔中的一笔，填入用途栏。",
             "本次修改目标选择F001，F009别动。", "C002", ("F001", "F009"), 9,
             "F001", "purpose", "团队采购"),
        )
        for request, reply, company, numbers, month, target, field, value in cases:
            with self.subTest(company=company, field=field):
                agent = self.agent(question_model(company, numbers))
                agent.ask(request)
                self.assertEqual(agent.last_response["category"], "clarification")
                self.assertNotIn("invoice_change", agent.last_response)
                self.assertIsNotNone(agent.pending_intent)
                self.assertIn(MODEL_QUESTION, agent.last_response["chat_notice"])
                self.assertEqual(agent.last_response["execution"]["model_requests"], 2)
                agent.model = mixed_model(company=company, keys=(target,), target=target, field=field,
                                          value=value, month=month)
                agent.ask(reply)
                change = agent.last_response["invoice_change"]
                self.assertEqual((change["company_id"], change["year"], change["month"],
                                  change["invoice_nos"], change["field"], change["new_value"]),
                                 (company, 2026, month, (target,), field, value))
                self.assertEqual(agent.last_response["execution"]["model_requests"], 2)
                self.assertIsNone(agent.pending_intent)
                (tool, outcome), = [(name, data) for name, data in agent.last_response["tool_results"]
                                   if name == "get_invoice"]
                self.assertEqual((tool, outcome["status"], outcome["data"]["invoice_no"]),
                                 ("get_invoice", "SUCCESS", target))
                self.assertEqual(snapshot(self.path), before)

    def test_quoted_choice_keeps_outside_selection_pending_and_cancels_without_changes(self):
        request = ("甲企业2026年8月的F017、F018，用途各是什么？"
                   "复核标签「凭证归集待核」只加到这两笔中的一笔，写进备注栏。")
        before = snapshot(self.path)
        agent = self.agent(question_model("C001", ("F017", "F018")))
        agent.ask(request)
        agent.ask("本次修改目标是F016。")
        self.assertEqual(agent.last_response["category"], "clarification")
        self.assertNotIn("invoice_change", agent.last_response)
        self.assertIsNotNone(agent.pending_intent)
        agent.ask("取消")
        self.assertEqual(agent.last_response["execution"]["stop_reason"], "CANCELLED")
        self.assertIsNone(agent.pending_intent)
        self.assertEqual(snapshot(self.path), before)

    def test_quoted_choice_does_not_drop_conditions_or_override_a_preserved_target(self):
        base = ("甲企业2026年8月的F017、F018，用途各是什么？"
                "复核标签「凭证归集待核」只加到这两笔中的一笔，写进备注栏。")
        before = snapshot(self.path)
        for request, reply in (
            (base + "仅限金额超过1000元时修改。", "F018"),
            (base.replace("复核标签", "用途内容"), "F018"),
            (base, "这次复核标记落在F018，F018保持原样。"),
            (base, "查询 F018 的销方"),
        ):
            with self.subTest(request=request, reply=reply):
                agent = self.agent(question_model("C001", ("F017", "F018")))
                agent.ask(request)
                agent.ask(reply)
                self.assertNotIn("invoice_change", agent.last_response)
                self.assertFalse(agent.update_session.drafts)
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
        agent = self.agent(question_model("C002", ("F006", "F007")))
        agent.ask(LIVE_REQUEST.replace("只把 F007", "只把其中一张"))
        response = agent.last_response
        self.assert_separated(response)
        self.assertEqual(response["category"], "clarification")
        self.assertIn(MODEL_QUESTION, response["chat_notice"])
        self.assertEqual(response["execution"]["model_requests"], 2)
        self.assertNotIn("invoice_change", response)
        self.assertFalse(agent.update_session.drafts)
        self.assertEqual(snapshot(self.path), before)

    def test_short_choice_resumes_the_saved_edit_and_rereads_only_that_invoice(self):
        before = snapshot(self.path)
        for reply in ("F010", "发票号是 F010。", "就 F010 那张吧", "就 C001 的 F010 那张吧"):
            with self.subTest(reply=reply):
                agent = self.agent(question_model("C001", ("F005", "F010")))
                agent.ask(AMBIGUOUS_CHOICE)
                self.assertEqual(agent.last_response["category"], "clarification")
                agent.model = mixed_model(company="C001", keys=("F010",), target="F010", value=B_VALUE)
                agent.ask(reply)
                change = agent.last_response["invoice_change"]
                self.assertEqual((change["company_id"], change["year"], change["month"]), ("C001", 2026, 9))
                self.assertEqual((change["invoice_nos"], change["field"], change["new_value"]),
                                 (("F010",), "remark", B_VALUE))
                (tool, result), = [(name, data) for name, data in agent.last_response["tool_results"]
                                  if name == "get_invoice"]
                self.assertEqual((tool, result["status"], result["data"]["invoice_no"]),
                                 ("get_invoice", "SUCCESS", "F010"))
                self.assertEqual(agent.last_response["execution"]["model_requests"], 2)
                self.assertIsNone(agent.pending_intent)
                self.assertEqual(snapshot(self.path), before)

    def test_choice_outside_the_read_set_keeps_the_question_and_can_be_cancelled(self):
        before = snapshot(self.path)
        agent = self.agent(question_model("C001", ("F005", "F010")))
        agent.ask(AMBIGUOUS_CHOICE)
        agent.ask("F008")
        self.assertIn("F005", agent.last_response["chat_notice"])
        self.assertIn("F010", agent.last_response["chat_notice"])
        self.assertFalse(agent.last_response["tool_results"])
        self.assertNotIn("invoice_change", agent.last_response)
        self.assertIsNotNone(agent.pending_intent)
        agent.ask("算了")
        self.assertIsNone(agent.pending_intent)
        self.assertEqual(agent.last_response["execution"]["stop_reason"], "CANCELLED")
        agent.model = lambda *_: {
            "role": "assistant", "content": json.dumps({"kind": "information", "text": "请说明要查询的内容"})}
        agent.ask("F010")
        self.assertNotIn("invoice_change", agent.last_response)
        self.assertEqual(snapshot(self.path), before)

    def test_selected_ticket_does_not_preview_without_a_valid_model_proposal(self):
        before = snapshot(self.path)

        def unavailable(*_args):
            raise RuntimeError("model unavailable")

        for label, model in (
            ("model unavailable", unavailable),
            ("information without proposal", lambda *_: {
                "role": "assistant", "content": json.dumps({"kind": "information", "text": "暂不提出修改"})}),
            ("wrong field", mixed_model(company="C001", keys=("F010",), target="F010",
                                        field="purpose", value=B_VALUE)),
            ("wrong target", mixed_model(company="C001", keys=("F005", "F010"), target="F005",
                                         value=B_VALUE)),
        ):
            with self.subTest(label=label):
                agent = self.agent(question_model("C001", ("F005", "F010")))
                agent.ask(AMBIGUOUS_CHOICE)
                agent.model = model
                agent.ask("就 F010 那张吧")
                self.assertGreater(agent.last_response["execution"]["model_requests"], 0)
                self.assertNotIn("invoice_change", agent.last_response)
                self.assertFalse(agent.update_session.drafts)
                self.assertEqual(snapshot(self.path), before)

    def test_a_guessed_model_target_does_not_create_a_harness_question(self):
        before = snapshot(self.path)
        agent = self.agent(b_paraphrase_model())
        agent.ask(AMBIGUOUS_CHOICE)
        self.assertNotIn("invoice_change", agent.last_response)
        self.assertIsNone(agent.pending_intent)
        self.assertEqual(agent.last_response["execution"]["model_requests"], 2)
        self.assertEqual(snapshot(self.path), before)

    def test_model_can_reread_candidates_but_only_propose_the_selected_invoice(self):
        before = snapshot(self.path)
        agent = self.agent(question_model("C001", ("F005", "F010")))
        agent.ask(AMBIGUOUS_CHOICE)
        agent.model = b_paraphrase_model()
        agent.ask("就 F010 那张吧")
        change = agent.last_response["invoice_change"]
        self.assertEqual((change["company_id"], change["invoice_nos"], change["field"], change["new_value"]),
                         ("C001", ("F010",), "remark", B_VALUE))
        reads = [outcome for name, outcome in agent.last_response["tool_results"] if name == "get_invoice"]
        self.assertEqual({outcome["data"]["invoice_no"] for outcome in reads}, {"F005", "F010"})
        self.assertEqual(agent.last_response["execution"]["model_requests"], 2)
        self.assertEqual(snapshot(self.path), before)

    def test_a_new_query_does_not_resume_pending_invoice_edit(self):
        agent = self.agent(question_model("C001", ("F005", "F010")))
        agent.ask(AMBIGUOUS_CHOICE)
        self.assertIsNotNone(agent.pending_intent)
        agent.model = lambda *_: {
            "role": "assistant", "content": json.dumps({"kind": "information", "text": "查销方"})}
        agent.ask("C001 的 F010 的销方是谁？")
        self.assertNotIn("invoice_change", agent.last_response)
        self.assertIsNone(agent.pending_intent)

    def test_choice_checks_current_permission_and_period(self):
        read_only_agent = Agent("U002", self.path, question_model("C001", ("F005", "F010")), mode="mock")
        read_only_agent.ask(AMBIGUOUS_CHOICE)
        read_only_agent.model = mixed_model(company="C001", keys=("F010",), target="F010", value=B_VALUE)
        read_only_agent.ask("F010")
        self.assertEqual(read_only_agent.last_response["execution"]["stop_reason"], "DENIED")
        self.assertNotIn("invoice_change", read_only_agent.last_response)

        agent = self.agent(question_model("C001", ("F005", "F010")))
        agent.ask(AMBIGUOUS_CHOICE)
        agent.model = mixed_model(company="C001", keys=("F010",), target="F010", value=B_VALUE)
        with closing(open_existing(self.path)) as db:
            db.execute("UPDATE invoices SET invoice_date=? WHERE company_id=? AND invoice_no=?",
                       ("2026-10-01", "C001", "F010"))
            db.commit()
        before = snapshot(self.path)
        agent.ask("F010")
        self.assertEqual(agent.last_response["execution"]["stop_reason"], "SCOPE_MISMATCH")
        self.assertNotIn("invoice_change", agent.last_response)
        self.assertEqual(snapshot(self.path), before)

    async def test_workbench_choice_uses_fresh_value_then_cancels_without_changes(self):
        app = AgentWorkspace(self.path, DEFAULT_TEMPLATE, self.path.with_name("no-profiles.json"),
                             model=question_model("C001", ("F005", "F010")), trace_path=self.path.with_name("choice.jsonl"),
                             session_path=self.path.with_name("sessions.sqlite3"))
        app.mode = "mock"
        async with app.run_test(size=(150, 44)) as pilot:
            app.screen.query_one("#login-user", Select).value = "U001"
            await pilot.click("#sign-in")
            await self.await_state(pilot, lambda: app.user == "U001")
            await test_tui_p0.P0Test.send(self, app, pilot, AMBIGUOUS_CHOICE)
            await self.await_state(pilot, lambda: bool(app.records) and not app.busy)
            self.assertNotIsInstance(app.screen, Approval)
            with closing(open_existing(self.path)) as db:
                db.execute("UPDATE invoices SET remark=? WHERE company_id=? AND invoice_no=?",
                           ("已收到新附件", "C001", "F010"))
                db.commit()
            before = snapshot(self.path)
            records = len(app.records)
            app.agent.model = mixed_model(company="C001", keys=("F010",), target="F010", value=B_VALUE)
            await test_tui_p0.P0Test.send(self, app, pilot, "发票号是 F010")
            await self.await_state(pilot, lambda: isinstance(app.screen, Approval) or
                                   (len(app.records) > records and not app.busy))
            dialog = app.screen
            self.assertIsInstance(dialog, Approval)
            self.assertIn("C001 · 2026-09", dialog.body)
            self.assertIn("字段　备注", dialog.body)
            self.assertIn(f"第 1 / 1 张\nF010\n原值　已收到新附件\n新值　{B_VALUE}", dialog.body)
            self.assertEqual(snapshot(self.path), before)
            dialog.answer(False)
            await self.await_state(pilot, lambda: len(app.records) > records and not app.busy)
            self.assertEqual(app.agent.write_receipt["status"], "CANCELLED")
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
             b_paraphrase_model(), "AMBIGUOUS"),
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
            app.agent.model = question_model("C002", ("F006", "F007"))
            await test_tui_p0.P0Test.send(self, app, pilot, LIVE_REQUEST.replace("只把 F007", "只把其中一张"))
            await self.await_state(pilot, lambda: isinstance(app.screen, Approval) or
                                   (len(app.records) > records and not app.busy))
            self.assertNotIsInstance(app.screen, Approval)
            self.assertIn("请明确要修改的发票编号", chat_text())
            self.assert_separated(app.agent.last_response)
        self.assertEqual(snapshot(self.path), before)
