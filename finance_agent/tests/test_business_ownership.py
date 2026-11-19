import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.invoice_batch import run_invoice_batch
from app.tool_registry import validate_arguments
from tests.test_tui_p0 import FIXTURE
from tests.test_model_intent import call
from tests.test_sql_invoice_selection import snapshot

class BusinessOwnershipTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.book=Path(temp.name)/'fixture.sqlite3'; import_workspace(FIXTURE,self.book)
    def agent(self,user='U001'):
        return Agent(user,self.book,lambda *_:call('change_invoice',{}),mode='mock',trace_path=self.book.with_suffix('.jsonl'))
    def start(self,agent):
        agent.model=lambda *_:call('change_invoice',{'company_id':'C001','year':2026,'month':9,'field':'purpose','new_value':'仓储日常维护'})
        agent.ask('帮我办理一笔发票用途调整：甲企业2026年9月，新用途为“仓储日常维护”。是哪张发票我随后告诉你，现在还不能确定票号。')
        self.assertEqual(agent.last_response['execution']['stop_reason'],'WAITING_USER')
        self.assertNotIn('invoice_no',agent.pending_intent['scope'])
    def test_same_business_contract_owns_state_fresh_read_and_real_preview(self):
        agent=self.agent(); before=snapshot(self.book); self.start(agent); seen=[]
        def model(messages,tools):
            names={t['function']['name'] for t in tools}
            self.assertIn('change_invoice',names); self.assertNotIn('propose_invoice_changes',names)
            ctx=json.loads(next(m['content'] for m in reversed(messages) if m.get('name')=='context_data' and 'invoice_change' in m['content']))
            self.assertNotIn('request_id',ctx['invoice_change'])
            return call('change_invoice',{'company_id':'C001','invoice_no':'F003','year':2026,'month':9,'field':'purpose','new_value':'仓储日常维护'})
        agent.model=model
        agent.ask('票号补上，是F003，企业、月份和新用途都照上一条。这次请出正式修改预览，把原用途与拟写入用途摆出来，先给我审阅。')
        planned=agent.last_response.get('invoice_change'); self.assertIsNotNone(planned)
        self.assertEqual((planned['company_id'],planned['invoice_nos'],planned['field'],planned['new_value']),('C001',('F003',),'purpose','仓储日常维护'))
        self.assertTrue(any(n=='get_invoice' and r['evidence']['source']=='current_sqlite' for n,r in agent.last_response['tool_results']))
        def reject(body):seen.append(body); return False
        run_invoice_batch(agent,planned['source_request'],planned,approve_batch=reject,approve_item=reject,checkpoint=lambda *_:self.fail('no confirmed writes'))
        self.assertEqual(len(seen),1); self.assertEqual(snapshot(self.book),before)
    def test_unknown_parameters_and_model_authority_are_rejected(self):
        for patch in ({'selection_id':'fake'},{'confirmed':True},{'actor':'U001'},{'pending_request_id':'fake'},{'action':'propose'}):
            agent=self.agent(); agent.model=lambda *_,p=patch:call('change_invoice',p)
            agent.ask('甲企业2026年9月，想改用途，新用途为“核对”，票号稍后定。')
            self.assertIsNone(agent.pending_intent)
            self.assertTrue(any(r['status']=='INVALID_ARGUMENTS' for _,r in agent.last_response['tool_results']))
    def test_conflicting_company_or_actual_period_cannot_preview(self):
        for patch in ({'company_id':'C002','invoice_no':'F003'},{'invoice_no':'F012'}):
            agent=self.agent(); self.start(agent); agent.model=lambda *_,p=patch:call('change_invoice',p)
            agent.ask('票号为F003。' if patch.get('invoice_no')=='F003' else '票号为F012。')
            self.assertIsNone(agent.last_response.get('invoice_change'))
            self.assertNotIn('invoice_no',agent.pending_intent['scope'])
    def test_query_mentions_cannot_select_ambiguous_target_or_wrong_field(self):
        text='乙企业2026年9月，查F002和F006用途；想从中选一张把备注填“附件回收待核”，还没选票，先别变更。'
        for patch in ({'company_id':'C002','field':'remark','new_value':'附件回收待核','invoice_no':'F002'}, {'company_id':'C002','field':'purpose','new_value':'附件回收待核'}):
            agent=self.agent(); agent.model=lambda *_,p=patch:call('change_invoice',p)
            agent.ask(text); self.assertIsNone(agent.pending_intent)
            self.assertIsNone(agent.last_response.get('invoice_change'))
    def test_permissions_and_cancel_do_not_grant_write_authority(self):
        agent=self.agent('U002'); agent.model=lambda *_:call('change_invoice',{'company_id':'C001','field':'purpose','new_value':'核对'})
        agent.ask('甲企业的用途想填“核对”，票号稍后定。'); self.assertIsNone(agent.pending_intent)
        agent=self.agent(); self.start(agent); agent.cancel_update(); self.assertIsNone(agent.pending_intent)
    def test_current_correction_conflict_cannot_reuse_old_value(self):
        agent=self.agent(); self.start(agent)
        agent.model=lambda *_:call('change_invoice',{'invoice_no':'F003','field':'purpose','new_value':'仓储日常维护'})
        agent.ask('票号F003，新用途另定为“设备维护”，给我看预览。')
        self.assertIsNone(agent.last_response.get('invoice_change'))
        self.assertEqual(agent.pending_intent['change']['new_value'], ['仓储日常维护'])
    def test_omitted_known_slots_use_the_same_verified_state(self):
        agent=self.agent(); self.start(agent)
        agent.model=lambda *_:call('change_invoice',{'invoice_no':'F003'})
        agent.ask('票号补为F003，给我看正式预览。')
        self.assertIsNotNone(agent.last_response.get('invoice_change'))
    def test_advanced_selection_contract_remains_strict_and_separate(self):
        args={'selection_id':'current','field':'purpose','new_value':'x','mode':'item','excluded_invoice_ids':[]}
        self.assertEqual(validate_arguments('propose_invoice_changes',json.dumps(args)),args)
        for key in args:
            with self.assertRaises(ValueError):
                validate_arguments('propose_invoice_changes',json.dumps({k:v for k,v in args.items() if k!=key}))
        with self.assertRaises(ValueError):
            validate_arguments('propose_invoice_changes','{"action":"request"}')

if __name__=='__main__':unittest.main()
