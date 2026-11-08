"""Frozen accountant trial through the real workspace and isolated fixture."""
from contextlib import closing, contextmanager
import json
import sqlite3
import unittest
from unittest.mock import patch

import httpx

from app.agent import Agent, scripted_model
from app.responses import render_reference_error, render_scope, scope_key
from app.session_store import SessionStore
from app.tasks import list_tasks
from app.tui_screens import Approval
from tests import test_tui_p0 as fixture

SCOPE = fixture.SCOPE
DETAIL = {"company_id": "C001", "invoice_no": "F002"}
DIRECTORY = "甲企业有哪些发票？我想看看完整的发票清单。"
EXPLICIT = "帮我看看甲企业 F002 这张发票的详细信息。"
PLAIN = "帮我看看甲企业 F002 的详细信息。"
CREATE = "这些没填用途的发票我明天再处理，先帮我记成一个待办，别弄丢了。"
FINAL = {"role": "assistant", "content": json.dumps({
    "kind": "information", "text": "不可信标记：金额 99999 元，所有任务都已完成。"})}


def call(name, args, identifier):
    return fixture.tool(name, args, identifier)


def directory(page):
    return call("list_invoice_directory", {"company_id": "C001", "year": 0, "month": 0, "page": page}, f"page-{page}")


def batch(*replies):
    return {"role": "assistant", "tool_calls": [c for reply in replies for c in reply["tool_calls"]]}


def check():
    return call("check_missing_purpose", SCOPE, "missing")


def create():
    return call("manage_task", {**SCOPE, "action": "create", "task_id": "", "note": CREATE}, "create")


class AccountantTrialTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.workbook = fixture.P0Test()
        self.workbook.setUp()
        self.addCleanup(self.workbook.doCleanups)
        blocked = patch.object(httpx.HTTPTransport, "handle_request", side_effect=AssertionError("external HTTP disabled"))
        self.http = blocked.start()
        self.addCleanup(blocked.stop)
        self.addCleanup(self.http.assert_not_called)

    @contextmanager
    def workspace(self, replies):
        app = self.workbook.app(replies)
        shown = []
        chat_message = app.chat_message

        def observe(role, text):
            shown.append((role, text))
            chat_message(role, text)

        with patch.object(app, "chat_message", side_effect=observe):
            yield app, shown

    async def send(self, app, pilot, text):
        previous = len(app.records)
        await self.workbook.send(app, pilot, text)
        await self.workbook.await_state(pilot, lambda: len(app.records) == previous + 1)

    def assert_plain(self, shown):
        text = "\n".join(text for role, text in shown if role != "你")
        for token in ('"status"', '"ok"', '"evidence"', 'anchor_id', 'tool_call_id', 'current_sqlite', '不可信标记'):
            self.assertNotIn(token, text)
        return text

    async def test_frozen_directory_and_explicit_details(self):
        replies = [directory(1), directory(2), FINAL, call("get_invoice", DETAIL, "exact"), FINAL,
                   call("get_invoice", DETAIL, "plain"), FINAL]
        with self.workspace(replies) as (app, shown):
            async with app.run_test(size=(120, 40)) as pilot:
                await self.workbook.sign_in(app, pilot)
                shown.clear()
                await self.send(app, pilot, DIRECTORY)
                self.assertEqual([c["id"] for c in app.records[-1][1]], ["page-1", "page-2"])
                self.assertEqual([role for role, _ in shown].count("查询与处理结果"), 1)
                cards = [text for role, text in shown if role == "业务核验 / 发票目录"]
                self.assertEqual(len(cards), 2)
                self.assertIn("第 1 页", cards[0])
                self.assertIn("第 2 页", cards[1])
                self.assertEqual(sum(len(text.splitlines()) - 1 for text in cards), 20)
                for query in (EXPLICIT, PLAIN):
                    shown.clear()
                    await self.send(app, pilot, query)
                    self.assertEqual(app.records[-1][1][0]["status"], "SUCCESS")
                    self.assertEqual(app.records[-1][1][0]["scope"]["company_id"], "C001")
                    self.assertIn("F002", self.assert_plain(shown))

    async def test_real_reference_still_needs_current_authorization(self):
        monthly = call("list_invoices", SCOPE, "list")
        with self.workspace([monthly, FINAL, FINAL]) as (app, shown):
            async with app.run_test(size=(120, 40)) as pilot:
                await self.workbook.sign_in(app, pilot)
                shown.clear()
                await self.send(app, pilot, "那张发票。")
                self.assertIn("还不能确定", self.assert_plain(shown))
                self.assertEqual(app.records[-1][0], "AMBIGUOUS")
                await self.send(app, pilot, "列出 C001 2026-09 发票。")
                shown.clear()
                await self.send(app, pilot, "刚才第二张。")
                self.assertIn("发票详情", " ".join(role for role, _ in shown))
                with closing(sqlite3.connect(self.workbook.path)) as db, db:
                    db.execute("UPDATE permissions SET can_read=0 WHERE user_id='U001' AND company_id='C001'")
                shown.clear()
                await self.send(app, pilot, "C001 那张发票。")
                text = self.assert_plain(shown)
                self.assertIn("没有读取权限", text)
                self.assertNotIn("销售方", text)

    def test_same_number_uses_explicit_company_and_rechecks_access(self):
        other = {"company_id": "C002", "invoice_no": "F002"}
        agent = Agent("U001", self.workbook.path, scripted_model([
            call("get_invoice", DETAIL, "a"), FINAL, call("get_invoice", other, "b"), FINAL,
            call("get_invoice", other, "c")]), mode="mock")
        agent.ask(EXPLICIT)
        agent.ask("帮我看乙企业 F002 这张发票。")
        with closing(sqlite3.connect(self.workbook.path)) as db, db:
            db.execute("UPDATE permissions SET can_read=0 WHERE user_id='U001' AND company_id='C002'")
        agent.ask("再看乙企业 F002 这张发票。")
        results = [json.loads(m["content"]) for m in agent.messages if m["role"] == "tool"]
        self.assertEqual([r["status"] for r in results], ["SUCCESS", "SUCCESS", "DENIED"])
        self.assertEqual([r["data"]["company_id"] for r in results[:2]], ["C001", "C002"])
        self.assertIsNone(results[-1]["data"])

    async def test_finance_and_distinct_evidence_groups(self):
        summary = call("get_finance_summary", SCOPE, "summary")
        ledger = call("list_invoices", SCOPE, "invoices")
        with self.workspace([summary, FINAL, batch(summary, ledger), FINAL]) as (app, shown):
            async with app.run_test(size=(120, 40)) as pilot:
                await self.workbook.sign_in(app, pilot)
                shown.clear()
                await self.send(app, pilot, "查甲企业 2026 年 9 月的发票和银行收支情况。")
                text = self.assert_plain(shown)
                for amount in ("9622.06", "13000.50", "7180.74"):
                    self.assertEqual(text.count(amount), 1)
                self.assertEqual(text.count("R001"), 1)
                shown.clear()
                await self.send(app, pilot, "查甲企业 2026 年 9 月发票明细和汇总。")
                self.assertEqual([role for role, _ in shown].count("查询与处理结果"), 1)
                self.assertEqual(len(app.records[-1][1]), 2)
        evidence = {"scope": SCOPE, "source": "current_sqlite",
                    "rule": {"rule_id": "R001", "version": "1.0", "name": "统计说明"}}
        variants = [evidence, {**evidence, "scope": {**SCOPE, "month": 8}},
                    {**evidence, "scope": {**SCOPE, "company_id": "C002"}},
                    {**evidence, "rule": {**evidence["rule"], "version": "2.0"}},
                    {**evidence, "source": "local_display_preference"}]
        self.assertEqual(len({scope_key(item) for item in variants}), len(variants))
        self.assertEqual(len({render_scope(item, conversational=True) for item in variants}), len(variants))

    async def test_different_company_and_rule_keep_separate_cards(self):
        calls = batch(call("get_finance_summary", SCOPE, "first"),
                      call("get_finance_summary", {**SCOPE, "company_id": "C002"}, "second"), check())
        with self.workspace([calls, FINAL]) as (app, shown):
            async with app.run_test(size=(120, 40)) as pilot:
                await self.workbook.sign_in(app, pilot)
                shown.clear()
                await self.send(app, pilot, "查 C001 和 C002 2026-09 的收支，并核对 C001 未填用途。")
                self.assertEqual([c["status"] for c in app.records[-1][1]], ["SUCCESS"] * 3)
                headings = [text for role, text in shown if role == "查询与处理结果"]
                self.assertEqual(len(headings), 3)
                self.assertIn("C001", headings[0])
                self.assertIn("C002", headings[1])
                self.assertIn("R002 v2.0", headings[2])

    async def test_save_and_current_progress_are_separate(self):
        reads = batch(call("list_tasks", {"company_id": "C001"}, "tasks"), check())
        replies = [check(), FINAL, batch(check(), create()), FINAL, reads, FINAL]
        with self.workspace(replies) as (app, shown):
            async with app.run_test(size=(120, 40)) as pilot:
                await self.workbook.sign_in(app, pilot)
                await self.send(app, pilot, "甲企业 2026-09 哪些发票没填用途？")
                shown.clear()
                await self.workbook.send(app, pilot, CREATE)
                await self.workbook.await_state(pilot, lambda: isinstance(app.screen, Approval) and app.screen.focused)
                self.assertEqual(app.screen.focused.id, "cancel")
                self.assertEqual(list_tasks(self.workbook.path, "U001", "C001")["data"], [])
                await pilot.press("tab", "enter")
                await self.workbook.await_state(pilot, lambda: len(app.records) == 2)
                text = self.assert_plain(shown)
                self.assertIn("已创建用途补充待办，进行中", text)
                self.assertIn("5 张发票", text)
                self.assertEqual(text.count("R002"), 1)
                self.assertNotIn("无法", text)
                self.assertNotIn("都已完成", text)
                self.assertNotIn("已重新核对待办与缺项", text)
                self.assertEqual(list_tasks(self.workbook.path, "U001", "C001")["data"][0]["status"], "ACTIVE")
                self.assertEqual(self.workbook.purpose(), (None, 0))
                shown.clear()
                await self.send(app, pilot, "查一下甲企业 2026-09 的待办和缺用途进度。")
                text = self.assert_plain(shown)
                self.assertIn("已重新核对待办与缺项", text)
                self.assertIn("5 张发票", text)
                self.assertNotIn("已创建", text)

    async def test_cancelled_denied_and_database_failure_never_claim_save(self):
        for user, failure in (("U001", "CANCELLED"), ("U002", "DENIED"), ("U001", "ERROR"), ("U001", "UNKNOWN_OUTCOME")):
            with self.subTest(failure=failure), self.workspace([check(), FINAL, batch(check(), create())]) as (app, shown):
                async with app.run_test(size=(120, 40)) as pilot:
                    await self.workbook.sign_in(app, pilot, user)
                    await self.send(app, pilot, "甲企业 2026-09 哪些发票没填用途？")
                    shown.clear()
                    await self.workbook.send(app, pilot, CREATE)
                    if failure != "DENIED":
                        await self.workbook.await_state(pilot, lambda: isinstance(app.screen, Approval) and app.screen.focused)
                        if failure == "CANCELLED":
                            await pilot.press("escape")
                        else:
                            hook = "_check" if failure == "ERROR" else "_task"
                            with patch(f"app.tasks.{hook}", side_effect=sqlite3.OperationalError("synthetic database fault")):
                                await pilot.press("tab", "enter")
                                await self.workbook.await_state(pilot, lambda: len(app.records) == 2)
                    await self.workbook.await_state(pilot, lambda: len(app.records) == 2)
                    self.assertEqual(app.records[-1][1][-1]["status"], failure)
                    self.assertNotIn("已创建", self.assert_plain(shown))
                    saved = list_tasks(self.workbook.path, "U001", "C001")["data"]
                    if failure == "UNKNOWN_OUTCOME":
                        self.assertIn("提交结果未知", self.assert_plain(shown))
                        self.assertEqual([task["status"] for task in saved], ["ACTIVE"])
                    else:
                        self.assertEqual(saved, [])

    async def test_old_reference_error_is_reopened_without_protocol_json(self):
        path = self.workbook.directory / "history.sqlite3"
        old = SessionStore(path, self.workbook.path, "U001")
        try:
            seq = old.begin("那张发票。", "mock")
            body = '请明确引用对象：{"status":"DENIED","evidence":{}}'
            old.finish(seq, [("Agent", body)], [], None, None)
        finally:
            old.close()
        with self.workspace([]) as (app, shown):
            app.session_path = path
            async with app.run_test(size=(120, 40)) as pilot:
                await self.workbook.sign_in(app, pilot)
                self.assertIn("没有读取权限", self.assert_plain(shown))

    def test_reference_failure_messages_are_distinct(self):
        messages = [render_reference_error(status) for status in
                    ("AMBIGUOUS", "DENIED", "NOT_FOUND", "SCOPE_MISMATCH", "ERROR")]
        self.assertEqual(len(set(messages)), 5)
        self.assert_plain([("Agent", message) for message in messages])
