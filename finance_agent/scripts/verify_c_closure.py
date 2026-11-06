"""真实CLI验收驱动，仅限本阶段artifacts虚构库；不替换模型、工具或业务结果。"""
import argparse
from contextlib import closing, redirect_stdout
from dataclasses import asdict
import hashlib
import inspect
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'finance_agent'))
from tests.closure_approval import C2_REQUEST, SimulatedApproval, digest, facts

STEPS={
    'create': [('C1-CLOSURE-01','检查C001 2026年9月哪些发票还没有填写必填用途，不要猜用途。'),('C2-SIMULATED-APPROVAL-01',C2_REQUEST)],
    'resume': [('C3-CLOSURE-01','继续我在C001 2026年9月尚未完成的用途待办，核对现在还缺哪些发票。'),('C4-CLOSURE-01','把甲企业 F002 的用途改为项目资料核对。'),('C5-CLOSURE-01','现在还剩哪些没补完？接下来应该处理什么？')],
    'restart': [('C6-CLOSURE-01','查询我在C001 2026年9月尚未完成的任务和当前缺失用途。')],
}


def snapshot(db):
    with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row
        return {table:[dict(r) for r in c.execute('SELECT * FROM '+table+' ORDER BY rowid')]
                for table in ['invoices','bank_transactions','invoice_audit','tasks','preferences','rules','permissions']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=STEPS,required=True)
    parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args();folder=args.directory.resolve()
    if not folder.is_relative_to(ROOT/'artifacts/s4_p0c_closure'):
        raise ValueError('仅允许本轮忽略目录中的虚构验收库')
    manifest=json.loads((folder/'manifest.json').read_text('utf-8'))
    criteria=ROOT/'docs/verification/stage4/S4-P0C-CLOSURE-CASES.md'
    policy_file=ROOT/'finance_agent/tests/closure_approval.py'
    for path,key in [(criteria,'criteria_sha256'),(policy_file,'approval_policy_sha256')]:
        if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest[key]:
            raise ValueError('冻结准则发生变化，拒绝Live')
    db=folder/'workflow.sqlite'
    output=folder/(args.stage+'_results.json')
    if output.exists():
        raise FileExistsError('不覆盖首次结果；诊断重跑必须另建ID/输出')
    import main as cli
    import app.agent as agent_module
    original=agent_module.Agent
    agents=[];results=[];current=None;position=0;policy=SimulatedApproval();console=io.StringIO()
    steps=STEPS[args.stage]
    def factory(*a,**kw):
        agent=original(*a,**kw);agents.append(agent);return agent
    def finish():
        nonlocal current
        if current is None:return
        agent=agents[-1]
        current.update(after=snapshot(db),response=agent.last_response,receipt=agent.write_receipt,
                       trace_id=agent.trace_id,end_drafts=len(agent.update_session.drafts),
                       end_confirmations=len(agent.update_session.confirmations),oracle=facts(db))
        results.append(current);current=None
    def prompt_input(prompt):
        nonlocal current,position
        agent=agents[-1]
        if prompt=='你：':
            finish()
            if position==len(steps):return 'exit'
            case,text=steps[position];position+=1
            current=dict(case=case,text=text,process_id=os.getpid(),before=snapshot(db),
                         start_drafts=len(agent.update_session.drafts),start_confirmations=len(agent.update_session.confirmations),
                         confirmations=[],code_sha=manifest['code_sha'])
            print('SIMULATED_TEST_USER:',text)
            return '/edit '+text if case=='C4-CLOSURE-01' else text
        if '核对原始要求及实际对象/内容' in prompt:
            frame=inspect.currentframe();proposal=None
            while frame:
                if frame.f_code.co_name=='confirm_long_term':
                    proposal=frame.f_locals['proposal'];break
                frame=frame.f_back
            if proposal is None:raise RuntimeError('未找到实际可信CLI提案')
            if current['case']=='C2-SIMULATED-APPROVAL-01':
                decision=policy.review(proposal,db,agent.user_id,agent.management_proposals.turn_id)
            else:
                # 仅恢复当前SQLite中本用户该企业的唯一任务，不更改说明/目标。
                state=snapshot(db);owned=[r for r in state['tasks'] if r['user_id']=='U001' and r['company_id']=='C001' and r['status'] in {'ACTIVE','WAITING_USER','PAUSED'}]
                p=proposal['proposal'];rid=proposal['request_id']
                expected=dict(company_id='C001',action='resume',task_id=owned[0]['task_id'] if len(owned)==1 else None,year=2026,month=9,note='')
                fp=digest(['U001','task','resume',current['text'],agent.management_proposals.turn_id,rid,p,proposal['current']])
                approved=(len(owned)==1 and p==expected and proposal['fingerprint']==fp and current['case']=='C3-CLOSURE-01')
                decision=dict(approved=approved,confirmation_source='SIMULATED_TEST_USER',reasons=[] if approved else ['not_exact_current_task_resume'])
            answer='confirm '+proposal['request_id'] if decision['approved'] else '取消'
            current['confirmations'].append(dict(source='SIMULATED_TEST_USER',proposal=proposal,decision=decision,before=snapshot(db),input=answer))
            print('SIMULATED_APPROVAL_CHECK:',json.dumps(decision,ensure_ascii=False))
            return answer
        if prompt=='最终确认：':
            draft=next(iter(agent.update_session.drafts.values()));payload=asdict(draft)
            expected=dict(actor='U001',company_id='C001',invoice_no='F002',field='purpose',new_value='项目资料核对')
            approved=current['case']=='C4-CLOSURE-01' and all(payload.get(k)==v for k,v in expected.items())
            state=snapshot(db)
            approved=approved and not state['invoice_audit'] and any(r['user_id']=='U001' and r['company_id']=='C001' and r['can_modify'] for r in state['permissions'])
            answer='confirm '+draft.request_id if approved else '取消'
            current['confirmations'].append(dict(source='SIMULATED_TEST_USER',draft=payload,fingerprint=draft.fingerprint(),approved=approved,before=state,input=answer))
            return answer
        if '本条是补充该修改' in prompt:return '新主题'
        raise RuntimeError('未冻结的可信交互入口，停止而不自动确认')
    argv=['main.py','--db',str(db),'--profiles-local',str(folder/'profiles.json'),'chat','--mode','live','--user','U001','--profile','shared-flash','--trace',str(folder/(args.stage+'_trace.jsonl'))]
    try:
        with patch('app.agent.Agent',side_effect=factory),patch('builtins.input',side_effect=prompt_input),patch.object(sys,'argv',argv),redirect_stdout(console):
            cli.main()
    finally:
        finish();output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        (folder/(args.stage+'_console.txt')).write_text(console.getvalue(),encoding='utf-8')
    for r in results:
        print(json.dumps(dict(case=r['case'],process=r['process_id'],trace_id=r['trace_id'],stop=r['response']['execution']['stop_reason'],receipt=r['receipt']['status'],missing=len(r['oracle']['missing']),tasks=len(r['after']['tasks']),audit=len(r['after']['invoice_audit'])),ensure_ascii=True))


if __name__=='__main__':main()
