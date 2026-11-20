"""Assistant reads must not initialize workbooks; synthetic DBs, zero API."""
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from app.assistant_config import (
    configure, connect, dispatch_allowed, read, refresh_assistant, tool_enabled, use_skill)
from app.cli_workspaces import import_workspace
from app.stage2_schema import open_existing
from app.model_config import DEFAULT_TEMPLATE
from app.tui import AgentWorkspace
from tests import test_tui_p0 as helpers


class AssistantReadonlyTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.book = self.root / 'fictional.sqlite3'
        import_workspace(helpers.FIXTURE, self.book)

    def test_missing_books_are_never_created_by_reads_or_configuration(self):
        actions = {
            'tool_enabled': lambda path: tool_enabled(path, 'U001', 'get_invoice'),
            'refresh': lambda path: refresh_assistant(SimpleNamespace(
                assistant_id='missing', db_path=path, user_id='U001')),
            'skill': lambda path: use_skill(path, 'U001', 'missing', 'C001', []),
            'dispatch': lambda path: dispatch_allowed(path, 'U001', 'missing', 'get_invoice'),
            'initialize': lambda path: connect(path),
            'configure': lambda path: configure(path, 'U001', 'tool', 'get_invoice', {},
                capabilities={'assistant.manage'}),
        }
        for name, action in actions.items():
            with self.subTest(entry=name):
                missing = self.root / (name + '.sqlite3')
                with self.assertRaises(sqlite3.OperationalError):
                    action(missing)
                self.assertFalse(missing.exists())

    def test_legacy_reads_preserve_schema_and_reject_unregistered_assistants(self):
        with closing(open_existing(self.book, readonly=True)) as db:
            before = db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall()
            self.assertFalse(any(row['name'] == 'assistant_config' for row in before))
            self.assertIsNone(read(db, 'U001', 'assistant', 'missing'))
        self.assertTrue(tool_enabled(self.book, 'U001', 'get_invoice'))
        self.assertFalse(dispatch_allowed(self.book, 'U001', 'missing', 'get_invoice'))
        with self.assertRaises(PermissionError):
            refresh_assistant(SimpleNamespace(assistant_id='missing', db_path=self.book, user_id='U001'))
        with self.assertRaises(PermissionError):
            use_skill(self.book, 'U001', 'missing', 'C001', [])
        with closing(open_existing(self.book, readonly=True)) as db:
            self.assertEqual(db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall(), before)


class AssistantInitializationUITests(unittest.IsolatedAsyncioTestCase):
    async def test_f5_initializes_configuration_only_in_an_existing_workbook(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            book = root / 'fictional.sqlite3'
            import_workspace(helpers.FIXTURE, book)
            with closing(open_existing(book, readonly=True)) as db:
                before = list(db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no'))
            app = AgentWorkspace(book, DEFAULT_TEMPLATE, root / 'none.json', session_path=None)
            async with app.run_test(size=(150, 42)) as pilot:
                await helpers.P0Test.sign_in(self, app, pilot)
                await pilot.press('f5')
                await pilot.pause()
                with closing(open_existing(book, readonly=True)) as db:
                    self.assertTrue(db.execute("SELECT 1 FROM sqlite_master WHERE name='assistant_config'").fetchone())
                    self.assertEqual(list(db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no')), before)
                    self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
