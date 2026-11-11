"""Offline contest examples using the normal Textual workbench and business tools."""
import json
from pathlib import Path
from tempfile import mkdtemp

from textual import on
from textual.containers import HorizontalScroll, Vertical
from textual.widgets import Button, ContentSwitcher, Input

from .cli_workspaces import import_workspace
from .tui import AgentWorkspace
from .tui_screens import TextAction

SUMMARY = "汇总甲企业 2026 年 9 月的发票价税合计、银行收入和支出"
ASK_PERIOD = "帮我查一下甲企业的发票和银行收支情况"
SUPPLY_PERIOD = "2026 年 9 月"
DIRECTORY = "列出甲企业 2026 年 9 月全部发票，按价税合计从高到低排序"
BANK = "查看甲企业 2026 年 9 月的银行流水明细"
CHECK_A = "检查甲企业 2026 年 9 月哪些发票缺少必填用途"
RULE_HISTORY = "查看甲企业 R002 的历史版本，以及哪个版本当前有效"
RULE_B = "乙企业 2026 年 9 月适用什么发票用途规则？"
CHECK_B = "检查乙企业 2026 年 9 月哪些发票违反用途必填要求"
EDIT = "把甲企业 F002 的用途改成资料打印"
REMARK = "把甲企业 F003 的备注改成待补充报销凭证"
READ_INVOICE = "查看甲企业 F002 当前的用途和备注"
CANCEL_EDIT = "把甲企业 F004 的用途改成办公资料"
TASK = "为甲企业 2026 年 9 月剩余缺用途发票创建待办，下次继续处理"
PROGRESS = "查看甲企业 2026 年 9 月的待办和当前剩余缺用途发票"
PREFERENCE = "记住我希望甲企业的财务查询回复尽量简洁"
READ_PREFERENCE = "查看我在甲企业保存的财务回复偏好"
NO_DATA = "汇总甲企业 2026 年 7 月的发票和银行收支"
DENIED_READ = "查看乙企业 2026 年 9 月的发票"
DENIED_EDIT = "把甲企业 F002 的用途改成办公资料"

SCOPE = {"company_id": "C001", "year": 2026, "month": 9}
SCOPE_B = {**SCOPE, "company_id": "C002"}
PREFERENCE_KEY = "财务回复偏好"

SECTIONS = {
    "finance": ("财务查询", (
        ("summary", "汇总收支", SUMMARY),
        ("ask-period", "追问年月", ASK_PERIOD),
        ("supply-period", "补年月（先追问）", SUPPLY_PERIOD),
        ("directory", "金额降序", DIRECTORY),
        ("bank", "银行流水", BANK),
    )),
    "rules": ("规则知识库", (
        ("check-a", "甲企业用途检查", CHECK_A),
        ("rule-history", "R002 历史版本", RULE_HISTORY),
        ("rule-b", "乙企业适用规则", RULE_B),
        ("check-b", "乙企业用途检查", CHECK_B),
    )),
    "invoices": ("发票操作", (
        ("edit", "修改 F002 用途", EDIT),
        ("remark", "修改 F003 备注", REMARK),
        ("read-invoice", "重查 F002", READ_INVOICE),
        ("cancel-edit", "取消示例 F004", CANCEL_EDIT),
    )),
    "memory": ("任务与记忆", (
        ("task", "创建待办", TASK),
        ("progress", "待办进度", PROGRESS),
        ("preference", "保存偏好", PREFERENCE),
        ("read-preference", "读取偏好", READ_PREFERENCE),
    )),
    "safety": ("安全与审计", (
        ("no-data", "无数据查询", NO_DATA),
        ("denied-read", "乙企业查询（U002）", DENIED_READ),
        ("denied-edit", "甲企业修改（U002）", DENIED_EDIT),
        ("audit", "查看操作记录", None),
    )),
}
PRESETS = {f"demo-{key}": request for _, rows in SECTIONS.values() for key, _, request in rows}
PRESET_HINTS = {
    "supply-period": "先在本对话点击「追问年月」，再补充年月。",
    "cancel-edit": "在正式确认弹窗点击「终止」或按 Esc。",
    "progress": "创建待办后可查看保存结果，也可直接核对当前进度。",
    "denied-read": "通过「账户」切换到 U002，再执行乙企业查询。",
    "denied-edit": "通过「账户」切换到 U002，再执行甲企业修改。",
    "audit": "打开现有「记录」页，展开操作编号核对工具、规则和审计。",
}

TOOL_PROPOSALS = {
    SUMMARY: ("get_finance_summary", SCOPE),
    DIRECTORY: ("list_invoice_directory", {**SCOPE, "page": 1, "sort_by": "amount", "sort_order": "desc"}),
    BANK: ("list_bank_transactions", SCOPE),
    CHECK_A: ("check_missing_purpose", SCOPE),
    RULE_HISTORY: ("list_rule_versions", {"company_id": "C001", "rule_id": "R002"}),
    RULE_B: ("get_applicable_rules", {"company_id": "C002", "rule_type": "purpose", "business_date": "2026-09-01"}),
    CHECK_B: ("check_missing_purpose", SCOPE_B),
    READ_INVOICE: ("get_invoice", {"company_id": "C001", "invoice_no": "F002"}),
    TASK: ("manage_task", {**SCOPE, "action": "create", "task_id": "", "note": ""}),
    PREFERENCE: ("manage_preference", {"company_id": "C001", "action": "create",
                                       "key": PREFERENCE_KEY, "value": "尽量简洁"}),
    READ_PREFERENCE: ("manage_preference", {"company_id": "C001", "action": "get",
                                            "key": PREFERENCE_KEY, "value": ""}),
    NO_DATA: ("get_finance_summary", {**SCOPE, "month": 7}),
    DENIED_READ: ("list_invoice_directory", {**SCOPE_B, "page": 1}),
}
EDITS = {
    EDIT: ("F002", "purpose", "资料打印"),
    REMARK: ("F003", "remark", "待补充报销凭证"),
    CANCEL_EDIT: ("F004", "purpose", "办公资料"),
    DENIED_EDIT: ("F002", "purpose", "办公资料"),
}


def assistant_reply(kind, text, **fields):
    return {"role": "assistant", "content": json.dumps(
        {"kind": kind, "text": text, **fields}, ensure_ascii=False)}


def demo_model(messages, tools):
    user_index = next(index for index in range(len(messages) - 1, -1, -1)
                      if messages[index]["role"] == "user" and not messages[index].get("name"))
    request = messages[user_index]["content"].strip().rstrip("。.")
    results = [json.loads(message["content"]) for message in messages[user_index + 1:]
               if message["role"] == "tool"]

    def tool(name, params):
        return {"role": "assistant", "tool_calls": [{"id": f"mock-demo-{len(results) + 1}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(params, ensure_ascii=False)}}]}

    if request == ASK_PERIOD:
        return assistant_reply("clarification", "请问要查询哪一年、哪一月？", missing_fields=["year", "month"])
    if request == SUPPLY_PERIOD:
        # Agent.ask only includes this message after consuming a valid pending clarification.
        original = json.dumps(ASK_PERIOD + "。", ensure_ascii=False)
        resumed = any(message["role"] == "system"
                      and message["content"].startswith("本轮用户提供了上一项未完成业务请求的字面补充。")
                      and message["content"].endswith((original, json.dumps(ASK_PERIOD, ensure_ascii=False)))
                      for message in messages[user_index + 1:])
        if not resumed:
            return assistant_reply("clarification", "请先在本对话点击「追问年月」，再补充年月。",
                                   missing_fields=["demo_example"])
        if not results:
            return tool("get_finance_summary", SCOPE)
    elif request in EDITS:
        invoice, field, value = EDITS[request]
        if not results:
            return tool("get_invoice", {"company_id": "C001", "invoice_no": invoice})
        selection = (results[0].get("data") or {}).get("selection_id")
        if len(results) == 1 and selection:
            return tool("propose_invoice_changes", {"selection_id": selection, "field": field,
                        "new_value": value, "mode": "item", "excluded_invoice_ids": []})
    elif request == PROGRESS:
        if not results:
            return tool("list_tasks", {"company_id": "C001"})
        if len(results) == 1:
            return tool("check_missing_purpose", SCOPE)
    elif request in TOOL_PROPOSALS and not results:
        return tool(*TOOL_PROPOSALS[request])
    if results:
        return assistant_reply("information", "银行流水仅供查询。" if request == BANK else "请核对本轮业务结果。")
    return assistant_reply("clarification", "离线演示支持输入框上方的预置对话，请选择一项发送。",
                           missing_fields=["demo_example"])


class DemoWorkspace(AgentWorkspace):
    mock_demo = True

    def __init__(self, folder, template):
        super().__init__(folder / "demo.sqlite3", template, folder / "profiles-unused.json",
                         model=demo_model, trace_path=folder / "trace.jsonl",
                         session_path=folder / "conversations.sqlite3")
        self.mode = "mock"

    def model_state(self):
        return "mock", "MOCK · OFFLINE DEMO", "固定脚本 · 仅用官方虚构账簿 · 0 API 请求"

    def chat_presets(self):
        yield Vertical(
            HorizontalScroll(
                *(TextAction(label, id=f"demo-category-{key}", classes="current" if key == "finance" else None)
                  for key, (label, _) in SECTIONS.items()), id="demo-categories"),
            ContentSwitcher(
                *(HorizontalScroll(
                    *(TextAction(label, id=f"demo-{key}", tooltip=PRESET_HINTS.get(key, request))
                      for key, label, request in rows), id=f"demo-options-{section}")
                  for section, (_, rows) in SECTIONS.items()),
                initial="demo-options-finance", id="demo-options"),
            id="demo-presets",
        )

    @on(Button.Pressed, "#demo-categories Button")
    def select_category(self, event):
        event.stop()
        category = event.button.id.removeprefix("demo-category-")
        self.workspace_widget("#demo-options", ContentSwitcher).current = f"demo-options-{category}"
        for button in self.workspace_widget("#demo-categories").query(Button):
            button.set_class(button is event.button, "current")

    @on(Button.Pressed, "#demo-options Button")
    def send_preset(self, event):
        event.stop()
        if not self.user or self.busy:
            return
        key = event.button.id
        if key == "demo-audit":
            self.show("records")
            return
        if key in {"demo-denied-read", "demo-denied-edit"} and self.user != "U002":
            self.note(PRESET_HINTS[key.removeprefix("demo-")])
            return
        if key == "demo-supply-period":
            pending = self.agent.pending_intent if self.agent else None
            if not pending or pending["request"].strip().rstrip("。.") != ASK_PERIOD:
                self.note(PRESET_HINTS["supply-period"])
                return
        request = PRESETS[key]
        if not request.endswith("？"):
            request += "。"
        prompt = self.workspace_widget("#prompt", Input)
        prompt.post_message(Input.Submitted(prompt, request))

    @staticmethod
    def business_card(tool, data, evidence):
        if tool == "manage_preference" and isinstance(data, dict):
            return "企业偏好", f"{data['preference_key']}：{data['value']}"
        card = AgentWorkspace.business_card(tool, data, evidence)
        if tool == "list_bank_transactions" and card:
            title, detail = card
            return title, "银行流水只读。\n" + detail
        return card

    def open_settings(self):
        self.note("离线演示使用独立账簿和固定脚本。请通过启动菜单选 1 使用真实模型。")


def open_demo(root: Path, *, reset=False):
    storage = root / "data" / "mock-demo"
    storage.mkdir(parents=True, exist_ok=True)
    existing = [folder for folder in storage.glob("run-*")
                if (folder / "demo.sqlite3").is_file()]
    if reset or not existing:
        folder = Path(mkdtemp(prefix="run-", dir=storage))
        import_workspace(root / "tests" / "fixtures" / "example.xlsx", folder / "demo.sqlite3")
    else:
        folder = max(existing, key=lambda path: path.stat().st_ctime_ns)
    return DemoWorkspace(folder, root / "config" / "model_profiles.toml")
