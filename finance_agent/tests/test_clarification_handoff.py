"""Finite program evidence; scripted semantics do not prove natural language."""
import unittest
from app.business_request import BusinessRequestError


class IndependentActionTests(unittest.TestCase):
    def test_waiting_is_not_matter_deferral(self):
        from app.business_request import legacy_action
        for reason in ('await_selection', 'await_value'):
            self.assertEqual(legacy_action({'action_reason': reason}), 'continue')
            with self.assertRaises(BusinessRequestError):
                legacy_action({'turn_action': 'pause', 'action_reason': reason})
        self.assertEqual(legacy_action({'turn_action':'pause','action_reason':'defer_matter'}),'pause')
        with self.assertRaises(BusinessRequestError):
            legacy_action({'turn_action':'pause'})


if __name__ == '__main__':
    unittest.main()
