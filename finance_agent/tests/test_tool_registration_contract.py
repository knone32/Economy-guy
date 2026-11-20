"""Registration metadata is a capability limit, never a query authorization."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch
from app.agent import Agent
from app.tool_contracts import TOOL_SPECS, ToolSpec
from tests import test_business_request_phase as fixtures


class ToolRegistrationContractTests(unittest.TestCase):
    def test_incomplete_or_unimplemented_metadata_is_rejected(self):
        valid=TOOL_SPECS['list_invoices']
        for values in ({'result_adapter':'invented_adapter'}, {'reads_financial_data':False},
                       {'objects':()}, {'read_mode':'none'}, {'condition_mode':'infer_from_chinese'},
                       {'parameters':(('company_id','credential'),)}, {'normal':'true'}):
            with self.subTest(values=values),self.assertRaises(ValueError):replace(valid,**values)
        with self.assertRaises(TypeError):TOOL_SPECS['injected']=valid

    def test_unadapted_read_tools_still_need_current_runtime_basis(self):
        fixture=fixtures.BusinessRequestPhaseTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        agent=Agent('U001',fixture.book,lambda *_:None,mode='mock',trace_path=fixture.root/'registry.jsonl')
        for name,args in (('invoice_total',{'company_id':'C001','year':2026,'month':9}),
                          ('count_invoice_fields',{'company_id':'C001','year':2026,'month':9,'selector':'all'}),
                          ('not_a_registered_tool',{})):
            with self.subTest(name=name),patch('app.agent.handle_tool') as backend:
                result=agent.dispatch_tool(name,json.dumps(args),'U001',fixture.book)
                self.assertEqual(result['status'],'DENIED');backend.assert_not_called()

    def test_capability_presence_does_not_override_actor_or_request_turn(self):
        fixture=fixtures.BusinessRequestPhaseTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        from app.business_request import bind
        agent=Agent('U001',fixture.book,lambda *_:None,mode='mock',trace_path=fixture.root/'actor.jsonl')
        agent.trace_id='current-turn'
        for actor,turn in (('U001','retired-turn'),('U002','current-turn')):
            agent.business_request=bind(json.dumps(fixture.requirement(),ensure_ascii=False),actor=actor,
                book=fixture.book,turn_id=turn,request=fixture.text)
            with self.subTest(actor=actor,turn=turn),patch('app.agent.handle_tool') as backend:
                result=agent.dispatch_tool('get_finance_summary',json.dumps({'company_id':'C001','year':2026,'month':9}),
                                           'U001',fixture.book)
                self.assertNotEqual(result['status'],'SUCCESS');backend.assert_not_called()
