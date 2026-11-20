"""Public candidate lifecycle and stale-revision counterexamples; no HTTP."""
from copy import deepcopy
from contextlib import closing
import os
import sqlite3
import unittest
from app.session_store import SessionStore
from app.tui_screens import Approval
from tests import test_ticket_pending_recovery_20261120 as recovery
from tests.test_model_intent import final


class DurableTicketTests(unittest.IsolatedAsyncioTestCase):
    setUp = recovery.PendingTicketRecoveryTests.setUp
    app = recovery.PendingTicketRecoveryTests.app
    seed = recovery.PendingTicketRecoveryTests.seed
    chat = staticmethod(recovery.PendingTicketRecoveryTests.chat)
    no_write = recovery.PendingTicketRecoveryTests.no_write
    sign_in = recovery.PendingTicketRecoveryTests.sign_in
    send = recovery.PendingTicketRecoveryTests.send
    await_state = recovery.PendingTicketRecoveryTests.await_state

    async def test_actual_new_chat_explicit_resume_fresh_preview(self):
        await self.seed()
        app = self.app({'invoice_no':'F006'})
        async with app.run_test(size=(150,42)) as pilot:
            await self.sign_in(app,pilot)
            old_chat = app.conversation.chat
            app.request_new_chat()
            await self.await_state(pilot,lambda: isinstance(app.screen,Approval) and app.screen.is_mounted)
            app.screen.answer(True)  # program-simulated local chat choice
            await self.await_state(pilot,lambda: app.conversation.chat != old_chat)
            self.assertIsNone(app.resume_invoice_pending)
            self.assertIsNone(app.agent)
            await self.send(app,pilot,'/pending')
            row, = app.conversation.list_invoice_candidates()
            self.assertIn(row['id'],self.chat(app))
            self.assertEqual(row['state'],'PAUSED')
            await self.send(app,pilot,f"/resume {row['id']} {row['revision']}")
            with closing(sqlite3.connect(self.book)) as db,db:
                db.execute("UPDATE invoices SET remark='新聊天前独立原值' WHERE company_id='C001' AND invoice_no='F006'")
            await self.send(app,pilot,'继续选中的单票，编号 F006，先给预览。')
            await self.await_state(pilot,lambda: isinstance(app.screen,Approval))
            self.assertIn('原值　新聊天前独立原值',app.screen.body)
            self.assertIn('新值　跨重启待复核',app.screen.body)
            self.assertFalse(app.agent.update_session.confirmations)
            persisted, = app.conversation.list_invoice_candidates()
            self.assertEqual(persisted['id'],row['id'])
            self.assertGreater(persisted['revision'],row['revision'])
            app.screen.answer(False)
            await self.await_state(pilot,lambda: not app.busy)
            self.assertEqual(app.conversation.list_invoice_candidates(),[])
            with closing(sqlite3.connect(self.book)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)

    async def test_model_pause_and_stop_have_different_durable_terminal_states(self):
        for action, expected in (('pause','PAUSED'),('stop','CANCELLED')):
            with self.subTest(action=action):
                await self.seed()
                app = self.app()
                app.model_override = lambda *_: final(turn_action=action)
                async with app.run_test(size=(150,42)) as pilot:
                    await self.sign_in(app,pilot)
                    candidate_id = app.conversation.list_invoice_candidates()[0]['id']
                    await self.send(app,pilot,'先缓缓，之后再说。' if action=='pause' else '取消这项，不办了。')
                    await self.await_state(pilot,lambda: bool(app.records) and not app.busy)
                    self.assertIsNone(app.agent.pending_intent)
                    with app.conversation.connection() as db:
                        state = db.execute('SELECT state FROM invoice_candidates WHERE id=?',(candidate_id,)).fetchone()[0]
                    self.assertEqual(state,expected)
                    self.assertEqual(bool(app.conversation.list_invoice_candidates()),action=='pause')
                # Retire paused fixture before seeding the next independent case.
                store = SessionStore(self.sessions,self.book,'U001')
                store.set_invoice_pending(None)
                store.close()
        self.no_write()
    async def test_new_chat_lists_explicit_candidate_and_terminal_cancel_cannot_revive(self):
        original = await self.seed()
        store = SessionStore(self.sessions, self.book, 'U001')
        self.addCleanup(store.close)
        item, = store.list_invoice_candidates()
        old_chat = store.chat
        store.new_chat(None)
        self.assertNotEqual(store.chat, old_chat)
        self.assertIsNone(store.history()['invoice_pending'])
        self.assertEqual(store.list_invoice_candidates()[0]['id'], item['id'])
        restored = store.resume_invoice_candidate(item['id'], item['revision'])
        self.assertEqual(restored['source_request'], original['source_request'])
        token = store.invoice_token
        store.set_invoice_pending(None)
        self.assertEqual(store.list_invoice_candidates(), [])
        with self.assertRaises(ValueError):
            store.resume_invoice_candidate(*token)
        self.no_write()

    async def test_stale_revision_cannot_overwrite_cancel_or_new_content(self):
        original = await self.seed()
        store = SessionStore(self.sessions, self.book, 'U001')
        self.addCleanup(store.close)
        item, = store.list_invoice_candidates()
        store.resume_invoice_candidate(item['id'], item['revision'])
        stale = store.invoice_token
        newer = deepcopy(original)
        newer['change']['new_value'] = ['新修订']
        store.set_invoice_pending(newer)
        current = store.invoice_token
        store.invoice_token = stale  # delayed trusted window, not model token
        with self.assertRaises(ValueError):
            store.set_invoice_pending(original)
        self.assertEqual(store.list_invoice_candidates()[0]['pending']['change']['new_value'], ['新修订'])
        store.invoice_token = current
        store.set_invoice_pending(None)
        store.invoice_token = stale
        with self.assertRaises(ValueError):
            store.set_invoice_pending(original)
        self.assertEqual(store.list_invoice_candidates(), [])
        self.no_write()

    async def test_stale_visible_approval_cannot_submit_after_revision_changed(self):
        await self.seed()
        app = self.app({'invoice_no':'F006'})
        async with app.run_test(size=(150,42)) as pilot:
            await self.sign_in(app,pilot)
            await self.send(app,pilot,'继续单票，编号 F006，给我预览。')
            await self.await_state(pilot,lambda: isinstance(app.screen,Approval))
            candidate_id, revision = app.conversation.invoice_token
            # Independent writer represents a later revision, after this
            # window's preview. Never changes invoice data or grants approval.
            with app.conversation.connection() as db:
                db.execute("UPDATE invoice_candidates SET state='CANCELLED',revision=revision+1 WHERE id=? AND revision=?",
                           (candidate_id,revision))
            app.screen.answer(True)  # deliberately confirm a stale visible UI
            await self.await_state(pilot,lambda: not app.busy)
            self.assertEqual(app.conversation.list_invoice_candidates(),[])
            with app.conversation.connection() as db:
                self.assertEqual(tuple(db.execute('SELECT state,revision FROM invoice_candidates WHERE id=?',(candidate_id,)).fetchone()),
                                 ('CANCELLED',revision+1))
        self.no_write()

    async def test_same_content_resume_claim_retires_old_visible_approval(self):
        await self.seed()
        old = self.app({'invoice_no':'F006'})
        async with old.run_test(size=(150,42)) as old_pilot:
            await self.sign_in(old,old_pilot)
            await self.send(old,old_pilot,'继续单票，编号 F006，给我预览。')
            await self.await_state(old_pilot,lambda: isinstance(old.screen,Approval))
            old_chat = old.conversation.chat
            candidate_id,revision = old.conversation.invoice_token
            original, = old.conversation.list_invoice_candidates()
            self.assertEqual(original['state'],'PAUSED')
            old.conversation.validate_invoice_revision()
            # Ordinary same-path windows are locked out. Use a second supported
            # session path to the same isolated SQLite file to exercise a late
            # window's revision guard; no lock/candidate/approval is mocked.
            alternate = self.root/'second-session-path'
            alternate.mkdir()
            alias = alternate/'sessions.sqlite3'
            os.link(self.sessions,alias)
            self.assertTrue(os.path.samefile(self.sessions,alias))
            with old.conversation.connection() as db:
                self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'delete')
            new = self.app()
            new.session_path = alias
            async with new.run_test(size=(150,42)) as new_pilot:
                await self.sign_in(new,new_pilot)
                new.request_new_chat()
                await self.await_state(new_pilot,lambda: isinstance(new.screen,Approval) and new.screen.is_mounted)
                new.screen.answer(True)  # program-simulated new-chat choice
                await self.await_state(new_pilot,lambda: new.conversation.chat != old_chat)
                await self.send(new,new_pilot,f'/resume {candidate_id} {revision}')
                self.assertEqual(new.resume_invoice_pending,original['pending'])
                self.assertIsNone(new.agent)  # resume restores no draft/approval
                # First red: unchanged revision lets this exact guard pass.
                with self.assertRaises(ValueError):
                    old.conversation.validate_invoice_revision()
                self.assertEqual(new.conversation.invoice_token,(candidate_id,revision+1))
                with new.conversation.connection() as db:
                    self.assertEqual(tuple(db.execute('SELECT candidate_id,candidate_revision FROM chats WHERE id=?',
                                                     (old_chat,)).fetchone()),(candidate_id,revision))
                with self.assertRaises(ValueError):
                    new.conversation.resume_invoice_candidate(candidate_id,revision)
            # Return to the old App's Textual context before answering its UI.
            old.screen.answer(True)  # deliberately confirm the old window
            await self.await_state(old_pilot,lambda: not old.busy)
            current, = old.conversation.list_invoice_candidates()
            self.assertEqual(current['pending'],original['pending'])
            self.assertEqual(current['revision'],revision+1)
            with old.conversation.connection() as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.no_write()

    async def test_same_store_resume_claim_invalidates_old_token_without_file_alias(self):
        await self.seed()
        store = SessionStore(self.sessions,self.book,'U001')
        self.addCleanup(store.close)
        store.pause_invoice_candidate()
        old_chat,old_token = store.chat,store.invoice_token
        before, = store.list_invoice_candidates()
        store.new_chat(None)
        new_chat = store.chat
        restored = store.resume_invoice_candidate(*old_token)
        new_token = store.invoice_token
        self.assertEqual(restored,before['pending'])
        self.assertEqual(new_token,(old_token[0],old_token[1]+1))
        # Restore only the old owner's captured view in the same service;
        # candidate contents/SQLite/locks are never altered by this fixture.
        store.chat,store.invoice_token = old_chat,old_token
        with self.assertRaises(ValueError):
            store.validate_invoice_revision()
        store.chat,store.invoice_token = new_chat,new_token
        store.validate_invoice_revision()
        store.chat = 'not-an-active-chat'
        with self.assertRaises(ValueError):
            store.resume_invoice_candidate(*new_token)
        store.chat = new_chat
        store.validate_invoice_revision()  # failed target bind rolled claim back
        current, = store.list_invoice_candidates()
        self.assertEqual(current['pending'],before['pending'])
        self.assertEqual(current['revision'],new_token[1])
        with store.connection() as db:
            self.assertEqual(tuple(db.execute('SELECT candidate_id,candidate_revision FROM chats WHERE id=?',(old_chat,)).fetchone()),old_token)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.no_write()
