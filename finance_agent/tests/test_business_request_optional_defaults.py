"""Finite syntax defaults never default business conditions or permissions."""
from copy import deepcopy
import unittest
from app.business_request import BusinessRequestError
from tests import test_business_request_common_sources as common

class OptionalSourceDefaultsTests(unittest.TestCase):
    setUp=common.CommonReadSourceTests.setUp
    unchanged=common.CommonReadSourceTests.unchanged
    followup=common.CommonReadSourceTests.followup

    def test_optional_carriers_have_same_bound_targets(self):
        expected=self.fixture.make()
        for empty in (None,''):
            target=self.fixture.target();target.update(company_source=empty,period_source=empty,relation_source=None)
            for body in [target['seller'],*target['filters'],*target['metrics']]:body['source']=empty
            self.assertEqual(self.fixture.make(target).targets,expected.targets)
            target=self.fixture.target()
            for body in [target['seller'],*target['filters'],*target['metrics']]:body['source']={'kind':'current','quote':empty,'key':empty}
            self.assertEqual(self.fixture.make(target).targets,expected.targets)
        target=deepcopy(self.target);target.update(relation_source=None,company_source={'kind':'context','quote':None,'key':''},period_source={'kind':'context','quote':'','key':''})
        for metric in target['metrics']:metric['source'].update(quote=None)
        self.assertEqual(self.followup(target).targets,self.followup().targets)

    def test_relation_sources_do_not_grant_replacement(self):
        for source in (None,''):
            target={**self.target,'relation_source':source}
            self.assertEqual(self.followup(target).targets,self.followup().targets)
            target['filters']=[]
            self.assertIn('i1.previous_filters_not_replaced',self.followup(target).unresolved)
        for source in (False,[],{}, {'kind':'current','quote':None,'key':''}, {'kind':'context'}, {'kind':'current','key':'unowned'}, {'kind':'current','quote':'not in current text'}):
            with self.subTest(source=source),self.assertRaises(BusinessRequestError):self.followup({**self.target,'relation_source':source})
        target={**self.target,'relation_source':{'kind':'current','quote':self.follow,'key':None}}
        direct={**self.target,'relation_quote':self.follow}
        self.assertEqual(self.followup(target).targets,self.followup(direct).targets)
        for relation in ('replace','clarify'):
            with self.assertRaises(BusinessRequestError):self.followup({**self.target,'relation':relation,'relation_source':None})
        with self.assertRaises(BusinessRequestError):self.followup({**self.target,'relation_quote':self.follow,'relation_source':{'kind':'current','quote':'conflict'}})

    def test_unknown_null_business_values_and_missing_sources_still_reject(self):
        for field in ('filters','metrics','periods','group_by','comparisons'):
            with self.subTest(field=field),self.assertRaises(BusinessRequestError):self.fixture.make({**self.fixture.target(),field:None})
        target=self.fixture.target();target['seller'].pop('quote');target['seller']['source']=None
        with self.assertRaises(BusinessRequestError):self.fixture.make(target)
        for bad in ({'kind':None},{'kind':''},{'kind':'current','key':False},{'kind':'current','quote':False},{'kind':'current','unknown':None}):
            target=self.fixture.target();target['seller']['source']=bad
            with self.subTest(source=bad),self.assertRaises(BusinessRequestError):self.fixture.make(target)
        with self.assertRaises(BusinessRequestError):self.fixture.make({**self.fixture.target(),'unknown_business_field':None})
