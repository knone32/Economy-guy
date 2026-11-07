"""Single-session Agent workspace for interactive terminals."""
from concurrent.futures import Future, TimeoutError
from contextlib import closing
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3

from rich.panel import Panel
from rich.text import Text
from textual import on, work
from textual.app import App
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, ContentSwitcher, DataTable, Footer, Input, RichLog, Static
from textual.worker import get_current_worker

from .agent import Agent
from .cli_chat import safe_text, turn_tools
from .cli_workspaces import company_access, invoice_history, missing_migrations, workspace_users
from .model_config import ProfileError, load_profiles, resolve_connection
from .queries import list_invoices
from .stage2_schema import open_existing
from .tasks import list_tasks, task_details
from .trace import redact
from .tui_intent import edit_turn
from .tui_screens import Approval, Choices, Login, Settings

ROOT = Path(__file__).resolve().parents[1]
STATUS = {
    "ANSWERED": "本轮回复完成", "COMPLETED": "本轮处理完成", "SUCCESS": "执行成功",
    "NO_DATA": "没有符合条件的记录", "NO_CHANGE": "当前无需变更",
    "WAITING_USER": "等待补充", "AMBIGUOUS": "请补充范围", "WAITING_CONFIRMATION": "等待确认",
    "COMMITTED": "已成功保存并核验", "CURRENT_VALUE_MATCHES": "当前值已相同",
    "DENIED": "权限不足", "ERROR": "本轮执行失败", "SCOPE_MISMATCH": "请求范围不一致", "CANCELLED": "已取消",
    "UNKNOWN_OUTCOME": "提交结果未知，请查看执行记录", "MODEL_LIMIT": "本轮处理达到上限",
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
    """A deliberately fixed offline script for checking UI wiring."""
    current = next(m["content"] for m in reversed(messages) if m["role"] == "user")
    if messages[-1]["role"] == "tool":
        return {"role": "assistant", "content": '{"kind":"information","text":"已返回本轮业务核验。"}'}
    from .responses import explicit_scope
    scope = explicit_scope(current, include_update_aliases=True)
    if not scope.get("periods") and not scope.get("month"):
        return {"role": "assistant", "content": '{"kind":"clarification","text":"请补充账期","missing_fields":["year","month"]}'}
    return {"role": "assistant", "tool_calls": [{
        "id": "offline-query", "type": "function", "function": {"name": "get_finance_summary",
        "arguments": '{"company_id":"C001","year":2026,"month":9}'}}]}


class AgentWorkspace(App):
    TITLE = "Economy-guy · 财税工作台"
    CSS_PATH = "tui.tcss"
    NAV_ITEMS = (
        ("go-chat", "对话", "当前对话"),
        ("go-tasks", "待办", "待办事项"),
        ("go-finance", "发票", "发票明细"),
        ("go-records", "记录", "执行记录"),
        ("account", "账户", "我的账户"),
    )
    BINDINGS = [("f2", "navigation", "导航"), ("f3", "account", "账户"),
                ("f4", "cancel_edit", "取消未提交操作"), ("ctrl+q", "quit_safe", "退出")]

    def __init__(self, db, template, local, *, model=None, trace_path=None):
        super().__init__()
        self.db = Path(db).resolve()
        self.profile_options = {"template": template, "local": local}
        self.trace_path = trace_path
        self.model_override = model
        self.agent = None
        self.user = None
        self.profile = None
        self.mode = "live"
        self.company = None
        self.period = None
        self.read_workspace = None
        self.busy = False
        self.supplement = False
        self.task_route = None
        self.session_epoch = 0
        self.records = []
        self.model_requests = 0
        self.last_api_status = ""
        self.last_api_ok = None

    def compose(self):
        yield Static("Economy-guy", id="status", markup=False)
        with Horizontal(id="layout"):
            with Vertical(id="rail"):
                yield Button("菜单", id="nav", tooltip="展开导航 · F2")
                for key, short, label in self.NAV_ITEMS:
                    if key == "account":
                        yield Static("", id="rail-spacer")
                    yield Button(short, id=key, tooltip=label, classes="current" if key == "go-chat" else None)
            with ContentSwitcher(initial="chat", id="panes"):
                with Vertical(id="chat"):
                    yield RichLog(id="chat-log", markup=False, wrap=True)
                    with Horizontal(id="ai-guide"):
                        yield Static("", id="ai-guide-text", markup=False)
                        yield Button("配置 AI 模型", id="configure-ai", variant="primary")
                    yield Static("发送消息", id="composer-label", markup=False)
                    yield Static("", id="chat-note", markup=False)
                    yield Button("补充本次修改", id="supplement")
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
        self.push_screen(Login(), self.signed_in)

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
        self.profile = None
        self.reset_agent(clear_log=True)
        self.note("可输入问题，按 Enter 发送。")
        self.chat_message("工作台", "可直接查询、提出修改、保存待办。发票和待办变更会弹出确认。"
                          "\n例如：把甲企业 F002 的用途改成资料打印。")
        self.show("chat")

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

    def model_changes(self, mode, profile):
        if mode != self.mode:
            return True
        try:
            _, default = load_profiles(**self.profile_options)
        except ProfileError:
            default = None
        fallback = os.environ.get("FINANCE_MODEL_PROFILE") or default
        current = self.agent.connection.profile.profile_name if self.agent and self.agent.connection else self.profile
        return (profile or fallback) != (current or fallback)

    def set_model(self, mode, profile):
        if self.model_changes(mode, profile):
            self.reset_agent(clear_log=True)
        self.mode, self.profile = mode, profile
        self.update_header()

    def reset_agent(self, *, clear_log):
        if self.agent:
            self.agent.cancel_update()
        self.agent = None
        self.supplement = False
        self.workspace_widget("#supplement", Button).display = False
        self.session_epoch += 1
        self.records.clear()
        self.model_requests = 0
        self.last_api_status = ""
        self.last_api_ok = None
        if clear_log:
            self.workspace_widget("#chat-log", RichLog).clear()

    def logout(self):
        self.reset_agent(clear_log=True)
        self.user, self.profile, self.company, self.period, self.task_route = None, None, None, None, None
        self.read_workspace = None
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
        elif destination == "settings-scope":
            self.choose_workspace_scope()
        elif destination == "settings-records":
            self.show("records")
        elif destination in {"switch-account", "sign-out"}:
            self.confirm_logout("切换账号" if destination == "switch-account" else "退出登录")
        self.update_header()

    def resolve_profile(self, *, require_key):
        _, default = load_profiles(**self.profile_options)
        name = self.profile or os.environ.get("FINANCE_MODEL_PROFILE") or default
        if not name:
            raise ProfileError("No AI configuration selected")
        return resolve_connection(self.user, name, require_key=require_key, **self.profile_options)

    def model_state(self):
        """Offline configuration checks and observed transport outcomes stay distinct."""
        if self.mode == "mock":
            return "mock", "固定脚本测试（开发诊断）", "使用固定示例联调界面。"
        try:
            profile = self.resolve_profile(require_key=False).profile
        except ProfileError:
            return "unconfigured", "尚未配置 AI", "选择现有 AI 配置或新建一个。"
        if not os.environ.get(profile.api_key_env, "").strip():
            return "missing-key", "缺少 API 密钥", f"为 {profile.model} 输入密钥后即可发送。"
        if self.last_api_ok is True:
            return "connected", "真实 AI 已响应", profile.model
        if self.last_api_ok is False:
            return "failed", "最近连接失败", "请核对网络和 AI 配置，可在执行记录查看详情。"
        return "unverified", "连接尚未验证", f"{profile.model} 的密钥已设置。发送消息后才会联网。"

    def profile_status(self):
        _, title, detail = self.model_state()
        return f"{title} · {detail}"

    def update_header(self):
        company = self.company or "未选择"
        period = f"{self.period[0]:04d}-{self.period[1]:02d}" if self.period else "未选择"
        state, title, detail = self.model_state()
        mode = "固定脚本测试" if state == "mock" else "真实 AI"
        model_label = title if state == "mock" else f"{mode}  /  {title}"
        self.workspace_widget("#status", Static).update(safe_text(
            f"Economy-guy  /  财税工作台     比赛模拟数据 · {self.user or '未登录'}\n"
            f"{company}  ·  {period}     {model_label}"))
        self.workspace_widget("#ai-guide-text", Static).update(safe_text(f"{title}\n{detail}"))
        self.workspace_widget("#ai-guide").display = state in {"unconfigured", "missing-key", "unverified", "failed"}

    def note(self, text):
        self.workspace_widget("#chat-note", Static).update(safe_text(text))

    def chat_message(self, role, text):
        log = self.workspace_widget("#chat-log", RichLog)
        log.write(Text(role, style="bold #9ad8ce"))
        log.write(Text(safe_text(text)))

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
                           management_confirmation=self.confirm_management, **options)
        self.agent.messages[0]["content"] += (
            "\n本工作台内，待办 create/update/correct 的 note 必须逐字保留当前用户原始要求，"
            "不补造任务内容、期限或目标。明确缺失参数时追问。")
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
        if not self.user or self.screen is not self.screen_stack[0]:
            return
        rail = self.workspace_widget("#rail")
        expanded = not rail.has_class("expanded")
        rail.set_class(expanded, "expanded")
        self.workspace_widget("#nav", Button).label = "收起导航" if expanded else "菜单"
        for key, short, label in self.NAV_ITEMS:
            self.workspace_widget("#" + key, Button).label = label if expanded else short

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
        if not self.user:
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
            self.reset_agent(clear_log=True)
            self.show("chat")
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
            self.supplement = False
            self.workspace_widget("#supplement", Button).display = False
            self.note("已取消当前未提交操作。")

    @on(Button.Pressed)
    def button(self, event):
        key = event.button.id or ""
        if key.startswith("go-"):
            self.show(key.removeprefix("go-"))
        elif key == "nav":
            self.action_navigation()
        elif key == "account":
            self.action_account()
        elif key == "configure-ai":
            self.open_settings()
        elif key.startswith("todo-"):
            route = getattr(self, "task_links", {}).get(key)
            if route:
                self.open_task(route)
        elif key == "back-tasks":
            self.show("tasks")
        elif key == "linked-finance":
            self.select_pane("finance")
            self.call_later(self.refresh_pane, "finance")
        elif key == "back-detail" and self.task_route:
            self.open_task(self.task_route)
        elif key == "choose-finance":
            self.choose_workspace_scope(for_finance=True)
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
        try:
            self.ensure_agent()
        except (ProfileError, ValueError):
            self.update_header()
            self.note("暂时无法发送。请使用「配置 AI 模型」检查设置。")
            return
        event.input.value = ""
        self.chat_message("你", message)
        args = edit_turn(message, self.agent.pending_edit, guided=self.supplement)
        if args.pop("cancel", False):
            self.action_cancel_edit()
            return
        self.busy = True
        event.input.disabled = True
        self.note("正在处理，请稍候。")
        self.supplement = False
        self.workspace_widget("#supplement", Button).display = False
        self.run_turn(message, args, self.read_workspace)

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
            note = p.get("note") or current.get("context", {}).get("note") or "（无）"
            title = "确认待办"
            name = self.company_name(p["company_id"])
            body = (f"用户　{self.user}\n对象　{name} · {p['year']:04d}-{p['month']:02d} 发票用途\n"
                    f"备注　{note}\n关联表格　发票明细\n"
                    f"操作　{dict(create='新建', update='补充', correct='更正', resume='恢复', complete='完成', cancel='取消', wait='等待补充', pause='暂停').get(p['action'], p['action'])}\n"
                    "业务服务已检查本次操作的权限与冲突，确认后会重新检查。")
        else:
            title = "确认偏好"
            body = (f"用户　{self.user}\n企业　{p['company_id']}\n"
                    f"偏好　{p['key']}\n原值　{(proposal.get('current') or {}).get('value') or '（无）'}\n"
                    f"拟保存值　{p.get('value') or '（空）'}\n操作　{'删除' if p['action'] == 'delete' else '保存'}")
        danger = p["action"] in {"cancel", "delete"}
        return self.wait_confirmation(title, body, "确认操作" if danger else "确认保存", danger=danger)

    @work(thread=True, group="agent", exit_on_error=False)
    def run_turn(self, message, args, read_workspace):
        agent = self.agent
        offset = len(agent.messages)
        receipt = None
        try:
            answer = agent.ask(message, read_workspace=read_workspace, **args)
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
                        receipt = agent.commit_update(draft.request_id, draft.fingerprint())
                if receipt is None:
                    receipt = agent.cancel_update()
            calls = turn_tools(agent.messages[offset:])
            verified, cards = [], []
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
                if call is not None and outcome["status"] in {"SUCCESS", "NO_DATA"}:
                    card = self.business_card(call["tool"], outcome.get("data"), evidence)
                    if card:
                        cards.append(card)
                if outcome["status"] == "SUCCESS" and evidence.get("management_confirmation"):
                    verified.append("已按本次确认保存，业务库记录可重新查看。")
            self.call_from_thread(self.finish_turn, answer, calls, receipt, verified, cards)
        except Exception:
            agent.cancel_update()
            if self.is_running:
                self.call_from_thread(self.fail_turn)

    @staticmethod
    def business_card(tool, data, evidence):
        if evidence.get("source") != "current_sqlite" or not isinstance(data, dict):
            return None
        if tool == "get_finance_summary":
            return ("账期合计", "\n".join(
                f"{label}　¥{data[key + '_total']} · {data[key + '_count']} 条"
                for label, key in (("发票价税合计", "invoice"), ("银行收入", "bank_income"), ("银行支出", "bank_expense"))))
        if tool == "check_missing_purpose":
            return ("用途检查", f"当前缺失用途 {data['count']} 张")
        return None

    def finish_turn(self, answer, calls, receipt, verified, cards):
        response = self.agent.last_response
        status = receipt["status"] if receipt else response["execution"]["stop_reason"]
        # Keep raw wire JSON and internal anchors in execution evidence rather than chat.
        readable = "\n".join(line for line in answer.splitlines()
                             if not line.startswith(("已展示引用列表 anchor:", "缺失明细（业务数据）：",
                                                     "持久化管理结果", "当前剩余对象：",
                                                     "本轮查询结果（业务数据")))
        if readable.startswith("请求已安全停止") or readable.startswith("已达到本轮预算"):
            readable = status_label(status)
        if cards:
            readable = "\n".join(line for line in readable.splitlines()
                                 if not line.startswith(("本轮查询：", "本轮检查：")))
        if readable:
            self.chat_message("Agent", readable)
        log = self.workspace_widget("#chat-log", RichLog)
        for title, text in cards:
            log.write(Panel(Text(safe_text(text)), title=title, border_style="#36515d", expand=False))
        for detail in verified:
            self.chat_message("业务回执", detail)
        if receipt:
            self.chat_message("发票回执", receipt["message"])
            if receipt.get("task_progress"):
                from .responses import render_task_progress
                progress = render_task_progress(receipt["task_progress"])
                self.chat_message("当前待办", "\n".join(line for line in progress.splitlines()
                                                  if not line.startswith("当前剩余对象：")))
        api = response.get("api_counts")
        if api:
            self.model_requests += api["attempts"]
        self.records.append((status, calls, self.last_api_status))
        for call in calls:
            scope = call.get("scope") or {}
            if self.read_workspace is None and call["status"] in {"SUCCESS", "NO_DATA"} and scope.get("company_id"):
                self.company = scope["company_id"]
                if "year" in scope and "month" in scope:
                    self.period = scope["year"], scope["month"]
        self.workspace_widget("#supplement", Button).display = bool(self.agent.pending_edit)
        self.note(f"{status_label(status)} · F2 打开导航，可选择执行记录")
        self.unlock()

    def fail_turn(self):
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
        for key, _, _ in self.NAV_ITEMS:
            self.workspace_widget("#" + key, Button).set_class(key == f"go-{page}", "current")

    def show(self, page):
        if not self.user:
            return
        if page != "finance":
            self.task_route = None
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
        widgets = []
        for company in company_access(self.db, self.user):
            if not company["read"]:
                continue
            outcome = list_tasks(self.db, self.user, company["company_id"])
            for task in outcome["data"] or []:
                key = f"todo-{len(self.task_links)}"
                self.task_links[key] = (task["company_id"], task["task_id"])
                widgets.append(Button(Text(safe_text(
                    f"{company['name']} · {task['year']:04d}-{task['month']:02d} 发票用途"
                    f" · {TASK_STATUS.get(task['status'], '未知')}")), id=key))
        return widgets or [Static("当前账号没有可查看的待办。可在对话中提出保存缺失用途待办。", markup=False)]

    def open_task(self, route):
        self.task_route = route
        self.select_pane("tasks")
        self.call_later(self.refresh_pane, "tasks")

    def task_detail_widgets(self, route):
        outcome = task_details(self.db, self.user, *route)
        back = Button("返回待办列表", id="back-tasks")
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
                Button(Text(safe_text(title)), id="linked-finance", tooltip="打开当前发票明细"),
                Button("在对话中继续", id="continue-task", variant="primary", disabled=not data["can_execute"]),
                classes="task-card",
            ),
        ]

    def continue_task(self):
        if self.busy or not self.task_route:
            return
        try:
            self.ensure_agent()
            outcome = self.agent.focus_task(*self.task_route)
        except (ValueError, OSError, sqlite3.Error):
            self.show("chat")
            self.note("无法恢复待办。请核对模型设置和当前工作库。")
            return
        if not outcome["ok"] or not outcome["data"]["can_execute"]:
            self.call_later(self.refresh_pane, "tasks")
            return
        data = outcome["data"]
        task, count = data["task"], data["check"]["count"]
        self.read_workspace = None
        self.company = task["company_id"]
        self.period = task["year"], task["month"]
        self.show("chat")
        hint = "可以询问剩余事项。" if count else "可以明确要求标记完成，保存前仍会确认。"
        self.chat_message("当前待办", f"已重新核对此待办，当前缺失用途 {count} 张。{hint}")

    def company_name(self, company):
        return next((r["name"] for r in company_access(self.db, self.user)
                     if r["company_id"] == company and r["read"]), company)

    def choose_workspace_scope(self, for_finance=False):
        try:
            rows = company_access(self.db, self.user)
        except (OSError, sqlite3.Error):
            self.note("无法读取企业权限，请核对工作库。")
            return
        self.push_screen(Choices("选择可读企业", [(r["name"], r["company_id"]) for r in rows if r["read"]]),
                         lambda company: self.pick_period(company, for_finance) if company else None)

    def pick_period(self, company, for_finance):
        from .tui_screens import Period

        def selected(period):
            if period is None:
                return
            self.company, self.period = company, period
            self.read_workspace = (company, *period)
            self.update_header()
            if for_finance:
                self.show("finance")

        self.push_screen(Period(self.period), selected)

    def finance_widgets(self):
        if self.task_route:
            outcome = task_details(self.db, self.user, *self.task_route)
            back = Button("返回待办详情", id="back-detail")
            if not outcome["ok"]:
                return [back, Static(status_label(outcome["status"]), markup=False)]
            data = outcome["data"]
            task = data["task"]
            company, period = task["company_id"], (task["year"], task["month"])
            invoices = data["invoices"]
            check = data["check"]
            related = list_tasks(self.db, self.user, company)["data"] or []
            related = [t for t in related if (t["year"], t["month"]) == period]
            states = "、".join(TASK_STATUS[t["status"]] for t in related) or "无"
            if check is not None:
                rule = check["rule"]
                details = f"当前缺失用途 {check['count']} 张 · {rule['rule_id']} v{rule['version']}"
            else:
                details = data["problem"]
            header = f"{self.company_name(company)} · {period[0]:04d}-{period[1]:02d}\n{details}\n本账号关联待办　{states}"
        else:
            back = Button("选择企业和账期", id="choose-finance")
            if not self.company or not self.period:
                return [back, Static("请选择企业和账期查看发票明细。", markup=False)]
            company, period = self.company, self.period
            with closing(open_existing(self.db, readonly=True)) as db:
                db.execute("BEGIN")
                invoices = list_invoices(db, self.user, company, *period)
            header = f"{self.company_name(company)} · {period[0]:04d}-{period[1]:02d} 发票明细"
        self.invoice_rows = invoices
        table = DataTable(id="invoice-table", cursor_type="row")
        table.add_columns("发票号", "日期", "价税合计", "用途")
        for index, row in enumerate(invoices):
            table.add_row(*(Text(safe_text(str(value))) for value in
                            (row["invoice_no"], row["invoice_date"], row["amount"], row["purpose"] or "未填写")),
                          key=str(index))
        return [back, Static(safe_text(header), markup=False), table,
                Static("选择一行查看明细。" if invoices else "没有符合条件的发票。",
                       id="invoice-detail", markup=False)]

    @on(DataTable.RowSelected, "#invoice-table")
    def invoice_selected(self, event):
        index = int(event.row_key.value)
        if not self.user or index >= len(self.invoice_rows):
            return
        row = self.invoice_rows[index]
        from .queries import get_invoice
        try:
            with closing(open_existing(self.db, readonly=True)) as db:
                current = get_invoice(db, self.user, row["company_id"], row["invoice_no"])
        except (ValueError, OSError, sqlite3.Error):
            current = None
        details = "记录已不可读取。请刷新企业与账期。"
        if current:
            details = (f"销售方　{current['seller_name']}\n项目　{current['item_name']}\n"
                       f"用途　{current['purpose'] or '未填写'}\n备注　{current['remark'] or '（无）'}")
        self.workspace_widget("#invoice-detail", Static).update(safe_text(details))

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
                if call.get("error"):
                    lines.append(f"  {call['error']}")
            items.append(Static(safe_text("\n".join(lines)), markup=False))
        for audit in invoice_history(self.db, self.user):
            items.append(Static(safe_text(
                f"{audit['committed_at']} · {audit['company_id']} {audit['invoice_no']} · 成功修改"
                f"\n原值 {audit['old_value'] or '（空）'}　新值 {audit['new_value']}"
                f"\n审计编号 {audit['request_id']}"), markup=False))
        return items or [Static("暂无执行记录。", markup=False)]
