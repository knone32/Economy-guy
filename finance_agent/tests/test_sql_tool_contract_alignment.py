"""The advertised seller path must be the same path the runtime accepts."""
import json
import unittest

from app.tool_registry import TOOLS, validate_arguments


class SQLToolContractAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.tool=next(t['function'] for t in TOOLS if t['function']['name']=='query_business_sql')
        self.seller={'mode':'single','quote':'完整销售方','value':'完整销售方'}
        self.scope={'company_id':'C001','periods':[{'year':2028,'month':10}],
                    'company_quote':'C001','period_quote':'2028年10月','seller':self.seller}

    def test_exposed_description_names_the_schema_nested_path_and_runtime_owner(self):
        schema=self.tool['parameters']
        self.assertEqual(set(schema['properties']),{'sql','read_scope'})
        self.assertIn('seller',schema['properties']['read_scope']['properties'])
        self.assertIn('read_scope.seller',self.tool['description'])
        self.assertIn('BusinessRequest',self.tool['description'])
        self.assertNotIn('可选seller=',self.tool['description'])
        self.assertFalse(schema['additionalProperties'])

    def test_nested_optional_seller_validates_without_promoting_top_level_seller(self):
        args={'sql':'SELECT COUNT(*) FROM invoices','read_scope':self.scope}
        self.assertEqual(validate_arguments('query_business_sql',json.dumps(args)),args)
        with self.assertRaises(ValueError):
            validate_arguments('query_business_sql',json.dumps({'sql':args['sql'],'seller':self.seller}))
        self.assertEqual(validate_arguments('query_business_sql',json.dumps({'sql':args['sql']})),{'sql':args['sql']})

    def test_conflicting_nested_shape_is_not_silently_discarded(self):
        args={'sql':'SELECT COUNT(*) FROM invoices','read_scope':{**self.scope,'seller':{'mode':'single','value':'完整销售方'}}}
        with self.assertRaises(ValueError):validate_arguments('query_business_sql',json.dumps(args))
