"""Call-local SQL identity sources never grant write authority."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import app.agent as runtime
from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.provenance import SOURCES, validate_scope
from tests.test_answer_evidence import facts, final


class SqlReadIdentityTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.book = Path(tmp.name)/'fictional.sqlite3'
        import_workspace(Path(__file__).parent/'fixtures/example.xlsx', self.book)
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute("UPDATE invoices SET invoice_no='QX-73195' WHERE company_id='C001' AND invoice_no='F008'")
        self.proofs, self.contexts = [], []

    def sql(self, columns='*', condition="invoice_no LIKE '%731%'", suffix=''):
        return (f"SELECT {columns} FROM invoices WHERE {condition} "
                "AND invoice_date >= '2026-09-01' AND invoice_date < '2026-10-01' " + suffix)

    def run_case(self, statements, *, target=('C001','QX-73195'), mutate=None, actor='U001', workspace=None,
                 request='查C001 2026年9月票号含731的发票，看看当前用途和备注。'):
        step = 0
        def model(messages, tools):
            nonlocal step
            step += 1
            if step <= len(statements):
                name, args = 'query_business_sql', {'sql':statements[step-1]}
            elif step == len(statements)+1:
                name, args = 'get_invoice', dict(zip(('company_id','invoice_no'),target))
            else:
                refs = [f['ref'] for f in facts(messages) if f.get('label')=='发票编号']
                return final(answer=refs or [f['ref'] for f in facts(messages) if f.get('type')=='result'][:1])
            return {'role':'assistant','tool_calls':[{'id':'call'+str(step),'type':'function',
                'function':{'name':name,'arguments':json.dumps(args)}}]}
        agent = Agent(actor,self.book,model,mode='mock',trace_path=self.book.with_suffix('.jsonl'))
        real = runtime.handle_tool
        def dispatch(name,*args,**kwargs):
            if name=='get_invoice':
                self.proofs.append(deepcopy(kwargs['provenance']))
                self.contexts.append(deepcopy(agent.context.proof().values))
            result=real(name,*args,**kwargs)
            if name=='query_business_sql' and mutate: mutate(result)
            return result
        with closing(sqlite3.connect(self.book)) as db:
            before=db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no').fetchall()
        with patch.object(runtime,'handle_tool',side_effect=dispatch): answer=agent.ask(request,read_workspace=workspace)
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(before,db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no').fetchall())
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)
        self.assertEqual(agent.write_receipt['status'],'NOT_SUBMITTED')
        self.assertFalse(agent.update_session.drafts)
        result=next((r for n,r in agent.last_response['tool_results'] if n=='get_invoice'),None)
        return agent,answer,result

    def test_original_full_row_fresh_read_is_readonly_and_call_local(self):
        agent,answer,r=self.run_case([self.sql()])
        self.assertEqual(r['status'],'SUCCESS');self.assertIn('QX-73195',answer)
        proof=self.proofs[-1]
        self.assertEqual(proof.sources['invoice_no'],'controlled_read_scope')
        self.assertNotIn(proof.sources['invoice_no'],SOURCES)
        self.assertNotIn('invoice_no',self.contexts[-1])
        self.assertNotIn('invoice_no',agent.context.proof().values)
        self.assertEqual(validate_scope(proof,'U001','prepare_invoice_update',
            {'company_id':'C001','invoice_no':'QX-73195'})['status'],'AMBIGUOUS')

    def test_two_original_key_columns_can_be_fresh_read(self):
        _,_,r=self.run_case([self.sql('company_id, invoice_no')]);self.assertEqual(r['status'],'SUCCESS')

    def test_two_different_singletons_remain_ambiguous(self):
        _,_,r=self.run_case([self.sql(),self.sql(condition="invoice_no='F009'")])
        self.assertNotEqual(r['status'],'SUCCESS')

    def test_multiple_rows_remain_ambiguous(self):
        _,_,r=self.run_case([self.sql(condition='1=1')]);self.assertNotEqual(r['status'],'SUCCESS')

    def test_paging_aggregation_literal_alias_and_missing_company_fail_closed(self):
        for statement in (self.sql(suffix='LIMIT 1'),self.sql(suffix='LIMIT 1 OFFSET 0'),
                self.sql('company_id, invoice_no, COUNT(*)',suffix='GROUP BY company_id,invoice_no'),
                self.sql("company_id, 'QX-73195' AS invoice_no"),self.sql('invoice_no')):
            with self.subTest(statement=statement):
                _,_,r=self.run_case([statement]);self.assertNotEqual(r['status'],'SUCCESS')

    def test_unproved_truncated_or_forged_projection_metadata_fail_closed(self):
        mutations=[lambda r:r['evidence']['query_scope'].__setitem__('sql_sha256','wrong-hash'),
            lambda r:r['data'].__setitem__('sql',r['data']['sql']+' LIMIT 1'),
            lambda r:r['data'].__setitem__('truncated',True),
            lambda r:r['evidence']['query_scope'].__setitem__('status','UNKNOWN'),
            lambda r:r['evidence']['query_scope'].__setitem__('query_set_complete',False),
            lambda r:r['evidence']['query_scope'].__setitem__('display_truncated',True),
            lambda r:r['evidence']['query_scope']['columns'][1].__setitem__('field','purpose')]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                _,_,r=self.run_case([self.sql()],mutate=mutate);self.assertNotEqual(r['status'],'SUCCESS')

    def test_mismatching_company_or_number_cannot_use_singleton(self):
        for target in (('C001','F009'),('C002','QX-73195')):
            with self.subTest(target=target):
                _,_,r=self.run_case([self.sql()],target=target);self.assertNotEqual(r['status'],'SUCCESS')

    def test_current_explicit_invoice_and_period_win(self):
        for request in ('查C001 2026年9月F009当前用途和备注。','查C001 2026年8月票号含731的发票当前用途和备注。'):
            with self.subTest(request=request):
                _,_,r=self.run_case([self.sql()],request=request)
                self.assertTrue(r is None or r['status']!='SUCCESS')

    def test_old_turn_sql_cannot_supply_current_identity(self):
        stage=0
        def model(messages,tools):
            nonlocal stage
            stage+=1
            if stage in (1,3):
                name,args=('query_business_sql',{'sql':self.sql()}) if stage==1 else ('get_invoice',{'company_id':'C001','invoice_no':'QX-73195'})
                return {'role':'assistant','tool_calls':[{'id':'call'+str(stage),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}
            return final(answer=[f['ref'] for f in facts(messages) if f.get('type')=='result'][:1])
        agent=Agent('U001',self.book,model,mode='mock',trace_path=self.book.with_suffix('.jsonl'))
        agent.ask('查C001 2026年9月票号含731的发票。')
        agent.ask('另查C001 2026年9月票号含731的当前备注。')
        results=[r for n,r in agent.last_response['tool_results'] if n=='get_invoice']
        self.assertTrue(results);self.assertNotEqual(results[-1]['status'],'SUCCESS')

    def test_repeated_singleton_same_key_remains_unique(self):
        _,_,r=self.run_case([self.sql(),self.sql('company_id, invoice_no')])
        self.assertEqual(r['status'],'SUCCESS')

    def test_cross_company_singletons_cannot_choose_one(self):
        statements=[self.sql(condition="company_id='C001' AND invoice_no LIKE '%731%'"),
                    self.sql(condition="company_id='C002' AND invoice_no LIKE '%008%'")]
        agent,_,r=self.run_case(statements,request='查C001和C002 2026年9月票号含731或008的发票当前备注。')
        sql_results=[r for n,r in agent.last_response['tool_results'] if n=='query_business_sql']
        self.assertEqual([r['status'] for r in sql_results],['SUCCESS','SUCCESS'])
        self.assertNotEqual(r['status'],'SUCCESS')

    def test_actual_fresh_get_still_rechecks_revoked_acl(self):
        def revoke(result):
            with closing(sqlite3.connect(self.book)) as db,db:
                db.execute("UPDATE permissions SET can_read=0 WHERE user_id='U001' AND company_id='C001'")
        _,_,r=self.run_case([self.sql()],mutate=revoke)
        self.assertEqual(r['status'],'DENIED')

    def test_current_explicit_unreadable_company_is_not_retargeted(self):
        _,_,r=self.run_case([self.sql()],actor='U002',request='查C002 2026年9月票号含731的发票当前备注。')
        self.assertTrue(r is None or r['status']!='SUCCESS')

    def test_denied_background_does_not_block_independent_current_sql_detail(self):
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute("UPDATE companies SET name='北湾数据中心',short_name='北湾' WHERE company_id='C002'")
        agent,_,r=self.run_case([self.sql()],actor='U002',workspace=('C001',2026,9),
            request='北湾不查了，只看C001 2026年9月票号含731的发票当前用途和备注。')
        self.assertEqual(r['status'],'SUCCESS')
        self.assertEqual((r['data']['company_id'],r['data']['invoice_no']),('C001','QX-73195'))
        self.assertEqual(self.proofs[-1].sources['invoice_no'],'controlled_read_scope')
        self.assertNotIn('invoice_no',agent.context.proof().values)

    def test_only_unreadable_company_cannot_borrow_selected_workspace_for_sql_detail(self):
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute("UPDATE companies SET name='北湾数据中心',short_name='北湾' WHERE company_id='C002'")
        agent,_,r=self.run_case([self.sql()],actor='U002',workspace=('C001',2026,9),
            request='查北湾2026年9月票号含731的发票当前用途和备注。')
        self.assertEqual(agent.last_response['execution']['stop_reason'],'DENIED')
        self.assertTrue(r is None or r['status']!='SUCCESS')
        self.assertFalse(any(outcome['status']=='SUCCESS' for _,outcome in agent.last_response['tool_results']))

    def test_only_unknown_company_cannot_borrow_selected_workspace_for_sql_detail(self):
        agent,_,r=self.run_case([self.sql()],actor='U002',workspace=('C001',2026,9),
            request='查C997 2026年9月票号含731的发票当前用途和备注。')
        self.assertEqual(agent.last_response['execution']['stop_reason'],'SCOPE_MISMATCH')
        self.assertTrue(r is None or r['status']!='SUCCESS')
        self.assertFalse(any(outcome['status']=='SUCCESS' for _,outcome in agent.last_response['tool_results']))
