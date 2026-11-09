"""Presentation and current-SQLite navigation for paginated invoice results."""
from contextlib import closing
import json
import unittest
from unittest.mock import patch

from app.stage2_schema import open_existing
from app.tui_screens import Choices
from tests import test_p05_sessions as sessions
from tests import test_tui_p0 as fixture


SCOPE = {"company_id": "C001", "year": 2026}
DIRECTORY = "list_invoice_directory"
PROMPT = "查询甲企业 2026 年所有发票"


def tool(page, *, scope=SCOPE):
    return fixture.tool(DIRECTORY, {**scope, "month": scope.get("month", 0), "page": page}, f"page-{page}")


class DirectoryPilotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.h = sessions.SessionTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    async def test_two_pages_keep_tool_evidence_and_open_first_page(self):
        h = self.h
        bank = fixture.tool("list_annual_bank_income", {**SCOPE, "page": 1}, "income")
        app = h.app([tool(1), tool(2), bank, fixture.FINAL])
        async with app.run_test(size=(100, 34)) as pilot:
            await h.helper.sign_in(app, pilot)
            await h.helper.send(app, pilot, PROMPT)
            await h.helper.await_state(pilot, lambda: bool(app.records) and not app.busy)
            self.assertEqual(app.chat_invoice_route, ("C001", 2026, 0, 1))
            text = h.log(app)
            self.assertEqual(text.count("业务核验 / 发票目录"), 1)
            self.assertIn("共 20 张", text)
            self.assertIn("第 1 页", text)
            self.assertIn("第 2 页", text)
            self.assertIn("每页 10 张", text)
            self.assertIn("年度银行收入流水", text)
            self.assertNotIn("F020", text)
            self.assertEqual([c["id"] for c in app.records[-1][1]], ["page-1", "page-2", "income"])
            results = [r for name, r in app.agent.last_response["tool_results"] if name == DIRECTORY]
            self.assertEqual([r["data"]["total"] for r in results], [20, 20])
            with closing(open_existing(h.book, readonly=True)) as db:
                expected = [r[0] for r in db.execute("""SELECT invoice_no FROM invoices
                    WHERE company_id='C001' AND invoice_date LIKE '2026-%' ORDER BY invoice_date,invoice_no""")]
            self.assertEqual([row["invoice_no"] for r in results for row in r["data"]["rows"]], expected)
            await h.helper.press_button(app, pilot, "#chat-invoices")
            await h.helper.await_state(pilot, lambda: bool(app.workspace_widget("#finance-body").query("#invoice-next")))
            self.assertEqual([row["invoice_no"] for row in app.invoice_rows], expected[:10])
            # The browser re-reads SQLite, including changes made after the chat result.
            with closing(open_existing(h.book)) as db, db:
                db.execute("UPDATE invoices SET amount_cents=123 WHERE company_id='C001' AND invoice_no=?", (expected[10],))
            await h.helper.press_button(app, pilot, "#invoice-next")
            await h.helper.await_state(pilot, lambda: bool(app.invoice_rows) and app.invoice_rows[0]["invoice_no"] == expected[10])
            self.assertEqual([row["invoice_no"] for row in app.invoice_rows], expected[10:])
            self.assertEqual(app.invoice_rows[0]["amount"], "1.23")
            with closing(open_existing(h.book)) as db, db:
                db.execute("UPDATE permissions SET can_read=0 WHERE user_id='U001' AND company_id='C001'")
            await h.helper.press_button(app, pilot, "#invoice-prev")
            await h.helper.await_state(pilot, lambda: not app.workspace_widget("#finance-body").query("#invoice-table"))
            self.assertEqual(app.invoice_rows, [])
        events = [json.loads(line) for line in h.trace.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([e["data"]["request"]["id"] for e in events if e["event"] == "tool_result"],
                         ["page-1", "page-2", "income"])

    async def test_second_page_only_and_conversation_changes_reset_navigation(self):
        h = self.h
        app = h.app([tool(2), fixture.FINAL])
        async with app.run_test(size=(100, 34)) as pilot:
            await h.helper.sign_in(app, pilot)
            original = app.conversation.chat
            await h.helper.send(app, pilot, PROMPT + "，只显示第 2 页")
            await h.helper.await_state(pilot, lambda: bool(app.records) and not app.busy)
            self.assertEqual(app.chat_invoice_route, ("C001", 2026, 0, 2))
            text = h.log(app)
            self.assertIn("预览第 2 页", text)
            self.assertNotIn("第 1 页", text)
            self.assertNotIn("F011", text)
            await h.helper.press_button(app, pilot, "#chat-invoices")
            await h.helper.await_state(pilot, lambda: bool(app.workspace_widget("#finance-body").query("#invoice-prev")))
            self.assertEqual(app.invoice_page, 2)
            self.assertEqual(app.invoice_rows[0]["invoice_no"], "F001")
            await h.helper.press_button(app, pilot, "#invoice-prev")
            await h.helper.await_state(pilot, lambda: bool(app.invoice_rows) and app.invoice_rows[0]["invoice_no"] == "F011")
            app.show("chat")
            app.request_new_chat()
            await h.helper.press_button(app, pilot, "#approve")
            self.assertNotEqual(app.conversation.chat, original)
            for reopen in (False, True):
                if reopen:
                    app.choose_conversation(original)
                    self.assertEqual(app.conversation.chat, original)
                    self.assertIn("预览第 2 页", h.log(app))
                self.assertFalse(app.chat_invoice_routes)
                self.assertFalse(app.workspace_widget("#chat-invoices").display)
                self.assertIsNone(app.invoice_route)
                self.assertEqual(app.invoice_page, 1)

    async def test_unauthorized_directory_has_no_card_or_route(self):
        h = self.h
        app = h.app([tool(1, scope={**SCOPE, "company_id": "C002"})])
        async with app.run_test(size=(100, 34)) as pilot:
            await h.helper.sign_in(app, pilot, "U002")
            await h.helper.send(app, pilot, "查询乙企业 2026 年所有发票")
            await h.helper.await_state(pilot, lambda: bool(app.records) and not app.busy)
            self.assertEqual(app.records[-1][1][0]["status"], "DENIED")
            self.assertNotIn("业务核验 / 发票目录", h.log(app))
            self.assertFalse(app.workspace_widget("#chat-invoices").display)

    async def test_distinct_scope_picker_preserves_selected_range(self):
        h = self.h
        app = h.app()
        async with app.run_test(size=(100, 34)) as pilot:
            await h.helper.sign_in(app, pilot)
            app.show_turn_results([page(1), page(2, scope={**SCOPE, "company_id": "C002"})])
            app.open_chat_invoice_directory()
            await h.helper.await_state(pilot, lambda: isinstance(app.screen, Choices))
            self.assertIn("C002 · 2026 年 · 第 2 页", str(app.screen.choices))
            await h.helper.press_button(app, pilot, "#choice-1")
            await h.helper.await_state(pilot, lambda: bool(app.workspace_widget("#finance-body").query("#invoice-table")))
            self.assertEqual((app.invoice_route, app.invoice_page), (("C002", 2026, 0), 2))
            self.assertTrue(app.invoice_rows)
            self.assertTrue(all(row["company_id"] == "C002" for row in app.invoice_rows))


def page(number, *, scope=SCOPE, total=20, status="SUCCESS", source="current_sqlite"):
    data = {"total": total, "page": number, "page_size": 10, "rows": [
        {"company_id": scope["company_id"], "invoice_date": "2026-08-01",
         "invoice_no": f"DEMO-{number}", "amount": "1.00"}
    ]}
    if status == "NO_DATA":
        data["rows"] = []
    return DIRECTORY, {"status": status, "evidence": {"source": source, "scope": scope}, "data": data}


class DirectoryPresentationTests(unittest.TestCase):
    def setUp(self):
        h = sessions.SessionTests()
        h.setUp()
        self.addCleanup(h.doCleanups)
        self.app = h.app()

    def render(self, results):
        with patch.object(self.app, "chat_message") as message:
            self.app.show_turn_results(results)
        return [args[1] for args, _ in message.call_args_list if args[0] == "业务核验 / 发票目录"]

    def test_out_of_order_and_duplicate_pages_show_one_first_page_preview(self):
        first = page(1)
        single, = self.render([first])
        self.assertIn("预览第 1 页", single)
        self.assertNotIn("第 2 页", single)
        summary, = self.render([page(2), first, first])
        self.assertEqual(summary.count("DEMO-1"), 1)
        self.assertNotIn("DEMO-2", summary)
        self.assertIn("已查询 第 1 页、第 2 页", summary)
        self.assertEqual(self.app.chat_invoice_route, ("C001", 2026, 0, 1))

    def test_distinct_companies_years_months_and_unfiltered_stay_separate(self):
        scopes = [SCOPE, {**SCOPE, "company_id": "C002"}, {**SCOPE, "year": 2025},
                  {**SCOPE, "month": 8}, {"company_id": "C001"}]
        cards = self.render([page(1, scope=scope) for scope in scopes])
        self.assertEqual(len(cards), len(scopes))
        self.assertIn("全部账期", cards[-1])
        self.assertEqual(self.app.chat_invoice_routes,
                         (("C001", 2026, 0, 1), ("C002", 2026, 0, 1), ("C001", 2025, 0, 1),
                          ("C001", 2026, 8, 1), ("C001", 0, 0, 1)))

    def test_disagreeing_totals_stay_attributed_and_failed_data_is_ignored(self):
        results = [page(1), page(2, total=21), page(1, total=19),
                   page(3, total=444, status="ERROR"), page(4, total=555, source="untrusted"),
                   page(5, total=666, status="DENIED"), page(6, total=777, status="NO_CHANGE"),
                   (DIRECTORY, {"status": "SUCCESS", "evidence": None, "data": None})]
        summary, = self.render(results)
        self.assertIn("不一致", summary)
        for text in ("第 1 页报告共 20 张", "第 2 页报告共 21 张", "第 1 页报告共 19 张"):
            self.assertIn(text, summary)
        for text in ("444", "555", "666", "777", "DEMO-2", "共 60 张"):
            self.assertNotIn(text, summary)
        self.assertEqual(self.app.chat_invoice_route, ("C001", 2026, 0, 1))
        empty, = self.render([page(1, total=0, status="NO_DATA")])
        self.assertIn("共 0 张", empty)
        self.assertIsNone(self.app.chat_invoice_route)
