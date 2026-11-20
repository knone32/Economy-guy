"""Published model guidance must describe tools the runtime actually accepts."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.agent import SYSTEM
from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.invoice_batch import run_invoice_batch
from app.tool_registry import TOOLS, validate_arguments
from tests.test_model_intent import call
from tests.test_sql_invoice_selection import snapshot


class BusinessContractGuidanceTests(unittest.TestCase):
    def test_incomplete_single_invoice_uses_its_existing_business_interface(self):
        schemas={t['function']['name']:t['function']['parameters'] for t in TOOLS}
        self.assertEqual(schemas['change_invoice']['required'],[])
        self.assertNotIn('action=request',SYSTEM)
        self.assertEqual(validate_arguments('change_invoice','{}'),{})

    def test_complex_selection_keeps_complete_schema_without_request_mode(self):
        args={'selection_id':'current','field':'remark','new_value':'example',
              'mode':'item','excluded_invoice_ids':[]}
        self.assertEqual(validate_arguments('propose_invoice_changes',json.dumps(args)),args)
        with self.assertRaises(ValueError):
            validate_arguments('propose_invoice_changes','{"action":"request"}')

    def test_same_authorized_actor_is_limited_by_assistant_tools_at_dispatch(self):
        """A configured tool set is independent from the user's invoice ACL."""
        with TemporaryDirectory() as folder:
            book=Path(folder)/'fixture.sqlite3'
            import_workspace(Path(__file__).parent/'fixtures/example.xlsx',book)
            before=snapshot(book)
            args={'company_id':'C001','year':2026,'month':9,'invoice_no':'F006',
                  'field':'remark','new_value':'确认前审阅'}
            seen=[]
            def model(messages,tools):
                seen.append({t['function']['name'] for t in tools})
                return call('change_invoice',args)
            restricted=Agent('U001',book,model,mode='mock')
            restricted.allowed_tools=frozenset({'get_invoice'})
            text='甲企业2026年9月 F006，备注填“确认前审阅”，先预览。'
            restricted.ask(text)
            self.assertNotIn('change_invoice',seen[0])
            self.assertTrue(any(r['status']=='DENIED' for _,r in restricted.last_response['tool_results']))
            self.assertIsNone(restricted.last_response.get('invoice_change'))
            self.assertIsNone(restricted.pending_intent)
            self.assertEqual(snapshot(book),before)
            enabled=Agent('U001',book,model,mode='mock');enabled.ask(text)
            plan=enabled.last_response['invoice_change'];previews=[]
            def reject(body):previews.append(body);return False
            run_invoice_batch(enabled,plan['source_request'],plan,approve_batch=reject,
                approve_item=reject,checkpoint=lambda *_:self.fail('No approval'))
            self.assertEqual(len(previews),1)
            self.assertEqual(snapshot(book),before)
