"""Public failure regressions, scripted contract evidence only; no model API."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.invoice_batch import run_invoice_batch
from app.pending_transition import transition, PendingTransitionError
from app.responses import request_scope
from tests.test_tui_p0 import FIXTURE
from tests.test_model_intent import call, final
from tests.test_sql_invoice_selection import snapshot


REQUEST = '这次处理甲企业2026年9月：先核一下F002和F010的用途。我还想给其中一张加一条备注“凭证附件已核”，票号留到下一条再定，眼下只查。'
AMEND = '落在F002。备注内容重新定为“合同附件已核”，前面那版不用了。请把当前备注和拟写入内容给我审核。'


class UnboundPendingTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.book = Path(tmp.name) / 'book.sqlite3'
        import_workspace(FIXTURE, self.book)

    def pending_agent(self, *, company='C001', field='remark', value='合同附件已核', clarify=False):
        stage = 0
        agent = None
        def model(messages, tools):
            nonlocal stage
            stage += 1
            if stage == 1:
                result = call('get_invoice', {'company_id':'C001','invoice_no':'F002'}, ident='one')
                result['tool_calls'] += call('get_invoice', {'company_id':'C001','invoice_no':'F010'}, ident='two')['tool_calls']
                return result
            if stage == 2:
                return final(kind='clarification', text='请指定要加备注的票号。', missing_fields=['invoice_no'],
                    pending_change={'field':'remark','new_value':'凭证附件已核'},
                    pending={'action':'create','scope':{'company_id':['C001'],'year':[2026],'month':[9]}})
            if clarify:
                return final(kind='clarification', text='仍需明确票号。', missing_fields=['invoice_no'],
                    pending={'action':'continue','request_id':agent.pending_intent['request_id']})
            if stage == 3:
                return call('get_invoice', {'company_id':company,'invoice_no':'F002'})
            if stage == 4:
                read = next(json.loads(m['content']) for m in reversed(messages) if m['role']=='tool')
                if read['status'] != 'SUCCESS':
                    return final(missing_fields=[])
                return call('propose_invoice_changes', {'selection_id':read['data']['selection_id'],
                    'field':field,'new_value':value,'mode':'item','excluded_invoice_ids':[],
                    'pending_request_id':agent.pending_intent['request_id'],'target_year':2026,'target_month':9})
            return final(missing_fields=[])
        agent = Agent('U001', self.book, model, mode='mock', trace_path=self.book.with_suffix('.jsonl'))
        agent.ask(REQUEST)
        self.assertIsNotNone(agent.pending_intent)
        self.assertNotIn('invoice_no', agent.pending_intent['scope'])
        self.assertEqual(agent.pending_intent['scope']['company_id'], ['C001'])
        self.assertEqual(agent.pending_intent['scope']['periods'], [(2026,9)])
        return agent

    def test_public_amendment_reaches_formal_preview_without_commit(self):
        before = snapshot(self.book)
        agent = self.pending_agent()
        self.assertIsNone(agent.last_response.get('invoice_change'))
        agent.ask(AMEND)
        change = agent.last_response.get('invoice_change')
        self.assertIsNotNone(change)
        self.assertEqual((change['company_id'],change['invoice_nos'],change['field'],change['new_value']),
                         ('C001',('F002',),'remark','合同附件已核'))
        previews = []
        run_invoice_batch(agent, agent.last_user_request, change, approve_batch=lambda *_:False,
                          approve_item=lambda body:previews.append(body) or False, checkpoint=lambda *_:None)
        self.assertTrue(previews)
        self.assertIn('合同附件已核', previews[0])
        self.assertEqual(snapshot(self.book), before)

    def test_unknown_invoice_stays_unbound_and_waits(self):
        before = snapshot(self.book)
        agent = self.pending_agent(clarify=True)
        agent.ask('具体票号还未定，先别处理。')
        self.assertNotIn('invoice_no', agent.pending_intent['scope'])
        self.assertIsNone(agent.last_response.get('invoice_change'))
        self.assertEqual(snapshot(self.book), before)

    def test_wrong_company_field_and_unsourced_value_cannot_preview(self):
        before = snapshot(self.book)
        for patch in ({'company':'C002'}, {'field':'purpose'}, {'value':'未经用户要求的值'}):
            with self.subTest(patch=patch):
                agent = self.pending_agent(**patch)
                agent.ask(AMEND)
                self.assertIsNone(agent.last_response.get('invoice_change'))
                self.assertEqual(snapshot(self.book), before)

    def test_unbound_scope_cannot_accept_an_unsourced_company_or_invoice(self):
        for patch in ({'company_id':['C002']}, {'invoice_no':['F999']}):
            with self.subTest(patch=patch), self.assertRaises(PendingTransitionError):
                transition(None, {'action':'create','scope':patch}, actor='U001',book=self.book,
                           current_id='new', current_request=REQUEST, current_scope=request_scope(REQUEST,True),
                           missing_fields=['invoice_no'], change={'field':'remark','new_value':'凭证附件已核'})


if __name__ == '__main__':
    unittest.main()
