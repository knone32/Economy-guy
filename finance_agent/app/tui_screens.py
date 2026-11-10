"""Textual dialogs. Every durable action has a distinct, cancel-first preview."""
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import re
import sqlite3

from rich.text import Text
from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, ContentSwitcher, DirectoryTree, Input, Label, Select, Static

from .cli_workspaces import company_access, import_workspace, missing_migrations, rules_available, upgrade_workspace, workspace_users
from .model_config import Profile, ProfileError, add_profile, update_user_profile, validate_profile, visible_profiles
from .trace import redact
from .tui_local import recent_workbooks
from .win_vault import CredentialError


class TextAction(Button):
    """Terminal-style action, retaining Textual mouse and keyboard semantics."""

    def get_content_width(self, container, viewport):
        extra = 0 if self.has_class("text-link") else 4
        return super().get_content_width(container, viewport) + extra

    def render(self):
        if self.has_class("text-link"):
            label = self.label.copy()
            label.stylize("underline")
        elif self.has_class("current"):
            label = Text.assemble("› ", self.label)
        else:
            label = Text.assemble("[ ", self.label, " ]")
        label.stylize_before(self.rich_style)
        label.justify = self.styles.text_align
        label.no_wrap = True
        return label


class Dialog(ModalScreen):
    BINDINGS = [("escape", "close_dialog", "返回")]

    def action_close_dialog(self):
        self.dismiss(None)


class Approval(Dialog):
    BINDINGS = [Binding("pageup", "scroll_preview('up')", show=False),
                Binding("pagedown", "scroll_preview('down')", show=False)]

    def action_scroll_preview(self, direction):
        content = self.query_one("#approval-content", VerticalScroll)
        if direction == "up":
            content.scroll_page_up(animate=False)
        else:
            content.scroll_page_down(animate=False)

    def __init__(self, title, body, action, *, cancel="取消", danger=False, skip=False):
        super().__init__()
        self.title_text, self.body, self.action_text = title, body, action
        self.cancel_text, self.danger, self.skip = cancel, danger, skip
        self.resolved = False

    def compose(self):
        body = Text()
        for index, line in enumerate(redact(self.body).splitlines()):
            if index:
                body.append("\n")
            label, separator, value = line.partition("　")
            if separator:
                body.append(label + separator, style="dim")
                body.append(value, style="bold" if label in {"原值", "新值", "拟保存值"} else "")
            else:
                body.append(line)
        with Vertical():
            yield Label(self.title_text, classes="dialog-title")
            with VerticalScroll(id="approval-content"):
                yield Static(body, markup=False)
            with Horizontal(classes="dialog-actions"):
                yield TextAction(self.cancel_text, id="cancel")
                if self.skip:
                    yield TextAction("跳过", id="skip")
                yield TextAction(self.action_text, id="approve", variant="error" if self.danger else "primary")

    def on_mount(self):
        self.query_one("#cancel").focus()

    def answer(self, value):
        if self.resolved:
            return
        self.resolved = True
        self.query_one("#approve").disabled = True
        self.dismiss(value)

    def action_close_dialog(self):
        self.answer(False)

    @on(Button.Pressed)
    def pressed(self, event):
        key = event.button.id
        self.answer("skip" if key == "skip" else key == "approve")


class Choices(Dialog):
    def __init__(self, title, choices):
        super().__init__()
        self.title_text, self.choices = title, choices

    def compose(self):
        with VerticalScroll():
            yield Label(self.title_text, classes="dialog-title")
            yield TextAction("返回", id="cancel")
            for index, (label, value) in enumerate(self.choices):
                if value is None:
                    yield Static(Text(redact(label)), classes="field-hint")
                else:
                    yield TextAction(Text(redact(label)), id=f"choice-{index}", classes="choice",
                                     variant="error" if value in {"quit", "logout"} else "default")

    @on(Button.Pressed)
    def pressed(self, event):
        key = event.button.id
        self.dismiss(None if key == "cancel" else self.choices[int(key.split("-")[-1])][1])


class WorkbookBrowser(Dialog):
    def __init__(self, start):
        super().__init__()
        self.start = start

    def compose(self):
        with Vertical(id="settings-shell"):
            yield Label("浏览并打开已有账簿", classes="dialog-title")
            yield Input(str(self.start), id="browse-folder", placeholder="目录路径，按 Enter 打开")
            yield DirectoryTree(self.start, id="workbook-tree")
            yield Static("", id="browse-feedback", markup=False)
            yield TextAction("返回", id="cancel")

    @on(Input.Submitted)
    def change_folder(self, event):
        path = Path(event.value.strip().strip('"')).expanduser()
        if path.is_dir():
            self.query_one(DirectoryTree).path = path.resolve()
        else:
            self.query_one("#browse-feedback", Static).update("找不到此目录。")

    @on(DirectoryTree.FileSelected)
    def selected(self, event):
        if event.path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
            self.dismiss(event.path.resolve())
        else:
            self.query_one("#browse-feedback", Static).update("请选择 .db、.sqlite 或 .sqlite3 文件。")

    @on(Button.Pressed, "#cancel")
    def cancel(self):
        self.dismiss(None)


class Login(Dialog):
    def __init__(self, *, start_in_picker=False):
        super().__init__()
        self.start_in_picker = start_in_picker

    def compose(self):
        with VerticalScroll():
            yield Label("Economy-guy  /  财税工作台", classes="dialog-title")
            yield Static("比赛模拟数据 · SIMULATED_IDENTITY\n选择账簿和模拟账号即可开始。使用真实 AI 前，需要配置模型和密钥。",
                         classes="field-hint", markup=False)
            yield Static(str(self.app.db), id="login-db", classes="field-hint", markup=False)
            yield Label("模拟账号", classes="field-label")
            yield Select([], prompt="选择模拟账号", id="login-user")
            yield Static("", id="login-status", classes="field-error", markup=False)
            with Horizontal(classes="dialog-actions"):
                yield TextAction("进入对话", id="sign-in", variant="primary", disabled=True)
                yield TextAction("选择或导入工作库", id="login-settings")
                yield TextAction("退出程序", id="quit", variant="error")

    def refresh_accounts(self):
        users = []
        message = ""
        blocked = True
        try:
            users = workspace_users(self.app.db)
            if missing_migrations(self.app.db):
                message = "此账簿来自较早版本，需要更新数据库结构才能使用当前功能。原有发票和流水将保留。"
            else:
                blocked = False
                if not rules_available(self.app.db):
                    message = "此账簿缺少启用的业务规则。部分检查不可用，请联系规则管理员。"
        except (OSError, ValueError, sqlite3.Error):
            message = "找不到可用工作库。请选择已有库，或从官方 Excel 导入。"
        self.query_one("#login-db", Static).update(str(self.app.db))
        self.query_one("#login-user", Select).set_options(
            [(f"{row['name']}  ·  {row['user_id']}", row["user_id"]) for row in users])
        self.query_one("#sign-in", Button).disabled = blocked
        self.query_one("#login-status", Static).update(message)

    def open_picker(self):
        self.app.push_screen(Settings(self.app, workbook_only=True), lambda _: self.refresh_accounts())

    def on_mount(self):
        self.refresh_accounts()
        if self.start_in_picker:
            self.call_after_refresh(self.open_picker)

    def action_close_dialog(self):
        self.app.exit()

    @on(Button.Pressed)
    def pressed(self, event):
        match event.button.id:
            case "quit":
                self.app.exit()
            case "login-settings":
                self.open_picker()
            case "sign-in":
                user = self.query_one("#login-user", Select).value
                if user == Select.BLANK:
                    self.query_one("#login-status", Static).update("请先选择模拟账号。")
                else:
                    self.dismiss(user)


class Settings(Dialog):
    def __init__(self, application, *, return_to_task=False, workbook_only=False):
        super().__init__()
        self.application = application
        self.return_to_task = return_to_task
        self.workbook_only = workbook_only
        self.profiles = []

    GROUPS = (("账户", "account"), ("AI 模型", "model"), ("业务数据", "data"), ("高级诊断", "advanced"))

    def compose(self):
        app = self.application
        initial = "model" if app.user else "data"
        with Vertical(id="settings-shell"):
            yield Label("选择账簿" if self.workbook_only else "工作台设置", classes="dialog-title")
            with Horizontal(id="settings-tabs"):
                for label, key in self.GROUPS:
                    yield TextAction(label, id=f"group-{key}", classes="current" if key == initial else None)
            with ContentSwitcher(initial=f"settings-{initial}", id="settings-groups"):
                with VerticalScroll(id="settings-account"):
                    yield Label("我的账户", classes="section")
                    yield Static(f"{app.user or '未登录'} · 比赛模拟数据", markup=False)
                    if app.user:
                        for company in company_access(app.db, app.user):
                            yield Static(Text(company["name"] + " · " + ", ".join(
                                label for key, label in (("read", "可读取"), ("modify", "可修改")) if company[key])))
                        with Horizontal(classes="dialog-actions"):
                            yield TextAction("切换账号", id="switch-account")
                            yield TextAction("退出登录", id="sign-out", variant="error")
                with VerticalScroll(id="settings-model"):
                    yield Label("AI 模型管理中心", classes="section")
                    yield Static("", id="profile-state", classes="field-hint", markup=False)
                    yield TextAction("＋ 新建 AI 配置", id="new-profile", variant="primary", disabled=not app.user)
                    yield Static("", id="model-feedback", classes="field-hint", markup=False)
                    yield Label("我的 AI", classes="section")
                    yield Vertical(id="model-list")
                with VerticalScroll(id="settings-data"):
                    yield Label("打开已有账簿", classes="section")
                    yield Select([(str(p), p) for p in recent_workbooks(app.recent_path)],
                                 prompt="最近使用的账簿", id="recent-workbooks")
                    yield Static(f"当前打开：{app.db}", classes="field-hint", markup=False)
                    yield Label("要打开的账簿路径", classes="field-label")
                    yield Input(value=str(app.db), placeholder="已有工作库或新库路径", id="db")
                    yield Static("", id="db-feedback", classes="field-error", markup=False)
                    with Horizontal(classes="dialog-actions"):
                        yield TextAction("打开已有账簿", id="use-db")
                        yield TextAction("浏览账簿文件", id="browse-db")
                        yield TextAction("查看升级内容", id="upgrade-db")
                    if self.workbook_only:
                        yield Static("选择有效账簿后返回登录。旧账簿可先查看升级内容。", classes="field-hint", markup=False)
                    yield Label("从 Excel 创建新账簿", classes="section")
                    yield Label("Excel 文件路径", classes="field-label")
                    yield Input(placeholder="仅导入时填写官方 .xlsx 文件路径", id="excel")
                    yield Input(placeholder="新账簿保存路径，例如 新账簿.sqlite3", id="new-db")
                    yield Static("", id="excel-feedback", classes="field-error", markup=False)
                    yield TextAction("校验并创建新账簿", id="import-db", variant="primary")
                    scope = app.read_workspace
                    selected = f"{scope[0]} · {scope[1]:04d}-{scope[2]:02d}" if scope else "尚未选择"
                    yield Label("当前只读查询范围", classes="field-label")
                    yield Static(selected + " · 仅用于查询", classes="field-hint", markup=False)
                    if app.user:
                        yield TextAction("选择企业和账期", id="settings-scope")
                        yield TextAction("偏好设置", id="settings-preferences")
                with VerticalScroll(id="settings-advanced"):
                    yield Label("开发诊断", classes="section")
                    yield Static("固定脚本仅用于开发和界面联调，无法理解自然语言。结果仅供开发核对。",
                                 classes="field-hint", markup=False)
                    yield Static(app.profile_status(), id="diagnostic-state", classes="field-hint", markup=False)
                    yield TextAction("启用固定脚本测试（Mock）", id="use-mock", disabled=not app.user)
                    yield TextAction("查看执行记录", id="settings-records", disabled=not app.user)
                    yield TextAction("规则与高级命令行管理", id="legacy")
            with Horizontal(classes="dialog-actions"):
                yield TextAction("返回待办详情" if self.return_to_task else "关闭", id="close")

    def action_close_dialog(self):
        self.dismiss("return-task" if self.return_to_task else None)

    def message(self, text, field="model-feedback"):
        self.query_one("#" + field, Static).update(redact(text))

    @on(Select.Changed, "#recent-workbooks")
    def recent_selected(self, event):
        if event.value != Select.BLANK:
            self.query_one("#db", Input).value = str(event.value)

    def browser_selected(self, path):
        if path:
            self.query_one("#db", Input).value = str(path)
            self.open_workbook(path)

    def open_workbook(self, path):
        transition = "\n切换工作库将结束当前对话并取消未提交操作。请重新选择账号。" if self.app.user and path != self.app.db else ""
        try:
            if path.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
                raise ValueError("请选择 .db、.sqlite 或 .sqlite3 文件。")
            workspace_users(path)
            pending = missing_migrations(path)
        except (OSError, ValueError, sqlite3.Error):
            self.message("找不到可用账簿。请选择存在的财税账簿文件。", "db-feedback")
            return
        if pending:
            self.app.push_screen(Approval(
                "查看升级内容",
                "此账簿来自较早版本，需要更新数据库结构才能使用当前功能。原有发票和流水将保留。\n"
                "先在账簿目录保存并验证独立备份，再补齐审计、规则、待办、偏好及引用所需结构。"
                "现有权限和审计保留。缺少的规则需另行管理。\n"
                f"目标　{path}{transition}", "备份并升级"),
                lambda yes: self.change_workspace(path, upgrade=True) if yes else None)
        elif transition:
            self.app.push_screen(Approval("切换工作库", f"目标　{path}{transition}", "确认切换",
                                          cancel="保留当前工作库"),
                                 lambda yes: self.change_workspace(path) if yes else None)
        else:
            self.change_workspace(path)

    def on_mount(self):
        self.call_later(self.refresh_profiles)

    async def refresh_profiles(self):
        app = self.application
        listing = self.query_one("#model-list", Vertical)
        await listing.remove_children()
        self.profiles = []
        active = None
        try:
            if app.user:
                active = app.resolve_profile(require_key=False).profile
        except ProfileError:
            pass
        using = active if app.mode == "live" else None
        current = (f"{using.profile_name} · {provider_label(using.provider)} / {using.model}"
                   if using else "尚未选择 AI")
        self.message(f"当前使用 · {current}\n{app.profile_status()}", "profile-state")
        self.message(app.profile_status(), "diagnostic-state")
        if not app.user:
            await listing.mount(Static("请登录后管理 AI 配置。", markup=False))
            return
        try:
            self.profiles = [Profile(**item) for item in visible_profiles(app.user, **app.profile_options)]
        except ProfileError as error:
            await listing.mount(Static(f"无法读取 AI 配置。{error}", classes="field-error", markup=False))
            return
        if not self.profiles:
            await listing.mount(Static("暂无 AI 配置。点击上方「＋ 新建 AI 配置」开始。", markup=False))
            return
        entries = []
        for index, profile in enumerate(self.profiles):
            state = "正在使用" if profile == using else "未使用"
            kind = "个人" if profile.scope == "user" else "共享"
            key = "密钥已设置" if app.current_key(profile) else "等待设置密钥"
            entries.extend((
                TextAction(redact(profile.profile_name), id=f"ai-profile-{index}"),
                Static(redact(f"{provider_label(profile.provider)} / {profile.model} · {kind} · {key} · {state}"),
                       classes="field-hint", markup=False),
            ))
        await listing.mount(*entries)

    def profile_done(self, feedback):
        if feedback:
            if self.return_to_task:
                feedback += " 返回待办详情后，可选择「在对话中继续」。"
            self.message(feedback)
            self.call_later(self.refresh_profiles)

    @on(Button.Pressed)
    def pressed(self, event):
        key = event.button.id
        if key.startswith("group-"):
            group = key.removeprefix("group-")
            self.query_one("#settings-groups", ContentSwitcher).current = f"settings-{group}"
            for tab in self.query("#settings-tabs Button"):
                tab.set_class(tab.id == key, "current")
            return
        if key == "new-profile":
            self.app.push_screen(NewUserProfile(self.application.user), self.profile_done)
            return
        if key.startswith("ai-profile-"):
            profile = self.profiles[int(key.removeprefix("ai-profile-"))]
            self.app.push_screen(ProfileDetails(self.application.user, profile), self.profile_done)
            return
        if key == "close":
            self.action_close_dialog()
            return
        if key == "legacy":
            self.app.push_screen(Approval(
                "进入高级命令行管理",
                "即将结束当前 TUI 工作台，进入高级命令行管理。当前对话会关闭，已保存的业务数据不会删除。",
                "进入高级管理", danger=True), lambda yes: self.app.open_legacy_home() if yes else None)
            return
        if key in {"settings-scope", "settings-records", "settings-preferences"}:
            self.dismiss(key)
            return
        if key in {"switch-account", "sign-out"}:
            self.dismiss(key)
            return
        if key == "use-mock":
            def enable_mock():
                self.application.set_model("mock", self.application.profile)
                self.profile_done("已启用固定脚本测试。")
            approve_connection(self, self.application.mode != "mock", enable_mock)
            return
        if key == "browse-db":
            folder = Path(self.query_one("#db", Input).value.strip().strip('"')).expanduser().parent
            self.app.push_screen(WorkbookBrowser(folder if folder.is_dir() else Path.cwd()), self.browser_selected)
            return
        if key == "import-db":
            excel = self.query_one("#excel", Input).value.strip().strip('"')
            target = self.query_one("#new-db", Input).value.strip().strip('"')
            if not excel or not target:
                self.message("请填写 Excel 文件和新账簿的保存路径。", "excel-feedback")
                return
            path = Path(target).expanduser().resolve()
            self.app.push_screen(Approval("创建新账簿", f"Excel　{excel}\n新账簿　{path}", "创建"),
                                 lambda yes: self.change_workspace(path, excel=excel) if yes else None)
            return
        db_text = self.query_one("#db", Input).value.strip().strip('"')
        if not db_text:
            self.message("请填写账簿路径。", "db-feedback")
            return
        self.open_workbook(Path(db_text).expanduser().resolve())

    def change_workspace(self, path, *, upgrade=False, excel=None):
        try:
            counts = None
            backup = None
            if excel:
                if path.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
                    raise ValueError("请选择 .db、.sqlite 或 .sqlite3 新库路径。")
                counts = import_workspace(excel, path)
            elif upgrade:
                workspace_users(path)
                backup = upgrade_workspace(path, backup=True)
            self.app.set_workspace(path)
            message = (f"已导入 {counts['invoices']} 张发票、{counts['bank_transactions']} 条流水。"
                       if counts else "账簿已打开。")
            if backup:
                message = f"账簿已升级。备份位于 {backup}。"
            if not rules_available(path):
                message += " 当前没有启用的业务规则，请联系规则管理员。"
            if self.workbook_only:
                self.app.notify(message)
                self.dismiss(None)
            else:
                self.message(message, "db-feedback")
        except (ValueError, FileExistsError) as error:
            self.message(str(error), "excel-feedback" if excel else "db-feedback")
        except (OSError, sqlite3.Error):
            self.message("工作库不可用。请核对路径、写入权限或文件格式。", "db-feedback")


class Period(Dialog):
    def __init__(self, period, months=(), *, actual_only=False):
        super().__init__()
        self.period = period
        self.months = months
        self.actual_only = actual_only

    def month_options(self, year):
        return [(f"{ym} · {invoices} 张发票 · {bank} 条流水", ym)
                for ym, invoices, bank in self.months if ym[:4] == year]

    def compose(self):
        years = list(dict.fromkeys(ym[:4] for ym, _, _ in self.months))
        with VerticalScroll():
            yield Label("选择账期", classes="dialog-title")
            if years:
                yield Select([(y, y) for y in years], allow_blank=False, value=years[0], id="period-year")
                yield Select(self.month_options(years[0]), prompt="选择已有月份", id="period-month")
                yield TextAction("使用选中月份", id="choose-listed", variant="primary")
            else:
                yield Static("当前企业没有发票或流水记录。", markup=False)
            if not self.actual_only:
                yield Label("输入其他年月", classes="field-label")
                value = f"{self.period[0]:04d}-{self.period[1]:02d}" if self.period else ""
                yield Input(value=value, placeholder="例如 2026-09", id="period")
                yield TextAction("使用输入的账期", id="choose")
            yield Static("", id="period-error", classes="field-error", markup=False)
            yield TextAction("取消", id="cancel")

    @on(Select.Changed, "#period-year")
    def year_changed(self, event):
        self.query_one("#period-month", Select).set_options(self.month_options(event.value))

    @on(Button.Pressed)
    def pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "choose-listed":
            value = self.query_one("#period-month", Select).value
            if value == Select.BLANK:
                self.query_one("#period-error", Static).update("请选择月份。")
            else:
                self.accept(value)
        else:
            self.accept(self.query_one("#period", Input).value)

    @on(Input.Submitted)
    def submitted(self, event):
        self.accept(event.value)

    def accept(self, value):
        from datetime import date
        value = value.strip()
        try:
            parsed = date.fromisoformat(value + "-01")
            if parsed.isoformat()[:7] != value:
                raise ValueError()
        except ValueError:
            self.query_one("#period-error", Static).update("请输入明确年月，例如 2026-09。")
            return
        self.dismiss((parsed.year, parsed.month))


class TaskNote(Dialog):
    def __init__(self, title, progress):
        super().__init__()
        self.title_text, self.progress = title, progress

    def compose(self):
        with Vertical():
            yield Label("新建发票用途待办", classes="dialog-title")
            yield Static(Text(redact(f"{self.title_text}\n{self.progress}")))
            yield Input(placeholder="填写后续处理备注", id="task-note", max_length=500)
            yield Static("", id="task-note-error", markup=False)
            with Horizontal(classes="dialog-actions"):
                yield TextAction("取消", id="cancel")
                yield TextAction("核对待办", id="review-task", variant="primary")

    @on(Button.Pressed)
    def pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            self.review()

    @on(Input.Submitted)
    def review(self):
        note = self.query_one("#task-note", Input).value.strip()
        if note:
            self.dismiss(note)
        else:
            self.query_one("#task-note-error", Static).update("请填写简短备注。")


PROVIDERS = {"deepseek": "DeepSeek", "openai": "OpenAI", "openai-compatible": "OpenAI 兼容"}
ENDPOINT_DEFAULTS = {"deepseek": "https://api.deepseek.com", "openai": "https://api.openai.com/v1",
                     "openai-compatible": ""}


def provider_label(provider):
    return PROVIDERS[provider]


def credential_fields():
    yield Label("API Key", classes="field-label")
    yield Input(placeholder="输入新密钥，内容隐藏", password=True, id="key")
    yield Select([("仅本次使用", "session"), ("Windows 安全保存", "saved")],
                 allow_blank=False, value="session", id="key-mode")


def approve_connection(screen, changed, apply):
    if changed and screen.app.agent is not None:
        screen.app.push_screen(Approval(
            "更换 AI 连接", "可见聊天会保留。新 AI 将从此处开始，当前未提交的操作会取消。",
            "确认更换", cancel="保持当前连接"), lambda yes: apply() if yes is True else None)
    else:
        apply()


def active_profile(app):
    if app.mode == "live":
        try:
            return app.resolve_profile(require_key=False).profile
        except ProfileError:
            pass
    return None


class ProfileDetails(Dialog):
    def __init__(self, actor, profile):
        super().__init__()
        self.actor = actor
        self.profile = profile

    def compose(self):
        app = self.app
        p = self.profile
        with VerticalScroll():
            yield Label(redact(p.profile_name), classes="dialog-title")
            yield Static(redact(f"{provider_label(p.provider)} / {p.model} · {'个人配置' if p.scope == 'user' else '共享配置'}"),
                         markup=False)
            yield Static(app.profile_status() if active_profile(app) == p else "当前未使用此 AI。", markup=False)
            key_state = "密钥已设置" if app.current_key(p) else "等待设置密钥"
            yield Static(f"{key_state}。{app.key_status(p)}", classes="field-hint", markup=False)
            yield Static("", id="detail-feedback", classes="field-error", markup=False)
            yield TextAction("使用此 AI", id="use-profile", variant="primary")
            yield TextAction("编辑配置", id="edit-profile", disabled=p.scope != "user")
            yield TextAction("设置 / 更换密钥", id="set-key")
            yield TextAction("忘记已保存密钥", id="forget-key")
            yield TextAction("返回", id="cancel")

    def check_profile(self):
        if self.app.user != self.actor or self.app.resolve_profile(
            require_key=False, selection=self.profile.profile_name
        ).profile != self.profile:
            raise ProfileError("账号或配置已变化，请返回管理中心重新打开。")

    def feedback(self, message):
        self.query_one("#detail-feedback", Static).update(redact(message))

    @on(Button.Pressed)
    def pressed(self, event):
        action = event.button.id
        if action == "cancel":
            self.dismiss(None)
            return
        app, p = self.app, self.profile
        try:
            self.check_profile()
        except ProfileError as error:
            self.feedback(str(error))
            return
        if action == "edit-profile" and p.scope == "user":
            app.push_screen(NewUserProfile(self.actor, previous=p), self.edited)
        elif action == "set-key":
            app.push_screen(ProfileKey(self.actor, p), self.edited)
        elif action == "use-profile":
            def use():
                try:
                    self.check_profile()
                except ProfileError as error:
                    self.feedback(str(error))
                    return
                app.set_model("live", p.profile_name, remember=True)
                self.dismiss(f"已选择 {p.profile_name} / {p.model}。{app.profile_status()}")
            approve_connection(self, app.model_changes("live", p.profile_name), use)
        elif action == "forget-key":
            def forget(confirmed):
                if confirmed is not True:
                    return
                try:
                    self.check_profile()
                    app.forget_key(p)
                except (ProfileError, CredentialError) as error:
                    self.feedback(str(error))
                    return
                self.dismiss("已移除此配置的 Windows 密钥和本次输入。环境变量如有设置，仍可用。")
            app.push_screen(Approval("忘记已保存密钥", f"模型 {p.model}。移除后将重新核对连接状态。", "确认忘记"), forget)

    def edited(self, feedback):
        if feedback:
            self.dismiss(feedback)


class ProfileKey(Dialog):
    def __init__(self, actor, profile):
        super().__init__()
        self.actor = actor
        self.profile = profile

    def compose(self):
        with VerticalScroll():
            yield Label("设置 / 更换密钥", classes="dialog-title")
            yield Static(redact(f"{self.profile.profile_name} · {self.profile.model}"), markup=False)
            yield from credential_fields()
            yield Static("", id="key-feedback", classes="field-error", markup=False)
            with Horizontal(classes="dialog-actions"):
                yield TextAction("取消", id="cancel")
                yield TextAction("保存密钥", id="save-key", variant="primary")

    @on(Button.Pressed)
    def pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        app, p = self.app, self.profile
        field = self.query_one("#key", Input)
        secret = field.value.strip()
        if not secret:
            self.query_one("#key-feedback", Static).update("请输入 API Key。")
            return
        remember = self.query_one("#key-mode", Select).value == "saved"
        is_active = active_profile(app) == p
        changed = is_active and (app.current_key(p) != secret or app.model_changes("live", p.profile_name, new_key=secret))

        def apply():
            try:
                if app.user != self.actor or app.resolve_profile(require_key=False, selection=p.profile_name).profile != p:
                    raise ProfileError("账号或配置已变化，密钥未保存。")
            except ProfileError as error:
                self.query_one("#key-feedback", Static).update(str(error))
                return
            feedback = app.apply_key(p, secret, remember)
            field.value = ""
            if is_active:
                app.set_model("live", p.profile_name, force=changed)
            self.dismiss(feedback + (" " + app.profile_status() if is_active else " 可从详情选用此 AI。"))

        approve_connection(self, changed, apply)


DEEPSEEK_MODELS = {"deepseek-flash": "DeepSeek Flash", "deepseek-v4-pro": "DeepSeek V4 Pro"}


class NewUserProfile(Dialog):
    def __init__(self, actor, *, previous=None):
        super().__init__()
        self.actor = actor
        self.previous = previous
        self.provider = previous.provider if previous else "openai-compatible"
        self.auto_endpoint = not previous or previous.base_url == ENDPOINT_DEFAULTS[self.provider]

    def compose(self):
        previous = self.previous
        with VerticalScroll():
            yield Label("编辑个人 AI 配置" if previous else "新建 AI 配置", classes="dialog-title")
            yield Label("配置名称", classes="field-label")
            yield Input(value=previous.profile_name if previous else "", placeholder="自定义名称，例如 finance-ai",
                        disabled=previous is not None, id="profile-name")
            yield Label("服务商", classes="field-label")
            yield Select([(label, key) for key, label in PROVIDERS.items()], value=self.provider, allow_blank=False, id="provider")
            yield Label("模型 ID", classes="field-label")
            model = previous.model if previous else ""
            preset = model if model in DEEPSEEK_MODELS else "custom" if model else "deepseek-flash"
            picker = Select([(label, key) for key, label in DEEPSEEK_MODELS.items()] + [("自定义模型 ID", "custom")],
                            value=preset, allow_blank=False, id="deepseek-model")
            picker.display = self.provider == "deepseek"
            yield picker
            manual = Input(value=model, placeholder="填写服务商提供的模型 ID", id="model-name")
            manual.display = self.provider != "deepseek" or preset == "custom"
            yield manual
            yield Static("只离线校验配置。模型是否可用，要在发送消息后才能验证。", classes="field-hint", markup=False)
            if not previous:
                yield from credential_fields()
                yield Static("可留空先保存配置，稍后从详情设置密钥。", classes="field-hint", markup=False)
            with Collapsible(title="高级设置", collapsed=True, id="profile-advanced"):
                yield Label("服务地址（HTTPS）", classes="field-label")
                yield Input(value=previous.base_url if previous else ENDPOINT_DEFAULTS[self.provider], id="endpoint")
                yield Label("凭据环境变量引用", classes="field-label")
                yield Input(value=previous.api_key_env if previous else "", placeholder="留空生成独立引用", id="key-env")
                yield Label("服务账户逻辑引用", classes="field-label")
                yield Input(value=previous.service_account_ref if previous else "", placeholder="留空使用配置名称", id="account-ref")
                yield Label("消息协议", classes="field-label")
                yield Select([("自动", "auto"), ("标准", "standard"), ("DeepSeek Thinking", "deepseek-thinking"),
                              ("Qwen 低力度思考预检", "qwen-thinking-preflight")],
                             value=previous.protocol if previous else "auto", allow_blank=False, id="protocol")
            yield Static("", id="profile-error", classes="field-error", markup=False)
            with Horizontal(classes="dialog-actions"):
                yield TextAction("取消", id="cancel")
                yield TextAction("保存配置" if previous else "保存并使用此 AI", id="save-profile", variant="primary")

    @on(Select.Changed, "#provider")
    def provider_changed(self, event):
        endpoint = self.query_one("#endpoint", Input)
        self.auto_endpoint &= endpoint.value == ENDPOINT_DEFAULTS[self.provider]
        previous = self.provider
        self.provider = event.value
        if self.auto_endpoint:
            endpoint.value = ENDPOINT_DEFAULTS[self.provider]
        picker = self.query_one("#deepseek-model", Select)
        manual = self.query_one("#model-name", Input)
        if self.provider == "deepseek" and previous != "deepseek" and manual.value.strip():
            model = manual.value.strip()
            picker.value = model if model in DEEPSEEK_MODELS else "custom"
        if previous == "deepseek" and self.provider != "deepseek" and not manual.value and picker.value in DEEPSEEK_MODELS:
            manual.value = picker.value
        self.update_model_fields()

    @on(Select.Changed, "#deepseek-model")
    def preset_changed(self):
        self.update_model_fields()

    def update_model_fields(self):
        picker = self.query_one("#deepseek-model", Select)
        picker.display = self.provider == "deepseek"
        self.query_one("#model-name", Input).display = not picker.display or picker.value == "custom"

    def candidate(self, secret):
        def value(field):
            return self.query_one("#" + field, Input).value.strip()

        name, model, endpoint = value("profile-name"), value("model-name"), value("endpoint")
        preset = self.query_one("#deepseek-model", Select).value
        if self.provider == "deepseek" and preset in DEEPSEEK_MODELS:
            model = preset
        if not name:
            raise ProfileError("请填写配置名称，可用英文字母、数字、点、下划线或短横线。")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,199}", model):
            raise ProfileError("请填写有效的模型 ID，并向服务商核对名称。")
        if not endpoint:
            raise ProfileError("请在高级设置填写服务商的 HTTPS 地址。")
        env = value("key-env")
        if not env:
            identity = f"{self.actor}/{name}/{endpoint.rstrip('/')}"
            env = "ECONOMY_PROFILE_" + sha256(identity.encode()).hexdigest()[:20].upper()
        data = {"profile_name": name, "scope": "user", "owner_user_id": self.actor,
                "provider": self.query_one("#provider", Select).value, "model": model,
                "base_url": endpoint, "api_key_env": env, "service_account_ref": value("account-ref") or name,
                "protocol": self.query_one("#protocol", Select).value}
        if redact(data) != data or (secret and secret in data.values()):
            raise ProfileError("请将密钥只填在 API Key 输入框。")
        return validate_profile(data)

    @on(Button.Pressed)
    def pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        if event.button.id != "save-profile":
            return
        app = self.app
        field = self.query_one("#profile-error", Static)
        key = None if self.previous else self.query_one("#key", Input)
        secret = key.value.strip() if key is not None else ""
        remember = key is not None and self.query_one("#key-mode", Select).value == "saved"
        try:
            candidate = self.candidate(secret)
        except ProfileError as error:
            field.update(str(error))
            return
        active_edit = self.previous is not None and active_profile(app) == self.previous
        changed = active_edit and self.previous != candidate
        name = candidate.profile_name

        def save():
            if app.user != self.actor:
                field.update("账号已变化，未保存配置。")
                return
            try:
                if self.previous:
                    update_user_profile(self.previous, asdict(candidate), self.actor, **app.profile_options)
                else:
                    add_profile(asdict(candidate), self.actor, isolated_credentials=True, **app.profile_options)
            except ProfileError as error:
                field.update(str(error))
                return
            try:
                if app.resolve_profile(require_key=False, selection=name).profile != candidate:
                    raise ProfileError("重载的配置与保存内容不一致")
            except ProfileError:
                if changed:
                    app.set_model("live", name, force=True)
                self.dismiss("配置已写入，但重新读取核对失败。未处理本次输入的密钥，请重新打开管理中心核对。")
                return
            feedback = app.apply_key(candidate, secret, remember) if secret else ""
            if key is not None:
                key.value = ""
            if not self.previous or active_edit:
                app.set_model("live", name, force=changed, remember=self.previous is None)
                feedback += " " + app.profile_status()
            self.dismiss(f"已保存 {name}。{feedback}".strip())

        approve_connection(self, not self.previous or changed, save)
