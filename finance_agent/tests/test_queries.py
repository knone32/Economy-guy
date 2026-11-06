import unittest
from app.queries import QueryError, get_invoice, list_bank_transactions, list_invoices, list_missing_purpose_invoices
from tests.helpers import DatabaseTestCaseMixin


class QueryTests(DatabaseTestCaseMixin, unittest.TestCase):
    def test_filters_company_and_month(self):
        rows = list_invoices(self.connection, "U001", "C001", 2026, 9)
        self.assertEqual(len(rows), 10); self.assertTrue(all(r["company_id"] == "C001" and r["invoice_date"].startswith("2026-09") for r in rows))
        self.assertEqual(len(list_bank_transactions(self.connection, "U001", "C002", 2026, 8)), 12)

    def test_no_records_returns_empty_list(self):
        self.assertEqual(list_invoices(self.connection, "U001", "C001", 2026, 7), [])

    def test_invalid_parameters_and_permission_are_clear_errors(self):
        with self.assertRaises(QueryError): list_invoices(self.connection, "U001", "C001", 2026, 13)
        with self.assertRaises(QueryError): list_invoices(self.connection, "U002", "C002", 2026, 9)
        with self.assertRaises(QueryError): get_invoice(self.connection, "U001", "C001", "")

    def test_missing_purpose_query(self):
        rows = list_missing_purpose_invoices(self.connection, "U001", "C001", 2026, 9)
        self.assertEqual([r["invoice_no"] for r in rows], ["F002", "F004", "F003", "F006", "F009"])
