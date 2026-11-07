"""Final workbook acceptance on isolated official fixtures."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch

from app.cli_workspaces import BASE_COLUMNS, _snapshot, missing_migrations, rules_available, upgrade_workspace, workspace_users
from app.importer import initialize_database
from app.queries import QueryError, available_periods
from app.stage2_schema import open_existing
from app.tui_local import recent_workbooks, remember_workbook, startup_workbook

FIXTURE = Path(__file__).parent / "fixtures" / "example.xlsx"


class FinalWorkbookTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.db = self.folder / "original.db"
        initialize_database(FIXTURE, self.db)

    def snapshot(self, path):
        with closing(open_existing(path, readonly=True)) as db:
            return _snapshot(db, BASE_COLUMNS)

    def test_upgrade_backup_preserves_business_and_does_not_seed_rules(self):
        with closing(open_existing(self.db)) as db, db:
            db.execute("INSERT INTO users (user_id,name) VALUES (?,?)", ("U003", "第三位模拟账号"))
        before = self.snapshot(self.db)
        backup = upgrade_workspace(self.db, backup=True)
        self.assertNotEqual(backup, self.db)
        self.assertEqual(before, self.snapshot(backup))
        self.assertEqual(before, self.snapshot(self.db))
        self.assertTrue(missing_migrations(backup))
        self.assertFalse(missing_migrations(self.db))
        self.assertFalse(rules_available(self.db))
        self.assertEqual(len(workspace_users(self.db)), 3)

    def test_ddl_failure_rolls_back_and_keeps_verified_backup(self):
        before = self.snapshot(self.db)
        with patch("app.cli_workspaces.REFERENCE_DDL", "INVALID DDL;"):
            with self.assertRaises(sqlite3.OperationalError):
                upgrade_workspace(self.db, backup=True)
        self.assertEqual(before, self.snapshot(self.db))
        self.assertIn("invoice_audit", missing_migrations(self.db))
        backup, = self.folder.glob("*-backup-*.sqlite3")
        self.assertEqual(before, self.snapshot(backup))

    def test_recent_priority_and_unavailable_path(self):
        upgrade_workspace(self.db)
        prefs = self.folder / "prefs.json"
        missing = self.folder / "missing.sqlite3"
        remember_workbook(prefs, self.db)
        self.assertEqual(recent_workbooks(prefs), [self.db])
        self.assertEqual(startup_workbook(missing, prefs, restore=True), (self.db, False))
        self.assertEqual(startup_workbook(missing, prefs, restore=False), (missing, True))
        remember_workbook(prefs, missing)
        self.assertEqual(startup_workbook(self.db, prefs, restore=True), (missing, True))

    def test_periods_use_real_counts_and_acl(self):
        with closing(open_existing(self.db, readonly=True)) as db:
            rows = available_periods(db, "U001", "C001")
            self.assertEqual(rows[0], ("2026-09", 10, 12))
            with self.assertRaises(QueryError):
                available_periods(db, "U002", "C002")
        with closing(open_existing(self.db)) as db, db:
            db.execute("DELETE FROM invoices WHERE company_id='C001'")
            db.execute("DELETE FROM bank_transactions WHERE company_id='C001'")
            self.assertEqual(available_periods(db, "U001", "C001"), [])
