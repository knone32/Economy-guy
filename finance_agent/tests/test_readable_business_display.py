"""Isolated presentation/cancel checks only; zero API, no approved writes."""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from textual.widgets import Collapsible, Select, Static
from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.invoice_batch import run_invoice_batch
from app.model_config import DEFAULT_TEMPLATE
from app.responses import render_information, render_stopped, render_query_conditions
from app.rules import resolve_rule
from app.tui import AgentWorkspace
from app.tui_screens import Approval
from tests import test_business_request_delivery as delivery_fixture


class ReadableBusinessDisplayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp=TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.book=self.root/'isolated-preview.sqlite'
        import_workspace(Path(__file__).parent/'fixtures/example.xlsx',self.book)
        with closing(sqlite3.connect(self.book)) as db,db:
            db.execute('DELETE FROM invoices')
            db.execute('INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?)',
                ('C001','PV-730','2026-11-03','隔离验收销售方','隔离预览',190000,'巡检备件','旧备注'))
        self.agent=Agent('U001',self.book,lambda *_:self.fail('No model during presentation checks'),
                         mode='mock',trace_path=self.root/'trace.jsonl')

    def preview(self, *, rule=False):
        if rule:
            with closing(sqlite3.connect(self.book)) as db,db:
                db.execute("UPDATE invoices SET purpose='' WHERE invoice_no='PV-730'")
        field='purpose' if rule else 'remark';value='巡检备件' if rule else '复核完成'
        label='用途' if field=='purpose' else '备注'
        message=f'C001 2026年11月PV-730这张发票的{label}改为“{value}”。'
        plan={'company_id':'C001','year':2026,'month':11,'invoice_nos':('PV-730',),
              'field':field,'new_value':value,'mode':'item','excluded':(),
              'source_request':message,'actor':self.agent.user_id,'workbook':str(self.book),'turn':self.agent.trace_id}
        if rule:
            with closing(sqlite3.connect(self.book)) as db:
                db.row_factory=sqlite3.Row
                decision=resolve_rule(db,'U001','C001','purpose','2026-09-01')
            plan['rule_reference']={'business_date':'2026-09-01','rule_id':decision.rule_id,
                'version':decision.version,'params':decision.params,'cohort':True,'subset_filters':(), 'screening':True}
        digest=hashlib.sha256(self.book.read_bytes()).hexdigest();seen=[]
        with patch.object(self.agent,'commit_update',side_effect=AssertionError('No confirmed writes')) as commit:
            status,_=run_invoice_batch(self.agent,message,plan,approve_batch=lambda *_:self.fail('Item only'),
                approve_item=lambda body:seen.append(body) or False,checkpoint=lambda *_:self.fail('No confirmation'))
        commit.assert_not_called();self.assertEqual(status,'CANCELLED');self.assertEqual(len(seen),1)
        self.assertEqual(hashlib.sha256(self.book.read_bytes()).hexdigest(),digest)
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)
        self.assertFalse(self.agent.update_session.drafts);self.assertFalse(self.agent.update_session.confirmations)
        return seen[0]

    def test_user_instruction_preview_answers_five_questions_without_technical_details(self):
        body=self.preview()
        for text in ('甲企业','2026 年 11 月','PV-730','备注由“旧备注”改为“复核完成”',
                     '您指定','重新读取','仅这一张','用途','不作修改','尚未保存'):
            self.assertIn(text,body)
        for technical in ('原始要求','C001','request_id','SQL','法律','法规'):
            self.assertNotIn(technical,body)
        self.assertIn('原始要求',body.technical_details)
        self.assertIn('C001',body.technical_details)

    def test_rule_selection_explains_name_version_condition_and_actual_match_without_inventing_law(self):
        body=self.preview(rule=True)
        for text in ('甲企业发票用途规则','v2.0','所有发票用途必填','用途未填写','实际命中',
                     '由您明确提供','规则不推断','不代表目标月份正式合规认定'):
            self.assertIn(text,body)
        self.assertNotIn('法律',body);self.assertIn('R002',body.technical_details)

    def test_query_facts_and_partial_reply_keep_numbers_and_limits_without_sql_or_json(self):
        f=delivery_fixture.BusinessRequestDeliveryTests(methodName='runTest');f.setUp();self.addCleanup(f.doCleanups)
        from app.answer_evidence import catalog,select
        from app.business_request_delivery import accept_result,verified_statistics_answer,assess_selection
        from app.tool_registry import handle_tool
        request=f.requirement();result=accept_result(request,'query_business_sql',f.actual_result(f.sql),'U002',f.book)
        results=[('query_business_sql',result)];original=deepcopy(result);facts=catalog(results,{},'readable')
        selected=verified_statistics_answer(request,facts,results)
        self.assertTrue(assess_selection(request,selected,facts,results)['complete'])
        text=select(selected,facts)+'\n'+render_stopped(results,'WAITING_CONFIRMATION')
        for value in ('1797.00','2357.00','1 张','销售方','玄野服务有限公司','展会物料','尚未保存'):
            self.assertIn(value,text)
        for machine in ('SELECT','seller_name','invoice_date','"columns"','"tool"','current_sqlite'):
            self.assertNotIn(machine,text)
        self.assertEqual(original,result)
        self.assertEqual(render_query_conditions({'conditions':[{'field':'amount_cents','operator':'IN','value':[10000,235700]}]}),
                         '金额属于“100.00 元、2357.00 元”')
        detail=handle_tool('get_invoice',json.dumps({'company_id':'C001','invoice_no':'PV-730'}),'U001',self.book)
        readable=render_information([('get_invoice',detail)])
        self.assertIn('备注：旧备注',readable);self.assertNotIn('"remark"',readable)

    async def test_original_confirmation_layout_cancel_and_collapsed_details(self):
        body=self.preview();app=AgentWorkspace(self.book,DEFAULT_TEMPLATE,self.root/'missing-profile.json',model=lambda *_:self.fail('No API'))
        app.mode='mock';answers=[]
        async with app.run_test(size=(160,48)) as pilot:
            app.screen.query_one('#login-user',Select).value='U001';await pilot.click('#sign-in');await pilot.pause()
            app.push_screen(Approval('逐张确认发票修改',body,'确认本张',cancel='终止',skip=True),answers.append)
            await pilot.pause()
            screen=app.screen;self.assertIsInstance(screen,Approval)
            self.assertEqual(screen.focused.id,'cancel')
            details=screen.query_one('#approval-technical',Collapsible);self.assertTrue(details.collapsed)
            summary=screen.query_one('#approval-content').query_one(Static)
            self.assertIn('影响范围',str(summary.renderable));self.assertNotIn('原始要求',str(summary.renderable))
            for control in ('#cancel','#approve'):
                region=screen.query_one(control).region
                self.assertGreater(region.width,0);self.assertLessEqual(region.bottom,48)
            if output:=os.environ.get('ECONOMY_DISPLAY_ARTIFACT_DIR'):
                destination=Path(output);destination.mkdir(parents=True,exist_ok=True)
                (destination/'preview-collapsed.svg').write_text(app.export_screenshot(),encoding='utf-8')
                details.collapsed=False;await pilot.pause()
                (destination/'preview-technical.svg').write_text(app.export_screenshot(),encoding='utf-8')
            await pilot.press('escape');await pilot.pause()
            self.assertEqual(answers,[False])
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT remark,purpose FROM invoices').fetchone(),('旧备注','巡检备件'))
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)
