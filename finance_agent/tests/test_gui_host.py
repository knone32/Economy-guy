"""Deterministic GUI host regressions; scripted model only, no API."""
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.cli_workspaces import import_workspace
from app.gui_host import GuiError, GuiHost
from tests.test_business_request_single_entry import semantic_input


def tool(name, **args):
    return {'role': 'assistant', 'tool_calls': [{'id': 'gui-call', 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}]}


class GuiHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.book = self.root / 'fictional.sqlite'
        import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', self.book)
        self.session = self.root / 'sessions.sqlite3'

    def host(self, model):
        host = GuiHost(self.book, 'U001', session_path=self.session, mode='mock', model=model)
        self.addCleanup(host.close)
        return host

    def change_model(self):
        def model(messages, tools):
            if semantic_input(messages):
                return {'role': 'assistant', 'content': '{"kind":"legacy"}'}
            if any(message.get('role') == 'tool' for message in messages):
                return {'role': 'assistant',
                        'content': json.dumps({'kind': 'information', 'text': '等待预览确认。'},
                                              ensure_ascii=False)}
            return tool('change_invoice', company_id='C001', invoice_no='F001',
                        field='remark', new_value='已核对')
        return model

    def test_snapshot_exposes_session_without_business_write(self):
        host = self.host(lambda *_: None)
        snap = host.snapshot()
        self.assertEqual(snap['session']['user'], 'U001')
        self.assertEqual(snap['session']['workbook'], str(self.book.resolve()))
        self.assertEqual(snap['persistence']['send'], 'not_attempted')
        self.assertEqual(snap['settings']['account']['user_id'], 'U001')
        self.assertEqual(snap['settings']['account']['workbook'], str(self.book.resolve()))
        self.assertEqual(snap['settings']['model']['status'], 'MOCK')
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0], 0)

    def test_single_preview_is_server_owned_and_commit_is_readback_verified(self):
        host = self.host(self.change_model())
        snap = host.send('把C001 F001的备注改成已核对。')
        self.assertTrue(snap['preview'], snap)
        self.assertEqual(snap['preview']['count'], 1)
        self.assertFalse(any('request_id' in item or 'fingerprint' in item
                             for item in snap['preview']['items']))
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute("SELECT remark FROM invoices WHERE company_id='C001' "
                                        "AND invoice_no='F001'").fetchone()[0], '日常办公采购')
        out = host.confirm_preview(snap['preview']['id'], context=snap['context'])
        self.assertEqual(out['receipt']['status'], 'COMMITTED', out)
        self.assertTrue(out['receipt']['readback_verified'])
        self.assertNotIn('fingerprint', json.dumps(out.get('receipt'), ensure_ascii=False))
        self.assertEqual(out['persistence']['send'], 'saved')
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute("SELECT remark FROM invoices WHERE company_id='C001' "
                                        "AND invoice_no='F001'").fetchone()[0], '已核对')
            audit = db.execute('SELECT company_id,invoice_no,field,new_value,status FROM invoice_audit').fetchall()
        self.assertEqual(audit, [('C001', 'F001', 'remark', '已核对', 'COMMITTED')])

    def test_query_display_ack_enables_same_chat_reference_continuation(self):
        target = {
            'target_id': 'i1', 'object': 'invoices', 'company_ids': ['C001'],
            'company_quote': 'C001', 'periods': [[2026, 9]], 'period_quote': '2026年9月',
            'seller': {'mode': 'none', 'quote': '不设置销售方条件', 'value': ''},
            'filters': [], 'metrics': [{'operation': 'details', 'field': '*', 'quote': '发票明细'}],
            'group_by': [], 'comparisons': [],
        }
        def model(messages, tools):
            if semantic_input(messages):
                return {'role': 'assistant', 'content': json.dumps(
                    {'kind': 'read', 'targets': [target], 'unresolved': []}, ensure_ascii=False)}
            catalog = next((message for message in reversed(messages)
                            if message.get('name') == 'answer_catalog'), None)
            if catalog:
                facts = json.loads(catalog['content'].rsplit('\n', 1)[-1])
                refs = [fact['ref'] for fact in facts if fact.get('type') in {'result', 'scalar'}]
                if refs:
                    return {'role': 'assistant', 'content': json.dumps(
                        {'kind': 'information', 'text': '本轮结果见卡。', 'answer': refs},
                        ensure_ascii=False)}
            return tool('query_business_sql',
                        sql="SELECT * FROM invoices WHERE company_id='C001' "
                            "AND invoice_date LIKE '2026-09-%'")
        host = self.host(model)
        snap = host.send('查C001 2026年9月不设置销售方条件的发票明细。')
        self.assertTrue(snap['display'])
        self.assertFalse(snap['display']['acknowledged'])
        blocked = host.send('刚才那张发票的用途也看一下。')
        self.assertTrue(blocked['error'])
        snap = host.acknowledge_display(snap['display']['trace'])
        self.assertTrue(snap['display']['acknowledged'])
        followup = host.send('刚才那张发票的用途也看一下。')
        self.assertFalse(followup['error'])
        self.assertEqual(followup['session']['active_chat'], snap['session']['active_chat'])

    def test_confirmation_timeout_closes_handle_and_never_approves(self):
        host = self.host(self.change_model())
        host.CONFIRMATION_TIMEOUT = 0.2
        snap = host.send('把C001 F001的备注改成已核对。')
        preview = snap['preview']
        self.assertTrue(preview)
        old_id = preview['id']
        context = snap['context']
        time.sleep(0.35)
        out = host.snapshot()
        self.assertIsNone(out['preview'])
        self.assertIsNone(out['receipt'])
        self.assertFalse(out['busy'])
        self.assertEqual(out['confirmation']['state'], 'EXPIRED')
        self.assertIn('未批准', out['confirmation']['message'])
        with self.assertRaises(GuiError):
            host.confirm_preview(old_id, context=context)
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0], 0)

    def test_paused_candidate_exposes_backend_cancel_only_when_current(self):
        def model(messages, tools):
            if semantic_input(messages):
                return {'role': 'assistant', 'content': '{"kind":"legacy"}'}
            if any(message.get('role') == 'tool' for message in messages):
                return {'role': 'assistant', 'content': json.dumps(
                    {'kind': 'information', 'text': '请补充新值。'}, ensure_ascii=False)}
            return tool('change_invoice', company_id='C001', invoice_no='F001', field='remark')
        host = self.host(model)
        host.send('把C001 F001的备注改一下，具体内容稍后给。')
        paused = host.pause()
        self.assertEqual(len(paused['candidates']), 1)
        candidate = paused['candidates'][0]
        self.assertEqual(candidate['state'], 'PAUSED')
        self.assertTrue(candidate['can_resume'])
        self.assertTrue(candidate['can_cancel'])
        out = host.cancel(context=paused['context'])
        self.assertIsNone(out['pending'])
        self.assertEqual(out['candidates'], [])
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0], 0)

    def test_pause_storage_failure_cannot_claim_recoverable(self):
        def model(messages, tools):
            if semantic_input(messages):
                return {'role': 'assistant', 'content': '{"kind":"legacy"}'}
            if any(message.get('role') == 'tool' for message in messages):
                return {'role': 'assistant',
                        'content': json.dumps({'kind': 'information', 'text': '请补充新值。'},
                                              ensure_ascii=False)}
            return tool('change_invoice', company_id='C001', invoice_no='F001', field='remark')
        host = self.host(model)
        snap = host.send('把C001 F001的备注改一下，具体内容稍后给。')
        self.assertEqual(snap['pending']['missing_fields'], ['new_value'])
        def fail(*args, **kwargs):
            raise OSError('injected storage failure')
        original = host.store.set_invoice_pending
        host.store.set_invoice_pending = fail
        try:
            out = host.pause()
        finally:
            host.store.set_invoice_pending = original
        self.assertTrue(out['error'])
        self.assertEqual(out['persistence']['send'], 'failed')
        self.assertNotEqual(out['pending']['state'], 'PAUSED')
        self.assertEqual(out['candidates'], [])

    def test_cancel_preview_does_not_write_or_persist_approval(self):
        host = self.host(self.change_model())
        snap = host.send('把C001 F001的备注改成已核对。')
        self.assertTrue(snap['preview'])
        out = host.cancel_preview(snap['preview']['id'], context=snap['context'])
        self.assertIsNone(out['preview'])
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT remark FROM invoices WHERE company_id='C001' "
                                        "AND invoice_no='F001'").fetchone()[0], '日常办公采购')


if __name__ == '__main__':
    unittest.main()
