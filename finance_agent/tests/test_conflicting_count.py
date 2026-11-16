"""Verified query conclusions must agree with the evidence shown in the workbench."""
import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from textual.widgets import Select

from app.agent import Agent, scripted_model
from app.cli_workspaces import import_workspace
from app.model_config import DEFAULT_TEMPLATE
from app.tui import AgentWorkspace, ChatLog
from tests import test_tui_p0


COUNT_PROMPT = "分析一下 C001 2026年9月的发票数据，告诉我总共有多少张，并说明数据来源。"
COUNT_SQL = ("SELECT COUNT(*) AS invoice_count FROM invoices "
             "WHERE company_id = 'C001' AND invoice_date LIKE '2026-09%'")
FALSE_CLAIM = "C001 在 2026 年 9 月有 999 张发票。"


def final(text):
    return {"role": "assistant", "content": json.dumps({"kind": "information", "text": text}, ensure_ascii=False)}


class ConflictingCountTests(unittest.IsolatedAsyncioTestCase):
    await_state = test_tui_p0.P0Test.await_state

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / "workbook.db"
        import_workspace(test_tui_p0.FIXTURE, self.path)

    def sqlite_rows(self, sql):
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as db:
            return db.execute(sql).fetchall()

    def ask(self, text, tool, arguments, reply, user="U001"):
        agent = Agent(user, self.path, scripted_model([test_tui_p0.tool(tool, arguments), final(reply)]),
                      mode="mock", trace_path=self.directory / "agent.jsonl")
        answer = agent.ask(text)
        self.assertEqual(agent.last_response["tool_results"][0][0], tool)
        return agent, answer

    async def test_workbench_count_conflict_uses_same_scope_and_value_as_card(self):
        app = AgentWorkspace(self.path, DEFAULT_TEMPLATE, self.directory / "no-profiles.json",
                             model=scripted_model([test_tui_p0.tool("query_business_sql", {"sql": COUNT_SQL}),
                                                   final(FALSE_CLAIM)]),
                             trace_path=self.directory / "workbench.jsonl")
        app.mode = "mock"
        async with app.run_test(size=(150, 42)) as pilot:
            app.screen.query_one("#login-user", Select).value = "U001"
            await pilot.click("#sign-in")
            await self.await_state(pilot, lambda: app.user == "U001")
            await test_tui_p0.P0Test.send(self, app, pilot, COUNT_PROMPT)
            await self.await_state(pilot, lambda: app.agent is not None and not app.busy and app.agent.last_response)
            chat = "\n".join(str(entry) for entry in app.workspace_widget("#chat-log", ChatLog).entries)
            card = str(app.workspace_widget("#business-log", ChatLog).entries[-1].renderable)
            self.assertEqual(self.sqlite_rows(COUNT_SQL), [(10,)])
            self.assertEqual(self.sqlite_rows("SELECT COUNT(*) FROM invoice_audit"), [(0,)])
            for shown in (chat, card):
                for claim in ("C001", "2026-09", "10 张", "当前账簿"):
                    self.assertIn(claim, shown)
                self.assertNotIn("999", shown)
            self.assertNotIn(FALSE_CLAIM, str(app.agent.messages))
            self.assertIn(FALSE_CLAIM, (self.directory / "workbench.jsonl").read_text(encoding="utf-8"))

    def test_correct_reply_still_reports_scope_and_actual_count(self):
        sql = COUNT_SQL.replace("C001", "C002").replace("2026-09", "2026-08")
        count, = self.sqlite_rows(sql)[0]
        agent, answer = self.ask("分析一下 C002 2026年8月的发票总数，并说明数据来源。", "query_business_sql",
                                 {"sql": sql}, f"C002 2026年8月共有 {count} 张发票。")
        source = agent.last_response["tool_results"][0][1]["evidence"]
        self.assertEqual(source["source"], "current_sqlite")
        for shown in (answer, agent.last_response["chat_notice"]):
            for part in ("C002", "2026-08", f"{count} 张", "当前账簿"):
                self.assertIn(part, shown)

    def test_compact_sql_keeps_count_and_money_from_same_filtered_rows(self):
        sql = ("SELECT COUNT(*) AS invoice_count, SUM(amount_cents) AS invoice_total_cents FROM invoices "
               "WHERE company_id = 'C002' AND invoice_date LIKE '2026-08%' AND amount_cents >= 100000")
        count, cents = self.sqlite_rows(sql)[0]
        self.assertLess(count, 10)
        self.assertGreater(count, 0)
        amount = f"{cents // 100:,}.{cents % 100:02}"
        agent, answer = self.ask("分析 C002 2026年8月单张金额至少1000元的发票，给出张数及价税合计和来源。",
                                 "query_business_sql", {"sql": sql},
                                 "C001 2026年9月共 999 张，合计 987654.32 元，依据 R999。")
        for shown in (answer, agent.last_response["chat_notice"]):
            for part in ("C002", "2026-08", f"{count} 张", f"¥{amount}", "当前账簿"):
                self.assertIn(part, shown)
            for part in ("C001", "2026-09", "999 张", "987654.32", "R999"):
                self.assertNotIn(part, shown)

    def test_finance_summary_retains_grounded_rule_explanation(self):
        scope = {"company_id": "C001", "year": 2026, "month": 9}
        agent, answer = self.ask("分析 C001 2026年9月的财务数据，并说明统计依据。", "get_finance_summary", scope,
                                 "发票合计 987654.32 元，依据 R999 v9.9。")
        outcome = agent.last_response["tool_results"][0][1]
        self.assertEqual(outcome["evidence"]["rule"]["rule_id"], "R001")
        for shown in (answer, agent.last_response["chat_notice"]):
            for key in ("invoice_total", "bank_income_total", "bank_expense_total"):
                self.assertIn(outcome["data"][key], shown)
            self.assertIn("R001 v1.0", shown)
            self.assertIn("按开票日期", shown)
            self.assertNotIn("987654.32", shown)
            self.assertNotIn("R999", shown)

    def test_empty_sql_rows_and_zero_count_have_distinct_meanings(self):
        for expression, expected_status, expected_text in (
            ("invoice_no", "NO_DATA", "没有匹配的记录"),
            ("COUNT(*) AS invoice_count", "SUCCESS", "0 张"),
        ):
            with self.subTest(expression=expression):
                sql = (f"SELECT {expression} FROM invoices "
                       "WHERE company_id = 'C001' AND invoice_date LIKE '2027-02%'")
                independent = self.sqlite_rows(sql)
                self.assertEqual(independent, [] if expected_status == "NO_DATA" else [(0,)])
                agent, answer = self.ask("分析 C001 2027年2月的发票数据，并说明数据来源。", "query_business_sql",
                                         {"sql": sql}, "当前有 999 张发票。")
                self.assertEqual(agent.last_response["tool_results"][0][1]["status"], expected_status)
                self.assertIn(expected_text, agent.last_response["chat_notice"])
                self.assertIn("2027-02", answer)
                self.assertNotIn("999", answer)

    def test_denied_sql_is_not_rendered_as_an_empty_or_successful_query(self):
        sql = COUNT_SQL.replace("C001", "C002")
        agent, answer = self.ask("分析 C002 2026年9月的发票总数，并说明数据来源。", "query_business_sql",
                                 {"sql": sql}, "查到 999 张。", user="U002")
        self.assertEqual(agent.last_response["tool_results"][0][1]["status"], "DENIED")
        for shown in (answer, agent.last_response["chat_notice"]):
            self.assertIn("权限", shown)
            self.assertNotIn("0 张", shown)
            self.assertNotIn("999", shown)
            self.assertNotIn("没有匹配的记录", shown)
