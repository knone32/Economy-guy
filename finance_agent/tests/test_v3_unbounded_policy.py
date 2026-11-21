"""Synthetic temporary ledgers only. No real AUTH/ledger/profile or HTTP."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import importlib.util
import hashlib
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tests import test_v3_shared_budget as old

budget=old.budget
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'finance_agent'))
GUARD=ROOT/'external/v3_live_guard_unbounded.py'
if not GUARD.is_file():GUARD=ROOT.parent/'evidence-root/v3_live_guard_unbounded.py'
spec=importlib.util.spec_from_file_location('new_guard',GUARD)
guard_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard_module)

class UnboundedPolicyTests(unittest.TestCase):
    def setUp(self):
        self.f=old.V3SharedBudgetTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
    def enable(self):
        authority={'authorized':True,'authorized_by':'user','instruction':'Synthetic explicit instruction removes cumulative request/token/cost limits; retain accounting and per-request safety.'}
        self.f.auth.update(cumulative_policy=budget.UNBOUNDED_POLICY,cumulative_policy_authorization=authority,
            max_c_requests=None,max_c_tokens=None,incremental_cost_limit_micros=None)
        self.f.data.update(cumulative_policy=budget.UNBOUNDED_POLICY,cumulative_policy_authorization=deepcopy(authority),
            limits={'requests':None,'tokens':None,'cost_micros':None})
        self.f.save()
    def test_inspect_is_readonly_and_append_preserves_same_ledger_prefix_and_identity(self):
        self.enable();before=self.f.path.read_bytes();info=self.f.guard().inspect()
        self.assertEqual(before,self.f.path.read_bytes());self.assertEqual(info['limits'],dict.fromkeys(('requests','tokens','cost_micros')))
        self.assertEqual(info['cumulative_policy'],budget.UNBOUNDED_POLICY)
        self.f.guard().execute(self.f.body(),'synthetic',self.f.send,lambda e:None)
        data=budget.load(self.f.path);self.assertEqual(data['entries'][:13],self.f.entries)
        self.assertEqual(data['budget_id'],self.f.auth['budget_id']);self.assertEqual(data['totals']['requests'],14)
        self.assertEqual(info['historical_cumulative_compliance'],'UNKNOWN_NOT_ZERO')
    def test_unbounded_can_account_beyond_all_three_old_global_caps(self):
        entries=deepcopy(self.f.entries)
        while len(entries)<64:
            entry=deepcopy(entries[0]);entry['id']='large-'+str(len(entries));entries.append(entry)
        entries[-1]['usage']={'prompt_tokens':1200000,'completion_tokens':0,'total_tokens':1200000}
        entries[-1]['tokens']=1200000;entries[-1]['cost_micros']=2400000
        totals={'requests':64,'tokens':sum(e['tokens'] for e in entries),'cost_micros':sum(e['cost_micros'] for e in entries)}
        self.f.data.update(entries=entries,totals=totals)
        self.f.auth['preserved_prefix']={'entry_count':64,'entries_sha256':budget.prefix_digest(entries),'totals':totals}
        self.enable();self.f.guard().execute(self.f.body(),'beyond',self.f.send,lambda e:None)
        data=budget.load(self.f.path);self.assertEqual(data['entries'][:64],entries)
        self.assertEqual(data['totals']['requests'],65);self.assertGreater(data['totals']['tokens'],700000)
        self.assertGreater(data['totals']['cost_micros'],2200000)
    def test_null_without_policy_or_without_user_authority_is_rejected(self):
        self.f.auth['max_c_requests']=None;self.f.save()
        with self.assertRaises(budget.BudgetStop):self.f.guard()
        self.enable();self.f.auth['cumulative_policy_authorization']['authorized_by']='executor';self.f.save()
        with self.assertRaisesRegex(budget.BudgetStop,'unbounded.*authorization'):self.f.guard()
    def test_unbounded_requires_all_explicit_null_auth_fields(self):
        for key in budget.CUMULATIVE_FIELDS:
            self.enable();self.f.auth[key]=10**20;self.f.save()
            with self.assertRaises(budget.BudgetStop):self.f.guard()
            self.enable();del self.f.auth[key];self.f.save()
            with self.assertRaises(budget.BudgetStop):self.f.guard()
    def test_migration_requires_matching_policy_authority_and_all_explicit_ledger_nulls(self):
        for mode in ('policy','authority','missing','finite'):
            self.enable()
            if mode=='policy':self.f.data.pop('cumulative_policy')
            elif mode=='authority':self.f.data['cumulative_policy_authorization']['instruction']='different'
            elif mode=='missing':del self.f.data['limits']['tokens']
            else:self.f.data['limits']['cost_micros']=10**20
            self.f.save()
            with self.assertRaises(budget.BudgetStop):self.f.guard().inspect()
    def test_old_bounded_authorization_cannot_open_unbounded_ledger(self):
        oldauth=deepcopy(self.f.auth);self.enable();self.f.auth=oldauth;self.f.save()
        with self.assertRaisesRegex(budget.BudgetStop,'policy_mismatch'):self.f.guard().inspect()
    def test_output_8192_limit_and_wire_consistency_remain(self):
        self.enable()
        for bound in (8193,True):
            with self.assertRaises(budget.BudgetStop):self.f.guard().execute(self.f.body(bound),'bad',self.f.send,lambda e:None,max_output_tokens=bound)
        self.assertFalse(self.f.sent)
        self.f.auth['max_output_tokens']=8193;self.f.save()
        with self.assertRaises(budget.BudgetStop):self.f.guard()
    def test_unknown_usage_still_locks_and_never_resends(self):
        self.enable();calls=[]
        def send(body):calls.append(body);return 200,{'id':'bad','usage':{}},'bad'
        with self.assertRaises(budget.BudgetStop):self.f.guard().execute(self.f.body(),'bad',send,lambda e:None)
        with self.assertRaises(budget.BudgetStop):self.f.guard().execute(self.f.body(),'again',send,lambda e:None)
        self.assertEqual(len(calls),1);self.assertTrue(budget.load(self.f.path)['unknown_usage'])
    def test_prefix_and_unknown_historical_evidence_are_not_relaxed(self):
        self.enable();self.f.data['entries'][0]['case']='tampered';self.f.save()
        with self.assertRaisesRegex(budget.BudgetStop,'prefix_changed'):self.f.guard().inspect()
        self.enable();self.f.index.write_text('changed',encoding='utf-8')
        with self.assertRaisesRegex(budget.BudgetStop,'prior_unknown'):self.f.guard()
    def test_same_atomic_lock_serializes_unbounded_appends(self):
        self.enable()
        def execute(i):return self.f.guard().execute(self.f.body(),'thread-'+str(i),self.f.send,lambda e:None)[0]
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(list(pool.map(execute,range(2))),[200,200])
        data=budget.load(self.f.path);self.assertEqual(data['totals']['requests'],15);self.assertEqual(data['entries'][:13],self.f.entries)
    def test_known_usage_local_log_failure_remains_durable(self):
        self.enable()
        def failed(entry):raise OSError('synthetic failure')
        with self.assertRaises(budget.LocalLogError):self.f.guard().execute(self.f.body(),'local',self.f.send,failed)
        data=budget.load(self.f.path);self.assertFalse(data['unknown_usage']);self.assertEqual(data['entries'][-1]['status'],'complete')
        self.assertEqual(data['entries'][-1]['local_log_status'],'failed');self.assertEqual(len(self.f.sent),1)

class UnboundedGuardTests(unittest.TestCase):
    setUp=UnboundedPolicyTests.setUp
    enable=UnboundedPolicyTests.enable
    def make_guard(self,unbounded=True,cap=None):
        if unbounded:self.enable()
        else:
            for value in (self.f.auth,self.f.data):
                value.pop('cumulative_policy',None);value.pop('cumulative_policy_authorization',None)
            self.f.auth.update(max_c_requests=64,max_c_tokens=700000,incremental_cost_limit_micros=2200000)
            self.f.data['limits']={'requests':64,'tokens':700000,'cost_micros':2200000}
            self.f.save()
        checkout=self.f.root/'checkout';(checkout/'tools').mkdir(parents=True,exist_ok=True)
        (checkout/'tools/v3_shared_budget.py').write_bytes((ROOT/'tools/v3_shared_budget.py').read_bytes())
        profile=self.f.root/'synthetic-profile.json';profile.write_text('{}',encoding='utf-8')
        self.f.auth.update(source_root=str(checkout),frozen_sha='synthetic-sha',profile_config=str(profile),
            profile_config_sha256=hashlib.sha256(profile.read_bytes()).hexdigest(),per_scene_caps={'PUBLIC':cap})
        self.f.save()
        return guard_module.GuardedHTTP(self.f.auth_path,case_id='PUBLIC',evidence_dir=self.f.root/'evidence')
    def git(self,args,**kwargs):return SimpleNamespace(stdout='synthetic-sha\n' if args[-2:]==['rev-parse','HEAD'] else '')
    def test_new_guard_null_scene_requires_new_policy_and_explicit_case(self):
        g=self.make_guard();self.assertIsNone(g.scene_limit())
        del g.auth['per_scene_caps']['PUBLIC']
        with self.assertRaises(RuntimeError):g.scene_limit()
        g=self.make_guard(False,None)
        with self.assertRaises(RuntimeError):g.scene_limit()
    def test_fake_http_retains_official_model_receipt_and_zero_retry_checks(self):
        import httpx,openai
        g=self.make_guard();sent=[]
        def fake(transport,request):
            sent.append(json.loads(request.content));return httpx.Response(200,json={'id':'synthetic-receipt','model':'deepseek-flash',
                'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}},request=request)
        with patch.object(guard_module.subprocess,'run',side_effect=self.git),patch.object(httpx.HTTPTransport,'handle_request',fake):
            with g:
                with httpx.Client(transport=httpx.HTTPTransport(retries=0),trust_env=False) as client:
                    self.assertEqual(client.post('https://api.deepseek.com/chat/completions',json={'model':'deepseek-flash','messages':[]}).status_code,200)
                    with self.assertRaises(RuntimeError):client.post('https://example.invalid/chat/completions',json={'model':'deepseek-flash'})
                    with self.assertRaises(RuntimeError):client.post('https://api.deepseek.com/chat/completions',json={'model':'other'})
                with self.assertRaises(RuntimeError):httpx.HTTPTransport(retries=1)
                with self.assertRaises(RuntimeError):openai.OpenAI(api_key='synthetic',max_retries=1)
        self.assertEqual(len(sent),1);self.assertEqual(sent[0]['max_tokens'],8192);self.assertEqual(sent[0]['temperature'],0)
        self.assertFalse(sent[0]['stream']);self.assertEqual(g.stats()['totals']['requests'],14)
    def test_source_and_profile_guard_still_fail_before_http(self):
        g=self.make_guard()
        with patch.object(guard_module.subprocess,'run',return_value=SimpleNamespace(stdout='wrong')):
            with self.assertRaisesRegex(RuntimeError,'source'):g.verify()
        Path(g.auth['profile_config']).write_text('changed',encoding='utf-8')
        with patch.object(guard_module.subprocess,'run',side_effect=self.git):
            with self.assertRaisesRegex(RuntimeError,'profile'):g.verify()

