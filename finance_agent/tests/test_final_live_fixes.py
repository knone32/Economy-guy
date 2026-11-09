import unittest
from contextlib import closing

from app.agent import Agent, scripted_model
from app.stage2_schema import open_existing
from app.tasks import list_tasks
from tests import test_p05_sessions as sessions
from tests.test_tui_p0 import FINAL, tool


MONTH = {"company_id": "C001", "year": 2026, "month": 9}


class FinalLiveFixes(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = sessions.SessionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def agent(self, *replies, user="U001", **options):
        return Agent(user, self.fixture.book, scripted_model(replies), mode="mock", **options)

    def test_directory_preview_is_the_only_ordered_reference(self):
        agent = self.agent(tool("list_invoice_directory", {**MONTH, "page": 1}), FINAL, FINAL)
        agent.ask("查甲企业2026年9月发票目录")
        page = agent.last_response["tool_results"][0][1]["data"]
        self.assertGreater(len(page["rows"]), 3)
        agent.ask("查看第二张发票")
        reference = agent.last_response["tool_results"][0][1]
        self.assertEqual(reference["data"]["invoice_no"], page["rows"][1]["invoice_no"])
        self.assertEqual(reference["evidence"]["reference"]["source"], "list_invoice_directory")

        agent = self.agent(tool("list_invoice_directory", {**MONTH, "page": 1}), FINAL)
        agent.ask("查甲企业2026年9月发票目录")
        agent.ask("查看第四张发票")
        self.assertEqual(agent.last_response["execution"]["stop_reason"], "AMBIGUOUS")
        self.assertFalse(agent.last_response["tool_results"])

    def test_cross_company_comparison_reads_both_current_joint_keys(self):
        read = lambda company: tool("get_invoice", {"company_id": company, "invoice_no": "F002"})
        agent = self.agent(read("C001"), FINAL, read("C002"), FINAL)
        agent.ask("查看甲企业F002")
        with closing(open_existing(self.fixture.book)) as conn, conn:
            conn.execute("UPDATE invoices SET remark=? WHERE company_id=? AND invoice_no=?",
                         ("刚改过的备注", "C001", "F002"))
        answer = agent.ask("再查乙企业F002，和刚才那张有什么不同")
        self.assertIn("C001/F002 与 C002/F002", answer)
        self.assertIn("刚改过的备注", answer)
        self.assertEqual([outcome["data"]["company_id"] for _, outcome in agent.last_response["tool_results"]],
                         ["C002", "C001"])

        denied = self.agent(read("C001"), FINAL, read("C002"), user="U002")
        denied.ask("查看甲企业F002")
        answer = denied.ask("再查乙企业F002，和刚才那张有什么不同")
        self.assertEqual(denied.last_response["execution"]["stop_reason"], "DENIED")
        self.assertNotIn("刚改过的备注", answer)

    def test_annual_explanation_does_not_run_monthly_compliance(self):
        annual = tool("list_annual_blank_purpose", {"company_id": "C001", "year": 2026, "page": 1})
        agent = self.agent(annual, FINAL)
        agent.ask("查甲企业2026年全年用途为空的发票")
        self.assertEqual(agent.last_response["tool_results"][0][1]["data"]["total"], 10)
        answer = agent.ask("是不是这10张都违反规定了？")
        self.assertIn("不能把这些发票一律认定为违规", answer)
        self.assertIn("R002 v2.0", answer)
        self.assertFalse(agent.last_response["tool_results"])
        self.assertEqual(agent.last_response["execution"]["model_requests"], 0)

    def test_rule_history_and_yuan_display_preserve_raw_storage(self):
        request = tool("list_rule_versions", {"company_id": "C001", "rule_id": "R002"})
        agent = self.agent(request, FINAL)
        answer = agent.ask("甲企业R002的历史v1.0还适用吗？")
        self.assertIn("R002 v1.0 · 已停用", answer)
        self.assertIn("R002 v2.0 · 启用", answer)
        self.assertIn("达到¥1,000.00（含）", answer)
        raw = agent.last_response["tool_results"][0][1]["data"]
        self.assertIn("100000", raw[0]["content"])

    def test_bank_explanation_and_explicit_read_only_boundary(self):
        agent = self.agent(tool("get_finance_summary", MONTH), FINAL)
        answer = agent.ask("查甲企业2026年9月银行收入和支出，能判断具体发票是否付款吗？")
        self.assertIn("无法据此判断具体发票是否已付款", answer)
        self.assertIn("银行支出", answer)
        self.assertIn("无法据此判断", agent.ask("那能看出哪些发票已经付款吗？"))
        answer = agent.ask("修改银行支出总额", allow_prepare=True)
        self.assertIn("统计总额均为只读", answer)
        self.assertFalse(agent.last_response["tool_results"])

    def test_duplicate_task_retains_one_record_and_gives_next_step(self):
        args = {**MONTH, "action": "create", "task_id": "", "note": ""}
        approvals = []
        agent = self.agent(tool("manage_task", args, "first"), FINAL,
                           tool("check_missing_purpose", MONTH, "check"), tool("manage_task", args, "second"),
                           management_confirmation=lambda proposal: approvals.append(proposal) or True)
        agent.ask("为甲企业2026年9月缺用途发票创建待办", task_note_from_request=True)
        answer = agent.ask("再为甲企业2026年9月缺用途发票创建一个待办", task_note_from_request=True)
        self.assertEqual(agent.last_response["execution"]["stop_reason"], "CONFLICT")
        self.assertIn("已有未完成待办", answer)
        self.assertIn("查看或继续", answer)
        self.assertEqual(len(approvals), 1)
        self.assertEqual(len(list_tasks(self.fixture.book, "U001", "C001")["data"]), 1)

    async def test_pilot_shows_preview_then_second_invoice(self):
        h = self.fixture
        app = h.app([tool("list_invoice_directory", {**MONTH, "page": 1}), FINAL, FINAL])
        async with app.run_test(size=(110, 36)) as pilot:
            await h.helper.sign_in(app, pilot)
            await h.helper.send(app, pilot, "查甲企业2026年9月发票目录")
            await h.helper.await_state(pilot, lambda: len(app.records) == 1 and not app.busy)
            expected = app.agent.last_response["tool_results"][0][1]["data"]["rows"][1]["invoice_no"]
            self.assertIn(expected, h.log(app))
            await h.helper.send(app, pilot, "查看第二张发票")
            await h.helper.await_state(pilot, lambda: len(app.records) == 2 and not app.busy)
            self.assertEqual(app.agent.last_response["tool_results"][0][1]["data"]["invoice_no"], expected)
