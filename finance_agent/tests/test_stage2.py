"""Stage 2所有写入验证仅针对临时数据库。"""
from copy import deepcopy
from dataclasses import replace
import json
import sqlite3
import unittest
import io
import sys
from contextlib import redirect_stdout
from unittest.mock import patch
from app.stage2_schema import migrate, open_existing
from app.updates import UpdateSession, prepare_invoice_update, confirm_draft, commit_invoice_update, inspect_request
from app.rules import SEED_RULES, import_rules, disable_rule, find_rules, resolve_rule, check_missing_purpose, RuleError, make_rule
from app.agent import Agent, handle_tool, scripted_model, TOOLS
from tests.helpers import DatabaseTestCaseMixin

ADMIN = frozenset({"rule.manage"})


class Stage2Tests(DatabaseTestCaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        migrate(self.db_path)
        import_rules(self.db_path, SEED_RULES, ADMIN)
        self.session = UpdateSession("U001")
        self.session.begin_turn("把甲企业F002用途改为项目资料打印", True)

    def prepare(self, company="C001", invoice="F002", field="purpose", value="项目资料打印", session=None):
        return prepare_invoice_update(self.db_path, session or self.session, company, invoice, field, value)

    def confirmed(self, **kwargs):
        outcome = self.prepare(**kwargs)
        self.assertEqual(outcome["status"], "WAITING_CONFIRMATION")
        draft = outcome["data"]
        self.assertTrue(confirm_draft(self.session, draft["request_id"], draft["fingerprint"]))
        return draft["request_id"]

    def value(self, company="C001", invoice="F002", field="purpose"):
        return self.connection.execute(f"SELECT {field} FROM invoices WHERE company_id=? AND invoice_no=?", (company, invoice)).fetchone()[0]

    def test_no_confirmation_or_old_session_cannot_commit(self):
        draft = self.prepare()["data"]
        self.assertEqual(commit_invoice_update(self.db_path, self.session, draft["request_id"])["status"], "DENIED")
        new = UpdateSession("U001")
        new.drafts = self.session.drafts.copy()
        new.confirmations[draft["request_id"]] = draft["fingerprint"]
        self.assertEqual(commit_invoice_update(self.db_path, new, draft["request_id"])["status"], "DENIED")
        self.assertIsNone(self.value())

    def test_permissions_and_readonly_fields(self):
        user = UpdateSession("U002")
        user.begin_turn("改用途", True)
        self.assertEqual(self.prepare(session=user)["status"], "DENIED")
        self.assertEqual(self.prepare(company="C002", session=user)["status"], "DENIED")
        self.assertEqual(self.prepare(field="amount_cents")["status"], "INVALID_ARGUMENTS")
        self.assertEqual(self.prepare(invoice="不存在")["status"], "NOT_FOUND")
        user.begin_turn("查询", False)
        self.assertEqual(self.prepare(session=user)["status"], "DENIED")

    def test_explicit_clear_is_prepared_and_requires_confirmation(self):
        agent = Agent("U001", self.db_path, mode="mock")
        agent.update_session.begin_turn("清空甲企业F001备注", True)
        outcome = handle_tool("prepare_invoice_update", '{"company_id":"C001","invoice_no":"F001","field":"remark","new_value":""}', "U001", self.db_path, agent.update_session)
        self.assertEqual(outcome["status"], "WAITING_CONFIRMATION")
        draft = outcome["data"]
        self.assertTrue(confirm_draft(agent.update_session, draft["request_id"], draft["fingerprint"]))
        self.assertEqual(commit_invoice_update(self.db_path, agent.update_session, draft["request_id"])["status"], "COMMITTED")
        self.assertEqual(self.value(invoice="F001", field="remark"), "")

    def test_commit_audit_isolation_restart_and_idempotence(self):
        other = self.value("C002")
        request = self.confirmed()
        first = commit_invoice_update(self.db_path, self.session, request)
        self.assertEqual(first["status"], "COMMITTED")
        self.assertEqual(self.value(), "项目资料打印")
        self.assertEqual(self.value("C002"), other)
        self.assertEqual(commit_invoice_update(self.db_path, self.session, request)["status"], "COMMITTED")
        self.assertEqual(inspect_request(self.db_path, "U001", request)["status"], "COMMITTED")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM invoice_audit").fetchone()[0], 1)
        self.connection.execute("UPDATE invoices SET purpose='后来修改' WHERE company_id='C001' AND invoice_no='F002'")
        self.connection.commit()
        self.assertFalse(inspect_request(self.db_path, "U001", request)["data"]["current_matches"])
        self.assertEqual(self.value(), "后来修改")

    def test_conflict_and_audit_failure_rollback(self):
        request = self.confirmed()
        self.connection.execute("UPDATE invoices SET purpose='他人修改' WHERE company_id='C001' AND invoice_no='F002'")
        self.connection.commit()
        self.assertEqual(commit_invoice_update(self.db_path, self.session, request)["status"], "CONFLICT")
        request = self.confirmed(value="新的用途")
        self.connection.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON invoice_audit BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END")
        self.connection.commit()
        self.assertEqual(commit_invoice_update(self.db_path, self.session, request)["status"], "ERROR")
        self.assertEqual(self.value(), "他人修改")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM invoice_audit").fetchone()[0], 0)

    def test_revoked_permission_at_commit_and_fingerprint_conflict(self):
        request = self.confirmed()
        self.connection.execute("UPDATE permissions SET can_modify=0 WHERE user_id='U001' AND company_id='C001'")
        self.connection.commit()
        self.assertEqual(commit_invoice_update(self.db_path, self.session, request)["status"], "DENIED")
        self.connection.execute("UPDATE permissions SET can_modify=1 WHERE user_id='U001' AND company_id='C001'")
        self.connection.commit()
        self.assertEqual(commit_invoice_update(self.db_path, self.session, request)["status"], "COMMITTED")
        draft = replace(self.session.drafts[request], new_value="不同内容")
        self.session.drafts[request] = draft
        confirm_draft(self.session, request, draft.fingerprint())
        self.assertEqual(commit_invoice_update(self.db_path, self.session, request)["status"], "CONFLICT")

    def test_no_change_and_unknown_readback(self):
        request = self.confirmed(invoice="F001", value="购买办公文具")
        self.assertEqual(commit_invoice_update(self.db_path, self.session, request)["status"], "NO_CHANGE")
        request = self.confirmed()
        with patch("app.updates.inspect_request", side_effect=sqlite3.OperationalError("readback failed")):
            self.assertEqual(commit_invoice_update(self.db_path, self.session, request)["status"], "UNKNOWN_OUTCOME")
        self.assertEqual(inspect_request(self.db_path, "U001", request)["status"], "COMMITTED")

    def test_commit_ack_lost_queries_history_instead_of_rewriting(self):
        request = self.confirmed()
        real_open = open_existing
        class LostAcknowledgement:
            def __init__(self, connection):
                self.connection = connection
            def __getattr__(self, name):
                return getattr(self.connection, name)
            def commit(self):
                self.connection.commit()
                raise sqlite3.OperationalError("提交确认丢失")
        def wrapped(path, readonly=False):
            connection = real_open(path, readonly)
            return connection if readonly else LostAcknowledgement(connection)
        with patch("app.updates.open_existing", side_effect=wrapped):
            self.assertEqual(commit_invoice_update(self.db_path, self.session, request)["status"], "COMMITTED")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM invoice_audit").fetchone()[0], 1)
        self.assertEqual(self.value(), "项目资料打印")

    def test_future_and_other_company_rules_excluded(self):
        future = make_rule("R002", "future", "未来版本", "C001", "2027-01-01", "ACTIVE", "purpose", {"mode":"all", "threshold_cents":0})
        import_rules(self.db_path, [future], ADMIN)
        self.assertEqual(resolve_rule(self.connection, "U001", "C001", "purpose", "2026-09-01").version, "2.0")
        self.assertEqual(resolve_rule(self.connection, "U001", "C002", "purpose", "2026-09-01").rule_id, "R003")

    def test_migration_does_not_change_business_data(self):
        before = [tuple(row) for row in self.connection.execute("SELECT * FROM invoices ORDER BY company_id,invoice_no")]
        migrate(self.db_path)
        after = [tuple(row) for row in self.connection.execute("SELECT * FROM invoices ORDER BY company_id,invoice_no")]
        self.assertEqual(before, after)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM bank_transactions").fetchone()[0], 48)

    def test_rules_versions_threshold_spaces_and_month(self):
        c001 = check_missing_purpose(self.connection, "U001", "C001", 2026, 9)
        self.assertEqual(c001["rule"]["version"], "2.0")
        self.assertEqual(c001["count"], 5)
        self.connection.execute("UPDATE invoices SET purpose=' \t　' WHERE company_id='C002' AND invoice_no='F002'")
        self.connection.commit()
        c002 = check_missing_purpose(self.connection, "U001", "C002", 2026, 9)
        self.assertEqual({r["invoice_no"] for r in c002["missing_invoices"]}, {"F002", "F005", "F006"})
        with self.assertRaises(RuleError):
            check_missing_purpose(self.connection, "U001", "C001", 2026, 8)
        with self.assertRaises(PermissionError):
            check_missing_purpose(self.connection, "U002", "C002", 2026, 9)
        self.assertEqual(resolve_rule(self.connection, "U001", "C002", "bank", "2026-09-01").rule_id, "R004")

    def test_rule_management_independent_conflicts_and_disable(self):
        with self.assertRaises(PermissionError):
            import_rules(self.db_path, SEED_RULES)
        import_rules(self.db_path, SEED_RULES, ADMIN)
        self.assertEqual(len(find_rules(self.db_path, ADMIN)), 5)
        bad = deepcopy(SEED_RULES[0])
        bad["content"] = "任意正文与执行参数不一致"
        with self.assertRaises(RuleError):
            import_rules(self.db_path, [bad], ADMIN)
        changed = deepcopy(SEED_RULES[0])
        changed["name"] = "同版不同名称"
        with self.assertRaises(RuleError):
            import_rules(self.db_path, [changed], ADMIN)
        new = make_rule("R002", "3.0", "甲企业发票用途规则", "C001", "2026-09-01", "ACTIVE", "purpose", {"mode":"all", "threshold_cents":0})
        import_rules(self.db_path, [new], ADMIN)
        with self.assertRaisesRegex(RuleError, "RULE_CONFLICT"):
            resolve_rule(self.connection, "U001", "C001", "purpose", "2026-09-01")
        disable_rule(self.db_path, "R002", "3.0", ADMIN)
        self.assertEqual(resolve_rule(self.connection, "U001", "C001", "purpose", "2026-09-01").version, "2.0")
        disable_rule(self.db_path, "R002", "2.0", ADMIN)
        with self.assertRaisesRegex(RuleError, "NO_APPLICABLE_RULE"):
            resolve_rule(self.connection, "U001", "C001", "purpose", "2026-09-01")

    def test_agent_prepare_stops_and_model_has_no_commit_or_identity(self):
        calls = [{"id":"p", "type":"function", "function":{"name":"prepare_invoice_update", "arguments":json.dumps({"company_id":"C001", "invoice_no":"F002", "field":"purpose", "new_value":"资料打印"})}}]
        agent = Agent("U001", self.db_path, scripted_model([{"role":"assistant", "tool_calls":calls}]), mode="mock")
        self.assertIn("尚未保存", agent.ask("修改甲企业F002用途为资料打印", allow_prepare=True))
        self.assertIsNone(self.value())
        self.assertNotIn("commit", json.dumps(TOOLS).lower())
        self.assertEqual(handle_tool("commit_invoice_update", "{}", "U001", self.db_path)["status"], "INVALID_ARGUMENTS")
        result = handle_tool("check_missing_purpose", '{"company_id":"C001","year":2026,"month":9}', "U001", self.db_path)
        self.assertEqual(result["evidence"]["rule"], result["data"]["rule"])

    def test_real_cli_confirmation_flow_with_mock_model(self):
        import main
        calls = [{"id":"cli-p", "type":"function", "function":{"name":"prepare_invoice_update", "arguments":json.dumps({"company_id":"C001", "invoice_no":"F002", "field":"purpose", "new_value":"CLI已确认用途"})}}]
        original_agent = Agent
        captured = []
        def factory(*args, **kwargs):
            agent = original_agent(*args, **kwargs)
            captured.append(agent)
            return agent
        inputs = iter(["/edit 把甲企业F002用途改为CLI已确认用途", "CONFIRM", "exit"])
        def keyboard(prompt):
            text = next(inputs)
            if text == "CONFIRM":
                return "confirm " + next(iter(captured[0].update_session.drafts))
            return text
        trace = self.db_path.parent / "cli.jsonl"
        with patch.object(sys, "argv", ["main.py", "--db", str(self.db_path), "chat", "--user", "U001", "--trace", str(trace)]), \
                patch("app.agent.Agent", side_effect=factory), \
                patch("app.agent.live_model", scripted_model([{"role":"assistant", "tool_calls":calls}])), \
                patch("builtins.input", side_effect=keyboard), redirect_stdout(io.StringIO()) as output:
            main.main()
        self.assertEqual(self.value(), "CLI已确认用途")
        self.assertIn('"status": "COMMITTED"', output.getvalue())
        self.assertIn("update.result", trace.read_text(encoding="utf-8"))
