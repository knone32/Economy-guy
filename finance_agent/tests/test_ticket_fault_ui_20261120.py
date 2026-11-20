"""Actual Workbench/Pilot fault evidence, with PROGRAM SIMULATED confirmation.

No model HTTP or human approval. Only temporary official fictional databases
are written. Set TICKET_UI_EVIDENCE_DIR to retain rendered UI captures locally.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from textual.widgets import Collapsible, Static

from app.cli_workspaces import import_workspace
from app.model_config import DEFAULT_TEMPLATE
from app.tui import AgentWorkspace
from app.tui_screens import Approval
from app.updates import inspect_request
from tests import test_tui_p0 as helpers
from tests.test_model_intent import call


class TicketFaultWorkbenchTests(unittest.IsolatedAsyncioTestCase):
    await_state = helpers.P0Test.await_state
    sign_in = helpers.P0Test.sign_in
    send = helpers.P0Test.send

    @staticmethod
    def logs(app):
        return {name: '\n'.join(line.text for line in app.workspace_widget('#' + name).lines)
                for name in ('chat-log', 'business-log')}

    @staticmethod
    def capture(app, name, observed):
        destination = os.environ.get('TICKET_UI_EVIDENCE_DIR')
        if destination:
            folder = Path(destination)
            folder.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename=name + '.svg', path=str(folder))
            (folder / (name + '.json')).write_text(json.dumps({
                'evidence_kind': 'offline_program_fault_Textual_Pilot',
                'confirmation': 'PROGRAM_SIMULATED_NOT_HUMAN',
                'model_http_calls': 0, **observed}, ensure_ascii=False, indent=2), encoding='utf-8')

    async def test_unknown_result_is_visible_retry_blocked_and_restart_checks_original_request(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            book = root / 'fictional.sqlite3'
            sessions = root / 'sessions.sqlite3'
            import_workspace(helpers.FIXTURE, book)
            with closing(sqlite3.connect(book)) as db, db:
                db.execute('CREATE TABLE program_update_events(company_id TEXT, invoice_no TEXT)')
                db.execute('''CREATE TRIGGER program_count_updates AFTER UPDATE OF remark ON invoices
                              BEGIN INSERT INTO program_update_events VALUES (NEW.company_id,NEW.invoice_no); END''')

            def counts():
                with closing(sqlite3.connect(book)) as db:
                    return {
                        'remark': db.execute("SELECT remark FROM invoices WHERE company_id='C001' AND invoice_no='F006'").fetchone()[0],
                        'audits': db.execute('SELECT request_id,status FROM invoice_audit').fetchall(),
                        'updates': db.execute('SELECT company_id,invoice_no FROM program_update_events').fetchall(),
                    }

            args = {'company_id': 'C001', 'year': 2026, 'month': 9, 'invoice_no': 'F006',
                    'field': 'remark', 'new_value': '程序模拟确认故障测试'}
            app = AgentWorkspace(book, DEFAULT_TEMPLATE, root / 'no-profiles.json',
                                 model=lambda *_: call('change_invoice', args),
                                 session_path=sessions, trace_path=root / 'fault.jsonl')
            app.mode = 'mock'
            async with app.run_test(size=(150, 42)) as pilot:
                await self.sign_in(app, pilot)
                await self.send(app, pilot, '甲企业2026年9月 F006 备注填写「程序模拟确认故障测试」，先给我预览。')
                await self.await_state(pilot, lambda: isinstance(app.screen, Approval)
                                       and app.screen.is_mounted and bool(app.screen.query('#approve')))
                preview = app.screen.body
                self.assertIn('原值　按月结算', preview)
                self.assertIn('新值　程序模拟确认故障测试', preview)
                self.assertEqual(counts(), {'remark': '按月结算', 'audits': [], 'updates': []})
                draft, = app.agent.update_session.drafts.values()
                request_id, fingerprint = draft.request_id, draft.fingerprint()
                original_session_id = app.agent.update_session.session_id
                expected = {'remark': '程序模拟确认故障测试',
                            'audits': [(request_id, 'COMMITTED')], 'updates': [('C001', 'F006')]}
                self.capture(app, '01-program-preview', {'preview': preview, 'sql': counts()})

                def lose_response_after_save(*_):
                    # Verify the real production transaction and audit have
                    # committed before injecting exactly one lost response.
                    self.assertEqual(counts(), expected)
                    raise sqlite3.OperationalError('PROGRAM FAULT: response lost after actual save')

                with patch('app.updates._readback', side_effect=lose_response_after_save) as lost:
                    # PROGRAM SIMULATED confirmation through the actual modal;
                    # this is not a desktop click and never human evidence.
                    app.screen.query_one('#approve').press()
                    await self.await_state(pilot, lambda: not app.busy)
                    lost.assert_called_once()
                await pilot.pause()
                self.assertEqual(app.agent.write_receipt['status'], 'UNKNOWN_OUTCOME')
                self.assertEqual(app.agent.write_receipt['request_id'], request_id)
                self.assertFalse(app.agent.update_session.drafts)
                self.assertFalse(app.agent.update_session.confirmations)
                visible = self.logs(app)
                note = str(app.workspace_widget('#chat-note', Static).renderable)
                self.assertIn('发票修改结果未知', visible['chat-log'])
                self.assertIn('先核查审计，再决定是否重试', visible['chat-log'])
                self.assertIn('结果未知，请核查审计', visible['business-log'])
                self.assertIn('结果未知', note)
                self.assertNotIn('保存成功', '\n'.join(visible.values()) + note)
                self.assertNotIn('已保存并回读', '\n'.join(visible.values()) + note)
                self.assertTrue(app.workspace_widget('#business-log').display)
                self.assertEqual(counts(), expected)
                self.capture(app, '02-unknown-visible', {'request_id': request_id, 'note': note,
                                                       **visible, 'sql': counts()})

                # Same request cannot acquire another approval/transaction;
                # a fresh editing request through the UI must also stop.
                with patch('app.agent.commit_invoice_update', side_effect=AssertionError('must not rewrite')):
                    self.assertEqual(app.agent.commit_update(request_id, fingerprint)['status'], 'UNKNOWN_OUTCOME')
                old_count = len(app.records)
                await self.send(app, pilot, '/edit 把甲企业 F006 的备注改成另一次改动')
                await self.await_state(pilot, lambda: len(app.records) > old_count and not app.busy)
                self.assertNotIsInstance(app.screen, Approval)
                self.assertFalse(app.agent.update_session.drafts)
                self.assertEqual(counts(), expected)
                saved = app.conversation.history()['turns'][0]
                self.assertEqual((saved['state'], saved['lookup']), ('UNKNOWN_OUTCOME', request_id))

            # New App/login invokes the real read-only recovery adapter. Keep
            # the original UNKNOWN record; do not manufacture a restored draft.
            restarted = AgentWorkspace(book, DEFAULT_TEMPLATE, root / 'no-profiles.json',
                                       model=lambda *_: helpers.FINAL,
                                       session_path=sessions, trace_path=root / 'restart.jsonl')
            restarted.mode = 'mock'
            lookups = []

            def record_recovery(path, actor, lookup):
                result = inspect_request(path, actor, lookup)
                lookups.append((lookup, result))
                return result

            with patch('app.tui_sessions.inspect_request', side_effect=record_recovery):
                async with restarted.run_test(size=(150, 42)) as pilot:
                    await self.sign_in(restarted, pilot)
                    await pilot.pause()
                    restored = self.logs(restarted)
                    self.assertIn('已在 SQLite 成功审计中核实上次提交', restored['chat-log'])
                    self.assertTrue(any(lookup == request_id and result['status'] == 'COMMITTED'
                                        and result['data']['current_matches'] for lookup, result in lookups))
                    self.assertIsNone(restarted.agent)
                    self.assertEqual(counts(), expected)
                    self.capture(restarted, '03-restarted-login', {'request_id': request_id, **restored,
                                                                 'sql': counts()})

                    # Open actual execution-record widgets, expand the original
                    # operation, and inspect rendered request/audit details.
                    restarted.show('records')
                    await self.await_state(pilot, lambda: bool(restarted.screen.query(f"#operation-{saved['seq']}")))
                    record = restarted.screen.query_one(f"#operation-{saved['seq']}", Collapsible)
                    record.collapsed = False
                    await pilot.pause()
                    detail = '\n'.join(str(widget.renderable) for widget in record.query(Static))
                    self.assertIn(request_id, detail)
                    self.assertIn('成功审计', detail)
                    self.assertIn('程序模拟确认故障测试', detail)
                    self.assertIn('审计已证实提交', str(record.title))
                    self.capture(restarted, '04-restarted-original-record', {
                        'request_id': request_id, 'record_title': str(record.title),
                        'record_details': detail, 'sql': counts()})

                    restarted.ensure_agent()
                    self.assertNotEqual(restarted.agent.update_session.session_id, original_session_id)
                    self.assertIsNone(restarted.agent.pending_intent)
                    self.assertFalse(restarted.agent.update_session.drafts)
                    self.assertFalse(restarted.agent.update_session.confirmations)
                    self.assertEqual(restarted.agent.commit_update(request_id, fingerprint)['status'], 'DENIED')
                    self.assertEqual(counts(), expected)


if __name__ == '__main__':
    unittest.main()
