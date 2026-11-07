"""Textual dialogs. Every durable action has a distinct, cancel-first preview."""
from pathlib import Path
import os
import sqlite3

from rich.text import Text
from textual import on
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static

from .cli_workspaces import import_workspace, missing_migrations, upgrade_workspace, workspace_users
from .model_config import ProfileError, add_profile, load_profiles, validate_profile, visible_profiles
from .trace import redact


class Dialog(ModalScreen):
    DEFAULT_CSS = """
    Dialog { align: center middle; background: #091820 70%; }
    Dialog > VerticalScroll { width: 76; max-width: 95%; height: auto; max-height: 92%;
        background: #182d36; border: tall #508a8a; padding: 1 2; }
    Dialog Label { color: #a5e1d9; margin-bottom: 1; }
    Dialog Button { margin: 0 1 0 0; }
    Dialog Horizontal { height: 3; margin-top: 1; }
    Dialog Input, Dialog Select { margin-bottom: 1; }
    """
    BINDINGS = [("escape", "close_dialog", "返回")]

    def action_close_dialog(self):
        self.dismiss(None)


class Approval(Dialog):
    def __init__(self, title, body, action):
        super().__init__()
        self.title_text, self.body, self.action_text = title, body, action
        self.resolved = False

    def compose(self):
        with VerticalScroll():
            yield Label(self.title_text)
            yield Static(redact(self.body), markup=False)
            with Horizontal():
                yield Button("取消", id="cancel")
                yield Button(self.action_text, id="approve", variant="warning")

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
            yield Label(self.title_text)
            yield Button("返回", id="cancel")
            for index, (label, _) in enumerate(self.choices):
                yield Button(Text(redact(label)), id=f"choice-{index}")

    @on(Button.Pressed)
    def pressed(self, event):
        key = event.button.id
        self.dismiss(None if key == "cancel" else self.choices[int(key.split("-")[-1])][1])


class Login(Dialog):
    def compose(self):
        with VerticalScroll():
            yield Label("Economy-guy  ／  财税工作台")
            yield Static("SIMULATED_IDENTITY · 比赛模拟环境\n选择工作库中的模拟账号进入对话。正式业务环境尚未开放。",
                         markup=False)
            yield Static(str(self.app.db), id="login-db", markup=False)
            yield Select([], prompt="选择模拟账号", id="login-user")
            yield Static("", id="login-status", markup=False)
            with Horizontal():
                yield Button("进入对话", id="sign-in", variant="primary", disabled=True)
                yield Button("选择或导入工作库", id="login-settings")
                yield Button("退出程序", id="quit")

    def refresh_accounts(self):
        users = []
        message = ""
        try:
            users = workspace_users(self.app.db)
            if missing_migrations(self.app.db):
                message = "当前库需要加法升级。请打开工作库设置。"
        except (OSError, ValueError, sqlite3.Error):
            message = "找不到可用工作库。请选择已有库，或从官方 Excel 导入。"
        self.query_one("#login-db", Static).update(str(self.app.db))
        self.query_one("#login-user", Select).set_options(
            [(f"{row['user_id']}  {row['name']}", row["user_id"]) for row in users])
        self.query_one("#sign-in", Button).disabled = bool(message)
        self.query_one("#login-status", Static).update(message)

    def on_mount(self):
        self.refresh_accounts()

    def action_close_dialog(self):
        self.app.exit()

    @on(Button.Pressed)
    def pressed(self, event):
        match event.button.id:
            case "quit":
                self.app.exit()
            case "login-settings":
                self.app.push_screen(Settings(self.app), lambda _: self.refresh_accounts())
            case "sign-in":
                user = self.query_one("#login-user", Select).value
                if user == Select.BLANK:
                    self.query_one("#login-status", Static).update("请先选择模拟账号。")
                else:
                    self.dismiss(user)


class Settings(Dialog):
    def __init__(self, application):
        super().__init__()
        self.application = application
        self.profiles = {}
        try:
            self.profiles = {p["profile_name"]: p for p in
                             visible_profiles(application.user, **application.profile_options)}
        except ProfileError:
            pass

    def compose(self):
        app = self.application
        with VerticalScroll():
            yield Label("工作区设置")
            yield Static("业务身份与模型模式分别设置。联网只发生在 Live 对话发送后。", markup=False)
            yield Select([("Live · 真实模型", "live"), ("Mock · 离线测试", "mock")],
                         value=app.mode, allow_blank=False, id="mode")
            yield Select([(f"{n} · {p['provider']} / {p['model']}", n) for n, p in self.profiles.items()],
                         prompt="选择可见 Profile", id="profile",
                         value=app.profile if app.profile in self.profiles else Select.BLANK)
            yield Static(app.profile_status(), id="profile-state", markup=False)
            yield Input(placeholder="可选 · 隐藏输入 Key，仅在本进程设置", password=True, id="key")
            with Horizontal():
                yield Button("应用模型设置", id="apply-model")
                yield Button("新建个人 Profile", id="new-profile", disabled=not app.user)
            yield Label("工作库")
            yield Input(value=str(app.db), placeholder="已有工作库或新库路径", id="db")
            yield Input(placeholder="官方 .xlsx 路径（仅导入时填写）", id="excel")
            with Horizontal():
                yield Button("切换已有库", id="use-db")
                yield Button("校验并导入", id="import-db")
                yield Button("升级旧库", id="upgrade-db")
            yield Static("最近联网状态　" + (app.last_api_status or "尚未发起请求"), markup=False)
            yield Button("规则与高级管理", id="legacy")
            yield Static("", id="settings-status", markup=False)
            yield Button("关闭", id="close")

    def message(self, text):
        self.query_one("#settings-status", Static).update(redact(text))

    @on(Select.Changed, "#profile")
    def profile_changed(self, event):
        item = self.profiles.get(event.value)
        if item:
            ready = bool(os.environ.get(item["api_key_env"], "").strip())
            self.query_one("#profile-state", Static).update(
                f"离线配置合法 · {item['provider']} / {redact(item['model'])} · "
                f"Key {'就绪' if ready else '未设置'}。联网结果请见对话执行记录。")

    def profile_created(self, name):
        if name is None:
            return
        self.profiles = {p["profile_name"]: p for p in visible_profiles(self.app.user, **self.app.profile_options)}
        select = self.query_one("#profile", Select)
        select.set_options([(f"{n} · {p['provider']} / {p['model']}", n) for n, p in self.profiles.items()])
        select.value = name
        self.message("个人 Profile 已保存且离线校验通过。可输入 Key，再应用模型设置。")

    @on(Button.Pressed)
    def pressed(self, event):
        key = event.button.id
        if key == "new-profile":
            self.app.push_screen(NewUserProfile(), self.profile_created)
            return
        if key == "close":
            self.dismiss(None)
            return
        if key == "legacy":
            self.app.push_screen(
                Approval("打开数字管理菜单", "当前对话将关闭。已保存的任务、偏好和审计仍可查询。", "打开管理菜单"),
                lambda yes: self.app.open_legacy_home() if yes else None)
            return
        if key == "apply-model":
            model = self.query_one("#profile", Select).value
            mode = self.query_one("#mode", Select).value
            item = self.profiles.get(model)
            key_field = self.query_one("#key", Input)
            secret = key_field.value.strip()
            key_field.value = ""
            if secret:
                if item is None:
                    self.message("请先选择 Profile。")
                    return
                env = item["api_key_env"]
                if (env != "API_KEY" and not env.endswith("_API_KEY")) or os.environ.get(env):
                    self.message("请从启动终端管理此凭据环境变量。")
                    return
                os.environ[env] = secret
            self.app.set_model(mode, model if item else None)
            if item:
                self.profile_changed(Select.Changed(self.query_one("#profile", Select), model))
            self.message(self.app.profile_status())
            return
        db_text = self.query_one("#db", Input).value.strip().strip('"')
        if not db_text:
            self.message("请填写工作库路径。")
            return
        path = Path(db_text).expanduser().resolve()
        if key == "use-db":
            self.change_workspace(path)
        elif key == "upgrade-db":
            self.app.push_screen(Approval("升级旧库", f"补齐现有库的表和索引。\n{path}", "升级"),
                                 lambda yes: self.change_workspace(path, upgrade=True) if yes else None)
        elif key == "import-db":
            excel = self.query_one("#excel", Input).value.strip().strip('"')
            if not excel:
                self.message("请填写官方 Excel 路径及一个新工作库路径。")
                return
            self.app.push_screen(Approval("导入新工作库", f"{excel}\n新库 {path}", "导入"),
                                 lambda yes: self.change_workspace(path, excel=excel) if yes else None)

    def change_workspace(self, path, *, upgrade=False, excel=None):
        try:
            counts = None
            if excel:
                if path.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
                    raise ValueError("请选择 .db、.sqlite 或 .sqlite3 新库路径。")
                counts = import_workspace(excel, path)
            elif upgrade:
                workspace_users(path)
                upgrade_workspace(path)
            self.app.set_workspace(path)
            self.message(f"已导入 {counts['invoices']} 张发票、{counts['bank_transactions']} 条流水。请重新选择账号。"
                         if counts else "工作库已选定。请重新选择账号。")
        except (ValueError, FileExistsError) as error:
            self.message(str(error))
        except (OSError, sqlite3.Error):
            self.message("工作库不可用。请核对路径、写入权限或文件格式。")


class Period(Dialog):
    def __init__(self, period):
        super().__init__()
        self.period = period

    def compose(self):
        with VerticalScroll():
            yield Label("选择账期 · 仅用于工作区查看")
            value = f"{self.period[0]:04d}-{self.period[1]:02d}" if self.period else ""
            yield Input(value=value, placeholder="例如 2026-09", id="period")
            yield Static("", id="period-error", markup=False)
            with Horizontal():
                yield Button("取消", id="cancel")
                yield Button("使用此账期", id="choose")

    @on(Button.Pressed)
    def pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            self.accept()

    @on(Input.Submitted)
    def submitted(self):
        self.accept()

    def accept(self):
        from datetime import date
        value = self.query_one("#period", Input).value
        try:
            parsed = date.fromisoformat(value + "-01")
            if parsed.isoformat()[:7] != value:
                raise ValueError()
        except ValueError:
            self.query_one("#period-error", Static).update("请输入明确年月，例如 2026-09。")
            return
        self.dismiss((parsed.year, parsed.month))


class NewUserProfile(Dialog):
    def compose(self):
        with VerticalScroll():
            yield Label("新建个人 Profile · 仅离线校验")
            yield Static("只保存配置和环境变量名。请在返回设置后输入 Key。", markup=False)
            yield Input(placeholder="Profile 名称", id="profile-name")
            yield Select([("DeepSeek", "deepseek"), ("OpenAI", "openai"), ("OpenAI 兼容", "openai-compatible")],
                         value="deepseek", allow_blank=False, id="provider")
            yield Input(value="deepseek-flash", placeholder="模型名称", id="model-name")
            yield Input(value="https://api.deepseek.com", placeholder="HTTPS 模型端点", id="endpoint")
            yield Input(value="DEEPSEEK_API_KEY", placeholder="Key 环境变量名", id="key-env")
            yield Static("", id="profile-error", markup=False)
            with Horizontal():
                yield Button("取消", id="cancel")
                yield Button("离线校验并保存", id="save-profile")

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
        try:
            candidate = validate_profile(data)
            profiles, _ = load_profiles(**self.app.profile_options)
            if any(p.api_key_env == candidate.api_key_env and p.base_url != candidate.base_url
                   for p in profiles.values()):
                raise ProfileError("不同端点请配置独立的凭据环境变量")
            add_profile(data, self.app.user, **self.app.profile_options)
        except ProfileError as error:
            self.query_one("#profile-error", Static).update(redact(str(error)))
            return
        self.dismiss(name)
