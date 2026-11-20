"""Pure structure restatement; no model invocation or relaxed source binding."""
from copy import deepcopy
import json
import unittest
from app.business_request import (bind, messages, read_catalog, schema_restatement_messages,
                                 BusinessRequestError)
from tests import test_business_request as fixture_module


class SchemaRestatementTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_module.BusinessRequestTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.context=messages(self.fixture.text,read_catalog(self.fixture.book,'U001'))

    def raw(self,target=None,unresolved=None,**extra):
        return {'kind':'read','targets':[target or self.fixture.target()],
                'unresolved':[] if unresolved is None else unresolved,**extra}

    def parse(self,body,text=None):
        return bind(json.dumps(body,ensure_ascii=False),actor='U001',book=self.fixture.book,
                    turn_id='restated',request=text or self.fixture.text)

    def test_strict_top_level_and_unresolved_types_remain_rejected(self):
        for bad in (self.raw(type='read'),self.raw(unresolved=[{'slot':'seller'}])):
            with self.subTest(body=bad),self.assertRaises(BusinessRequestError):self.parse(bad)
        self.assertFalse(self.parse(self.raw()).unresolved)
        self.assertEqual(self.parse(self.raw(unresolved=['i1.seller'])).unresolved,('i1.seller',))

    def test_ambiguous_seller_uses_current_short_string_not_candidate_array(self):
        target=self.fixture.target()
        target['seller']={'mode':'ambiguous','value':list(self.fixture.names),'quote':'从青屿取得的全部发票'}
        text='C001 2026年9月从青屿取得的全部发票，用途为物料，金额和张数。'
        with self.assertRaises(BusinessRequestError):self.parse(self.raw(target),text)
        target['seller']['value']='青屿'
        req=self.parse(self.raw(target),text)
        self.assertEqual(set(req.targets[0].seller.names),set(self.fixture.names))
        self.assertIn('i1.seller',req.unresolved)
        with self.assertRaises(BusinessRequestError):req.require_current('U001',self.fixture.book)

    def test_helper_reuses_only_original_context_without_mutating_it(self):
        original=deepcopy(self.context)
        restated=schema_restatement_messages(self.context,error_code='top_level')
        self.assertEqual(restated[:2],original)
        self.assertEqual(len(restated),3);self.assertEqual(restated[-1]['role'],'system')
        restated[0]['content']='caller mutation'
        self.assertEqual(self.context,original)
        # The helper does not create or normalize a binding: original strict parse still owns it.
        self.assertFalse(self.parse(self.raw()).unresolved)

    def test_helper_rejects_generator_context_and_dynamic_error_body(self):
        invalids=[self.context+[{'role':'assistant','content':'failed output'}],
                  [self.context[0],{'role':'assistant','content':self.context[1]['content']}],
                  [self.context[0],{'role':'user','content':json.dumps({'request':'x','sql':'SELECT 1'})}]]
        for invalid in invalids:
            with self.subTest(context=invalid),self.assertRaises(ValueError):
                schema_restatement_messages(invalid)
        with self.assertRaises(ValueError):schema_restatement_messages(self.context,error_code='failed model SQL body')
        with self.assertRaises(TypeError):schema_restatement_messages(self.context,failed_reply='arbitrary output')

    def test_static_type_guidance_keeps_all_sources_in_original_input(self):
        for code in ('invalid_structure','top_level','unresolved','seller_value'):
            repeated=schema_restatement_messages(tuple(self.context),error_code=code)
            self.assertEqual(repeated[:2],self.context)
            self.assertFalse(any('tool_calls' in m or m['role']=='tool' for m in repeated))
            self.assertEqual(json.loads(repeated[1]['content']),json.loads(self.context[1]['content']))
