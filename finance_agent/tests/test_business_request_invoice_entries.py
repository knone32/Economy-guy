"""Existing handlers + real RuleDecision/display owner; temporary fictional DBs."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from app.business_request import bind,BusinessRequestError
from app.business_request_entries import trusted_reference_catalog
from app.business_request_delivery import preflight,accept_result,assess_results,assess_selection,RequestDeliveryError
from app.cli_workspaces import import_workspace
from app.tool_registry import handle_tool
from app.references import record_display,invalidate_references
from app.answer_evidence import catalog
from app.tool_contracts import TOOL_SPECS,CAPABILITIES,SUPPORT_TOOLS,READ_ONLY_TOOLS

class InvoiceEntryTests(unittest.TestCase):
    def setUp(self):
        tmp=TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name);self.book=self.root/'fictional.sqlite'
        import_workspace(Path(__file__).parent/'fixtures/example.xlsx',self.book)
    def target(self,text):
        return {'target_id':'i1','object':'invoices','company_ids':['C001'],'company_quote':'C001',
            'periods':[[2026,9]],'period_quote':'2026年9月','seller':{'mode':'none','value':'','quote':text},
            'filters':[],'metrics':[{'operation':'details','field':'*','quote':text}],'group_by':[],'comparisons':[]}
    def req(self,text,target,**kwargs):
        return bind({'kind':'read','targets':[target],'unresolved':[]},actor='U001',book=self.book,turn_id='actual',request=text,**kwargs)
    def run_tool(self,request,name,**args):
        return handle_tool(name,json.dumps(args,ensure_ascii=False),'U001',self.book,business_request=request)
    def rule(self,reference=None):
        text='C001 2026年9月检查规则必填用途缺项的明细、张数和金额。'
        if reference:text+='按'+reference+'参考规则。'
        target=self.target('检查规则必填用途缺项的明细、张数和金额')
        target['purpose_check']={'criterion':'required_missing','rule_type':'purpose','quote':text}
        if reference:target['purpose_check']['reference_business_date']=reference
        target['metrics']=[{'operation':op,'field':field,'quote':'明细、张数和金额'} for op,field in [('details','*'),('count','*'),('sum','amount_cents')]]
        return self.req(text,target)
    def directory(self,coverage='all',page=None,sort_by='date'):
        text='C001 2026年9月发票目录'+('全部' if coverage=='all' else '第'+str(page)+'页')
        target=self.target('发票目录')
        target['directory']={'coverage':coverage,'sort_by':sort_by,'sort_order':'asc','quote':text}
        if page is not None:target['directory']['page']=page
        return self.req(text,target)
    def ref(self,kind='display_ordinal',ordinal=1,context=None,recent=None,trusted_scope=None,**override):
        text='查看刚才第1张发票详情' if kind=='display_ordinal' else '查看刚查询的发票详情'
        trusted=trusted_reference_catalog(actor='U001',book=self.book,reference_context=context,recent_context=recent)
        target={'target_id':'r1','object':'invoices','company_ids':[],'periods':[],
            'seller':{'mode':'none','value':'','quote':text},'filters':[],
            'metrics':[{'operation':'details','field':'*','quote':text}],'group_by':[],'comparisons':[],
            'reference':{'kind':kind,'quote':text}}
        if kind=='display_ordinal':target['reference']['ordinal']=ordinal
        target.update(override)
        return self.req(text,target,trusted_references=trusted,trusted_scope=trusted_scope),trusted
    def display(self):
        display='actual-display'
        anchors=record_display(self.book,'U001',display,[{'scope':{'company_id':'C001','year':2026,'month':9},
            'source':'list_invoices','keys':[{'company_id':'C001','invoice_no':'F002'}]}])
        return {'ordinal':1,'anchor_id':anchors[0]['anchor_id'],'scope':{'company_id':['C001'],'periods':[(2026,9)]},'display_ids':[display]}
    def test_tools_are_financial_capabilities_not_support(self):
        for name in ('check_missing_purpose','list_invoice_directory','resolve_invoice_reference','resolve_recent_invoice'):
            self.assertIn(name,CAPABILITIES);self.assertNotIn(name,SUPPORT_TOOLS)
            self.assertTrue(TOOL_SPECS[name].reads_financial_data)
            self.assertIn(name,READ_ONLY_TOOLS)
    def test_actual_rule_complete_set_and_fact_selection_cover_independent_metrics(self):
        req=self.rule();result=self.run_tool(req,'check_missing_purpose',company_id='C001',year=2026,month=9)
        self.assertEqual(result['status'],'SUCCESS',result)
        self.assertEqual(result['data']['count'],len(result['data']['missing_invoices']))
        self.assertTrue(assess_results(req,[('check_missing_purpose',result)])['complete'])
        facts=catalog([('check_missing_purpose',result)],{},'actual')
        self.assertTrue(assess_selection(req,['actual:r0.result'],facts,[('check_missing_purpose',result)])['complete'])
        self.assertFalse(assess_selection(req,[],facts,[('check_missing_purpose',result)])['complete'])
    def test_plain_blank_filter_cannot_become_required_missing_because_tool_was_selected(self):
        text='C001 2026年9月查看空用途发票';target=self.target('空用途发票')
        target['filters']=[{'field':'purpose','operator':'is_blank','value':'','quote':'空用途'}]
        req=self.req(text,target)
        with patch('app.tool_registry.check_missing_purpose',side_effect=AssertionError('must not read')):
            result=self.run_tool(req,'check_missing_purpose',company_id='C001',year=2026,month=9)
        self.assertEqual(result['status'],'TOOL_CAPABILITY_MISMATCH')
    def test_rule_reference_date_is_separate_from_target_month_and_wrong_tool_date_rejected(self):
        from app.provenance import ScopeProof
        req=self.rule('2026-10-01');values={'company_id':['C001'],'year':[2026],'month':[9],'periods':[(2026,9)]}
        good=handle_tool('check_missing_purpose',json.dumps({'company_id':'C001','year':2026,'month':9,'rule_business_date':'2026-10-01'}),
            'U001',self.book,business_request=req,expected_scope={'company_id':'C001','year':2026,'month':9},
            provenance=ScopeProof('U001',values,dict.fromkeys(values,'controlled_read_scope')))
        self.assertEqual(good['status'],'SUCCESS',good)
        self.assertEqual((good['data']['target_year'],good['data']['target_month']),(2026,9))
        self.assertEqual(good['data']['rule_business_date'],'2026-10-01');self.assertTrue(good['data']['reference_rule_screening'])
        bad=self.run_tool(req,'check_missing_purpose',company_id='C001',year=2026,month=8,rule_business_date='2026-10-01')
        self.assertEqual(bad['status'],'TOOL_CAPABILITY_MISMATCH')
    def test_rule_extra_seller_truncated_set_and_fake_rule_rejected(self):
        req=self.rule();good=self.run_tool(req,'check_missing_purpose',company_id='C001',year=2026,month=9)
        for field in ('count','rule'):
            bad=deepcopy(good)
            if field=='count':bad['data']['count']+=1
            else:bad['evidence']['rule']['version']='fake'
            with self.assertRaises(RequestDeliveryError):accept_result(req,'check_missing_purpose',bad,'U001',self.book)
        from dataclasses import replace
        seller=replace(req.targets[0].seller,mode='single',names=('actual',),value='actual')
        changed=replace(req,targets=(replace(req.targets[0],seller=seller),))
        with self.assertRaises(RequestDeliveryError):preflight(changed,'check_missing_purpose',{'company_id':'C001','year':2026,'month':9},'U001',self.book)
    def test_directory_page_only_and_sort_modes(self):
        for sort in ('date','amount','invoice_no'):
            req=self.directory('page',1,sort)
            result=self.run_tool(req,'list_invoice_directory',company_id='C001',year=2026,month=9,page=1,sort_by=sort,sort_order='asc')
            self.assertEqual(result['status'],'SUCCESS',result)
            self.assertTrue(assess_results(req,[('list_invoice_directory',result)])['complete'])
            self.assertEqual(result['data']['sort_by'],sort)
    def test_directory_all_multiple_pages_remains_partial_even_all_pages_collected(self):
        with closing(sqlite3.connect(self.book)) as db,db:
            row=list(db.execute("SELECT * FROM invoices WHERE company_id='C001' AND invoice_no='F002'").fetchone())
            row[1]='PUBLIC-EXTRA';db.execute('INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?)',row)
        req=self.directory();results=[]
        for page in (1,2):
            result=self.run_tool(req,'list_invoice_directory',company_id='C001',year=2026,month=9,page=page)
            self.assertIn(result['status'],('SUCCESS','NO_DATA'));results.append(('list_invoice_directory',result))
        self.assertGreater(results[0][1]['data']['total'],results[0][1]['data']['page_size'])
        self.assertFalse(assess_results(req,results)['complete'])
    def test_directory_all_single_full_page_can_complete_and_wrong_page_cannot(self):
        with closing(sqlite3.connect(self.book)) as db,db:db.execute("DELETE FROM invoices WHERE company_id='C001' AND invoice_no!='F002'")
        req=self.directory();result=self.run_tool(req,'list_invoice_directory',company_id='C001',year=2026,month=9,page=1)
        self.assertTrue(assess_results(req,[('list_invoice_directory',result)])['complete'])
        page=self.directory('page',2);bad=self.run_tool(page,'list_invoice_directory',company_id='C001',year=2026,month=9,page=1)
        self.assertEqual(bad['status'],'SCOPE_MISMATCH')
    def test_directory_plain_details_and_additional_filters_cannot_pass(self):
        text='C001 2026年9月发票明细';req=self.req(text,self.target('发票明细'))
        bad=self.run_tool(req,'list_invoice_directory',company_id='C001',year=2026,month=9,page=1)
        self.assertEqual(bad['status'],'TOOL_CAPABILITY_MISMATCH')
        req=self.directory()
        with self.assertRaises(RequestDeliveryError):preflight(req,'query_business_sql',{},'U001',self.book)
    def test_display_reference_uses_real_owner_anchor_and_fresh_row(self):
        context=self.display();req,trusted=self.ref(context=context)
        self.assertNotIn('invoice_no',trusted.public()[0]);self.assertEqual(req.targets[0].company_ids,('C001',))
        result=handle_tool('resolve_invoice_reference',json.dumps({'company_id':'C001','ordinal':1,'anchor_id':context['anchor_id']}),'U001',self.book,reference_context=context,business_request=req)
        self.assertEqual(result['status'],'SUCCESS',result);self.assertEqual(result['data']['invoice_no'],'F002')
        self.assertTrue(assess_results(req,[('resolve_invoice_reference',result)])['complete'])
    def test_missing_wrong_actor_or_retired_reference_and_model_key_cannot_authorize(self):
        with self.assertRaises(BusinessRequestError):self.ref()
        context=self.display()
        with self.assertRaises(BusinessRequestError):self.ref(context=context,ordinal=2)
        req,_=self.ref(context=context)
        with self.assertRaises(RequestDeliveryError):preflight(req,'resolve_invoice_reference',{'company_id':'C002','ordinal':1,'anchor_id':''},'U001',self.book)
        invalidate_references(self.book,'U001')
        with self.assertRaises(BusinessRequestError):self.ref(context=context)
        text='查看第1张';target={'target_id':'r','object':'invoices','reference':{'kind':'display_ordinal','ordinal':1,'quote':text,'invoice_no':'F002'}}
        with self.assertRaises(BusinessRequestError):self.req(text,target)
    def test_recent_queried_needs_runtime_actor_book_and_not_model_invoice(self):
        recent={'actor':'U001','workbook':str(self.book),'candidates':{'queried':{'company_id':'C001','invoice_no':'F002'}},'explicit':{}}
        req,_=self.ref(kind='recent_queried',recent=recent)
        result=handle_tool('resolve_recent_invoice',json.dumps({'source':'queried'}),'U001',self.book,recent_context=recent,business_request=req)
        self.assertEqual(result['status'],'SUCCESS',result)
        self.assertEqual(result['data']['invoice_no'],'F002')
        with self.assertRaises(BusinessRequestError):self.ref(kind='recent_queried',recent={**recent,'actor':'U002'})
        with self.assertRaises(BusinessRequestError):self.ref(kind='recent_modified',recent=recent)
    def test_explicit_reference_scope_conflict_and_acl_are_rejected(self):
        context=self.display()
        with self.assertRaises(BusinessRequestError):self.ref(context=context,company_ids=['C002'])
        text='C002 2026年9月目录';target=self.target('目录');target.update(company_ids=['C002'],company_quote='C002')
        target['directory']={'coverage':'page','page':1,'quote':'目录'}
        with self.assertRaises(BusinessRequestError):bind({'kind':'read','targets':[target],'unresolved':[]},actor='U002',book=self.book,turn_id='denied',request=text)
    def test_reference_cannot_overwrite_existing_trusted_scope(self):
        context=self.display()
        aligned={'company_id':['C001'],'periods':[(2026,9)],'year':[2026],'month':[9]}
        req,_=self.ref(context=context,trusted_scope=aligned)
        self.assertEqual(req.targets[0].company_ids,('C001',));self.assertEqual(req.targets[0].periods,((2026,9),))
        for conflict in ({'company_id':['C002']},{'periods':[(2026,10)]},{'year':[2027]},{'month':[10]}):
            with self.subTest(conflict=conflict):
                before=deepcopy(conflict)
                with self.assertRaises(BusinessRequestError) as raised:self.ref(context=context,trusted_scope=conflict)
                self.assertEqual(raised.exception.status,'SCOPE_MISMATCH')
                self.assertEqual(conflict,before)
