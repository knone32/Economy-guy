import unittest
from app.importer import initialize_database
from tests.helpers import DatabaseTestCaseMixin, EXCEL


class ImporterTests(DatabaseTestCaseMixin, unittest.TestCase):
    def test_imports_all_expected_records(self):
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 40)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM bank_transactions").fetchone()[0], 48)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0], 2)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 2)

    def test_reinitializing_does_not_duplicate_records(self):
        self.connection.close()
        with self.assertRaises(FileExistsError):
            initialize_database(EXCEL, self.db_path)
        from app.database import connect
        connection = connect(self.db_path)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 40)
        finally:
            connection.close()

    def test_important_fields_are_preserved(self):
        row = self.connection.execute("SELECT invoice_date, amount_cents, purpose FROM invoices WHERE company_id=? AND invoice_no=?", ("C001", "F001")).fetchone()
        self.assertEqual((row["invoice_date"], row["amount_cents"], row["purpose"]), ("2026-09-01", 50000, "购买办公文具"))
