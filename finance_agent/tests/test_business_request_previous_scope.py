"""Read-only prior-target scope survives cleared incidental Context state."""
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from app.business_request import bind,BusinessRequestError
from tests import test_business_request as fixture_module


class PreviousScopeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_module.BusinessRequestTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.book=self.fixture.book;self.before=self.book.read_bytes();self.addCleanup(self.unchanged)
        self.original='C001 2026年9月从青屿取得的全部发票，用途为物料，金额和张数。'
        self.first=self.fixture.target()
        self.first['seller']={'mode':'ambiguous','quote':'从青屿取得的全部发票','value':'青屿'}
        self.previous=self.initial()
        self.follow=self.fixture.names[0]
        self.target=self.fixture.target()
        self.target.update(company_source='context',company_quote='',period_source='context',period_quote='',
            previous_target_id='i1',seller={'mode':'single','quote':self.follow,'value':self.follow})
        self.target['filters'][0].update(quote='',source={'kind':'context','key':'i1.filters.0'})
        for index,metric in enumerate(self.target['metrics']):
            metric.update(quote='',source={'kind':'context','key':f'i1.metrics.{index}'})

    def unchanged(self):
        self.assertEqual(self.before,self.book.read_bytes())
        with closing(sqlite3.connect(self.book)) as db:self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)

    def initial(self,targets=None,text=None,actor='U001'):
        return bind(json.dumps({'kind':'read','targets':targets or [self.first],'unresolved':[]},ensure_ascii=False),
            actor=actor,book=self.book,turn_id='first',request=text or self.original)

    def followup(self,target=None,previous=None,trusted=None,text=None,actor='U001',book=None):
        return bind(json.dumps({'kind':'read','targets':[target or self.target],'unresolved':[]},ensure_ascii=False),
            actor=actor,book=book or self.book,turn_id='next',request=text or self.follow,
            previous_request=previous or self.previous,trusted_scope={} if trusted is None else trusted,revision=2)

    def test_empty_trusted_scope_can_use_exact_current_prior_target_and_records_source(self):
        req=self.followup();req.require_current('U001',self.book,turn_id='next')
        self.assertFalse(req.unresolved)
        self.assertEqual(req.targets[0].company_ids,('C001',));self.assertEqual(req.targets[0].periods,((2026,9),))
        self.assertEqual(req.targets[0].company_source.key,f'1/{self.previous.request_hash}/i1.company_ids')
        self.assertEqual(req.targets[0].period_source.key,f'1/{self.previous.request_hash}/i1.periods')
        target=deepcopy(self.target);target.pop('previous_target_id')
        self.assertFalse(self.followup(target=target).unresolved)

    def test_existing_trusted_conflicts_cannot_fall_back_to_previous_scope(self):
        for trusted in ({'company_id':['C002']},{'company_id':['C001','C002']},
                        {'periods':[(2026,10)]},{'year':[2027]},{'month':[10]}):
            with self.subTest(trusted=trusted),self.assertRaises(BusinessRequestError):self.followup(trusted=trusted)
        self.assertFalse(self.followup(trusted={'year':[2026],'month':[9]}).unresolved)

    def test_company_or_period_widening_and_narrowing_do_not_acquire_prior_source(self):
        for change in ({'company_ids':['C002']},{'company_ids':['C001','C002']},
                       {'periods':[[2026,9],[2026,10]]},{'periods':[[2026,10]]}):
            with self.subTest(change=change),self.assertRaises(BusinessRequestError):self.followup(target={**self.target,**change})
        initial=deepcopy(self.first);initial.update(periods=[[2026,9],[2026,10]],period_quote='2026年9月和10月')
        multi=self.initial([initial],self.original.replace('2026年9月','2026年9月和10月'))
        with self.assertRaises(BusinessRequestError):self.followup(previous=multi)

    def test_ambiguous_previous_targets_require_existing_id_and_matching_object(self):
        second=deepcopy(self.first);second['target_id']='i2'
        multiple=self.initial([self.first,second])
        target=deepcopy(self.target);target.pop('previous_target_id')
        with self.assertRaises(BusinessRequestError):self.followup(target=target,previous=multiple)
        self.assertFalse(self.followup(previous=multiple).unresolved)
        bank={'target_id':'b1','object':'bank_transactions','company_ids':['C001'],'company_quote':'C001',
            'periods':[[2026,9]],'period_quote':'2026年9月','filters':[],
            'metrics':[{'operation':'count','field':'*','quote':'银行笔数'}],'group_by':[],'comparisons':[]}
        mixed=self.initial([self.first,bank],self.original+'银行笔数。')
        for identifier in ('missing','b1'):
            with self.subTest(identifier=identifier),self.assertRaises(BusinessRequestError):
                self.followup(target={**self.target,'previous_target_id':identifier},previous=mixed)

    def test_invalid_identity_book_hash_or_stale_catalog_is_not_a_prior_source(self):
        for previous in (replace(self.previous,actor='U002'),replace(self.previous,request_hash='wrong'),
                         replace(self.previous,catalog_hash='stale')):
            with self.subTest(previous=previous),self.assertRaises(BusinessRequestError):self.followup(previous=previous)
        with TemporaryDirectory() as temp:
            other=Path(temp)/'other.sqlite';shutil.copyfile(self.book,other)
            with self.assertRaises(BusinessRequestError):self.followup(book=other)
        readonly=self.initial(actor='U002')
        with self.assertRaises(BusinessRequestError) as error:
            self.followup(target={**self.target,'company_ids':['C002']},previous=readonly,actor='U002')
        self.assertEqual(error.exception.status,'DENIED')

    def test_prior_scope_does_not_disable_existing_filter_or_seller_retention(self):
        req=self.followup(target={**self.target,'filters':[]})
        self.assertIn('i1.previous_filters_not_replaced',req.unresolved)
        target=deepcopy(self.target);target['seller']={'mode':'none','quote':'全部发票金额和张数','value':''}
        req=self.followup(target=target,text='统计全部发票金额和张数。')
        self.assertIn('i1.previous_seller_not_replaced',req.unresolved)
