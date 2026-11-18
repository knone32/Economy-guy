"""Causal regressions for model prose, pending requests and independent write scope."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.agent import Agent
from app.cli_workspaces import import_workspace
from tests.test_tui_p0 import FIXTURE
from tests.test_named_invoice_selection import tool_group
from tests.test_sql_invoice_selection import snapshot


def final(text, kind="information", **extra):
    return {"role": "assistant", "content": json.dumps({"kind": kind, "text": text, **extra}, ensure_ascii=False)}


class ModelReplyScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "sample.sqlite3"
        import_workspace(FIXTURE, self.path)
        self.before = snapshot(self.path)

    def agent(self, model, user="U001"):
        return Agent(user, self.path, model, mode="mock", trace_path=self.path.with_suffix(".jsonl"))

    def test_actual_model_query_body_survives_agent_output(self):
        replies = iter((tool_group("get_invoice", ({"company_id": "C002", "invoice_no": "F001"},)),
                        final("F001 的当前备注是部门采购，本轮仅查看。")))
        agent = self.agent(lambda *_: next(replies))
        answer = agent.ask("乙企业2026年9月，F001备注报一下，只查看。")
        self.assertEqual(agent.last_response.get("assistant_text"), "F001 的当前备注是部门采购，本轮仅查看。")
        self.assertIn(agent.last_response["assistant_text"], answer)
        self.assertIn(agent.last_response["assistant_text"], agent.last_response["chat_notice"])
        self.assertEqual(snapshot(self.path), self.before)

    def test_pending_invoice_choice_does_not_require_a_phrase_match(self):
        replies = iter((tool_group("get_invoice", ({"company_id": "C001", "invoice_no": n} for n in ("F017", "F018"))),
                        final("两张的用途已核对。要把备注写成凭证归集待核的是哪一张？", "clarification", missing_fields=["invoice_no"])))
        agent = self.agent(lambda *_: next(replies))
        request = "甲企业账期2026年8月；核对F017和F018的用涂；用途保留；备注给其中一张写「凭证归集待核」，哪张稍后定。"
        agent.ask(request)
        self.assertIsNotNone(agent.pending_intent)
        self.assertEqual(agent.pending_intent["request"], request)
        self.assertEqual(agent.pending_intent["missing_fields"], ("invoice_no",))
        self.assertEqual(agent.last_response.get("assistant_text"), "两张的用途已核对。要把备注写成凭证归集待核的是哪一张？")
        self.assertEqual(snapshot(self.path), self.before)

    def _mixed(self, *, wrong_month=False, wrong_key=False, user="U001", field="remark"):
        stage = iter(("read", "proposal"))
        def model(messages, _tools):
            if next(stage) == "read":
                return tool_group("get_invoice", ({"company_id": "C002", "invoice_no": n} for n in ("F015", "F012")))
            data = [json.loads(m["content"])["data"] for m in messages if m["role"] == "tool"]
            selected = next(d for d in data if d and d.get("invoice_no") == "F015")
            return tool_group("propose_invoice_changes", ({
                "selection_id": selected["selection_id"], "field": field,
                "new_value": "展会住宿凭证待归档", "mode": "item", "excluded_invoice_ids": [],
                "write_scope": {"company_id": "C002", "year": 2026, "month": 9 if wrong_month else 8,
                                "invoice_nos": ["F019" if wrong_key else "F015"]}},))
        agent = self.agent(model, user)
        agent.ask("账期2026年8月，对应乙企业。F015的备注请改成「展会住宿凭证待归档」。用涂不修改，保留原样。F015与F012各自的用途请报一下。")
        return agent

    def test_query_two_write_one_uses_independent_scope(self):
        agent = self._mixed()
        self.assertEqual(agent.last_response["invoice_change"]["invoice_nos"], ("F015",))
        self.assertEqual(agent.last_response["invoice_change"]["field"], "remark")
        self.assertEqual(snapshot(self.path), self.before)

    def test_independent_scope_cannot_change_month_or_invent_a_target(self):
        for options in ({"wrong_month": True}, {"wrong_key": True}, {"field": "purpose"}, {"user": "U002"}):
            with self.subTest(options=options):
                agent = self._mixed(**options)
                self.assertNotIn("invoice_change", agent.last_response)
                self.assertEqual(snapshot(self.path), self.before)

    def test_tools_do_not_require_an_intent_declaration(self):
        agent = self.agent(lambda *_: final("你好。", "general"))
        self.assertNotIn("declare_business_intent", agent.allowed_tools)
        agent.ask("你好")
        self.assertEqual(agent.last_response["execution"]["model_requests"], 1)

    def test_model_resumes_real_pending_source_with_a_fresh_selection(self):
        turns = iter(("read_two", "ask", "read_one", "proposal"))
        def model(messages, _tools):
            stage = next(turns)
            if stage in {"read_two", "read_one"}:
                return tool_group("get_invoice", ({"company_id": "C001", "invoice_no": n}
                                  for n in (("F017", "F018") if stage == "read_two" else ("F018",))))
            if stage == "ask":
                return final("请选定要处理备注的票号。", "clarification", missing_fields=["invoice_no"])
            pending = next(json.loads(m["content"])["pending_request"] for m in reversed(messages)
                           if m.get("name") == "context_data" and "pending_request" in json.loads(m["content"]))
            selected = next(json.loads(m["content"])["data"] for m in reversed(messages) if m["role"] == "tool")
            return tool_group("propose_invoice_changes", ({
                "selection_id": selected["selection_id"], "field": "remark", "new_value": "凭证归集待核",
                "mode": "item", "excluded_invoice_ids": ["F017"], "pending_request_id": pending["request_id"],
                "write_scope": {"company_id": "C001", "year": 2026, "month": 8, "invoice_nos": ["F018"]}},))
        agent = self.agent(model)
        agent.ask("甲企业2026年8月；核对F017和F018各自的用涂；用途保留，只给其中一张的备注写「凭证归集待核」，稍后选票。")
        pending_id = agent.pending_intent["request_id"]
        agent.ask("另一张F017的记录保留原样，要处理的发飘是F018。")
        self.assertEqual(agent.last_response["invoice_change"]["invoice_nos"], ("F018",))
        self.assertIn("凭证归集待核", agent.last_response["invoice_change"]["source_request"])
        self.assertIsNone(agent.pending_intent)
        self.assertNotEqual(agent.trace_id, pending_id)
        self.assertEqual(snapshot(self.path), self.before)

    def test_model_cancellation_clears_pending_without_writes(self):
        agent = self.agent(lambda *_: final("请补充票号。", "clarification", missing_fields=["invoice_no"]))
        agent.ask("甲企业2026年8月，备注改成「待核」，票号稍后给。")
        pending_id = agent.pending_intent["request_id"]
        agent.model = lambda *_: final("已终止这项待补要求。", pending={"request_id": pending_id, "action": "cancel"})
        agent.ask("前面那个先放弃吧。")
        self.assertIsNone(agent.pending_intent)
        self.assertEqual(agent.last_response["assistant_text"], "已终止这项待补要求。")
        self.assertEqual(snapshot(self.path), self.before)

    def test_pending_change_does_not_require_an_assignment_verb(self):
        replies = iter((tool_group("get_invoice", ({"company_id": "C001", "invoice_no": "F011"},)),
                        final("请确定要选哪张。", "clarification", missing_fields=["invoice_no"],
                              pending_change={"field": "remark", "new_value": "对账附件待归集"})))
        agent = self.agent(lambda *_: next(replies))
        agent.ask("甲企业2026年8月，看看F011。备注的预定内容是「对账附件待归集」，目标票尚未决定。")
        self.assertEqual(agent.pending_intent["change"], {"field": ["remark"], "new_value": ["对账附件待归集"]})
        self.assertEqual(snapshot(self.path), self.before)

    def test_pending_cannot_store_a_model_invented_new_value(self):
        agent = self.agent(lambda *_: final("请给票号。", "clarification", missing_fields=["invoice_no"],
                                           pending_change={"field": "remark", "new_value": "模型编造的新内容"}))
        agent.ask("甲企业2026年8月，备注预定内容是「对账附件待归集」，票号稍后给。")
        self.assertIsNone(agent.pending_intent)
        self.assertNotIn("invoice_change", agent.last_response)
        self.assertEqual(snapshot(self.path), self.before)


class ModelReplyWorkbenchTests(unittest.IsolatedAsyncioTestCase):
    setUp = ModelReplyScopeTests.setUp

    async def test_workbench_displays_the_model_body(self):
        from textual.widgets import Select
        from app.model_config import DEFAULT_TEMPLATE
        from app.tui import AgentWorkspace, ChatLog
        from tests import test_tui_p0
        replies = iter((tool_group("get_invoice", ({"company_id": "C002", "invoice_no": "F001"},)),
                        final("我查到 F001 当前备注为部门采购，这轮只查看。")))
        app = AgentWorkspace(self.path, DEFAULT_TEMPLATE, self.path.with_suffix(".profiles.json"),
                             model=lambda *_: next(replies), trace_path=self.path.with_suffix(".ui.jsonl"))
        app.mode = "mock"
        async with app.run_test(size=(150, 42)) as pilot:
            app.screen.query_one("#login-user", Select).value = "U001"
            await pilot.click("#sign-in")
            await test_tui_p0.P0Test.await_state(self, pilot, lambda: app.user == "U001")
            await test_tui_p0.P0Test.send(self, app, pilot, "乙企业2026年9月，F001备注报一下，只查看。")
            await test_tui_p0.P0Test.await_state(self, pilot, lambda: app.agent and app.agent.last_response and not app.busy)
            chat = "\n".join(str(entry) for entry in app.workspace_widget("#chat-log", ChatLog).entries)
            self.assertIn("我查到 F001 当前备注为部门采购，这轮只查看。", chat)
            self.assertEqual(snapshot(self.path), self.before)


if __name__ == "__main__":
    unittest.main()
