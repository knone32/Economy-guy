import json
from pathlib import Path
import unittest
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
