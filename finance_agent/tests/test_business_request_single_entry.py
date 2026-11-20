"""Natural read proposals do not need a second legacy read-intent sidecar."""
from contextlib import closing
import copy
import json
import sqlite3
import unittest
from app.agent import Agent
from tests import test_business_request_phase as fixtures


def semantic_input(messages):
    if len(messages)!=2 or messages[1].get('role')!='user':return False
    try:return set(json.loads(messages[1]['content']))=={
        'request','read_catalog','trusted_scope','previous_requirement','business_definition'}
    except (ValueError,TypeError):return False


class SingleEntryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BusinessRequestPhaseTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.book=self.fixture.book

    def test_pending_read_binds_before_sql_or_dedicated_proposal_without_old_intent(self):
        for query_tool in ('query_business_sql','get_finance_summary'):
            with self.subTest(query_tool=query_tool):
                phase='prepare';seen=[]
                requirement=self.fixture.requirement();target=requirement['targets'][0]
                target.update(periods=[[2026,8]],period_quote='2026年8月')
                def model(messages,tools):
                    seen.append({'phase':phase,'semantic':semantic_input(messages),'tools':copy.deepcopy(tools),
                                 'messages':copy.deepcopy(messages)})
                    if phase=='prepare':
                        if semantic_input(messages):return {'role':'assistant','content':'{"kind":"legacy"}'}
                        return {'role':'assistant','tool_calls':[fixtures.tool('start','change_invoice',
                            company_id='C001',invoice_no='F001',year=2026,month=9,field='remark')]}
                    if semantic_input(messages):
                        return {'role':'assistant','content':json.dumps(requirement,ensure_ascii=False)}
                    prompt=next(m for m in reversed(messages) if m.get('name')=='answer_catalog')
                    facts=json.loads(prompt['content'].rsplit('\n',1)[1])
                    refs=[f['ref'] for f in facts if f.get('type')=='scalar']
                    if refs:return {'role':'assistant','content':json.dumps({'kind':'information','text':'本轮结果。','answer':refs})}
                    args=({'sql':"SELECT SUM(amount_cents) AS cents,COUNT(*) AS n FROM invoices WHERE company_id='C001' AND substr(invoice_date,1,7)='2026-08'"}
                          if query_tool=='query_business_sql' else {'company_id':'C001','year':2026,'month':8})
                    # This is the natural proposal shape observed in R01: no
                    # old intent sidecar. Its scope is not an independent request.
                    return {'role':'assistant','tool_calls':[fixtures.tool('read',query_tool,**args)]}
                a=Agent('U001',self.book,model,mode='mock',trace_path=self.fixture.root/(query_tool+'.jsonl'))
                a.ask('C001 2026年9月 F001备注要修改，内容稍后补。')
                pending=copy.deepcopy(a.pending_intent);self.assertIsNotNone(pending)
                with closing(sqlite3.connect(self.book)) as db:
                    before=db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no').fetchall()
                    truth=db.execute("SELECT SUM(amount_cents),COUNT(*) FROM invoices WHERE company_id='C001' AND substr(invoice_date,1,7)='2026-08'").fetchone()
                phase='read';answer=a.ask('单票修改先放着，请查C001 2026年8月全部发票金额和张数。')
                self.assertIsNotNone(a.business_request)
                self.assertTrue(next(s for s in seen if s['phase']=='read')['semantic'])
                self.assertEqual(a.business_request.targets[0].periods,((2026,8),))
                self.assertEqual(a.business_request.targets[0].filters,())
                self.assertTrue(a.last_response['business_request_final_coverage']['complete'])
                self.assertEqual(a.paused_invoice_candidate,pending);self.assertIsNone(a.pending_intent)
                self.assertFalse(a.update_session.drafts);self.assertFalse(a.update_session.confirmations)
                self.assertIn('暂挂',answer)
                if query_tool=='query_business_sql':
                    result=next(r for n,r in a.last_response['tool_results'] if n==query_tool)
                    self.assertEqual(tuple(result['data']['rows'][0]),truth)
                with closing(sqlite3.connect(self.book)) as db:
                    self.assertEqual(before,db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no').fetchall())
                    self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)

    def test_same_entry_can_continue_native_edit_without_read_request(self):
        phase='start'
        def model(messages,tools):
            if semantic_input(messages):return {'role':'assistant','content':'{"kind":"legacy"}'}
            args={'company_id':'C001','invoice_no':'F001','year':2026,'month':9,'field':'remark'} if phase=='start' else {'new_value':'复核资料'}
            return {'role':'assistant','tool_calls':[fixtures.tool('native','change_invoice',**args)]}
        a=Agent('U001',self.book,model,mode='mock',trace_path=self.fixture.root/'continue.jsonl')
        a.ask('C001 2026年9月 F001备注要修改，内容稍后补。')
        phase='continue';a.ask('备注填写“复核资料”，用途别动。')
        self.assertIsNone(a.business_request);self.assertIsNone(a.paused_invoice_candidate)
        self.assertEqual(a.last_response['execution']['stop_reason'],'WAITING_CONFIRMATION')
        change=a.last_response['invoice_change']
        self.assertEqual((change['company_id'],tuple(change['invoice_nos']),change['field'],change['new_value']),
                         ('C001',('F001',),'remark','复核资料'))
        # The existing UI/batch owner creates the formal draft from this
        # validated preview candidate; a read request is never its owner.
        self.assertFalse(a.update_session.drafts)
        self.assertFalse(a.update_session.confirmations)
        with closing(sqlite3.connect(self.book)) as db:
            self.assertNotEqual(db.execute("SELECT remark FROM invoices WHERE company_id='C001' AND invoice_no='F001'").fetchone()[0],'复核资料')
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)
