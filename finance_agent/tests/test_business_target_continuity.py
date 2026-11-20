"""Public single-invoice path: the patch cannot silently retain a contradicted target."""
from copy import deepcopy
import unittest

from tests import test_business_sources as base
from tests.test_model_intent import call


class TargetContinuityTests(unittest.TestCase):
    setUp = base.BusinessSourceTests.setUp
    tearDown = base.BusinessSourceTests.tearDown
    ask = base.BusinessSourceTests.ask
    start = base.BusinessSourceTests.start
    preview = base.BusinessSourceTests.preview

    def prepare_known_target(self):
        self.ask('甲企业2026年9月 F006 的备注要改。新内容稍后明确。',
                 company_id='C001',year=2026,month=9,invoice_no='F006',field='remark')
        pending=deepcopy(self.agent.pending_intent)
        self.assertEqual(pending['scope']['invoice_no'], ['F006'])
        self.assertEqual(pending['change'], {'field':['remark']})

    def test_model_patch_may_not_inherit_a_contradicted_invoice(self):
        self.prepare_known_target()
        reply=self.ask('票号更正为F010，备注写「核对完毕」。给我预览。',
                       new_value='核对完毕')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))
        self.assertNotIn('invoice_no', self.agent.pending_intent['scope'])
        self.assertNotIn('invoice_no', self.agent.pending_intent['provenance'])
        self.assertIn('invoice_no', self.agent.pending_intent['missing_fields'])
        self.assertIn('发票', reply)
        self.ask('再明确一次，是 F010。', invoice_no='F010')
        plan,body=self.preview()
        self.assertEqual((plan['invoice_nos'],plan['new_value']),(('F010',),'核对完毕'))
        self.assertIn('原值　月底资料整理',body)

    def test_same_explicit_target_or_no_new_identifier_can_inherit(self):
        for text in ('F006，备注写「项目交接」。', '还是上一张，备注写「项目交接」。'):
            with self.subTest(text=text):
                self.agent.cancel_update()
                self.prepare_known_target()
                self.ask(text,new_value='项目交接')
                self.assertEqual(self.preview()[0]['invoice_nos'], ('F006',))

    def test_a_reference_inside_an_unquoted_value_is_data_not_a_target(self):
        self.prepare_known_target()
        value='参照乙企业2026年10月F010台账'
        self.ask(f'请把原票备注写成{value}，其余不变。',new_value=value,invoice_no='F006')
        plan,body=self.preview()
        self.assertEqual((plan['company_id'],plan['month'],plan['invoice_nos'],plan['new_value']),
                         ('C001',9,('F006',),value))
        self.assertIn('原值　按月结算',body)

    def test_quoted_value_may_match_a_separately_specified_target(self):
        self.start()
        self.ask('F010 的用途改为「F010」；先看预览。', invoice_no='F010',new_value='F010')
        plan,_=self.preview()
        self.assertEqual((plan['invoice_nos'],plan['new_value']),(('F010',),'F010'))

    def test_value_cannot_supply_a_target_if_it_is_its_only_source(self):
        self.start()
        value='参考F010台账'
        self.ask('备注写成'+value+'。',field='remark',new_value=value,invoice_no='F010')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))
        self.assertNotIn('invoice_no',self.agent.pending_intent['scope'])


    def test_echo_with_missing_reference_can_be_repaired_once(self):
        self.start()
        seen = []
        def model(_, tools):
            seen.append([item['function']['name'] for item in tools])
            if len(seen) == 1:
                return call('change_invoice', {'invoice_no':'F006','field':'purpose',
                                               'new_value':'生产资料领用'})
            return call('change_invoice', {'invoice_no':'F006','value_ref':'previous'}, ident='corrected-source')
        self.agent.model = model
        self.agent.ask('编号是 F006，其余沿用上一办理，先看预览。')
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[1], ['change_invoice'])
        self.assertEqual(self.preview()[0]['new_value'], '生产资料领用')

    def test_echo_repair_never_silently_uses_old_value_on_correction(self):
        for mode in ('literal', 'echo', 'no_action'):
            with self.subTest(mode=mode):
                self.agent.cancel_update()
                self.start()
                calls = []
                def model(_, __):
                    calls.append(True)
                    if len(calls) == 2 and mode == 'no_action':
                        return {'role':'assistant','content':'{"kind":"information","text":"已保存。"}'}
                    value = '复查交接' if len(calls) == 2 and mode == 'literal' else '生产资料领用'
                    return call('change_invoice', {'invoice_no':'F006','new_value':value}, ident=f'action-{len(calls)}')
                self.agent.model = model
                reply=self.agent.ask('票号 F006，但原内容不要了。新值是复查交接，先核对。')
                self.assertEqual(len(calls),2)
                if mode == 'literal':
                    self.assertEqual(self.preview()[0]['new_value'],'复查交接')
                else:
                    self.assertIsNone(self.agent.last_response.get('invoice_change'))
                    self.assertNotIn('new_value',self.agent.pending_intent['change'])
                    self.assertNotIn('已保存',reply)

    def test_bounded_repair_cannot_extend_budget(self):
        self.start()
        self.agent.max_requests = 1
        self.ask('F006，按原内容。',invoice_no='F006',new_value='生产资料领用')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))
        self.assertNotIn('new_value',self.agent.pending_intent['change'])


    def test_repeated_unquoted_target_and_value_cannot_mask_target_conflict(self):
        self.prepare_known_target()
        self.ask('改的是F010，备注拟填写F010。', new_value='F010')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))
        self.assertNotIn('invoice_no',self.agent.pending_intent['scope'])
        self.ask('F010 的备注填写「F010」。', invoice_no='F010',new_value='F010')
        self.assertEqual(self.preview()[0]['invoice_nos'],('F010',))

    def test_rejected_old_invoice_argument_cannot_reactivate_on_later_value_only(self):
        self.prepare_known_target()
        self.ask('票改为F010，内容晚一点再给。',invoice_no='F006')
        self.assertNotIn('invoice_no',self.agent.pending_intent['scope'])
        self.ask('内容是「查阅已毕」，请先预览。', new_value='查阅已毕')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))
        self.ask('编号确认 F010。',invoice_no='F010')
        self.assertEqual(self.preview()[0]['invoice_nos'],('F010',))


    def test_single_unquoted_literal_cannot_swallow_an_omitted_target(self):
        self.prepare_known_target()
        self.ask('票号更正为F010。',new_value='F010')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))
        self.assertNotIn('invoice_no',self.agent.pending_intent['scope'])


    def test_ambiguous_selection_cannot_leave_new_or_old_invoice_active(self):
        self.ask('乙企业2026年9月，查F002和F006，办哪张还没选。',
                 company_id='C002',field='purpose')
        self.assertIsNone(self.agent.pending_intent)
        self.prepare_known_target()
        self.ask('F006和F010之间还没有确定，备注写什么也没定。', field='remark')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))
        self.assertNotIn('invoice_no',self.agent.pending_intent['scope'])
        self.assertEqual(self.agent.pending_intent['change'],{'field':['remark']})
