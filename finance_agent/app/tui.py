"""Single-session Agent workspace for interactive terminals."""
from concurrent.futures import Future, TimeoutError
from contextlib import closing
from dataclasses import asdict
import json
import os
import re
from pathlib import Path
import sqlite3

from rich.text import Text
from textual import on, work
from textual.app import App
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, ContentSwitcher, DataTable, Footer, Input, RichLog, Static
from textual.worker import get_current_worker

from .agent import Agent
from .cli_chat import safe_text, turn_tools
from .cli_workspaces import company_access, invoice_history, missing_migrations, workspace_users
from .model_config import ModelConnection, ProfileError, load_profiles, resolve_connection
from .persistence import ManagementIntent, ManagementTurn, confirm_management
from .queries import QueryError, available_periods, get_invoice, invoice_directory
from .responses import needs_progress_evidence, render_scope, scope_key, verified_task_progress
from .rules import RuleError, check_missing_purpose
from .stage2_schema import open_existing
from .tasks import list_tasks, manage_task, task_details
from .trace import redact
from .tui_intent import edit_turn
from .tui_local import remember_workbook, startup_workbook
from .tui_sessions import ConversationUI
from .tui_screens import Approval, Choices, Login, Settings, TaskNote, TextAction
from .win_vault import CredentialError, profile_target

ROOT = Path(__file__).resolve().parents[1]
STATUS = {
    "ANSWERED": "本轮回复完成", "COMPLETED": "本轮处理完成", "SUCCESS": "执行成功",
    "NO_DATA": "没有符合条件的记录", "NO_CHANGE": "当前无需变更",
    "WAITING_USER": "等待补充", "AMBIGUOUS": "请补充范围", "WAITING_CONFIRMATION": "等待确认",
    "COMMITTED": "已成功保存并核验", "CURRENT_VALUE_MATCHES": "当前值已相同",
    "DENIED": "权限不足", "ERROR": "本轮执行失败", "SCOPE_MISMATCH": "请求范围不一致", "CANCELLED": "已取消",
    "UNKNOWN_OUTCOME": "提交结果未知，请先查看执行记录再决定是否重试", "MODEL_LIMIT": "本轮处理达到上限",
    "TOOL_LIMIT": "本轮查询次数达到上限，请缩小范围后继续",
    "CONTEXT_LIMIT": "本轮内容太多，请缩小范围后继续",
    "INVALID_ARGUMENTS": "本轮未能确认查询或操作条件，请补充具体对象与范围",
    "CONFLICT": "当前状态有变化，请重新核对", "NOT_FOUND": "没有找到目标",
    "API_OR_RESPONSE_ERROR": "模型连接或响应失败，请检查设置与执行记录",
    "INVALID_RESPONSE": "模型回复格式无效，请重新描述",
    "PROTOCOL_ERROR": "模型响应异常，请查看执行记录",
    "RULE_CONFLICT": "当前规则存在冲突", "NO_APPLICABLE_RULE": "没有适用规则",
}
TASK_STATUS = {"ACTIVE": "进行中", "WAITING_USER": "等待补充", "PAUSED": "已暂停",
               "COMPLETED": "已完成", "CANCELLED": "已取消"}


def status_label(code):
    return STATUS.get(code, "本轮未核实完成，请查看执行详情")


def offline_model(messages, tools):
    """Two deterministic read examples for the development diagnostic."""
    current = next(m["content"] for m in reversed(messages) if m["role"] == "user")
    if messages[-1]["role"] == "tool":
        return {"role":"assistant","content":'{"kind":"information","text":"已返回本轮业务核验。"}'}
    from .responses import explicit_scope
    if re.search(r"用途|缺项", current) and re.search(r"未填|没填|没有填|缺|还剩", current):
        tool = "check_missing_purpose"
    elif re.search(r"收支|汇总|合计", current):
        tool = "get_finance_summary"
    else:
        return {"role":"assistant","content":'{"kind":"clarification","text":"固定脚本不支持这项请求，请配置真实 AI。","missing_fields":["live_model"]}'}
    data = next((json.loads(m["content"]) for m in messages if m.get("name") == "context_data"), {})
    scope = {**data.get("scope", {}), **data.get("read_workspace", {}).get("scope", {}), **explicit_scope(current, include_update_aliases=True)}
    company, periods = scope.get("company_id", []), scope.get("periods", [])
    if len(company) != 1 or len(periods) != 1:
        return {"role":"assistant","content":'{"kind":"clarification","text":"请选择明确企业和账期","missing_fields":["company_id","year","month"]}'}
    year, month = periods[0]
    return {"role":"assistant","tool_calls":[{"id":"offline-query","type":"function","function":{
        "name":tool,"arguments":json.dumps({"company_id":company[0],"year":year,"month":month})}}]}


class AgentWorkspace(ConversationUI, App):
    TITLE = "Economy-guy · 财税工作台"
    CSS_PATH = "tui.tcss"
    NAV_ITEMS = (("go-chat", "对话"), ("go-tasks", "待办"), ("go-finance", "发票"),
                 ("go-records", "记录"), ("account", "账户"))
    BINDINGS = [("f2", "navigation", "导航"), ("f3", "account", "账户"),
                ("f4", "cancel_edit", "取消未提交操作"), ("ctrl+q", "quit_safe", "退出")]

    def __init__(self, db, template, local, *, model=None, trace_path=None, recent_path=None, restore_recent=False, vault=None, session_path=None):
        super().__init__()
        self.db = Path(db).resolve()
        self.recent_path = recent_path
        self.restore_recent = restore_recent
        self.vault = vault
        self.session_path = session_path
        self.conversation = None
        self.conversation_blocked = False
        self.turn_seq = None
        self.turn_display = []
        self.resumed = []
        self.resume_focus = None
        self.resume_displays = []
        self.has_saved_history = False
        self.saved_records = []
        self.session_keys = {}
        self.profile_options = {"template": template, "local": local}
        self.trace_path = trace_path
        self.model_override = model
        self.agent = None
        self.user = None
        self.profile = None
        self.mode = "live"
        # Table browsing can follow a result; only an explicit UI selection sets the query scope.
        self.company = None
        self.period = None
        self.read_workspace = None
        self.busy = False
        self.supplement = False
        self.task_route = None
        self.task_focus = None
        self.invoice_route = None
        self.chat_invoice_route = None
        self.invoice_page = 1
        self.session_epoch = 0
        self.records = []
        self.model_requests = 0
        self.last_api_status = ""
        self.last_api_ok = None

    def compose(self):
        yield Static("Economy-guy", id="status", markup=False)
        yield TextAction("选择查询企业和账期", id="query-scope", classes="text-link")
        with Horizontal(id="layout"):
            with Vertical(id="rail"):
                for key, label in self.NAV_ITEMS:
                    if key == "account":
                        yield Static("", id="rail-spacer")
                    yield TextAction(label, id=key, classes="current" if key == "go-chat" else None)
            with ContentSwitcher(initial="chat", id="panes"):
                with Vertical(id="chat"):
                    yield RichLog(id="chat-log", markup=False, wrap=True)
                    with Horizontal(id="ai-guide"):
                        yield Static("", id="ai-guide-text", markup=False)
                        yield TextAction("配置 AI 模型", id="configure-ai", variant="primary")
                    yield TextAction("查看本轮发票目录", id="chat-invoices", classes="text-link")
                    yield Static("发送消息", id="composer-label", markup=False)
                    yield Static("", id="chat-note", markup=False)
                    yield TextAction("补充本次修改", id="supplement")
                    yield Input(placeholder="输入财税问题或修改要求，按 Enter 发送", id="prompt")
                with Vertical(id="tasks"):
                    yield Static("待办事项", classes="section", markup=False)
                    yield VerticalScroll(id="task-body")
                with Vertical(id="finance"):
                    yield Static("发票明细 · 只读", classes="section", markup=False)
                    yield VerticalScroll(id="finance-body")
                with Vertical(id="records"):
                    yield Static("执行记录 · 当前对话与本人成功审计", classes="section", markup=False)
                    yield VerticalScroll(id="record-list")
        yield Footer()

    def on_mount(self):
        self.workspace_widget("#chat-invoices").display = False
        self.db, needs_selection = startup_workbook(self.db, self.recent_path, restore=self.restore_recent)
        self.push_screen(Login(start_in_picker=needs_selection), self.signed_in)

    def signed_in(self, user):
        if not user:
            return
        try:
            if user not in {row["user_id"] for row in workspace_users(self.db)} or missing_migrations(self.db):
                raise ValueError()
        except (OSError, ValueError, sqlite3.Error):
            self.push_screen(Login(), self.signed_in)
            return
        self.user = user
        try:
            remember_workbook(self.recent_path, self.db)
        except OSError:
            self.notify("无法保存最近账簿，当前账簿仍可使用。", severity="warning")
        self.profile = None
        self.reset_agent(clear_log=True)
        self.note("可输入问题，按 Enter 发送。")
        if not self.open_conversation():
            self.chat_message("工作台", "可直接查询、提出修改、保存待办。发票和待办变更会弹出确认。"
                          "\n例如：把甲企业 F002 的用途改成资料打印。")
        self.show("chat")

    def on_unmount(self):
        self.close_conversation()

    def open_legacy_home(self):
        self.reset_agent(clear_log=True)
        self.exit("legacy_home")

    def set_workspace(self, path):
        workspace_users(path)
        if missing_migrations(path):
            raise ValueError("该工作库需要先加法升级。")
        if path == self.db:
            return
        self.db = path
        if self.user:
            self.logout()

    def model_changes(self, mode, profile, *, new_key=None):
        if mode != self.mode:
            return True
        if mode == "mock":
            return False
        try:
            target = self.resolve_profile(require_key=False, selection=profile).profile
            if self.agent and self.agent.connection:
                connection = self.agent.connection
                return (target != connection.profile or
                        (new_key if new_key is not None else self.current_key(target)) != connection.api_key)
            return target != self.resolve_profile(require_key=False).profile
        except ProfileError:
            return profile != self.profile

    def set_model(self, mode, profile):
        if self.model_changes(mode, profile):
            had_agent = self.agent is not None
            self.reset_agent(clear_log=False)
            if had_agent or self.has_saved_history:
                message = "模型连接已更换。上方文字可供回看。新的 AI 上下文从此处开始，未提交操作已取消。"
                self.resumed, self.resume_displays, self.resume_focus = [], [], None
                if self.conversation:
                    try:
                        self.conversation.boundary(message)
                    except (OSError, ValueError, sqlite3.Error):
                        self.notify("无法保存上下文分界。请先检查会话存储。", severity="warning")
                self.chat_message("会话分界", message)
        self.mode, self.profile = mode, profile
        self.update_header()

    def reset_agent(self, *, clear_log, keep_connection_state=False):
        if self.agent and self.agent.workbook_available():
            self.agent.cancel_update()
        self.agent = None
        self.task_focus = None
        self.chat_invoice_route = None
        self.workspace_widget("#chat-invoices").display = False
        self.supplement = False
        self.workspace_widget("#supplement", Button).display = False
        self.session_epoch += 1
        self.records.clear()
        self.model_requests = 0
        if not keep_connection_state:
            self.last_api_status = ""
            self.last_api_ok = None
        if clear_log:
            self.workspace_widget("#chat-log", RichLog).clear()

    def logout(self):
        self.reset_agent(clear_log=True)
        self.close_conversation()
        self.user, self.profile, self.company, self.period, self.task_route = None, None, None, None, None
        self.read_workspace = None
        self.invoice_route = None
        self.workspace_widget("#prompt", Input).value = ""
        self.task_links = {}
        self.invoice_rows = []
        for pane in ("#task-body", "#finance-body", "#record-list"):
            self.workspace_widget(pane).display = False
        self.update_header()
        # Settings may still be open. Present login when that dialog closes.
        if not isinstance(self.screen, Settings):
            self.push_screen(Login(), self.signed_in)

    def settings_closed(self, destination):
        if not self.user and not isinstance(self.screen, Login):
            self.push_screen(Login(), self.signed_in)
        elif destination == "return-task" and self.task_route:
            self.open_task(self.task_route)
        elif destination == "settings-scope":
            self.choose_workspace_scope()
        elif destination == "settings-preferences":
            from .tui_preferences import open_preferences
            open_preferences(self)
        elif destination == "settings-records":
            self.show("records")
        elif destination in {"switch-account", "sign-out"}:
            self.confirm_logout("切换账号" if destination == "switch-account" else "退出登录")
        self.update_header()

    def resolve_profile(self, *, require_key, selection=...):
        _, default = load_profiles(**self.profile_options)
        selected = self.profile if selection is ... else selection
        name = selected or os.environ.get("FINANCE_MODEL_PROFILE") or default
        if not name:
            raise ProfileError("No AI configuration selected")
        bound = resolve_connection(self.user, name, require_key=False, **self.profile_options)
        if not require_key:
            return bound
        key = self.current_key(bound.profile)
        if not key:
            raise ProfileError("当前配置缺少 API 密钥。")
        return ModelConnection(bound.profile, key)

    def current_key(self, profile):
        target = profile_target(profile)
        if target in self.session_keys:
            return self.session_keys[target]
        try:
            saved = self.vault.read(target) if self.vault else None
        except CredentialError:
            saved = None
        return saved or os.environ.get(profile.api_key_env, "").strip()

    def key_status(self, profile):
        if not self.vault:
            return "系统安全存储不可用。可仅本次使用。"
        try:
            if self.vault.read(profile_target(profile)):
                return "此模型配置在 Windows 中已有保存的密钥。"
        except CredentialError:
            return "暂时无法读取系统凭据。可仅本次使用。"
        return "此模型配置没有保存的密钥。"

    def apply_key(self, profile, secret, remember):
        target = profile_target(profile)
        self.session_keys[target] = secret
        if remember and self.vault:
            try:
                self.vault.write(target, secret)
                return "密钥已保存到 Windows 凭据管理器。"
            except CredentialError:
                pass
        if remember:
            return "系统未能安全保存密钥，密钥仅本次使用。"
        return "密钥仅本次使用。"

    def forget_key(self, profile):
        if not self.vault:
            raise CredentialError("系统安全存储不可用。")
        target = profile_target(profile)
        self.vault.forget(target)
        self.session_keys.pop(target, None)
        self.set_model(self.mode, self.profile)

    def model_state(self):
        """Offline configuration checks and observed transport outcomes stay distinct."""
        if self.mode == "mock":
            return "mock", "固定脚本测试（开发诊断）", "使用固定示例联调界面。"
        try:
            profile = self.resolve_profile(require_key=False).profile
        except ProfileError:
            return "unconfigured", "尚未配置 AI", "选择现有 AI 配置或新建一个。"
        if not self.current_key(profile):
            return "missing-key", "缺少 API 密钥", f"为 {profile.model} 输入密钥后即可发送。"
        if self.last_api_ok is True:
            return "connected", "真实 AI 已响应", profile.model
        if self.last_api_ok is False:
            return "failed", "最近模型请求失败", f"{profile.model} · 请核对网络和 AI 配置，详情见执行记录。"
        return "unverified", "连接尚未验证", f"{profile.model} 的密钥已设置。发送消息后才会联网。"

    def profile_status(self):
        _, title, detail = self.model_state()
        return f"{title} · {detail}"

    def update_header(self):
        query = "未选择"
        if self.read_workspace:
            company, year, month = self.read_workspace
            query = f"{self.company_name(company)} / {year:04d}-{month:02d}"
        focus = self.task_focus_label()
        state, title, detail = self.model_state()
        self.workspace_widget("#status", Static).update(safe_text(
            f"Economy-guy / 财税工作台 · 比赛模拟 · {self.user or '未登录'} · {title}\n"
            f"任务焦点：{focus}"))
        self.workspace_widget("#query-scope", Button).label = Text(safe_text(f"当前查询企业：{query}（只读）"))
        self.workspace_widget("#ai-guide-text", Static).update(safe_text(f"{title}\n{detail}"))
        self.workspace_widget("#ai-guide").display = state in {"unconfigured", "missing-key", "unverified", "failed"}

    def task_focus_label(self):
        if not self.task_focus:
            return "无"
        try:
            outcome = task_details(self.db, self.user, *self.task_focus)
        except (OSError, ValueError, sqlite3.Error):
            return "暂时无法读取"
        if not outcome["ok"]:
            return "已不可读取"
        return self.format_task_focus(outcome["data"])

    def format_task_focus(self, data):
        task = data["task"]
        check = data["check"]
        progress = f"缺用途 {check['count']} 张" if check is not None else "进度不可用"
        return (f"{self.company_name(task['company_id'])} / {task['year']:04d}-{task['month']:02d} "
                f"发票用途 · {TASK_STATUS[task['status']]} · {progress}")

    def note(self, text):
        self.workspace_widget("#chat-note", Static).update(safe_text(text))

    def chat_message(self, role, text):
        log = self.workspace_widget("#chat-log", RichLog)
        log.write(Text(role, style="bold #83ddd6"))
        clean = self.storage_text(text)
        log.write(Text(clean))
        if self.turn_seq is not None and role != "你":
            self.turn_display.append((role,clean))

    def ensure_agent(self):
        if not self.user:
            raise ValueError("请先选择模拟账号。")
        if self.agent is not None:
            return
        options = {}
        if self.model_override is not None:
            options["model"] = self.model_override
        elif self.mode == "live":
            options["connection"] = self.resolve_profile(require_key=True)
        else:
            options["model"] = offline_model
        self.agent = Agent(self.user, self.db, mode=self.mode, trace_path=self.trace_path,
                           management_confirmation=self.confirm_management,
                           display_preference=self.conversation.manage_detail if self.conversation else None, **options)
        self.agent.messages[0]["content"] += (
            "\n本工作台内，待办 create/update/correct 的 note 必须逐字保留当前用户原始要求，"
            "不补造任务内容、期限或目标。明确缺失参数时追问。")
        if self.session_path is not None:
            self.agent.context.display_ids = list(self.resume_displays)
        if self.conversation:
            self.agent.workbook_guard = self.conversation.validate
            if self.task_focus:
                self.agent.focus_task(*self.task_focus)
            self.agent.context.restored_turns = list(self.resumed)
            self.agent.context.personal_detail = self.conversation.personal_detail()
        if self.agent.transport:
            trace = self.agent.transport.trace

            def observe(event, data):
                if event == "api.response":
                    self.last_api_ok = data["success"] is True
                    self.last_api_status = ("已收到模型响应" if data["success"] else
                                            f"{data['http_category']} HTTP {data['http_status'] or '无响应'}")
                trace(event, data)

            self.agent.transport.trace = observe

    def action_navigation(self):
        if self.user and self.screen is self.screen_stack[0]:
            self.workspace_widget("#rail .current", Button).focus()

    def open_settings(self):
        if self.user and not self.busy:
            self.push_screen(Settings(self), self.settings_closed)

    def confirm_logout(self, title):
        if self.agent is None:
            self.logout()
        else:
            self.push_screen(Approval(
                title, "当前对话将关闭，未提交的操作会取消。已保存的业务记录仍可查看。",
                title, danger=True), lambda yes: self.logout() if yes else None)

    def action_account(self):
        if not self.user or self.screen is not self.screen_stack[0]:
            return
        if self.busy:
            self.note("请等待本轮操作结束。")
            return
        self.push_screen(Choices("账户 · SIMULATED_IDENTITY", [
            ("我的账户与权限", "account"), ("当前查询范围", "company"),
            ("工作台设置", "settings"), ("帮助与关于", "help"), ("新对话", "new"),
            ("切换账号", "switch"), ("退出登录", "logout"), ("退出程序", "quit"),
        ]), self.account_choice)

    def account_choice(self, choice):
        if choice == "settings":
            self.open_settings()
        elif choice in {"switch", "logout"}:
            self.confirm_logout("切换账号" if choice == "switch" else "退出登录")
        elif choice == "new":
            self.request_new_chat()
        elif choice == "quit":
            self.action_quit_safe()
        elif choice == "company":
            self.choose_workspace_scope()
        elif choice == "help":
            self.push_screen(Choices("帮助与关于", [
                ("输入问题或完整修改要求，按 Enter 发送", None),
                ("Tab 切换焦点，Esc 取消弹窗，F2 导航，F3 账户", None),
                ("比赛模拟数据可搭配真实 AI。固定脚本测试位于高级诊断。", None)]))
        elif choice == "account":
            rows = company_access(self.db, self.user)
            self.push_screen(Choices(f"我的账户 · {self.user} · 比赛模拟",
                [(f"{row['name']} · 读取 {'允许' if row['read'] else '拒绝'} · "
                  f"修改 {'允许' if row['modify'] else '拒绝'}", None) for row in rows]))

    def request_new_chat(self):
        if self.busy or isinstance(self.screen, Approval):
            self.note("本轮仍在处理或等待确认，请先完成或取消本轮操作。")
            return
        prompt = self.workspace_widget("#prompt", Input)

        def start(confirmed):
            if confirmed is True and not self.busy:
                if self.conversation:
                    try:
                        self.conversation.new_chat(self.read_workspace)
                    except (OSError, ValueError, sqlite3.Error):
                        self.note("无法保存新对话，请重新打开账簿。")
                        return
                self.resumed, self.resume_displays, self.resume_focus = [], [], None
                self.has_saved_history = False
                self.saved_records = []
                self.reset_agent(clear_log=True, keep_connection_state=True)
                prompt.value = ""
                self.show("chat")
                self.note("已开始新对话。可输入问题，按 Enter 发送。")

        if self.agent is not None or self.has_saved_history or prompt.value.strip():
            self.push_screen(Approval(
                "开始新对话？",
                "当前对话内容将不再显示，未提交的修改意图会取消。已保存的待办、财务数据和审计记录不会删除。",
                "开始新对话", cancel="返回当前对话", danger=True), start)
        else:
            start(True)

    def action_quit_safe(self):
        if self.busy:
            self.note("等待本轮结束或取消弹窗后可退出。")
        elif isinstance(self.screen, Approval):
            return
        elif self.agent is not None:
            def leave(confirmed):
                if confirmed:
                    self.reset_agent(clear_log=True)
                    self.exit()
            self.push_screen(Approval("退出程序", "将关闭当前对话。已保存的业务记录仍可查看。",
                                      "退出程序", danger=True), leave)
        else:
            self.exit()

    def action_cancel_edit(self):
        if self.agent and not self.busy:
            self.agent.cancel_update()
            self.task_focus = None
            self.remember_focus()
            self.update_header()
            self.supplement = False
            self.workspace_widget("#supplement", Button).display = False
            self.note("已取消当前未提交操作。")

    @on(Button.Pressed)
    def button(self, event):
        key = event.button.id or ""
        if key.startswith("go-"):
            self.show(key.removeprefix("go-"))
        elif key == "account":
            self.action_account()
        elif key == "query-scope":
            if not self.busy:
                self.choose_workspace_scope()
        elif key == "chat-invoices" and self.chat_invoice_route:
            self.show_invoice_directory(*self.chat_invoice_route)
        elif key == "new-task" and not self.busy:
            self.new_task()
        elif key == "configure-ai":
            self.open_settings()
        elif key.startswith("todo-"):
            route = getattr(self, "task_links", {}).get(key)
            if route:
                self.open_task(route)
        elif key == "back-tasks":
            self.show("tasks")
        elif key == "linked-finance":
            self.invoice_route = None
            self.invoice_page = 1
            self.select_pane("finance")
            self.call_later(self.refresh_pane, "finance")
        elif key == "back-detail" and self.task_route:
            self.open_task(self.task_route)
        elif key == "choose-finance":
            self.choose_workspace_scope(for_finance=True)
        elif key == "choose-finance-company":
            self.choose_company(lambda company: self.show_invoice_directory(company, 0, 0) if company else None)
        elif key in {"invoice-prev", "invoice-next"}:
            self.invoice_page += 1 if key == "invoice-next" else -1
            self.call_later(self.refresh_pane, "finance")
        elif key == "continue-task":
            self.continue_task()
        elif key == "supplement":
            self.supplement = True
            self.note("可补充企业或发票，或输入「新值是…」。也可用引号括住完整新值，或发送一项新的要求。")
            self.workspace_widget("#prompt", Input).focus()

    @on(Input.Submitted, "#prompt")
    def submitted(self, event):
        message = event.value.strip()
        if not message or self.busy or not self.user:
            return
        if self.conversation_blocked:
            self.note("此账号的账簿对话已在另一窗口打开。请关闭后重新登录。")
            return
        try:
            self.ensure_agent()
        except (OSError, ProfileError, ValueError, sqlite3.Error):
            self.update_header()
            self.note("暂时无法发送。请使用「配置 AI 模型」检查设置。")
            return
        if self.conversation:
            try:
                self.agent.context.personal_detail = self.conversation.personal_detail()
            except (OSError, ValueError, sqlite3.Error):
                self.note("工作库身份或会话存储已变化，请重新打开。")
                return
        args = edit_turn(message, self.agent.pending_edit, guided=self.supplement)
        if args.pop("cancel", False):
            event.input.value = ""
            self.action_cancel_edit()
            return
        if self.conversation:
            try:
                self.turn_seq = self.conversation.begin(self.storage_text(message), self.mode)
            except (OSError, ValueError, sqlite3.Error):
                self.note("无法保存本轮记录。请重新打开工作库后再试。")
                return
        event.input.value = ""
        self.chat_message("你", message)
        self.busy = True
        event.input.disabled = True
        self.note("正在处理，请稍候。")
        self.supplement = False
        self.workspace_widget("#supplement", Button).display = False
        scope = self.read_workspace or self.resume_focus
        if self.resume_focus and any(word in message for word in ("刚才","上一轮")):
            scope = self.resume_focus
        self.run_turn(message, args, scope)

    def wait_confirmation(self, title, body, action, *, danger=False):
        """Let the worker wait for the modal while the terminal stays responsive."""
        answer = Future()
        epoch = self.session_epoch

        def present():
            def resolve(yes):
                if not answer.done():
                    answer.set_result(yes is True and epoch == self.session_epoch)
            self.note("等待确认。")
            self.push_screen(Approval(title, body, action, danger=danger), resolve)

        self.call_from_thread(present)
        worker = get_current_worker()
        while not worker.is_cancelled and self.is_running:
            try:
                return answer.result(timeout=0.2)
            except TimeoutError:
                pass
        return False

    def confirm_management(self, proposal):
        if redact(proposal) != proposal:
            return False
        p = proposal["proposal"]
        if proposal["domain"] == "task":
            if p["action"] in {"create", "update", "correct"} and p["note"].strip() != proposal["original_request"].strip():
                self.call_from_thread(self.chat_message, "待办未保存", "候选备注与原始要求不同。请重述待办内容后再试。")
                return False
            current = proposal.get("current") or {}
            old_note = current.get("context", {}).get("note") or "（无）"
            new_note = p.get("note") or old_note
            previous = ""
            if current:
                previous = (f"原账期　{current['year']:04d}-{current['month']:02d}\n"
                            f"当前状态　{TASK_STATUS.get(current['status'], '未知')}\n")
            notes = f"原值　{old_note}\n新值　{new_note}" if p["action"] in {"create", "update", "correct"} else f"备注　{old_note}"
            title = "确认待办"
            name = self.company_name(p["company_id"])
            body = (f"用户　{self.user}\n对象　{name} · {p['year']:04d}-{p['month']:02d} 发票用途\n"
                    f"{previous}{notes}\n关联表格　发票明细\n"
                    f"操作　{dict(create='新建', update='补充', correct='更正', resume='恢复', complete='完成', cancel='取消', wait='等待补充', pause='暂停').get(p['action'], p['action'])}\n"
                    "尚未提交。确认后会重新检查权限与冲突。")
        elif proposal["domain"] == "display_preference":
            title = "确认个人回复习惯"
            body = (f"用户　{self.user}\n生效范围　当前账号与账簿\n"
                    f"原值　{proposal['current']['value']}\n"
                    f"拟保存值　{p['value'] or '普通'}\n尚未保存。")
        else:
            title = "确认偏好"
            body = (f"用户　{self.user}\n企业　{p['company_id']}\n"
                    f"偏好　{p['key']}\n原值　{(proposal.get('current') or {}).get('value') or '（无）'}\n"
                    f"拟保存值　{p.get('value') or '（空）'}\n操作　{'删除' if p['action'] == 'delete' else '保存'}\n尚未提交。")
        if proposal["domain"] in {"display_preference","preference"}:
            body += "\n原始要求　" + proposal["original_request"]
        danger = p["action"] in {"cancel", "delete"}
        accepted = self.wait_confirmation(title, body, "确认操作" if danger else "确认保存", danger=danger)
        if accepted and self.conversation and self.turn_seq is not None:
            self.conversation.checkpoint(self.turn_seq)
        return accepted

    @work(thread=True, group="agent", exit_on_error=False)
    def run_turn(self, message, args, read_workspace):
        agent = self.agent
        offset = len(agent.messages)
        receipt = None
        try:
            agent.ask(message, read_workspace=read_workspace, **args)
            if agent.update_session.drafts:
                draft, = agent.update_session.drafts.values()
                fields = asdict(draft)
                if redact(fields) == fields:
                    field = "用途" if draft.field == "purpose" else "备注"
                    note = "\n此企业与工作区提示不同。" if self.company and self.company != draft.company_id else ""
                    name = self.company_name(draft.company_id)
                    body = (f"企业　{name}（{draft.company_id}）\n发票　{draft.invoice_no}\n字段　{field}\n"
                            f"原值　{draft.old_value or '（空）'}\n新值　{draft.new_value or '（清空）'}{note}\n尚未提交。")
                    if self.wait_confirmation("确认发票修改", body, "确认修改"):
                        if self.conversation and self.turn_seq is not None:
                            self.conversation.checkpoint(self.turn_seq, draft.request_id)
                        receipt = agent.commit_update(draft.request_id, draft.fingerprint())
                if receipt is None:
                    receipt = agent.cancel_update()
            calls = turn_tools(agent.messages[offset:])
            verified = []
            call_by_id = {call["id"]: call for call in calls}
            for item in agent.messages[offset:]:
                if item["role"] != "tool":
                    continue
                outcome = json.loads(item["content"])
                evidence = outcome.get("evidence") or {}
                rule = evidence.get("rule")
                call = call_by_id.get(item["tool_call_id"])
                if call is not None and isinstance(rule, dict):
                    call["rule"] = (rule.get("rule_id") or rule.get("id"), rule.get("version"))
                if call is not None:
                    call["source"] = evidence.get("source")
                if outcome["status"] == "SUCCESS" and evidence.get("management_confirmation") and (not call or call["tool"] != "manage_task"):
                    if "preference_readback_verified" in evidence:
                        verified.append("偏好已保存并回读。" if evidence["preference_readback_verified"] else
                                        "偏好已提交，当前值尚未核实，请打开偏好设置。")
                    else:
                        verified.append("已按本次确认保存，业务库记录可重新查看。")
            self.call_from_thread(self.finish_turn, calls, receipt, verified,
                                  not args.get("allow_prepare") and not args.get("continue_edit"))
        except Exception:
            if agent.workbook_available():
                agent.cancel_update()
            if self.is_running:
                self.call_from_thread(self.fail_turn)

    @staticmethod
    def business_card(tool, data, evidence):
        if evidence.get("source") != "current_sqlite":
            return None
        if tool == "list_invoices" and isinstance(data, list):
            return ("发票目录", f"本账期共 {len(data)} 张\n" + AgentWorkspace.invoice_lines(data))
        if tool == "list_tasks" and isinstance(data, list):
            return ("待办", "\n".join(f"{row['year']} 年 {row['month']} 月用途补充待办，{TASK_STATUS.get(row['status'], '状态待核对')}"
                                      for row in data) or "当前没有待办。")
        if tool == "list_bank_transactions" and isinstance(data, list):
            return ("银行流水", "\n".join(f"{row['transaction_date']}　{row['direction']} ¥{row['amount']}"
                                          for row in data) or "没有符合条件的银行流水。")
        if not isinstance(data, dict):
            return None
        if tool == "get_finance_summary":
            return ("账期合计", "\n".join(
                f"{label} ¥{data[key + '_total']}（{data[key + '_count']} {unit}）"
                for label, key, unit in (("发票价税合计", "invoice", "张"), ("银行收入", "bank_income", "条"),
                                         ("银行支出", "bank_expense", "条"))))
        if tool in {"get_invoice", "resolve_invoice_reference"} and data:
            return ("发票详情", AgentWorkspace.invoice_text(data))
        if tool == "list_invoice_directory":
            rows = data["rows"]
            header = f"共 {data['total']} 张 · 第 {data['page']} 页 · 每页 {data['page_size']} 张"
            return ("发票目录", header + "\n" + AgentWorkspace.invoice_lines(rows))
        if tool == "check_missing_purpose":
            return ("用途检查", f"目前有 {data['count']} 张发票未填写必填用途。\n"
                    + "\n".join(f"{r['invoice_date']}　{r['invoice_no']}" for r in data["missing_invoices"]))
        if tool == "manage_task" and "task" in data:
            task = data["task"]
            state = TASK_STATUS.get(task["status"], "状态待核对")
            if evidence.get("management_confirmation"):
                action = "已创建" if evidence.get("operation", {}).get("action") == "create" else "已保存"
                next_step = "，后续可在待办中继续处理" if task["status"] == "ACTIVE" else ""
                return ("待办回执", f"{action}用途补充待办，{state}{next_step}。")
            return ("待办", f"{task['year']} 年 {task['month']} 月用途补充待办，{state}。")
        if tool == "get_applicable_rules":
            return ("适用规则", data["content"])
        return None

    @staticmethod
    def invoice_lines(rows):
        return "\n".join(f"{row['invoice_date']}　{row['invoice_no']}　¥{row['amount']}" for row in rows) or "本页没有发票。"

    @staticmethod
    def invoice_text(row):
        return (f"发票编号　{row['invoice_no']}\n开票日期　{row['invoice_date']}\n"
                f"销售方　{row['seller_name']}\n项目　{row['item_name']}\n价税合计　¥{row['amount']}\n"
                f"用途　{row['purpose'] or '未填写'}\n备注　{row['remark'] or '（无）'}")

    def show_turn_results(self, results):
        groups = {}
        for tool, outcome in results:
            if outcome["status"] not in {"SUCCESS", "NO_DATA", "NO_CHANGE"}:
                continue
            evidence = outcome["evidence"]
            data = outcome["data"]
            card = self.business_card(tool, data, evidence)
            if card is None:
                if outcome["status"] == "NO_DATA":
                    card = ("查询结果", "没有符合条件的记录。")
                elif outcome["status"] == "NO_CHANGE":
                    card = ("处理结果", outcome["error"] or "当前无需变更。")
                else:
                    continue
            group = groups.setdefault(scope_key(evidence), (evidence, []))
            group[1].append(card)
            if tool == "list_bank_transactions" and "amount_rule" in evidence and "finance_summary" in evidence:
                amount_basis = {**evidence, "rule": evidence["amount_rule"]}
                totals = evidence["finance_summary"]
                amount_group = groups.setdefault(scope_key(amount_basis), (amount_basis, []))
                amount_group[1].append(("银行收支合计", f"收入 ¥{totals['bank_income_total']}，支出 ¥{totals['bank_expense_total']}。"))
            if outcome["status"] == "SUCCESS" and tool in {"list_invoice_directory", "list_invoices", "get_invoice"}:
                scope = evidence["scope"]
                page = data["page"] if tool == "list_invoice_directory" else 1
                self.chat_invoice_route = (scope["company_id"], scope.get("year", 0), scope.get("month", 0), page)
        for evidence, cards in groups.values():
            self.chat_message("查询与处理结果", render_scope(evidence, conversational=True))
            for title, text in cards:
                self.chat_message(f"业务核验 / {title}", text)
        return bool(groups)

    def finish_turn(self, calls, receipt, verified, read_only=True):
        response = self.agent.last_response
        stop = response["execution"]["stop_reason"]
        status = receipt["status"] if receipt else stop
        results = response["tool_results"]
        self.chat_invoice_route = None
        shown = self.show_turn_results(results)
        self.workspace_widget("#chat-invoices").display = self.chat_invoice_route is not None
        notice = response["chat_notice"]
        if notice:
            self.chat_message("Agent", notice)
        elif stop not in {"ANSWERED", "COMPLETED", "TASK_FINISHED", "WAITING_CONFIRMATION"}:
            self.chat_message("Agent", status_label(stop))
        elif response["operation_receipt"]["status"] == "CURRENT_VALUE_MATCHES":
            self.chat_message("发票回执", "当前发票值已经符合要求，本轮无需再次保存。")
        elif not (shown or verified or receipt):
            self.chat_message("Agent", "本轮没有可核实的业务结果。请补充查询对象或查看执行记录。")
        progress = verified_task_progress(results)
        if progress:
            self.chat_message("当前待办", "已重新核对待办与缺项。请逐张补充用途，全部补齐后再确认完成。")
        elif needs_progress_evidence(results):
            self.chat_message("当前待办", "暂时无法将本轮检查与唯一待办对应，请打开待办详情核对。")
        for detail in verified:
            self.chat_message("业务回执", detail)
        if receipt:
            self.chat_message("发票回执", receipt["message"])
            if receipt.get("task_progress"):
                progress = receipt["task_progress"]
                if progress["status"] == "SUCCESS":
                    count = progress["data"]["check"]["count"]
                    self.chat_message("当前待办", f"已重新核对当前待办，剩余 {count} 张发票待补用途。")
                else:
                    self.chat_message("当前待办", "本次修改结果见发票回执。请打开待办详情重新核对进度。")
        api = response.get("api_counts")
        if api:
            self.model_requests += api["attempts"]
        if self.agent.transport and response["execution"]["stop_reason"] in {
            "API_OR_RESPONSE_ERROR", "INVALID_RESPONSE", "PROTOCOL_ERROR",
        }:
            if self.last_api_ok is not False:
                self.last_api_status = "模型响应或协议校验失败"
            self.last_api_ok = False
        observed = self.last_api_status if api and api["attempts"] else ""
        self.records.append((status, calls, observed))
        if self.task_focus and self.task_focus[1] not in self.agent.context.scope.get("task_id", []):
            self.task_focus = None
        for call in calls:
            scope = call.get("scope") or {}
            if self.read_workspace is None and call["status"] in {"SUCCESS", "NO_DATA"} and scope.get("company_id"):
                self.company = scope["company_id"]
                if "year" in scope and "month" in scope:
                    self.period = scope["year"], scope["month"]
        self.workspace_widget("#supplement", Button).display = bool(self.agent.pending_edit)
        self.save_turn(calls, "UNKNOWN_OUTCOME" if any(c["status"] == "UNKNOWN_OUTCOME" for c in calls) else status,
                       read_only)
        self.remember_focus()
        self.note(f"{status_label(status)} · F2 聚焦导航，可选择执行记录")
        self.unlock()

    def fail_turn(self):
        self.turn_seq = None
        self.turn_display = []
        self.note("本轮处理失败。请核对设置。若结果未知，请先查执行记录。")
        self.unlock()

    def unlock(self):
        self.busy = False
        prompt = self.workspace_widget("#prompt", Input)
        prompt.disabled = False
        if self.workspace_widget("#panes", ContentSwitcher).current == "chat":
            prompt.focus()
        self.update_header()

    def workspace_widget(self, selector, widget=None):
        return self.screen_stack[0].query_one(selector, widget)

    def select_pane(self, page):
        self.workspace_widget("#panes", ContentSwitcher).current = page
        for key, _ in self.NAV_ITEMS:
            self.workspace_widget("#" + key, Button).set_class(key == f"go-{page}", "current")

    def show(self, page):
        if not self.user:
            return
        self.task_route = None
        if page == "finance":
            self.invoice_route = None
            self.invoice_page = 1
        self.select_pane(page)
        self.update_header()
        if page == "chat":
            self.workspace_widget("#prompt", Input).focus()
        else:
            self.call_later(self.refresh_pane, page)

    async def refresh_pane(self, page):
        targets = {"tasks": "#task-body", "finance": "#finance-body", "records": "#record-list"}
        holder = self.workspace_widget(targets[page], VerticalScroll)
        await holder.remove_children()
        try:
            if page == "tasks":
                widgets = self.task_widgets()
            elif page == "finance":
                widgets = self.finance_widgets()
            else:
                widgets = self.record_widgets()
        except (OSError, ValueError, sqlite3.Error):
            widgets = [Static("无法读取当前记录。请核对工作库、规则或权限。", markup=False)]
        await holder.mount(*widgets)
        holder.display = True

    def task_widgets(self):
        self.task_links = {}
        if self.task_route:
            return self.task_detail_widgets(self.task_route)
        widgets = [TextAction("新建待办", id="new-task", variant="primary")]
        for company in company_access(self.db, self.user):
            if not company["read"]:
                continue
            outcome = list_tasks(self.db, self.user, company["company_id"])
            for task in outcome["data"] or []:
                key = f"todo-{len(self.task_links)}"
                self.task_links[key] = (task["company_id"], task["task_id"])
                widgets.append(TextAction(Text(safe_text(
                    f"{company['name']} · {task['year']:04d}-{task['month']:02d} 发票用途"
                    f" · {TASK_STATUS.get(task['status'], '未知')}")), id=key))
        if len(widgets) == 1:
            widgets.append(Static("当前账号没有可查看的待办。", markup=False))
        return widgets

    def new_task(self):
        self.choose_company(lambda company: self.select_period(
            company, lambda period: self.task_note(company, period) if period else None,
            actual_only=True) if company else None, modify=True)

    def task_feedback(self, message):
        self.push_screen(Choices(message, []))

    def task_note(self, company, period):
        try:
            with closing(open_existing(self.db, readonly=True)) as db, db:
                db.execute("BEGIN")
                check = check_missing_purpose(db, self.user, company, *period)
        except (OSError, ValueError, sqlite3.Error, RuleError):
            self.task_feedback("无法核对用途，请检查当前账簿、权限和适用规则。")
            return
        if not check["count"]:
            self.task_feedback("该账期没有待补用途的发票。")
            return
        title = f"{self.company_name(company)}（{company}） · {period[0]:04d}-{period[1]:02d}"
        progress = f"当前缺失用途 {check['count']} 张"
        self.push_screen(TaskNote(title, progress),
                         lambda note: self.preview_task(company, period, title, progress, note) if note else None)

    def preview_task(self, company, period, title, progress, note):
        actor, path, epoch = self.user, self.db, self.session_epoch
        intent = ManagementIntent(actor, "task", note, "create", turn=ManagementTurn(actor))
        params = {"company_id": company, "action": "create", "year": period[0], "month": period[1], "note": note}
        try:
            outcome = manage_task(path, actor, **params, intent=intent)
        except (OSError, ValueError, sqlite3.Error):
            self.task_feedback("无法核对待办，请检查账簿。")
            return
        if outcome["status"] != "WAITING_CONFIRMATION":
            self.task_feedback(outcome["error"] or status_label(outcome["status"]))
            return

        def save(yes):
            try:
                if yes is not True or self.busy or (self.user, self.db, self.session_epoch) != (actor, path, epoch):
                    return
                approved = confirm_management(intent, outcome["data"])
                saved = manage_task(path, actor, **params, intent=approved)
                if saved["status"] != "SUCCESS":
                    self.task_feedback(saved["error"] or status_label(saved["status"]))
                    return
                route = (company, saved["data"]["task"]["task_id"])
                verified = task_details(path, actor, *route)
                self.open_task(route)
                if verified["ok"]:
                    self.notify("待办已保存，并从账簿重新读取。")
                else:
                    self.notify("已保存，当前无法回读。请检查待办列表。", severity="warning")
            except (OSError, ValueError, sqlite3.Error):
                self.task_feedback("暂时无法核对保存结果，请先查看待办列表。")
            finally:
                intent.turn.active = False

        self.push_screen(Approval("确认新建待办", f"用户　{actor}\n对象　{title}\n"
                                  f"备注　{note}\n{progress}\n尚未提交。", "确认保存"), save)

    def open_task(self, route):
        self.task_route = route
        self.select_pane("tasks")
        self.call_later(self.refresh_pane, "tasks")

    def task_detail_widgets(self, route):
        outcome = task_details(self.db, self.user, *route)
        back = TextAction("返回待办列表", id="back-tasks")
        if not outcome["ok"]:
            return [back, Static(status_label(outcome["status"]), markup=False)]
        data = outcome["data"]
        task = data["task"]
        label = self.company_name(task["company_id"])
        title = f"{label} · {task['year']:04d}-{task['month']:02d} 发票明细"
        check = data["check"]
        permission = "当前可处理" if data["can_execute"] else (
            "当前缺少修改权限，记录仍保留" if not data["may_modify"] else "当前不可继续执行")
        progress = f"当前缺失用途 {check['count']} 张" if check is not None else data["problem"]
        note = task["context"].get("note", "")
        return [
            back,
            Vertical(
                Static(safe_text(f"用户　{self.user}\n对象　{title}\n备注　{note}"),
                       classes="task-fields", markup=False),
                Static(safe_text(f"{TASK_STATUS[task['status']]} · {permission}\n{progress}"),
                       classes="task-progress", markup=False),
                TextAction(Text(safe_text(title)), id="linked-finance", classes="text-link", tooltip="打开当前发票明细"),
                TextAction("在对话中继续", id="continue-task", variant="primary", disabled=not data["can_execute"]),
                classes="task-card",
            ),
        ]

    def continue_task(self):
        if self.busy or not self.task_route:
            return
        route = self.task_route
        try:
            outcome = task_details(self.db, self.user, *route)
            if not outcome["ok"] or not outcome["data"]["can_execute"]:
                self.call_later(self.refresh_pane, "tasks")
                return
            try:
                self.ensure_agent()
            except ProfileError:
                self.push_screen(Approval(
                    "继续与 AI 对话",
                    "当前待办可以查看，但继续与 AI 对话需要先配置模型。\n" + self.profile_status(),
                    "配置 AI 模型", cancel="返回待办详情"),
                    lambda yes: self.push_screen(Settings(self, return_to_task=True), self.settings_closed)
                    if yes else None)
                return
            pending_edit = bool(self.agent.pending_edit)
            outcome = self.agent.focus_task(*route)
        except (ValueError, OSError, sqlite3.Error):
            self.push_screen(Choices("无法恢复待办", [("请核对当前工作库和账号，再重新打开待办。", None)]))
            return
        if not outcome["ok"] or not outcome["data"]["can_execute"]:
            self.call_later(self.refresh_pane, "tasks")
            return
        check = outcome["data"]["check"]
        previous_query = self.read_workspace is not None
        self.read_workspace = None
        self.company = self.period = None
        self.task_focus = route
        self.remember_focus()
        self.supplement = False
        self.workspace_widget("#supplement", Button).display = False
        self.show("chat")
        self.note("已进入待办对话，可输入问题继续。")
        hint = "可以询问剩余事项。" if check["count"] else "可以明确要求标记完成，保存前仍会确认。"
        scope_note = "原查询范围已取消。" if previous_query else ""
        edit_note = "未提交的修改意图已取消。" if pending_edit else ""
        focus = self.format_task_focus(outcome["data"])
        self.chat_message("当前待办", f"已进入 {focus}。{scope_note}{edit_note}状态已从工作库重新读取。{hint}")

    def company_name(self, company):
        try:
            return next((r["name"] for r in company_access(self.db, self.user)
                         if r["company_id"] == company and r["read"]), company)
        except (OSError, ValueError, sqlite3.Error):
            return company

    def choose_workspace_scope(self, for_finance=False):
        self.choose_company(lambda company: self.pick_period(company, for_finance) if company else None)

    def choose_company(self, callback, *, modify=False):
        try:
            rows = [r for r in company_access(self.db, self.user)
                    if r["read"] and (not modify or r["modify"])]
        except (OSError, ValueError, sqlite3.Error):
            self.push_screen(Choices("无法读取企业权限", [("请核对当前账簿后再试。", None)]))
            return
        if not rows:
            self.push_screen(Choices("没有符合权限的企业", [("请核对当前模拟账号。", None)]))
            return
        self.push_screen(Choices("选择可读企业", [
            (f"{r['name']} · {r['company_id']} · {'可读取、可修改' if r['modify'] else '只读'}", r["company_id"])
            for r in rows]), callback)

    def select_period(self, company, callback, *, actual_only=False):
        from .queries import QueryError
        from .tui_screens import Period

        try:
            with closing(open_existing(self.db, readonly=True)) as db, db:
                db.execute("BEGIN")
                months = available_periods(db, self.user, company)
        except QueryError:
            self.push_screen(Choices("无法读取账期", [("当前账号没有此企业的读取权限。", None)]))
            return
        except (OSError, sqlite3.Error):
            self.push_screen(Choices("无法读取账期", [("读取账簿出错，请核对文件。", None)]))
            return
        self.push_screen(Period(self.period, months, actual_only=actual_only), callback)

    def pick_period(self, company, for_finance):
        def selected(period):
            if period is None:
                return
            self.company, self.period = company, period
            self.read_workspace = (company, *period)
            self.remember_focus()
            self.update_header()
            if for_finance:
                self.show("finance")

        self.select_period(company, selected)

    def show_invoice_directory(self, company, year, month, page=1):
        self.task_route = None
        self.invoice_route = (company, year, month)
        self.invoice_page = page
        self.select_pane("finance")
        self.call_later(self.refresh_pane, "finance")

    def finance_widgets(self):
        actions = [
            TextAction("按企业查看全部", id="choose-finance-company"),
            TextAction("按企业和账期查看", id="choose-finance"),
        ]
        detail = ""
        if self.task_route:
            outcome = task_details(self.db, self.user, *self.task_route)
            actions = [TextAction("返回待办详情", id="back-detail")]
            if not outcome["ok"]:
                return [*actions, Static(status_label(outcome["status"]), markup=False)]
            task, check = outcome["data"]["task"], outcome["data"]["check"]
            company, year, month = task["company_id"], task["year"], task["month"]
            if check:
                rule = check["rule"]
                detail = f" · 当前缺失用途 {check['count']} 张 · {rule['rule_id']} v{rule['version']}"
            else:
                detail = f" · {outcome['data']['problem']}"
        elif self.invoice_route:
            company, year, month = self.invoice_route
        elif self.company:
            company, (year, month) = self.company, self.period or (0, 0)
        else:
            return [*actions, Static("请选择企业查看发票目录。", markup=False)]
        try:
            with closing(open_existing(self.db, readonly=True)) as db, db:
                db.execute("BEGIN")
                data = invoice_directory(db, self.user, company, year, month, self.invoice_page)
        except QueryError:
            return [*actions, Static("当前账号没有读取该企业发票的权限。", markup=False)]
        self.invoice_rows = data["rows"]
        table = DataTable(id="invoice-table", cursor_type="row")
        table.add_columns("日期", "发票号（查看）", "价税合计", "用途")
        for row in self.invoice_rows:
            key = json.dumps([row["company_id"], row["invoice_no"]], ensure_ascii=False)
            table.add_row(Text(safe_text(row["invoice_date"])), Text(safe_text(row["invoice_no"]), style="#91cbff underline"),
                          Text(row["amount"], style="#91cbff"),
                          Text("已填写" if row["has_purpose"] else "未填写",
                               style="" if row["has_purpose"] else "#f3cf83"), key=key)
        period = f"{year:04d}-{month:02d}" if year else "全部账期"
        pages = max(1, (data["total"] + data["page_size"] - 1) // data["page_size"])
        page = Horizontal(TextAction("上一页", id="invoice-prev", disabled=self.invoice_page <= 1),
                          TextAction("下一页", id="invoice-next", disabled=self.invoice_page >= pages),
                          classes="dialog-actions")
        return [Horizontal(*actions, classes="dialog-actions"),
                Static(safe_text(f"{self.company_name(company)} · {period} · 共 {data['total']} 张"
                                 f" · {self.invoice_page}/{pages} 页{detail}"), markup=False), table, page,
                Static("选择发票编号查看详情。" if self.invoice_rows else "本页没有发票。", markup=False)]

    @on(DataTable.RowSelected, "#invoice-table")
    def invoice_selected(self, event):
        if not self.user or self.workspace_widget("#panes", ContentSwitcher).current != "finance":
            return
        company, invoice = json.loads(event.row_key.value)
        try:
            with closing(open_existing(self.db, readonly=True)) as db, db:
                db.execute("BEGIN")
                current = get_invoice(db, self.user, company, invoice)
        except (ValueError, OSError, sqlite3.Error):
            current = None
        if current:
            self.push_screen(Choices("发票详情", [(self.invoice_text(current), None)]))
        else:
            self.task_feedback("此发票当前不可读取。请返回目录刷新。")

    def record_widgets(self):
        items = [Static(f"本次对话的真实模型请求尝试　{self.model_requests}", markup=False)] if self.model_requests else []
        if self.last_api_status:
            items.append(Static(safe_text("最近联网状态　" + self.last_api_status), markup=False))
        for index, (status, calls, api) in reversed(list(enumerate(self.records, 1))):
            lines = [f"第 {index} 轮 · {status_label(status)}"]
            if api:
                lines.append(f"联网　{api}")
            for call in calls:
                scope = call["scope"] or {}
                where = scope.get("company_id", "")
                if "year" in scope and "month" in scope:
                    where += f" {scope['year']:04d}-{scope['month']:02d}"
                rule_id, version = call.get("rule", (None, None))
                rule = f" · {rule_id} v{version}" if rule_id and version else ""
                lines.append(f"{call['tool']} · {status_label(call['status'])} · {where}{rule} · {call['id']}")
                if call.get("source"):
                    lines.append(f"  来源 {call['source']}")
                if call.get("error"):
                    lines.append(f"  {call['error']}")
            items.append(Static(safe_text("\n".join(lines)), markup=False))
        for state, mode, calls in reversed(self.saved_records):
            lines = [f"历史轮次 · {state} · {mode or '未记录'}"]
            for call in calls:
                scope = call.get("scope") or {}
                lines.append(f"{call['tool']} · {status_label(call['status'])} · {scope.get('company_id','')} · {call['id']}")
            items.append(Static(safe_text("\n".join(lines)), markup=False))
        for audit in invoice_history(self.db, self.user):
            items.append(Static(safe_text(
                f"{audit['committed_at']} · {audit['company_id']} {audit['invoice_no']} · 成功修改"
                f"\n原值 {audit['old_value'] or '（空）'}　新值 {audit['new_value']}"
                f"\n审计编号 {audit['request_id']}"), markup=False))
        return items or [Static("暂无执行记录。", markup=False)]
