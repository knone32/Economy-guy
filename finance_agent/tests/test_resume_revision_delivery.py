"""Program delivery check; no model API or invoice approval."""
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from app.cli_workspaces import import_workspace
from app.model_config import DEFAULT_TEMPLATE
from app.tui import AgentWorkspace
from tests import test_tui_p0 as helpers
from tests.test_model_intent import call


class ResumeRevisionDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_resume_displays_claimed_revision_and_rejects_old_revision(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            book = root / 'fictional.sqlite3'
            import_workspace(helpers.FIXTURE, book)
            app = AgentWorkspace(book, DEFAULT_TEMPLATE, root / 'none.json',
                model=lambda *_: call('change_invoice', {
                    'company_id': 'C001', 'year': 2026, 'month': 9,
                    'field': 'remark', 'new_value': '待复核'}),
                session_path=root / 'sessions.sqlite3', trace_path=root / 'trace.jsonl')
            app.mode = 'mock'
            async with app.run_test(size=(150, 42)) as pilot:
                await helpers.P0Test.sign_in(self, app, pilot)
                await helpers.P0Test.send(self, app, pilot,
                    '甲企业2026年9月有张票，备注填「待复核」，票号稍后给。')
                await helpers.P0Test.await_state(self, pilot, lambda: bool(app.records) and not app.busy)
                app.pause_invoice_selection()
                candidate, = app.conversation.list_invoice_candidates()
                old_revision = candidate['revision']
                app.resume_invoice_selection(f"{candidate['id']} {old_revision}")
                candidate_id, claimed_revision = app.conversation.invoice_token
                self.assertEqual(claimed_revision, old_revision + 1)
                chat = '\n'.join(line.text for line in app.workspace_widget('#chat-log').lines)
                self.assertRegex(chat, f'已选择 {candidate_id} · 修订\\s+{claimed_revision}。')
                with self.assertRaises(ValueError):
                    app.conversation.resume_invoice_candidate(candidate_id, old_revision)
                self.assertIsNone(app.agent)
                with closing(sqlite3.connect(book)) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
