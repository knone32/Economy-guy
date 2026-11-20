import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from app.assistant_config import configure, refresh_assistant, use_skill
from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.tool_registry import handle_tool
from tests.test_model_intent import call


class AssistantConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'book.sqlite3'
        import_workspace(Path(__file__).parent/'fixtures/example.xlsx',self.path)

    def put(self,kind,key,body,revision=0,enabled=True,actor='U001'):
        return configure(self.path,actor,kind,key,body,expected_revision=revision,enabled=enabled,capabilities={'assistant.manage'})

    def assistants(self):
        self.put('skill','missing',{'name':'查发票缺项','tools':['check_missing_purpose'],'steps':['按企业和业务日期读适用制度','列出缺项和制度版本']})
        tools=['use_skill','get_invoice','check_missing_purpose']
        for name,extra in [('query',[]),('edit',['change_invoice'])]:
            self.put('assistant',name,{'name':name,'tools':tools+extra,'skills':['missing']})

    def test_shared_lifecycle_refreshes_existing_agents_and_stale_dispatch(self):
        self.assistants()
        agents=[Agent('U001',self.path,lambda *_:None,mode='mock') for _ in range(2)]
        for agent,key in zip(agents,['query','edit']):
            agent.assistant_id=key;refresh_assistant(agent)
            self.assertEqual(agent.active_skills[0]['revision'],1)
            self.assertEqual(use_skill(self.path,'U001','missing','C001',agent.allowed_tools)['revision'],1)
        self.put('skill','missing',{'name':'查发票缺项','tools':['check_missing_purpose'],'steps':['先列缺项，再讲制度版本和剩余事项']},1)
        for agent in agents:
            refresh_assistant(agent);self.assertEqual(agent.active_skills[0]['revision'],2)
        self.put('skill','missing',{'name':'查发票缺项','tools':['check_missing_purpose'],'steps':['停用']},2,False)
        for agent in agents:
            refresh_assistant(agent);self.assertEqual(agent.active_skills,[])
            self.assertIn('check_missing_purpose',agent.allowed_tools)
            with self.assertRaises(PermissionError):use_skill(self.path,'U001','missing','C001',agent.allowed_tools)
        stale=agents[0].allowed_tools
        self.put('tool','get_invoice',{},enabled=False)
        result=handle_tool('get_invoice',json.dumps({'company_id':'C001','invoice_no':'F006'}),'U001',self.path,allowed_tools=stale)
        self.assertEqual(result['status'],'DENIED')
        self.put('assistant','query',{'name':'查询助手','tools':['use_skill'],'skills':[]},1)
        result=handle_tool('get_invoice',json.dumps({'company_id':'C001','invoice_no':'F006'}),'U001',self.path,allowed_tools=stale,assistant_id='query')
        self.assertEqual(result['status'],'DENIED')
        result=handle_tool('use_skill',json.dumps({'company_id':'C001','skill_id':'missing'}),'U001',self.path,allowed_tools=stale,assistant_id='query')
        self.assertEqual(result['status'],'DENIED')

    def test_assistant_and_actor_permissions_are_independent(self):
        self.assistants()
        args={'company_id':'C001','year':2026,'month':9,'invoice_no':'F006','field':'remark','new_value':'暂存前核对'}
        def model(*_):return call('change_invoice',args)
        query=Agent('U001',self.path,model,mode='mock');query.assistant_id='query'
        query.ask('甲企业2026年9月F006备注改为“暂存前核对”')
        self.assertIsNone(query.last_response.get('invoice_change'))
        self.assertTrue(any(r['status']=='DENIED' for _,r in query.last_response['tool_results']))
        edit=Agent('U001',self.path,model,mode='mock');edit.assistant_id='edit'
        edit.ask('甲企业2026年9月F006备注改为“暂存前核对”')
        self.assertIsNotNone(edit.last_response.get('invoice_change'))
        self.put('assistant','edit',{'name':'补录','tools':['get_invoice','change_invoice'],'skills':[]},actor='U002')
        denied=Agent('U002',self.path,model,mode='mock');denied.assistant_id='edit'
        denied.ask('甲企业2026年9月F006备注改为“暂存前核对”')
        self.assertIsNone(denied.last_response.get('invoice_change'))

    def test_management_requires_explicit_capability_and_revision(self):
        with self.assertRaises(PermissionError):configure(self.path,'U001','tool','get_invoice',{})
        self.put('tool','get_invoice',{})
        with self.assertRaises(ValueError):self.put('tool','get_invoice',{},enabled=False)
        with self.assertRaises(ValueError):self.put('tool','arbitrary_python',{})

    def test_switch_model_keeps_assistant_scope(self):
        from types import SimpleNamespace
        self.assistants()
        original=Agent('U001',self.path,lambda *_:None,mode='mock')
        original.assistant_id='query';refresh_assistant(original)
        switched=original.switch_model(SimpleNamespace(authorize=lambda actor:None))
        self.assertEqual(switched.assistant_id,'query')
        self.assertNotIn('change_invoice',switched.allowed_tools)
