"""DeepSeek协议模拟，非live；私有推理哨兵只在本轮进程及传输上下文出现。"""
import json
import os
import subprocess
import sys
import unittest
from copy import deepcopy
from unittest.mock import patch
from app.agent import Agent,scripted_model
from app.stage2_schema import migrate as stage2
from app.stage3_schema import migrate as stage3
from app.rules import import_rules,SEED_RULES
from tests.helpers import DatabaseTestCaseMixin,ROOT

PRIVATE='PRIVATE_PROTOCOL_TEST_SENTINEL_74391'
SCOPE={'company_id':'C001','year':2026,'month':9}
ENV={'OPENAI_BASE_URL':'https://api.deepseek.com','OPENAI_MODEL':'deepseek-flash'}


def final(reasoning=PRIVATE):
    return {'role':'assistant','content':json.dumps({'kind':'information','text':'查询结果'}),'reasoning_content':reasoning}


def calls(*items,reasoning=PRIVATE):
    return {'role':'assistant','tool_calls':[{'id':str(i),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}
        for i,(name,args) in enumerate(items)],'reasoning_content':reasoning}


class Stage4PCTests(DatabaseTestCaseMixin,unittest.TestCase):
    def setUp(self):
        super().setUp()
        stage2(self.db_path);stage3(self.db_path);import_rules(self.db_path,SEED_RULES,{'rule.manage'})
        self.env=patch.dict(os.environ,ENV)
        self.env.start();self.addCleanup(self.env.stop)

    def agent(self,replies,**kwargs):
        from app.thinking_protocol import ThinkingProtocol
        agent=Agent('U001',self.db_path,scripted_model(replies),mode='mock',**kwargs)
        agent.protocol=ThinkingProtocol()  # 显式开启协议模拟；普通Mock不受live配置影响。
        return agent

    def test_thinking_tool_reply_is_replayed_exactly(self):
        seen=[]
        replies=iter([calls(('get_finance_summary',SCOPE)),final('FINAL_PRIVATE_SENTINEL')])
        def model(messages,tools):
            seen.append(deepcopy(messages));return next(replies)
        agent=Agent('U001',self.db_path,model,mode='mock')
        from app.thinking_protocol import ThinkingProtocol
        agent.protocol=ThinkingProtocol()
        answer=agent.ask('C001 2026-09')
        actual=next(m for m in seen[1] if m.get('tool_calls'))
        self.assertEqual(actual.get('reasoning_content'),PRIVATE)
        self.assertNotIn(PRIVATE,answer)
        self.assertNotIn(PRIVATE,json.dumps(agent.messages,ensure_ascii=False))

    def test_final_without_tool_is_replayed_next_user_turn(self):
        agent=self.agent([final()])
        agent.ask('C001 2026-09')
        agent.model=scripted_model([calls(('get_finance_summary',SCOPE)),final('later')])
        agent.ask('请再查当前汇总')
        context=agent.model_messages()
        self.assertTrue(any(m.get('reasoning_content')==PRIVATE and not m.get('tool_calls') for m in context))
        self.assertEqual(agent.execution.stop_reason,'ANSWERED')

    def test_multiple_calls_rejection_and_budget_still_pair(self):
        for limit,user in ((1,'U001'),(12,'U002')):
            agent=self.agent([calls(('get_finance_summary',SCOPE),('get_finance_summary',{**SCOPE,'company_id':'C002'}))],max_tools=limit)
            agent.user_id=user
            agent.ask('查询资料')
            messages=agent.model_messages()
            self.assertEqual([c['id'] for m in messages for c in m.get('tool_calls',[])],
                             [m['tool_call_id'] for m in messages if m['role']=='tool'])
            self.assertEqual(next(m['reasoning_content'] for m in messages if m.get('tool_calls')),PRIVATE)
            self.assertEqual(agent.execution.stop_reason,'TOOL_LIMIT' if limit==1 else 'DENIED')

    def test_private_current_context_limit_stops_before_next_api(self):
        agent=self.agent([calls(('get_finance_summary',SCOPE),reasoning=PRIVATE*1000)],max_context_chars=7000)
        agent.ask('C001 2026-09')
        self.assertEqual(agent.execution.stop_reason,'CONTEXT_LIMIT')
        self.assertEqual(agent.execution.model_requests,1)
        self.assertNotIn(PRIVATE,agent.last_response['text'])

    def test_history_is_trimmed_with_private_fields_as_whole_turn(self):
        agent=self.agent([final(PRIVATE*300)],max_context_chars=7000)
        agent.ask('先查询C001 2026-09')
        agent.model=scripted_model([final('CURRENT_PROTOCOL')])
        agent.ask('现在解释一般概念')
        context=agent.model_messages()
        self.assertFalse(any(PRIVATE in m.get('reasoning_content','') for m in context))
        self.assertTrue(any(m.get('reasoning_content')=='CURRENT_PROTOCOL' for m in context))
        self.assertLessEqual(len(json.dumps(context,ensure_ascii=False)),7000)

    def test_ordinary_provider_never_receives_private_field(self):
        with patch.dict(os.environ,{'OPENAI_BASE_URL':'https://example.test/v1','OPENAI_MODEL':'standard-model'}):
            agent=self.agent([calls(('get_finance_summary',SCOPE)),final()])
            agent.ask('C001 2026-09')
            self.assertFalse(any('reasoning_content' in m for m in agent.model_messages()))

    def test_missing_none_and_invalid_reasoning_fail_without_write(self):
        for value in (None,42,{'confirmed':True}):
            agent=self.agent([calls(('manage_preference',{'company_id':'C001','action':'create','key':'format','value':'简洁'}),reasoning=value)],management_confirmation=lambda p:True)
            agent.ask('请记住C001简洁')
            self.assertEqual(agent.execution.stop_reason,'API_OR_RESPONSE_ERROR')
            self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM preferences').fetchone()[0],0)
        missing=final();missing.pop('reasoning_content')
        agent=self.agent([missing]);agent.ask('C001 2026-09')
        self.assertEqual(agent.execution.stop_reason,'API_OR_RESPONSE_ERROR')

    def test_actual_empty_reasoning_is_preserved_not_invented(self):
        agent=self.agent([final('')]);agent.ask('C001 2026-09')
        context=agent.model_messages()
        self.assertTrue(any(m.get('content')==final('')['content'] and m.get('reasoning_content')=='' for m in context))

    def test_trace_never_contains_raw_reasoning_even_nested(self):
        from app.trace import write_trace
        path=self.db_path.parent/'private_trace.jsonl'
        agent=self.agent([calls(('get_finance_summary',SCOPE)),final()],trace_path=path)
        answer=agent.ask('C001 2026-09')
        for event in ('model_input','model_reply','tool_result','turn.finished','error'):
            write_trace(path,'mock','s',event,{'nested':[{'reasoning_content':PRIVATE}]})
        text=path.read_text(encoding='utf-8')
        self.assertNotIn(PRIVATE,text)
        self.assertIn('PRIVATE_PROTOCOL',text)
        self.assertNotIn(PRIVATE,answer)

    def test_identity_new_agent_and_process_do_not_restore_private_state(self):
        agent=self.agent([final()]);agent.ask('C001 2026-09')
        agent.user_id='U002'
        self.assertNotIn(PRIVATE,json.dumps(agent.model_messages(),ensure_ascii=False))
        fresh=self.agent([final('new')])
        self.assertNotIn(PRIVATE,json.dumps(fresh.model_messages(),ensure_ascii=False))
        command="from app.agent import Agent; import sys,json; print(json.dumps(Agent('U001',sys.argv[1],mode='mock').model_messages()))"
        run=subprocess.run([sys.executable,'-X','utf8','-c',command,str(self.db_path)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertNotIn(PRIVATE,run.stdout)

    def test_private_reasoning_does_not_enter_task_preference_or_audit(self):
        args={'company_id':'C001','action':'create','key':'format','value':'简洁'}
        agent=self.agent([calls(('manage_preference',args)),final()],management_confirmation=lambda p:p['proposal']==args)
        agent.ask('C001保存偏好简洁')
        for table in ('preferences','tasks','invoice_audit','invoices'):
            self.assertNotIn(PRIVATE,str([tuple(r) for r in self.connection.execute('SELECT * FROM '+table)]))

    def test_provider_configuration_change_cannot_export_history(self):
        agent=self.agent([final()]);agent.ask('C001 2026-09')
        with patch.dict(os.environ,{'OPENAI_BASE_URL':'https://elsewhere.test/v1','OPENAI_MODEL':'another'}):
            agent.model=lambda *_:self.fail('不得在旧协议会话调用新服务')
            answer=agent.ask('查询当前值')
            self.assertNotIn(PRIVATE,answer)
            self.assertEqual(agent.execution.stop_reason,'PROTOCOL_ERROR')

    def test_explicit_off_and_no_tools_strip_private_fields(self):
        from app.thinking_protocol import ThinkingProtocol
        message=final()
        off=ThinkingProtocol('https://api.deepseek.com','deepseek-flash',thinking=False)
        self.assertNotIn('reasoning_content',off.wire([message])[0])
        on=ThinkingProtocol('https://api.deepseek.com','deepseek-flash')
        self.assertNotIn('reasoning_content',on.wire([message],tools=False)[0])
        self.assertIn('reasoning_content',on.wire([message],tools=True)[0])

    def test_sdk_payload_has_original_fields_but_standard_api_does_not(self):
        from app.agent import live_model
        from unittest.mock import MagicMock
        for base,model,expected in (('https://api.deepseek.com','deepseek-flash',True),
                                     ('https://example.test/v1','standard',False)):
            with patch.dict(os.environ,{'OPENAI_BASE_URL':base,'OPENAI_MODEL':model,'OPENAI_API_KEY':'unit-test-placeholder'}),patch('openai.OpenAI') as sdk:
                result=MagicMock();result.choices[0].message.model_dump.return_value=final()
                create=sdk.return_value.__enter__.return_value.chat.completions.create
                create.return_value=result
                live_model([final()], [{'type':'function','function':{'name':'test'}}])
                sent=create.call_args.kwargs['messages'][0]
                self.assertEqual('reasoning_content' in sent,expected)
                if expected:
                    self.assertEqual(sent['reasoning_content'],PRIVATE)

    def test_scope_correction_discards_conflicting_private_history(self):
        agent=self.agent([final()]);agent.ask('C001 2026-09')
        agent.model=scripted_model([calls(('get_finance_summary',{**SCOPE,'month':8}),reasoning='AUGUST_PROTOCOL'),final('AUGUST_FINAL')])
        answer=agent.ask('更正为C001 2026-08')
        self.assertIn('9046.35',answer)
        self.assertNotIn(PRIVATE,json.dumps(agent.model_messages(),ensure_ascii=False))

    def test_custom_deepseek_proxy_is_blocked_without_guessing(self):
        with patch.dict(os.environ,{'OPENAI_BASE_URL':'https://proxy.example.test/v1'}):
            agent=self.agent([])
            answer=agent.ask('C001 2026-09')
            self.assertEqual(agent.execution.stop_reason,'PROTOCOL_ERROR')
            self.assertIn('代理',answer)
            self.assertEqual(agent.execution.model_requests,0)

    def test_api_error_after_commit_never_rewrites_business(self):
        path=self.db_path.parent/'error_trace.jsonl'
        agent=self.agent([calls(('prepare_invoice_update',{'company_id':'C001','invoice_no':'F002','field':'purpose','new_value':'资料整理'}))],trace_path=path)
        agent.ask('C001 F002用途改为资料整理',allow_prepare=True)
        draft=next(iter(agent.update_session.drafts.values()))
        self.assertEqual(agent.commit_update(draft.request_id,draft.fingerprint())['status'],'COMMITTED')
        def failed(*_):
            raise RuntimeError(PRIVATE)
        agent.model=failed
        answer=agent.ask('再次查询当前用途')
        self.assertEqual(agent.execution.stop_reason,'API_OR_RESPONSE_ERROR')
        self.assertEqual(agent.execution.model_requests,1)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM invoice_audit').fetchone()[0],1)
        self.assertEqual(self.connection.execute("SELECT purpose FROM invoices WHERE company_id='C001' AND invoice_no='F002'").fetchone()[0],'资料整理')
        self.assertNotIn(PRIVATE,answer+path.read_text(encoding='utf-8'))

    def test_plain_mock_stays_independent_of_live_provider_environment(self):
        tool_reply=calls(('get_finance_summary',SCOPE));tool_reply.pop('reasoning_content')
        text_reply=final();text_reply.pop('reasoning_content')
        agent=Agent('U001',self.db_path,scripted_model([tool_reply,text_reply]),mode='mock')
        answer=agent.ask('C001 2026-09')
        self.assertIn('9622.06',answer)
        self.assertEqual(agent.execution.stop_reason,'ANSWERED')


if __name__=='__main__':
    unittest.main()
