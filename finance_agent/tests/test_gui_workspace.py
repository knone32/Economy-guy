"""GUI additions through original services; no API or human approval."""
import base64
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from app.cli_workspaces import import_workspace
from app.gui_host import GuiHost,GuiError
from app.pending_transition import request_change


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.book=self.root/'fictional.sqlite'
        self.fixture=Path(__file__).parent/'fixtures/example.xlsx'
        import_workspace(self.fixture,self.book)
        self.host=GuiHost(self.book,'U001',session_path=self.root/'sessions.sqlite',mode='mock',
            model=lambda *a:self.fail('Structured GUI must not call a model'))
        self.addCleanup(self.host.close)
        self.before=self.facts()
    def facts(self):
        with closing(sqlite3.connect(self.book)) as db:
            return {t:db.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in ('invoices','invoice_audit')}
    def ack(self,view):
        if view.get('display'):return self.host.acknowledge_display(view['display']['trace'],context=view['context'])
        return view
    def tearDown(self):self.assertEqual(self.facts(),self.before)

    def test_directory_paging_fresh_detail_and_original_display_ack(self):
        args={'company_id':'C001','year':2026,'month':9,'page':1,'sort_by':'amount','sort_order':'asc'}
        view=self.host.read_business('list_invoice_directory',args)
        self.assertIsNone(view['error']);self.assertEqual(view['workspace']['result']['status'],'SUCCESS')
        self.assertFalse(view['display']['acknowledged']);self.ack(view)
        number=view['workspace']['result']['data']['rows'][0]['invoice_no']
        detail=self.host.read_business('get_invoice',{'company_id':'C001','invoice_no':number})
        self.assertEqual(detail['workspace']['result']['data']['invoice_no'],number)
        self.ack(detail)
        self.assertTrue(self.host.host.agent.context.display_ids)

    def test_host_binding_selection_blocks_forged_identity_and_old_revision(self):
        old=self.host.snapshot();selector=next(b['id'] for b in old['settings']['bindings'] if 'U002' in b['label'])
        with self.assertRaises(GuiError):self.host.select_binding('U001',context=old['context'])
        view=self.host.select_binding(selector,context=old['context'])
        self.assertEqual(view['session']['user'],'U002')
        denied=self.host.read_business('list_bank_transactions',{'company_id':'C002','year':2026,'month':9})
        self.assertFalse(denied['workspace']['result']['ok'])
        self.assertEqual(denied['workspace']['result']['status'],'DENIED')
        stale=self.host.read_business('get_invoice',{'company_id':'C001','invoice_no':'F005'},context=old['context'])
        self.assertTrue(stale['error'])

    def test_pending_owner_blocks_read_and_rebind_without_losing_values(self):
        agent=self.host.host.agent
        agent.pending_intent=request_change({'company_id':'C001','field':'remark','new_value':'等待核对'},None,
            actor='U001',book=self.book,current_id='pending',current_request='甲企业有张票备注填“等待核对”，票号稍后给。',business_continuation=True)
        original=agent.pending_intent.copy();view=self.host.snapshot()
        denied=self.host.read_business('get_invoice',{'company_id':'C001','invoice_no':'F005'})
        self.assertTrue(denied['error']);self.assertEqual(agent.pending_intent,original)
        selector=next(b['id'] for b in view['settings']['bindings'] if 'U002' in b['label'])
        denied=self.host.select_binding(selector,context=view['context'])
        self.assertTrue(denied['error']);self.assertEqual(agent.pending_intent,original)
        with self.assertRaises(Exception):self.host.request_close(view['context'])

    def test_preference_preview_cancel_reuses_original_confirmation_and_writes_nothing(self):
        view=self.host.preference_change({'company_id':'C001','action':'create','key':'验收显示','value':'简明列示'})
        self.assertTrue(view['preview']);self.assertEqual(view['preview']['kind'],'preference')
        self.host.cancel_preview(view['preview']['id'],context=view['context'])
        self.host._worker.join(5)
        with closing(sqlite3.connect(self.book)) as db:self.assertEqual(db.execute('SELECT count(*) FROM preferences').fetchone()[0],0)

    def test_import_creates_separate_book_without_rebinding_or_overwriting(self):
        old=self.host.db_path
        view=self.host.import_workbook('example.xlsx',base64.b64encode(self.fixture.read_bytes()).decode())
        self.assertEqual(self.host.db_path,old)
        self.assertEqual(len(view['settings']['bindings']),4)

    def test_missing_credentials_keeps_settings_and_readonly_ui_without_fake_live(self):
        template=self.root/'profiles.toml';template.write_text('profiles=[]\n',encoding='utf-8')
        other_book=self.root/'unconfigured-book.sqlite';import_workspace(self.fixture,other_book)
        other=GuiHost(other_book,'U001',session_path=self.root/'unconfigured.sqlite',mode='live',
            profiles_file=template,profiles_local=self.root/'absent.json')
        try:
            self.assertFalse(other.snapshot()['settings']['model']['configured'])
            with self.assertRaises(GuiError):other.send('查询发票')
            view=other.read_business('get_invoice',{'company_id':'C001','invoice_no':'F005'})
            self.assertEqual(view['workspace']['result']['status'],'SUCCESS')
        finally:other.close()

    def test_profile_save_uses_vault_and_forces_current_user_scope(self):
        from unittest.mock import patch
        template=self.root/'profile-template.toml';template.write_text('profiles=[]\n',encoding='utf-8')
        local=self.root/'profile-local.json';self.host.profiles.options={'template':template,'local':local}
        secret='synthetic-local-storage-marker'
        with patch('app.win_vault.WindowsVault') as vault:
            self.host.save_profile({'profile_name':'isolated','provider':'deepseek','model':'deepseek-flash',
                'base_url':'https://api.deepseek.com','api_key':secret,'scope':'global','owner_user_id':'U002'})
            vault.return_value.write.assert_called_once()
        import json
        data=json.loads(local.read_text(encoding='utf-8'))
        self.assertEqual(data['profiles'][0]['scope'],'user')
        self.assertEqual(data['profiles'][0]['owner_user_id'],'U001')
        self.assertNotIn(secret,local.read_text(encoding='utf-8'))
        self.assertNotIn(secret,json.dumps(self.host.snapshot()))

    def test_personal_preference_uses_original_preview_and_cancel(self):
        view=self.host.preference_change({'scope':'personal','action':'set','key':'阅读习惯','value':'详细'})
        self.assertTrue(view['preview'])
        self.host.cancel_preview(view['preview']['id'],context=view['context']);self.host._worker.join(5)
        self.assertEqual(self.host.store.personal_detail(),'普通')


if __name__=='__main__':unittest.main()
