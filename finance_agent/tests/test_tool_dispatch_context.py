"""Reject mismatched trusted SQL context before opening capability resources."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.assistant_config import configure
from app.business_sql import BusinessSQL
from app.cli_workspaces import import_workspace
from app.provenance import ScopeProof
from app.tool_registry import handle_tool


class DispatchContextTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.book = self.root / 'fictional.sqlite3'
        import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', self.book)
        values = {'company_id': ['C001'], 'periods': [(2026, 9)]}
        self.workspace = BusinessSQL(self.book, 'U001', ScopeProof('U001', values, dict.fromkeys(values, 'user_current')))
        self.addCleanup(self.workspace.close)
        self.args = json.dumps({'sql': 'SELECT COUNT(*) AS n FROM invoices'})

    def dispatch(self, *, actor='U001', path=None, workspace=None):
        selections = {}
        result = handle_tool('query_business_sql', self.args, actor, path or self.book,
                             sql_workspace=workspace, invoice_selections=selections)
        return result, selections

    def test_missing_mismatched_actor_and_path_reject_without_any_database_open(self):
        missing = self.root / 'must-not-create.sqlite3'
        existing = self.root / 'must-not-open.sqlite3'
        existing.write_bytes(b'Unrelated existing file must not be opened as SQLite.')
        for actor, path, workspace in (
                ('U001', missing, None),
                ('U002', self.book, self.workspace),
                ('U001', missing, self.workspace),
                ('U001', existing, self.workspace)):
            with self.subTest(actor=actor, path=path, workspace=workspace):
                with patch('app.assistant_config.tool_enabled') as capabilities, \
                     patch('app.assistant_config.dispatch_allowed') as assistant, \
                     patch('sqlite3.connect', side_effect=AssertionError('No SQLite open permitted')) as opened:
                    result, selections = self.dispatch(actor=actor, path=path, workspace=workspace)
                self.assertEqual(result['status'], 'DENIED')
                self.assertEqual(result['evidence']['source'], 'tool_context')
                self.assertIsNone(result['data'])
                self.assertFalse(selections)
                capabilities.assert_not_called()
                assistant.assert_not_called()
                opened.assert_not_called()
                self.assertFalse(missing.exists())
                self.assertEqual(existing.read_bytes(), b'Unrelated existing file must not be opened as SQLite.')

    def test_valid_unconfigured_legacy_book_still_reads_without_schema_changes(self):
        before = self.book.read_bytes()
        result, _ = self.dispatch(workspace=self.workspace)
        self.assertEqual(result['status'], 'SUCCESS', result)
        self.assertEqual(result['data']['rows'], [(10,)])
        with closing(sqlite3.connect(self.book)) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='assistant_config'").fetchone())
        self.assertEqual(self.book.read_bytes(), before)

    def test_valid_context_still_obeys_tool_disable_and_reenable(self):
        configure(self.book, 'U001', 'tool', 'query_business_sql', {}, enabled=False,
                  capabilities={'assistant.manage'})
        result, selections = self.dispatch(workspace=self.workspace)
        self.assertEqual(result['status'], 'DENIED')
        self.assertEqual(result['evidence']['source'], 'tool_configuration')
        self.assertFalse(selections)
        configure(self.book, 'U001', 'tool', 'query_business_sql', {}, enabled=True,
                  expected_revision=1, capabilities={'assistant.manage'})
        result, _ = self.dispatch(workspace=self.workspace)
        self.assertEqual(result['status'], 'SUCCESS', result)

    def test_valid_workspace_does_not_bypass_current_assistant_scope(self):
        configure(self.book, 'U001', 'assistant', 'no-sql', {'name': '只查单票',
                  'tools': ['get_invoice'], 'skills': []}, capabilities={'assistant.manage'})
        result = handle_tool('query_business_sql', self.args, 'U001', self.book,
                             sql_workspace=self.workspace, assistant_id='no-sql')
        self.assertEqual(result['status'], 'DENIED')
