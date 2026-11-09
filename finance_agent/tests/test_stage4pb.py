"""4P-B：已执行事实、范围完整汇总和当前任务进度，全部使用临时SQLite。"""
import json
import subprocess
import sys
import sqlite3
import unittest
from unittest.mock import patch
from app.agent import Agent, scripted_model
from app.persistence import ManagementIntent
from app.preferences import manage_preference
from app.tasks import manage_task
from app.rules import SEED_RULES, import_rules
from app.stage2_schema import migrate as stage2
from app.stage3_schema import migrate as stage3
from tests.helpers import DatabaseTestCaseMixin, ROOT


def call(name,args,identifier='q'):
    return {'id':identifier,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}


def reply(*calls):
    return {'role':'assistant','tool_calls':list(calls)}


FINAL={'role':'assistant','content':json.dumps({'kind':'information','text':'模型声称全部成功'})}
PERIOD={'company_id':'C001','year':2026,'month':9}
TASK={**PERIOD,'action':'create','task_id':'','note':'下次继续补齐用途'}


class Stage4PBTests(DatabaseTestCaseMixin,unittest.TestCase):
    def setUp(self):
        super().setUp()
        stage2(self.db_path); stage3(self.db_path)
        import_rules(self.db_path,SEED_RULES,{'rule.manage'})

    def agent(self,replies,**kwargs):
        return Agent('U001',self.db_path,scripted_model(replies),mode='mock',**kwargs)

    def assert_pairs(self,agent):
        self.assertEqual([c['id'] for m in agent.messages for c in m.get('tool_calls',[])],
                         [m['tool_call_id'] for m in agent.messages if m['role']=='tool'])

    def task(self):
        return manage_task(self.db_path,'U001',**TASK,intent=ManagementIntent('U001','task','明确下次继续补用途'))['data']['task']

    def prepare(self,agent,field='purpose',value='项目资料整理'):
        agent.model=scripted_model([reply(call('prepare_invoice_update',
            {'company_id':'C001','invoice_no':'F002','field':field,'new_value':value}))])
        agent.ask('将C001 F002 '+field+'改为'+value,allow_prepare=True)
        return next(iter(agent.update_session.drafts.values()))

    def test_query_success_survives_duplicate(self):
        agent=self.agent([reply(call('get_finance_summary',PERIOD)),reply(call('get_finance_summary',PERIOD,'again'))])
        answer=agent.ask('查询C001 2026-09')
        self.assertIn('9622.06',answer)
        self.assertIn('NO_PROGRESS',answer)
        self.assertIn('未完成',answer)
        self.assertEqual(agent.execution.stop_reason,'NO_PROGRESS')
        self.assertEqual(agent.execution.actual_tools,1)
        self.assert_pairs(agent)

    def test_confirmed_task_success_survives_duplicate(self):
        agent=self.agent([reply(call('manage_task',TASK)),reply(call('manage_task',TASK,'again'))],management_confirmation=lambda p:p['proposal']==TASK)
        answer=agent.ask('将C001 2026-09缺用途记成下次继续的待办')
        task_id=self.connection.execute('SELECT task_id FROM tasks').fetchone()[0]
        self.assertIn(task_id,answer)
        self.assertIn('SUCCESS',answer)
        self.assertIn('NO_PROGRESS',answer)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],1)
        self.assert_pairs(agent)

    def test_preference_update_survives_duplicate(self):
        manage_preference(self.db_path,'U001','C001','create','format','简洁',ManagementIntent('U001','preference','明确直接保存'))
        args={'company_id':'C001','action':'update','key':'format','value':'详细'}
        agent=self.agent([reply(call('manage_preference',args)),reply(call('manage_preference',args,'again'))],management_confirmation=lambda p:True)
        answer=agent.ask('C001 format改为详细')
        self.assertIn('详细',answer)
        self.assertIn('NO_PROGRESS',answer)
        self.assertEqual(self.connection.execute('SELECT value FROM preferences').fetchone()[0],'详细')

    def test_success_then_invalid_response_or_api_error_preserves_evidence(self):
        for final in ({'role':'assistant','content':'invalid json'},None):
            with self.subTest(final=final):
                agent=self.agent([reply(call('get_finance_summary',PERIOD)),final])
                answer=agent.ask('查询C001 2026-09')
                self.assertIn('9622.06',answer)
                if final is not None:
                    self.assertEqual(agent.execution.stop_reason,'EVIDENCE_RETURNED')
                    self.assertIn('仅覆盖',answer)
                else:
                    self.assertIn(agent.execution.stop_reason,answer)
                    self.assertIn('未完成',answer)
                self.assertNotEqual(agent.execution.stop_reason,'ANSWERED')

    def test_mixed_success_denied_error_does_not_claim_global_success(self):
        for name,args,status in (('get_finance_summary',{**PERIOD,'company_id':'C002'},'DENIED'),
                                 ('get_invoice',{'company_id':'C001','invoice_no':''},'INVALID_ARGUMENTS')):
            with self.subTest(status=status):
                agent=self.agent([reply(call('get_finance_summary',PERIOD,'ok'),call(name,args,'bad'))])
                agent.user_id='U002'
                answer=agent.ask('查询C001 2026-09资料')
                self.assertIn('9622.06',answer)
                self.assertIn(status,answer)
                self.assertNotIn('12667.24',answer)
                self.assertNotIn('全部成功',answer)
                self.assert_pairs(agent)

    def test_tool_limit_preserves_success_and_all_ids(self):
        agent=self.agent([reply(call('get_finance_summary',PERIOD,'ok'),call('list_invoices',PERIOD,'skip'))],max_tools=1)
        answer=agent.ask('查询C001 2026-09')
        self.assertIn('9622.06',answer)
        self.assertIn('TOOL_LIMIT',answer)
        self.assertEqual(agent.execution.actual_tools,1)
        self.assert_pairs(agent)

    def test_database_error_does_not_hide_previous_success(self):
        import app.tool_registry as registry
        original=registry.finance.get_finance_summary
        def failure(connection,user,**args):
            if args['company_id']=='C002':
                raise sqlite3.OperationalError('临时故障')
            return original(connection,user,**args)
        agent=self.agent([reply(call('get_finance_summary',PERIOD,'ok'),
            call('get_finance_summary',{**PERIOD,'company_id':'C002'},'error'))])
        with patch('app.tool_registry.finance.get_finance_summary',side_effect=failure):
            answer=agent.ask('查询C001和C002 2026-09资料')
        self.assertEqual(agent.execution.stop_reason,'ERROR')
        self.assertIn('9622.06',answer)
        self.assertIn('ERROR',answer)
        self.assertNotIn('12667.24',answer)
        self.assert_pairs(agent)

    def test_no_evidence_cannot_make_success(self):
        agent=self.agent([FINAL])
        answer=agent.ask('把C001 F002保存',allow_prepare=True)
        self.assertNotIn('全部成功',answer)
        self.assertEqual(agent.write_receipt['status'],'NOT_SUBMITTED')
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM invoice_audit').fetchone()[0],0)

    def test_a2_followup_retains_goal_and_details_include_aggregates(self):
        question={'role':'assistant','content':json.dumps({'kind':'clarification','text':'年份月份？','missing_fields':['year','month']})}
        def model(messages,tools):
            if messages[-1]['role']=='user' and '2026' not in messages[-1]['content']:
                return question
            if messages[-1]['role']=='tool':
                return FINAL
            self.assertTrue(any('发票和银行收支' in m.get('content','') for m in messages))
            return reply(call('list_invoices',PERIOD,'invoices'),call('list_bank_transactions',PERIOD,'bank'))
        agent=Agent('U001',self.db_path,model,mode='mock')
        self.assertIn('年份',agent.ask('帮我看看甲企业的发票和银行收支。'))
        answer=agent.ask('2026 年 9 月。')
        for item in ('9622.06','13000.50','7180.74','10张','4条','8条','R001','1.0','C001','2026-09'):
            self.assertIn(item,answer)
        self.assertIsNone(agent.execution.schedule)

    def test_detail_aggregates_are_not_hardcoded_and_scope_changes(self):
        self.connection.execute("UPDATE invoices SET amount_cents=amount_cents+1 WHERE company_id='C001' AND invoice_no='F002'")
        self.connection.commit()
        for company,month in (('C001',9),('C001',8),('C002',9),('C001',7)):
            args={'company_id':company,'year':2026,'month':month}
            agent=self.agent([reply(call('list_invoices',args)),FINAL])
            answer=agent.ask(f'查询{company} 2026-{month:02d}')
            cents,count=self.connection.execute('SELECT COALESCE(SUM(amount_cents),0),COUNT(*) FROM invoices WHERE company_id=? AND invoice_date LIKE ?',
                (company,f'2026-{month:02d}%')).fetchone()
            self.assertIn(f'{cents//100}.{cents%100:02d}',answer)
            self.assertIn(f'{count}张',answer)
            self.assertIn(company,answer)
            if not count:
                self.assertIn('没有匹配记录',answer)

    def test_month_correction_discards_old_scope(self):
        agent=self.agent([reply(call('get_finance_summary',PERIOD)),FINAL])
        self.assertIn('9622.06',agent.ask('C001 2026-09'))
        agent.model=scripted_model([reply(call('get_finance_summary',{**PERIOD,'month':8})),FINAL])
        answer=agent.ask('改查C001 2026-08')
        self.assertIn('9046.35',answer)
        self.assertNotIn('9622.06',answer)

    def test_commit_shows_current_remaining_without_completing_task(self):
        task=self.task()
        agent=self.agent([])
        draft=self.prepare(agent)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM invoice_audit').fetchone()[0],0)
        receipt=agent.commit_update(draft.request_id,draft.fingerprint())
        self.assertEqual(receipt['status'],'COMMITTED')
        self.assertTrue(receipt['readback_verified'])
        progress=receipt.get('task_progress')
        self.assertIsNotNone(progress)
        self.assertEqual(progress['status'],'SUCCESS')
        self.assertEqual(progress['data']['check']['count'],4)
        self.assertEqual(progress['data']['task']['task_id'],task['task_id'])
        self.assertEqual(progress['data']['task']['status'],'ACTIVE')
        self.assertNotIn('F002',[r['invoice_no'] for r in progress['data']['check']['missing_invoices']])
        self.assertEqual(self.connection.execute("SELECT purpose FROM invoices WHERE company_id='C001' AND invoice_no='F002'").fetchone()[0],'项目资料整理')
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM invoice_audit WHERE status='COMMITTED'").fetchone()[0],1)
        code="from app.tasks import task_progress; import sys,json; print(json.dumps(task_progress(sys.argv[1],'U001','C001',2026,9),ensure_ascii=False))"
        completed=subprocess.run([sys.executable,'-X','utf8','-c',code,str(self.db_path)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['data']['check']['count'],4)

    def test_remark_no_change_cancel_failure_do_not_invent_progress(self):
        self.task()
        agent=self.agent([])
        for field,value,status in (('remark','备注整理','COMMITTED'),('remark','备注整理','NO_CHANGE')):
            draft=self.prepare(agent,field,value)
            receipt=agent.commit_update(draft.request_id,draft.fingerprint())
            self.assertEqual(receipt['status'],status)
            self.assertEqual(receipt['task_progress']['data']['check']['count'],5)
        draft=self.prepare(agent)
        cancelled=agent.cancel_update()
        self.assertEqual(cancelled['status'],'CANCELLED')
        self.assertNotIn('task_progress',cancelled)
        draft=self.prepare(agent)
        self.connection.execute("UPDATE invoices SET purpose='其他已改内容' WHERE company_id='C001' AND invoice_no='F002'")
        self.connection.commit()
        failed=agent.commit_update(draft.request_id,draft.fingerprint())
        self.assertEqual(failed['status'],'CONFLICT')
        self.assertNotIn('task_progress',failed)
        self.assertEqual(self.connection.execute("SELECT status FROM tasks").fetchone()[0],'ACTIVE')

    def test_progress_failure_does_not_undo_verified_commit(self):
        self.task()
        agent=self.agent([])
        draft=self.prepare(agent)
        self.connection.execute("UPDATE rules SET status='DISABLED' WHERE rule_id='R002' AND version='2.0'")
        self.connection.commit()
        receipt=agent.commit_update(draft.request_id,draft.fingerprint())
        self.assertEqual(receipt['status'],'COMMITTED')
        self.assertTrue(receipt['readback_verified'])
        self.assertEqual(receipt['task_progress']['status'],'NO_APPLICABLE_RULE')
        self.assertIsNone(receipt['task_progress']['data'])

    def test_progress_permission_is_rechecked_and_not_cached(self):
        from app.tasks import task_progress
        self.task()
        self.connection.execute("UPDATE permissions SET can_read=0 WHERE user_id='U001' AND company_id='C001'")
        self.connection.commit()
        progress=task_progress(self.db_path,'U001','C001',2026,9)
        self.assertEqual(progress['status'],'DENIED')
        self.assertIsNone(progress['data'])

    def test_progress_uses_new_database_values_and_preserves_task_status(self):
        from app.tasks import task_progress
        self.task()
        self.assertEqual(task_progress(self.db_path,'U001','C001',2026,9)['data']['check']['count'],5)
        self.connection.execute("UPDATE invoices SET purpose='后来真实补充' WHERE company_id='C001' AND invoice_no='F003'")
        self.connection.commit()
        progress=task_progress(self.db_path,'U001','C001',2026,9)
        self.assertEqual(progress['data']['check']['count'],4)
        self.assertNotIn('F003',[r['invoice_no'] for r in progress['data']['check']['missing_invoices']])
        self.assertEqual(self.connection.execute('SELECT status FROM tasks').fetchone()[0],'ACTIVE')
        self.assertEqual(task_progress(self.db_path,'U002','C001',2026,9)['status'],'NO_DATA')

    def test_combined_plan_without_confirmation_never_saves(self):
        steps=[{'step_id':'check','action':'check_missing_purpose','arguments':PERIOD,'depends_on':[]},
               {'step_id':'save','action':'manage_task','arguments':TASK,'depends_on':['check']}]
        agent=self.agent([reply(call('set_schedule',{'goal':'检查后保存','steps':steps,'stop_condition':'等待确认'})),
            reply(call('check_missing_purpose',PERIOD)),reply(call('manage_task',TASK))])
        answer=agent.ask('检查C001 2026-09用途，把未完成事项记成下次待办')
        self.assertEqual(agent.execution.stop_reason,'WAITING_CONFIRMATION',answer)
        self.assertIn('确认',answer)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)
        self.assertIsNone(agent.management_turn)
        self.assertFalse(agent.update_session.drafts)
        self.assert_pairs(agent)

    def test_natural_combined_plan_only_proposes_then_requires_confirmation(self):
        steps=[{'step_id':'check','action':'check_missing_purpose','arguments':PERIOD,'depends_on':[]},
               {'step_id':'save','action':'manage_task','arguments':TASK,'depends_on':['check']}]
        replies=[reply(call('set_schedule',{'goal':'检查后保存下次待办','steps':steps,'stop_condition':'等待确认或已保存'})),
                 reply(call('check_missing_purpose',PERIOD)),reply(call('manage_task',TASK))]
        for accept in (False,True):
            seen=[]
            def confirm(p):
                self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)
                seen.append(p)
                return accept
            agent=self.agent(replies,management_confirmation=confirm)
            answer=agent.ask('检查 C001 2026 年 9 月还缺哪些发票用途，把没完成的事情记下来，下次继续。')
            self.assertEqual(len(seen),1,answer)
            self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],int(accept))
            self.assert_pairs(agent)
            self.assertLessEqual(agent.execution.model_requests,9)
            self.assertLessEqual(agent.execution.actual_tools,12)


if __name__=='__main__':
    unittest.main()
