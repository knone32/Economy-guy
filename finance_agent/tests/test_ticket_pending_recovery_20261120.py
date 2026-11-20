"""Public unfinished single-ticket recovery; scripted semantics, no approval/HTTP."""
import asyncio
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from app.cli_workspaces import import_workspace
from app.model_config import DEFAULT_TEMPLATE
from app.session_store import SessionStore
from app.tui import AgentWorkspace
from app.tui_screens import Approval
from tests import test_tui_p0 as helpers
from tests.test_model_intent import call
from app.agent import scripted_model
from tests import test_ticket_fault_ui_20261120 as fault_ui


START = '甲企业2026年9月有张发票，备注填「跨重启待复核」，票号稍后补。'
PATCH = {'company_id': 'C001', 'year': 2026, 'month': 9, 'field': 'remark', 'new_value': '跨重启待复核'}


class PendingTicketRecoveryTests(unittest.IsolatedAsyncioTestCase):
    await_state = helpers.P0Test.await_state
    sign_in = helpers.P0Test.sign_in
    send = helpers.P0Test.send

    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.book = self.root / 'fictional.sqlite3'
        self.sessions = self.root / 'sessions.sqlite3'
        import_workspace(helpers.FIXTURE, self.book)

    def app(self, args=None):
        app = AgentWorkspace(self.book, DEFAULT_TEMPLATE, self.root / 'no-profiles.json',
                             model=lambda *_: call('change_invoice', args or {}),
                             session_path=self.sessions, trace_path=self.root / 'trace.jsonl')
        app.mode = 'mock'
        return app

    @staticmethod
    def chat(app):
        return '\n'.join(line.text for line in app.workspace_widget('#chat-log').lines)

    def no_write(self):
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT remark FROM invoices WHERE company_id='C001' AND invoice_no='F006'").fetchone()[0], '按月结算')

    async def seed(self):
        app = self.app(PATCH)
        async with app.run_test(size=(150, 42)) as pilot:
            await self.sign_in(app, pilot)
            await self.send(app, pilot, START)
            await self.await_state(pilot, lambda: bool(app.records) and not app.busy)
            pending = deepcopy(app.agent.pending_intent)
            self.assertEqual(pending['missing_fields'], ('invoice_no',))
            self.assertNotIsInstance(app.screen, Approval)
        return pending

    async def test_real_process_restart_recovers_source_then_requires_fresh_preview(self):
        program = '''
import asyncio,json,sys
from pathlib import Path
from tests.test_ticket_pending_recovery_20261120 import PendingTicketRecoveryTests
async def main():
    test = PendingTicketRecoveryTests()
    test.root = Path(sys.argv[1]); test.book = test.root/'fictional.sqlite3'; test.sessions = test.root/'sessions.sqlite3'
    pending = await test.seed()
    print(json.dumps(pending,ensure_ascii=False))
asyncio.run(main())
'''
        result = await asyncio.to_thread(subprocess.run, [sys.executable, '-X', 'utf8', '-B', '-c', program, str(self.root)],
                                         capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        original = json.loads(result.stdout.strip())
        app = self.app({'invoice_no': 'F006'})
        async with app.run_test(size=(150, 42)) as pilot:
            await self.sign_in(app, pilot)
            self.assertIn('未提交的单票候选', self.chat(app))
            self.assertIn('跨重启待复核', self.chat(app))
            self.assertIsNone(app.agent)
            saved_candidate = app.conversation.history()['invoice_pending']
            self.assertEqual(saved_candidate['provenance'], original['provenance'])
            self.assertEqual(saved_candidate['source_request'], original['source_request'])
            fault_ui.TicketFaultWorkbenchTests.capture(app, '05-pending-restored-after-process', {
                'chat-log':self.chat(app), 'original_candidate':original,
                'restored_candidate':saved_candidate, 'confirmation':'NONE_PREVIEW_ONLY'})
            # A normally completed unrelated read preserves the runtime
            # candidate. Its SQL result supplies neither the write nor target.
            app.model_override = scripted_model([call('get_invoice', {'company_id':'C002','invoice_no':'F006'}), helpers.FINAL])
            await self.send(app, pilot, '先查询乙企业2026年9月F006，这次只查询。')
            await self.await_state(pilot, lambda: bool(app.records) and not app.busy)
            self.assertEqual(app.conversation.history()['invoice_pending'], saved_candidate)
            app.agent.model = lambda *_: call('change_invoice', {'invoice_no':'F006'})
            with closing(sqlite3.connect(self.book)) as db, db:
                db.execute("UPDATE invoices SET remark='重启后独立原值' WHERE company_id='C001' AND invoice_no='F006'")
            await self.send(app, pilot, '继续这项单票候选，编号 F006，先给我预览。')
            await self.await_state(pilot, lambda: isinstance(app.screen, Approval))
            self.assertIn('原值　重启后独立原值', app.screen.body)
            self.assertIn('新值　跨重启待复核', app.screen.body)
            fault_ui.TicketFaultWorkbenchTests.capture(app, '06-restored-fresh-preview', {
                'preview':app.screen.body, 'confirmation':'NONE_PREVIEW_ONLY'})
            draft, = app.agent.update_session.drafts.values()
            self.assertIn(original['source_request'], draft.source_request)
            self.assertNotEqual(draft.request_id, original['request_id'])
            self.assertFalse(app.agent.update_session.confirmations)
            app.screen.answer(False)
            await self.await_state(pilot, lambda: not app.busy)
            self.assertIsNone(app.conversation.history().get('invoice_pending'))
            with closing(sqlite3.connect(self.book)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0], 0)

    async def test_cancel_before_agent_creation_persists_and_cannot_revive(self):
        for mode in ('before_agent', 'after_agent', 'new_chat', 'task', 'interrupted'):
            with self.subTest(mode=mode):
                await self.seed()
                app = self.app()
                async with app.run_test(size=(150, 42)) as pilot:
                    await self.sign_in(app, pilot)
                    self.assertIn('未提交的单票候选', self.chat(app))
                    self.assertIsNone(app.agent)
                    if mode == 'before_agent':
                        await self.send(app, pilot, '/cancel')
                    elif mode == 'after_agent':
                        app.ensure_agent()
                        self.assertIsNotNone(app.agent.pending_intent)
                        await pilot.press('f4')
                    elif mode == 'new_chat':
                        old_chat = app.conversation.chat
                        app.request_new_chat()
                        await self.await_state(pilot, lambda: isinstance(app.screen, Approval)
                                               and app.screen.is_mounted and bool(app.screen.query('#cancel')))
                        app.screen.answer(True)  # program-simulated local chat reset
                        await self.await_state(pilot, lambda: app.conversation.chat != old_chat)
                        app.choose_conversation(old_chat)
                        self.assertEqual(app.conversation.chat, old_chat)
                    elif mode == 'task':
                        # Isolated preseeded fixture task; not a model-created
                        # task and not evidence of a human management approval.
                        with closing(sqlite3.connect(self.book)) as db, db:
                            db.execute('''INSERT INTO tasks(task_id,user_id,company_id,task_type,year,month,context_json,status)
                                VALUES ('program-fixture-task','U001','C001','missing_purpose',2026,9,'{}','ACTIVE')''')
                        app.task_route = ('C001','program-fixture-task')
                        app.continue_task()
                        self.assertIsNone(app.agent.pending_intent)
                    else:
                        # A process interruption after begin has no new trusted
                        # terminal state; it must not revive the prior snapshot.
                        app.conversation.begin('有新的要求，本轮尚未处理完。', 'mock')
                    self.assertIsNone(app.conversation.history().get('invoice_pending'))
                reopened = self.app({'invoice_no': 'F006'})
                async with reopened.run_test(size=(150, 42)) as pilot:
                    await self.sign_in(reopened, pilot)
                    await self.send(reopened, pilot, '编号 F006。')
                    await self.await_state(pilot, lambda: bool(reopened.records) and not reopened.busy)
                    self.assertNotIsInstance(reopened.screen, Approval)
                    self.assertFalse(reopened.agent.pending_intent['change'])
        self.no_write()

    async def test_changed_permission_or_actor_cannot_restore_candidate(self):
        for column in ('can_read','can_modify'):
            with self.subTest(permission=column):
                await self.seed()
                other = SessionStore(self.sessions, self.book, 'U002')
                self.assertIsNone(other.history().get('invoice_pending'))
                other.close()
                with closing(sqlite3.connect(self.book)) as db, db:
                    db.execute(f"UPDATE permissions SET {column}=0 WHERE user_id='U001' AND company_id='C001'")
                try:
                    app = self.app({'invoice_no': 'F006'})
                    async with app.run_test(size=(150, 42)) as pilot:
                        await self.sign_in(app, pilot)
                        self.assertNotIn('已找回未提交的单票候选', self.chat(app))
                        self.assertIn('权限', self.chat(app))
                        await self.send(app, pilot, '继续，编号 F006。')
                        await self.await_state(pilot, lambda: bool(app.records) and not app.busy)
                        self.assertNotIsInstance(app.screen, Approval)
                        self.assertFalse(app.agent.update_session.confirmations)
                finally:
                    with closing(sqlite3.connect(self.book)) as db, db:
                        db.execute("UPDATE permissions SET can_read=1,can_modify=1 WHERE user_id='U001' AND company_id='C001'")
        self.no_write()


if __name__ == '__main__':
    unittest.main()
