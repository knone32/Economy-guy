"""Textual dialogs. Every durable action has a distinct, cancel-first preview."""
from pathlib import Path
import os
import sqlite3

from rich.text import Text
from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, ContentSwitcher, DirectoryTree, Input, Label, Select, Static

from .cli_workspaces import company_access, import_workspace, missing_migrations, rules_available, upgrade_workspace, workspace_users
from .model_config import ProfileError, add_profile, load_profiles, validate_profile, visible_profiles
from .trace import redact
from .tui_local import recent_workbooks


class TextAction(Button):
    """Terminal-style action, retaining Textual mouse and keyboard semantics."""

    def get_content_width(self, container, viewport):
        extra = 0 if self.has_class("compact-action") or self.has_class("text-link") else 4
        return super().get_content_width(container, viewport) + extra

    def render(self):
        if self.has_class("text-link"):
            label = Text.assemble(self.label, style="underline")
        elif self.has_class("compact-action"):
            label = Text.assemble("›" if self.has_class("current") else "", self.label)
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

    def __init__(self, title, body, action, *, cancel="取消", danger=False):
        super().__init__()
        self.title_text, self.body, self.action_text = title, body, action
        self.cancel_text, self.danger = cancel, danger
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
        self.answer(event.button.id == "approve")


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
        self.profiles = {}
        try:
            self.profiles = {p["profile_name"]: p for p in
                             visible_profiles(application.user, **application.profile_options)}
        except ProfileError:
            pass

    GROUPS = (("账户", "account"), ("AI 模型", "model"), ("业务数据", "data"), ("高级诊断", "advanced"))

    def compose(self):
        app = self.application
        initial = "model" if app.user else "data"
        try:
            selected_profile = app.resolve_profile(require_key=False).profile.profile_name if app.user else None
        except ProfileError:
            selected_profile = None
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
                    yield Label("正常使用（真实 AI）", classes="section")
                    yield Static("使用已配置的 AI 服务处理财税问题。发送消息可能产生 API 费用。",
                                 classes="field-hint", markup=False)
                    yield Label("AI 配置", classes="field-label")
                    yield Select([(f"{n} · {p['model']}", n) for n, p in self.profiles.items()],
                                 prompt="使用默认配置", id="profile",
                                 value=selected_profile if selected_profile in self.profiles else Select.BLANK)
                    yield Static(app.profile_status(), id="profile-state", classes="field-hint", markup=False)
                    yield Label("API 密钥", classes="field-label")
                    yield Input(placeholder="隐藏输入，仅在本次运行使用", password=True, id="key")
                    yield Static("", id="model-feedback", classes="field-hint", markup=False)
                    with Horizontal(classes="dialog-actions"):
                        yield TextAction("使用此 AI 配置", id="apply-model", variant="primary")
                        yield TextAction("新建个人 AI 配置", id="new-profile", disabled=not app.user)
                with VerticalScroll(id="settings-data"):
                    yield Label("打开已有账簿", classes="section")
                    yield Select([(str(p), p) for p in recent_workbooks(app.recent_path)],
                                 prompt="最近使用的账簿", id="recent-workbooks")
                    yield Label("当前账簿路径", classes="field-label")
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

    @on(Select.Changed, "#profile")
    def profile_changed(self, event):
        item = self.profiles.get(event.value)
        if item and not self.app.model_changes("live", event.value):
            self.message(self.app.profile_status(), "profile-state")
        elif item:
            ready = bool(os.environ.get(item["api_key_env"], "").strip())
            self.query_one("#profile-state", Static).update(
                f"配置可用 · {redact(item['model'])} · 密钥{'已设置' if ready else '未设置'}。应用后可查看联网状态。")
        else:
            self.message("应用时将检查默认配置是否有效。", "profile-state")

    def profile_created(self, name):
        if name is None:
            return
        self.profiles = {p["profile_name"]: p for p in visible_profiles(self.app.user, **self.app.profile_options)}
        select = self.query_one("#profile", Select)
        select.set_options([(f"{n} · {p['provider']} / {p['model']}", n) for n, p in self.profiles.items()])
        select.value = name
        self.message("个人 Profile 已保存且离线校验通过。可输入 Key，再应用模型设置。")

    def request_model(self, mode, profile):
        selected = None
        secret = ""
        if mode == "live":
            try:
                selected = self.app.resolve_profile(require_key=False, selection=profile).profile
            except ProfileError:
                self.message("没有可用的 AI 配置。请选择有效配置或新建个人 AI 配置。")
                return
            key_field = self.query_one("#key", Input)
            secret = key_field.value.strip()
            env = selected.api_key_env
            if secret and ((env != "API_KEY" and not env.endswith("_API_KEY")) or os.environ.get(env)):
                self.message("请从启动终端管理此密钥。")
                return

        def apply(confirmed):
            if not confirmed:
                return
            if secret:
                os.environ[env] = secret
                key_field.value = ""
            self.app.set_model(mode, profile)
            status = self.app.profile_status()
            self.message(status, "profile-state")
            self.message(status, "diagnostic-state")
            if selected:
                _, title, detail = self.app.model_state()
                followup = " 返回待办详情后，选择「在对话中继续」。" if self.return_to_task else ""
                self.message(f"已选择 {selected.profile_name} / {selected.model}。{title}。{detail}{followup}")
            else:
                self.message("已启用固定脚本测试。")
        changed = self.app.model_changes(mode, profile)
        if changed and self.app.agent is not None:
            self.app.push_screen(Approval(
                "切换 AI 模型",
                "切换 AI 模型将开始新的对话。当前未提交的操作会取消，已保存的财务数据、待办和审计记录不会删除。",
                "确认切换", cancel="保持当前模型"), apply)
        else:
            apply(True)

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
            self.app.push_screen(NewUserProfile(), self.profile_created)
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
        if key in {"settings-scope", "settings-records"}:
            self.dismiss(key)
            return
        if key in {"switch-account", "sign-out"}:
            self.dismiss(key)
            return
        if key == "use-mock":
            self.request_model("mock", self.app.profile)
            return
        if key == "apply-model":
            value = self.query_one("#profile", Select).value
            self.request_model("live", None if value == Select.BLANK else value)
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


class NewUserProfile(Dialog):
    def compose(self):
        with VerticalScroll():
            yield Label("新建个人 AI 配置", classes="dialog-title")
            yield Static("此处保存服务配置。密钥请在返回模型设置后填写。", classes="field-hint", markup=False)
            yield Label("配置名称", classes="field-label")
            yield Input(placeholder="例如 finance-flash", id="profile-name")
            yield Static("", id="profile-error", classes="field-error", markup=False)
            yield Label("服务商", classes="field-label")
            yield Select([("DeepSeek", "deepseek"), ("OpenAI", "openai"), ("OpenAI 兼容", "openai-compatible")],
                         value="deepseek", allow_blank=False, id="provider")
            yield Label("模型名称", classes="field-label")
            yield Input(value="deepseek-flash", placeholder="模型名称", id="model-name")
            yield Static("", id="model-name-error", classes="field-error", markup=False)
            yield Label("服务地址（HTTPS）", classes="field-label")
            yield Input(value="https://api.deepseek.com", placeholder="HTTPS 模型端点", id="endpoint")
            yield Static("", id="endpoint-error", classes="field-error", markup=False)
            yield Label("密钥环境变量名", classes="field-label")
            yield Input(value="DEEPSEEK_API_KEY", placeholder="Key 环境变量名", id="key-env")
            yield Static("", id="key-env-error", classes="field-error", markup=False)
            with Horizontal(classes="dialog-actions"):
                yield TextAction("取消", id="cancel")
                yield TextAction("离线校验并保存", id="save-profile", variant="primary")

    @on(Button.Pressed)
    def pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        name = self.query_one("#profile-name", Input).value.strip()
        data = {
            "profile_name": name, "scope": "user", "owner_user_id": self.app.user,
            "provider": self.query_one("#provider", Select).value, "service_account_ref": name,
            "model": self.query_one("#model-name", Input).value.strip(),
            "base_url": self.query_one("#endpoint", Input).value.strip(),
            "api_key_env": self.query_one("#key-env", Input).value.strip(), "protocol": "auto",
        }
        required = (("profile_name", "profile-error", "请填写配置名称。"),
                    ("model", "model-name-error", "请填写模型名称。"),
                    ("base_url", "endpoint-error", "请填写服务地址。"),
                    ("api_key_env", "key-env-error", "请填写密钥环境变量名。"))
        for key, field, message in required:
            self.query_one("#" + field, Static).update("" if data[key] else message)
        if any(not data[key] for key, _, _ in required):
            return
        try:
            candidate = validate_profile(data)
            profiles, _ = load_profiles(**self.app.profile_options)
            if any(p.api_key_env == candidate.api_key_env and p.base_url != candidate.base_url
                   for p in profiles.values()):
                raise ProfileError("不同端点请配置独立的凭据环境变量")
            add_profile(data, self.app.user, **self.app.profile_options)
        except ProfileError as error:
            message = str(error)
            field = ("endpoint-error" if "端点" in message or "URL" in message else
                     "key-env-error" if "环境变量" in message else "profile-error")
            for name in ("endpoint-error", "key-env-error", "profile-error"):
                self.query_one("#" + name, Static).update(redact(message) if name == field else "")
            return
        self.dismiss(name)
