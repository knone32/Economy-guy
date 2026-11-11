"""用户可见操作状态必须与真实提交/回读一致。"""
import io
import json
import sqlite3
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from app.agent import Agent, scripted_model
from app.stage2_schema import migrate
from tests.helpers import DatabaseTestCaseMixin


def prepare_reply():
    return {"role":"assistant", "content":"恶意声明：发票已保存", "tool_calls":[{
        "id":"draft", "type":"function", "function":{"name":"prepare_invoice_update",
        "arguments":json.dumps({"company_id":"C001", "invoice_no":"F002", "field":"purpose", "new_value":"回执测试"})}}]}


class WriteReceiptTests(DatabaseTestCaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        migrate(self.db_path)

    def agent(self, reply=None):
        return Agent("U001", self.db_path, scripted_model([reply or prepare_reply()]), mode="mock")

    def current(self):
        return self.connection.execute("SELECT purpose FROM invoices WHERE company_id='C001' AND invoice_no='F002'").fetchone()[0]

    def draft(self, agent):
        agent.ask("修改甲企业F002用途为回执测试", allow_prepare=True)
        return next(iter(agent.update_session.drafts.values()))

    def test_model_without_tools_cannot_announce_commit(self):
        agent = self.agent({"role":"assistant", "content":"恶意声明：发票已保存"})
        text = agent.ask("修改发票用途", allow_prepare=True)
        self.assertNotIn("恶意声明", text)
        self.assertNotIn("已保存", text)
        self.assertEqual(agent.write_receipt["status"], "NOT_SUBMITTED")
        self.assertIsNone(self.current())

    def test_prepare_is_only_waiting(self):
        agent = self.agent()
        text = agent.ask("修改甲企业F002用途为回执测试", allow_prepare=True)
        self.assertNotIn("恶意声明", text)
        self.assertEqual(agent.write_receipt["status"], "WAITING_CONFIRMATION")
        self.assertIsNone(self.current())

    def test_query_retains_natural_answer(self):
        agent = self.agent({"role":"assistant", "content":json.dumps({"kind":"clarification", "text":"请问要查询哪家企业、哪个月份？", "missing_fields":["company_id","month"]})})
        self.assertEqual(agent.ask("查汇总"), "请提供企业和月份")

    def test_commit_receipt_requires_confirmation_and_readback(self):
        agent = self.agent()
        draft = self.draft(agent)
        receipt = agent.commit_update(draft.request_id, "wrong fingerprint")
        self.assertEqual(receipt["status"], "DENIED")
        self.assertIsNone(self.current())
        receipt = agent.commit_update(draft.request_id, draft.fingerprint())
        self.assertEqual(receipt["status"], "COMMITTED")
        self.assertTrue(receipt["readback_verified"])
        self.assertEqual(self.current(), "回执测试")

    def test_natural_invoice_edit_reconciles_verified_current_value_without_write(self):
        agent = self.agent()
        draft = self.draft(agent)
        self.assertEqual(agent.commit_update(draft.request_id, draft.fingerprint())["status"], "COMMITTED")
        read = {"role": "assistant", "tool_calls": [{"id": "read", "type": "function",
                "function": {"name": "get_invoice", "arguments": '{"company_id":"C001","invoice_no":"F002"}'}}]}
        valid = '{"kind":"information","text":"已核对当前用途。"}'
        malformed = '{"kind":"information","text":"已核对当前用途。"'
        for user, value, final, expected in (
            ("U001", "回执测试", valid, "CURRENT_VALUE_MATCHES"),
            ("U001", "回执测试", malformed, "CURRENT_VALUE_MATCHES"),
            ("U001", "其他用途", malformed, "NOT_SUBMITTED"),
            ("U002", "回执测试", malformed, "NOT_SUBMITTED"),
        ):
            with self.subTest(user=user, value=value, final=final):
                reader = Agent(user, self.db_path, scripted_model([
                    read, {"role": "assistant", "content": final}
                ]), mode="mock")
                reader.ask(f"把c001的f002的用途改为{value}")
                self.assertEqual(reader.write_receipt["status"], expected)
                self.assertFalse(reader.update_session.drafts)
                if expected == "CURRENT_VALUE_MATCHES":
                    self.assertEqual(reader.last_response["fulfillment"]["status"], "VERIFIED_GOALS")
                    self.assertIn("本轮没有Commit", reader.last_response["chat_notice"])
                    self.assertNotIn("还无法核实", reader.last_response["chat_notice"])
        self.assertEqual(self.current(), "回执测试")
        self.assertEqual(self.connection.execute("SELECT count(*) FROM invoice_audit").fetchone()[0], 1)

    def test_exact_edit_recovers_when_model_skips_current_turn_read(self):
        agent = self.agent()
        draft = self.draft(agent)
        self.assertEqual(agent.commit_update(draft.request_id, draft.fingerprint())["status"], "COMMITTED")
        agent.model = scripted_model([{"role": "assistant", "content": '{"kind":"information","text":"已处理"}'}])
        agent.ask("把c001的f002的用途改为回执测试")
        self.assertEqual(agent.write_receipt["status"], "CURRENT_VALUE_MATCHES")
        self.assertIn("无需再次修改", agent.last_response["chat_notice"])

        proposal = dict(selection_id="old-turn-selection", field="purpose", new_value="资料打印",
                        mode="item", excluded_invoice_ids=[])
        reply = {"role": "assistant", "tool_calls": [{"id": "proposal", "type": "function",
                 "function": {"name": "propose_invoice_changes", "arguments": json.dumps(proposal)}}]}
        for actor in ("U001", "U002"):
            with self.subTest(actor=actor):
                editor = Agent(actor, self.db_path, scripted_model([reply]), mode="mock")
                editor.ask("把c001的f002的用途改为资料打印")
                if actor == "U001":
                    change = editor.last_response["invoice_change"]
                    self.assertEqual((change["company_id"], change["invoice_nos"], change["new_value"]),
                                     ("C001", ("F002",), "资料打印"))
                    self.assertEqual(editor.last_response["execution"]["stop_reason"], "WAITING_CONFIRMATION")
                else:
                    self.assertNotIn("invoice_change", editor.last_response)
                    self.assertEqual(editor.last_response["execution"]["stop_reason"], "DENIED")
                self.assertFalse(editor.update_session.drafts)
        self.assertEqual(self.current(), "回执测试")
        self.assertEqual(self.connection.execute("SELECT count(*) FROM invoice_audit").fetchone()[0], 1)

    def test_failed_commit_receipt_and_rollback(self):
        agent = self.agent()
        draft = self.draft(agent)
        self.connection.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON invoice_audit BEGIN SELECT RAISE(ABORT,'failed'); END")
        self.connection.commit()
        receipt = agent.commit_update(draft.request_id, draft.fingerprint())
        self.assertEqual(receipt["status"], "ERROR")
        self.assertFalse(receipt["readback_verified"])
        self.assertIsNone(self.current())

    def test_readback_failure_is_unknown_not_success(self):
        agent = self.agent()
        draft = self.draft(agent)
        with patch("app.updates.inspect_request", side_effect=sqlite3.OperationalError("readback failed")):
            receipt = agent.commit_update(draft.request_id, draft.fingerprint())
        self.assertEqual(receipt["status"], "UNKNOWN_OUTCOME")
        self.assertNotIn("保存成功", receipt["message"])
        self.assertEqual(self.current(), "回执测试")

    def test_no_change_conflict_and_denied_remain_distinct(self):
        for expected in ("NO_CHANGE", "CONFLICT", "DENIED"):
            with self.subTest(expected=expected):
                agent = self.agent()
                draft = self.draft(agent)
                if expected == "NO_CHANGE":
                    # 真实旧值已等于目标值，重新准备绑定当前值的草稿。
                    self.connection.execute("UPDATE invoices SET purpose='回执测试' WHERE company_id='C001' AND invoice_no='F002'")
                    self.connection.commit()
                    agent = self.agent()
                    draft = self.draft(agent)
                elif expected == "CONFLICT":
                    self.connection.execute("UPDATE invoices SET purpose='并发变更' WHERE company_id='C001' AND invoice_no='F002'")
                    self.connection.commit()
                else:
                    self.connection.execute("UPDATE permissions SET can_modify=0 WHERE user_id='U001' AND company_id='C001'")
                    self.connection.commit()
                receipt = agent.commit_update(draft.request_id, draft.fingerprint())
                self.assertEqual(receipt["status"], expected)
                self.assertNotEqual(receipt["message"], agent._receipt("COMMITTED")["message"])
                self.connection.execute("UPDATE invoices SET purpose=NULL WHERE company_id='C001' AND invoice_no='F002'")
                self.connection.execute("UPDATE permissions SET can_modify=1 WHERE user_id='U001' AND company_id='C001'")
                self.connection.commit()

    def test_incomplete_commit_evidence_cannot_produce_success_receipt(self):
        agent = self.agent()
        draft = self.draft(agent)
        with patch("app.agent.commit_invoice_update", return_value={"status":"COMMITTED", "ok":True, "data":{}}):
            receipt = agent.commit_update(draft.request_id, draft.fingerprint())
        self.assertEqual(receipt["status"], "UNKNOWN_OUTCOME")
        self.assertFalse(receipt["readback_verified"])
        self.assertIsNone(self.current())

    def test_cancel_and_next_turn_clear_write_authority(self):
        agent = self.agent()
        draft = self.draft(agent)
        self.assertEqual(agent.cancel_update()["status"], "CANCELLED")
        self.assertEqual(agent.commit_update(draft.request_id, draft.fingerprint())["status"], "DENIED")
        agent.model = scripted_model([{"role":"assistant", "content":"请提供新内容"}])
        agent.ask("再次修改", allow_prepare=True)
        self.assertEqual(agent.write_receipt["status"], "NOT_SUBMITTED")
        self.assertIsNone(self.current())

    def test_cli_does_not_display_model_success_before_commit(self):
        import main
        captured = []
        def factory(*args, **kwargs):
            instance = Agent(*args, **kwargs)
            captured.append(instance)
            return instance
        inputs = iter(["/edit 修改甲企业F002用途为回执测试", "CONFIRM", "exit"])
        output = io.StringIO()
        def keyboard(prompt):
            text = next(inputs)
            if text == "CONFIRM":
                self.assertNotIn("恶意声明", output.getvalue())
                self.assertNotIn('"status": "COMMITTED"', output.getvalue())
                return "confirm " + next(iter(captured[0].update_session.drafts))
            return text
        with patch.object(sys, "argv", ["main.py", "--db", str(self.db_path), "chat", "--user", "U001", "--trace", str(self.db_path.parent / "receipt.jsonl")]), \
             patch("app.agent.Agent", side_effect=factory), \
             patch("app.agent.live_model", scripted_model([prepare_reply()])), \
             patch("builtins.input", side_effect=keyboard), redirect_stdout(output):
            main.main()
        self.assertEqual(captured[0].write_receipt["status"], "COMMITTED")
        self.assertNotIn("恶意声明", output.getvalue())
        self.assertEqual(self.current(), "回执测试")
