"""Finite configured terminology reaches independent input, zero API."""
from contextlib import closing
from copy import deepcopy
import json,sqlite3,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from app.assistant_config import configure,refresh_assistant
from app.business_request import messages,BUSINESS_FIELDS,DEFINITION,bind,BusinessRequestError
from app.cli_workspaces import import_workspace
from app.skill_business_terms import semantic_skill_terms

class SkillBusinessTermsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.book=Path(self.tmp.name)/'book.sqlite'
  import_workspace(Path(__file__).parent/'fixtures/example.xlsx',self.book)
  self.term={'term':'检核口径','object':'invoices','metrics':[{'operation':'sum','field':'amount_cents'},{'operation':'count','field':'*'}]}
  self.body={'name':'公开虚构定义','tools':['query_business_sql'],'steps':['PRIVATE_STEP_SENTINEL'],'business_terms':[self.term]}
  self.agent=SimpleNamespace(assistant_id='a',db_path=self.book,user_id='U001',messages=[{'role':'system','content':'SYSTEM_SENTINEL'}],trace=lambda *args:None)
  with closing(sqlite3.connect(self.book)) as db:self.before=list(db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no'))
  self.addCleanup(self.unchanged)
 def unchanged(self):
  with closing(sqlite3.connect(self.book)) as db:
   self.assertEqual(self.before,list(db.execute('SELECT * FROM invoices ORDER BY company_id,invoice_no')))
   self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)
 def put(self,kind,key,body,revision=0,enabled=True):
  return configure(self.book,'U001',kind,key,body,expected_revision=revision,enabled=enabled,capabilities={'assistant.manage'})
 def activate(self):
  self.put('skill','s',self.body);self.put('assistant','a',{'name':'a','tools':['query_business_sql'],'skills':['s']});refresh_assistant(self.agent)
 def test_legacy_and_empty_terms_preserve_input_bytes(self):
  old={k:v for k,v in self.body.items() if k!='business_terms'};self.put('skill','legacy',old)
  expected=messages('普通问题',{})
  for body in (old,{**old,'business_terms':[]}):self.assertEqual(expected,messages('普通问题',{},active_skills=[{'id':'legacy','revision':1,**body}]))
 def test_projection_revision_and_skill_disable(self):
  self.activate();before=deepcopy(DEFINITION);context=messages('检核口径',{},active_skills=self.agent.active_skills);payload=json.loads(context[1]['content'])
  self.assertEqual(set(payload),{'request','read_catalog','trusted_scope','previous_requirement','business_definition'})
  self.assertEqual(payload['business_definition']['skill_terms'],[{'skill_id':'s','revision':1,'terms':[self.term]}])
  self.assertNotIn('PRIVATE_STEP_SENTINEL',str(context));self.assertNotIn('SYSTEM_SENTINEL',str(context));self.assertEqual(DEFINITION,before)
  changed=deepcopy(self.body);changed['business_terms'][0]['metrics']=[{'operation':'count','field':'*'}]
  self.put('skill','s',changed,1);refresh_assistant(self.agent);self.assertEqual(semantic_skill_terms(self.agent.active_skills,BUSINESS_FIELDS)[0]['revision'],2)
  self.put('skill','s',changed,2,False);refresh_assistant(self.agent);self.assertEqual(self.agent.active_skills,[])
 def test_dependencies_and_owner_still_control_activation(self):
  self.activate();self.put('tool','query_business_sql',{},enabled=False);refresh_assistant(self.agent);self.assertEqual(self.agent.active_skills,[])
  self.agent.user_id='U002'
  with self.assertRaises(PermissionError):refresh_assistant(self.agent)
 def test_invalid_mapping_or_authority_fields_cannot_be_saved_or_projected(self):
  bad=[{**self.term,**change} for change in ({'object':'invented'},{'term':''},{'sql':'SELECT 1'},{'answer':42},{'authorized':True},{'filters':[]})]
  bad += [{**self.term,'metrics':[m]} for m in ({'operation':'avg','field':'amount_cents'},{'operation':'sum','field':'invented'},{'operation':'count','field':'*','source':'trusted'})]
  for entry in bad:
   with self.subTest(entry=entry),self.assertRaises(ValueError):self.put('skill','bad',{**self.body,'business_terms':[entry]})
   with self.subTest(entry=entry),self.assertRaises(ValueError):semantic_skill_terms([{'id':'s','revision':1,'business_terms':[entry]}],BUSINESS_FIELDS)
  for revision in (True,0,'1'):
   with self.assertRaises(ValueError):semantic_skill_terms([{'id':'s','revision':revision,'business_terms':[self.term]}],BUSINESS_FIELDS)
  with self.assertRaises(PermissionError):configure(self.book,'U001','skill','s',self.body)
 def test_mapping_does_not_grant_scope_or_current_source(self):
  self.activate();messages('检核口径',{},active_skills=self.agent.active_skills)
  target={'target_id':'i','object':'invoices','company_ids':['C002'],'company_quote':'C002','periods':[[2026,9]],'period_quote':'2026年9月','seller':{'mode':'none','value':'','quote':'统计'},'metrics':[{'operation':'sum','field':'amount_cents','quote':'检核口径'}]}
  with self.assertRaises(BusinessRequestError) as error:bind({'kind':'read','targets':[target]},actor='U002',book=self.book,turn_id='t',request='C002 2026年9月统计检核口径')
  self.assertEqual(error.exception.status,'DENIED')
  target['company_ids']=['C001'];target['company_quote']='C001';target['metrics'][0]['quote']=''
  with self.assertRaises(BusinessRequestError):bind({'kind':'read','targets':[target]},actor='U001',book=self.book,turn_id='t',request='C001 2026年9月统计检核口径')
 def test_actual_agent_first_semantic_input_contains_only_active_term_definition(self):
  from app.agent import Agent
  self.activate();seen=[]
  def model(context,tools):
   seen.append((deepcopy(context),deepcopy(tools)))
   self.assertEqual(len(seen),1,'Missing scope should stop before financial execution')
   target={'target_id':'i','object':'invoices','company_ids':[],'periods':[],
    'seller':{'mode':'none','value':'','quote':'检核口径'},
    'metrics':[{**metric,'quote':'检核口径'} for metric in self.term['metrics']]}
   return {'role':'assistant','content':json.dumps({'kind':'read','targets':[target],'unresolved':[]},ensure_ascii=False)}
  agent=Agent('U001',self.book,model,mode='mock',trace_path=self.book.parent/'semantic.jsonl')
  agent.assistant_id='a';agent.ask('请统计检核口径')
  self.assertEqual(seen[0][1],[])
  payload=json.loads(seen[0][0][1]['content'])
  self.assertEqual(payload['business_definition']['skill_terms'],[{'skill_id':'s','revision':1,'terms':[self.term]}])
  self.assertNotIn('PRIVATE_STEP_SENTINEL',str(seen[0]));self.assertNotIn('tool_calls',str(seen[0]))
  self.assertTrue(agent.business_request.unresolved)
