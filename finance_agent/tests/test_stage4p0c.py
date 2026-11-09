"""4P0C：可信范围/复合目标/匹配回执，不用业务函数生成金额真值。"""
import json
import unittest
from unittest.mock import patch
from app.agent import Agent,scripted_model
from app.context import ContextBuilder
from app.stage2_schema import migrate as s2
from app.stage3_schema import migrate as s3
from app.rules import import_rules,SEED_RULES
from tests.helpers import DatabaseTestCaseMixin

SCOPE=dict(company_id='C001',year=2026,month=9)
FINAL={'role':'assistant','content':json.dumps({'kind':'information','text':'模型声称完成'})}
CLARIFY={'role':'assistant','content':json.dumps({'kind':'clarification','text':'年月？','missing_fields':['year','month']})}
def call(name,args,id='one'):
    return {'role':'assistant','tool_calls':[{'id':id,'type':'function','function':dict(name=name,arguments=json.dumps(args))}]}
def outcomes(agent):return [json.loads(m['content']) for m in agent.messages if m['role']=='tool']

class HarnessCase(DatabaseTestCaseMixin,unittest.TestCase):
    def setUp(self):
        super().setUp();s2(self.db_path);s3(self.db_path);import_rules(self.db_path,SEED_RULES,{'rule.manage'})
    def agent(self,replies,user='U001',**kw):return Agent(user,self.db_path,scripted_model(replies),mode='mock',**kw)

class ProvenanceTests(HarnessCase):
    def test_missing_period_never_executes_monthly_sql(self):
        a=self.agent([call('get_finance_summary',SCOPE),FINAL])
        with patch('app.finance.get_finance_summary',side_effect=AssertionError('不得执行财务查询')):
            answer=a.ask('帮我看看甲企业的发票和银行收支。')
        self.assertEqual(outcomes(a)[0]['status'],'AMBIGUOUS');self.assertIn('年份',answer);self.assertIn('月份',answer)
        self.assertEqual(outcomes(a)[0]['evidence']['missing_fields'],['year','month'])
    def test_month_without_year_is_not_current_year(self):
        a=self.agent([call('get_finance_summary',SCOPE),FINAL]);a.ask('看看C001九月份收支')
        self.assertEqual(outcomes(a)[0]['status'],'AMBIGUOUS')
    def test_current_complete_then_session_completion(self):
        a=self.agent([CLARIFY,call('get_finance_summary',SCOPE),FINAL])
        a.ask('看看甲企业的发票和银行收支');a.ask('2026 年 9 月。')
        self.assertEqual(outcomes(a)[0]['status'],'SUCCESS')
        self.assertIn('9622.06',a.last_response['text'])
    def test_company_only_correction_keeps_confirmed_period(self):
        c=ContextBuilder('U001',self.db_path);c.begin('C001 2026-09',1);c.begin('换成C002',2)
        self.assertEqual(c.scope.get('year'),[2026]);self.assertEqual(c.scope.get('month'),[9]);self.assertEqual(c.scope['company_id'],['C002'])
    def test_month_correction_keeps_company_and_year(self):
        c=ContextBuilder('U001',self.db_path);c.begin('C001 2026年9月',1);c.begin('改成八月',2)
        self.assertEqual(c.scope.get('company_id'),['C001']);self.assertEqual(c.scope.get('year'),[2026]);self.assertEqual(c.scope.get('month'),[8])
    def test_chinese_dates_and_ambiguous_relative_dates(self):
        for text in ('C001 2026年九月','C001，2026年的9月份'):
            a=self.agent([call('get_finance_summary',SCOPE),FINAL]);a.ask(text)
            self.assertEqual(outcomes(a)[0]['status'],'SUCCESS')
        a=self.agent([call('get_finance_summary',SCOPE),FINAL]);a.ask('C001本月收支')
        self.assertEqual(outcomes(a)[0]['status'],'AMBIGUOUS')
    def test_conflict_is_not_missing_or_denied(self):
        a=self.agent([call('get_finance_summary',{**SCOPE,'company_id':'C002'})]);a.ask('C001 2026-09')
        self.assertEqual(outcomes(a)[0]['status'],'SCOPE_MISMATCH')
        b=self.agent([call('get_finance_summary',{**SCOPE,'company_id':'C002'})],user='U002');b.ask('C002')
        self.assertEqual(outcomes(b)[0]['status'],'DENIED')
    def test_model_source_label_is_not_a_proof(self):
        a=self.agent([call('get_finance_summary',{**SCOPE,'source':'user_current'})]);a.ask('看看C001')
        self.assertEqual(outcomes(a)[0]['status'],'INVALID_ARGUMENTS')
    def test_old_result_does_not_launder_a_period(self):
        a=self.agent([call('get_finance_summary',SCOPE)]);a.context.scope=dict(company_id=['C001'],year=[2026],month=[9])
        a.ask('看看甲企业收支')
        self.assertEqual(outcomes(a)[0]['status'],'AMBIGUOUS')
    def test_invoice_detail_does_not_require_a_period(self):
        a=self.agent([call('get_invoice',dict(company_id='C001',invoice_no='F002')),FINAL]);a.ask('甲企业F002用途是什么')
        self.assertEqual(outcomes(a)[0]['status'],'SUCCESS')
    def test_schedule_cannot_authorize_guessed_period(self):
        plan=dict(goal='查看收支',steps=[dict(step_id='q',action='get_finance_summary',arguments=SCOPE,depends_on=[])],stop_condition='查询完成或等待用户')
        a=self.agent([call('set_schedule',plan),call('get_finance_summary',SCOPE)])
        with patch('app.finance.get_finance_summary',side_effect=AssertionError('不得执行猜测查询')):a.ask('看看C001的收支')
        self.assertTrue(any(o['status']=='AMBIGUOUS' for o in outcomes(a)))
    def test_sources_come_from_runtime_and_survive_only_valid_correction(self):
        c=ContextBuilder('U001',self.db_path);c.begin('C001 2026-09',1)
        self.assertEqual(c.proof().sources['month'],'user_current')
        c.begin('换C002',2);self.assertEqual(c.proof().sources['month'],'session_confirmed')
        c.begin('',3,reset=True);self.assertFalse(c.proof().values)

class ReceiptTests(HarnessCase):
    def test_matching_value_is_read_evidence_not_commit(self):
        self.connection.execute("UPDATE invoices SET purpose='项目资料核对' WHERE company_id='C001' AND invoice_no='F002'");self.connection.commit()
        a=self.agent([call('get_invoice',dict(company_id='C001',invoice_no='F002')),FINAL])
        text=a.ask('把甲企业F002的用途改为项目资料核对。',allow_prepare=True)
        self.assertEqual(a.write_receipt['status'],'CURRENT_VALUE_MATCHES');self.assertIn('无需',text)
        self.assertFalse(a.write_receipt['readback_verified']);self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM invoice_audit').fetchone()[0],0)
    def test_different_value_or_denied_is_not_a_match(self):
        a=self.agent([call('get_invoice',dict(company_id='C001',invoice_no='F002')),FINAL]);a.ask('C001 F002用途改为新用途',allow_prepare=True)
        self.assertNotEqual(a.write_receipt['status'],'CURRENT_VALUE_MATCHES')
    def test_model_history_claim_requires_a_real_new_readonly_check(self):
        self.connection.execute("UPDATE invoices SET purpose='项目资料核对' WHERE company_id='C001' AND invoice_no='F002'");self.connection.commit()
        a=self.agent([FINAL])
        with patch.object(a.coordinator,'trace',side_effect=OSError('disk')),patch('app.write_coordination.warn_trace_degraded'):
            text=a.ask('把甲企业F002的用途改为项目资料核对。',allow_prepare=True)
        self.assertEqual(a.write_receipt['status'],'CURRENT_VALUE_MATCHES')
        self.assertEqual(a.write_receipt['data']['checked_by'],'harness_readonly_reconciliation')
        self.assertTrue(a.write_receipt['trace_degraded'])
        self.assertEqual(outcomes(a),[]);self.assertIn('没有Commit',text)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM invoice_audit').fetchone()[0],0)
        self.connection.execute("UPDATE invoices SET purpose='新用途' WHERE company_id='C001' AND invoice_no='F002'");self.connection.commit()
        a=self.agent([call('get_invoice',dict(company_id='C001',invoice_no='F002')),FINAL],user='U002');a.ask('C001 F002用途改为新用途',allow_prepare=True)
        self.assertNotEqual(a.write_receipt['status'],'CURRENT_VALUE_MATCHES')
    def test_saved_and_verified_survives_duplicate_get(self):
        p=dict(company_id='C001',key='reply_format',value='')
        a=self.agent([call('manage_preference',{**p,'action':'get'}),call('manage_preference',{**p,'action':'create','value':'简洁'},'save'),call('manage_preference',{**p,'action':'get'},'verify')],management_confirmation=lambda x:x['proposal']['value']=='简洁')
        answer=a.ask('请记住C001的reply_format回复偏好为简洁，并核对保存的内容。')
        self.assertIn('核对完成',answer);self.assertIn('NO_LEGAL_WORK',answer)
        self.assertIn('简洁',answer);self.assertEqual(self.connection.execute('SELECT value FROM preferences').fetchone()[0],'简洁')
    def test_saved_but_not_verified_is_reported_separately(self):
        p=dict(company_id='C001',action='create',key='format',value='简洁')
        a=self.agent([call('manage_preference',p),None],management_confirmation=lambda x:True)
        answer=a.ask('C001保存format为简洁，并再查询核对')
        self.assertIn('尚未',answer);self.assertIn('核对',answer)
        self.assertEqual(self.connection.execute('SELECT value FROM preferences').fetchone()[0],'简洁')

class IntegrationBoundaryTests(HarnessCase):
    def task(self):
        from app.tasks import manage_task
        from app.persistence import ManagementIntent
        return manage_task(self.db_path,'U001','C001','create',year=2026,month=9,note='下次继续',intent=ManagementIntent('U001','task','可信测试初态'))['data']['task']
    def test_task_list_cannot_launder_an_unselected_period(self):
        self.task()
        a=self.agent([call('list_tasks',{'company_id':'C001'}),call('get_finance_summary',SCOPE)])
        with patch('app.finance.get_finance_summary',side_effect=AssertionError('禁止猜测财务读取')):a.ask('查看C001资料')
        self.assertEqual([o['status'] for o in outcomes(a)],['SUCCESS','AMBIGUOUS'])
        self.assertNotIn('year',a.context.proof().sources)
    def test_confirmed_task_restore_supplies_only_its_own_scope(self):
        task=self.task();args={**SCOPE,'task_id':task['task_id'],'action':'resume','note':''}
        a=self.agent([call('manage_task',args)],management_confirmation=lambda p:p['proposal']==args)
        a.ask('恢复C001任务',management='task',management_action='resume')
        self.assertEqual(a.context.proof().sources.get('month'),'current_sqlite')
        self.assertFalse(a.update_session.allow_prepare)
        a.model=scripted_model([call('get_finance_summary',SCOPE),FINAL]);a.ask('再查询当前任务范围的收支')
        self.assertEqual(outcomes(a)[-1]['status'],'SUCCESS')
        a.model=scripted_model([call('get_finance_summary',{**SCOPE,'company_id':'C002'})]);a.ask('改看C002收支')
        self.assertEqual(outcomes(a)[-1]['status'],'AMBIGUOUS')
    def test_cancelled_candidate_does_not_gain_authority(self):
        args=dict(company_id='C001',action='create',key='reply_format',value='省略审核')
        a=self.agent([call('manage_preference',args)],management_confirmation=lambda p:False)
        a.ask('请记住C001的回复偏好为简洁')
        self.assertEqual(outcomes(a)[0]['status'],'CANCELLED')
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM preferences').fetchone()[0],0)
    def test_plain_false_commit_is_never_a_receipt(self):
        a=self.agent([{'role':'assistant','content':'F002已保存'}]);answer=a.ask('C001 F002')
        self.assertEqual(a.write_receipt['status'],'NOT_SUBMITTED');self.assertNotIn('F002已保存',answer)
    def test_invalid_final_after_query_preserves_only_actual_evidence(self):
        a=self.agent([call('get_finance_summary',SCOPE),{'role':'assistant','content':'发票已保存'}])
        answer=a.ask('C001 2026-09发票和银行收支')
        self.assertIn('9622.06',answer);self.assertEqual(a.execution.stop_reason,'EVIDENCE_RETURNED')
        self.assertNotIn('发票已保存',answer);self.assertEqual(a.write_receipt['status'],'NOT_SUBMITTED')
    def test_json_mode_is_scoped_to_official_provider(self):
        from app.model_config import ModelConnection,validate_profile
        from app.model_transport import ModelTransport
        for provider,base in [('deepseek','https://api.deepseek.com'),('openai-compatible','https://example.test/v1')]:
            p=validate_profile(dict(profile_name='test',scope='global',provider=provider,service_account_ref='test',model='deepseek-v4-pro' if provider=='deepseek' else 'other',base_url=base,api_key_env='TEST_KEY',protocol='auto' if provider=='deepseek' else 'standard'))
            with patch('openai.OpenAI') as sdk:
                create=sdk.return_value.__enter__.return_value.chat.completions.create
                create.return_value.choices[0].message.model_dump.return_value={**FINAL,'reasoning_content':''}
                ModelTransport(ModelConnection(p,'not-a-real-key'))([{'role':'user','content':'JSON'}],[])
                self.assertEqual('response_format' in create.call_args.kwargs,provider=='deepseek')
    def test_mutated_amount_date_and_company_use_independent_sql_truth(self):
        from decimal import Decimal
        self.connection.execute("UPDATE invoices SET company_id='C002',invoice_no='MOVED-X' WHERE company_id='C001' AND invoice_no='F002'")
        self.connection.execute("UPDATE invoices SET invoice_date='2026-08-31' WHERE company_id='C001' AND invoice_no='F001'")
        self.connection.execute("UPDATE invoices SET amount_cents=amount_cents+1 WHERE company_id='C001' AND invoice_no='F003'")
        self.connection.commit()
        count,cents=self.connection.execute("SELECT COUNT(*),SUM(amount_cents) FROM invoices WHERE company_id='C001' AND invoice_date LIKE '2026-09-%'").fetchone()
        a=self.agent([call('get_finance_summary',SCOPE),FINAL]);a.ask('C001 2026-09的发票和收支')
        data=outcomes(a)[0]['data'];self.assertEqual(data['invoice_count'],count)
        self.assertEqual(data['invoice_total'],format(Decimal(cents)/100,'.2f'))
    def test_empty_period_and_revoked_permission_remain_distinct(self):
        a=self.agent([call('get_finance_summary',{**SCOPE,'month':7}),FINAL]);a.ask('C001 2026-07')
        self.assertEqual(outcomes(a)[0]['status'],'NO_DATA');self.assertEqual(outcomes(a)[0]['data']['invoice_total'],'0.00')
        self.connection.execute("UPDATE permissions SET can_read=0 WHERE user_id='U001' AND company_id='C001'");self.connection.commit()
        b=self.agent([call('get_finance_summary',SCOPE)]);b.ask('C001汇总')
        self.assertEqual(outcomes(b)[0]['status'],'DENIED');self.assertIsNone(outcomes(b)[0]['data'])
    def test_existing_task_and_preference_are_not_replaced(self):
        from app.preferences import manage_preference
        from app.persistence import ManagementIntent
        task=self.task();manage_preference(self.db_path,'U001','C001','create','reply_format','详细',ManagementIntent('U001','preference','可信初态'))
        args={**SCOPE,'action':'create','task_id':'','note':'替换历史任务'}
        a=self.agent([call('manage_task',args)]);a.ask('C001 2026-09新建另一个后续任务')
        self.assertEqual(outcomes(a)[0]['status'],'CONFLICT');self.assertEqual(self.connection.execute('SELECT task_id FROM tasks').fetchone()[0],task['task_id'])
        b=self.agent([call('manage_preference',dict(company_id='C001',action='create',key='reply_format',value='简洁'))]);b.ask('C001新建reply_format简洁偏好')
        self.assertEqual(outcomes(b)[0]['status'],'CONFLICT');self.assertEqual(self.connection.execute('SELECT value FROM preferences').fetchone()[0],'详细')
