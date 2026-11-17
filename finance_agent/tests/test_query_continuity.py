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
from app.references import reference_catalog
from app.tui import AgentWorkspace, ChatLog
from tests import test_tui_p0


FIRST = {"company_id": "C001", "invoice_no": "F002"}
SECOND = {"company_id": "C001", "invoice_no": "F003"}
REQUEST = "查 C001 的 F002，然后再查 C001 的另一张发票。"
PURPOSE = "先查 C001 的 F002 的用途，然后再查 C001 的另一张发票。"
SAME_COMPANY = "先查 C001 的 F002，再查同一家公司的另一张发票。"
NO_COMPANY = "先查 F002 的用途，再查同一家公司的另一张"
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
            self.assertEqual(app.agent.pending_intent["invoice_followup"], "F002")

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

    async def test_workbench_followup_accepts_prefix_and_company_alias(self):
        variants = ("先" + REQUEST, REQUEST.replace("C001", "甲企业"))
        app = self.app(tool("get_invoice", FIRST), CLARIFY)
        async with app.run_test(size=(150, 42)) as pilot:
            await self.login(app, pilot)
            for request in variants:
                with self.subTest(request=request):
                    if app.agent is not None:
                        app.agent.model = scripted_model([tool("get_invoice", FIRST), CLARIFY])
                    first = await self.ask(app, pilot, request)
                    self.assertEqual(first["execution"]["stop_reason"], "WAITING_USER")
                    self.assertIn("F002", first["chat_notice"])
                    self.assertIn("第二张", first["chat_notice"])
                    self.assertIn("F002", str(app.workspace_widget("#business-log", ChatLog).entries[-1].renderable))
                    self.assertEqual(app.agent.pending_intent["scope"], {"company_id": ["C001"]})
                    self.assertEqual(app.agent.pending_intent["request"], request)
                    blocked = Mock(side_effect=AssertionError("续查范围由待补状态提供"))
                    app.agent.model = blocked
                    followup = await self.ask(app, pilot, "F003")
                    blocked.assert_not_called()
                    self.assertEqual(followup["invoice_followup_read"]["arguments"], SECOND)
                    self.assertEqual(followup["invoice_followup_read"]["status"], "SUCCESS")
                    self.assertIsNone(app.agent.pending_intent)
        events = [json.loads(line) for line in (self.directory / "workbench.jsonl").read_text(
            encoding="utf-8").splitlines()]
        proves = [event["data"] for event in events if event["event"] == "invoice.followup_read"]
        self.assertEqual([event["original_request"] for event in proves], list(variants))
        for event in proves:
            self.assertEqual(event["arguments"], SECOND)
            self.assertEqual(event["provenance"]["sources"], {"company_id": "session_confirmed", "invoice_no": "user_current"})
        self.assert_zero_audit()

    async def test_workbench_keeps_followup_for_purpose_and_same_company(self):
        app = self.app(tool("get_invoice", FIRST), CLARIFY)
        async with app.run_test(size=(150, 42)) as pilot:
            await self.login(app, pilot)
            for request in (PURPOSE, SAME_COMPANY, NO_COMPANY):
                with self.subTest(request=request):
                    app.read_workspace = ("C001", 2026, 9)
                    if app.agent:
                        app.agent.model = scripted_model([tool("get_invoice", FIRST), CLARIFY])
                    first = await self.ask(app, pilot, request)
                    self.assertEqual(first["execution"]["stop_reason"], "WAITING_USER")
                    self.assertIn("F002", first["chat_notice"])
                    self.assertIn("第二张", first["chat_notice"])
                    self.assertIn("F002", str(app.workspace_widget("#business-log", ChatLog).entries[-1].renderable))
                    self.assertEqual(app.agent.pending_intent["scope"], {"company_id": ["C001"]})
                    app.read_workspace = ("C002", 2026, 9)
                    app.agent.model = Mock(side_effect=AssertionError("待补企业已可信确认"))
                    second = await self.ask(app, pilot, "F003")
                    app.agent.model.assert_not_called()
                    self.assertEqual(second["invoice_followup_read"]["arguments"], SECOND)
                    self.assertEqual(second["invoice_followup_read"]["status"], "SUCCESS")
                    self.assertIsNone(app.agent.pending_intent)
        trace = [json.loads(line) for line in (self.directory / "workbench.jsonl").read_text(
            encoding="utf-8").splitlines()]
        proofs = [item["data"] for item in trace if item["event"] == "invoice.followup_read"]
        self.assertEqual([item["original_request"] for item in proofs], [PURPOSE, SAME_COMPANY, NO_COMPANY])
        for entry in proofs:
            self.assertEqual(entry["provenance"]["sources"], {"company_id": "session_confirmed", "invoice_no": "user_current"})
        self.assert_zero_audit()

    def test_missing_company_can_be_supplied_without_losing_either_read(self):
        model = Mock(side_effect=AssertionError("没有可信企业时须追问"))
        agent = Agent("U001", self.path, model, mode="mock")
        self.assertIn("企业", agent.ask(NO_COMPANY))
        self.assertEqual(agent.pending_intent["missing_fields"], ("company_id",))
        self.assertFalse(agent.last_response["tool_results"])
        first = agent.ask("甲企业")
        self.assertIn("F002", first)
        self.assertIn("第二张", first)
        self.assertEqual(agent.pending_intent["scope"], {"company_id": ["C001"]})
        agent.ask("F003")
        self.assertEqual(agent.last_response["invoice_followup_read"]["arguments"], SECOND)
        self.assertEqual(agent.last_response["invoice_followup_read"]["status"], "SUCCESS")
        self.assertIsNone(agent.pending_intent)
        model.assert_not_called()
        self.assert_zero_audit()

    def test_local_correction_replaces_only_that_read_and_failed_second_remains_pending(self):
        agent = Agent("U001", self.path, scripted_model([tool("get_invoice", FIRST), CLARIFY]), mode="mock")
        agent.ask(REQUEST)
        agent.model = Mock(side_effect=AssertionError("已知局部更正应使用可信读取"))
        self.assertIn("未找到 F999", agent.ask("第一张改查 F999"))
        self.assertEqual(agent.pending_intent["missing_fields"], ("first_invoice_no",))
        self.assertEqual(agent.last_response["execution"]["stop_reason"], "WAITING_USER")
        first = agent.ask("F004")
        self.assertIn("F004", first)
        self.assertIn("第二张", first)
        self.assertEqual(agent.invoice_query_chain.first.key, {"company_id": "C001", "invoice_no": "F004"})
        self.assertEqual(agent.pending_intent["request"], REQUEST)
        self.assertEqual(agent.pending_intent["scope"], {"company_id": ["C001"]})

        agent.ask("第二张改查 F999")
        self.assertEqual(agent.last_response["invoice_followup_read"]["arguments"],
                         {"company_id": "C001", "invoice_no": "F999"})
        self.assertEqual(agent.last_response["invoice_followup_read"]["status"], "NO_DATA")
        self.assertEqual(agent.last_response["execution"]["stop_reason"], "WAITING_USER")
        self.assertIn("未找到 F999", agent.last_response["chat_notice"])
        self.assertEqual(agent.invoice_query_chain.first.key, {"company_id": "C001", "invoice_no": "F004"})
        agent.ask("第二张改查 F003")
        self.assertEqual(agent.last_response["invoice_followup_read"]["arguments"], SECOND)
        self.assertEqual(agent.last_response["invoice_followup_read"]["status"], "SUCCESS")
        self.assertIsNone(agent.pending_intent)
        agent.model.assert_not_called()
        self.assert_zero_audit()

    def test_alias_queries_keep_the_second_read_in_the_same_company(self):
        scenarios = (
            ("乙企业的 F005 先帮我看一下用途，同一个企业我还有一张票也要查。", "C002", "F005", "F008"),
            ("想先核实甲企业 F004 的用途，另外一张也在甲企业，号码我下一条发。", "C001", "F004", "F006"),
        )
        for request, company, first, second in scenarios:
            with self.subTest(request=request):
                target = {"company_id": company, "invoice_no": first}
                agent = Agent("U001", self.path, scripted_model([tool("get_invoice", target), CLARIFY]), mode="mock")
                self.assertIn("第二张", agent.ask(request))
                self.assertEqual(agent.pending_intent["scope"], {"company_id": [company]})
                agent.model = Mock(side_effect=AssertionError("待补查询直接鉴权"))
                agent.ask(second)
                self.assertEqual(agent.last_response["invoice_followup_read"]["arguments"],
                                 {"company_id": company, "invoice_no": second})
                self.assertIsNone(agent.pending_intent)
                agent.model.assert_not_called()
        agent = Agent("U001", self.path, scripted_model([tool("get_invoice", FIRST), FINAL]), mode="mock")
        agent.ask("先查 C001 的 F002，另一张不用查了。")
        self.assertIsNone(agent.pending_intent)
        self.assertIsNone(agent.invoice_query_chain)
        self.assert_zero_audit()

    def test_joint_key_repairs_failed_first_and_retires_its_old_reference(self):
        agent = Agent("U001", self.path, scripted_model([tool("get_invoice", FIRST), CLARIFY]), mode="mock")
        agent.ask(REQUEST)
        old_anchor, = reference_catalog(self.path, "U001")
        agent.model = Mock(side_effect=AssertionError("不交给模型选择对象"))
        self.assertIn("未找到 F999", agent.ask("第一张改查 C002/F999"))
        self.assertIsNone(agent.context.recent_invoice_query)
        self.assertEqual(reference_catalog(self.path, "U001"), [])
        self.assertIn("编号", agent.ask(f"查看第 1 张发票 anchor:{old_anchor['anchor_id']}"))
        self.assertIn("编号", agent.ask("查看刚才那张发票"))
        self.assertEqual(agent.pending_intent["missing_fields"], ("first_invoice_no",))
        self.assertIn("第二张", agent.ask("C001 的 F004"))
        self.assertEqual(agent.last_response["invoice_followup_read"]["arguments"],
                         {"company_id": "C001", "invoice_no": "F004"})
        agent.ask("C001/F003")
        self.assertEqual(agent.last_response["invoice_followup_read"]["arguments"], SECOND)
        self.assertIsNone(agent.pending_intent)
        agent.model.assert_not_called()
        self.assert_zero_audit()

    def test_second_nonliteral_correction_works_when_pending_and_completed(self):
        for previous_number in ("F003", "F999"):
            with self.subTest(previous_number=previous_number):
                agent = Agent("U001", self.path, scripted_model([tool("get_invoice", FIRST), CLARIFY]), mode="mock")
                agent.ask(REQUEST)
                agent.model = Mock(side_effect=AssertionError("只重查被更正的一项"))
                agent.ask(previous_number)
                answer = agent.ask("第二张我刚才报错了，换成 F009，第一张照旧。")
                self.assertIn("F009", answer)
                self.assertIn("第一张", answer)
                self.assertEqual(len(agent.last_response["tool_results"]), 1)
                self.assertEqual(agent.last_response["invoice_followup_read"]["arguments"],
                                 {"company_id": "C001", "invoice_no": "F009"})
                self.assertIsNone(agent.pending_intent)
                self.assertIn("第一张", agent.ask("第一张改查 F999"))
                self.assertIn("F004", agent.ask("F004"))
                self.assertIsNone(agent.pending_intent)
                agent.model.assert_not_called()
        self.assert_zero_audit()

    def test_natural_query_cancellation_can_target_one_item_or_whole_round(self):
        agent = Agent("U001", self.path, scripted_model([tool("get_invoice", FIRST), CLARIFY]), mode="mock")
        agent.ask(REQUEST)
        agent.model = Mock(side_effect=AssertionError("自然语言取消不调用模型"))
        self.assertIn("第二张", agent.ask("只取消第一张，第二张照旧。"))
        self.assertIsNone(agent.context.recent_invoice_query)
        self.assertEqual(agent.pending_intent["missing_fields"], ("invoice_no",))
        agent.ask("F003")
        self.assertEqual(agent.context.recent_invoice_query, SECOND)
        self.assertIn("取消", agent.ask("这轮先撤掉，第二张不用查了。"))
        self.assertIsNone(agent.pending_intent)
        self.assertIsNone(agent.context.recent_invoice_query)
        self.assertIn("编号", agent.ask("前头那张的用途还能帮我看下吗？"))
        agent.model.assert_not_called()
        self.assert_zero_audit()

    def test_cancel_only_second_retires_its_anchor_and_retains_first(self):
        agent = Agent("U001", self.path, scripted_model([tool("get_invoice", FIRST), CLARIFY]), mode="mock")
        agent.ask(REQUEST)
        first_anchor, = reference_catalog(self.path, "U001")
        agent.model = Mock(side_effect=AssertionError("单项取消与已展示引用均无需选择模型对象"))
        agent.ask("甲企业编号 F003")
        second_anchor, = reference_catalog(self.path, "U001")
        self.assertNotEqual(second_anchor["anchor_id"], first_anchor["anchor_id"])
        self.assertIn("保留第一张", agent.ask("取消第二张"))
        self.assertEqual(reference_catalog(self.path, "U001"), [first_anchor])
        self.assertIsNone(agent.pending_intent)
        self.assertNotIn("F003", agent.ask(f"查看第 1 张发票 anchor:{second_anchor['anchor_id']}"))
        agent.model.assert_not_called()
        self.assert_zero_audit()

    async def test_live_information_reply_keeps_same_company_question(self):
        first = {"company_id": "C002", "invoice_no": "F005"}
        second = {"company_id": "C002", "invoice_no": "F008"}
        information = {"role": "assistant", "content": json.dumps({
            "kind": "information", "text": "乙企业 F005 的用途为空。您提到的那一张，请把票号发给我后再查。",
        }, ensure_ascii=False)}
        app = self.app(tool("get_invoice", first), information)
        async with app.run_test(size=(150, 42)) as pilot:
            await self.login(app, pilot)
            response = await self.ask(app, pilot, "能帮我看一眼乙企业 F005 的用途吗？同一家还有一张，票号我等下补")
            self.assertEqual(response["execution"]["stop_reason"], "WAITING_USER")
            self.assertIn("F005", response["chat_notice"])
            self.assertIn("第二张", response["chat_notice"])
            self.assertEqual(app.agent.pending_intent["scope"], {"company_id": ["C002"]})
            app.agent.model = Mock(side_effect=AssertionError("补号直接使用待补企业"))
            response = await self.ask(app, pilot, "F008")
            self.assertEqual(response["invoice_followup_read"]["arguments"], second)
            self.assertEqual(response["invoice_followup_read"]["status"], "SUCCESS")
            self.assertIn("F008", str(app.workspace_widget("#business-log", ChatLog).entries[-1].renderable))
            app.agent.model.assert_not_called()
        self.assert_zero_audit()

    def test_live_correction_updates_second_item_before_reference_resolution(self):
        agent = Agent("U001", self.path, scripted_model([tool("get_invoice", FIRST), CLARIFY]), mode="mock")
        agent.ask(REQUEST)
        first_anchor, = reference_catalog(self.path, "U001")
        agent.model = Mock(side_effect=AssertionError("只通过原查询状态更正"))
        agent.ask("F003")
        old_anchor, = reference_catalog(self.path, "U001")
        answer = agent.ask("把第二张换成 F009 看看，前一张保持原样。")
        self.assertIn("保留第一张", answer)
        self.assertEqual(agent.last_response["invoice_followup_read"]["arguments"],
                         {"company_id": "C001", "invoice_no": "F009"})
        self.assertEqual(agent.last_response["execution"]["actual_tool_calls"], 1)
        self.assertEqual(agent.invoice_query_chain.first.key, FIRST)
        self.assertIsNone(agent.pending_intent)
        self.assertNotIn("F003", agent.ask(f"查看第 1 张发票 anchor:{old_anchor['anchor_id']}"))
        agent.model.assert_not_called()
        agent.model = scripted_model([FINAL])
        self.assertIn("F002", agent.ask(f"查看第 1 张发票 anchor:{first_anchor['anchor_id']}"))
        self.assert_zero_audit()

    async def test_live_cancel_both_retires_pending_and_old_references(self):
        app = self.app(tool("get_invoice", FIRST), CLARIFY)
        async with app.run_test(size=(150, 42)) as pilot:
            await self.login(app, pilot)
            await self.ask(app, pilot, REQUEST.rstrip("。"))
            app.agent.model = Mock(side_effect=AssertionError("取消不由模型解释"))
            cancelled = await self.ask(app, pilot, "两张的查询先取消，第二张的编号不用等了。")
            self.assertEqual(cancelled["execution"]["stop_reason"], "CANCELLED")
            self.assertIsNone(app.agent.pending_intent)
            self.assertIsNone(app.agent.context.recent_invoice_query)
            self.assertEqual(reference_catalog(self.path, "U001"), [])
            app.agent.model.assert_not_called()
            app.agent.model = scripted_model([tool("get_invoice", SECOND), CLARIFY])
            bare = await self.ask(app, pilot, "F003")
            self.assertEqual(bare["tool_results"][0][1]["status"], "AMBIGUOUS")
            app.agent.model = Mock(side_effect=AssertionError("旧指代不再解析"))
            relative = await self.ask(app, pilot, "刚才那张的用途呢？")
            self.assertEqual(relative["category"], "reference_error")
            self.assertFalse(relative["tool_results"])
            app.agent.model.assert_not_called()
            app.agent.model = scripted_model([tool("get_invoice", FIRST), FINAL])
            explicit = await self.ask(app, pilot, "请直接查甲企业编号 F002 的用途。")
            self.assertEqual(explicit["tool_results"][0][1]["data"]["invoice_no"], "F002")
        self.assert_zero_audit()

    def test_ambiguous_control_preserves_chain_and_single_cancel_keeps_first(self):
        request = "请查看甲企业 F002 的备注? 同公司第二张的号码我晚些补。"
        agent = Agent("U001", self.path, scripted_model([tool("get_invoice", FIRST), FINAL]), mode="mock")
        self.assertIn("第二张", agent.ask(request))
        anchor, = reference_catalog(self.path, "U001")
        agent.model = Mock(side_effect=AssertionError("续查指令不交给通用列表或模型"))
        self.assertIn("请明确", agent.ask("把第二张换成 F009 或 F010，前一张保持原样。"))
        self.assertFalse(agent.last_response["tool_results"])
        self.assertEqual(agent.pending_intent["scope"], {"company_id": ["C001"]})
        self.assertEqual(reference_catalog(self.path, "U001"), [anchor])
        self.assertIn("请明确", agent.ask("取消两张，首张保持原样"))
        self.assertEqual(agent.pending_intent["scope"], {"company_id": ["C001"]})
        self.assertIn("未找到 F999", agent.ask("请把第 2 张改查 F999，首张不变"))
        self.assertEqual(agent.last_response["invoice_followup_read"]["status"], "NO_DATA")
        self.assertIn("保留第一张", agent.ask("请取消另一张，首张继续查"))
        self.assertIsNone(agent.pending_intent)
        self.assertEqual(reference_catalog(self.path, "U001"), [anchor])
        agent.model.assert_not_called()
        self.assert_zero_audit()

    def test_additional_invoice_with_verb_before_quantity_preserves_verified_company(self):
        prompts = (
            ("劳驾看看甲企业 F004 的备注。同一家还要看一张，编号我再发。", CLARIFY),
            ("看看甲企业 F004 的备注。同一家还有一张要看，编号我再发。", FINAL),
            ("劳驾，看看甲企业 F004 的备注；同家公司再帮我查一张，票号稍后给你。", FINAL),
            ("先核实甲企业 F004 的备注再看看一张同公司的，编号稍后给你。", CLARIFY),
        )
        first = {"company_id": "C001", "invoice_no": "F004"}
        second = {"company_id": "C001", "invoice_no": "F006"}
        for prompt, reply in prompts:
            with self.subTest(prompt=prompt):
                model = scripted_model([tool("get_invoice", first), reply])
                agent = Agent("U001", self.path, model, mode="mock")
                answer = agent.ask(prompt)
                self.assertIn("F004", answer)
                self.assertEqual(agent.last_response["execution"]["stop_reason"], "WAITING_USER")
                self.assertIn("第二张发票的编号", agent.last_response["chat_notice"])
                self.assertIsNotNone(agent.pending_intent)
                self.assertEqual(agent.pending_intent["scope"], {"company_id": ["C001"]})
                self.assertEqual(agent.invoice_query_chain.first.key, first)
                name, result = agent.last_response["tool_results"][0]
                self.assertEqual((name, result["status"], result["evidence"]["source"]),
                                 ("get_invoice", "SUCCESS", "current_sqlite"))
                agent.model = Mock(side_effect=AssertionError("待补企业从首张证据取得"))
                agent.ask("F006", read_workspace=("C002", 2026, 9))
                self.assertEqual(agent.last_response["invoice_followup_read"]["arguments"], second)
                self.assertEqual(agent.last_response["invoice_followup_read"]["status"], "SUCCESS")
                self.assertIsNone(agent.pending_intent)
                agent.model.assert_not_called()
        self.assert_zero_audit()

    def test_additional_invoice_does_not_bind_unverified_or_unrequested_company(self):
        first = {"company_id": "C001", "invoice_no": "F004"}
        prompt = "看看甲企业 F004 的备注。同一家还要看一张，编号我再发。"
        cases = (
            ("U001", prompt, {"company_id": "C002", "invoice_no": "F004"}, "SCOPE_MISMATCH"),
            ("U002", prompt.replace("甲企业", "乙企业"), {"company_id": "C002", "invoice_no": "F004"}, "DENIED"),
            ("U001", prompt.replace("F004", "F999"), {"company_id": "C001", "invoice_no": "F999"}, "NO_DATA"),
            ("U001", "看看甲企业 F004 的备注。", first, "SUCCESS"),
            ("U001", prompt.replace("同一家", "另一家乙企业"), first, "SUCCESS"),
        )
        for user, request, target, status in cases:
            with self.subTest(request=request, status=status):
                agent = Agent(user, self.path, scripted_model([tool("get_invoice", target), CLARIFY]), mode="mock")
                agent.ask(request)
                self.assertEqual(agent.last_response["tool_results"][0][1]["status"], status)
                self.assertIsNone(agent.invoice_query_chain)
        self.assert_zero_audit()

    def test_first_read_alone_does_not_discard_clarification_for_second(self):
        for targets, expected in (([FIRST], "WAITING_USER"), ([FIRST, SECOND], "ANSWERED")):
            with self.subTest(targets=targets):
                calls = [tool("get_invoice", target, f"invoice-{i}") for i, target in enumerate(targets)]
                agent = Agent("U001", self.path, scripted_model([*calls, CLARIFY]), mode="mock")
                agent.ask("查 C001 的 F002 和 F003")
                response = agent.last_response
                self.assertEqual([outcome["data"]["invoice_no"] for _, outcome in response["tool_results"]],
                                 [target["invoice_no"] for target in targets])
                self.assertEqual(response["execution"]["stop_reason"], expected)
                self.assertEqual("发票编号" in (response["chat_notice"] or ""), len(targets) == 1)
        self.assert_zero_audit()

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

    async def test_cancel_while_waiting_clears_bare_number_and_relative_reference(self):
        app = self.app(tool("get_invoice", FIRST), CLARIFY)
        async with app.run_test(size=(150, 42)) as pilot:
            await self.login(app, pilot)
            for control, request in (("f4", SAME_COMPANY), ("/cancel", NO_COMPANY)):
                app.read_workspace = ("C001", 2026, 9)
                with self.subTest(control=control):
                    if app.agent:
                        app.agent.model = scripted_model([tool("get_invoice", FIRST), CLARIFY])
                    waiting = await self.ask(app, pilot, request)
                    self.assertEqual(waiting["execution"]["stop_reason"], "WAITING_USER")
                    self.assertIsNotNone(app.agent.pending_intent)
                    if control == "f4":
                        await pilot.press("f4")
                    else:
                        await test_tui_p0.P0Test.send(self, app, pilot, control)
                    self.assertIsNone(app.agent.pending_intent)

                    app.agent.model = scripted_model([tool("get_invoice", SECOND), FINAL])
                    bare = await self.ask(app, pilot, "F003")
                    self.assertNotIn("invoice_followup_read", bare)
                    self.assertEqual(bare["tool_results"][0][1]["status"], "AMBIGUOUS")
                    self.assertIn("company_id", bare["tool_results"][0][1]["evidence"]["missing_fields"])
                    app.agent.model = Mock(return_value=tool("resolve_recent_invoice", {"source": "queried"}))
                    relative = await self.ask(app, pilot, "刚才那张发票")
                    self.assertEqual(relative["category"], "reference_error")
                    self.assertIn("发票编号", relative["chat_notice"])
                    self.assertFalse(relative["tool_results"])
                    app.agent.model.assert_not_called()

                    app.agent.model = scripted_model([tool("get_invoice", FIRST), FINAL])
                    explicit = await self.ask(app, pilot, "C001/F002")
                    self.assertEqual(explicit["tool_results"][0][1]["data"]["invoice_no"], "F002")
            self.assert_zero_audit()

    def test_cli_cancel_retires_relative_invoice_and_allows_explicit_key(self):
        agent = Agent("U001", self.path, scripted_model([tool("get_invoice", FIRST), CLARIFY]), mode="mock",
                      trace_path=self.directory / "cli.jsonl")
        output = io.StringIO()

        def keyboard():
            yield REQUEST
            self.assertEqual(agent.last_response["tool_results"][0][1]["status"], "SUCCESS")
            self.assertEqual(agent.last_response["execution"]["stop_reason"], "WAITING_USER")
            self.assertIsNotNone(agent.pending_intent)
            yield "/cancel"
            self.assertIsNone(agent.pending_intent)
            agent.model = scripted_model([tool("get_invoice", SECOND), FINAL])
            yield "F003"
            self.assertEqual(agent.last_response["tool_results"][0][1]["status"], "AMBIGUOUS")
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
