"""One public failure and action contracts; scripted models, zero model API."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.invoice_batch import run_invoice_batch
from app.pending_transition import request_change, PendingRequestError
from app.tool_registry import validate_arguments, TOOLS
from tests.test_tui_p0 import FIXTURE
from tests.test_model_intent import call, final
from tests.test_sql_invoice_selection import snapshot


PUBLIC = '乙企业2026年9月这批，麻烦先告诉我F002、F006各自写没写用途。还有个备注整理的事：两张里我想选一张备注填“附件回收待核”，选哪张还没定，先别做变更。'


class InvoiceRequestTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.book = Path(tmp.name) / 'book.sqlite3'
        import_workspace(FIXTURE, self.book)

    def request_agent(self):
        stage = 0
        agent = None
        def model(messages, tools):
            nonlocal stage
            stage += 1
            if stage == 1:
                read = call('get_invoice', {'company_id':'C002','invoice_no':'F002'}, ident='first')
                read['tool_calls'] += call('get_invoice', {'company_id':'C002','invoice_no':'F006'}, ident='second')['tool_calls']
                return read
            if stage == 2:
                return call('propose_invoice_changes', {'action':'request','field':'remark','new_value':'附件回收待核'})
            if stage == 3:
                return call('get_invoice', {'company_id':'C002','invoice_no':'F006'})
            if stage == 4:
                read = next(json.loads(m['content']) for m in reversed(messages) if m['role']=='tool')
                return call('propose_invoice_changes', {'selection_id':read['data']['selection_id'],
                    'field':'remark','new_value':'凭据整理复核','mode':'item','excluded_invoice_ids':[],
                    'pending_request_id':agent.pending_intent['request_id'], 'target_year':2026,'target_month':9})
            self.fail('request must stop without final lifecycle JSON')
        agent = Agent('U001', self.book, model, mode='mock', trace_path=self.book.with_suffix('.jsonl'))
        agent.ask(PUBLIC)
        return agent

    def test_public_request_persists_known_slots_and_delivers_authoritative_question(self):
        before = snapshot(self.book)
        agent = self.request_agent()
        pending = agent.pending_intent
        self.assertIsNotNone(pending)
        self.assertEqual(pending['scope']['company_id'], ['C002'])
        self.assertEqual(pending['scope']['periods'], [(2026,9)])
        self.assertNotIn('invoice_no', pending['scope'])
        self.assertEqual(pending['change'], {'field':['remark'],'new_value':['附件回收待核']})
        self.assertEqual(pending['missing_fields'], ('invoice_no',))
        self.assertEqual(agent.last_response['execution']['model_requests'], 2)
        self.assertEqual(agent.last_response['execution']['stop_reason'], 'WAITING_USER')
        self.assertIn('发票编号', agent.last_response['text'])
        self.assertIsNone(agent.last_response.get('invoice_change'))
        self.assertFalse(agent.update_session.drafts)
        self.assertEqual(snapshot(self.book), before)

    def test_request_then_explicit_target_fresh_proposal_reaches_preview_without_write(self):
        before = snapshot(self.book)
        agent = self.request_agent()
        agent.ask('选F006，备注重新定为“凭据整理复核”，请核对后给我预览。')
        change = agent.last_response.get('invoice_change')
        self.assertIsNotNone(change)
        self.assertEqual((change['company_id'],change['invoice_nos'],change['field'],change['new_value']),
                         ('C002',('F006',),'remark','凭据整理复核'))
        previews = []
        run_invoice_batch(agent, agent.last_user_request, change, approve_batch=lambda *_:False,
                          approve_item=lambda body:previews.append(body) or False, checkpoint=lambda *_:None)
        self.assertTrue(previews)
        self.assertIn('凭据整理复核', previews[0])
        self.assertEqual(snapshot(self.book), before)

    def test_request_schema_does_not_weaken_complete_proposals(self):
        self.assertEqual(validate_arguments('propose_invoice_changes','{"action":"request"}'), {'action':'request'})
        complete = {'selection_id':'fresh','field':'remark','new_value':'值','mode':'item','excluded_invoice_ids':[]}
        self.assertEqual(validate_arguments('propose_invoice_changes',json.dumps(complete)), complete)
        for missing in complete:
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                validate_arguments('propose_invoice_changes',json.dumps({k:v for k,v in complete.items() if k!=missing}))
        for extra in ({'selection_id':'x'}, {'mode':'item'}, {'write_scope':{}}, {'actor':'U001'},
                      {'confirmed':True}, {'pending_request_id':'invented'}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                validate_arguments('propose_invoice_changes',json.dumps({'action':'request',**extra}))
        schema = next(t['function']['parameters'] for t in TOOLS if t['function']['name']=='propose_invoice_changes')
        self.assertEqual(set(schema['anyOf'][1]['required']),set(complete))

    def test_missing_business_slots_create_only_unbound_pending(self):
        replies = iter((call('propose_invoice_changes',{'action':'request'}),))
        agent = Agent('U001',self.book,lambda *_:next(replies),mode='mock',trace_path=self.book.with_suffix('.jsonl'))
        agent.ask('我有一项发票办理，细节下一条再说。')
        self.assertEqual(agent.pending_intent['scope'], {})
        self.assertEqual(set(agent.pending_intent['missing_fields']),
                         {'company_id','invoice_no','year','month','field','new_value'})
        self.assertIsNone(agent.last_response.get('invoice_change'))

    def test_untrusted_owner_field_value_identity_and_book_are_rejected(self):
        args = {'action':'request','field':'remark','new_value':'附件回收待核'}
        base = dict(actor='U001',book=self.book,current_id='now',current_request='乙企业2026年9月备注填“附件回收待核”，票号未定。')
        pending = request_change(args,None,**base)
        for patch in ({'company_id':'C001'}, {'invoice_no':'F999'}, {'field':'purpose'}, {'new_value':'伪造值'}):
            with self.subTest(patch=patch), self.assertRaises(PendingRequestError):
                request_change({**args,**patch},None,**base)
        for patch in ({'actor':'U002'}, {'book':self.book.with_name('other.sqlite3')}):
            with self.subTest(patch=patch), self.assertRaises(PendingRequestError):
                request_change(args,pending,**{**base,**patch})
        with self.assertRaises(PendingRequestError):
            request_change(args,None,**{**base,'actor':'U002'})

    def test_request_cannot_pair_inherited_field_with_another_current_field_value(self):
        base = dict(actor='U001',book=self.book,current_id='now',current_request='乙企业备注填“旧值”，票号后补。')
        pending = request_change({'action':'request','field':'remark','new_value':'旧值'},None,**base)
        with self.assertRaises(PendingRequestError):
            request_change({'action':'request','new_value':'新用途'},pending,
                           **{**base,'current_request':'用途改成“新用途”。'})

    def test_public_read_field_and_unselected_read_invoice_are_not_write_sources(self):
        base = dict(actor='U001',book=self.book,current_id='now',current_request=PUBLIC)
        for patch in ({'field':'purpose'}, {'invoice_no':'F002'}):
            with self.subTest(patch=patch), self.assertRaises(PendingRequestError):
                request_change({'action':'request','field':'remark','new_value':'附件回收待核',**patch},None,**base)


if __name__ == '__main__':
    unittest.main()
