"""P1-E tests against the existing local store and the actual Textual workbench."""
from contextlib import closing
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from app.cli_workspaces import import_workspace
from app.session_store import SessionBusyError, SessionStore
from app.stage2_schema import open_existing
from app.tui_screens import Approval, Choices
from tests import test_p05_sessions as sessions
from tests import test_tui_p0 as fixture


class ConversationStoreTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.book = Path(directory.name) / "book.sqlite"
        self.store = self.book.with_name("sessions.sqlite")
        import_workspace(sessions.FIXTURE, self.book)

    def open(self, user="U001", book=None):
        store = SessionStore(self.store, book or self.book, user)
        self.addCleanup(store.close)
        return store

    def test_archive_reopen_is_atomic_and_survives_restart(self):
        store = self.open()
        first = store.chat
        seq = store.begin("第一条   " + "甲" * 50, "mock")
        store.finish(seq, [], [], None, None)
        store.new_chat(None)
        second = store.chat
        self.assertEqual([(r["id"], r["state"]) for r in store.list_chats()],
                         [(second, "ACTIVE"), (first, "ARCHIVED")])
        self.assertEqual(store.list_chats()[1]["title"], "第一条 " + "甲" * 32 + "…")
        seq = store.begin("第二条", "mock")
        before = store.list_chats()
        with self.assertRaises(SessionBusyError):
            store.switch_chat(first)
        with self.assertRaises(SessionBusyError):
            store.new_chat(None)
        self.assertEqual(store.chat, second)
        self.assertEqual(store.list_chats(), before)
        store.finish(seq, [], [], None, None)
        lock = store.lock
        store.switch_chat(first)
        self.assertIs(store.lock, lock)
        self.assertEqual([r["id"] for r in store.list_chats() if r["state"] == "ACTIVE"], [first])
        store.close()
        script = """
import sys
from app.session_store import SessionStore

store = SessionStore(sys.argv[1], sys.argv[2], "U001")
try:
    print(store.chat)
finally:
    store.close()
"""
        child = subprocess.run([sys.executable, "-c", script, str(self.store), str(self.book)],
                               cwd=Path(__file__).resolve().parents[1], capture_output=True,
                               text=True, check=True, timeout=20)
        self.assertEqual(child.stdout.strip(), first)
        resumed = self.open()
        self.assertEqual(resumed.chat, first)
        self.assertEqual(resumed.history()["turns"][0]["state"], "COMPLETED")
        resumed.switch_chat(second)
        self.assertEqual(resumed.history()["turns"][0]["request"], "第二条")

    def test_foreign_chat_ids_do_not_change_either_active_chat(self):
        one = self.open()
        other = self.open("U002")
        copy = self.book.with_name("copy.sqlite")
        shutil.copyfile(self.book, copy)
        copied = self.open(book=copy)
        for store, foreign in ((one, other), (other, one), (one, copied), (copied, one)):
            before = store.list_chats()
            self.assertEqual([row["id"] for row in before], [store.chat])
            with self.assertRaises(ValueError):
                store.switch_chat(foreign.chat)
            self.assertEqual(store.list_chats(), before)

    def test_recovered_interrupted_turn_stays_interrupted_after_switch(self):
        store = self.open()
        old = store.chat
        store.begin("未完成的旧查询", "mock")
        store.close()
        resumed = self.open()
        resumed.new_chat(None)
        resumed.switch_chat(old)
        turn, = resumed.history()["turns"]
        self.assertEqual((turn["state"], turn["hint"], turn["calls"]), ("INTERRUPTED", None, []))


class ConversationPilotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.h = sessions.SessionTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    async def my_chats(self, app, pilot):
        await pilot.press("f3")
        self.assertIsInstance(app.screen, Choices)
        await self.choose(app, pilot, "conversations")
        self.assertIsInstance(app.screen, Choices)
        self.assertIn("我的对话", app.screen.title_text)

    async def choose(self, app, pilot, value):
        index = next(i for i, choice in enumerate(app.screen.choices) if choice[1] == value)
        await self.h.helper.press_button(app, pilot, f"#choice-{index}")

    async def test_menu_restores_visible_history_and_requeries_current_workbook(self):
        h = self.h
        call = fixture.tool("check_missing_purpose", sessions.SCOPE)
        app = h.app([call, fixture.FINAL, call, fixture.FINAL])
        async with app.run_test(size=(90, 26)) as pilot:
            await h.helper.sign_in(app, pilot)
            first = app.conversation.chat
            await h.helper.send(app, pilot, "查甲企业 2026-09 缺用途的发票。")
            await h.helper.await_state(pilot, lambda: not app.busy and app.has_saved_history)
            old_agent = app.agent
            self.assertIn("5 张", h.log(app))
            await self.my_chats(app, pilot)
            await self.choose(app, pilot, "new")
            await h.helper.press_button(app, pilot, "#approve")
            second = app.conversation.chat
            self.assertNotEqual(second, first)
            self.assertNotIn("5 张", h.log(app))
            with closing(open_existing(h.book)) as db, db:
                db.execute("UPDATE invoices SET purpose='测试已填' WHERE company_id='C001' AND invoice_no='F002'")
            await self.my_chats(app, pilot)
            await self.choose(app, pilot, first)
            self.assertEqual(app.conversation.chat, first)
            self.assertIsNone(app.agent)
            self.assertIn("5 张", h.log(app))
            self.assertEqual(app.resume_focus, ("C001", 2026, 9))
            await h.helper.send(app, pilot, "再查这个月的缺项。")
            await h.helper.await_state(pilot, lambda: not app.busy and bool(app.records))
            self.assertIsNot(app.agent, old_agent)
            self.assertIn("4 张", h.log(app))
            self.assertFalse(app.agent.update_session.drafts)
            self.assertIsNone(app.agent.pending_edit)
            self.assertEqual(app.mode, "mock")
        reopened = h.app()
        async with reopened.run_test(size=(90, 26)) as pilot:
            await h.helper.sign_in(reopened, pilot)
            self.assertEqual(reopened.conversation.chat, first)
            self.assertIn("4 张", h.log(reopened))

    async def test_acl_change_hides_archived_title_results_and_focus(self):
        h = self.h
        store = SessionStore(h.store, h.book, "U001")
        old = store.chat
        store.select_focus(("C002", 2026, 9), None)
        seq = store.begin("查乙企业测试标题", "mock")
        store.finish(seq, [["Agent", "受限旧结果"]], [
            {"tool": "get_finance_summary", "status": "SUCCESS", "scope": {"company_id": "C002", "year": 2026, "month": 9}}
        ], "fictional-trace", {"tools": ["get_finance_summary"], "focus": ["C002", 2026, 9]})
        store.new_chat(None)
        store.close()
        with closing(open_existing(h.book)) as db, db:
            db.execute("UPDATE permissions SET can_read=0 WHERE user_id='U001' AND company_id='C002'")
        app = h.app()
        async with app.run_test(size=(90, 26)) as pilot:
            await h.helper.sign_in(app, pilot)
            await self.my_chats(app, pilot)
            self.assertIn("部分内容已无读取权限", str(app.screen.choices))
            self.assertNotIn("测试标题", str(app.screen.choices))
            await self.choose(app, pilot, old)
            self.assertNotIn("受限旧结果", h.log(app))
            self.assertIsNone(app.read_workspace)
            self.assertIsNone(app.resume_focus)
            self.assertEqual((app.resume_displays, app.saved_records), ([], []))

    async def test_switch_rejected_until_invoice_confirmation_is_cancelled(self):
        h = self.h
        store = SessionStore(h.store, h.book, "U001")
        old = store.chat
        store.new_chat(None)
        current = store.chat
        store.close()
        app = h.app([fixture.tool("prepare_invoice_update", fixture.EDIT)])
        async with app.run_test(size=(90, 26)) as pilot:
            await h.helper.sign_in(app, pilot)
            await h.helper.send(app, pilot, "把甲企业 F002 的用途改成资料打印。")
            await h.helper.await_state(pilot, lambda: isinstance(app.screen, Approval))
            app.choose_conversation(old)
            self.assertEqual(app.conversation.chat, current)
            self.assertIsInstance(app.screen, Approval)
            await h.helper.press_button(app, pilot, "#cancel")
            await h.helper.await_state(pilot, lambda: not app.busy)
            app.choose_conversation(old)
            self.assertEqual(app.conversation.chat, old)
            self.assertIsNone(app.agent)
        with closing(open_existing(h.book, readonly=True)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM invoice_audit").fetchone()[0], 0)


    async def test_persisted_switch_and_new_refuse_pending_edit_until_explicit_cancel(self):
        h = self.h
        store = SessionStore(h.store, h.book, "U001")
        old = store.chat
        store.new_chat(None)
        current = store.chat
        store.close()
        app = h.app([fixture.tool("prepare_invoice_update", fixture.EDIT)])
        async with app.run_test(size=(90, 26)) as pilot:
            await h.helper.sign_in(app, pilot)
            await h.helper.send(app, pilot, "把 F002 的用途改成资料打印。")
            await h.helper.await_state(pilot, lambda: bool(app.records) and not app.busy)
            self.assertTrue(app.agent.pending_edit)
            app.choose_conversation(old)
            app.request_new_chat()
            self.assertEqual(app.conversation.chat, current)
            self.assertTrue(app.agent.pending_edit)
            self.assertNotIsInstance(app.screen, Approval)
            app.action_cancel_edit()
            app.choose_conversation(old)
            self.assertEqual(app.conversation.chat, old)
            self.assertIsNone(app.agent)
