"""Finite program evidence; scripted semantics do not prove natural language."""
import copy, json, unittest
from unittest.mock import patch
from app.business_request import BusinessRequestError
from tests import test_pending_relationship_repair as repair
tool=repair.tool


def envelope(value):
    return {'role':'assistant','content':json.dumps(value,ensure_ascii=False)}


class ClarificationOwnerTests(unittest.TestCase):
    setUp=repair.PendingRevisionRepairTests.setUp
    tearDown=repair.PendingRevisionRepairTests.tearDown
    facts=repair.PendingRevisionRepairTests.facts
    origin=repair.PendingRevisionRepairTests.origin
    matter_origin=repair.MatterOwnershipRepairTests.matter_origin
    seed_set=repair.MatterOwnershipRepairTests.seed_set

    def start(self, path):
        self.seed_set()  # Real SQLite query and actual display registration.
        text='从刚才那两张选一张，仅改备注为“附件另存待核”，等我选定，不保存。'
        route={'kind':'legacy','action_reason':'await_selection','field':'remark','field_quote':'改备注',
               'matter_relation':'new','matter_quote':'选一张，仅改备注',
               'reference_relation':'displayed','reference_quote':'刚才那两张'}
        change={'field':'remark','new_value':'附件另存待核','source':{'kind':'current','quote':'改备注为“附件另存待核”'}}
        final={'kind':'clarification','text':'等待选票。','missing_fields':['invoice_no'],'pending_change':change}
        replies=[envelope(route),envelope(final) if path=='direct' else tool({'field':'remark','new_value':'附件另存待核'})]
        self.agent.model=lambda *_:replies.pop(0)
        with patch('app.invoice_action.get_invoice',side_effect=AssertionError('No single read before selection')):
            self.agent.ask(text)
        self.assertFalse(replies)
        state=self.agent.pending_intent
        self.assertEqual(state['change']['new_value'],['附件另存待核'])
        self.assertIn('reference_collection',state)
        self.assertIn('new_value',state['provenance'])
        self.assertNotIn('invoice_no',state['scope'])
        self.assertFalse(getattr(self.agent,'paused_invoice_candidate',None))
        self.assertFalse(self.agent.last_response.get('invoice_change'))
        self.assertFalse(self.agent.update_session.drafts)
        return copy.deepcopy(state)

    def test_direct_and_tool_clarifications_preserve_set_then_fresh_select(self):
        from app.queries import get_invoice
        for path in ('direct','tool'):
            with self.subTest(path=path):
                original=self.start(path)
                # A later direct clarification must not erase a tool-bound value.
                text='还是等我选票，备注内容沿用，不要另办。'
                self.agent.model=iter([envelope({'kind':'legacy','action_reason':'await_selection',
                    'value_relation':'keep','value_quote':'备注内容沿用','matter_relation':'continue','matter_quote':'不要另办'}),
                    envelope({'kind':'clarification','text':'请选票。','missing_fields':['invoice_no']})]).__next__
                replies=self.agent.model
                self.agent.model=lambda *_:replies()
                with patch('app.invoice_action.get_invoice',side_effect=AssertionError('No single read while waiting')):
                    self.agent.ask(text)
                self.assertEqual(self.agent.pending_intent['change'],original['change'])
                self.assertEqual(self.agent.pending_intent['reference_collection'],original['reference_collection'])
                text='选F004，沿用备注。'
                replies=iter([envelope({'kind':'legacy','value_relation':'keep','value_quote':'沿用备注',
                    'matter_relation':'continue','matter_quote':'选F004'}),tool({'invoice_no':'F004'})])
                self.agent.model=lambda *_:next(replies)
                with patch('app.invoice_action.get_invoice',wraps=get_invoice) as fresh:
                    self.agent.ask(text)
                self.assertTrue(fresh.called)
                planned=self.agent.last_response['invoice_change']
                self.assertEqual(tuple(planned['invoice_nos']),('F004',))
                self.assertEqual(planned['new_value'],'附件另存待核')

    def test_outside_set_and_unsourced_prose_cannot_bind(self):
        before=self.start('direct')
        text='就这两张中的F008。'
        replies=iter([envelope({'kind':'legacy','value_relation':'keep','value_quote':text,
                     'matter_relation':'continue','matter_quote':text}),tool({'invoice_no':'F008'})])
        self.agent.model=lambda *_:next(replies)
        with patch('app.invoice_action.get_invoice',side_effect=AssertionError('Outside target cannot read')):
            self.agent.ask(text)
        self.assertEqual(self.agent.pending_intent['change'],before['change'])
        self.assertFalse(self.agent.last_response.get('invoice_change'))
        from app.invoice_action import bind_clarification
        denied,state,proposal,reads=bind_clarification(self.agent,['invoice_no'],before,'等待选票',
            change={'field':'remark','new_value':'正文伪造','source':{'kind':'current','quote':'正文伪造'}})
        self.assertEqual(denied['status'],'DENIED')
        self.assertEqual(state,before);self.assertIsNone(proposal);self.assertFalse(reads)

    def test_body_only_and_unrelated_reference_do_not_supply_values_or_objects(self):
        from app.invoice_action import bind_clarification, change_invoice
        from app.intent_contract import BoundIntent
        self.seed_set()
        text='从刚才两张选一张改备注，等待选定。'
        result,state,proposal,reads=bind_clarification(self.agent,['invoice_no'],None,text,field='remark')
        self.assertNotIn('new_value',state['change'])
        self.assertIsNone(proposal);self.assertFalse(reads)
        text='独立新事项，备注改为“保留候选值”，对象稍后给。'
        source=BoundIntent('amend','U001',str(self.book),self.agent.trace_id,text,
            {'matter_relation':'new','reference_relation':'none'},
            {'source':'independent_business_entry','matter_quote':'独立新事项','reference_quote':'对象稍后给'})
        result,state,proposal,reads=change_invoice(self.agent,{'field':'remark','new_value':'保留候选值'},None,text,revision_origin=source)
        self.assertNotIn('reference_collection',state)
        self.assertNotIn('invoice_no',state['scope'])
        self.assertEqual(state['change']['new_value'],['保留候选值'])
        self.assertFalse(reads);self.assertIsNone(proposal)

    def test_explicit_pause_creates_real_recoverable_record(self):
        from app.session_store import SessionStore
        from app.session_host import SessionHost
        state=self.start('direct')
        store=SessionStore(self.book.parent/'sessions.sqlite',self.book,'U001')
        self.addCleanup(store.close)
        store.set_invoice_pending(state,state='ACTIVE')
        from app.agent import Agent
        replies=iter([envelope({'kind':'legacy','turn_action':'pause','action_reason':'defer_matter',
            'action_quote':'把整个事项暂缓','value_relation':'keep','value_quote':'内容保留',
            'matter_relation':'continue','matter_quote':'把整个事项暂缓'}),
            envelope({'kind':'clarification','text':'暂缓等待。','missing_fields':['invoice_no']})])
        host=SessionHost(store,lambda actor,book:Agent(actor,book,lambda *_:next(replies),mode='mock'))
        with patch('app.invoice_action.get_invoice',side_effect=AssertionError('Pause needs no single read')):
            view=host.send_message('把整个事项暂缓，内容保留。',expected=host.snapshot()['context'])
        with store.connection() as db:
            row=db.execute('SELECT * FROM invoice_candidates WHERE id=?',(store.invoice_token[0],)).fetchone()
            self.assertEqual(row['state'],'PAUSED')
        self.assertTrue(store.list_invoice_candidates())
        self.assertEqual(view['business_status'],'PAUSED')
        self.assertEqual(view['pending']['known']['new_value'],'附件另存待核')


class IndependentActionTests(unittest.TestCase):
    def test_waiting_is_not_matter_deferral(self):
        from app.business_request import legacy_action
        for reason in ('await_selection', 'await_value'):
            self.assertEqual(legacy_action({'action_reason': reason}), 'continue')
            with self.assertRaises(BusinessRequestError):
                legacy_action({'turn_action': 'pause', 'action_reason': reason})
        self.assertEqual(legacy_action({'turn_action':'pause','action_reason':'defer_matter'}),'pause')
        for action in ('pause',False,''):
            with self.assertRaises(BusinessRequestError):
                legacy_action({'turn_action':action})


if __name__ == '__main__':
    unittest.main()
