"""Presentation adapter for local TUI sessions and read-only restoration."""
import json
import sqlite3

from .cli_chat import safe_text
from .cli_workspaces import company_access
from .provenance import ANNUAL
from .responses import explicit_scope, render_reference_error
from .session_store import SessionBusyError, SessionStore
from .tasks import task_details
from .updates import inspect_request


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
        self.has_saved_history = False
        self.saved_records = []

    def restore_conversation(self):
        history = self.conversation.history()
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
            if turn["calls"]:
                self.saved_records.append((turn["state"],turn["mode"],turn["calls"]))
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
        self.resumed = self.resumed[-6:]
        self.resume_displays = self.resume_displays[-64:]
        self.saved_records = self.saved_records[-20:]
        if self.has_saved_history:
            for selector in ("#chat-log", "#business-log"):
                self.workspace_widget(selector).scroll_end(animate=False)
            self.note("已继续上次对话。当前业务状态将在查询时重新读取。")
        return self.has_saved_history

    def remember_focus(self):
        if self.conversation:
            try:
                self.conversation.select_focus(self.read_workspace, self.task_focus)
            except (OSError, ValueError, sqlite3.Error):
                self.notify("当前焦点无法保存，请核对工作库。", severity="warning")

    def save_turn(self, calls, status, read_only):
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
        try:
            evidence = [{**call,"id":self.storage_text(call["id"])} for call in calls]
            self.conversation.finish(self.turn_seq, self.turn_display, evidence, self.agent.trace_id, hint, state)
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
