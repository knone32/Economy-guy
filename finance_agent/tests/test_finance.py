import unittest
from app.finance import bank_expense_total, bank_income_total, invoice_total
from app.queries import QueryError
from tests.helpers import DatabaseTestCaseMixin


class FinanceTests(DatabaseTestCaseMixin, unittest.TestCase):
    def test_official_check_values(self):
        self.assertEqual(invoice_total(self.connection, "U001", "C001", 2026, 8), "9046.35")
        self.assertEqual(bank_expense_total(self.connection, "U001", "C001", 2026, 8), "5720.99")
        self.assertEqual(bank_income_total(self.connection, "U001", "C002", 2026, 9), "13700.75")

    def test_income_expense_and_precision_are_separate(self):
        self.assertEqual(bank_income_total(self.connection, "U001", "C001", 2026, 9), "13000.50")
        self.assertEqual(bank_expense_total(self.connection, "U001", "C001", 2026, 9), "7180.74")
        self.assertEqual(invoice_total(self.connection, "U001", "C002", 2026, 8), "13667.05")

    def test_zero_is_only_successful_empty_result(self):
        self.assertEqual(invoice_total(self.connection, "U001", "C001", 2026, 7), "0.00")
        with self.assertRaises(QueryError): invoice_total(self.connection, "U002", "C002", 2026, 7)
