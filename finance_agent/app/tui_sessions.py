"""Presentation adapter for local TUI sessions and read-only restoration."""
import json
import sqlite3

from .cli_chat import safe_text
from .cli_workspaces import company_access
from .provenance import ANNUAL
from .responses import explicit_scope, render_reference_error, render_invoice_pending
from .session_store import SessionBusyError, SessionStore
from .tasks import task_details
from .updates import inspect_request
from .business_sources import recover_candidate
from .invoice_action import public_state as invoice_business_state


BUSINESS_RECORD = "业务记录 / "
_LEGACY_BUSINESS = {"查询与处理结果", "业务回执", "发票回执", "当前待办", "待办回执", "待办未保存"}


def business_title(role):
    if role.startswith(BUSINESS_RECORD):
        return role.removeprefix(BUSINESS_RECORD).partition(" / ")[2]
    if role.startswith("业务核验 / "):
        return role.removeprefix("业务核验 / ")
    return role if role in _LEGACY_BUSINESS else None


def _legacy_sql_rows(body):
    """Recover saved evidence rows while leaving the original session entry intact."""
    _, marker, display = body.partition("\n列 ")
    if not body.startswith("SQL\n") or not marker:
        return body
    header, _, rows = display.partition("\n")
    columns = header.split(" · ")
    lines = []
    decoder = json.JSONDecoder()
    for line in rows.splitlines():
        if line.startswith("["):
            try:
                values, offset = decoder.raw_decode(line)
            except ValueError:
                lines.append(line)
                continue
            if isinstance(values, list) and len(values) == len(columns):
                line = " · ".join(f"{key} {value}" for key, value in zip(columns, values)) + line[offset:]
        lines.append(line)
    return "\n".join(lines)


QUERY_TOOLS = ANNUAL | {"get_finance_summary", "list_invoices", "list_invoice_directory", "check_missing_purpose",
               "get_invoice", "resolve_invoice_reference", "list_bank_transactions", "get_applicable_rules"}


def query_scopes(calls):
    scopes = {}
    for call in calls:
        scope = call.get("scope") or {}
        if (call["tool"] in QUERY_TOOLS and call["status"] in {"SUCCESS", "NO_DATA"}
                and scope.get("company_id")):
            scopes[(scope["company_id"], scope.get("year"), scope.get("month"))] = None
    return tuple(scopes)


class ConversationUI:
    def close_conversation(self):
        if self.conversation:
            self.conversation.close()
            self.conversation = None

    def open_conversation(self):
        self.clear_conversation_history()
        self.conversation_blocked = False
        if self.session_path is None:
            return False
        try:
            self.conversation = SessionStore(self.session_path, self.db, self.user)
            return self.restore_conversation()
        except SessionBusyError:
            self.conversation_blocked = True
            self.note("此账号的账簿对话已在另一窗口打开。请关闭后重新登录。")
        except (OSError, ValueError, sqlite3.Error):
            self.close_conversation()
            self.notify("无法打开本机会话存储。当前聊天仅保存在进程内。", severity="warning")
        return False

    def clear_conversation_history(self):
        self.resumed, self.resume_displays, self.resume_focus = [], [], None
        self.resume_invoice_pending = None
        self.has_saved_history = False
        self.saved_records = []

    def restore_conversation(self):
        history = self.conversation.history()
        reference_state = None
        permitted = {row["company_id"] for row in company_access(self.db,self.user) if row["read"]}
        focus = history["focus"]
        if focus and focus[0] in permitted:
            self.read_workspace = tuple(focus)
            self.company, year, month = self.read_workspace
            self.period = year, month
        task = history["task"]
        if task and task[0] in permitted:
            found = task_details(self.db, self.user, *task)
            if found["ok"] and found["data"]["can_execute"]:
                self.task_focus = tuple(task)
        for turn in history["turns"]:
            # State retirement is not model history. Apply it even when a long
            # request, management filter or lost read permission hides the body.
            state = (turn.get('hint') or {}).get('reference_state')
            if (turn['seq'] > history['boundary'] and type(state) is dict
                    and (turn['state'] == 'COMPLETED' or state.get('retired') is True)):
                reference_state = state
                if state.get('retired') is True:
                    self.resume_displays = []
            scopes = [call.get("scope") or {} for call in turn["calls"]]
            scoped = {scope.get("company_id") for scope in scopes}
            scoped.update(company for scope in scopes for company in scope.get("company_ids", ()))
            scoped.update(explicit_scope(turn["request"], include_update_aliases=True).get("company_id", ()))
            for role, _ in turn["display"]:
                if role.startswith(BUSINESS_RECORD):
                    companies, _, _ = role.removeprefix(BUSINESS_RECORD).partition(" / ")
                    scoped.update(filter(None, companies.split(",")))
            if (scoped - {None}) - permitted:
                continue
            self.has_saved_history = True
            if turn["request"] or turn["calls"]:
                self.saved_records.append({
                    **turn["operation"], "seq": turn["seq"], "state": turn["state"], "mode": turn["mode"],
                    "calls": turn["calls"], "trace": turn["trace"], "lookup": turn["lookup"],
                    "companies": sorted((scoped - {None}) | set(turn["operation"].get("companies", ()))),
                })
            if turn["request"]:
                self.chat_message("你", turn["request"])
            for role, body in turn["display"]:
                # Older builds persisted the resolver envelope in visible history.
                prefix = "请明确引用对象："
                if role == "Agent" and body.startswith(prefix):
                    try:
                        status = json.loads(body[len(prefix):]).get("status")
                    except (ValueError, AttributeError):
                        status = None
                    body = render_reference_error(status if isinstance(status, str) else None)
                if role == "业务核验 / SQL 查询证据":
                    body = _legacy_sql_rows(body)
                self.chat_message(role, body)
            if turn["state"] == "INTERRUPTED":
                self.chat_message("会话状态", "上次处理被中断。请重新提出查询。")
            elif turn["state"] == "UNKNOWN_OUTCOME":
                message = "上次操作结果待核实。请检查执行记录及当前业务状态。"
                if turn["lookup"]:
                    audit = inspect_request(self.db, self.user, turn["lookup"])
                    if audit["status"].startswith("COMMITTED"):
                        message = "已在 SQLite 成功审计中核实上次提交。请查看当前发票。"
                self.chat_message("会话状态", message)
            if turn["state"] != "COMPLETED" or turn["seq"] <= history["boundary"]:
                continue
            scopes = query_scopes(turn["calls"])
            if scopes:
                self.query_focus = scopes
            if turn["trace"]:
                self.resume_displays.append(turn["trace"])
            if turn["hint"] and turn["request"]:
                hint = turn["hint"]
                focus = hint.get("focus")
                if len(turn["request"]) <= 2000 and (not focus or focus[0] in permitted):
                    self.resumed.append({"request":turn["request"], **hint})
                self.resume_focus = tuple(focus) if focus and focus[0] in permitted else None
        # Idle F4 can update this snapshot without adding a transcript turn.
        # It is newer than any retained per-turn hint and must win restoration.
        if history.get('reference_state') is not None:
            reference_state = history['reference_state']
            if reference_state.get('retired') is True:
                self.resume_displays = []
        self.resumed = self.resumed[-6:]
        if reference_state is not None:
            self.resumed.append({'request': '', 'reference_state': reference_state})
        self.resume_displays = self.resume_displays[-64:]
        self.saved_records = self.saved_records[-20:]
        self.resume_invoice_pending = None
        if history.get('invoice_pending') is not None:
            try:
                self.resume_invoice_pending = recover_candidate(history['invoice_pending'], actor=self.user, book=self.db)
            except (OSError, ValueError, PermissionError, sqlite3.Error) as error:
                self.conversation.set_invoice_pending(None)
                self.chat_message('会话状态', str(error))
            else:
                state = invoice_business_state(self.resume_invoice_pending)
                labels = {'company_id':'企业','year':'年','month':'月','invoice_no':'票号',
                          'field':'字段','new_value':'新内容','change_choice':'字段及内容',
                          'invoice_selection':'目标核验'}
                known = '；'.join(f'{labels[key]}：' + ({'purpose':'用途','remark':'备注'}.get(value,value)
                    if key == 'field' else str(value)) for key,value in state['known'].items())
                missing = '、'.join(labels.get(key,key) for key in state['missing_fields'])
                self.chat_message('会话状态', '已找回未提交的单票候选。' + known + '\n仍需补充：' + missing
                    + '。请明确继续或更正；之后会重新核权、读取当前发票并给出新的确认预览。尚未保存。')
        if self.has_saved_history:
            for selector in ("#chat-log", "#business-log"):
                self.workspace_widget(selector).scroll_end(animate=False)
            self.note("已继续上次对话。当前业务状态将在查询时重新读取。")
        if self.conversation.list_invoice_candidates():
            self.chat_message('待续发票修改', '有尚未保存的发票修改，可在“待办”中选择继续办理。恢复后仍须核对新的确认预览，历史内容不提供批准。')
        return self.has_saved_history

    def invoice_candidate_text(self, row):
        state=invoice_business_state(row['pending']);known=state['known']
        company=self.company_name(known['company_id']) if known.get('company_id') else '企业待补充'
        return render_invoice_pending(state,company_name=company,paused=row.get('state')=='PAUSED')

    def show_invoice_candidates(self):
        if not self.conversation:
            self.note('当前未启用本地会话存储。')
            return
        rows = self.conversation.list_invoice_candidates()
        from .tui_screens import Choices
        choices=[(self.invoice_candidate_text(row),(row['id'],row['revision'])) for row in rows]
        if not choices:choices=[('没有可继续办理的发票修改。',None)]
        owner=self.conversation;identity=(self.user,self.db,self.session_epoch)
        def resume(selected):
            if selected is None:return
            if self.busy or self.conversation is not owner or identity!=(self.user,self.db,self.session_epoch):
                self.note('当前会话已变化，请重新打开待办选择。');return
            try:self.resume_invoice_selection(f'{selected[0]} {selected[1]}')
            except (OSError,ValueError,PermissionError,sqlite3.Error) as error:
                self.note(str(error) or '该修改已变化，请重新打开待办选择。')
        self.push_screen(Choices('选择要继续的发票修改',choices),resume)

    def resume_invoice_selection(self, argument):
        if not self.conversation:
            raise ValueError('当前未启用本地会话存储。')
        if self.agent and (self.agent.pending_intent or self.agent.pending_edit):
            raise ValueError('请先 /pause 暂缓或 /cancel 取消当前事项。')
        candidate_id, revision = argument.split()
        candidate = self.conversation.resume_invoice_candidate(candidate_id,int(revision))
        self.reset_agent(clear_log=False,retire_candidate=False)
        self.resume_invoice_pending = candidate
        self.select_pane('chat')
        summary=self.invoice_candidate_text({'pending':candidate,'state':'ACTIVE'})
        self.chat_message('待续发票修改', '已恢复：'+summary+'\n请补充或更正办理内容；系统会重新核权、读取当前值并生成新预览，尚未批准或保存。')

    def pause_invoice_selection(self):
        if not self.conversation:
            self.note('当前未启用本地会话存储，无法跨聊天暂缓。')
            return
        self.conversation.pause_invoice_candidate()
        self.reset_agent(clear_log=False,retire_candidate=False)
        self.resume_invoice_pending = None
        self.note('已暂缓发票修改，可在“待办”中选择继续办理；尚未保存。')

    def retire_invoice_candidate(self):
        """Persist trusted out-of-turn cancellation, even before Agent creation."""
        self.resume_invoice_pending = None
        if self.conversation:
            self.conversation.set_invoice_pending(None)

    def remember_focus(self):
        if self.conversation:
            try:
                self.conversation.select_focus(self.read_workspace, self.task_focus)
            except (OSError, ValueError, sqlite3.Error):
                self.notify("当前焦点无法保存，请核对工作库。", severity="warning")

    def save_turn(self, calls, status, read_only, *, operation=None):
        if self.turn_seq is None or not self.conversation:
            return
        read_tools = ANNUAL | {"get_finance_summary","list_invoices","list_invoice_directory",
                      "check_missing_purpose","get_invoice","resolve_invoice_reference","list_bank_transactions"}
        reads = [call for call in calls if call["status"] in {"SUCCESS","NO_DATA"} and call["tool"] in read_tools]
        focus = {(scope["company_id"],scope["year"],scope.get("month", 0)) for call in reads
                 if {"company_id","year"} <= (scope := call.get("scope") or {}).keys()}
        state = status if status in {"UNKNOWN_OUTCOME","INTERRUPTED"} else "COMPLETED"
        hint = None
        annual_focus = self.agent.context.annual_focus
        retired_annual_focus = self.resume_focus and self.resume_focus[2] == 0 and not annual_focus
        if read_only and state == "COMPLETED" and (
                reads or retired_annual_focus or self.agent.last_response.get("category") == "clarification"):
            next_focus = annual_focus or (next(iter(focus)) if len(focus) == 1 else None)
            hint = {"tools":[c["tool"] for c in reads], "focus":next_focus}
            if reads or retired_annual_focus:
                self.resume_focus = next_focus
        # Snapshot the reference owner's *post-turn* state, not earlier reads
        # from a turn which may have just been cancelled. Null is meaningful.
        hint = {**(hint or {}), 'reference_state': self.agent.context.reference_state_snapshot()}
        try:
            evidence = [{**call, "id": self.storage_text(call["id"]),
                         "error": self.storage_text(call["error"]) if call.get("error") else None} for call in calls]
            self.conversation.finish(self.turn_seq, self.turn_display, evidence, self.agent.trace_id, hint, state,
                                     operation=operation,
                                     invoice_pending=(self.agent.pending_intent if self.agent.pending_intent
                                         and self.agent.pending_intent.get('business_action') == 'single_invoice' else
                                         getattr(self.agent,'paused_invoice_candidate',None)),
                                     candidate_state=('PAUSED' if getattr(self.agent,'paused_invoice_candidate',None) else
                                         'CANCELLED' if status == 'CANCELLED' else
                                         'COMPLETED' if status in {'COMMITTED','COMMITTED_UNVERIFIED','CURRENT_VALUE_MATCHES','UNKNOWN_OUTCOME'}
                                         or any(change.get('status') in {'COMMITTED','COMMITTED_UNVERIFIED'} for change in (operation or {}).get('changes',[])) else None))
            self.has_saved_history = True
        except (OSError, ValueError, sqlite3.Error):
            self.notify("本轮历史保存失败。请检查执行记录与当前业务状态。", severity="warning")
        finally:
            self.turn_seq = None
            self.turn_display = []

    def storage_text(self, text):
        keys = set(self.session_keys.values())
        if self.agent and self.agent.connection:
            keys.add(self.agent.connection.api_key)
        for key in sorted(filter(None, keys), key=len, reverse=True):
            text = text.replace(key, "[REDACTED]")
        return safe_text(text)
