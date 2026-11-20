"""Native same-call read binding from current controlled catalog, no HTTP."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from app.agent import Agent, SYSTEM
from app.business_sql import BusinessSQL
from app.cli_workspaces import import_workspace
from app.provenance import ScopeProof, validate_scope
from app.tool_registry import handle_tool, TOOLS, validate_arguments
from tests.test_model_intent import call, final
from tests.test_sql_invoice_selection import snapshot


class ControlledReadScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.book = Path(temporary.name)/'fictional.sqlite3'
        import_workspace(Path(__file__).parent/'fixtures/example.xlsx',self.book)
        with closing(sqlite3.connect(self.book)) as db,db:
            db.execute("INSERT INTO companies(company_id,name,short_name) VALUES ('ZX-83','澄曜材料有限责任公司','澄曜')")
            db.execute("INSERT INTO permissions VALUES ('U002','ZX-83',1,0)")
            for month in (8,9):
                db.execute("""INSERT INTO invoices(company_id,invoice_no,invoice_date,seller_name,item_name,amount_cents,purpose,remark)
                    VALUES ('ZX-83',?,?, '虚构销售方','虚构项目',12345,'','')""",(f'P{month}',f'2037-{month:02d}-01'))
        self.request = '澄曜这边，37年先八月再九月，请比较发票金额。'
        self.binding = {'company_id':'ZX-83','periods':[{'year':2037,'month':8},{'year':2037,'month':9}],
                        'company_quote':'澄曜','period_quote':'37年先八月再九月'}
        self.sql = "SELECT substr(invoice_date,1,7) AS month,SUM(amount_cents) AS total_cents FROM invoices WHERE company_id='ZX-83' GROUP BY 1 ORDER BY 1"

    def query(self, binding=None, request=None):
        proof = ScopeProof('U002',{}, {})
        workspace = BusinessSQL(self.book,'U002',proof,request=request or self.request)
        self.addCleanup(workspace.close)
        args = {'sql':self.sql}
        if binding is not None:
            args['read_scope'] = binding
        result = handle_tool('query_business_sql',json.dumps(args), 'U002',self.book,sql_workspace=workspace)
        return result,workspace

    def test_native_schema_and_handler_accept_registered_alias_and_unique_short_year(self):
        before = snapshot(self.book)
        schema = next(t['function']['parameters'] for t in TOOLS if t['function']['name']=='query_business_sql')
        self.assertIn('read_scope',schema['properties'])
        self.assertEqual(schema['required'],['sql'])
        self.assertEqual(validate_arguments('query_business_sql',json.dumps({'sql':self.sql,'read_scope':self.binding}))['read_scope'],self.binding)
        result,workspace = self.query(self.binding)
        self.assertEqual(result['status'],'SUCCESS',result)
        self.assertEqual(result['data']['rows'],[('2037-08',12345),('2037-09',12345)])
        self.assertEqual(workspace.proof.values['company_id'],['ZX-83'])
        self.assertEqual(workspace.proof.sources['company_id'],'controlled_read_scope')
        denied_write = validate_scope(workspace.proof,'U002','prepare_invoice_update',
                         {'company_id':'ZX-83','invoice_no':'P8'})
        self.assertEqual(denied_write['status'],'AMBIGUOUS')
        self.assertIn('company_id',denied_write['evidence']['missing_fields'])
        self.assertEqual(snapshot(self.book),before)

    def test_sql_only_still_has_no_scope_and_unregistered_abbreviation_is_rejected(self):
        result,_ = self.query()
        self.assertEqual(result['status'],'AMBIGUOUS')
        bad = deepcopy(self.binding);bad['company_quote']='澄'
        result,_ = self.query(bad)
        self.assertEqual(result['status'],'AMBIGUOUS',result)

    def test_alias_collision_century_collision_and_missing_current_quote_reject(self):
        for mode in ('alias','year','quote','unauthorized'):
            with self.subTest(mode=mode),closing(sqlite3.connect(self.book)) as db,db:
                binding = deepcopy(self.binding)
                if mode=='alias':
                    db.execute("INSERT INTO companies VALUES ('OTHER-4','澄曜服务公司','澄曜')")
                    db.execute("INSERT INTO permissions VALUES ('U002','OTHER-4',1,0)")
                elif mode=='year':
                    db.execute("""INSERT INTO invoices SELECT company_id,invoice_no||'X',replace(invoice_date,'2037','2137'),
                        seller_name,item_name,amount_cents,purpose,remark FROM invoices WHERE company_id='ZX-83'""")
                elif mode=='quote':
                    binding['period_quote']='37年八月九月'
                else:
                    binding['company_id']='C002';binding['company_quote']='乙企业'
                db.commit()
                result,_ = self.query(binding)
                self.assertIn(result['status'],{'AMBIGUOUS','DENIED','SCOPE_MISMATCH'},result)
                if mode=='alias':
                    db.execute("DELETE FROM permissions WHERE company_id='OTHER-4'");db.execute("DELETE FROM companies WHERE company_id='OTHER-4'")
                if mode=='year':db.execute("DELETE FROM invoices WHERE invoice_date LIKE '2137-%'")

    def test_model_sees_current_acl_catalog_without_static_fixture_mapping(self):
        seen = []
        def model(messages,tools):
            seen.append(messages)
            return call('query_business_sql',{'sql':self.sql,'read_scope':self.binding}) if len(seen)==1 else final()
        agent = Agent('U002',self.book,model,mode='mock')
        agent.ask(self.request)
        result = next(r for name,r in agent.last_response['tool_results'] if name=='query_business_sql')
        self.assertEqual(result['status'],'SUCCESS',result)
        self.assertNotIn('甲企业=C001',SYSTEM)
        context = json.loads(next(m['content'] for m in seen[0] if m.get('name')=='context_data'))
        catalog = context['read_catalog']['companies']
        self.assertIn('ZX-83',{c['company_id'] for c in catalog})
        self.assertNotIn('C002',{c['company_id'] for c in catalog})
        self.assertNotIn('controlled_read_scope',agent.context.sources.values())

    def test_legacy_read_sidecar_cannot_create_unverified_sql_scope(self):
        target = {'company_id':'ZX-83','year':2037,'month':9}
        intent = {'action':'read','target':target,'sources':{
            'company_id':{'kind':'current','text':'澄'},
            'year':{'kind':'current','text':'37年'},'month':{'kind':'current','text':'九月'}}}
        replies = iter((call('query_business_sql',{'sql':self.sql},
            content=json.dumps({'intent':intent},ensure_ascii=False)),final()))
        agent = Agent('U002',self.book,lambda *_:next(replies),mode='mock')
        agent.ask(self.request)
        result = next(r for name,r in agent.last_response['tool_results'] if name=='query_business_sql')
        self.assertEqual(result['status'],'AMBIGUOUS')

    def test_registered_id_cannot_be_taken_from_a_longer_unregistered_identifier(self):
        binding = deepcopy(self.binding);binding['company_quote']='ZX-83'
        result,_ = self.query(binding,request='ZX-83X，37年先八月再九月，请比较发票金额。')
        self.assertEqual(result['status'],'AMBIGUOUS',result)

    def test_existing_trusted_sql_only_scope_remains_supported(self):
        replies = iter((call('query_business_sql',{'sql':'SELECT COUNT(*) AS cnt FROM invoices'}),final()))
        agent = Agent('U002',self.book,lambda *_:next(replies),mode='mock')
        agent.ask('C001 2026年9月，统计发票张数。')
        self.assertTrue(any(name=='query_business_sql' and result['status']=='SUCCESS'
                            for name,result in agent.last_response['tool_results']))
