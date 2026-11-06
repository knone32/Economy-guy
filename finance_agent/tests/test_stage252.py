"""自然交互和实际查询范围的反向回归。"""
import json
import unittest
from app.agent import Agent, scripted_model
from app.tool_registry import handle_tool
from app.stage2_schema import migrate
from app.rules import import_rules, SEED_RULES
from tests.helpers import DatabaseTestCaseMixin


def final(kind, text):
    return {"role":"assistant", "content":json.dumps({"kind":kind,"text":text},ensure_ascii=False)}


def query(company="C001", identifier="q"):
    return {"id":identifier,"type":"function","function":{"name":"get_finance_summary","arguments":json.dumps({"company_id":company,"year":2026,"month":9})}}


class Stage252Tests(DatabaseTestCaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        migrate(self.db_path)
        import_rules(self.db_path,SEED_RULES,{"rule.manage"})

    def agent(self, replies):
        return Agent("U001",self.db_path,scripted_model(replies),mode="mock")

    def test_greeting_retains_model_expression(self):
        agent = self.agent([final("general","你好！可以从财税概念或资料查询开始。")])
        answer = agent.ask("你好")
        self.assertIn("你好！可以从财税概念或资料查询开始。",answer)
        self.assertIn("不代表数据库执行",answer)
        self.assertEqual(agent.write_receipt["status"],"NOT_SUBMITTED")

    def test_concept_explanation_needs_no_database(self):
        agent = self.agent([final("general","价税合计是金额与税额的合计。")])
        self.assertIn("价税合计是金额与税额的合计",agent.ask("价税合计是什么意思"))
        self.assertFalse(any(m["role"]=="tool" for m in agent.messages))

    def test_fake_information_commit_remains_unverified(self):
        agent = self.agent([final("information","F002用途已修改成功并保存")])
        self.assertNotIn("修改成功",agent.ask("修改甲企业F002用途",allow_prepare=True))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM invoice_audit").fetchone()[0],0)

    def test_general_cannot_bypass_active_edit(self):
        agent = self.agent([final("general","F002已经保存")])
        self.assertNotIn("F002已经保存",agent.ask("修改F002",allow_prepare=True))
        self.assertEqual(agent.write_receipt["status"],"NOT_SUBMITTED")

    def test_wrong_company_scope_is_explicit_mismatch(self):
        agent = self.agent([{"role":"assistant","tool_calls":[query("C002")]},final("information","C001合计12667.24元")])
        answer = agent.ask("查询C001 2026-09的发票总额")
        self.assertIn("范围不一致",answer)
        self.assertIn("C002",answer)
        self.assertNotIn("12667.24",answer)
        outcome = json.loads([m for m in agent.messages if m["role"]=="tool"][0]["content"])
        self.assertEqual(outcome["status"],"SCOPE_MISMATCH")
        self.assertIsNone(outcome["data"])

    def test_actual_scope_shown_when_natural_alias_cannot_be_verified(self):
        agent = self.agent([{"role":"assistant","tool_calls":[query("C002")]},final("information","甲企业合计12667.24元")])
        # Stage 3B已识别官方“甲企业”；保留未识别自然语言别称的原验收目标。
        answer = agent.ask("查询甲方公司九月总额")
        self.assertIn("C002",answer)
        self.assertIn("2026-09",answer)
        self.assertIn("current_sqlite",answer)
        self.assertIn("1.0",answer)
        self.assertNotIn("甲企业合计",answer)

    def test_multiple_tools_preserve_individual_scopes(self):
        agent = self.agent([{"role":"assistant","tool_calls":[query("C001","a"),query("C002","b")]},final("information","两家总额合在一起")])
        answer = agent.ask("查询C001和C002 2026-09汇总")
        self.assertIn("C001",answer)
        self.assertIn("C002",answer)
        self.assertEqual(answer.count("2026-09"),2)
        self.assertEqual(answer.count("current_sqlite"),2)
        self.assertIn("9622.06",answer)
        self.assertIn("12667.24",answer)

    def test_tool_evidence_includes_scope_and_rule(self):
        for name, raw in (("get_finance_summary",'{"company_id":"C001","year":2026,"month":9}'),
                          ("check_missing_purpose",'{"company_id":"C002","year":2026,"month":9}'),
                          ("list_bank_transactions",'{"company_id":"C001","year":2026,"month":9}')):
            with self.subTest(name=name):
                outcome = handle_tool(name,raw,"U001",self.db_path)
                self.assertEqual(outcome["evidence"]["scope"]["month"],9)
                self.assertEqual(outcome["evidence"]["source"],"current_sqlite")
                self.assertTrue(outcome["evidence"]["rule"]["version"])

    def test_general_display_and_operation_receipt_have_separate_sources(self):
        agent = self.agent([final("general","你好")])
        agent.ask("你好")
        self.assertEqual(agent.last_response["category"],"general_unverified")
        self.assertEqual(agent.last_response["operation_receipt"]["status"],"NOT_SUBMITTED")

    def test_mismatched_month_is_rejected(self):
        agent = self.agent([{"role":"assistant","tool_calls":[query()]}])
        self.assertIn("范围不一致",agent.ask("查C001 2026年8月汇总"))
        result = json.loads([m for m in agent.messages if m["role"]=="tool"][0]["content"])
        self.assertEqual(result["evidence"]["scope"]["month"],9)
        self.assertEqual(result["evidence"]["requested_scope"]["month"],[8])

    def test_scope_conflict_does_not_leak_unauthorized_company(self):
        agent = Agent("U002",self.db_path,scripted_model([{"role":"assistant","tool_calls":[query("C002")]}]),mode="mock")
        agent.ask("查C001 2026-09")
        result = json.loads([m for m in agent.messages if m["role"]=="tool"][0]["content"])
        self.assertEqual(result["status"],"DENIED")
        self.assertEqual(result["evidence"],{})

    def test_detail_actual_date_is_scoped(self):
        outcome = handle_tool("get_invoice",'{"company_id":"C001","invoice_no":"F002"}',"U001",self.db_path)
        self.assertEqual(outcome["evidence"]["scope"]["year"],2026)
        self.assertEqual(outcome["evidence"]["scope"]["month"],9)
        outcome = handle_tool("get_invoice",'{"company_id":"C001","invoice_no":"F002"}',"U001",self.db_path,expected_scope={"month":[8]})
        self.assertEqual(outcome["status"],"SCOPE_MISMATCH")

    def test_bank_query_with_unseeded_rules_still_has_explicit_evidence(self):
        self.connection.execute("DELETE FROM rules")
        self.connection.commit()
        outcome = handle_tool("list_bank_transactions",'{"company_id":"C001","year":2026,"month":9}',"U001",self.db_path)
        self.assertEqual(outcome["status"],"SUCCESS")
        self.assertEqual(outcome["evidence"]["rule_status"],"NO_APPLICABLE_RULE")
        self.assertNotIn("rule",outcome["evidence"])
        self.assertEqual(len(outcome["data"]),12)
