"""Published model guidance must describe tools the runtime actually accepts."""
import json
import unittest

from app.agent import SYSTEM
from app.tool_registry import TOOLS, validate_arguments


class BusinessContractGuidanceTests(unittest.TestCase):
    def test_incomplete_single_invoice_uses_its_existing_business_interface(self):
        schemas={t['function']['name']:t['function']['parameters'] for t in TOOLS}
        self.assertEqual(schemas['change_invoice']['required'],[])
        self.assertNotIn('action=request',SYSTEM)
        self.assertEqual(validate_arguments('change_invoice','{}'),{})

    def test_complex_selection_keeps_complete_schema_without_request_mode(self):
        args={'selection_id':'current','field':'remark','new_value':'example',
              'mode':'item','excluded_invoice_ids':[]}
        self.assertEqual(validate_arguments('propose_invoice_changes',json.dumps(args)),args)
        with self.assertRaises(ValueError):
            validate_arguments('propose_invoice_changes','{"action":"request"}')
