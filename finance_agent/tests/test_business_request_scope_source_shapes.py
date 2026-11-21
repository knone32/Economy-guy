"""Equivalent scope-source syntax never creates new source authority."""
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
import json
import sqlite3
import unittest
from app.business_request import bind,BusinessRequestError
from tests import test_business_request as fixture_module


class ScopeSourceShapeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_module.BusinessRequestTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.book=self.fixture.book;self.before=self.book.read_bytes();self.addCleanup(self.unchanged)
        self.previous=self.fixture.make();self.follow=self.fixture.names[0]
        self.target=self.fixture.target()
        self.target.update(company_source='context',company_quote='',period_source='context',period_quote='',
            previous_target_id='i1',seller={'mode':'single','quote':self.follow,'value':self.follow})
        self.target['filters'][0].update(quote='',source={'kind':'context','key':'i1.filters.0'})
        for index,metric in enumerate(self.target['metrics']):
            metric.update(quote='',source={'kind':'context','key':f'i1.metrics.{index}'})

    def unchanged(self):
        self.assertEqual(self.before,self.book.read_bytes())
        with closing(sqlite3.connect(self.book)) as db:self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)

    def followup(self,target=None,previous=None,trusted=None):
        prior=previous or self.previous
        return bind(json.dumps({'kind':'read','targets':[target or self.target],'unresolved':[]},ensure_ascii=False),
            actor='U001',book=self.book,turn_id='follow',request=self.follow,revision=prior.revision+1,
            previous_request=prior,trusted_scope={} if trusted is None else trusted)

    def test_current_token_and_objects_use_the_same_actual_current_quote_validation(self):
        plain=self.fixture.make()
        target=self.fixture.target()
        target['company_source']={'kind':'current','quote':'C001','key':None}
        target['period_source']={'kind':'current','quote':'2026年9月'}
        self.assertEqual(self.fixture.make(target).targets,plain.targets)
        target.update(company_quote='',period_quote='')
        self.assertEqual(self.fixture.make(target).targets,plain.targets)
        target['company_source']['quote']='没有出现在原话的企业'
        with self.assertRaises(BusinessRequestError):self.fixture.make(target)
        target=self.fixture.target();target['period_source']={'kind':'current','quote':'2027年9月','key':None}
        with self.assertRaises(BusinessRequestError) as error:self.fixture.make(target)
        self.assertEqual(error.exception.status,'INVALID_ARGUMENTS')  # dual quotes disagree

    def test_context_token_null_and_omitted_key_have_identical_runtime_sources(self):
        token=self.followup()
        for declaration in ({'kind':'context'},{'kind':'context','quote':''},
                            {'kind':'context','quote':'','key':None}):
            target=deepcopy(self.target);target.update(company_source=declaration,period_source=declaration)
            current=self.followup(target)
            self.assertEqual(current.targets,token.targets)
            current.require_current('U001',self.book,turn_id='follow')

    def test_nonempty_reference_keys_and_quotes_match_only_actual_selected_field_sources(self):
        expected=self.followup();target=deepcopy(self.target)
        target['company_source']=asdict(expected.targets[0].company_source)
        target['period_source']=asdict(expected.targets[0].period_source)
        self.assertEqual(self.followup(target).targets,expected.targets)
        for field,key in [('company_source','scope.company_id'),('period_source','scope.periods')]:
            scoped=deepcopy(self.target);scoped[field]={'kind':'context','quote':'','key':key}
            trusted={'company_id':['C001'],'periods':[(2026,9)]}
            self.assertFalse(self.followup(scoped,trusted=trusted).unresolved)
        for key in ('wrong','1/wrong-hash/i1.company_ids',
                    f'1/{self.previous.request_hash}/other.company_ids',
                    f'1/{self.previous.request_hash}/i1.periods'):
            bad=deepcopy(self.target);bad['company_source']={'kind':'context','quote':'','key':key}
            with self.subTest(key=key),self.assertRaises(BusinessRequestError) as error:self.followup(bad)
            self.assertEqual(error.exception.status,'INVALID_ARGUMENTS')
        bad=deepcopy(self.target);bad['period_source']={'kind':'context','quote':'不一致的旧时期','key':None}
        with self.assertRaises(BusinessRequestError) as error:self.followup(bad)
        self.assertEqual(error.exception.status,'INVALID_ARGUMENTS')

    def test_known_origin_key_lineage_is_checked_without_copying_model_claims(self):
        prior=self.followup()  # Its field sources carry the checked older revision.
        target=deepcopy(self.target)
        target['company_source']=asdict(prior.targets[0].company_source)
        target['period_source']=asdict(prior.targets[0].period_source)
        current=self.followup(target,previous=prior)
        self.assertEqual(current.targets[0].company_source.key,f'{prior.revision}/{prior.request_hash}/i1.company_ids')
        self.assertNotEqual(current.targets[0].company_source.key,target['company_source']['key'])
        target['company_source']['key']=target['company_source']['key'].replace(self.previous.request_hash,'stale-hash')
        with self.assertRaises(BusinessRequestError) as error:self.followup(target,previous=prior)
        self.assertEqual(error.exception.status,'INVALID_ARGUMENTS')

    def test_wrong_types_extra_authority_fields_and_conflicting_quotes_are_structural_errors(self):
        for declaration in (0,True,[],{'kind':'anchor'},{'kind':'context','quote':False},
                            {'kind':'context','key':7},{'kind':'context','key':False},
                            {'kind':'context','authorized':True}):
            target=deepcopy(self.target);target['company_source']=declaration
            with self.subTest(value=declaration),self.assertRaises(BusinessRequestError) as error:self.followup(target)
            self.assertEqual(error.exception.status,'INVALID_ARGUMENTS')
        target=deepcopy(self.target);target.update(company_quote='C001',
            company_source={'kind':'context','quote':'C002','key':None})
        with self.assertRaises(BusinessRequestError) as error:self.followup(target)
        self.assertEqual(error.exception.status,'INVALID_ARGUMENTS')

    def test_shape_compatibility_does_not_override_scope_or_retained_filter_constraints(self):
        target=deepcopy(self.target)
        target.update(company_source={'kind':'context','quote':'','key':None},
                      period_source={'kind':'context','quote':'','key':None})
        for change in ({'company_ids':['C001','C002']},{'periods':[[2026,9],[2026,10]]},
                       {'previous_target_id':'not-current'}):
            with self.subTest(change=change),self.assertRaises(BusinessRequestError):self.followup({**target,**change})
        with self.assertRaises(BusinessRequestError):self.followup(target,trusted={'company_id':['C002']})
        target['filters']=[]
        self.assertIn('i1.previous_filters_not_replaced',self.followup(target).unresolved)
