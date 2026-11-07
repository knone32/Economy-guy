"""S4-BR receipt and current-turn task progress regressions on isolated SQLite."""
from contextlib import closing
import json
import sqlite3

from app.persistence import ManagementIntent
from app.references import migrate as migrate_references
from app.responses import render_information
from app.tasks import manage_task
from tests.test_sec_b1 import snapshot
from tests.test_stage4p0c import FINAL, SCOPE, HarnessCase, call, outcomes


B2 = "将 C001 企业 2026 年 9 月 F002 发票的用途修改为项目资料核对。"
C5 = "核对 C001 2026 年 9 月当前用途待办和还缺哪些发票，并说明下一步。"
VALUE = "项目资料核对"
TARGET = {"company_id": "C001", "invoice_no": "F002"}


def tool_pairs(agent):
    return [m["tool_call_id"] for m in agent.messages if m["role"] == "tool"]


class ReviewCase(HarnessCase):
    def setUp(self):
        super().setUp()
        migrate_references(self.db_path)

    def state(self):
        rows = snapshot(self.db_path)
        rows.pop("reference_anchors")
        return rows


class MatchingReceiptTests(ReviewCase):
    def test_b2_and_supported_verbs_match_without_new_commit(self):
        with self.connection:
            self.connection.execute("UPDATE invoices SET purpose=?, remark=? WHERE company_id='C001' AND invoice_no='F002'",
                                    (VALUE, "已核对"))
        before = self.state()
        for text in (B2, *(B2.replace("修改为", verb) for verb in ("改为", "改成", "设置为")),
                     '将 C001 F002 的备注修改为“已核对”。'):
            with self.subTest(text=text):
                a = self.agent([call("get_invoice", TARGET, "current"), FINAL])
                answer = a.ask(text, allow_prepare=True)
                self.assertEqual(a.write_receipt["status"], "CURRENT_VALUE_MATCHES")
                self.assertEqual(a.write_receipt["data"]["checked_by"], "harness_readonly_reconciliation")
                self.assertIn("无需再次修改", answer)
                self.assertEqual(tool_pairs(a), ["current"])
                self.assertFalse(a.update_session.drafts)
                self.assertEqual(self.state(), before)

    def test_ambiguous_and_untrusted_intents_cannot_claim_a_match(self):
        with self.connection:
            self.connection.execute("UPDATE invoices SET purpose=? WHERE company_id='C001' AND invoice_no='F002'", (VALUE,))
        cases = (
            (B2.replace("C001 企业", ""), True, "U001"),
            (B2.replace("F002", ""), True, "U001"),
            (B2.replace(VALUE, "“ ”"), True, "U001"),
            (B2.replace("F002", "F002 和 F003"), True, "U001"),
            (B2.replace("用途", "销售方"), True, "U001"),
            (B2.rstrip("。")+"，用途修改为另一用途。", True, "U001"),
            (B2, True, "U002"),
            (B2.replace(VALUE, "其他内容"), True, "U001"),
            (B2.replace("C001", "C002"), True, "U001"),
            (B2.replace("9 月", "8 月"), True, "U001"),
            (B2, False, "U001"),
        )
        before = self.state()
        for text, edit, user in cases:
            with self.subTest(text=text, edit=edit, user=user):
                a = self.agent([FINAL], user=user)
                a.ask(text, allow_prepare=edit)
                self.assertNotEqual(a.write_receipt["status"], "CURRENT_VALUE_MATCHES")
                self.assertEqual(self.state(), before)

    def test_initial_commit_and_historical_audit_remain_distinct_from_match(self):
        prepare = call("prepare_invoice_update", {**TARGET, "field": "purpose", "new_value": VALUE}, "prepare")
        a = self.agent([prepare])
        a.ask(B2, allow_prepare=True)
        draft = next(iter(a.update_session.drafts.values()))
        outcome = a.commit_update(draft.request_id, draft.fingerprint())
        self.assertEqual((outcome["status"], outcome["readback_verified"]), ("COMMITTED", True))
        before = self.state()
        self.assertEqual(len(before["invoice_audit"]), 1)
        a = self.agent([call("get_invoice", TARGET), FINAL])
        a.ask(B2, allow_prepare=True)
        self.assertEqual(a.write_receipt["status"], "CURRENT_VALUE_MATCHES")
        self.assertEqual(self.state(), before)


class TaskProgressTests(ReviewCase):
    def prepare_progress(self):
        task = manage_task(self.db_path, "U001", "C001", "create", year=2026, month=9,
                           note="继续补齐用途", intent=ManagementIntent("U001","task","可信夹具"))
        self.assertEqual(task["status"], "SUCCESS")
        with self.connection:
            self.connection.execute("UPDATE invoices SET purpose=? WHERE company_id='C001' AND invoice_no='F002'", (VALUE,))
        return task["data"]["task"]["task_id"]

    def test_c5_joins_current_reads_and_renders_next_step_without_writes(self):
        task_id = self.prepare_progress()
        before = self.state()
        with closing(sqlite3.connect(self.db_path.as_uri()+"?mode=ro", uri=True)) as db:
            missing = [r[0] for r in db.execute("""SELECT invoice_no FROM invoices
                WHERE company_id='C001' AND invoice_date LIKE '2026-09%' AND trim(coalesce(purpose,''))=''
                ORDER BY invoice_date,invoice_no""")]
        reply = call("list_tasks", {"company_id": "C001"}, "task")
        reply["tool_calls"] += call("check_missing_purpose", SCOPE, "missing")["tool_calls"]
        a = self.agent([reply, FINAL])
        answer = a.ask(C5)
        self.assertEqual(tool_pairs(a), ["task", "missing"])
        self.assertEqual([r["status"] for r in outcomes(a)], ["SUCCESS", "SUCCESS"])
        self.assertEqual(len(missing), 4)
        self.assertIn(f"任务 {task_id} 状态仍为 ACTIVE", answer)
        self.assertIn("当前剩余 4 张", answer)
        for key in missing:
            self.assertIn(key, answer)
        for fragment in ("下一步", "Prepare", "可信确认", "Commit", "单独核对"):
            self.assertIn(fragment, answer)
        self.assertEqual(a.last_response["execution"]["model_requests"], 2)
        self.assertEqual(self.state(), before)

    def test_missing_or_conflicting_results_never_form_progress_receipt(self):
        self.prepare_progress()
        a = self.agent([call("list_tasks", {"company_id": "C001"}), call("check_missing_purpose", SCOPE, "check"), FINAL])
        a.ask(C5)
        task, check = outcomes(a)
        for variant in (
            [("check_missing_purpose", check)],
            [("list_tasks", task)],
            [("list_tasks", task), ("check_missing_purpose", {**check, "status": "DENIED"})],
            [("list_tasks", task), ("check_missing_purpose", {**check, "evidence": {**check["evidence"],
                                                                            "scope": {**SCOPE, "company_id": "C002"}}})],
            [("list_tasks", task), ("check_missing_purpose", {**check, "evidence": {**check["evidence"],
                                                                            "scope": {**SCOPE, "month": 8}}})],
            [("list_tasks", {**task, "data": [task["data"][0], {**task["data"][0], "task_id": "ambiguous"}]}),
             ("check_missing_purpose", check)],
        ):
            self.assertNotIn("下一步", render_information(variant))

    def test_old_task_read_cannot_substitute_for_current_tool_evidence(self):
        self.prepare_progress()
        a = self.agent([call("list_tasks", {"company_id": "C001"}), FINAL,
                        call("check_missing_purpose", SCOPE, "check"), FINAL])
        a.ask("查看 C001 的待办。")
        answer = a.ask(C5)
        self.assertIn("4张", answer)
        self.assertNotIn("下一步", answer)
