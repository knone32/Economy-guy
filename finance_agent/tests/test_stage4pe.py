"""冻结Live反例的最小回归：负向读取证据、当前轮写工具边界及查询焦点。"""
import json
import unittest
from app.agent import Agent, scripted_model
from app.rules import import_rules, SEED_RULES
from app.stage2_schema import migrate as s2
from app.stage3_schema import migrate as s3
from tests.helpers import DatabaseTestCaseMixin


def call(name,args,id='one'):
    return {'role':'assistant','tool_calls':[{'id':id,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}


FINAL={'role':'assistant','content':json.dumps({'kind':'information','text':'模型声称已完成'})}
PREF={'company_id':'C001','key':'reply_format','value':''}
SCOPE={'company_id':'C001','year':2026,'month':9}


class Stage4PETests(DatabaseTestCaseMixin,unittest.TestCase):
    def setUp(self):
        super().setUp();s2(self.db_path);s3(self.db_path);import_rules(self.db_path,SEED_RULES,{'rule.manage'})

    def test_missing_preference_then_confirmed_create_and_read(self):
        write=call('manage_preference',{**PREF,'action':'create','value':'简洁'},'two')
        write['tool_calls']+=call('manage_preference',{**PREF,'action':'get'},'three')['tool_calls']
        agent=Agent('U001',self.db_path,scripted_model([
            call('manage_preference',{**PREF,'action':'get'}),
            write,FINAL]),mode='mock',
            management_confirmation=lambda p:p['proposal']=={**PREF,'action':'create','value':'简洁'})
        answer=agent.ask('请记住C001的reply_format回复偏好为简洁，并核对保存的内容。')
        row=self.connection.execute('SELECT user_id,company_id,value FROM preferences').fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(tuple(row),('U001','C001','简洁'))
        outcomes=[json.loads(m['content']) for m in agent.messages if m['role']=='tool']
        self.assertEqual([r['status'] for r in outcomes],['NOT_FOUND','SUCCESS','SUCCESS'])
        self.assertIn('简洁',answer)
        self.assertEqual(agent.execution.stop_reason,'ANSWERED')

    def test_negative_read_never_creates_or_grants_confirmation(self):
        agent=Agent('U001',self.db_path,scripted_model([call('manage_preference',{**PREF,'action':'get'}),FINAL]),mode='mock')
        answer=agent.ask('查询C001的reply_format偏好。')
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM preferences').fetchone()[0],0)
        self.assertIn('NOT_FOUND',answer)
        self.assertNotIn('0.00',answer)
        self.assertFalse(agent.update_session.confirmations)

    def test_readonly_turn_hides_prepare_but_edit_still_prepares(self):
        seen=[]
        def model(messages,tools):
            seen.append({t['function']['name'] for t in tools})
            if len(seen)==1:return FINAL
            return call('prepare_invoice_update',dict(company_id='C001',invoice_no='F002',field='purpose',new_value='资料核对'))
        agent=Agent('U001',self.db_path,model,mode='mock')
        agent.ask('查看当前企业当前月份的未完成用途待办及现在还缺哪些发票用途。')
        self.assertNotIn('prepare_invoice_update',seen[0])
        agent.ask('把C001 F002的用途改为资料核对',allow_prepare=True)
        self.assertIn('prepare_invoice_update',seen[1])
        self.assertEqual(agent.write_receipt['status'],'WAITING_CONFIRMATION')
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM invoice_audit').fetchone()[0],0)

    def test_unsolicited_prepare_and_permission_denial_still_stop(self):
        args=dict(company_id='C001',invoice_no='F002',field='purpose',new_value='不能保存')
        for user,allow in [('U001',False),('U002',True)]:
            agent=Agent(user,self.db_path,scripted_model([call('prepare_invoice_update',args)]),mode='mock')
            agent.ask('C001 F002',allow_prepare=allow)
            self.assertEqual(agent.execution.stop_reason,'DENIED')
            self.assertFalse(agent.update_session.drafts)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM invoice_audit').fetchone()[0],0)

    def test_scope_correction_keeps_only_read_operation_focus(self):
        seen=[]
        def model(messages,tools):
            seen.append(messages)
            if len(seen)==1:return call('get_finance_summary',SCOPE)
            return FINAL
        agent=Agent('U001',self.db_path,model,mode='mock')
        agent.ask('看看C001 2026年9月发票和银行收支')
        agent.ask('改查甲企业2026年8月。')
        data=[json.loads(m['content']) for m in seen[-1] if m.get('name')=='context_data'][0]
        self.assertIn('get_finance_summary',data['prior_query_tools'])
        self.assertEqual(data['scope']['month'],[8])
        self.assertNotIn('9622.06',json.dumps(data))
        self.assertFalse(agent.update_session.confirmations)
