import unittest
from app.permissions import check_permission
from app.queries import get_invoice, QueryError
from tests.helpers import DatabaseTestCaseMixin


class PermissionTests(DatabaseTestCaseMixin, unittest.TestCase):
    def test_u001_can_read_both_companies(self):
        self.assertTrue(check_permission(self.connection, "U001", "C001", "read").allowed)
        self.assertTrue(check_permission(self.connection, "U001", "C002", "read").allowed)

    def test_u002_read_and_modify_limits(self):
        self.assertTrue(check_permission(self.connection, "U002", "C001", "read").allowed)
        self.assertFalse(check_permission(self.connection, "U002", "C002", "read").allowed)
        self.assertFalse(check_permission(self.connection, "U002", "C001", "modify").allowed)

    def test_unknown_user_is_denied(self):
        self.assertFalse(check_permission(self.connection, "U999", "C001", "read").allowed)

    def test_same_invoice_number_cannot_cross_company_scope(self):
        c001 = get_invoice(self.connection, "U001", "C001", "F001")
        c002 = get_invoice(self.connection, "U001", "C002", "F001")
        self.assertNotEqual(c001["amount"], c002["amount"])
        with self.assertRaises(QueryError): get_invoice(self.connection, "U002", "C002", "F001")
