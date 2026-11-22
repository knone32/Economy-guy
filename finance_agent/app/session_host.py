"""Trusted in-process frontend adapter; business state stays in its existing owners.

Call on a host worker. Confirmation callbacks must be supplied by the trusted
human UI, never by an RPC/model payload. This is not authentication or a server.
"""
from contextlib import contextmanager
from dataclasses import asdict
import json
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

    def __init__(self, store, agent_factory, *, confirm=None, require_display_ack=False, profiles=None):
        self.store, self._factory, self._confirm = store, agent_factory, confirm
        self.require_display_ack = require_display_ack
        if profiles is None:
            from .session_profiles import ExistingProfiles
            profiles = ExistingProfiles()
        self.profiles = profiles
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
                or self._agent_chat != self.store.chat or self._agent._retired):
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
        self._agent = self._hydrate(self._factory(self.store.actor,self.store.workbook))
        self._agent_chat = self.store.chat

    def _hydrate(self, agent):
        history = self.store.history()
        if (agent.user_id != self.store.actor
                or Path(agent.db_path).resolve() != self.store.workbook.resolve()
                or agent._active or agent._retired or len(agent.messages) != 1):
            raise SessionConflict('Factory must supply a fresh, correctly bound Agent')
        agent.workbook_guard = self.store.validate_invoice_revision
        agent.defer_display_anchors = self.require_display_ack
        agent.restore_business_request(history['business_request'])
        # Structured current state wins over all historical text and old hints.
        agent.context.restore_query_hints(
            [{'reference_state': history['reference_state']}] if history['reference_state'] is not None else [])
        agent.context.display_ids = [turn['trace'] for turn in history['turns']
            if turn['seq'] > history['boundary'] and turn['state'] == 'COMPLETED' and turn.get('trace')
            and (turn.get('hint') or {}).get('display_acknowledged') is True][-64:]
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
        if (not history['business_request'] and history.get('task') and not pending
                and not agent.coordinator.has_unverified_update):
            agent.focus_task(*history['task'])
        return agent

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
        historical = cancelled or paused or bool(response.get('display_retired'))
        results = response.get('tool_results') or []
        current_result = {'text': response.get('text'), 'category': response.get('category'),
                          'coverage': response.get('business_request_final_coverage'),
                          'cards': render_information(results) if results else ''}
        candidates = self.store.list_invoice_candidates()
        token = self.store.invoice_token
        paused_data = json.loads(json.dumps(pending,ensure_ascii=False)) if paused else None
        saved_pause = paused and any((row['id'],row['revision']) == token and row['state'] == 'PAUSED'
                                     and row['pending'] == paused_data for row in candidates)
        status = ('UNKNOWN_OUTCOME' if agent.coordinator.has_unverified_update else
                  'CANCELLED' if cancelled else
                  receipt['status'] if saved else
                  response['host_execution']['status'] if response.get('host_execution') else
                  'PAUSE_FAILED' if self._persistence['status'] == 'FAILED'
                      and self._persistence.get('stage') == 'pause' else
                  'PAUSED' if saved_pause and self._persistence['status'] != 'FAILED' else
                  'WAITING_CONFIRMATION' if preview else
                  'WAITING_USER' if pending else
                  'PROPOSAL_READY' if proposal else
                  'COMPLETE' if (current_result['coverage'] or {}).get('complete') else
                  'WAITING_USER' if response.get('category') in {'clarification', 'reference_error'} else 'IDLE')
        return redact({'version': 1, 'context': self._token(), 'busy': self._lock.locked(),
            'actor': self.store.actor, 'workbook': self.store.identity,
            'binding_mode': 'trusted_local_simulation_not_login_authentication',
            'model': agent.connection.metadata() if agent.connection else None,
            'task_focus': self.store.history().get('task'),
            'tasks': self.list_tasks(),
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
            'display': ({'trace': agent.trace_id, 'acknowledged': response.get('display_acknowledged') is True}
                        if self.require_display_ack and results and not self._lock.locked()
                        and self._display_ready() else None),
            'conversation': self.conversation_view(),
            'result': current_result if not historical else None,
            'workspace': response.get('ui_result') if not historical else None,
            'historical_result': current_result if historical else None})

    def conversation_view(self):
        """Same-frame presentation data, so a busy frontend never joins live Store data to an old Agent."""
        self._binding()
        from .cli_workspaces import company_access
        permitted = {row['company_id'] for row in company_access(self.store.workbook,self.store.actor) if row['read']}
        history = self.store.history()
        turns = []
        for turn in history['turns'][-60:]:
            companies = set((turn.get('operation') or {}).get('companies',()))
            for call in turn.get('calls') or []:
                scope = call.get('scope') or {}
                companies.update(scope.get('company_ids') or ([scope['company_id']] if scope.get('company_id') else []))
            if companies - permitted:
                continue
            turns.append({key:turn.get(key) for key in ('seq','state','request','display','lookup','operation')})
        return {'chat':self.store.chat,'chats':self.store.list_chats(),'turns':turns}

    def acknowledge_display(self, trace, *, expected):
        """Called after the browser renders this actual response; never accepts rows or identities."""
        with self._command(expected):
            agent = self._agent
            response = agent.last_response or {}
            if trace != agent.trace_id or not self._display_ready():
                raise SessionConflict('Display is not the current actual response')
            if response.get('display_acknowledged') is not True:
                anchors = response.get('display_anchors')
                if anchors is None:
                    anchors = agent.record_query_display(response['tool_results'])
                if anchors is None:
                    raise OSError('展示引用未能登记，请使用明确企业和票号。')
                response['display_anchors'] = anchors
                self.store.acknowledge_display(trace, agent.context.reference_state_snapshot())
                response['display_acknowledged'] = True
        return self.snapshot()

    def manage_preference(self, company, action, key, value, *, expected):
        """Use the same source-bound management confirmation as TUI settings."""
        from .persistence import ManagementIntent,ManagementTurn,confirm_management
        from .preferences import manage_preference
        from .stage2_schema import open_existing
        from contextlib import closing
        personal=company is None
        if (action not in ({'set','delete'} if personal else {'create','update','delete'}) or type(key) is not str or type(value) is not str
                or len(key)>80 or len(value)>500 or redact([key,value])!=[key,value]):
            raise ValueError('请选择有效偏好操作并移除可能的凭据。')
        with self._command(expected):
            self._transition_ready();actor=self.store.actor
            text='企业偏好：'+str(company)+'；'+str(key)+'；'+str(value)
            intent=ManagementIntent(actor,'display_preference' if personal else 'preference',text,action,turn=ManagementTurn(actor))
            def service(witness):
                if personal:return self.store.manage_detail(action,value,witness)
                return manage_preference(self.store.workbook,actor,company,action,key,value,witness)
            try:
                proposed=service(intent)
                if proposed['status']!='WAITING_CONFIRMATION':raise SessionConflict(proposed.get('error') or '偏好未准备。')
                old=(proposed['data'].get('current') or {}).get('value','（无）')
                body=f'当前账号 {actor}\n企业 {company}\n偏好 {key}\n原值 {old}\n新值 {value if action!="delete" else "（删除）"}\n仅影响表达偏好，不修改发票或权限。'
                if self._approval('确认企业偏好更改',body,'preference') is True:
                    outcome=service(confirm_management(intent,proposed['data']))
                    message=('偏好已保存并回读。' if outcome['status']=='SUCCESS' and outcome.get('evidence',{}).get('preference_readback_verified')
                             else outcome.get('error') or '偏好当前值尚未核实，请重新查询。')
                else:message='已取消企业偏好修改，未保存。'
                seq=self.store.begin(text,self._agent.mode);self._agent.trace_id=uuid4().hex
                self._agent.last_response={'category':'operation_result','text':message,'tool_results':[]}
                self._save(seq,len(self._agent.messages),message)
            finally:intent.turn.active=False
        return self.snapshot()

    def _display_ready(self):
        response = self._agent.last_response or {}
        return bool(response.get('tool_results') and response.get('category') in {'database_query','clarification'}
                    and not response.get('host_execution') and not response.get('display_retired')
                    and not self._agent.coordinator.has_unverified_update)

    def list_conversations(self):
        self._binding()
        return self.store.list_chats()

    def list_profiles(self):
        self._binding()
        return self.profiles.list(self.store.actor)

    def _transition_ready(self):
        agent = self._agent
        if agent._active or agent.coordinator.has_unverified_update:
            raise SessionConflict('运行中或提交结果未知，请先完成处理或只读核查。')
        if (agent.pending_intent or agent.pending_edit or agent.update_session.drafts
                or agent.update_session.confirmations or self.store.history().get('invoice_pending')):
            raise SessionConflict('当前有待补或预览，请先明确暂缓或取消。')
        request = agent.business_request or agent._last_business_request
        waiting = (agent.last_response or {}).get('execution',{}).get('stop_reason') == 'WAITING_CONFIRMATION'
        if (request is not None and request.unresolved) or (waiting and agent.management_proposals and agent.management_proposals.active):
            raise SessionConflict('当前要求仍待澄清或确认，请先完成或取消。')

    def list_tasks(self):
        self._binding()
        from .cli_workspaces import company_access
        from .tasks import list_tasks
        return [list_tasks(self.store.workbook,self.store.actor,row['company_id'])
                for row in company_access(self.store.workbook,self.store.actor) if row['read']]

    def task_details(self, company_id, task_id):
        self._binding()
        from .tasks import task_details
        return task_details(self.store.workbook,self.store.actor,company_id,task_id)

    def open_task(self, company_id, task_id, *, expected):
        with self._command(expected):
            self._transition_ready()
            old = self._agent
            new = (old.switch_model(old.connection,retire_current=False) if old.connection
                   else self._factory(self.store.actor,self.store.workbook))
            new.workbook_guard = self.store.validate_invoice_revision
            new.defer_display_anchors = self.require_display_ack
            new.continuity = None
            outcome = new.focus_task(company_id,task_id,retire_previous=False)
            if not outcome.get('ok') or not (outcome.get('data') or {}).get('can_execute'):
                raise SessionConflict(outcome.get('error') or '当前待办不可办理，请核对权限、账期和规则。')
            task = outcome['data']['task']
            self.store.select_focus((company_id,task['year'],task['month']),(company_id,task_id),retire_request=True)
            old.cancel_update(retire_request=True)
            old.retire_session()
            self._agent = new
            self._persistence = {'status':'SAVED','error':None}
        return self.snapshot()

    def switch_profile(self, name, *, expected):
        if type(name) is not str or not name:
            raise SessionConflict('请选择已有的 Profile 名称。')
        with self._command(expected):
            self._transition_ready()
            old = self._agent
            connection = self.profiles.resolve(self.store.actor,name)
            new = self._hydrate(old.switch_model(connection,retire_current=False))
            old.retire_session()
            self._agent = new
            self._persistence = {'status':'UNCHANGED','message':'已切换本次宿主配置；未写入配置文件。'}
        return self.snapshot()

    def rebind(self, binding_factory, *, expected):
        """Python-only trusted-host handoff, never a browser-supplied actor/path.

        factory() must return a host-authorized (SessionStore, agent_factory,
        ExistingProfiles) tuple. Browser selectors must be resolved by that host
        policy first. Local simulated accounts are not login authentication.
        """
        with self._command(expected):
            self._transition_ready()
            if not callable(binding_factory):
                raise SessionConflict('重新绑定只能由受信宿主提供。')
            target_store = None
            try:
                target_store, factory, profiles = binding_factory()
                if target_store is self.store:
                    raise SessionConflict('新的绑定必须使用重新核验的会话。')
                replacement = SessionHost(target_store,factory,confirm=self._confirm,
                    require_display_ack=self.require_display_ack,profiles=profiles)
                replacement.snapshot()
            except Exception:
                if target_store is not None and target_store is not self.store:
                    target_store.close()
                raise
            self._agent.retire_session()
            self.store.close()
        return replacement

    def _save(self, seq, offset, text, *, state='COMPLETED', operation=None):
        agent = self._agent
        pending = agent.pending_intent or getattr(agent, 'paused_invoice_candidate', None)
        if pending and pending.get('business_action') != 'single_invoice':
            pending = None
        references = agent.context.reference_state_snapshot()
        if self.require_display_ack and self._display_ready() and not (agent.last_response or {}).get('display_acknowledged'):
            # A restart before the browser's render acknowledgement must not
            # promote a fetched-but-unseen row to a displayed reference.
            references = {'version':1,'retired':True,'invoice_query':None}
        hint = {'reference_state': references,
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
            previous = agent.last_response or {}
            if (self.require_display_ack and self._display_ready()
                    and previous.get('display_acknowledged') is not True):
                raise SessionConflict('Render and acknowledge the current actual result before continuing')
            seq = self.store.begin(self._storage_text(text), agent.mode)
            offset = len(agent.messages)
            state, operation = 'COMPLETED', None
            try:
                agent.ask(text)
                if getattr(agent,'started_new_matter',False):
                    self.store.detach_inactive_for_new_matter(seq)
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

    def read_business(self, name, arguments, *, expected):
        """Structured UI equivalent of the existing TUI read-only menus.

        No model proposal or SQL is accepted; original Handler ACL/schema and
        the existing save/render/ACK path remain authoritative.
        """
        allowed={'list_invoice_directory','get_invoice','list_bank_transactions',
            'get_finance_summary','check_missing_purpose','get_applicable_rules',
            'list_rule_versions','list_materials','open_material_reference','manage_preference'}
        if name not in allowed or type(arguments) is not dict:
            raise SessionConflict('该入口只允许已登记的只读业务查询。')
        if name=='manage_preference' and arguments.get('action')!='list':
            raise SessionConflict('偏好写入必须走原预览确认入口。')
        from .tool_registry import handle_tool,validate_arguments
        from .provenance import ScopeProof
        from .responses import render_tool_failure
        with self._command(expected):
            self._transition_ready()
            if self.require_display_ack and self._display_ready() and not (self._agent.last_response or {}).get('display_acknowledged'):
                raise SessionConflict('请先展示并核对当前查询结果。')
            args=validate_arguments(name,json.dumps(arguments,ensure_ascii=False))
            agent=self._agent
            scope={key:[args[key]] for key in ('company_id','year','month','invoice_no') if key in args}
            if args.get('year') and args.get('month'):scope['periods']=[(args['year'],args['month'])]
            labels={'list_invoice_directory':'发票目录','get_invoice':'发票详情','list_bank_transactions':'银行流水',
                'get_finance_summary':'综合汇总','check_missing_purpose':'用途缺项','get_applicable_rules':'适用规则',
                'list_rule_versions':'规则版本','list_materials':'业务资料','open_material_reference':'资料原文','manage_preference':'企业偏好'}
            text='界面只读查询：'+labels[name]+'；企业 '+str(args.get('company_id',''))
            if args.get('year'):text+='；%s年%s月'%(args['year'],args.get('month',0))
            if args.get('invoice_no'):text+='；发票 '+args['invoice_no']
            seq=self.store.begin(text,agent.mode);offset=len(agent.messages)
            agent.trace_id=uuid4().hex
            agent.coordinator.begin(text)
            agent.business_request=agent._last_business_request=None
            agent.context.begin(text,len(agent.messages),explicit=scope)
            raw=json.dumps(args,ensure_ascii=False);call_id='ui-'+agent.trace_id
            result=handle_tool(name,raw,self.store.actor,self.store.workbook,
                allowed_tools=agent.allowed_tools,expected_scope=scope,
                provenance=ScopeProof(self.store.actor,scope,dict.fromkeys(scope,'user_current')))
            output=render_information([(name,result)]) if result['ok'] else render_tool_failure(result['status'],name,result)
            agent.messages.extend([{'role':'user','content':text},
                {'role':'assistant','content':None,'tool_calls':[{'id':call_id,'type':'function',
                    'function':{'name':name,'arguments':raw}}]},
                {'role':'tool','tool_call_id':call_id,'content':json.dumps(result,ensure_ascii=False)},
                {'role':'assistant','content':output}])
            agent.last_response={'category':'database_query','text':output,'tool_results':[(name,result)],
                'write_expected':False,'delivery_source':'structured_ui_original_service',
                'ui_result':{'name':name,'arguments':args,'result':result},
                'execution':{'model_requests':0,'actual_tool_calls':1,'stop_reason':result['status']}}
            self._save(seq,offset,output)
        return self.snapshot()

    def _item_decision(self, body):
        answer = self._approval('逐张确认发票修改', body, 'item')
        return 'confirm' if answer is True else 'skip' if answer == 'skip' else None

    def _navigate(self, expected, change):
        with self._command(expected):
            self._transition_ready()
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
            self._agent.coordinator.cancel_update()
            self._agent.coordinator.receipt=self._agent._receipt('NOT_SUBMITTED')
            self._agent.restore_invoice_candidate(pending)
            self._agent.paused_invoice_candidate = None
            if self._agent.last_response:
                self._agent.last_response['display_retired'] = True
            self._persistence = {'status':'SAVED','error':None}
        return self.snapshot()

    def pause_current(self, *, expected):
        with self._command(expected):
            pending = self._agent.pause_invoice_update()
            if pending is None:
                raise SessionConflict('No original invoice candidate exists to pause')
            if self._agent.last_response:
                self._agent.last_response['display_retired'] = True
            try:
                self.store.set_invoice_pending(pending, state='PAUSED',
                    reference_state=self._agent.context.reference_state_snapshot())
            except (OSError, ValueError, sqlite3.Error) as error:
                # Failure to persist a pause is not a successful runtime pause.
                # Restore only the same unapproved business candidate through
                # its original validation owner; drafts/approvals stay retired.
                self._agent.paused_invoice_candidate = None
                restored = False
                try:
                    self._agent.restore_invoice_candidate(pending)
                    restored = True
                except (OSError,ValueError,PermissionError,sqlite3.Error):
                    pass
                self._persistence = {'status': 'FAILED', 'error':type(error).__name__,
                    'stage':'pause','pending_restored':restored,
                    'message': '暂缓未能保存，不能宣布可恢复。'}
                raise SessionConflict('暂缓未能保存，不能宣布可恢复；当前业务尚未提交。') from error
            self._persistence = {'status': 'SAVED', 'error': None}
        return self.snapshot()

    def cancel_current(self, *, expected):
        with self._command(expected):
            self._agent.cancel_update(retire_request=True)
            if self._agent.last_response:
                self._agent.last_response['display_retired'] = True
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
