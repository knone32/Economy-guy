"""One read Source declaration contract, no added intent or action authority."""
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
import json
import sqlite3
import unittest
from app.business_request import bind,BusinessRequestError
from tests import test_business_request as fixture_module


class CommonReadSourceTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_module.BusinessRequestTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.book=self.fixture.book;self.before=self.book.read_bytes();self.addCleanup(self.unchanged)
        self.previous=self.fixture.make();self.follow=self.fixture.names[0]
        self.target=self.fixture.target()
        self.target.update(company_source='context',company_quote='',period_source='context',period_quote='',previous_target_id='i1',
            seller={'mode':'single','value':self.follow,'quote':self.follow})
        self.target['filters'][0].update(quote='',source={'kind':'context','key':'i1.filters.0'})
        for index,metric in enumerate(self.target['metrics']):
            metric.update(quote='',source={'kind':'context','key':f'i1.metrics.{index}'})

    def unchanged(self):
        self.assertEqual(self.before,self.book.read_bytes())
        with closing(sqlite3.connect(self.book)) as db:self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)

    def followup(self,target=None,previous=None):
        old=previous or self.previous
        return bind(json.dumps({'kind':'read','targets':[target or self.target],'unresolved':[]},ensure_ascii=False),
            actor='U001',book=self.book,turn_id='next',request=self.follow,revision=old.revision+1,previous_request=old,trusted_scope={})

    def test_explicit_default_update_has_no_new_source_or_replacement_permission(self):
        expected=self.followup()
        for extra in ({'relation':'update'},{'relation':'update','relation_quote':''}):
            target={**self.target,**extra}
            self.assertEqual(self.followup(target).targets,expected.targets)
            target['filters']=[]
            self.assertIn('i1.previous_filters_not_replaced',self.followup(target).unresolved)
        for relation in ('replace','clarify'):
            with self.assertRaises(BusinessRequestError):self.followup({**self.target,'relation':relation})
        for quote in ('not in the request',None,False):
            with self.assertRaises(BusinessRequestError):self.followup({**self.target,'relation':'update','relation_quote':quote})

    def test_current_source_carriers_are_equivalent_for_seller_filter_and_metric(self):
        expected=self.fixture.make()
        for form in ('string','nested','both'):
            target=self.fixture.target()
            for body in [target['seller'],*target['filters'],*target['metrics']]:
                quote=body['quote']
                body['source']='current' if form=='string' else {'kind':'current','quote':quote,'key':None}
                if form=='nested':body.pop('quote')
            self.assertEqual(self.fixture.make(target).targets,expected.targets)
        for slot in ('seller','filter','metric'):
            target=self.fixture.target();body=target['seller'] if slot=='seller' else target['filters'][0] if slot=='filter' else target['metrics'][0]
            body.pop('quote');body['source']={'kind':'current','quote':'not a current quote','key':None}
            with self.subTest(slot=slot),self.assertRaises(BusinessRequestError):self.fixture.make(target)
            body['source']['quote']=''
            with self.subTest(slot=slot),self.assertRaises(BusinessRequestError):self.fixture.make(target)

    def test_context_quotes_use_the_same_effective_carrier_and_runtime_old_source(self):
        target=deepcopy(self.target)
        target['seller']={'mode':self.previous.targets[0].seller.mode,'value':self.previous.targets[0].seller.value,
                          'source':{'kind':'context','key':'i1.seller'}}
        expected=self.followup(target)
        for field in ('seller','filter','metric'):
            origin=(self.previous.targets[0].seller.source if field=='seller' else self.previous.targets[0].filters[0].source
                    if field=='filter' else self.previous.targets[0].metrics[0].source)
            for carrier in ('top','nested'):
                current=deepcopy(target);body=current['seller'] if field=='seller' else current['filters'][0] if field=='filter' else current['metrics'][0]
                body.pop('quote',None);body['source'].pop('quote',None)
                if carrier=='top':body['quote']=origin.quote
                else:body['source']['quote']=origin.quote
                self.assertEqual(self.followup(current).targets,expected.targets)
                if carrier=='top':body['quote']='wrong prior quote'
                else:body['source']['quote']='wrong prior quote'
                with self.subTest(field=field,carrier=carrier),self.assertRaises(BusinessRequestError) as error:self.followup(current)
                self.assertEqual(error.exception.status,'INVALID_ARGUMENTS')

    def test_context_null_key_or_token_requires_unique_same_type_same_value(self):
        target=deepcopy(self.target)
        target['seller']={'mode':self.previous.targets[0].seller.mode,'value':self.previous.targets[0].seller.value,
                          'source':{'kind':'context','key':'i1.seller'}}
        expected=self.followup(target)
        for form in ('context',{'kind':'context','quote':'','key':None}):
            current=deepcopy(target)
            for body in [current['seller'],*current['filters'],*current['metrics']]:body.update(source=form,quote='')
            self.assertEqual(self.followup(current).targets,expected.targets)
        ambiguous=deepcopy(target);ambiguous['seller']['value']=self.follow
        with self.assertRaises(BusinessRequestError):self.followup(ambiguous)
        first=self.fixture.target();first['metrics'].append(deepcopy(first['metrics'][0]))
        old=self.fixture.make(first);current=deepcopy(self.target);current['metrics'][0]['source']={'kind':'context','key':None}
        with self.assertRaises(BusinessRequestError):self.followup(current,previous=old)

    def test_cross_type_target_field_hash_and_value_claims_do_not_resolve(self):
        for key in ('i1.filters.0','other.metrics.0',f'99/{self.previous.request_hash}/i1.metrics.0',
                    '1/old-hash/i1.metrics.0'):
            target=deepcopy(self.target);target['metrics'][0]['source']={'kind':'context','key':key}
            with self.subTest(key=key),self.assertRaises(BusinessRequestError) as error:self.followup(target)
            self.assertEqual(error.exception.status,'INVALID_ARGUMENTS')
        target=deepcopy(self.target);target['filters'][0]['value']='changed value'
        with self.assertRaises(BusinessRequestError):self.followup(target)
        old=self.followup()
        target=deepcopy(self.target)
        for index,body in enumerate(target['metrics']):body['source']=asdict(old.targets[0].metrics[index].source)
        self.assertFalse(self.followup(target,previous=old).unresolved)
        target['metrics'][0]['source']['key']='1/not-known-origin/i1.metrics.0'
        with self.assertRaises(BusinessRequestError):self.followup(target,previous=old)

    def test_current_wrong_keys_quote_conflicts_and_unknown_source_types_are_invalid(self):
        for slot in ('seller','filter','metric'):
            for declaration in ({'kind':'current','key':'scope.periods'}, {'kind':'current','quote':'conflict'},
                                {'kind':'unknown'}, {'kind':'current','quote':False}, {'kind':'current','approved':True},None):
                target=self.fixture.target();body=target['seller'] if slot=='seller' else target['filters'][0] if slot=='filter' else target['metrics'][0]
                body['source']=declaration
                with self.subTest(slot=slot,source=declaration),self.assertRaises(BusinessRequestError) as error:self.fixture.make(target)
                self.assertEqual(error.exception.status,'INVALID_ARGUMENTS')

    def test_filter_value_checks_use_normalized_quote_for_blank_text_and_direction(self):
        target=self.fixture.target();target['filters']=[{'field':'purpose','operator':'is_blank','value':'',
            'source':{'kind':'current','quote':'用途为空','key':None}}]
        self.assertFalse(self.fixture.make(target,self.fixture.text.replace('用途为物料','用途为空')).unresolved)
        target['filters'][0].update(operator='=',value='not in actual current source')
        with self.assertRaises(BusinessRequestError):self.fixture.make(target,self.fixture.text.replace('用途为物料','用途为空'))
        bank={'target_id':'b1','object':'bank_transactions','company_ids':['C001'],'company_quote':'C001',
            'periods':[[2026,9]],'period_quote':'2026年9月','filters':[{'field':'direction','operator':'=','value':'收入',
            'source':{'kind':'current','quote':'进账','key':'model_interpretation:bank_direction'}}],
            'metrics':[{'operation':'count','field':'*','source':{'kind':'current','quote':'笔数','key':None}}],
            'group_by':[],'comparisons':[]}
        text='C001 2026年9月统计银行进账笔数。'
        req=self.fixture.make(bank,text);self.assertEqual(req.targets[0].filters[0].source.key,'model_interpretation:bank_direction')
        bank['filters'][0]['source']['key']='wrong current runtime key'
        with self.assertRaises(BusinessRequestError):self.fixture.make(bank,text)
