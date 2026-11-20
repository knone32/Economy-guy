"""Runtime-only pending-to-read transition, no new pending or draft owner."""
from copy import deepcopy
import json
import unittest
from app.business_request import (bind, messages, read_catalog, schema_restatement_messages,
                                 BusinessRequestError)
from tests import test_business_request as fixture_module


class ContextTransitionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_module.BusinessRequestTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        target=self.fixture.target()
        target['filters'].append({'field':'invoice_no','operator':'=','value':'A','quote':'发票A'})
        self.previous=self.fixture.make(target,self.fixture.text+'查看发票A。')
        self.text='C001 2026年10月统计全部发票金额和张数。'
        self.target=self.fixture.target()
        self.target.update(periods=[[2026,10]],period_quote='2026年10月',filters=[],
                           seller={'mode':'none','quote':'全部发票金额和张数','value':''})

    def parse(self,*,target=None,text=None,transition='continue',extra=None,actor='U001'):
        raw={'kind':'read','targets':[target or self.target],'unresolved':[],**(extra or {})}
        return bind(json.dumps(raw,ensure_ascii=False),actor=actor,book=self.fixture.book,turn_id='new-read',
                    request=text or self.text,revision=self.previous.revision+1,
                    previous_request=self.previous,context_transition=transition)

    def test_continue_still_blocks_silent_old_filters_while_handoff_accepts_current_whole_read(self):
        regular=self.parse()
        self.assertIn('i1.previous_seller_not_replaced',regular.unresolved)
        self.assertIn('i1.previous_filters_not_replaced',regular.unresolved)
        handoff=self.parse(transition='pending_to_read')
        handoff.require_current('U001',self.fixture.book,turn_id='new-read')
        self.assertFalse(handoff.unresolved);self.assertEqual(handoff.targets[0].filters,())
        self.assertEqual(handoff.targets[0].periods,((2026,10),))
        self.assertEqual(handoff.context_transition,'pending_to_read')
        self.assertEqual(handoff.revision,self.previous.revision+1)
        self.assertEqual(handoff.previous_request_revision,self.previous.revision)
        self.assertEqual(handoff.previous_request_hash,self.previous.request_hash)
        self.assertEqual(len(self.previous.targets[0].filters),2)

    def test_runtime_transition_does_not_allow_model_json_flags_or_invalid_values(self):
        for bad in ('invalid',None,True,[]):
            with self.subTest(value=bad),self.assertRaises(BusinessRequestError):self.parse(transition=bad)
        with self.assertRaises(BusinessRequestError):
            self.parse(transition='pending_to_read',extra={'context_transition':'pending_to_read'})
        target={**self.target,'context_transition':'pending_to_read'}
        with self.assertRaises(BusinessRequestError):self.parse(target=target,transition='pending_to_read')

    def test_explicit_context_references_remain_exact_and_current_sources_are_required(self):
        target=deepcopy(self.target)
        target['filters']=[{'field':'purpose','operator':'=','value':'物料','quote':'',
                           'source':{'kind':'context','key':'i1.filters.0'}}]
        req=self.parse(target=target,transition='pending_to_read')
        self.assertEqual(req.targets[0].filters[0].value,'物料')
        self.assertEqual(req.targets[0].filters[0].source.kind,'context')
        for mutation in ('wrong_key','changed_value','missing_current_source'):
            bad=deepcopy(target)
            if mutation=='wrong_key':bad['filters'][0]['source']['key']='not-a-target.filters.0'
            elif mutation=='changed_value':bad['filters'][0]['value']='另一个用途'
            else:bad['period_quote']='没有当前日期来源'
            with self.subTest(mutation=mutation),self.assertRaises(BusinessRequestError):
                self.parse(target=bad,transition='pending_to_read')
        with self.assertRaises(BusinessRequestError):self.parse(actor='U002',transition='pending_to_read')
        old=bind(json.dumps({'kind':'read','targets':[self.fixture.target()],'unresolved':[]},ensure_ascii=False),
            actor='U002',book=self.fixture.book,turn_id='old',request=self.fixture.text)
        denied={**self.target,'company_ids':['C002'],'company_quote':'C002'}
        with self.assertRaises(BusinessRequestError) as error:
            bind(json.dumps({'kind':'read','targets':[denied],'unresolved':[]},ensure_ascii=False),
                actor='U002',book=self.fixture.book,turn_id='new',request=self.text.replace('C001','C002'),
                previous_request=old,revision=old.revision+1,context_transition='pending_to_read')
        self.assertEqual(error.exception.status,'DENIED')

    def test_transition_keeps_original_two_messages_five_keys_and_schema_helper(self):
        catalog=read_catalog(self.fixture.book,'U001')
        regular=messages(self.text,catalog,previous_request=self.previous)
        handoff=messages(self.text,catalog,previous_request=self.previous,context_transition='pending_to_read')
        self.assertEqual(len(handoff),2)
        self.assertEqual(handoff[1],regular[1])
        payload=json.loads(handoff[1]['content'])
        self.assertEqual(set(payload),{'request','read_catalog','trusted_scope','previous_requirement','business_definition'})
        self.assertEqual(schema_restatement_messages(handoff)[:2],handoff)
        self.assertNotIn('context_transition',set(payload))
        with self.assertRaises(BusinessRequestError):messages(self.text,catalog,context_transition='model_flag')
