"""Settings UI for local display habits and the existing enterprise preference service."""
import sqlite3

from textual import on
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Input, Label, Static

from .persistence import ManagementIntent, ManagementTurn, confirm_management
from .preferences import manage_preference
from .trace import redact
from .tui_screens import Approval, Choices, Dialog, TextAction


class PreferenceForm(Dialog):
    def __init__(self, name="", value=""):
        super().__init__()
        self.habit_name, self.habit_value = name, value

    def compose(self):
        with VerticalScroll():
            yield Label("企业偏好", classes="dialog-title")
            yield Input(self.habit_name, placeholder="为这项习惯取一个名称", id="habit-name",
                        disabled=bool(self.habit_name), max_length=80)
            yield Input(self.habit_value, placeholder="输入希望如何展示或阅读", id="habit-value", max_length=500)
            yield Static("", id="habit-error", markup=False)
            with Horizontal(classes="dialog-actions"):
                yield TextAction("取消", id="cancel")
                yield TextAction("核对", id="habit-review", variant="primary")

    @on(Button.Pressed)
    def pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        name = self.query_one("#habit-name", Input).value.strip()
        value = self.query_one("#habit-value", Input).value.strip()
        if not name or not value or redact([name,value]) != [name,value]:
            self.query_one("#habit-error", Static).update("请填写名称与内容，移除可能的凭据。")
            return
        self.dismiss((name,value))


def open_preferences(app):
    def selected(value):
        if value == "personal":
            personal(app)
        elif value == "company":
            app.choose_company(lambda company: company_preferences(app, company) if company else None)

    app.push_screen(Choices("偏好设置", [
        ("个人回复习惯 · 当前账号与账簿", "personal"),
        ("企业偏好 · 当前账号与所选企业", "company"),
        ("偏好仅影响表达和只读习惯。当前明确要求优先。", None),
    ]), selected)


def personal(app):
    if not app.conversation:
        app.notify("本机会话存储不可用，暂时无法保存个人偏好。", severity="warning")
        return
    try:
        current = app.conversation.personal_detail()
    except (OSError, ValueError, sqlite3.Error):
        app.notify("本机偏好无法读取，请重新打开账簿。", severity="warning")
        return
    def selected(value):
        if value:
            action = "delete" if value == "普通" else "set"
            desired = "" if action == "delete" else value
            review(app, "display_preference", action, value, f"原值　{current}\n拟保存值　{value}",
                   lambda intent: app.conversation.manage_detail(action,desired,intent),
                   lambda outcome: outcome["evidence"].get("preference_readback_verified") is True,
                   lambda: personal(app))
    app.push_screen(Choices(f"个人回复习惯 · 当前为{current}",
                    [("简洁","简洁"),("详细","详细"),("移除设置并恢复普通","普通")]),selected)


def company_preferences(app, company):
    try:
        rows = manage_preference(app.db,app.user,company,"list")
    except (OSError, sqlite3.Error):
        app.notify("企业偏好无法读取，请重新打开账簿。", severity="warning")
        return
    if not rows["ok"]:
        app.notify(rows["error"] or "无法读取企业偏好。", severity="warning")
        return
    entries = rows["data"]

    def form(action, entry=None):
        name, value = (entry["preference_key"],entry["value"]) if entry else ("","")
        if action == "delete":
            change(action,name,"",value)
        else:
            app.push_screen(PreferenceForm(name,value),
                            lambda picked: change(action,*picked,value) if picked else None)

    def change(action, name, value, previous):
        def service(intent):
            return manage_preference(app.db,app.user,company,action,name,value,intent=intent)

        def verified(_):
            readback = manage_preference(app.db,app.user,company,"get",name)
            return (readback["status"] == "NOT_FOUND" if action == "delete" else
                    readback["status"] == "SUCCESS" and readback["data"]["value"] == value)

        shown = f"企业　{app.company_name(company)}（{company}）\n偏好　{name}\n原值　{previous or '（无）'}\n拟保存值　{value or '（移除）'}"
        review(app,"preference",action,f"{name}：{value}",shown,service,verified,
               lambda: company_preferences(app,company))

    def selected(value):
        if value == "new":
            form("create")
        elif isinstance(value,int):
            entry = entries[value]
            app.push_screen(Choices(f"偏好 · {entry['preference_key']}",
                [(entry["value"],None),("修改","update"),("删除","delete")]),
                lambda action: form(action,entry) if action else None)

    app.push_screen(Choices(f"企业偏好 · {app.company_name(company)}",
        [("新建偏好","new"),*((f"{row['preference_key']} · {row['value']}",i) for i,row in enumerate(entries))]),
        selected)


def review(app, domain, action, source, body, service, verified, done):
    actor, path, epoch = app.user, app.db, app.session_epoch
    intent = ManagementIntent(actor,domain,source,action,turn=ManagementTurn(actor))
    try:
        if app.conversation:
            app.conversation.validate()
        proposed = service(intent)
    except (OSError, ValueError, sqlite3.Error):
        app.notify("偏好存储不可用。", severity="warning")
        return
    if proposed["status"] != "WAITING_CONFIRMATION":
        app.notify(proposed["error"] or "无法准备偏好更改。", severity="warning")
        return

    # Display exactly the old value bound by the service, even if another process edited it.
    old = proposed["data"].get("current") or {}
    body = "\n".join(f"原值　{old.get('value','（无）')}" if line.startswith("原值　") else line
                      for line in body.splitlines())

    def save(yes):
        try:
            if yes is not True or app.busy or (app.user,app.db,app.session_epoch) != (actor,path,epoch):
                return
            if app.conversation:
                app.conversation.validate()
            outcome = service(confirm_management(intent,proposed["data"]))
            if outcome["status"] == "SUCCESS":
                app.notify("偏好已保存并回读。" if verified(outcome) else "当前值未能核实，请重新查看。")
            else:
                app.notify(outcome["error"] or "偏好未保存。", severity="warning")
        except (OSError, ValueError, sqlite3.Error):
            app.notify("请重新查看当前偏好，核实保存结果。", severity="warning")
        finally:
            intent.turn.active = False
            if (app.user,app.db,app.session_epoch) == (actor,path,epoch):
                done()

    app.push_screen(Approval("确认偏好更改",f"用户　{actor}\n{body}\n尚未保存。","确认"),save)
