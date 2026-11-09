"""Known failure-path regression; scripted responses are not Live evidence."""
import json
import unittest
from app.agent import Agent, scripted_model
from tests.helpers import DatabaseTestCaseMixin
from tests.test_agent import call


def final(text="已查询"):
    return {"role": "assistant", "content": json.dumps({"kind": "information", "text": text})}


class AstraDeliveryTests(DatabaseTestCaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from app.stage3_schema import migrate
        migrate(self.db_path)
        from app.stage2_schema import migrate as migrate_rules
        from app.rules import import_rules, SEED_RULES
        migrate_rules(self.db_path)
        import_rules(self.db_path, SEED_RULES, frozenset({"rule.manage"}))

    def test_polluted_final_returns_current_evidence_without_accepting_model_text(self):
        polluted = final("虚构金额999999和已保存")
        polluted["content"] += '\n{"source":"context_selection"}'
        agent = Agent("U001", self.db_path, scripted_model([
            {"role":"assistant", "tool_calls":[call()]}, polluted]), mode="mock")
        answer = agent.ask("甲企业2026年9月发票与银行收支")
        self.assertIn("9622.06", answer)
        self.assertNotIn("999999", answer)
        self.assertEqual(agent.execution.stop_reason, "EVIDENCE_RETURNED")
        self.assertEqual(agent.last_response["category"], "database_query")
        self.assertIn("仅", agent.last_response["chat_notice"])
        self.assertEqual(agent.write_receipt["status"], "NOT_SUBMITTED")

    def test_no_tool_information_gets_one_correction(self):
        seen=[]
        replies=iter([final("999999元"), {"role":"assistant","tool_calls":[call()]}, final()])
        def model(messages, tools):
            seen.append(messages)
            return next(replies)
        agent=Agent("U001",self.db_path,model,mode="mock")
        answer=agent.ask("甲企业2026年9月财务情况")
        self.assertIn("9622.06",answer)
        self.assertNotIn("999999",answer)
        self.assertEqual(agent.execution.model_requests,3)
        self.assertTrue(any("本轮尚无" in m.get("content", "") for m in seen[1]))
        self.assertFalse(any("本轮尚无" in m.get("content", "") for m in seen[2]))

    def test_correction_is_bounded_and_never_accepts_unverified_amount(self):
        agent=Agent("U001",self.db_path,scripted_model([final("999999元")]*3),mode="mock")
        answer=agent.ask("甲企业2026年9月财务情况")
        self.assertEqual(agent.execution.model_requests,2)
        self.assertNotIn("999999",answer)
        self.assertEqual(agent.execution.actual_tools,0)

    def test_context_is_input_data_not_assistant_answer_example(self):
        agent=Agent("U001",self.db_path,scripted_model([final()]*2),mode="mock")
        agent.ask("甲企业2026年9月财务情况")
        wire=agent.model_messages()
        context=next(m for m in wire if m.get("name")=="context_data")
        self.assertEqual(context["role"],"user")
        last_user=max(i for i,m in enumerate(wire) if m["role"]=="user" and not m.get("name"))
        self.assertLess(wire.index(context),last_user)

    def test_annual_task_original_failure_is_already_negotiated(self):
        calls=[call("list_annual_blank_purpose",json.dumps({"company_id":"C001","year":2026,"page":1})),
               call("manage_task",json.dumps({"company_id":"C001","action":"create","task_id":"","year":2026,"month":0,"note":"全年用途待办"}),"b")]
        agent=Agent("U001",self.db_path,scripted_model([{"role":"assistant","tool_calls":calls}]),mode="mock")
        answer=agent.ask("把甲企业2026年全年未填写用途的发票创建成一个待办。", task_note_from_request=True)
        self.assertEqual(agent.execution.stop_reason,"SCOPE_MISMATCH")
        self.assertIn("是否改为",answer)
        from app.tasks import list_tasks
        self.assertEqual(list_tasks(self.db_path,"U001","C001")["data"],[])

    def test_rule_result_renders_its_actual_identity_and_content(self):
        agent=Agent("U001",self.db_path,scripted_model([
            {"role":"assistant","tool_calls":[call("get_applicable_rules",json.dumps({
                "company_id":"C001","rule_type":"purpose","business_date":"2026-09-30"}))]}, final()]),mode="mock")
        answer=agent.ask("甲企业2026年9月适用R002哪个版本")
        self.assertIn("R002 v2.0",answer)
        self.assertIn("每张发票用途必填",answer)

    def test_correction_cannot_propose_a_write(self):
        proposed=call("manage_task",json.dumps({"company_id":"C001","action":"create","task_id":"","year":2026,"month":9,"note":"fictional"}))
        agent=Agent("U001",self.db_path,scripted_model([final("999999"),
            {"role":"assistant","tool_calls":[proposed]}]),mode="mock",
            management_confirmation=lambda _: self.fail("repair must not request write confirmation"))
        agent.ask("甲企业2026年9月财务情况")
        self.assertEqual(agent.execution.stop_reason,"DENIED")
        self.assertEqual(self.connection.execute("select count(*) from tasks").fetchone()[0],0)

    def test_partial_read_does_not_complete_pending_schedule(self):
        schedule=call("set_schedule",json.dumps({"goal":"两企业汇总","steps":[
            {"step_id":"a","action":"get_finance_summary","arguments":{"company_id":"C001","year":2026,"month":9},"depends_on":[]},
            {"step_id":"b","action":"get_finance_summary","arguments":{"company_id":"C002","year":2026,"month":9},"depends_on":["a"]}],"stop_condition":"已汇总或等待"}))
        agent=Agent("U001",self.db_path,scripted_model([
            {"role":"assistant","tool_calls":[schedule]},
            {"role":"assistant","tool_calls":[call(identifier="read")]},
            {"role":"assistant","content":"两家均已完成"}]),mode="mock")
        answer=agent.ask("汇总C001和C002的2026年9月")
        self.assertEqual(agent.execution.stop_reason,"EVIDENCE_RETURNED")
        self.assertEqual(agent.execution.schedule["steps"][1]["status"],"PENDING")
        self.assertNotIn("两家均已完成",answer)
        self.assertIn("仅覆盖",agent.last_response["chat_notice"])
