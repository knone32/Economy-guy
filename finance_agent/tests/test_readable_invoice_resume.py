"""Original persistent candidate, business selection UI; no model or approval."""
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from app.business_sources import bind_request
from app.cli_workspaces import import_workspace
from app.model_config import DEFAULT_TEMPLATE
from app.session_store import SessionStore
from app.tui import AgentWorkspace
from app.tui_screens import Choices
from tests import test_tui_p0 as helpers


class ReadableInvoiceResumeTests(unittest.IsolatedAsyncioTestCase):
    async def test_business_choice_resumes_current_revision_without_exposing_tokens(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);book=root/'fictional.sqlite';sessions=root/'sessions.sqlite'
            import_workspace(helpers.FIXTURE,book)
            request='C001 2026年9月F002这张发票调整用途，具体内容稍后提供。'
            pending=bind_request({'company_id':'C001','year':2026,'month':9,
                'invoice_no':'F002','field':'purpose'},None,actor='U001',book=book,
                current_id='program-source',current_request=request)
            with closing(SessionStore(sessions,book,'U001')) as store:
                store.set_invoice_pending(pending);store.pause_invoice_candidate()
                candidate,=store.list_invoice_candidates()
            with closing(sqlite3.connect(book)) as db:
                before=list(db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no'))
            app=AgentWorkspace(book,DEFAULT_TEMPLATE,root/'none.json',
                model=lambda *_:self.fail('No model needed for resume selection'),
                session_path=sessions,trace_path=root/'trace.jsonl')
            app.mode='mock'
            async with app.run_test(size=(150,42)) as pilot:
                await helpers.P0Test.sign_in(self,app,pilot)
                await pilot.click('#go-tasks');await pilot.pause()
                await pilot.click('#continue-invoice');await pilot.pause()
                self.assertIsInstance(app.screen,Choices)
                label=app.screen.choices[0][0]
                for value in ('甲企业','2026 年 9 月','F002','用途','新内容','暂缓','尚未保存'):
                    self.assertIn(value,label)
                for token in (candidate['id'],'company_id','invoice_no','/resume','修订'):
                    self.assertNotIn(token,label)
                await pilot.click('#choice-0');await pilot.pause()
                self.assertEqual(app.conversation.invoice_token,(candidate['id'],candidate['revision']+1))
                self.assertEqual(app.resume_invoice_pending['scope']['invoice_no'],['F002'])
                self.assertIsNone(app.agent)
                chat='\n'.join(line.text for line in app.workspace_widget('#chat-log').lines)
                self.assertIn('已恢复',chat);self.assertNotIn(candidate['id'],chat)
                with self.assertRaises(ValueError):
                    app.conversation.resume_invoice_candidate(candidate['id'],candidate['revision'])
                with closing(sqlite3.connect(book)) as db:
                    self.assertEqual(before,list(db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no')))
                    self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)
