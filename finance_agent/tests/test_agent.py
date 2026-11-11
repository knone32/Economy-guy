import json
from pathlib import Path
import unittest
from unittest.mock import patch
from app.agent import Agent, handle_tool, scripted_model, redact
from app.importer import initialize_database
from tests.helpers import DatabaseTestCaseMixin, EXCEL


def call(name="get_finance_summary", arguments=None, identifier="a"):
    return {"id": identifier, "type": "function", "function": {"name": name, "arguments": arguments if arguments is not None else '{"company_id":"C001","year":2026,"month":9}'}}


class AgentTests(DatabaseTestCaseMixin, unittest.TestCase):
    def agent(self, calls, **kwargs):
        return Agent("U001", self.db_path, scripted_model([
            {"role": "assistant", "tool_calls": calls},
            {"role": "assistant", "content": json.dumps({"kind":"information", "text":"完成"})}]), mode="mock", **kwargs)

    def test_multiple_tools_and_multiturn(self):
        agent = self.agent([call(), call("list_invoices", identifier="b")])
        self.assertIn("9622.06", agent.ask("查询甲企业2026年9月"))
        results = [json.loads(m["content"]) for m in agent.messages if m["role"] == "tool"]
        self.assertEqual(results[0]["data"]["invoice_total"], "9622.06")
        self.assertEqual(len(results[1]["data"]), 10)
        agent.model = scripted_model([{"role":"assistant", "content":json.dumps({"kind":"clarification", "text":"请提供月份", "missing_fields":["month"]})}])
        self.assertEqual(agent.ask("另一个问题"), "请提供月份")

    def test_errors_pair_all_results_and_stop(self):
        for arguments in ('{}', '{', '{"company_id":"C001","year":true,"month":9}'):
            agent = self.agent([call(arguments=arguments), call(identifier="b")])
            self.assertIn("停止", agent.ask("查询C001和C002 2026-09"))
            self.assertEqual(len([m for m in agent.messages if m["role"] == "tool"]), 2)

    def test_denied_no_identity_override(self):
        result = handle_tool("get_finance_summary", '{"company_id":"C002","year":2026,"month":9}', "U002", self.db_path)
        self.assertEqual(result["status"], "DENIED")
        result = handle_tool("get_finance_summary", '{"company_id":"C002","year":2026,"month":9,"user_id":"U001"}', "U002", self.db_path)
        self.assertEqual(result["status"], "INVALID_ARGUMENTS")

    def test_empty_and_missing_database(self):
        raw = '{"company_id":"C001","year":2026,"month":7}'
        result = handle_tool("get_finance_summary", raw, "U001", self.db_path)
        self.assertEqual(result["status"], "NO_DATA")
        self.assertEqual(result["data"]["invoice_total"], "0.00")
        self.assertEqual(result["data"]["bank_income_total"], "0.00")
        self.assertEqual(result["data"]["bank_expense_total"], "0.00")
        self.assertTrue(result["ok"])
        missing = self.db_path.parent / "missing.db"
        self.assertEqual(handle_tool("get_finance_summary", raw, "U001", missing)["status"], "ERROR")
        self.assertFalse(missing.exists())

    def test_api_failure_and_limits(self):
        def failed(messages, tools):
            raise RuntimeError("sensitive provider details")
        self.assertIn("失败", Agent("U001", self.db_path, failed).ask("查询"))
        # 不用重复请求测试硬限：重复调用现在由独立的NO_PROGRESS保护提前停止。
        unique_calls = [call("get_invoice",json.dumps({"company_id":"C001","invoice_no":f"F{i:03d}"}),str(i)) for i in range(1,6)]
        replies = iter({"role":"assistant", "tool_calls":[item]} for item in unique_calls)
        agent = Agent("U001", self.db_path, lambda m,t: next(replies), max_requests=2)
        self.assertIn("上限", agent.ask("查询C001的F001、F002、F003、F004、F005"))
        self.assertEqual(agent.last_response["execution"]["model_requests"],2)
        agent = self.agent(unique_calls, max_tools=2)
        agent.ask("查询C001的F001、F002、F003、F004、F005")
        results = [json.loads(m["content"]) for m in agent.messages if m["role"] == "tool"]
        self.assertEqual(len(results), 5)
        self.assertEqual(sum(r["status"] == "SUCCESS" for r in results), 2)
        self.assertEqual(agent.last_response["execution"]["stop_reason"],"TOOL_LIMIT")

    def test_summary_counts_and_rule_evidence(self):
        result = handle_tool("get_finance_summary", call()["function"]["arguments"], "U001", self.db_path)
        self.assertEqual(set(result), {"ok", "status", "data", "evidence", "error"})
        self.assertEqual(result["data"], {"invoice_total":"9622.06", "bank_income_total":"13000.50", "bank_expense_total":"7180.74", "invoice_count":10, "bank_income_count":4, "bank_expense_count":8})
        self.assertEqual(result["evidence"]["rule"]["version"], "1.0")

    def test_missing_month_model_clarifies_then_uses_context(self):
        agent = Agent("U001", self.db_path, scripted_model([
            {"role":"assistant", "content":json.dumps({"kind":"clarification", "text":"请提供年份和月份", "missing_fields":["year","month"]})},
            {"role":"assistant", "tool_calls":[call("get_finance_summary")]},
            {"role":"assistant", "content":json.dumps({"kind":"information", "text":"发票总额9622.06元"})}]), mode="mock")
        self.assertIn("月份", agent.ask("查询甲企业汇总"))
        self.assertFalse(any(m["role"] == "tool" for m in agent.messages))
        self.assertIn("9622.06", agent.ask("2026年9月"))

    def test_plain_finance_summary_asks_for_period_before_model_dispatch(self):
        from app.stage3_schema import migrate

        migrate(self.db_path)
        request = "查询甲企业的发票价税合计 银行收入和支出 并且说明统计依据"
        agent = Agent("U001", self.db_path, scripted_model([
            {"role": "assistant", "tool_calls": [call("manage_preference",
                '{"company_id":"C001","action":"get","key":"查询月份","value":""}', "preference")]},
            {"role": "assistant", "tool_calls": [call("clarification",
                '{"missing_fields":["year","month"]}', "invalid-tool")]},
        ]), mode="mock")
        answer = agent.ask(request)
        response = agent.last_response
        self.assertEqual(response["execution"]["stop_reason"], "WAITING_USER",
                         [(name, result["status"]) for name, result in response["tool_results"]])
        self.assertEqual(answer, "请补充年份、月份。")
        self.assertEqual(response["execution"]["model_requests"], 0)
        self.assertEqual(response["tool_results"], ())
        self.assertEqual(agent.pending_intent["request"], request)
        self.assertEqual(agent.pending_intent["scope"]["company_id"], ["C001"])

        agent.model = scripted_model([
            {"role": "assistant", "tool_calls": [call()]},
            {"role": "assistant", "content": json.dumps({"kind": "explanation", "text": "[[result]]"})},
        ])
        answer = agent.ask("2026年9月")
        self.assertIn(request, agent.last_user_request)
        self.assert_summary_result(agent, answer)
        self.assertIn("交易日期", answer)
        self.assertEqual(agent.last_response["fulfillment"]["status"], "VERIFIED_GOALS")

    def assert_summary_result(self, agent, answer):
        (name, result), = agent.last_response["tool_results"]
        self.assertEqual((name, result["status"]), ("get_finance_summary", "SUCCESS"))
        self.assertEqual(result["evidence"]["scope"], {"company_id": "C001", "year": 2026, "month": 9})
        self.assertEqual((result["evidence"]["rule"]["id"], result["evidence"]["rule"]["version"]),
                         ("R001", "1.0"))
        for text in ("9622.06", "13000.50", "7180.74", "R001"):
            self.assertIn(text, answer)

    def test_plain_finance_summary_respects_selected_period_and_company_acl(self):
        request = "查询甲企业的发票价税合计 银行收入和支出 并且说明统计依据"
        agent = self.agent([call()])
        self.assert_summary_result(agent, agent.ask(request, read_workspace=("C001", 2026, 9)))
        denied = Agent("U002", self.db_path, scripted_model([
            {"role": "assistant", "tool_calls": [call(arguments='{"company_id":"C002","year":2026,"month":9}')]}
        ]), mode="mock")
        self.assertIn("当前账号没有权限", denied.ask("查询乙企业2026年9月的发票价税合计、银行收入和支出"))
        self.assertEqual(denied.last_response["execution"]["stop_reason"], "DENIED")
        self.assertEqual(denied.last_response["tool_results"][0][1]["status"], "DENIED")
        undated = Agent("U002", self.db_path, scripted_model([]), mode="mock")
        undated.ask(request.replace("甲企业", "乙企业"))
        self.assertEqual(undated.last_response["execution"]["stop_reason"], "DENIED")
        self.assertEqual(undated.last_response["execution"]["model_requests"], 0)
        self.assertEqual(undated.last_response["tool_results"], ())

    def test_summary_explanation_keeps_current_amounts_and_rule(self):
        for extra, expected in (("", "VERIFIED_GOALS"), ("，再列出银行流水明细", "PARTIAL_RESULT")):
            with self.subTest(extra=extra):
                agent = Agent("U001", self.db_path, scripted_model([
                    {"role": "assistant", "tool_calls": [call()]},
                    {"role": "assistant", "content": json.dumps({
                        "kind": "explanation", "text": "[[result]]\n[[boundary]]",
                    })},
                ]), mode="mock")
                answer = agent.ask(
                    "查询甲企业的发票价税合计、银行收入和支出，并且说明统计依据" + extra,
                    read_workspace=("C001", 2026, 9),
                )
                self.assert_summary_result(agent, answer)
                response = agent.last_response
                self.assertEqual(response["chat_notice"], answer)
                self.assertEqual(response["fulfillment"]["status"], expected)
                self.assertEqual(response["execution"]["model_requests"], 2)
                self.assertIn("交易日期", answer)
                self.assertNotIn("[[", answer)
                self.assertEqual("其他要求尚未核实" in answer, bool(extra))

    def test_summary_explanation_without_rule_keeps_the_amounts(self):
        def without_rule(*args, **kwargs):
            result = handle_tool(*args, **kwargs)
            result["evidence"].pop("rule")
            return result

        agent = Agent("U001", self.db_path, scripted_model([
            {"role": "assistant", "tool_calls": [call()]},
            {"role": "assistant", "content": json.dumps({"kind": "explanation", "text": "[[result]]"})},
        ]), mode="mock")
        with patch("app.agent.handle_tool", side_effect=without_rule):
            answer = agent.ask("查询甲企业2026年9月的发票价税合计、银行收入和支出，并且说明统计依据")
        self.assertEqual(agent.last_response["chat_notice"], answer)
        self.assertEqual(agent.last_response["fulfillment"]["status"], "PARTIAL_RESULT")
        for amount in ("9622.06", "13000.50", "7180.74"):
            self.assertIn(amount, answer)
        self.assertIn("统计依据尚未核实", answer)
        self.assertNotIn("R001", answer)

    def test_summary_continues_after_period_and_requeries_a_corrected_month(self):
        august = call(arguments='{"company_id":"C001","year":2026,"month":8}')
        explanation = {"role": "assistant", "content": '{"kind":"explanation","text":"依据统计口径。"}'}
        agent = Agent("U001", self.db_path, scripted_model([
            {"role": "assistant", "tool_calls": [august]}, explanation,
            {"role": "assistant", "tool_calls": [call()]},
            {"role": "assistant", "content": "未按约定返回 JSON"},
        ]), mode="mock")
        self.assertIn("月份", agent.ask("查询甲企业的发票价税合计、银行收入和支出，并说明统计依据"))
        self.assertIn("2026-08", agent.ask("2026年8月"))
        self.assertEqual(agent.last_response["fulfillment"]["status"], "VERIFIED_GOALS")
        self.assert_summary_result(agent, agent.ask("打错了，改查九月份"))
        self.assertEqual(agent.last_response["fulfillment"]["status"], "VERIFIED_GOALS")
        self.assertIn("2026-09", agent.last_response["chat_notice"])
        self.assertIn("交易日期", agent.last_response["chat_notice"])

    def test_summary_explanation_before_read_gets_one_retrieval_opportunity(self):
        explanation = {"role": "assistant", "content": '{"kind":"explanation","text":"依据统计口径。"}'}
        agent = Agent("U001", self.db_path, scripted_model([
            explanation, {"role": "assistant", "tool_calls": [call()]}, explanation,
        ]), mode="mock")
        self.assert_summary_result(agent, agent.ask(
            "查询甲企业2026年9月的发票价税合计、银行收入和支出，并说明统计依据"))
        self.assertEqual(agent.last_response["execution"]["model_requests"], 3)

    def test_invoice_proposal_and_confirmed_task_survive_current_reads(self):
        from app.invoice_batch import run_invoice_batch
        from app.rules import import_rules, SEED_RULES
        from app.stage2_schema import migrate as stage2
        from app.stage3_schema import migrate as stage3

        stage2(self.db_path)
        stage3(self.db_path)
        import_rules(self.db_path, SEED_RULES, {"rule.manage"})
        invoice = call("get_invoice", '{"company_id":"C001","invoice_no":"F002"}')
        final = {"role": "assistant", "content": '{"kind":"information","text":"请核对结果。"}'}
        check = call("check_missing_purpose")
        agent = Agent("U001", self.db_path, scripted_model([
            {"role": "assistant", "tool_calls": [check]}, final,
        ]), mode="mock")
        self.assertIn("R002 v2.0", agent.ask("检查甲企业2026年9月哪些发票缺少必填用途，并说明依据"))
        self.assertEqual(agent.last_response["tool_results"][0][1]["data"]["count"], 5)

        replies = iter([None, True])

        def propose(messages, tools):
            if next(replies) is None:
                return {"role": "assistant", "tool_calls": [invoice]}
            detail = json.loads(next(m["content"] for m in reversed(messages) if m["role"] == "tool"))
            candidate = dict(selection_id=detail["data"]["selection_id"], field="purpose",
                             new_value="资料打印", mode="item", excluded_invoice_ids=[])
            return {"role": "assistant", "tool_calls": [call("propose_invoice_changes", json.dumps(candidate), "p")]}

        agent.model = propose
        request = "把甲企业F002的用途补成资料打印"
        agent.ask(request)
        self.assertEqual(agent.last_response["execution"]["stop_reason"], "WAITING_CONFIRMATION")
        self.assertEqual(self.connection.execute("select count(*) from invoice_audit").fetchone()[0], 0)
        proposal = agent.last_response["invoice_change"]
        status, _ = run_invoice_batch(agent, request, proposal, approve_item=lambda _: "confirm",
                                      approve_batch=lambda *_: self.fail("expected an item confirmation"),
                                      checkpoint=lambda _: None)
        self.assertEqual(status, "COMPLETED")
        self.assertTrue(agent.write_receipt["readback_verified"])
        self.assertEqual(self.connection.execute("select count(*) from invoice_audit").fetchone()[0], 1)

        agent.model = scripted_model([{"role": "assistant", "tool_calls": [invoice]},
                                      {"role": "assistant", "content": "未按约定返回 JSON"}])
        self.assertIn("资料打印", agent.ask("查看甲企业F002当前用途"))
        self.assertEqual(agent.last_response["fulfillment"]["status"], "VERIFIED_GOALS")

        task = dict(company_id="C001", year=2026, month=9, action="create", task_id="", note="")
        agent.model = scripted_model([{"role": "assistant", "tool_calls": [call("manage_task", json.dumps(task))]}, final])
        agent.management_confirmation = lambda proposal: proposal["domain"] == "task"
        agent.ask("把剩余缺用途发票留作待办", task_note_from_request=True)
        outcome = agent.last_response["tool_results"][0][1]
        self.assertEqual(outcome["status"], "SUCCESS", outcome["error"])
        task_id = outcome["data"]["task"]["task_id"]

        resumed = self.agent([call("list_tasks", '{"company_id":"C001"}', "tasks"), check])
        resumed.ask("查看甲企业2026年9月的待办及当前用途缺项")
        task_result, checked = (result for _, result in resumed.last_response["tool_results"])
        self.assertEqual(task_result["data"][0]["task_id"], task_id)
        self.assertEqual(checked["data"]["count"], 4)

    def test_tool_dispatch_denial_does_not_report_account_acl(self):
        agent = self.agent([call("clarification", '{"missing_fields":["year","month"]}')])
        agent.ask("查询甲企业2026年9月的发票价税合计、银行收入和支出")
        response = agent.last_response
        self.assertEqual(response["execution"]["stop_reason"], "DENIED")
        self.assertEqual(response["tool_results"][0][1]["status"], "DENIED")
        self.assertIn("本轮不可用的操作", response["chat_notice"])
        self.assertNotIn("账号没有权限", response["chat_notice"])

    def test_invalid_invoice_final_uses_exact_detail_coverage(self):
        for prompt, complete in (
            ("查看甲企业f002当前用途", True),
            ("查看甲企业F002当前用途，并列出该企业的银行流水", False),
        ):
            with self.subTest(prompt=prompt):
                agent = Agent("U001", self.db_path, scripted_model([
                    {"role": "assistant", "tool_calls": [call("get_invoice",
                        '{"company_id":"C001","invoice_no":"F002"}')]},
                    {"role": "assistant", "content": "模型未按约定返回 JSON"},
                ]), mode="mock")
                agent.ask(prompt)
                response = agent.last_response
                self.assertEqual(response["execution"]["stop_reason"], "EVIDENCE_RETURNED")
                self.assertEqual(response["single_query_verified"], complete)
                self.assertEqual(response["fulfillment"]["status"] == "VERIFIED_GOALS", complete)
                self.assertIn("F002", response["chat_notice"])
                self.assertIn("未填写", response["chat_notice"])
                self.assertEqual("还无法核实是否回答了全部问题" in response["chat_notice"], not complete)

    def test_bad_excel_row_never_publishes(self):
        from openpyxl import load_workbook
        workbook = load_workbook(EXCEL)
        workbook["发票"]["F6"] = None
        source = self.db_path.parent / "bad-row.xlsx"
        workbook.save(source)
        workbook.close()
        target = self.db_path.parent / "bad-row.db"
        before = self.db_path.read_bytes()
        with self.assertRaises(ValueError):
            initialize_database(source, target)
        self.assertFalse(target.exists())
        self.assertEqual(before, self.db_path.read_bytes())

    def test_trace_redacts_and_marks_mode(self):
        path = self.db_path.parent / "trace.jsonl"
        agent = self.agent([call()], trace_path=path)
        agent.ask("API_KEY=example-secret")
        data = path.read_text(encoding="utf-8")
        self.assertNotIn("example-secret", data)
        self.assertIn('"mode": "mock"', data)

    def test_import_failure_preserves_old_and_no_partial_new(self):
        before = self.db_path.read_bytes()
        broken = self.db_path.parent / "broken.xlsx"
        broken.write_bytes(b"invalid excel")
        with self.assertRaises(FileExistsError):
            initialize_database(broken, self.db_path)
        self.assertEqual(before, self.db_path.read_bytes())
        target = self.db_path.parent / "new.db"
        with self.assertRaises(Exception):
            initialize_database(broken, target)
        self.assertFalse(target.exists())
