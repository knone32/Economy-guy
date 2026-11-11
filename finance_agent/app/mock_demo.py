"""Offline contest examples using the normal Textual workbench and business tools."""
import json
from pathlib import Path
from tempfile import mkdtemp

from .cli_workspaces import import_workspace
from .tui import AgentWorkspace

SUMMARY = "汇总甲企业 2026 年 9 月的发票价税合计、银行收入和支出"
EDIT = "把甲企业 F002 的用途改成资料打印"
TASK = "为甲企业 2026 年 9 月剩余缺用途的发票创建待办"
PROGRESS = "查看甲企业 2026 年 9 月待办和剩余缺用途发票"
SCOPE = {"company_id": "C001", "year": 2026, "month": 9}


def demo_model(messages, tools):
    user_index = next(index for index in range(len(messages) - 1, -1, -1)
                      if messages[index]["role"] == "user" and not messages[index].get("name"))
    request = messages[user_index]["content"].strip().rstrip("。.")
    results = [json.loads(message["content"]) for message in messages[user_index + 1:]
               if message["role"] == "tool"]

    def tool(name, params, seq=1):
        return {"role": "assistant", "tool_calls": [{"id": f"mock-demo-{seq}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(params, ensure_ascii=False)}}]}

    if request == EDIT:
        if not results:
            return tool("get_invoice", {"company_id": "C001", "invoice_no": "F002"})
        selection = (results[0].get("data") or {}).get("selection_id")
        if len(results) == 1 and selection:
            return tool("propose_invoice_changes", {"selection_id": selection, "field": "purpose",
                        "new_value": "资料打印", "mode": "item", "excluded_invoice_ids": []}, 2)
    elif request == SUMMARY and not results:
        return tool("get_finance_summary", SCOPE)
    elif request == TASK and not results:
        return tool("manage_task", {**SCOPE, "action": "create", "task_id": "", "note": ""})
    elif request == PROGRESS:
        if not results:
            return tool("list_tasks", {"company_id": "C001"})
        if len(results) == 1:
            return tool("check_missing_purpose", SCOPE, 2)
    if request in {SUMMARY, EDIT, TASK, PROGRESS}:
        reply = {"kind": "information", "text": "固定演示步骤已结束，请查看实际执行结果。"}
    else:
        reply = {"kind": "clarification", "text": "离线演示只支持工作台中列出的固定示例，请复制其中一条。",
                 "missing_fields": ["demo_example"]}
    return {"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)}


class DemoWorkspace(AgentWorkspace):
    mock_demo = True

    def __init__(self, folder, template):
        super().__init__(folder / "demo.sqlite3", template, folder / "profiles-unused.json",
                         model=demo_model, trace_path=folder / "trace.jsonl",
                         session_path=folder / "conversations.sqlite3")
        self.mode = "mock"

    def model_state(self):
        return "mock", "MOCK · OFFLINE DEMO", "固定脚本 · 仅用官方虚构账簿 · 0 API 请求"

    def signed_in(self, user):
        super().signed_in(user)
        if self.user:
            self.chat_message("离线演示 · 固定模型提案", "\n".join((SUMMARY, EDIT, TASK, PROGRESS)))

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
