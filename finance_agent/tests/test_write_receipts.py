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

    def test_single_edit_recovers_verified_pronoun_and_checks_proposed_period(self):
        from app.invoice_batch import run_invoice_batch
        read = {"role": "assistant", "tool_calls": [{"id": "read", "type": "function",
                "function": {"name": "get_invoice", "arguments": '{"company_id":"C001","invoice_no":"F002"}'}}]}
        final = {"role": "assistant", "content": '{"kind":"information","text":"当前用途为空"}'}
        def proposal(selection, month=9):
            args = dict(selection_id=selection, field="purpose", new_value="资料打印",
                        mode="item", excluded_invoice_ids=[], target_year=2026, target_month=month)
            return {"role": "assistant", "tool_calls": [{"id": "proposal", "type": "function",
                    "function": {"name": "propose_invoice_changes", "arguments": json.dumps(args)}}]}
        agent = Agent("U001", self.db_path, scripted_model([read, final]), mode="mock")
        agent.ask("查询 C001 的 F002，看看用途填了没有")
        calls = iter((read, None))
        def edit_model(messages, tools):
            if reply := next(calls):
                return reply
            latest_tool = next(message for message in reversed(messages) if message["role"] == "tool")
            selection = json.loads(latest_tool["content"])["data"]["selection_id"]
            return proposal(selection)
        agent.model = edit_model
        agent.ask("把他的用途改成资料打印")
        self.assertEqual(agent.last_response["invoice_change"]["invoice_nos"], ("F002",))
        self.assertEqual(agent.last_response["execution"]["stop_reason"], "WAITING_CONFIRMATION")
        for month, status in ((9, "WAITING_CONFIRMATION"), (8, "SCOPE_MISMATCH")):
            direct = Agent("U001", self.db_path, scripted_model([proposal("old-selection", month)]), mode="mock")
            direct.ask("把 C001 的 F002 用途改为资料打印")
            self.assertEqual(direct.last_response["execution"]["stop_reason"], status)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM invoice_audit").fetchone()[0], 0)
        change = agent.last_response["invoice_change"]
        status, _ = run_invoice_batch(agent, change["source_request"], change,
            approve_batch=lambda *_: False, approve_item=lambda _: "confirm", checkpoint=lambda _: None)
        self.assertEqual(status, "COMPLETED")
        self.assertTrue(agent.write_receipt["readback_verified"])
        agent.model = scripted_model([final])
        agent.ask("把 C001 的 F002 用途改为资料打印")
        self.assertEqual(agent.write_receipt["status"], "CURRENT_VALUE_MATCHES")
        self.assertEqual(self.connection.execute("SELECT count(*) FROM invoice_audit").fetchone()[0], 1)

    def test_recent_edit_binds_current_tool_evidence_without_guessing_between_objects(self):
        def call(name, args, identifier):
            return {"role": "assistant", "tool_calls": [{"id": identifier, "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)}}]}

        invoice = {"company_id": "C001", "invoice_no": "F002"}
        initial = call("get_invoice", invoice, "initial")
        final = {"role": "assistant", "content": '{"kind":"information","text":"已核对。"}'}
        for prompt, lookup, month, conflict, expected in (
            ("这张票用途换成资料打印", "get_invoice", 9, False, "WAITING_CONFIRMATION"),
            ("用途改成资料打印", "resolve_recent_invoice", 9, False, "WAITING_CONFIRMATION"),
            ("用途改成资料打印", "resolve_recent_invoice", 8, False, "SCOPE_MISMATCH"),
            ("用途改成资料打印", "resolve_recent_invoice", 9, True, "AMBIGUOUS"),
            ("把它的用图改成资料打印", "resolve_recent_invoice", 9, False, "AMBIGUOUS"),
        ):
            with self.subTest(prompt=prompt, lookup=lookup, month=month, conflict=conflict):
                agent = Agent("U001", self.db_path, scripted_model([initial, final]), mode="mock")
                agent.ask("查询 C001 的 F002 当前用途")
                reads = iter((True, False))
                def model(messages, tools):
                    if next(reads):
                        args = invoice if lookup == "get_invoice" else {"source": "queried"}
                        return call(lookup, args, "lookup")
                    latest = next(message for message in reversed(messages) if message["role"] == "tool")
                    selection = json.loads(latest["content"])["data"]["selection_id"]
                    return call("propose_invoice_changes", dict(selection_id=selection, field="purpose",
                                new_value="资料打印", mode="item", excluded_invoice_ids=[],
                                target_year=2026, target_month=month), "proposal")
                agent.model = model
                candidates = {"queried": invoice}
                if conflict:
                    candidates["modified"] = {"company_id": "C001", "invoice_no": "F003"}
                with patch.object(agent.context, "recent_invoice_candidates", return_value=candidates):
                    agent.ask(prompt)
                response = agent.last_response
                self.assertEqual(response["execution"]["stop_reason"], expected)
                if expected == "WAITING_CONFIRMATION":
                    self.assertEqual(response["invoice_change"]["invoice_nos"], ("F002",))
                else:
                    self.assertNotIn("invoice_change", response)
                if conflict:
                    self.assertIn("发票来源", response["chat_notice"])
        self.assertEqual(self.connection.execute("SELECT count(*) FROM invoice_audit").fetchone()[0], 0)

    def field_clarification_agent(self, *, reference=False, value="资料打印", omit_marker=False, prompt=None,
                                  first_reply=None):
        agent = self.agent()
        invoice = {"company_id": "C001", "invoice_no": "F002"}
        use_resolver = reference and prompt is None
        prompt = prompt or ("把用图改成资料打印。" if reference else "把 C001 的 F002 改成资料打印。")
        if omit_marker:
            prompt = prompt.removeprefix("把").lstrip()

        def model(messages, tools):
            user_index = next(index for index in range(len(messages) - 1, -1, -1) if messages[index]["role"] == "user")
            last_user = messages[user_index]
            lookup = next((message for message in messages[user_index + 1:] if message["role"] == "tool"), None)
            if lookup is None:
                if first_reply and last_user["content"] == prompt:
                    return first_reply
                if use_resolver and last_user["content"] == prompt:
                    name, args = "resolve_recent_invoice", {"source": "queried"}
                else:
                    name, args = "get_invoice", invoice
            elif not reference and not omit_marker and last_user["content"] == prompt:
                return {"role": "assistant", "content": '{"kind":"information","text":"当前用途相同。"}'}
            else:
                selection = json.loads(lookup["content"])["data"]["selection_id"]
                name, args = "propose_invoice_changes", {
                    "selection_id": selection, "field": "purpose", "new_value": value, "mode": "item",
                    "excluded_invoice_ids": [], "target_year": 2026, "target_month": 9,
                }
            return {"role": "assistant", "tool_calls": [{"id": name, "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)}}]}

        if reference:
            from app.tool_registry import handle_tool
            read = handle_tool("get_invoice", json.dumps(invoice), "U001", self.db_path)
            agent.context.remember_invoice_query([("get_invoice", read)])
            agent.last_response = {"tool_results": [("get_invoice", read)]}
        agent.model = model
        agent.ask(prompt)
        return agent

    def test_missing_invoice_field_continues_to_separate_confirm_and_readback(self):
        from app.invoice_batch import run_invoice_batch

        agent = self.field_clarification_agent(omit_marker=True)
        self.assertEqual(agent.last_response["chat_notice"], "你想修改这张发票的用途还是备注？")
        self.assertEqual(agent.pending_intent["invoice_field"]["new_value"], "资料打印")
        self.assertEqual(agent.pending_intent["invoice_field"]["source"], "current_sqlite")
        self.assertFalse(agent.update_session.drafts)
        agent.ask("用途。")
        change = agent.last_response["invoice_change"]
        self.assertEqual((change["invoice_nos"], change["field"], change["new_value"]),
                         (("F002",), "purpose", "资料打印"))
        self.assertIsNone(agent.pending_intent)
        self.assertIsNone(self.current())
        self.assertEqual(self.connection.execute("SELECT count(*) FROM invoice_audit").fetchone()[0], 0)

        previews = []
        def approve(body):
            previews.append(body)
            self.assertIsNone(self.current())
            return "confirm"

        status, _ = run_invoice_batch(agent, change["source_request"], change,
                                      approve_item=approve, approve_batch=None, checkpoint=lambda _: None)
        self.assertEqual(status, "COMPLETED")
        self.assertEqual(len(previews), 1)
        self.assertEqual(agent.write_receipt["status"], "COMMITTED")
        self.assertTrue(agent.write_receipt["readback_verified"])
        self.assertEqual(self.current(), "资料打印")
        run_invoice_batch(agent, change["source_request"], change,
                          approve_item=lambda _: self.fail("repeated confirmation"),
                          approve_batch=None, checkpoint=lambda _: None)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM invoice_audit").fetchone()[0], 1)

    def test_suspected_invoice_field_waits_for_semantic_confirmation(self):
        agent = self.field_clarification_agent(reference=True)
        self.assertIn("用途改成「资料打印」吗", agent.last_response["chat_notice"])
        self.assertEqual(agent.pending_intent["invoice_field"]["suggested"], "用途")
        self.assertIsNone(self.current())
        agent.ask("是")
        self.assertEqual(agent.last_response["execution"]["stop_reason"], "WAITING_CONFIRMATION")
        self.assertEqual(agent.last_response["invoice_change"]["invoice_nos"], ("F002",))
        self.assertIsNone(self.current())
        self.assertEqual(self.connection.execute("SELECT count(*) FROM invoice_audit").fetchone()[0], 0)

    def test_recent_invoice_field_typo_from_detail_lookup(self):
        self.connection.execute("UPDATE invoices SET purpose='资料打印' WHERE company_id='C001' AND invoice_no='F002'")
        self.connection.commit()
        agent = self.field_clarification_agent(reference=True, value="你好", prompt="再把这张发票的用图改为你好")
        self.assertIn("用途改成「你好」吗", agent.last_response["chat_notice"])
        self.assertEqual(self.current(), "资料打印")
        agent.ask("是")
        self.assertEqual(agent.last_response["execution"]["stop_reason"], "WAITING_CONFIRMATION")
        change = agent.last_response["invoice_change"]
        self.assertEqual((change["invoice_nos"], change["field"], change["new_value"]),
                         (("F002",), "purpose", "你好"))
        self.assertEqual(self.current(), "资料打印")
        for prompt in ("不要再把这张发票的用图改为你好", "再把这张发票的金额改为你好"):
            with self.subTest(prompt=prompt):
                rejected = self.field_clarification_agent(reference=True, value="你好", prompt=prompt)
                self.assertIsNone(rejected.pending_intent)
                self.assertNotIn("invoice_change", rejected.last_response)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM invoice_audit").fetchone()[0], 0)

    def test_recent_invoice_typo_does_not_ask_for_literal_value_again(self):
        from app.invoice_batch import run_invoice_batch

        self.connection.execute("UPDATE invoices SET purpose='你好' WHERE company_id='C001' AND invoice_no='F002'")
        self.connection.commit()
        agent = self.field_clarification_agent(
            reference=True, value="你好", prompt="再把这张发票的用图改为你好",
            first_reply={"role": "assistant", "content": '{"kind":"clarification","text":"请补充新用途。",'
                                                      '"missing_fields":["new_value"]}'},
        )
        self.assertIn("用途改成「你好」吗", agent.last_response["chat_notice"])
        self.assertFalse(agent.update_session.drafts)
        agent.ask("是")
        change = agent.last_response["invoice_change"]
        run_invoice_batch(agent, change["source_request"], change,
                          approve_item=lambda _: self.fail("same value must not require confirmation"),
                          approve_batch=None, checkpoint=lambda _: None)
        self.assertEqual(self.current(), "你好")
        self.assertEqual(self.connection.execute("SELECT count(*) FROM invoice_audit").fetchone()[0], 0)

    def test_confirmed_field_reconciles_same_value_after_model_final_without_tools(self):
        prompt = "再把这张发票的用图改为你好"
        clarification = {"role": "assistant", "content": '{"kind":"clarification","text":"请补充新用途。",'
                                                            '"missing_fields":["new_value"]}'}
        for current in ("你好", "办公"):
            with self.subTest(current=current):
                self.connection.execute(
                    "UPDATE invoices SET purpose='你好' WHERE company_id='C001' AND invoice_no='F002'")
                self.connection.commit()
                agent = self.field_clarification_agent(reference=True, value="你好", prompt=prompt,
                                                      first_reply=clarification)
                self.assertIn("用途改成「你好」吗", agent.last_response["chat_notice"])
                self.connection.execute("UPDATE invoices SET purpose=? WHERE company_id='C001' AND invoice_no='F002'",
                                        (current,))
                self.connection.commit()
                agent.model = scripted_model([
                    {"role": "assistant", "content": '{"kind":"information","text":"无需修改。"}'}])
                agent.ask("是的")
                self.assertEqual(agent.write_receipt["status"],
                                 "CURRENT_VALUE_MATCHES" if current == "你好" else "NOT_SUBMITTED")
                self.assertEqual([(name, result["evidence"]["source"]) for name, result in
                                  agent.last_response["tool_results"]], [("get_invoice", "current_sqlite")])
                if current == "你好":
                    self.assertIn("无需再次修改", agent.last_response["chat_notice"])
                self.assertFalse(agent.update_session.drafts)
                self.assertEqual(self.current(), current)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM invoice_audit").fetchone()[0], 0)

    def test_invoice_field_continuation_retires_on_new_scope_and_rechecks_permissions(self):
        for action in ("account", "cancel", "different_invoice", "permission", "changed_value"):
            with self.subTest(action=action):
                agent = self.field_clarification_agent(value="打印" if action == "changed_value" else "资料打印")
                self.assertIsNotNone(agent.pending_intent)
                if action in {"account", "cancel", "different_invoice"}:
                    if action == "account":
                        agent.user_id = "U002"
                    elif action == "cancel":
                        agent.cancel_update()
                    agent.model = scripted_model([{"role": "assistant", "content": '{"kind":"general","text":"等待。"}'}])
                if action == "permission":
                    self.connection.execute("UPDATE permissions SET can_modify=0 WHERE user_id='U001' AND company_id='C001'")
                    self.connection.commit()
                try:
                    agent.ask("查询 C001 的 F003" if action == "different_invoice" else "用途")
                    self.assertNotIn("invoice_change", agent.last_response)
                    self.assertIsNone(agent.pending_intent)
                    self.assertFalse(agent.update_session.drafts)
                    if action in {"permission", "changed_value"}:
                        self.assertEqual(agent.last_response["execution"]["stop_reason"],
                                         "DENIED" if action == "permission" else "SCOPE_MISMATCH")
                finally:
                    if action == "permission":
                        self.connection.execute("UPDATE permissions SET can_modify=1 WHERE user_id='U001' AND company_id='C001'")
                        self.connection.commit()
        self.assertEqual(self.connection.execute("SELECT count(*) FROM invoice_audit").fetchone()[0], 0)

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
