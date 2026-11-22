"""Original owner entry boundaries; scripted protocol evidence, no HTTP."""
from copy import deepcopy
import unittest
from app.references import invalidate_references
from tests import test_paired_target_reads as paired
envelope=paired.envelope


TEXT='范围就留在上面两张里，2026年9月那张才算这次要办的；备注预填“业务资料核验完毕”。先别认定票号，等我选。'
# Captured d884ffd independent semantic reply (trace line 33).
ROUTE={'kind':'legacy','turn_action':'continue','action_reason':'await_selection','action_quote':'等我选',
    'field':'remark','field_quote':'备注预填“业务资料核验完毕”',
    'value_relation':'replace','value_quote':'备注预填“业务资料核验完毕”',
    'pending_change':{'field':'remark','new_value':'业务资料核验完毕',
        'source':{'kind':'current','quote':'备注预填“业务资料核验完毕”'}},
    'matter_relation':'new','matter_quote':'2026年9月那张才算这次要办的',
    'reference_relation':'displayed','reference_quote':'范围就留在上面两张里'}
QUESTION=envelope({'kind':'clarification','text':'请选择要办理的发票。','missing_fields':['invoice_no']})


class SelectionHandoffTests(unittest.TestCase):
    setUp=paired.PairedTargetReadTests.setUp
    tearDown=paired.PairedTargetReadTests.tearDown
    facts=paired.PairedTargetReadTests.facts

    def ready(self):
        host=paired.PairedTargetReadTests.host(self)
        self.read_reply=deepcopy(self.q[0])
        view=paired.PairedTargetReadTests.query(self,host)
        host.acknowledge_display(view['display']['trace'],context=view['context'])
        return host

    def test_captured_semantic_reply_establishes_waiting_without_execution_model(self):
        host=self.ready();self.q.append(envelope(ROUTE));before=len(self.model_calls)
        view=host.send(TEXT);agent=host.host.agent
        self.assertEqual(len(self.model_calls),before+1)
        self.assertEqual(agent.last_response['execution']['actual_tool_calls'],0)
        self.assertEqual(agent.last_response['execution']['stop_reason'],'WAITING_USER')
        self.assertEqual(view['pending']['known']['month'],9)
        self.assertEqual(view['pending']['known']['new_value'],'业务资料核验完毕')
        self.assertNotIn('invoice_no',view['pending']['known'])
        self.assertTrue(agent.pending_intent['reference_collection'])
        self.assertFalse(view['preview'])

    def test_invalid_value_source_cannot_establish_trusted_pending(self):
        host=self.ready();route=deepcopy(ROUTE)
        route['pending_change']['source']['quote']='不在当前原话中的来源'
        self.q.extend([envelope(route),QUESTION])
        view=host.send(TEXT)
        self.assertFalse(host.host.agent.pending_intent)
        self.assertFalse(view['preview'])

    def test_invalidated_anchor_cannot_establish_trusted_pending(self):
        host=self.ready();invalidate_references(self.book,'U001')
        self.q.extend([envelope(ROUTE),QUESTION]);view=host.send(TEXT)
        self.assertFalse(host.host.agent.pending_intent)
        self.assertFalse(view['preview'])

    def test_new_matter_with_existing_pending_preserves_original_owner(self):
        host=self.ready();self.q.append(envelope(ROUTE));host.send(TEXT)
        old=deepcopy(host.host.agent.pending_intent)
        self.q.extend([envelope(ROUTE),QUESTION]);before=len(self.model_calls)
        view=host.send(TEXT)
        self.assertEqual(len(self.model_calls),before+2,'Matter conflict must retain original path')
        self.assertEqual(host.host.agent.pending_intent,old)
        self.assertFalse(view['preview'])

    def test_genuine_read_is_not_selection_waiting(self):
        host=self.ready();self.q.append(self.read_reply)
        view=paired.PairedTargetReadTests.query(self,host)
        self.assertTrue(view['current_result']['coverage']['complete'])
        self.assertFalse(host.host.agent.pending_intent)
        self.assertEqual(host.host.agent.last_response['execution']['stop_reason'],'ANSWERED')


if __name__=='__main__':unittest.main()
