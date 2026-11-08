"""R3 acceptance against isolated official fixtures and the real Agent/TUI."""
import json
import unittest
from decimal import Decimal

from app.persistence import ManagementIntent
from app.tasks import manage_task
from tests import test_s4_br as br
from tests import test_tui_p0 as fixture

YEAR = {"company_id": "C001", "year": 2026}


class ClosureTests(br.ReviewCase):
    def test_annual_amounts_and_blank_fields_match_sql(self):
        amount = br.call("get_annual_finance_summary", YEAR, "amount")
        amount["tool_calls"] += br.call("list_annual_blank_purpose", {**YEAR, "page": 1}, "blank")["tool_calls"]
        a = self.agent([amount, br.FINAL])
        answer = a.ask("查询甲企业 2026 年发票、银行收入支出和用途为空的发票。")
        total, blank = br.outcomes(a)
        self.assertEqual(br.tool_pairs(a), ["amount", "blank"])
        self.assertEqual([total["status"], blank["status"]], ["SUCCESS", "SUCCESS"])
        inv = self.connection.execute("SELECT count(*), sum(amount_cents) FROM invoices WHERE company_id='C001' AND invoice_date LIKE '2026-%'").fetchone()
        bank = dict((r[0], tuple(r)[1:]) for r in self.connection.execute(
            "SELECT direction,count(*),sum(amount_cents) FROM bank_transactions WHERE company_id='C001' AND transaction_date LIKE '2026-%' GROUP BY direction"))
        actual = total["data"]
        self.assertEqual((actual["invoice_count"], actual["invoice_total"]), (inv[0], f"{Decimal(inv[1]) / 100:.2f}"))
        for label, key in (("收入", "bank_income"), ("支出", "bank_expense")):
            self.assertEqual((actual[key+"_count"], actual[key+"_total"]), (bank[label][0], f"{Decimal(bank[label][1]) / 100:.2f}"))
        expected = [r[0] for r in self.connection.execute(
            "SELECT invoice_no FROM invoices WHERE company_id='C001' AND invoice_date LIKE '2026-%' AND trim(coalesce(purpose,''))='' ORDER BY invoice_date,invoice_no")]
        self.assertEqual(blank["data"]["total"], len(expected))
        self.assertEqual([row["invoice_no"] for row in blank["data"]["rows"]], expected[:10])
        self.assertNotIn("rule", blank["evidence"])
        self.assertIn("字段为空", answer)

    def test_annual_range_requires_unique_trusted_year_and_acl(self):
        name = "get_annual_finance_summary"
        for prompt, args, user, focus, status in (
            ("查询甲企业全年发票和银行。", YEAR, "U001", None, "AMBIGUOUS"),
            ("查询甲企业全年发票和银行。", YEAR, "U001", ("C001", 2026, 9), "AMBIGUOUS"),
            ("查询甲企业 2025 年和 2026 年。", YEAR, "U001", None, "AMBIGUOUS"),
            ("查询甲企业 2026 年上半年。", YEAR, "U001", None, "AMBIGUOUS"),
            ("查询甲企业 2026-13。", YEAR, "U001", ("C001", 2026, 0), "AMBIGUOUS"),
            ("查询甲企业 2026 年发票。", {**YEAR, "year": 2025}, "U001", None, "SCOPE_MISMATCH"),
            ("查询乙企业 2026 年发票。", {**YEAR, "company_id": "C002"}, "U002", None, "DENIED"),
        ):
            with self.subTest(prompt=prompt, args=args, focus=focus):
                a = self.agent([br.call(name, args), br.FINAL], user=user)
                a.ask(prompt, read_workspace=focus)
                [outcome] = br.outcomes(a)
                self.assertEqual((outcome["status"], outcome["data"]), (status, None))
        a = self.agent([br.call(name, YEAR), br.FINAL])
        a.ask("查同一年度发票和银行。", read_workspace=("C001", 2026, 0))
        self.assertEqual(br.outcomes(a)[0]["status"], "SUCCESS")
        self.assertEqual(a.last_response["execution"]["model_requests"], 2)

    def test_month_and_rule_boundaries_and_empty_year(self):
        for tool, args, prompt, status in (
            ("get_finance_summary", br.SCOPE, "查甲企业 2026 年 9 月金额。", "SUCCESS"),
            ("get_finance_summary", br.SCOPE, "查甲企业 2026 年金额。", "SCOPE_MISMATCH"),
            ("check_missing_purpose", br.SCOPE, "检查甲企业 2026 年 9 月必填用途。", "SUCCESS"),
            ("check_missing_purpose", {**br.SCOPE, "month": 8}, "检查甲企业 2026 年 8 月必填用途。", "INVALID_ARGUMENTS"),
            ("check_missing_purpose", br.SCOPE, "检查甲企业 2026 年全年必填用途。", "SCOPE_MISMATCH"),
            ("get_annual_finance_summary", {**YEAR, "year": 2025}, "查甲企业 2025 年金额。", "NO_DATA"),
        ):
            with self.subTest(tool=tool, prompt=prompt):
                a = self.agent([br.call(tool, args), br.FINAL])
                a.ask(prompt, read_workspace=("C001", 2026, 0))
                [outcome] = br.outcomes(a)
                self.assertEqual(outcome["status"], status)
                if status == "NO_DATA":
                    self.assertEqual(outcome["data"]["invoice_total"], "0.00")
                elif tool == "get_finance_summary" and status == "SUCCESS":
                    self.assertEqual(outcome["data"]["invoice_total"], "9622.06")
                elif tool == "check_missing_purpose" and status == "SUCCESS":
                    self.assertEqual((outcome["evidence"]["rule"]["version"], outcome["data"]["count"]), ("2.0", 5))
        with self.connection:
            self.connection.execute("DROP TABLE bank_transactions")
        a = self.agent([br.call("get_annual_finance_summary", YEAR), br.FINAL])
        a.ask("查甲企业 2026 年金额。")
        self.assertEqual((br.outcomes(a)[0]["status"], br.outcomes(a)[0]["data"]), ("ERROR", None))

    def test_annual_blank_uses_current_field_and_paginates(self):
        with self.connection:
            self.connection.execute("UPDATE invoices SET purpose=? WHERE company_id='C001' AND invoice_no='F002'", ("　\t",))
            self.connection.execute("UPDATE invoices SET purpose=NULL WHERE company_id='C001' AND invoice_no='F001'")
        def page(n):
            return br.call("list_annual_blank_purpose", {**YEAR, "page": n}, f"blank-{n}")
        a = self.agent([page(1), page(2), br.FINAL])
        a.ask("列出甲企业 2026 年所有用途为空的发票。")
        rows = [row["invoice_no"] for result in br.outcomes(a) for row in result["data"]["rows"]]
        self.assertIn("F002", rows)
        self.assertTrue(br.outcomes(a)[1]["data"]["rows"])
        self.assertEqual(len(rows), br.outcomes(a)[0]["data"]["total"])
        self.assertEqual(len(set(rows)), len(rows))

    def test_c5_reports_current_f002_without_attributing_history(self):
        task = manage_task(self.db_path, "U001", "C001", "create", year=2026, month=9, note="继续补齐",
                           intent=ManagementIntent("U001", "task", "可信测试"))["data"]["task"]
        with self.connection:
            self.connection.execute("UPDATE invoices SET purpose='测试已填' WHERE company_id='C001' AND invoice_no='F002'")
        start = self.state()
        reply = br.call("list_tasks", {"company_id": "C001"}, "task")
        reply["tool_calls"] += br.call("check_missing_purpose", br.SCOPE, "missing")["tool_calls"]
        a = self.agent([reply, br.FINAL])
        answer = a.ask(br.C5)
        self.assertIn("当前值已填写", answer)
        self.assertIn("F002", answer)
        self.assertIn("当前剩余 4 张", answer)
        self.assertIn(task["task_id"], answer)
        self.assertNotIn("本任务已补齐", answer)
        self.assertEqual(self.state(), start)


    def test_c5_distinguishes_verified_commit_from_task_attribution(self):
        task = manage_task(self.db_path, "U001", "C001", "create", year=2026, month=9, note="继续补齐",
                           intent=ManagementIntent("U001", "task", "可信测试"))["data"]["task"]
        with self.connection:
            self.connection.execute("UPDATE tasks SET created_at='2026-01-01 00:00:00' WHERE task_id=?", (task["task_id"],))
        a = self.agent([br.call("prepare_invoice_update", {**br.TARGET, "field": "purpose", "new_value": br.VALUE})])
        a.ask(br.B2, allow_prepare=True)
        draft = next(iter(a.update_session.drafts.values()))
        commit = a.commit_update(draft.request_id, draft.fingerprint())
        self.assertEqual((commit["status"], commit["readback_verified"]), ("COMMITTED", True))
        before = self.state()
        a = self.agent([br.call("list_tasks", {"company_id": "C001"}, "task"),
                        br.call("check_missing_purpose", br.SCOPE, "check"), br.FINAL])
        answer = a.ask(br.C5)
        for fragment in ("有补齐成功记录且当前值一致：F002", "审计未绑定待办", "ACTIVE", "当前剩余 4 张", "下一步"):
            self.assertIn(fragment, answer)
        self.assertEqual(br.tool_pairs(a), ["task", "check"])
        self.assertEqual(self.state(), before)


class InvalidFinalTests(unittest.IsolatedAsyncioTestCase):
    async def test_annual_cards_and_explicit_focus_reuse(self):
        h = fixture.P0Test()
        h.setUp()
        self.addCleanup(h.doCleanups)
        app = h.app([fixture.tool("get_annual_finance_summary", YEAR, "annual"),
                     fixture.FINAL, fixture.tool("list_annual_blank_purpose", {**YEAR, "page": 1}, "focus"),
                     fixture.FINAL])
        app.session_path = h.directory / "r3-conversations.sqlite3"
        async with app.run_test(size=(100, 34)) as pilot:
            await h.sign_in(app, pilot)
            self.assertIsNone(app.read_workspace)
            await h.send(app, pilot, "查甲企业 2026 年全年金额。")
            await h.await_state(pilot, lambda: len(app.records) == 1 and not app.busy)
            self.assertEqual(app.resume_focus, ("C001", 2026, 0))
            await h.send(app, pilot, "再查同一年度用途字段为空的发票。")
            await h.await_state(pilot, lambda: len(app.records) == 2 and not app.busy)
            self.assertEqual(app.records[-1][0], "ANSWERED")
            text = "".join(line.text for line in app.workspace_widget("#chat-log").lines)
            for expected in ("2026 年", "年度用途空值", "仅检查字段值"):
                self.assertIn(expected, text)

    async def test_directory_keeps_cards_and_explains_invalid_final(self):
        h = fixture.P0Test()
        h.setUp()
        self.addCleanup(h.doCleanups)
        def page(n):
            return fixture.tool("list_invoice_directory", {**YEAR, "year": 0, "month": 0, "page": n}, f"page-{n}")
        app = h.app([page(1), page(2), {"role": "assistant", "content": "未核验伪造成功"}])
        app.trace_path = h.directory / "invalid-final.jsonl"
        async with app.run_test(size=(100, 34)) as pilot:
            await h.sign_in(app, pilot)
            await h.send(app, pilot, "列出甲企业所有发票。")
            await h.await_state(pilot, lambda: bool(app.records))
            self.assertEqual(app.records[-1][0], "INVALID_RESPONSE")
            self.assertEqual([c["id"] for c in app.records[-1][1]], ["page-1", "page-2"])
            text = "".join(line.text for line in app.workspace_widget("#chat-log").lines)
            for expected in ("第 1 页", "第 2 页", "上方结果已核验", "模型未能整理"):
                self.assertIn(expected, text)
            self.assertNotIn("未核验伪造成功", text)
        events = [json.loads(line) for line in app.trace_path.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(e["event"] == "error" and e["data"] == {"category":"invalid_final_envelope"} for e in events))
