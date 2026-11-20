"""Current edit-owner read basis expires with its existing lifecycle."""
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.provenance import ScopeProof
from app.updates import prepare_invoice_update


class WriteReadBasisLifecycleTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.book=self.root/'fictional.sqlite'
        import_workspace(Path(__file__).parent/'fixtures/example.xlsx',self.book)
        self.agent=Agent('U001',self.book,lambda *_:self.fail('No model call'),mode='mock',trace_path=self.root/'trace.jsonl')
        self.scope={'company_id':['C001'],'invoice_no':['F001'],'year':[2026],'month':[9],
                    'field':['remark'],'new_value':['待核查']}
        self.text='C001 2026年9月F001备注改为待核查'
        self.proof=ScopeProof('U001',{k:self.scope[k] for k in ('company_id','invoice_no','year','month')},
                              dict.fromkeys(('company_id','invoice_no','year','month'),'user_current'))
        self.before=self.book.read_bytes();self.addCleanup(self.unchanged)

    def unchanged(self):
        self.assertEqual(self.before,self.book.read_bytes())
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)

    def begin(self):self.agent.coordinator.begin(self.text,True,edit_scope=deepcopy(self.scope))

    def fresh(self):
        return self.agent.dispatch_tool('get_invoice',json.dumps({'company_id':'C001','invoice_no':'F001'}),
                                       'U001',self.book,provenance=self.proof)

    def denied(self):
        with patch('app.agent.handle_tool') as handler:
            result=self.fresh();self.assertEqual(result['status'],'DENIED',result)
            self.assertNotIn('read_basis',result.get('evidence',{}));handler.assert_not_called()

    def test_cancelled_pending_does_not_keep_read_basis_from_stale_prepare_boolean(self):
        self.begin();live=self.fresh()
        self.assertEqual(live['status'],'SUCCESS');self.assertEqual(live['evidence']['read_basis']['kind'],'invoice_update_session')
        self.agent.coordinator.cancel_update()
        self.assertTrue(self.agent.update_session.allow_prepare)  # preserve the exact original stale flag control
        self.assertEqual(self.agent.coordinator.receipt['status'],'CANCELLED')
        cancelled=self.fresh()
        self.assertEqual(cancelled['status'],'DENIED',cancelled)
        self.assertNotIn('read_basis',cancelled.get('evidence',{}))

    def prepare(self):
        self.begin()
        outcome=prepare_invoice_update(self.book,self.agent.update_session,'C001','F001','remark','待核查')
        self.assertEqual(outcome['status'],'WAITING_CONFIRMATION',outcome)
        self.assertIn('request_id',outcome['data']);self.assertIn('fingerprint',outcome['data'])
        self.agent.coordinator.record_preparation(outcome)
        return next(iter(self.agent.update_session.drafts.values()))

    def test_live_pending_and_actual_waiting_draft_can_fresh_read_only_same_target(self):
        self.begin();self.assertEqual(self.fresh()['status'],'SUCCESS')
        draft=self.prepare();self.assertIsNone(self.agent.coordinator.pending)
        self.assertEqual(self.agent.coordinator.receipt['data']['request_id'],draft.request_id)
        self.assertEqual(self.agent.coordinator.receipt['data']['fingerprint'],draft.fingerprint())
        result=self.fresh();self.assertEqual(result['status'],'SUCCESS',result)
        self.assertEqual(result['evidence']['read_basis']['turn_id'],draft.turn_id)
        for args in ({'company_id':'C001','invoice_no':'F002'},{'company_id':'C002','invoice_no':'F001'}):
            with patch('app.agent.handle_tool') as handler:
                result=self.agent.dispatch_tool('get_invoice',json.dumps(args),'U001',self.book,provenance=self.proof)
                self.assertEqual(result['status'],'DENIED');handler.assert_not_called()

    def test_pending_scope_identity_and_source_must_match_current_session(self):
        for mutation in ('actor','scope','source','missing'):
            self.begin();coordinator=self.agent.coordinator
            if mutation=='actor':coordinator.pending['user_id']='U002'
            elif mutation=='scope':coordinator.session.expected_scope={**coordinator.session.expected_scope,'invoice_no':['F002']}
            elif mutation=='source':coordinator.session.source_request+='伪来源'
            else:coordinator.pending=None
            self.denied()

    def test_real_draft_cancel_new_turn_and_terminal_receipts_cannot_be_read_basis(self):
        self.prepare();self.agent.coordinator.cancel_update();self.denied()
        draft=self.prepare();coordinator=self.agent.coordinator
        coordinator.begin('新的普通问题',False)
        # Even reinserted old objects cannot revive their old turn or receipt.
        coordinator.session.drafts[draft.request_id]=draft
        coordinator.session.allow_prepare=True;coordinator.session.explicit_edit_only=True
        coordinator.session.expected_scope=deepcopy(self.scope)
        coordinator.receipt=coordinator._receipt('WAITING_CONFIRMATION',{'request_id':draft.request_id,'fingerprint':draft.fingerprint()})
        self.denied()
        for status in ('COMMITTED','NO_CHANGE','CURRENT_VALUE_MATCHES','CANCELLED','DENIED','ERROR'):
            self.prepare();coordinator.receipt=coordinator._receipt(status)
            self.denied()

    def test_waiting_receipt_requires_existing_matching_real_draft(self):
        for field,value in [('session_id','stale'),('turn_id','stale'),('actor','U002'),('company_id','C002'),
                            ('invoice_no','F002'),('source_request','stale source'),('field','purpose'),('new_value','other')]:
            with self.subTest(field=field):
                draft=self.prepare();coordinator=self.agent.coordinator
                bad=replace(draft,**{field:value})
                coordinator.session.drafts[draft.request_id]=bad
                # Matching a tampered object's own fingerprint is insufficient.
                coordinator.receipt['data']['fingerprint']=bad.fingerprint()
                self.denied()
        draft=self.prepare();coordinator=self.agent.coordinator
        coordinator.session.drafts.clear();self.denied()
        coordinator.session.drafts[draft.request_id]=object();self.denied()
        self.prepare();coordinator.receipt['data']['fingerprint']='wrong';self.denied()

    def test_unverified_owner_and_wrong_actor_or_workbook_never_supply_basis(self):
        draft=self.prepare();coordinator=self.agent.coordinator
        coordinator.unverified_draft=draft;self.denied()
        coordinator.unverified_draft=None;self.begin()
        args={'company_id':'C001','invoice_no':'F001'}
        self.assertIsNone(coordinator.read_basis('get_invoice',args,actor='U002',book=self.book))
        self.assertIsNone(coordinator.read_basis('get_invoice',args,actor='U001',book=self.root/'other.sqlite'))
        self.assertIsNone(coordinator.read_basis('get_finance_summary',args,actor='U001',book=self.book))

    def test_actual_commit_terminal_does_not_keep_old_edit_read_basis(self):
        # A separate disposable book is intentionally committed exactly once.
        # All other lifecycle tests above remain zero-write controls.
        with TemporaryDirectory() as temp:
            book=Path(temp)/'commit-control.sqlite'
            import_workspace(Path(__file__).parent/'fixtures/example.xlsx',book)
            a=Agent('U001',book,lambda *_:self.fail('No model call'),mode='mock',trace_path=Path(temp)/'trace.jsonl')
            a.coordinator.begin(self.text,True,edit_scope=deepcopy(self.scope))
            prepared=prepare_invoice_update(book,a.update_session,'C001','F001','remark','待核查')
            a.coordinator.record_preparation(prepared)
            draft=next(iter(a.update_session.drafts.values()))
            receipt=a.coordinator.commit_update(draft.request_id,draft.fingerprint())
            self.assertEqual(receipt['status'],'COMMITTED',receipt)
            self.assertTrue(receipt['readback_verified'])
            with closing(sqlite3.connect(book)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],1)
                self.assertEqual(db.execute("SELECT remark FROM invoices WHERE company_id='C001' AND invoice_no='F001'").fetchone()[0],'待核查')
            with patch('app.agent.handle_tool') as handler:
                result=a.dispatch_tool('get_invoice',json.dumps({'company_id':'C001','invoice_no':'F001'}),
                    'U001',book,provenance=self.proof)
                self.assertEqual(result['status'],'DENIED');handler.assert_not_called()
