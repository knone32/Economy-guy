"""Original three blocked entry paths, real Agent/Registry, no API or writes."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.tool_registry import handle_tool
from app.tui import AgentWorkspace
from tests.test_answer_evidence import facts, final, tool


class ReadEntryIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.book=Path(temp.name)/'fictional.sqlite'
        import_workspace(Path(__file__).parent/'fixtures/example.xlsx',self.book)
        with closing(sqlite3.connect(self.book)) as db:
            self.before=list(db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no'))

    def tearDown(self):
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(self.before,list(db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no')))
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)

    def target(self,text):
        return {'target_id':'i','object':'invoices','company_ids':['C001'],'company_quote':'C001',
            'periods':[[2026,9]],'period_quote':'2026年9月',
            'seller':{'mode':'none','value':'','quote':text},
            'metrics':[{'operation':'details','field':'*','quote':text}]}

    def execute(self,text,target,name,args,prepare=None):
        seen=[]
        def model(context,tools):
            seen.append((deepcopy(context),deepcopy(tools)))
            if len(seen)==1:
                self.assertEqual(tools,[])
                return {'role':'assistant','content':json.dumps({'kind':'read','targets':[target],'unresolved':[]},ensure_ascii=False)}
            if not any(m.get('role')=='tool' for m in context):
                self.assertIn(name,{t['function']['name'] for t in tools})
                return tool(name,**args)
            return final(answer=[next(f['ref'] for f in facts(context) if f['type']=='result')])
        agent=Agent('U001',self.book,model,mode='mock',trace_path=self.book.parent/'entry.jsonl')
        if prepare:prepare(agent)
        text_out=agent.ask(text)
        results=agent.last_response['tool_results']
        self.assertEqual([name for name,_ in results],[name],agent.last_response)
        self.assertEqual(results[0][1]['status'],'SUCCESS',agent.last_response)
        self.assertTrue(agent.last_response['business_request_final_coverage']['complete'],agent.last_response)
        data,evidence=results[0][1]['data'],results[0][1]['evidence']
        if name=='list_invoice_directory':
            route=AgentWorkspace.directory_scope(evidence,data,'SUCCESS')
            card=AgentWorkspace.directory_summary(SimpleNamespace(invoice_lines=AgentWorkspace.invoice_lines),[data],route)
        else:
            card=AgentWorkspace.business_card(name,data,evidence)
        self.assertTrue(card)
        self.assertTrue(text_out)
        self.assertFalse(agent.update_session.drafts);self.assertFalse(agent.update_session.confirmations)
        return seen,agent

    def test_rule_missing_tool_is_reachable_and_delivers_its_bound_view(self):
        text='C001 2026年9月检查规则必填用途缺项明细。';target=self.target('规则必填用途缺项明细')
        target['purpose_check']={'criterion':'required_missing','rule_type':'purpose','quote':'规则必填用途缺项明细'}
        self.execute(text,target,'check_missing_purpose',{'company_id':'C001','year':2026,'month':9})

    def test_directory_page_is_reachable_without_becoming_all_details(self):
        text='C001 2026年9月发票目录第1页。';target=self.target('发票目录第1页')
        target['directory']={'coverage':'page','page':1,'quote':'发票目录第1页'}
        _,agent=self.execute(text,target,'list_invoice_directory',{'company_id':'C001','year':2026,'month':9,'page':1})
        self.assertEqual(agent.business_request.targets[0].directory.coverage,'page')

    def test_actual_display_witness_reaches_semantics_binding_and_original_handler(self):
        text='请查看刚才展示的第1张发票详情。'
        target={'target_id':'r','object':'invoices','company_ids':[],'periods':[],
            'seller':{'mode':'none','value':'','quote':'发票详情'},
            'metrics':[{'operation':'details','field':'*','quote':'发票详情'}],
            'reference':{'kind':'display_ordinal','ordinal':1,'quote':'第1张'}}
        def display(agent):
            result=handle_tool('get_invoice',json.dumps({'company_id':'C001','invoice_no':'F002'}),'U001',self.book)
            self.assertTrue(AgentWorkspace.business_card('get_invoice',result['data'],result['evidence']))
            agent.trace_id='actual-program-display'
            self.assertTrue(agent.record_query_display([('get_invoice',result)]))
        seen,agent=self.execute(text,target,'resolve_invoice_reference',{'company_id':'C001','ordinal':1,'anchor_id':''},display)
        candidates=json.loads(seen[0][0][1]['content'])['business_definition']['trusted_invoice_references']
        self.assertEqual(candidates[0]['ordinal'],1)
        self.assertNotIn('invoice_no',candidates[0]);self.assertNotIn('anchor_id',candidates[0])
        self.assertEqual(agent.business_request.targets[0].reference.invoice_no,'F002')
