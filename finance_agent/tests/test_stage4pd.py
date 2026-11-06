"""4P-D：可信配置/冻结凭据/协议切换与原生观测，全部Mock和临时文件/SQLite。"""
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from contextlib import redirect_stdout
from app.agent import Agent,scripted_model
from tests.helpers import DatabaseTestCaseMixin


def profile(name='shared',scope='global',owner=None,account='team',model='deepseek-flash',env='TEST_DS_KEY',provider='deepseek',base='https://api.deepseek.com'):
    return dict(profile_name=name,scope=scope,owner_user_id=owner,provider=provider,service_account_ref=account,
                model=model,base_url=base,api_key_env=env,protocol='auto')


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.template=Path(self.temp.name)/'profiles.toml';self.template.write_text('profiles = []\n',encoding='utf-8')
        self.local=Path(self.temp.name)/'local.json'

    def add(self,data,**kwargs):
        from app.model_config import add_profile
        return add_profile(data,template=self.template,local=self.local,**kwargs)

    def resolve(self,user='U001',name=None,**kwargs):
        from app.model_config import resolve_connection
        return resolve_connection(user,name,template=self.template,local=self.local,**kwargs)

    def test_global_creation_requires_independent_manager(self):
        from app.model_config import ProfileError,visible_profiles
        with self.assertRaises(ProfileError): self.add(profile(),user_id='U001')
        self.assertFalse(self.local.exists())
        self.add(profile(),simulate_manager=True)
        self.assertEqual([p['profile_name'] for p in visible_profiles('U002',self.template,self.local)],['shared'])

    def test_user_visibility_and_selection_never_falls_back(self):
        from app.model_config import ProfileError,visible_profiles
        self.add(profile('mine','user','U001'),user_id='U001')
        self.add(profile('other','user','U002',env='OTHER_SECRET_ENV'),user_id='U002')
        self.assertEqual([p['profile_name'] for p in visible_profiles('U001',self.template,self.local)],['mine'])
        with patch.dict(os.environ,{'TEST_DS_KEY':'private-demo-key'}):
            self.assertEqual(self.resolve(name='mine').profile.owner_user_id,'U001')
            with self.assertRaises(ProfileError): self.resolve(name='other')
        with self.assertRaises(ProfileError): self.add(profile('forged','user','U002'),user_id='U001')

    def test_duplicate_names_and_conflicting_sources_rejected(self):
        from app.model_config import ProfileError,visible_profiles
        self.add(profile(),simulate_manager=True)
        before=self.local.read_bytes()
        with self.assertRaises(ProfileError): self.add(profile('shared','user','U001'),user_id='U001')
        self.assertEqual(self.local.read_bytes(),before)
        fields={k:v for k,v in profile().items() if v is not None}
        self.template.write_text('[[profiles]]\n'+'\n'.join(k+' = '+json.dumps(v) for k,v in fields.items()),encoding='utf-8')
        with self.assertRaises(ProfileError): visible_profiles('U001',self.template,self.local)

    def test_atomic_failure_and_malformed_config_preserve_old_file(self):
        from app.model_config import ProfileError
        self.add(profile(),simulate_manager=True);before=self.local.read_bytes()
        with patch('app.model_config.os.replace',side_effect=OSError('disk')):
            with self.assertRaises(ProfileError): self.add(profile('second'),simulate_manager=True)
        self.assertEqual(self.local.read_bytes(),before)
        self.local.write_text('{broken',encoding='utf-8')
        with self.assertRaises(ProfileError): self.add(profile('new'),simulate_manager=True)
        self.assertEqual(self.local.read_text(),'{broken')

    def test_keys_are_references_only_and_never_stored(self):
        from app.model_config import ProfileError
        with patch.dict(os.environ,{'TEST_DS_KEY':'SENSITIVE_ACTUAL_VALUE'}):
            self.add(profile(),simulate_manager=True)
            conn=self.resolve(name='shared')
            self.assertEqual(conn.api_key,'SENSITIVE_ACTUAL_VALUE')
            self.assertNotIn('SENSITIVE_ACTUAL_VALUE',repr(conn)+self.local.read_text()+json.dumps(conn.metadata()))
        with self.assertRaises(ProfileError): self.add({**profile('bad'),'api_key':'plaintext'},simulate_manager=True)

    def test_missing_key_does_not_fallback_but_mock_needs_no_key(self):
        from app.model_config import ProfileError
        self.add(profile(),simulate_manager=True)
        with patch.dict(os.environ,{'OPENAI_API_KEY':'legacy-value','OPENAI_BASE_URL':'https://api.deepseek.com','OPENAI_MODEL':'deepseek-flash'},clear=True):
            with self.assertRaises(ProfileError): self.resolve(name='shared')
            self.assertEqual(self.resolve(name='shared',require_key=False).api_key,'')

    def test_selection_precedence(self):
        for name in ('cli','env','default'):
            self.add(profile(name),simulate_manager=True)
        self.template.write_text('profiles=[]\n[settings]\ndefault_profile="default"\n',encoding='utf-8')
        with patch.dict(os.environ,{'TEST_DS_KEY':'demo','FINANCE_MODEL_PROFILE':'env'}):
            self.assertEqual(self.resolve(name='cli').profile.profile_name,'cli')
            self.assertEqual(self.resolve().profile.profile_name,'env')
            with patch.dict(os.environ,{'FINANCE_MODEL_PROFILE':''}):
                self.assertEqual(self.resolve().profile.profile_name,'default')

    def test_legacy_complete_groups_and_no_mixed_fields(self):
        from app.model_config import ProfileError
        for values in ({'OPENAI_API_KEY':'a','OPENAI_BASE_URL':'https://api.deepseek.com','OPENAI_MODEL':'deepseek-flash'},
                       {'KEY':'b','BASE_URL':'https://api.deepseek.com','MODEL':'deepseek-flash'}):
            with patch.dict(os.environ,values,clear=True):
                self.assertIn(self.resolve().api_key,('a','b'))
        with patch.dict(os.environ,{'OPENAI_API_KEY':'a','BASE_URL':'https://api.deepseek.com','MODEL':'deepseek-flash'},clear=True):
            with self.assertRaises(ProfileError): self.resolve()

    def test_unsafe_urls_and_unsupported_protocol_rejected(self):
        from app.model_config import ProfileError
        for url in ('http://api.deepseek.com','https://u:password@api.deepseek.com','https://127.0.0.1/v1',
                    'https://localhost/v1','https://api.deepseek.com?api_key=secret','file:///tmp/key'):
            with self.subTest(url=url),self.assertRaises(ProfileError):
                self.add(profile(base=url),simulate_manager=True)
        with self.assertRaises(ProfileError): self.add({**profile(),'protocol':'unknown'},simulate_manager=True)

    def test_cli_profile_add_list_check_without_network(self):
        import main,sys
        common=['main.py','--profiles-file',str(self.template),'--profiles-local',str(self.local)]
        commands=[['profiles','add','--scope','user','--user','U001','--name','mine','--provider','deepseek',
                   '--service-account-ref','personal','--model','deepseek-flash','--base-url','https://api.deepseek.com','--api-key-env','TEST_DS_KEY'],
                  ['profiles','list','--user','U001'],['profiles','check','--profile','mine','--user','U001']]
        with patch.dict(os.environ,{'TEST_DS_KEY':'actual-sensitive'}),patch('openai.OpenAI') as sdk:
            for args in commands:
                out=io.StringIO()
                with patch.object(sys,'argv',common+args),redirect_stdout(out): main.main()
                self.assertNotIn('actual-sensitive',out.getvalue())
            sdk.assert_not_called()

    def test_existing_edit_lock_and_unknown_fields_fail_closed(self):
        from app.model_config import ProfileError
        lock=self.local.with_name(self.local.name+'.lock');lock.write_text('occupied')
        with self.assertRaises(ProfileError): self.add(profile(),simulate_manager=True)
        self.assertFalse(self.local.exists());self.assertEqual(lock.read_text(),'occupied')
        lock.unlink()
        self.local.write_text(json.dumps({'profiles':[],'api_key':'not-a-reference'}))
        with self.assertRaises(ProfileError): self.resolve(name='missing')

    def test_explicit_missing_profile_never_uses_valid_default_or_legacy(self):
        from app.model_config import ProfileError
        self.add(profile(),simulate_manager=True)
        with patch.dict(os.environ,{'TEST_DS_KEY':'test','OPENAI_API_KEY':'other','OPENAI_BASE_URL':'https://api.deepseek.com','OPENAI_MODEL':'deepseek-flash'}):
            with self.assertRaises(ProfileError): self.resolve(name='not-exists')


class ReliabilityTests(DatabaseTestCaseMixin,unittest.TestCase):
    def setUp(self):
        super().setUp()
        from app.stage2_schema import migrate
        migrate(self.db_path)

    def prepared(self):
        args={'company_id':'C001','invoice_no':'F002','field':'purpose','new_value':'整理资料'}
        reply={'role':'assistant','tool_calls':[{'id':'p','type':'function','function':{'name':'prepare_invoice_update','arguments':json.dumps(args)}}]}
        agent=Agent('U001',self.db_path,scripted_model([reply]),mode='mock')
        agent.ask('C001 F002用途改为整理资料',allow_prepare=True)
        return agent,next(iter(agent.update_session.drafts.values()))

    def test_post_commit_missing_or_bad_date_never_hides_success(self):
        from app.updates import commit_invoice_update
        for bad in (None,'2026-99-01','not-a-date'):
            with self.subTest(date=bad):
                agent,draft=self.prepared()
                def commit(*args):
                    outcome=commit_invoice_update(*args)
                    outcome['data']['current_invoice']['invoice_date']=bad
                    return outcome
                with patch('app.agent.commit_invoice_update',side_effect=commit):
                    receipt=agent.commit_update(draft.request_id,draft.fingerprint())
                self.assertIn(receipt['status'],{'COMMITTED','NO_CHANGE'})
                self.assertTrue(receipt['readback_verified'])
                self.assertEqual(receipt['task_progress']['status'],'ERROR')
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM invoice_audit WHERE status='COMMITTED'").fetchone()[0],1)

    def test_auxiliary_exception_never_recommits(self):
        agent,draft=self.prepared()
        with patch('app.write_coordination.task_progress',side_effect=RuntimeError('aux')):
            receipt=agent.commit_update(draft.request_id,draft.fingerprint())
        self.assertEqual(receipt['status'],'COMMITTED')
        self.assertEqual(receipt['task_progress']['status'],'ERROR')
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM invoice_audit').fetchone()[0],1)

    def test_sqlite_progress_failure_and_invalid_result_do_not_undo_commit(self):
        for failure in (sqlite3.OperationalError('disk'),None):
            with self.subTest(failure=type(failure).__name__):
                agent,draft=self.prepared()
                kwargs={'side_effect':failure} if failure is not None else {'return_value':None}
                with patch('app.write_coordination.task_progress',**kwargs):
                    receipt=agent.commit_update(draft.request_id,draft.fingerprint())
                self.assertIn(receipt['status'],{'COMMITTED','NO_CHANGE'})
                self.assertEqual(receipt['task_progress']['status'],'ERROR')
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM invoice_audit WHERE status='COMMITTED'").fetchone()[0],1)


class SessionTests(DatabaseTestCaseMixin,unittest.TestCase):
    def setUp(self):
        super().setUp()
        from app.stage2_schema import migrate as stage2
        from app.stage3_schema import migrate as stage3
        from app.rules import import_rules,SEED_RULES
        stage2(self.db_path);stage3(self.db_path);import_rules(self.db_path,SEED_RULES,{'rule.manage'})

    def conn(self,name='one',account='team',model='deepseek-flash',key='key-one',scope='global',owner=None,provider='deepseek',base='https://api.deepseek.com'):
        from app.model_config import ModelConnection,validate_profile
        return ModelConnection(validate_profile(profile(name,scope,owner,account,model,provider=provider,base=base)),key)

    def seed_task(self):
        from app.tasks import manage_task
        from app.preferences import manage_preference
        from app.persistence import ManagementIntent
        task=manage_task(self.db_path,'U001','C001','create',note='下次核对用途',intent=ManagementIntent('U001','task','明确后续工作'))['data']['task']
        manage_preference(self.db_path,'U001','C001','create','format','简洁',ManagementIntent('U001','preference','明确简洁'))
        return task

    def test_same_account_model_switch_keeps_business_scope_not_protocol(self):
        task=self.seed_task()
        agent=Agent('U001',self.db_path,scripted_model([]),mode='mock',connection=self.conn())
        from app.thinking_protocol import ThinkingProtocol
        agent.protocol=ThinkingProtocol('https://api.deepseek.com','deepseek-flash',bind_environment=False)
        agent.model=scripted_model([{'role':'assistant','content':json.dumps({'kind':'information','text':'回答'}),'reasoning_content':'OLD_ACCOUNT_PRIVATE'}])
        agent.ask('C001 2026-09后续用途任务')
        switched=agent.switch_model(self.conn('two',model='deepseek-v4-pro'))
        self.assertEqual(switched.context.scope['company_id'],['C001'])
        context=json.dumps(switched.model_messages(),ensure_ascii=False)
        self.assertIn(task['task_id'],context);self.assertIn('简洁',context)
        self.assertNotIn('OLD_ACCOUNT_PRIVATE',context)
        self.assertFalse(switched.update_session.drafts)
        self.assertFalse(switched.trusted_events)
        self.assertIsNot(switched,agent)

    def test_cross_account_and_standard_switch_always_reset_private_history(self):
        self.seed_task()
        for conn in (self.conn('other',account='another',key='key-two'),
                     self.conn('standard',account='external',model='standard',provider='openai-compatible',base='https://example.test/v1')):
            agent=Agent('U001',self.db_path,scripted_model([]),mode='mock',connection=self.conn())
            agent.messages.append({'role':'assistant','content':'OLD_PROTOCOL_MARKER'})
            agent.context.scope={'company_id':['C001'],'year':[2026],'month':[9]}
            new=agent.switch_model(conn)
            self.assertNotIn('OLD_PROTOCOL_MARKER',json.dumps(new.model_messages()))
            self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],1)
            self.assertEqual(new.connection.api_key,conn.api_key)

    def test_credentials_are_frozen_and_rotation_requires_new_connection(self):
        from app.model_transport import ModelTransport
        conn=self.conn()
        with patch('openai.OpenAI') as sdk,patch.dict(os.environ,{'TEST_DS_KEY':'rotated-value'}):
            create=sdk.return_value.__enter__.return_value.chat.completions.create
            create.return_value.choices[0].message.model_dump.return_value={'role':'assistant','content':'{}','reasoning_content':''}
            ModelTransport(conn)([{'role':'user','content':'hi'}],[])
            self.assertEqual(sdk.call_args.kwargs['api_key'],'key-one')
            ModelTransport(self.conn(key='new-explicit-key'))([{'role':'user','content':'hi'}],[])
            self.assertEqual(sdk.call_args.kwargs['api_key'],'new-explicit-key')

    def test_user_identity_change_revokes_private_profile_and_context(self):
        agent=Agent('U001',self.db_path,scripted_model([]),mode='mock',connection=self.conn(scope='user',owner='U001'))
        agent.messages.append({'role':'assistant','content':'U001_SENSITIVE_HISTORY'})
        agent.user_id='U002'
        agent.ask('C001查询')
        self.assertEqual(agent.execution.stop_reason,'PROTOCOL_ERROR')
        self.assertNotIn('U001_SENSITIVE_HISTORY',json.dumps(agent.messages))

    def test_pending_draft_and_approval_cannot_cross_switch(self):
        from app.model_config import ProfileError
        args={'company_id':'C001','invoice_no':'F002','field':'purpose','new_value':'用途'}
        reply={'role':'assistant','tool_calls':[{'id':'p','type':'function','function':{'name':'prepare_invoice_update','arguments':json.dumps(args)}}]}
        agent=Agent('U001',self.db_path,scripted_model([reply]),mode='mock',connection=self.conn())
        agent.ask('C001 F002用途改为用途',allow_prepare=True)
        old=agent.update_session
        with self.assertRaises(ProfileError): agent.switch_model(self.conn('two'))
        agent.cancel_update()
        new=agent.switch_model(self.conn('two'))
        self.assertFalse(old.drafts);self.assertFalse(old.confirmations)
        self.assertFalse(new.update_session.allow_prepare)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM invoice_audit').fetchone()[0],0)

    def test_switch_rejected_during_active_tool_confirmation(self):
        from app.model_config import ProfileError
        args={'company_id':'C001','action':'create','key':'format','value':'简洁'}
        reply={'role':'assistant','tool_calls':[{'id':'p','type':'function','function':{'name':'manage_preference','arguments':json.dumps(args)}}]}
        seen=[]
        def confirm(p):
            with self.assertRaises(ProfileError): agent.switch_model(self.conn('two'))
            seen.append(p);return False
        agent=Agent('U001',self.db_path,scripted_model([reply]),mode='mock',connection=self.conn(),management_confirmation=confirm)
        agent.ask('记住C001简洁')
        self.assertEqual(len(seen),1)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM preferences').fetchone()[0],0)

    def test_unused_management_approval_is_revoked_before_switch(self):
        from app.model_config import ProfileError
        from app.persistence import ManagementCandidate,confirm_management
        from app.preferences import manage_preference
        args={'company_id':'C001','action':'create','key':'format','value':'简洁'}
        call={'role':'assistant','tool_calls':[{'id':'m','type':'function','function':{'name':'manage_preference','arguments':json.dumps(args)}}]}
        agent=Agent('U001',self.db_path,scripted_model([call]),mode='mock',connection=self.conn())
        request='保存C001简洁';agent.ask(request)
        outcome=json.loads(next(m['content'] for m in agent.messages if m['role']=='tool'))
        candidate=ManagementCandidate('U001','preference',request,'create',agent.management_proposals)
        approval=confirm_management(candidate,outcome['data'])
        with self.assertRaises(ProfileError): agent.switch_model(self.conn('next'))
        agent.cancel_update();agent.switch_model(self.conn('next'))
        self.assertEqual(manage_preference(self.db_path,'U001',**args,intent=approval)['status'],'DENIED')
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM preferences').fetchone()[0],0)

    def test_trace_failure_does_not_change_actual_sdk_result(self):
        from app.model_transport import ModelTransport
        with patch('openai.OpenAI') as sdk,patch('app.model_transport.warn_trace_degraded'):
            sdk.return_value.__enter__.return_value.chat.completions.create.return_value.choices[0].message.model_dump.return_value={'role':'assistant','content':'ok'}
            transport=ModelTransport(self.conn(),lambda *_: (_ for _ in ()).throw(OSError('trace disk')))
            self.assertEqual(transport([{'role':'user','content':'hello'}],[])['content'],'ok')
            self.assertEqual(transport.counts(),{'attempts':1,'successes':1,'failures':0})

    def test_unconfigured_agent_supports_restart_inspection_but_never_adopts_later_key(self):
        with patch.dict(os.environ,{},clear=True):
            agent=Agent('U001',self.db_path)
        self.assertFalse(agent.update_session.drafts)
        with patch.dict(os.environ,{'OPENAI_API_KEY':'new-key','OPENAI_BASE_URL':'https://api.deepseek.com','OPENAI_MODEL':'deepseek-flash'}),patch('openai.OpenAI') as sdk:
            agent.ask('查询C001')
            self.assertEqual(agent.execution.stop_reason,'PROTOCOL_ERROR')
            sdk.assert_not_called()

    def test_cli_hot_switch_lists_visible_profiles_and_preserves_identity(self):
        import main,sys
        from app.model_config import add_profile
        template=self.db_path.parent/'profiles.toml';template.write_text('profiles=[]\n')
        local=self.db_path.parent/'local.json'
        add_profile(profile('one'),simulate_manager=True,template=template,local=local)
        add_profile(profile('two',model='deepseek-v4-pro'),simulate_manager=True,template=template,local=local)
        inputs=iter(['/provider list','/provider status','/provider use two','/provider status','exit'])
        output=io.StringIO()
        with patch('builtins.input',side_effect=lambda _:next(inputs)),redirect_stdout(output),patch.object(sys,'argv',
            ['main.py','--db',str(self.db_path),'--profiles-file',str(template),'--profiles-local',str(local),'chat','--mode','mock','--user','U001','--profile','one']):
            main.main()
        self.assertIn('模型协议会话已重建',output.getvalue())
        self.assertIn('deepseek-v4-pro',output.getvalue())
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM invoice_audit').fetchone()[0],0)


class TraceTests(unittest.TestCase):
    def test_no_schedule_uses_tool_progress_without_changing_progress_count(self):
        from app.scheduler import TurnExecution,BudgetPolicy
        events=[];execution=TurnExecution(BudgetPolicy(),lambda e,d:events.append((e,d)))
        execution.observe('get_invoice',{'company_id':'C001','invoice_no':'F001'},
                          {'status':'SUCCESS','ok':True,'data':{},'evidence':{'source':'current_sqlite'}})
        self.assertEqual(execution.progress,1)
        self.assertNotIn('schedule.progress',[e for e,_ in events])
        self.assertIn('tool.progress',[e for e,_ in events])
        self.assertEqual((execution.model_requests,execution.actual_tools),(0,0))

    def test_real_schedule_progress_and_stop_still_work(self):
        from app.scheduler import TurnExecution,BudgetPolicy
        events=[];e=TurnExecution(BudgetPolicy(),lambda name,data:events.append(name))
        e.install('核对',[{'step_id':'one','action':'get_invoice','arguments':{'company_id':'C001'},'depends_on':[]}],'核对后停止')
        e.observe('get_invoice',{'company_id':'C001'},{'status':'SUCCESS','ok':True,'data':{},'evidence':{}})
        self.assertIn('schedule.progress',events)
        self.assertEqual(e.stop_reason,'COMPLETED')

    def test_redaction_preserves_business_keys_and_usage(self):
        from app.trace import redact
        source={'preference_key':'reply_format','tool_call_id':'q','prompt_tokens':100,'completion_tokens':20,'total_tokens':120,
                'api_key':'SHOULD_HIDE','Authorization':'Bearer SECRET','nested':{'reasoning_content':'PRIVATE_REASON'}}
        cleaned=redact(source)
        self.assertEqual(cleaned['preference_key'],'reply_format')
        self.assertEqual(cleaned['prompt_tokens'],100)
        self.assertEqual(cleaned['total_tokens'],120)
        self.assertNotIn('SHOULD_HIDE',json.dumps(cleaned))
        self.assertNotIn('PRIVATE_REASON',json.dumps(cleaned))
        args={'company_id':'C001','action':'create','key':'reply_format','value':'简洁'}
        self.assertEqual(redact(args)['key'],'reply_format')

    def test_nested_json_headers_urls_and_mixed_exception_text(self):
        from app.trace import redact
        source={'data':json.dumps({'api_key':'JSON_PRIVATE','preference_key':'format','total_tokens':9}),
                'headers':{'authorization':'Basic PRIVATE_ENCODED'},
                'error':'endpoint https://user:PASS@service.test/v1?api_key=QUERY_PRIVATE api_key="TEXT_PRIVATE" reasoning_content="PRIVATE THOUGHT"'}
        text=json.dumps(redact(source))
        for secret in ('JSON_PRIVATE','PRIVATE_ENCODED','PASS','QUERY_PRIVATE','TEXT_PRIVATE','PRIVATE THOUGHT'):
            self.assertNotIn(secret,text)
        self.assertIn('format',text);self.assertIn('9',text)

    def test_native_usage_known_unknown_and_failure_are_not_estimated(self):
        from app.model_config import ModelConnection,validate_profile
        from app.model_transport import ModelTransport
        from app.trace import write_trace
        conn=ModelConnection(validate_profile(profile()),'CREDENTIAL_NOT_LOGGED')
        with tempfile.TemporaryDirectory() as temp,patch('openai.OpenAI') as sdk:
            path=Path(temp)/'trace.jsonl'
            transport=ModelTransport(conn,lambda event,data:write_trace(path,'mock','x',event,data))
            create=sdk.return_value.__enter__.return_value.chat.completions.create
            response=MagicMock();response.choices[0].message.model_dump.return_value={'role':'assistant','content':'{}','reasoning_content':''}
            response.usage.model_dump.return_value={'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}
            create.return_value=response
            transport([{'role':'user','content':'hello'}],[])
            response.usage=None
            transport([{'role':'user','content':'hello'}],[])
            create.side_effect=RuntimeError('api_key=CREDENTIAL_NOT_LOGGED reasoning_content="private error"')
            with self.assertRaises(RuntimeError): transport([{'role':'user','content':'hello'}],[])
            events=[json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
            replies=[e['data'] for e in events if e['event']=='api.response']
            self.assertEqual(replies[0]['usage']['total_tokens'],120)
            self.assertEqual(replies[1]['usage_status'],'UNKNOWN')
            self.assertIsNone(replies[2]['usage']['total_tokens'])
            self.assertFalse(replies[2]['success'])
            self.assertGreaterEqual(replies[0]['latency_ms'],0)
            self.assertEqual(transport.counts(),{'attempts':3,'successes':2,'failures':1})
            self.assertNotIn('CREDENTIAL_NOT_LOGGED',path.read_text())


if __name__=='__main__': unittest.main()
