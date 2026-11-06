"""写入目标与跨轮约束、规则日期的缺陷回归。"""
import json
import unittest
from app.agent import Agent, scripted_model
from app.tool_registry import handle_tool
from app.updates import prepare_invoice_update, UpdateSession
from app.stage2_schema import migrate
from app.rules import import_rules, SEED_RULES, make_rule, disable_rule
from tests.helpers import DatabaseTestCaseMixin


def prepare(company="C001", invoice="F002"):
    return {"role":"assistant", "tool_calls":[{"id":"p", "type":"function", "function":{"name":"prepare_invoice_update",
        "arguments":json.dumps({"company_id":company,"invoice_no":invoice,"field":"purpose","new_value":"资料打印"})}}]}


def clarify():
    return {"role":"assistant","content":json.dumps({"kind":"clarification","text":"请提供目标","missing_fields":["invoice_no"]})}


class Stage253Tests(DatabaseTestCaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        migrate(self.db_path)
        import_rules(self.db_path,SEED_RULES,{"rule.manage"})

    def agent(self,replies,user="U001"):
        return Agent(user,self.db_path,scripted_model(replies),mode="mock")

    def assert_unchanged(self):
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM invoice_audit").fetchone()[0],0)
        self.assertIsNone(self.connection.execute("SELECT purpose FROM invoices WHERE company_id='C001' AND invoice_no='F002'").fetchone()[0])
        self.assertIsNone(self.connection.execute("SELECT purpose FROM invoices WHERE company_id='C002' AND invoice_no='F002'").fetchone()[0])

    def test_wrong_company_prepare_rejected_before_draft(self):
        agent = self.agent([prepare("C002")])
        agent.ask("修改C001/F002用途为资料打印",allow_prepare=True)
        self.assertEqual(agent.write_receipt["status"],"SCOPE_MISMATCH")
        self.assertFalse(agent.update_session.drafts)
        self.assert_unchanged()

    def test_wrong_invoice_prepare_rejected_before_draft(self):
        agent = self.agent([prepare(invoice="F003")])
        agent.ask("修改C001/F002用途为资料打印",allow_prepare=True)
        self.assertEqual(agent.write_receipt["status"],"SCOPE_MISMATCH")
        self.assertFalse(agent.update_session.drafts)
        self.assert_unchanged()

    def test_correct_target_waits_for_confirmation_then_commits(self):
        agent = self.agent([prepare()])
        agent.ask("修改C001/F002用途为资料打印",allow_prepare=True)
        self.assertEqual(agent.write_receipt["status"],"WAITING_CONFIRMATION")
        self.assertFalse(agent.update_session.confirmations)
        self.assert_unchanged()
        draft = next(iter(agent.update_session.drafts.values()))
        self.assertEqual(agent.commit_update(draft.request_id,draft.fingerprint())["status"],"COMMITTED")
        self.assertEqual(self.connection.execute("SELECT purpose FROM invoices WHERE company_id='C001' AND invoice_no='F002'").fetchone()[0],"资料打印")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM invoice_audit").fetchone()[0],1)

    def test_permission_denial_precedes_target_mismatch(self):
        for company in ("C001","C002"):
            agent = self.agent([prepare(company)],user="U002")
            agent.ask("修改C001/F002用途为资料打印",allow_prepare=True)
            self.assertEqual(agent.write_receipt["status"],"DENIED")
            result = json.loads([m for m in agent.messages if m["role"]=="tool"][-1]["content"])
            self.assertEqual(result["evidence"],{})
            self.assertIsNone(result["data"])
            self.assertFalse(agent.update_session.drafts)
        self.assert_unchanged()

    def test_original_target_survives_partial_continuation(self):
        agent = self.agent([clarify(),prepare("C002")])
        agent.ask("修改C001/F002用途",allow_prepare=True)
        agent.ask("改为资料打印",continue_edit=True)
        self.assertEqual(agent.write_receipt["status"],"SCOPE_MISMATCH")
        self.assertFalse(agent.update_session.drafts)
        self.assert_unchanged()

    def test_conflicting_continuation_does_not_union_targets(self):
        agent = self.agent([clarify(),prepare("C002")])
        agent.ask("修改C001发票用途为资料打印",allow_prepare=True)
        agent.ask("C002/F002",continue_edit=True)
        self.assertEqual(agent.write_receipt["status"],"SCOPE_MISMATCH")
        self.assertFalse(agent.update_session.drafts)
        self.assert_unchanged()

    def test_conflicting_invoice_continuation_is_rejected(self):
        agent = self.agent([clarify(),prepare(invoice="F003")])
        agent.ask("修改C001/F002用途",allow_prepare=True)
        agent.ask("F003改为资料打印",continue_edit=True)
        self.assertEqual(agent.write_receipt["status"],"SCOPE_MISMATCH")
        self.assertFalse(agent.update_session.drafts)
        self.assert_unchanged()

    def test_explicit_new_edit_replaces_target_and_invalidates_old_draft(self):
        agent = self.agent([prepare(),prepare("C002")])
        agent.ask("修改C001/F002用途为资料打印",allow_prepare=True)
        old = next(iter(agent.update_session.drafts.values()))
        agent.ask("更正：修改C002/F002用途为资料打印",allow_prepare=True)
        self.assertEqual(agent.write_receipt["status"],"WAITING_CONFIRMATION")
        self.assertEqual(agent.commit_update(old.request_id,old.fingerprint())["status"],"DENIED")
        self.assertFalse(agent.update_session.confirmations)
        self.assert_unchanged()

    def test_model_must_not_invent_absent_target(self):
        agent = self.agent([prepare()])
        agent.ask("修改发票用途为资料打印",allow_prepare=True)
        self.assertEqual(agent.write_receipt["status"],"AMBIGUOUS")
        self.assertFalse(agent.update_session.drafts)
        self.assert_unchanged()

    def test_rule_business_date_must_match_user_month(self):
        raw = '{"company_id":"C001","rule_type":"purpose","business_date":"2026-09-01"}'
        result = handle_tool("get_applicable_rules",raw,"U001",self.db_path,expected_scope={"company_id":["C001"],"year":[2026],"month":[8]})
        self.assertEqual(result["status"],"SCOPE_MISMATCH")
        self.assertIsNone(result["data"])

    def test_rule_date_format_is_strict(self):
        for value in ("20260901","2026-9-01","2026-02-30","2026-09-01T00:00:00"):
            with self.subTest(date=value):
                raw = json.dumps({"company_id":"C001","rule_type":"purpose","business_date":value})
                self.assertEqual(handle_tool("get_applicable_rules",raw,"U001",self.db_path)["status"],"INVALID_ARGUMENTS")

    def test_rule_date_correct_and_distinct_rule_states(self):
        def get(date, user="U001"):
            return handle_tool("get_applicable_rules",json.dumps({"company_id":"C001","rule_type":"purpose","business_date":date}),user,self.db_path)
        self.assertEqual(get("2026-09-01")["data"]["version"],"2.0")
        self.assertEqual(get("2026-08-01")["status"],"NO_APPLICABLE_RULE")
        disable_rule(self.db_path,"R002","2.0",{"rule.manage"})
        self.assertEqual(get("2026-09-01")["status"],"NO_APPLICABLE_RULE")
        import_rules(self.db_path,[make_rule("R002","3.0","新版","C001","2026-09-01","ACTIVE","purpose",{"mode":"all","threshold_cents":0}),
                                  make_rule("R002","4.0","冲突版","C001","2026-09-01","ACTIVE","purpose",{"mode":"all","threshold_cents":0})],{"rule.manage"})
        self.assertEqual(get("2026-09-01")["status"],"RULE_CONFLICT")

    def test_partial_continuation_keeps_invoice_constraint(self):
        agent = self.agent([clarify(),prepare(invoice="F003")])
        agent.ask("F002用途改为资料打印",allow_prepare=True)
        agent.ask("C001",continue_edit=True)
        self.assertEqual(agent.write_receipt["status"],"SCOPE_MISMATCH")
        self.assertFalse(agent.update_session.drafts)
        self.assert_unchanged()

    def test_missing_company_or_invoice_is_not_invented(self):
        for text in ("C001发票用途改为资料打印","F002用途改为资料打印"):
            with self.subTest(request=text):
                agent = self.agent([prepare()])
                agent.ask(text,allow_prepare=True)
                self.assertEqual(agent.write_receipt["status"],"AMBIGUOUS")
                self.assertFalse(agent.update_session.drafts)
                self.assert_unchanged()

    def test_service_cannot_override_session_constraint(self):
        session = UpdateSession("U001")
        session.begin_turn("修改C001/F002用途为资料打印",True,expected_scope={"company_id":["C001"],"invoice_no":["F002"]})
        outcome = prepare_invoice_update(self.db_path,session,"C002","F002","purpose","资料打印",expected_scope={"company_id":["C002"],"invoice_no":["F002"]})
        self.assertEqual(outcome["status"],"SCOPE_MISMATCH")
        self.assertFalse(session.drafts)
        self.assert_unchanged()

    def test_handler_derives_target_from_trusted_source_without_loop(self):
        session = UpdateSession("U001")
        session.begin_turn("修改C001/F002用途为资料打印",True)
        raw = json.dumps({"company_id":"C002","invoice_no":"F002","field":"purpose","new_value":"资料打印"})
        outcome = handle_tool("prepare_invoice_update",raw,"U001",self.db_path,session)
        self.assertEqual(outcome["status"],"SCOPE_MISMATCH")
        self.assertFalse(session.drafts)
        self.assert_unchanged()

    def test_rule_month_mismatch_through_agent(self):
        reply = {"role":"assistant","tool_calls":[{"id":"r","type":"function","function":{"name":"get_applicable_rules",
                "arguments":'{"company_id":"C001","rule_type":"purpose","business_date":"2026-09-01"}'}}]}
        agent = self.agent([reply])
        answer = agent.ask("查询C001 2026 年 8 月适用用途规则")
        self.assertIn("范围不一致",answer)
        outcome = json.loads([m for m in agent.messages if m["role"]=="tool"][0]["content"])
        self.assertEqual(outcome["evidence"]["scope"]["month"],9)
        self.assertEqual(outcome["status"],"SCOPE_MISMATCH")
        self.assertIsNone(outcome["data"])
