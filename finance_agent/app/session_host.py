"""Trusted in-process frontend adapter; business state stays in its existing owners.

Call on a host worker. Confirmation callbacks must be supplied by the trusted
human UI, never by an RPC/model payload. This is not authentication or a server.
"""
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
import sqlite3
from threading import Lock, get_ident
from uuid import uuid4

from .invoice_action import public_state as invoice_business_state
from .cli_chat import turn_tools
from .invoice_batch import run_invoice_batch
from .responses import render_information
from .trace import redact


class SessionConflict(ValueError):
    """Refresh the snapshot; never replay a stale frontend command."""


class SessionHost:
    """One trusted SessionStore and its current Agent, without a second draft.

    agent_factory(actor, workbook) must construct a fresh original Agent with
    host-owned model configuration. The caller owns/ closes the SessionStore.
    """

    def __init__(self, store, agent_factory, *, confirm=None):
        self.store, self._factory, self._confirm = store, agent_factory, confirm
        self._lock = Lock()
        self._command_thread = None
        self._generation, self._revision = uuid4().hex, 0
        self._persistence = {'status': 'UNCHANGED', 'error': None}
        self._agent = None
        self._restore()

    @property
    def agent(self):
        """Trusted host instrumentation only; never serialize this object."""
        return self._agent

    def _binding(self):
        if self._lock.locked() and self._command_thread != get_ident():
            raise SessionConflict('Host is busy; use the confirmation callback snapshot or refresh later')
        self.store.validate()
        if (self._agent.user_id != self.store.actor
                or Path(self._agent.db_path).resolve() != self.store.workbook.resolve()
                or self._agent_chat != self.store.chat):
            raise SessionConflict('Host actor/workbook/conversation changed')
        self.store.validate_invoice_revision()

    def _token(self):
        return {'generation': self._generation, 'revision': self._revision,
                'chat': self.store.chat,
                'candidate': list(self.store.invoice_token) if self.store.invoice_token else None}

    @contextmanager
    def _command(self, expected):
        if not self._lock.acquire(blocking=False):
            raise SessionConflict('Another host command is running')
        self._command_thread = get_ident()
        try:
            self._binding()
            if expected != self._token():
                raise SessionConflict('Conversation or revision changed; refresh before acting')
            self._revision += 1
            yield
        except (OSError, sqlite3.Error) as error:
            self._persistence = {'status': 'FAILED', 'error': type(error).__name__,
                'message': '宿主读写失败，请刷新并核查原状态，不能据此重复提交。'}
            raise
        finally:
            self._command_thread = None
            self._lock.release()

    def _restore(self):
        history = self.store.history()
        agent = self._factory(self.store.actor, self.store.workbook)
        if (agent.user_id != self.store.actor
                or Path(agent.db_path).resolve() != self.store.workbook.resolve()
                or agent._active or agent._retired or len(agent.messages) != 1):
            raise SessionConflict('Factory must supply a fresh, correctly bound Agent')
        agent.workbook_guard = self.store.validate_invoice_revision
        agent.restore_business_request(history['business_request'])
        # Structured current state wins over all historical text and old hints.
        agent.context.restore_query_hints(
            [{'reference_state': history['reference_state']}] if history['reference_state'] is not None else [])
        agent.context.display_ids = []
        pending = history['invoice_pending']
        unknown = [t['lookup'] for t in history['turns']
                   if t['state'] == 'UNKNOWN_OUTCOME' and t.get('lookup')]
        agent.coordinator.restore_verification_requests(unknown, actor=self.store.actor, book=self.store.workbook)
        for _ in unknown:
            remaining = len(agent.coordinator.unverified_request_ids)
            agent.reconcile_update()
            if len(agent.coordinator.unverified_request_ids) == remaining:
                break
        if pending is not None and not agent.coordinator.has_unverified_update:
            agent.restore_invoice_candidate(pending)
        self._agent = agent
        self._agent_chat = self.store.chat

    def snapshot(self):
        """Projection of owners, not a second authoritative state snapshot."""
        self._binding()
        agent = self._agent
        response = agent.last_response or {}
        pending = agent.pending_intent or getattr(agent, 'paused_invoice_candidate', None)
        drafts = [asdict(d) for d in agent.update_session.drafts.values()]
        preview = [{k: d[k] for k in ('company_id', 'invoice_no', 'field', 'old_value', 'new_value')}
                   for d in drafts]
        receipt = agent.write_receipt
        saved = (receipt.get('status') in {'COMMITTED', 'NO_CHANGE', 'CURRENT_VALUE_MATCHES'}
                 and receipt.get('readback_verified') is True)
        proposal = response.get('invoice_change') if not saved else None
        cancelled = agent.write_receipt.get('status') == 'CANCELLED'
        paused = bool(getattr(agent, 'paused_invoice_candidate', None))
        # A command receipt is newer than the preceding model answer. Keep the
        # latter as explicitly historical, never as the current action prompt.
        historical = cancelled or paused
        results = response.get('tool_results') or []
        current_result = {'text': response.get('text'), 'category': response.get('category'),
                          'coverage': response.get('business_request_final_coverage'),
                          'cards': render_information(results) if results else ''}
        candidates = self.store.list_invoice_candidates()
        status = ('UNKNOWN_OUTCOME' if agent.coordinator.has_unverified_update else
                  'CANCELLED' if cancelled else
                  receipt['status'] if saved else
                  response['host_execution']['status'] if response.get('host_execution') else
                  'PAUSED' if paused and self._persistence['status'] != 'FAILED'
                      and any(c['state'] == 'PAUSED' for c in candidates) else
                  'WAITING_CONFIRMATION' if preview else
                  'WAITING_USER' if pending else
                  'PROPOSAL_READY' if proposal else
                  'COMPLETE' if (current_result['coverage'] or {}).get('complete') else
                  'WAITING_USER' if response.get('category') in {'clarification', 'reference_error'} else 'IDLE')
        return redact({'version': 1, 'context': self._token(), 'busy': self._lock.locked(),
            'actor': self.store.actor, 'workbook': self.store.identity,
            'business_status': status,
            'requirement': agent.business_request_snapshot(),
            'pending': invoice_business_state(pending) if pending else None,
            'candidates': candidates,
            'preview': preview, 'approval_restored': False,
            'proposal': ({k: proposal[k] for k in ('company_id', 'year', 'month', 'invoice_nos', 'field', 'new_value')}
                         if proposal else None),
            'confirmation_channel_available': self._confirm is not None,
            'receipt': agent.write_receipt, 'persistence': dict(self._persistence),
            'execution': response.get('host_execution'),
            'result': current_result if not historical else None,
            'historical_result': current_result if historical else None})

    def list_conversations(self):
        self._binding()
        return self.store.list_chats()

    def _save(self, seq, offset, text, *, state='COMPLETED', operation=None):
        agent = self._agent
        pending = agent.pending_intent or getattr(agent, 'paused_invoice_candidate', None)
        if pending and pending.get('business_action') != 'single_invoice':
            pending = None
        hint = {'reference_state': agent.context.reference_state_snapshot(),
                'business_request': agent.business_request_snapshot()}
        try:
            self.store.finish(seq, [['Agent', self._storage_text(text)]], turn_tools(agent.messages[offset:]),
                agent.trace_id, hint, state, operation=operation, invoice_pending=pending,
                candidate_state=('PAUSED' if getattr(agent, 'paused_invoice_candidate', None) else
                    'COMPLETED' if agent.write_receipt.get('status') in
                    {'COMMITTED', 'NO_CHANGE', 'UNKNOWN_OUTCOME', 'CURRENT_VALUE_MATCHES'} else None))
        except (OSError, ValueError, sqlite3.Error) as error:
            self._persistence = {'status': 'FAILED', 'error': type(error).__name__,
                'message': '本轮历史保存失败；业务提交状态请按原回执核查，不能直接重提。'}
        else:
            self._persistence = {'status': 'SAVED', 'error': None}

    def _storage_text(self, text):
        connection = self._agent.connection
        if connection and connection.api_key:
            text = text.replace(connection.api_key, '[REDACTED]')
        return redact(text)

    def _approval(self, title, body, kind):
        if self._confirm is None:
            raise SessionConflict('No trusted human confirmation channel is installed')
        # The host blocks here; the frontend renders this original preview and
        # returns the human decision. No fingerprint/approval token goes to RPC.
        return self._confirm({'title': title, 'body': str(body), 'kind': kind,
                              'context': self._token(), 'snapshot': self.snapshot()})

    def preview(self):
        """Read current original proposal/draft; creates no approval or write."""
        view = self.snapshot()
        return {k: view[k] for k in ('context', 'proposal', 'preview', 'confirmation_channel_available')}

    def send_message(self, text, *, expected):
        if type(text) is not str or not text.strip():
            raise ValueError('A non-empty original user message is required')
        with self._command(expected):
            agent = self._agent
            seq = self.store.begin(self._storage_text(text), agent.mode)
            offset = len(agent.messages)
            state, operation = 'COMPLETED', None
            try:
                agent.ask(text)
                proposal = (agent.last_response or {}).get('invoice_change')
                if proposal is not None and self._confirm is not None:
                    agent.last_response.pop('invoice_change')
                    if getattr(agent, 'ticket_preview_candidate', None):
                        self.store.checkpoint_invoice_candidate(seq, agent.ticket_preview_candidate)
                    items = []
                    status, summary = run_invoice_batch(agent, proposal['source_request'], proposal,
                        approve_batch=lambda body, mode: self._approval('确认整批发票修改', body, mode) is True,
                        approve_item=lambda body: self._item_decision(body),
                        checkpoint=lambda request: self.store.checkpoint(seq, request), display_items=items)
                    operation = {'status': status, 'changes': items}
                    agent.last_response['host_execution'] = operation
                    if status == 'UNKNOWN_OUTCOME':
                        state = 'UNKNOWN_OUTCOME'
                    agent.last_response['text'] = summary
                elif agent.update_session.drafts and self._confirm is not None:
                    draft, = agent.update_session.drafts.values()
                    body = (f'发票 {draft.company_id}／{draft.invoice_no}\n'
                            f'{draft.field}：{draft.old_value} → {draft.new_value}\n尚未保存。')
                    if self._approval('确认发票修改', body, 'single') is True:
                        self.store.checkpoint(seq, draft.request_id)
                        try:
                            agent.commit_update(draft.request_id, draft.fingerprint())
                        except Exception:
                            agent.coordinator.require_update_verification(draft, None)
                            state = 'UNKNOWN_OUTCOME'
                    else:
                        agent.cancel_update()
                    agent.last_response['text'] = agent.write_receipt['message']
                if agent.coordinator.has_unverified_update:
                    state = 'UNKNOWN_OUTCOME'
                output = (agent.last_response or {}).get('text', '')
            except Exception:
                # Never turn a failed delivery into a claim that no transaction
                # happened. The original checkpoint/owner remains authoritative.
                state = 'UNKNOWN_OUTCOME' if agent.coordinator.has_unverified_update else 'INTERRUPTED'
                self._save(seq, offset, '本轮中断，请核查当前状态。', state=state, operation=operation)
                raise
            self._save(seq, offset, output, state=state, operation=operation)
        return self.snapshot()

    def _item_decision(self, body):
        answer = self._approval('逐张确认发票修改', body, 'item')
        return 'confirm' if answer is True else 'skip' if answer == 'skip' else None

    def _navigate(self, expected, change):
        with self._command(expected):
            if self._agent.coordinator.has_unverified_update:
                raise SessionConflict('Inspect the original unknown submission before switching')
            if self._agent.update_session.drafts or self._agent.pending_intent:
                raise SessionConflict('Pause or cancel unfinished work before switching')
            change()
            self._agent.cancel_update(retire_request=True)
            self._agent._retired = True
            self._restore()
        return self.snapshot()

    def new_conversation(self, *, expected):
        return self._navigate(expected, lambda: self.store.new_chat(None))

    def switch_conversation(self, chat, *, expected):
        return self._navigate(expected, lambda: self.store.switch_chat(chat))

    def resume_candidate(self, candidate_id, revision, *, expected):
        with self._command(expected):
            if (self._agent.coordinator.has_unverified_update or self._agent.update_session.drafts
                    or self._agent.pending_intent):
                raise SessionConflict('Finish or pause the current work before restoring another candidate')
            pending = self.store.resume_invoice_candidate(candidate_id, revision)
            self._agent.restore_invoice_candidate(pending)
            self._agent.paused_invoice_candidate = None
        return self.snapshot()

    def pause_current(self, *, expected):
        with self._command(expected):
            pending = self._agent.pause_invoice_update()
            if pending is None:
                raise SessionConflict('No original invoice candidate exists to pause')
            try:
                self.store.set_invoice_pending(pending, state='PAUSED')
            except (OSError, ValueError, sqlite3.Error):
                self._persistence = {'status': 'FAILED', 'message': '暂缓未能保存，不能宣布可恢复。'}
                raise
            self._persistence = {'status': 'SAVED', 'error': None}
        return self.snapshot()

    def cancel_current(self, *, expected):
        with self._command(expected):
            self._agent.cancel_update(retire_request=True)
            self._agent.paused_invoice_candidate = None
            try:
                self.store.set_invoice_pending(None, state='CANCELLED')
                self.store.set_reference_state(self._agent.context.reference_state_snapshot())
            except (OSError, ValueError, sqlite3.Error):
                self._persistence = {'status': 'FAILED', 'message': '运行中操作已取消，但取消记录保存失败。'}
                raise
            self._persistence = {'status': 'SAVED', 'error': None}
        return self.snapshot()

    def inspect_submission(self, *, expected):
        with self._command(expected):
            self._agent.reconcile_update()
        return self.snapshot()
