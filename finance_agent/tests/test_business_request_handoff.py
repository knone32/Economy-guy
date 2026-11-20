"""Preserve handoff business invariants through the unified semantic boundary.

Only the legacy-negative control deliberately exercises the old read sidecar.
Acceptance does not prescribe its extra protocol round trips.
"""
from contextlib import closing
import copy
import json
import sqlite3
import unittest
from app.agent import Agent
from tests import test_business_request_phase as fixtures
tool=fixtures.tool


class BusinessRequestHandoffTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BusinessRequestPhaseTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.book=self.fixture.book

    def run_handoff(self, *, max_requests=9, forbidden_write=False, semantic_kind='read',legacy_negative=False):
        first='C001 2026年9月F001的备注要修改，新值稍后补。'
        second='先不改，查C001 2026年8月全部发票金额和张数。'
        requirement=self.fixture.requirement();target=requirement['targets'][0]
        target.update(periods=[[2026,8]],period_quote='2026年8月')
        seen=[];turn=1
        intent={'action':'read','target':{'company_id':'C001','year':2026,'month':8},
                'sources':{k:{'kind':'current','text':second} for k in ('company_id','year','month')}}
        def model(messages, tools):
            seen.append((turn,copy.deepcopy(messages),copy.deepcopy(tools)))
            if turn==1:
                if not tools:return {'role':'assistant','content':'{"kind":"legacy"}'}
                return {'role':'assistant','tool_calls':[tool('pending','change_invoice',company_id='C001',
                    invoice_no='F001',year=2026,month=9,field='remark')]}
            n=sum(t==2 for t,_,_ in seen)
            if legacy_negative:
                if n==1:return {'role':'assistant','content':'{"kind":"legacy"}'}
                if n==2:return {'role':'assistant','content':json.dumps({'intent':intent},ensure_ascii=False),
                    'tool_calls':[tool('deferred-summary','get_finance_summary',company_id='C001',year=2026,month=8),
                                  tool('deferred-invoice','get_invoice',company_id='C001',invoice_no='F001')]}
                return {'role':'assistant','content':json.dumps({'kind':semantic_kind},ensure_ascii=False)}
            if n==1:return {'role':'assistant','content':json.dumps(requirement,ensure_ascii=False)}
            if n==2:
                call=(tool('bad-write','change_invoice',company_id='C001',invoice_no='F001',year=2026,month=9,
                           field='remark',new_value='不应保存') if forbidden_write else
                      tool('read','query_business_sql',sql="SELECT SUM(amount_cents) AS amount,COUNT(*) AS n FROM invoices WHERE company_id='C001' AND substr(invoice_date,1,7)='2026-08'"))
                return {'role':'assistant','tool_calls':[call]}
            # Current facts are supplied by the production answer prompt.
            prompt=next(m['content'] for m in reversed(messages) if m.get('name')=='answer_catalog')
            refs=[fact['ref'] for fact in json.loads(prompt.rsplit('\n',1)[1]) if fact.get('type')=='scalar']
            return {'role':'assistant','content':json.dumps({'kind':'information','text':'依据本轮证据回答。','answer':refs},ensure_ascii=False)}
        a=Agent('U001',self.book,model,mode='mock',trace_path=self.fixture.root/'handoff.jsonl')
        with closing(sqlite3.connect(self.book)) as db:
            before=db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no').fetchall()
        a.ask(first);pending=copy.deepcopy(a.pending_intent)
        self.assertIsNotNone(pending);self.assertEqual(a.last_response['execution']['stop_reason'],'WAITING_USER')
        a.max_requests=max_requests
        turn=2;answer=a.ask(second)
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(before,db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no').fetchall())
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)
        if a.business_request is not None:
            self.assertEqual(a.paused_invoice_candidate,pending)
            self.assertIsNone(a.pending_intent)
            self.assertIn('暂挂',answer)
        else:
            # No validated read has replaced the business action. Its original
            # unapproved data remains with the existing owner, without a draft.
            self.assertEqual(a.pending_intent,pending)
            self.assertIsNone(a.paused_invoice_candidate)
        self.assertFalse(a.update_session.drafts);self.assertFalse(a.update_session.confirmations)
        ids=[c['id'] for m in a.messages if m.get('role')=='assistant' for c in m.get('tool_calls') or []]
        paired=[m['tool_call_id'] for m in a.messages if m.get('role')=='tool']
        self.assertCountEqual(ids,paired)
        if legacy_negative:
            deferred=[json.loads(m['content']) for m in a.messages if m.get('role')=='tool'
                      and m['tool_call_id'].startswith('deferred-')]
            self.assertEqual(len(deferred),2)
            self.assertTrue(all(r['status']=='NOT_READY' for r in deferred))
        return a,answer,[x for x in seen if x[0]==2],second

    def test_new_read_enters_independent_stage_without_old_invoice_scope(self):
        a,answer,seen,text=self.run_handoff()
        semantic=[messages for _,messages,tools in seen if not tools]
        self.assertTrue(semantic)
        source=json.loads(semantic[-1][1]['content'])
        self.assertEqual(source['request'],text)
        self.assertNotIn('invoice_no',source['trusted_scope'])
        self.assertNotIn('month',source['trusted_scope'])
        self.assertNotIn('deferred-summary',json.dumps(semantic[-1],ensure_ascii=False))
        self.assertNotIn('SELECT ',json.dumps(semantic[-1]))
        self.assertEqual(a.business_request.context_transition,'pending_to_read')
        self.assertEqual(a.business_request.targets[0].periods,((2026,8),))
        results=a.last_response['tool_results']
        self.assertEqual(len(results),1)
        self.assertEqual(results[0][1]['status'],'SUCCESS')
        with closing(sqlite3.connect(self.book)) as db:
            truth=db.execute("SELECT SUM(amount_cents),COUNT(*) FROM invoices WHERE company_id='C001' AND substr(invoice_date,1,7)='2026-08'").fetchone()
        self.assertEqual(tuple(results[0][1]['data']['rows'][0]),truth)
        self.assertIn('10 张',answer)
        self.assertEqual(results[0][1]['evidence']['read_basis']['kind'],'business_request')
        self.assertTrue(a.last_response['business_request_final_coverage']['complete'])
        self.assertEqual(a.last_response['execution']['actual_tool_calls'],1)

    def test_no_remaining_slot_keeps_unsubmitted_candidate_without_dispatch(self):
        a,answer,seen,_=self.run_handoff(max_requests=1)
        self.assertEqual(a.last_response['execution']['actual_tool_calls'],0)

    def test_read_cannot_submit_paused_edit(self):
        a,answer,seen,_=self.run_handoff(forbidden_write=True)
        self.assertEqual(a.last_response['execution']['actual_tool_calls'],0)
        self.assertEqual(a.last_response['execution']['stop_reason'],'DENIED')

    def test_handoff_semantic_reply_cannot_escape_back_to_legacy_writes(self):
        a,answer,seen,_=self.run_handoff(semantic_kind='legacy',legacy_negative=True)
        self.assertIsNone(a.business_request)
        self.assertEqual(a.last_response['execution']['actual_tool_calls'],0)
        self.assertEqual(a.last_response['execution']['stop_reason'],'INVALID_ARGUMENTS')
