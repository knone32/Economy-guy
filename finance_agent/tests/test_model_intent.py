"""Explicit-source intent contracts; scripted models are not NLU evidence."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.invoice_batch import run_invoice_batch
from app.intent_contract import validate, apply_pending, proposal_edit, infer_proposal, IntentContractError
from app.provenance import ScopeProof
from app.provenance import validate_scope
from app.request_budget import BudgetExceeded


def call(name, args, *, content=None, ident='tool-current'):
    return {'role':'assistant', 'content': content or '', 'tool_calls':[
        {'id':ident, 'type':'function', 'function':{'name':name, 'arguments':json.dumps(args)}}]}


def final(**value):
    return {'role':'assistant', 'content':json.dumps({'kind':'information', 'text':'按本轮事实办理。', **value}, ensure_ascii=False)}


class ModelIntentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.book = Path(self.tmp.name) / 'fixture.sqlite3'
        import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', self.book)

    def rows(self):
        with closing(sqlite3.connect(self.book)) as db:
            return db.execute("SELECT purpose FROM invoices WHERE company_id='C002' AND invoice_no='F008'").fetchone()[0], db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0]

    def pending_agent(self, *, proposal_patch=None, source_text=None, complete=True):
        stage = 0
        agent = None
        def model(messages, tools):
            nonlocal stage
            stage += 1
            if stage == 1:
                first = call('get_invoice', {'company_id':'C002','invoice_no':'F001'}, ident='first')
                first['tool_calls'] += call('get_invoice', {'company_id':'C002','invoice_no':'F008'}, ident='second')['tool_calls']
                return first
            if stage == 2:
                return final(kind='clarification', text='请选择一张，等待确定目标。', missing_fields=['invoice_no'],
                    pending_change={'field':'purpose','new_value':'采购对账备查'},
                    pending={'action':'create','scope':{'company_id':['C002'],'invoice_no':['F001','F008'],
                        'year':[2026],'month':[9],'periods':[[2026,9]]}})
            if stage == 3:
                return call('get_invoice', {'company_id':'C002','invoice_no':'F008'})
            if stage == 4:
                read = next(json.loads(m['content']) for m in reversed(messages) if m['role']=='tool')
                proposal = {'selection_id':read['data']['selection_id'], 'field':'purpose',
                    'new_value':'设备领用复核','mode':'item','excluded_invoice_ids':[],
                    'pending_request_id':agent.pending_intent['request_id'], 'target_year':2026,'target_month':9}
                proposal.update(proposal_patch or {})
                return call('propose_invoice_changes', proposal)
            return final()
        agent = Agent('U001', self.book, model, mode='mock', trace_path=self.book.with_suffix('.jsonl'))
        agent.ask('乙企业2026年9月，查F001与F008备注；我想从两张中选一张，把用途换成“采购对账备查”，具体哪张稍后补，现在先别改。')
        self.assertIsNotNone(agent.pending_intent)
        self.assertEqual(agent.pending_intent['change']['new_value'], ['采购对账备查'])
        if not complete:
            return agent
        agent.ask(source_text or '选F008；用途不要沿用上一句那几个字，最后定为“设备领用复核”。请核对原值，按这个新值做草稿交给工作台确认。')
        return agent

    def test_literal_pending_amendment_reaches_preview_without_final_json(self):
        before = self.rows()
        agent = self.pending_agent()
        change = agent.last_response.get('invoice_change')
        self.assertIsNotNone(change)
        self.assertEqual((change['company_id'],change['invoice_nos'],change['field'],change['new_value']),
                         ('C002',('F008',),'purpose','设备领用复核'))
        self.assertIsNone(agent.pending_intent)
        seen = []
        status, _ = run_invoice_batch(agent, agent.last_user_request, change,
            approve_batch=lambda *_:False, approve_item=lambda preview:seen.append(preview) or False, checkpoint=lambda *_:None)
        self.assertTrue(seen)
        self.assertNotEqual(status, 'COMMITTED')
        self.assertEqual(self.rows(), before)

    def test_unmentioned_amended_value_is_rejected(self):
        agent = self.pending_agent(proposal_patch={'new_value':'模型自行补上的字'})
        self.assertIsNone(agent.last_response.get('invoice_change'))
        self.assertEqual(self.rows()[1], 0)

    def test_amendment_preserves_inherited_field_and_can_confirm_once(self):
        agent = self.pending_agent(source_text='选F008，最后就定为“设备领用复核”，请给草稿确认。')
        change = agent.last_response.get('invoice_change')
        self.assertIsNotNone(change)
        previews = []
        status, summary = run_invoice_batch(agent, agent.last_user_request, change,
            approve_batch=lambda *_:False, approve_item=lambda body:previews.append(body) or 'confirm',
            checkpoint=lambda *_:None)
        self.assertEqual(status, 'COMPLETED')
        self.assertIn('设备领用复核', previews[0])
        self.assertIn('会议资料邮寄', previews[0])
        self.assertEqual(self.rows(), ('设备领用复核', 1))
        self.assertTrue(agent.write_receipt['readback_verified'])
        replies = iter((call('get_invoice', {'company_id':'C002','invoice_no':'F008'}),final()))
        restarted = Agent('U001',self.book,lambda *_:next(replies),mode='mock',trace_path=self.book.with_suffix('.restart.jsonl'))
        answer = restarted.ask('乙企业2026年9月F008用途现值是什么？')
        self.assertIn('设备领用复核', answer)
        self.assertEqual(restarted.write_receipt['status'],'NOT_SUBMITTED')
        self.assertEqual(self.rows()[1], 1)

    def test_explicit_candidate_rejects_wrong_sources_and_selection(self):
        pending = {'actor':'U001','workbook':str(self.book),'request_id':'pending-safe','request':'原待补',
            'scope':{'company_id':['C002'],'year':[2026],'month':[9],'invoice_no':['F001','F008']},
            'change':{'field':['purpose'],'new_value':['原文字']}}
        request = '选F008；用途最后定为“设备领用复核”。'
        target = {'company_id':'C002','year':2026,'month':9,'invoice_no':'F008','field':'purpose','new_value':'设备领用复核'}
        sources = {k:{'kind':'pending'} for k in ('company_id','year','month')}
        sources.update(invoice_no={'kind':'current','text':'F008'},field={'kind':'current','text':'用途'},
                       new_value={'kind':'current','text':'设备领用复核'})
        raw = {'action':'amend','pending_request_id':'pending-safe','target':target,'sources':sources}
        from copy import deepcopy
        for slot, wrong in (('company_id','C001'),('invoice_no','F009'),('field','remark'),('new_value','无来源字样')):
            bad = deepcopy(raw); bad['target'][slot] = wrong
            with self.subTest(slot=slot), self.assertRaises(IntentContractError):
                validate(bad,actor='U001',book=self.book,request=request,turn_id='turn',pending=pending)
        bound = validate(raw,actor='U001',book=self.book,request=request,turn_id='turn',pending=pending)
        newer = apply_pending(bound,pending)
        self.assertEqual(newer['change']['new_value'], ['设备领用复核'])
        self.assertEqual(pending['change']['new_value'], ['原文字'])
        proposal = {'pending_request_id':'pending-safe','field':'purpose','new_value':'设备领用复核',
                    'mode':'item','excluded_invoice_ids':[]}
        for wrong_company, wrong_number, wrong_field, wrong_value in (
            ('C001','F008','purpose','设备领用复核'),('C002','F001','purpose','设备领用复核'),
            ('C002','F008','remark','设备领用复核'),('C002','F008','purpose','原文字')):
            selection = (((wrong_company,wrong_number),),{'company_id':wrong_company,'year':2026,'month':9},'get_invoice')
            p = {**proposal,'field':wrong_field,'new_value':wrong_value}
            with self.subTest(selection=selection,p=p), self.assertRaises(IntentContractError):
                proposal_edit(bound,p,selection,actor='U001',book=self.book,turn_id='turn',request=request)

    def test_cancel_sidecar_pairs_tools_and_cannot_continue_stale_pending(self):
        agent = self.pending_agent(complete=False)
        pending_id = agent.pending_intent['request_id']
        agent.model = lambda *_:call('get_invoice',{'company_id':'C002','invoice_no':'F008'},
            content=json.dumps({'intent':{'action':'cancel','pending_request_id':pending_id}}))
        answer = agent.ask('这件事停止，不继续办理。')
        self.assertIn('已取消',answer)
        self.assertIsNone(agent.pending_intent)
        self.assertEqual(agent.messages[-1]['role'],'tool')
        self.assertEqual(json.loads(agent.messages[-1]['content'])['status'],'CANCELLED')
        agent.model = lambda *_:call('propose_invoice_changes',{'selection_id':'old','field':'purpose',
            'new_value':'设备领用复核','mode':'item','excluded_invoice_ids':[],'pending_request_id':pending_id})
        agent.ask('还是按之前那项提交。')
        self.assertIsNone(agent.last_response.get('invoice_change'))
        self.assertEqual(self.rows()[1],0)

    def test_read_candidate_span_conflict_permission_and_key_are_guarded(self):
        base = {'action':'read','target':{'company_id':'C002','year':2026,'month':9,'invoice_no':'F008'},
            'sources':{'company_id':{'kind':'current','text':'乙这本账'},'year':{'kind':'current','text':'二六年'},
                       'month':{'kind':'current','text':'九月'},'invoice_no':{'kind':'current','text':'这张'}}}
        text = '二六年九月乙这本账，读一下这张。'
        with self.assertRaises(IntentContractError):
            validate(base,actor='U001',book=self.book,request=text,turn_id='t')
        raw = {**base,'target':{k:v for k,v in base['target'].items() if k!='invoice_no'},
               'sources':{k:v for k,v in base['sources'].items() if k!='invoice_no'}}
        with self.assertRaises(IntentContractError):
            validate(raw,actor='U002',book=self.book,request=text,turn_id='t')
        with self.assertRaises(IntentContractError):
            validate(raw,actor='U001',book=self.book,request='甲企业2026年9月。'+text,turn_id='t')
        anchor = ScopeProof('U001',{'company_id':['C001']},{'company_id':'trusted_reference'})
        with self.assertRaises(IntentContractError):
            validate(raw,actor='U001',book=self.book,request=text,turn_id='t',anchor=anchor)

    def test_sidecar_applies_pending_amendment_before_fresh_read_dispatch(self):
        agent = self.pending_agent(complete=False)
        pending_id = agent.pending_intent['request_id']
        target = {'company_id':'C002','year':2026,'month':9,'invoice_no':'F008','field':'purpose','new_value':'设备领用复核'}
        sources = {k:{'kind':'pending'} for k in ('company_id','year','month','field')}
        sources.update(invoice_no={'kind':'current','text':'F008'},new_value={'kind':'current','text':'设备领用复核'})
        intent = {'action':'amend','pending_request_id':pending_id,'target':target,'sources':sources}
        phase = 0
        def model(messages, tools):
            nonlocal phase
            phase += 1
            if phase == 1:
                return call('get_invoice', {'company_id':'C002','invoice_no':'F008'},content=json.dumps({'intent':intent},ensure_ascii=False))
            self.assertEqual(agent.pending_intent['scope']['invoice_no'],['F008'])
            self.assertEqual(agent.pending_intent['change']['new_value'],['设备领用复核'])
            result = next(json.loads(m['content']) for m in reversed(messages) if m['role']=='tool')
            return call('propose_invoice_changes',{'selection_id':result['data']['selection_id'],
                'field':'purpose','new_value':'设备领用复核','mode':'item','excluded_invoice_ids':[],
                'pending_request_id':pending_id})
        agent.model = model
        agent.ask('选F008，最后定为“设备领用复核”，请先核当前值再给草稿。')
        self.assertIsNotNone(agent.last_response.get('invoice_change'))
        events = [json.loads(line) for line in self.book.with_suffix('.jsonl').read_text(encoding='utf-8').splitlines()]
        applied = next(i for i,e in enumerate(events) if e['event']=='intent.applied')
        read = next(i for i,e in enumerate(events[applied+1:],applied+1)
                    if e['event']=='tool.requested' and e['data']['function']['name']=='get_invoice')
        self.assertLess(applied,read)
        self.assertEqual(self.rows()[1],0)

    def test_read_candidate_can_supply_sql_snapshot_without_becoming_write_source(self):
        intent = {'action':'read','target':{'company_id':'C002','year':2026,'month':9},
            'sources':{'company_id':{'kind':'current','text':'乙这本账'},
                       'year':{'kind':'current','text':'二六年'},'month':{'kind':'current','text':'九月'}}}
        replies = iter((call('query_business_sql', {'sql':'SELECT COUNT(*) AS cnt FROM invoices'},
            content=json.dumps({'intent':intent},ensure_ascii=False)),final()))
        agent = Agent('U001',self.book,lambda *_:next(replies),mode='mock',trace_path=self.book.with_suffix('.jsonl'))
        agent.ask('二六年九月乙这本账，发票几张？')
        self.assertTrue(any(n=='query_business_sql' and r['status']=='SUCCESS' and [list(row) for row in r['data']['rows']]==[[10]]
                            for n,r in agent.last_response['tool_results']))
        proof = ScopeProof('U001',{'company_id':['C002'],'invoice_no':['F008']},
                           {'company_id':'model_read_candidate','invoice_no':'model_read_candidate'})
        denied = validate_scope(proof,'U001','prepare_invoice_update',{'company_id':'C002','invoice_no':'F008'})
        self.assertEqual(denied['status'],'AMBIGUOUS')
        self.assertNotIn('model_read_candidate',agent.context.sources.values())

    def test_relative_period_uses_actual_anchor_arithmetic(self):
        anchor = ScopeProof('U001',{'company_id':['C002'],'year':[2026],'month':[9],'periods':[(2026,9)]},
                            {'company_id':'trusted_reference','year':'trusted_reference','month':'trusted_reference','periods':'trusted_reference'})
        intent = {'action':'read','target':{'company_id':'C002','year':2026,'month':8},
            'sources':{'company_id':{'kind':'anchor'},
                'year':{'kind':'period_offset','text':'往前一个月','months':-1},
                'month':{'kind':'period_offset','text':'往前一个月','months':-1}}}
        bound = validate(intent,actor='U001',book=self.book,request='按刚才的账期往前一个月。',turn_id='t',anchor=anchor)
        self.assertEqual(bound.target['month'],8)
        intent['target']['month']=7
        with self.assertRaises(IntentContractError):
            validate(intent,actor='U001',book=self.book,request='按刚才的账期往前一个月。',turn_id='t',anchor=anchor)

    def test_budget_refusal_preserves_pending_and_real_reads_without_network_claim(self):
        agent = self.pending_agent(complete=False)
        original = json.loads(json.dumps(agent.pending_intent))
        n = 0
        def model(messages, tools):
            nonlocal n
            n += 1
            if n == 1:
                return call('get_invoice',{'company_id':'C002','invoice_no':'F008'})
            raise BudgetExceeded('token_reservation', remaining_tokens=45005,reserved_tokens=52734,physical_requests=21)
        agent.model=model
        answer=agent.ask('先只核对乙企业2026年9月F008的当前用途。')
        self.assertIn('预算不足',answer)
        self.assertNotIn('API请求失败',answer)
        self.assertEqual(agent.last_response['execution']['stop_reason'],'REQUEST_BUDGET_EXCEEDED')
        self.assertTrue(any(n=='get_invoice' and r['status']=='SUCCESS' for n,r in agent.last_response['tool_results']))
        self.assertEqual(json.loads(json.dumps(agent.pending_intent)),original)
        self.assertEqual(self.rows()[1],0)

    def test_budget_close_uses_one_existing_slot_without_tools_and_keeps_notice(self):
        stage = 0
        agent = None
        def model(messages, tools):
            nonlocal stage
            stage += 1
            if stage == 1:
                return call('get_finance_summary',{'company_id':'C001','year':2026,'month':9})
            if stage == 2:
                raise BudgetExceeded('token_reservation',remaining_tokens=45005,reserved_tokens=52734)
            self.assertEqual(tools, [])
            return final(text='已经保存全部修改。', answer=[agent.trace_id+':r0.invoice_count'])
        agent=Agent('U001',self.book,model,mode='mock',trace_path=self.book.with_suffix('.jsonl'))
        answer=agent.ask('甲企业2026年9月发票几张？')
        self.assertEqual(stage,3)
        self.assertIn('发票张数 10 张',answer)
        self.assertIn('预算受限',answer)
        self.assertIn('未确认全部办理完成',answer)
        self.assertNotIn('已经保存全部修改',answer)
        self.assertEqual(agent.last_response['execution']['extensions'],0)
        self.assertEqual(agent.write_receipt['status'],'NOT_SUBMITTED')

    def test_budget_close_pairs_forbidden_calls_without_dispatch(self):
        stage=0
        def model(messages, tools):
            nonlocal stage
            stage+=1
            if stage==1:
                return call('get_invoice',{'company_id':'C001','invoice_no':'F004'})
            if stage==2:
                raise BudgetExceeded('token_reservation',remaining_tokens=45005,reserved_tokens=52734)
            return call('propose_invoice_changes',{'selection_id':'invented','field':'purpose',
                        'new_value':'不得执行','mode':'item','excluded_invoice_ids':[]},ident='budget-forbidden')
        agent=Agent('U001',self.book,model,mode='mock',trace_path=self.book.with_suffix('.jsonl'))
        answer=agent.ask('甲企业2026年9月F004用途是什么？')
        self.assertEqual(stage,3)
        self.assertEqual(agent.last_response['execution']['actual_tool_calls'],1)
        self.assertTrue(any(m.get('tool_call_id')=='budget-forbidden' and json.loads(m['content'])['status']=='DENIED'
                            for m in agent.messages if m['role']=='tool'))
        self.assertIn('预算受限',answer)
        self.assertEqual(self.rows()[1],0)

    def test_read_candidate_does_not_replace_actual_invoice_date_or_accept_bad_structure(self):
        request='乙企业2026年8月F008，查看当前用途。'
        target={'company_id':'C002','year':2026,'month':8,'invoice_no':'F008'}
        intent={'action':'read','target':target,'sources':{k:{'kind':'current','text':request} for k in target}}
        replies=iter((call('get_invoice',{'company_id':'C002','invoice_no':'F008'},
                            content=json.dumps({'intent':intent},ensure_ascii=False)),final()))
        agent=Agent('U001',self.book,lambda *_:next(replies),mode='mock',trace_path=self.book.with_suffix('.jsonl'))
        agent.ask(request)
        self.assertTrue(any(n=='get_invoice' and r['status']=='SCOPE_MISMATCH' for n,r in agent.last_response['tool_results']))
        from copy import deepcopy
        for mutate in ('action','source','year','actor'):
            bad=deepcopy(intent)
            if mutate=='action': bad['action']=[]
            elif mutate=='source': bad['sources']['company_id']['kind']=[]
            elif mutate=='year': bad['target']['year']=10**40
            else: bad['actor']='U001'
            with self.subTest(mutate=mutate), self.assertRaises(IntentContractError):
                validate(bad,actor='U001',book=self.book,request=request,turn_id='t')

    def test_optional_bridge_leaves_clear_and_batch_legacy_paths_unchanged(self):
        pending={'request_id':'p','scope':{},'change':{'new_value':['旧值']}}
        selection=((('C001','F004'),),{'company_id':'C001','year':2026,'month':9},'get_invoice')
        base={'pending_request_id':'p','field':'purpose','new_value':'','mode':'item','excluded_invoice_ids':[]}
        self.assertIsNone(infer_proposal(base,selection,pending=pending,actor='U001',book=self.book,
                                         request='显式清空要求',turn_id='t',anchor=None))
        self.assertIsNone(infer_proposal({**base,'new_value':'新值','mode':'batch'},selection,pending=pending,
                                         actor='U001',book=self.book,request='批量请求',turn_id='t',anchor=None))

    def test_current_span_read_candidate_can_normalize_without_new_wordlist(self):
        intent = {'action':'read','target':{'company_id':'C002','year':2026,'month':9},
            'sources':{'company_id':{'kind':'current','text':'乙这本账'},
                       'year':{'kind':'current','text':'二六年'},'month':{'kind':'current','text':'九月'}}}
        replies = iter((call('get_finance_summary', {'company_id':'C002','year':2026,'month':9},
                      content=json.dumps({'intent':intent}, ensure_ascii=False)), final()))
        agent = Agent('U001',self.book,lambda *_:next(replies),mode='mock',trace_path=self.book.with_suffix('.jsonl'))
        agent.ask('二六年九月乙这本账，把发票和银行收支各自汇总给我。')
        self.assertTrue(any(n=='get_finance_summary' and r['status']=='SUCCESS' for n,r in agent.last_response['tool_results']))
        self.assertEqual(agent.write_receipt['status'],'NOT_SUBMITTED')


if __name__ == '__main__': unittest.main()
