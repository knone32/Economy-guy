"""Scripted Agent/runtime checks; no NLU score, model HTTP or human approval.

Only FaultRecoveryTests injects a simulated trusted confirmation in a temporary
fictional database. It deliberately loses the post-commit readback response.
"""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.invoice_batch import run_invoice_batch
from app.session_store import SessionStore
from app.tool_registry import TOOLS
from app.updates import inspect_request
from tests import test_business_sources as base
from tests.test_model_intent import call
from tests.test_tui_p0 import FIXTURE


def final(**values):
    return {'role': 'assistant', 'content': json.dumps(
        {'kind': 'information', 'text': '请继续提供业务信息。', **values}, ensure_ascii=False)}


class TicketContinuityTests(unittest.TestCase):
    setUp = base.BusinessSourceTests.setUp
    tearDown = base.BusinessSourceTests.tearDown
    ask = base.BusinessSourceTests.ask
    preview = base.BusinessSourceTests.preview

    def start(self):
        self.ask('甲企业2026年9月有张发票，备注填「材料复核待办」，编号稍后补。',
                 company_id='C001', year=2026, month=9, field='remark', new_value='材料复核待办')
        self.assertEqual(self.agent.pending_intent['missing_fields'], ('invoice_no',))
        return deepcopy(self.agent.pending_intent)

    def read_other_company(self):
        replies = iter([call('get_invoice', {'company_id': 'C002', 'invoice_no': 'F006'}), final()])
        self.agent.model = lambda *_: next(replies)
        self.agent.ask('先核对乙企业2026年9月F006的现状，这次只查询。')
        self.assertTrue(any(name == 'get_invoice' and result['status'] == 'SUCCESS'
                            for name, result in self.agent.last_response['tool_results']))
        self.assertIsNone(self.agent.last_response.get('invoice_change'))

    def test_other_company_read_then_return_and_object_only_keeps_source(self):
        pending = self.start()
        self.read_other_company()
        self.assertEqual(self.agent.pending_intent, pending)
        self.agent.model = lambda *_: final()
        self.agent.ask('回到刚才甲企业那项办理，我接下来补编号。')
        self.assertEqual(self.agent.pending_intent, pending)
        self.ask('编号 F006，先给我核对原值和新值。', invoice_no='F006')
        plan, body = self.preview()
        self.assertEqual((plan['company_id'], plan['invoice_nos'], plan['field'], plan['new_value']),
                         ('C001', ('F006',), 'remark', '材料复核待办'))
        self.assertIn(pending['source_request'], plan['source_request'])
        self.assertIn('原值　按月结算', body)
        self.assertIn('新值　材料复核待办', body)
        self.assertEqual(self.agent.write_receipt['status'], 'CANCELLED')
        # Original source is checked before preview consumes the pending state;
        # the read-only detour itself never replaces that provenance.
        self.assertEqual(pending['provenance']['new_value']['kind'], 'current_literal')

    def test_explicit_stop_cannot_revive_by_same_object_only_patch(self):
        self.start()
        self.read_other_company()
        self.agent.model = lambda *_: final(turn_action='stop')
        self.agent.ask('刚才甲企业那项修改取消，请结束。')
        self.assertIsNone(self.agent.pending_intent)
        self.ask('F006。', invoice_no='F006')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))
        pending = self.agent.pending_intent
        self.assertFalse(pending['change'])
        self.assertNotIn('company_id', pending['scope'])
        self.assertNotIn('new_value', pending['provenance'])

    def test_target_patch_reads_current_object_and_preview_rechecks_current_value(self):
        self.start()
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute("UPDATE invoices SET remark='独立新原值' WHERE company_id='C001' AND invoice_no='F006'")
        # The fixture change is outside the agent. Preserve the no-agent-write
        # invariant used by the shared tearDown against this new baseline.
        from tests.test_sql_invoice_selection import snapshot
        self.before = snapshot(self.book)
        self.ask('编号 F006。', invoice_no='F006')
        reads = [result for name, result in self.agent.last_response['tool_results']
                 if name == 'get_invoice' and result['status'] == 'SUCCESS']
        self.assertTrue(reads)
        self.assertEqual(reads[-1]['evidence']['source'], 'current_sqlite')
        self.assertEqual(reads[-1]['data']['remark'], '独立新原值')
        self.assertIn('原值　独立新原值', self.preview()[1])

    def test_identity_and_permission_change_block_old_pending(self):
        for boundary in ('identity', 'read', 'modify'):
            with self.subTest(boundary=boundary):
                self.agent.user_id = 'U001'
                self.agent.cancel_update()
                self.start()
                if boundary == 'identity':
                    self.agent.user_id = 'U002'
                else:
                    column = 'can_read' if boundary == 'read' else 'can_modify'
                    with closing(sqlite3.connect(self.book)) as db, db:
                        db.execute(f"UPDATE permissions SET {column}=0 WHERE user_id='U001' AND company_id='C001'")
                try:
                    self.ask('编号 F006。', invoice_no='F006')
                    self.assertIsNone(self.agent.last_response.get('invoice_change'))
                    self.assertFalse(self.agent.update_session.drafts)
                    self.assertFalse(self.agent.update_session.confirmations)
                finally:
                    with closing(sqlite3.connect(self.book)) as db, db:
                        db.execute("UPDATE permissions SET can_read=1,can_modify=1 WHERE user_id='U001' AND company_id='C001'")

    def test_company_replacement_does_not_select_same_number_from_old_context(self):
        self.start()
        self.ask('企业改为乙企业，编号还未提供。', company_id='C002')
        self.assertEqual(self.agent.pending_intent['scope']['company_id'], ['C002'])
        self.assertNotIn('invoice_no', self.agent.pending_intent['scope'])
        self.ask('编号 F006。', invoice_no='F006')
        plan, body = self.preview()
        self.assertEqual(plan['company_id'], 'C002')
        self.assertIn('原值　两日住宿', body)

    def test_model_has_no_commit_or_confirmation_capability(self):
        self.assertFalse({'commit_invoice_update', 'confirm_draft', 'commit_update', 'inspect_request'}
                         & {tool['function']['name'] for tool in TOOLS})
        self.start()
        for args in ({'invoice_no': 'F006', 'confirmed': True},
                     {'invoice_no': 'F006', 'authorized': True}):
            self.ask('编号 F006，给我预览。', **args)
            self.assertIsNone(self.agent.last_response.get('invoice_change'))
            self.assertFalse(self.agent.update_session.drafts)
            self.assertFalse(self.agent.update_session.confirmations)


class FaultRecoveryTests(unittest.TestCase):
    def test_committed_but_lost_response_reuses_request_and_restart_only_reads(self):
        """PROGRAM FAULT TEST: simulated approval; never human or Live evidence."""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            book = root / 'fixture.sqlite3'
            import_workspace(FIXTURE, book)
            with closing(sqlite3.connect(book)) as db, db:
                db.execute('CREATE TABLE program_update_events(company_id TEXT, invoice_no TEXT)')
                db.execute('''CREATE TRIGGER program_count_updates AFTER UPDATE OF remark ON invoices
                              BEGIN INSERT INTO program_update_events VALUES (NEW.company_id,NEW.invoice_no); END''')
                initial_tasks = db.execute('SELECT * FROM tasks ORDER BY task_id').fetchall()
            agent = Agent('U001', book, lambda *_: call('change_invoice', {
                'company_id': 'C001', 'year': 2026, 'month': 9, 'invoice_no': 'F006',
                'field': 'remark', 'new_value': '程序故障测试'}), mode='mock',
                trace_path=root / 'fault.jsonl')
            agent.ask('甲企业2026年9月 F006 备注填写「程序故障测试」，先给预览。')
            plan = agent.last_response['invoice_change']
            store = SessionStore(root / 'sessions.sqlite3', book, 'U001')
            seq = store.begin('隔离夹具程序故障测试，模拟确认', 'mock')
            drafts = []
            previews = []

            def simulated_confirmation(body):
                previews.append(body)
                drafts.extend(agent.update_session.drafts.values())
                return 'confirm'

            # Commit and audit happen, then a deterministic readback exception
            # loses the receipt. The session checkpoint retains only lookup ID.
            with patch('app.updates._readback', side_effect=sqlite3.OperationalError('injected lost response')):
                run_invoice_batch(agent, plan['source_request'], plan,
                                  approve_item=simulated_confirmation, approve_batch=None,
                                  checkpoint=lambda request_id: store.checkpoint(seq, request_id))
            draft, = drafts
            self.assertEqual(len(previews), 1)
            self.assertIn('原值　按月结算', previews[0])
            self.assertIn('新值　程序故障测试', previews[0])
            self.assertEqual(agent.write_receipt['status'], 'UNKNOWN_OUTCOME')
            self.assertEqual(agent.write_receipt['request_id'], draft.request_id)
            self.assertFalse(agent.update_session.drafts)
            self.assertFalse(agent.update_session.confirmations)

            def counts():
                with closing(sqlite3.connect(book)) as db:
                    return (db.execute("SELECT remark FROM invoices WHERE company_id='C001' AND invoice_no='F006'").fetchone()[0],
                            db.execute('SELECT request_id,status FROM invoice_audit').fetchall(),
                            db.execute('SELECT company_id,invoice_no FROM program_update_events').fetchall())

            expected = ('程序故障测试', [(draft.request_id, 'COMMITTED')], [('C001', 'F006')])
            self.assertEqual(counts(), expected)
            # Calling the production entry again with the same request while
            # outcome is unknown is blocked before any second commit attempt.
            with patch('app.agent.commit_invoice_update', side_effect=AssertionError('must inspect, not rewrite')):
                self.assertEqual(agent.commit_update(draft.request_id, draft.fingerprint())['status'], 'UNKNOWN_OUTCOME')
            receipt = agent.reconcile_update()
            self.assertEqual(receipt['status'], 'COMMITTED')
            self.assertTrue(receipt['readback_verified'])
            self.assertEqual(receipt['request_id'], draft.request_id)
            self.assertEqual(counts(), expected)
            store.close()

            # Simulated process restart: a fresh Agent has no draft/approval.
            # SessionStore preserves UNKNOWN_OUTCOME + request ID for a readonly
            # audit/current-value lookup; no pending business or Task is restored.
            reopened = SessionStore(root / 'sessions.sqlite3', book, 'U001')
            history = reopened.history()
            turn, = history['turns']
            self.assertEqual((turn['state'], turn['lookup']), ('UNKNOWN_OUTCOME', draft.request_id))
            restarted = Agent('U001', book, lambda *_: final(), mode='mock')
            self.assertIsNone(restarted.pending_intent)
            self.assertFalse(restarted.update_session.drafts)
            self.assertFalse(restarted.update_session.confirmations)
            self.assertEqual(restarted.commit_update(draft.request_id, draft.fingerprint())['status'], 'DENIED')
            audit = inspect_request(book, 'U001', turn['lookup'])
            self.assertEqual(audit['status'], 'COMMITTED')
            self.assertEqual(audit['data']['historical_commit']['request_id'], draft.request_id)
            self.assertTrue(audit['data']['current_matches'])
            self.assertEqual(audit['data']['current_invoice']['remark'], '程序故障测试')
            self.assertEqual(counts(), expected)
            with closing(sqlite3.connect(book)) as db:
                self.assertEqual(db.execute('SELECT * FROM tasks ORDER BY task_id').fetchall(), initial_tasks)
            reopened.close()


if __name__ == '__main__':
    unittest.main()
