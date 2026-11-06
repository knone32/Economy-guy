"""单轮粗计划/增量预算测试；模型为Mock，业务执行使用真实临时SQLite。"""
import json
import unittest
from app.agent import Agent, scripted_model
from app.scheduler import BudgetPolicy, TurnExecution
from app.stage2_schema import migrate as stage2
from app.stage3_schema import migrate as stage3
from app.rules import import_rules, SEED_RULES
from app.tasks import manage_task
from app.persistence import ManagementIntent
from tests.helpers import DatabaseTestCaseMixin


def tool(name, args, identifier="call"):
    return {"id":identifier,"type":"function","function":{"name":name,"arguments":json.dumps(args)}}


def reply(*calls):
    return {"role":"assistant","tool_calls":list(calls)}


def final(kind="information", **kwargs):
    return {"role":"assistant","content":json.dumps({"kind":kind,"text":"不能作为完成证据",**kwargs})}


def invoice(number):
    return {"company_id":"C001","invoice_no":f"F{number:03d}"}


def plan(count=4):
    return {"goal":"按用户指定顺序核对发票", "steps":[
        {"step_id":str(i),"action":"get_invoice","arguments":invoice(i),"depends_on":[str(i-1)] if i>1 else []}
        for i in range(1,count+1)],"stop_condition":"所列对象核对完成，或需要用户/确认/无权限时停止"}


class Stage3CTests(DatabaseTestCaseMixin,unittest.TestCase):
    def setUp(self):
        super().setUp()
        stage2(self.db_path)
        stage3(self.db_path)
        import_rules(self.db_path,SEED_RULES,{"rule.manage"})

    def agent(self,replies,**kwargs):
        return Agent("U001",self.db_path,scripted_model(replies),mode="mock",**kwargs)

    def test_fast_path_has_no_extra_planning_request(self):
        agent=self.agent([reply(tool("get_finance_summary",{"company_id":"C001","year":2026,"month":9})),final()])
        answer=agent.ask("C001 2026-09 汇总")
        self.assertIn("9622.06",answer)
        state=agent.last_response["execution"]
        self.assertIsNone(state["schedule"])
        self.assertEqual((state["model_requests"],state["actual_tool_calls"],state["extensions"]),(2,1,0))

    def test_progress_with_pending_dependencies_extends_three(self):
        agent=self.agent([reply(tool("set_schedule",plan())),*[reply(tool("get_invoice",invoice(i),str(i))) for i in range(1,5)]])
        answer=agent.ask("C001 按顺序核对发票 F001、F002、F003、F004、F005、F006、F007、F008、F009、F010")
        self.assertIn("F004",answer)
        state=agent.last_response["execution"]
        self.assertEqual((state["model_requests"],state["extensions"],state["block_limit"]),(5,1,6))
        self.assertEqual(state["stop_reason"],"COMPLETED")
        self.assertTrue(all(s["status"]=="DONE" for s in state["schedule"]["steps"]))

    def test_two_extensions_then_hard_nine_requests(self):
        agent=self.agent([reply(tool("set_schedule",plan(10))),*[reply(tool("get_invoice",invoice(i),str(i))) for i in range(1,10)]])
        answer=agent.ask("C001 按顺序核对发票 F001、F002、F003、F004、F005、F006、F007、F008、F009、F010")
        self.assertIn("上限",answer)
        state=agent.last_response["execution"]
        self.assertEqual((state["model_requests"],state["extensions"],state["actual_tool_calls"]),(9,2,9))
        self.assertEqual(state["stop_reason"],"MODEL_LIMIT")
        self.assertNotEqual(state["schedule"]["status"],"COMPLETED")
        self.assert_pairs(agent)

    def assert_pairs(self,agent):
        calls=[c["id"] for m in agent.messages for c in m.get("tool_calls",[])]
        results=[m["tool_call_id"] for m in agent.messages if m["role"]=="tool"]
        self.assertEqual(calls,results)

    def test_no_progress_cannot_extend(self):
        execution=TurnExecution(BudgetPolicy())
        execution.schedule={"goal":"x","steps":[{"step_id":"a","action":"get_invoice","arguments":invoice(1),"depends_on":[],"status":"PENDING"}],"status":"ACTIVE","stop_condition":"done","revision":0}
        for _ in range(3):
            self.assertTrue(execution.start_request())
        self.assertFalse(execution.start_request())
        self.assertEqual(execution.snapshot()["stop_reason"],"NO_PROGRESS")
        self.assertEqual(execution.snapshot()["extensions"],0)

    def test_repeat_is_blocked_without_another_handler_execution(self):
        request=tool("get_invoice",invoice(1))
        agent=self.agent([reply(request),reply(request)])
        answer=agent.ask("C001 F001")
        self.assertIn("NO_PROGRESS",answer)
        self.assertEqual(agent.last_response["execution"]["actual_tool_calls"],1)
        self.assertEqual(agent.last_response["execution"]["requested_tool_calls"],2)
        self.assert_pairs(agent)

    def test_multiple_calls_cap_twelve_pair_all(self):
        agent=self.agent([reply(*(tool("get_invoice",invoice(i),str(i)) for i in range(1,15)))])
        answer=agent.ask("C001 发票明细 F001、F002、F003、F004、F005、F006、F007、F008、F009、F010、F011、F012、F013、F014")
        self.assertIn("TOOL_LIMIT",answer)
        self.assertEqual(agent.last_response["execution"]["actual_tool_calls"],12)
        self.assertEqual(agent.last_response["execution"]["requested_tool_calls"],14)
        self.assert_pairs(agent)

    def test_dependency_violation_does_not_complete_step(self):
        agent=self.agent([reply(tool("set_schedule",plan())),reply(tool("get_invoice",invoice(2)))])
        self.assertIn("SCHEDULE_MISMATCH",agent.ask("C001 按顺序核对发票 F001、F002、F003、F004、F005、F006、F007、F008、F009、F010"))
        self.assertTrue(all(s["status"]=="PENDING" for s in agent.last_response["execution"]["schedule"]["steps"]))

    def test_denied_stops_and_keeps_first_reason_with_multiple_calls(self):
        agent=Agent("U002",self.db_path,scripted_model([reply(tool("get_invoice",{"company_id":"C002","invoice_no":"F002"},"denied"),tool("get_invoice",invoice(1),"later"))]),mode="mock")
        answer=agent.ask("查询发票")
        self.assertIn("DENIED",answer)
        self.assertEqual(agent.last_response["execution"]["actual_tool_calls"],1)
        self.assert_pairs(agent)

    def test_prepare_waits_and_never_extends_or_commits(self):
        agent=self.agent([reply(tool("prepare_invoice_update",{"company_id":"C001","invoice_no":"F002","field":"remark","new_value":"待确认"}))])
        agent.ask("C001 F002 remark 改为 待确认",allow_prepare=True)
        self.assertEqual(agent.last_response["execution"]["stop_reason"],"WAITING_CONFIRMATION")
        self.assertEqual(agent.last_response["execution"]["extensions"],0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM invoice_audit").fetchone()[0],0)
        self.assertNotEqual(self.connection.execute("SELECT remark FROM invoices WHERE company_id='C001' AND invoice_no='F002'").fetchone()[0],"待确认")

    def test_plan_cannot_grant_write_authority(self):
        proposal=plan(2)
        proposal["steps"][1].update(action="prepare_invoice_update",arguments={"company_id":"C001","invoice_no":"F002","field":"remark","new_value":"不能保存"})
        agent=self.agent([reply(tool("set_schedule",proposal))])
        self.assertIn("DENIED",agent.ask("C001 查询"))
        self.assertFalse(agent.update_session.drafts)

    def test_fake_model_completion_keeps_pending_steps(self):
        agent=self.agent([reply(tool("set_schedule",plan())),final()])
        agent.ask("C001 核对发票 F001、F002、F003、F004、F005、F006、F007、F008、F009、F010")
        schedule=agent.last_response["execution"]["schedule"]
        self.assertNotEqual(schedule["status"],"COMPLETED")
        self.assertTrue(all(s["status"]=="PENDING" for s in schedule["steps"]))

    def test_unplanned_progress_does_not_buy_unlimited_requests(self):
        agent=self.agent([reply(tool("get_invoice",invoice(i),str(i))) for i in range(1,6)])
        agent.ask("C001 核对发票 F001、F002、F003、F004、F005、F006、F007、F008、F009、F010")
        self.assertEqual(agent.last_response["execution"]["model_requests"],3)
        self.assertEqual(agent.last_response["execution"]["extensions"],0)

    def test_replan_once_only_and_cannot_erase_executed_fact(self):
        first=plan(5)
        second=plan(4)
        second["goal"]="明确重规划剩余核对"
        third=plan(3)
        third["goal"]="不允许的第二次重规划"
        agent=self.agent([reply(tool("set_schedule",first)),reply(tool("get_invoice",invoice(1))),reply(tool("set_schedule",second)),reply(tool("set_schedule",third))])
        self.assertIn("REPLAN_LIMIT",agent.ask("C001 核对发票 F001、F002、F003、F004、F005、F006、F007、F008、F009、F010"))
        state=agent.last_response["execution"]
        self.assertEqual(state["replans"],1)
        self.assertEqual(state["schedule"]["steps"][0]["status"],"DONE")

    def test_resume_task_schedule_uses_real_restoration_not_authorization(self):
        task=manage_task(self.db_path,"U001","C001","create",note="下次补齐用途",intent=ManagementIntent("U001","task","保存后续待办"))["data"]["task"]
        args={"company_id":"C001","action":"resume","task_id":task["task_id"],"year":2026,"month":9,"note":""}
        agent=self.agent([reply(tool("manage_task",args)),final()],management_confirmation=lambda proposal:proposal['proposal']==args)
        agent.ask("恢复 C001 任务",management="task",management_action="resume")
        state=agent.last_response["execution"]
        self.assertIsNotNone(state["schedule"])
        self.assertEqual(state["stop_reason"],"COMPLETED")
        self.assertFalse(agent.update_session.allow_prepare)
        self.assertFalse(agent.update_session.drafts)

    def test_trace_budget_reasons_and_mode(self):
        path=self.db_path.parent/"budget.jsonl"
        agent=self.agent([reply(tool("set_schedule",plan())),*[reply(tool("get_invoice",invoice(i),str(i))) for i in range(1,5)]],trace_path=path)
        agent.ask("C001 核对发票 F001、F002、F003、F004、F005、F006、F007、F008、F009、F010")
        events=[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        extension=next(e for e in events if e["event"]=="budget.extended")
        self.assertEqual(extension["mode"],"mock")
        self.assertIn("reason",extension["data"])
        self.assertEqual(events[-1]["data"]["execution"]["stop_reason"],"COMPLETED")

    def test_schedule_schema_rejects_forged_status_unknown_tools_and_cycles(self):
        for variant in ("status","hidden","cycle","type"):
            proposal=plan()
            if variant=="status":
                proposal["steps"][0]["status"]="DONE"
            elif variant=="hidden":
                proposal["steps"][0]["action"]="add"
            elif variant=="cycle":
                proposal["steps"][0]["depends_on"]=["4"]
            else:
                proposal["steps"][0]["arguments"]["invoice_no"]=True
            with self.subTest(variant=variant):
                agent=self.agent([reply(tool("set_schedule",proposal))])
                agent.ask("C001 核对发票 F001、F002、F003、F004、F005、F006、F007、F008、F009、F010")
                self.assertIsNone(agent.last_response["execution"]["schedule"])
                self.assertEqual(agent.last_response["execution"]["extensions"],0)
                self.assertFalse(agent.update_session.drafts)

    def test_permissions_revoked_before_soft_limit_do_not_renew(self):
        answers=iter([reply(tool("set_schedule",plan())),reply(tool("get_invoice",invoice(1))),reply(tool("get_invoice",invoice(2)))])
        count=0
        def model(messages,tools):
            nonlocal count
            count+=1
            if count==3:
                self.connection.execute("UPDATE permissions SET can_read=0 WHERE user_id='U001' AND company_id='C001'")
                self.connection.commit()
            return next(answers)
        agent=Agent("U001",self.db_path,model,mode="mock")
        agent.ask("C001 核对发票 F001、F002、F003、F004、F005、F006、F007、F008、F009、F010")
        self.assertEqual(agent.last_response["execution"]["extensions"],0)
        self.assertEqual(agent.last_response["execution"]["stop_reason"],"DENIED")

    def test_soft_limit_rechecks_permission_after_real_progress(self):
        from app.tool_registry import remaining_work_allowed
        execution=TurnExecution(BudgetPolicy(),can_continue=lambda steps:remaining_work_allowed(self.db_path,"U001",steps,None,None))
        execution.install(**plan())
        for i in range(1,4):
            self.assertTrue(execution.start_request())
            execution.observe("get_invoice",invoice(i),{"ok":True,"status":"SUCCESS","data":None,"evidence":{"source":"test_execution"}})
        self.connection.execute("UPDATE permissions SET can_read=0 WHERE user_id='U001' AND company_id='C001'")
        self.connection.commit()
        self.assertFalse(execution.start_request())
        self.assertEqual(execution.snapshot()["stop_reason"],"NO_LEGAL_WORK")
        self.assertEqual(execution.snapshot()["extensions"],0)

    def test_last_model_request_prepare_only_waits(self):
        args={"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"实际用户内容"}
        agent=self.agent([reply(tool("prepare_invoice_update",args),tool("get_invoice",invoice(2),"skipped"))],max_requests=1)
        agent.ask("C001 F002 purpose 改为 实际用户内容",allow_prepare=True)
        self.assertEqual(agent.write_receipt["status"],"WAITING_CONFIRMATION")
        self.assertEqual(agent.last_response["execution"]["actual_tool_calls"],1)
        self.assert_pairs(agent)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM invoice_audit").fetchone()[0],0)

    def test_scheduled_prepare_step_is_waiting_not_done(self):
        proposal=plan(2)
        query={"company_id":"C001","year":2026,"month":9}
        proposal["steps"][0].update(action="get_finance_summary",arguments=query)
        args={"company_id":"C001","invoice_no":"F002","field":"remark","new_value":"待确认"}
        proposal["steps"][1].update(action="prepare_invoice_update",arguments=args)
        agent=self.agent([reply(tool("set_schedule",proposal)),reply(tool("get_finance_summary",query)),reply(tool("prepare_invoice_update",args))])
        agent.ask("先核对 C001 2026-09 汇总，再把 C001 F002 remark 改为 待确认",allow_prepare=True)
        self.assertEqual(len(agent.update_session.drafts),1)
        self.assertEqual(agent.last_response["execution"]["schedule"]["steps"][1]["status"],"WAITING_USER")
        self.assertEqual(agent.last_response["execution"]["schedule"]["status"],"WAITING_USER")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM invoice_audit").fetchone()[0],0)

    def test_new_user_message_has_new_budget_and_no_old_schedule(self):
        agent=self.agent([reply(tool("get_invoice",invoice(1))),final(),reply(tool("get_invoice",invoice(1))),final()])
        agent.ask("C001 F001")
        agent.ask("再次查 C001 F001")
        state=agent.last_response["execution"]
        self.assertEqual((state["model_requests"],state["actual_tool_calls"],state["extensions"]),(2,1,0))
        self.assertIsNone(state["schedule"])

    def test_budget_config_may_reduce_but_not_bypass_hard_limits(self):
        for kwargs in ({"max_requests":10},{"max_tools":13},{"max_extensions":3},{"max_replans":2},{"block_requests":True}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                BudgetPolicy(**kwargs)
        agent=self.agent([reply(tool("set_schedule",plan())),reply(tool("get_invoice",invoice(1))),reply(tool("get_invoice",invoice(2)))],max_extensions=0)
        agent.ask("C001 核对发票 F001、F002、F003、F004、F005、F006、F007、F008、F009、F010")
        self.assertEqual(agent.last_response["execution"]["stop_reason"],"EXTENSION_LIMIT")

    def test_api_failure_counts_request_but_never_finishes_plan(self):
        count=0
        def model(messages,tools):
            nonlocal count
            count+=1
            if count==1:
                return reply(tool("set_schedule",plan()))
            raise RuntimeError("provider secret")
        agent=Agent("U001",self.db_path,model,mode="mock")
        answer=agent.ask("C001 核对发票 F001、F002、F003、F004、F005、F006、F007、F008、F009、F010")
        self.assertNotIn("provider secret",answer)
        self.assertEqual(agent.last_response["execution"]["model_requests"],2)
        self.assertEqual(agent.last_response["execution"]["stop_reason"],"API_OR_RESPONSE_ERROR")
        self.assertTrue(all(s["status"]=="PENDING" for s in agent.last_response["execution"]["schedule"]["steps"]))


if __name__=="__main__":
    unittest.main()
