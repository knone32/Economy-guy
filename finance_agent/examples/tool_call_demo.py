"""最小 Tool Calling 教学实验：加法与 Stage 0 发票金额查询。"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import sys
from typing import Any

# 让 `python examples/tool_call_demo.py` 也能导入同级 app 包。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.finance import invoice_total
from app.queries import QueryError


ADD_SCHEMA = {
    "type": "function",
    "function": {
        "name": "add",
        "description": "计算两个整数的和。",
        "parameters": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"], "additionalProperties": False},
    },
}
INVOICE_TOTAL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "invoice_total",
        "description": "查询指定企业、年份和月份的发票价税合计。当前用户由程序决定，不能由模型指定。",
        "parameters": {"type": "object", "properties": {"company_id": {"type": "string", "description": "企业编号，例如 C001"}, "year": {"type": "integer"}, "month": {"type": "integer"}}, "required": ["company_id", "year", "month"], "additionalProperties": False},
    },
}
TOOLS = [ADD_SCHEMA, INVOICE_TOTAL_SCHEMA]


class ToolValidationError(ValueError):
    """模型工具请求的结构或参数不安全、不完整时抛出。"""


class PermissionDenied(PermissionError):
    """权限拒绝必须直接终止，不能靠模型重试绕过。"""


@dataclass
class ToolRequest:
    call_id: str
    name: str
    arguments: str


@dataclass
class ModelReply:
    content: str | None = None
    tool_calls: list[ToolRequest] | None = None


def add(a: int, b: int) -> int:
    """最普通的 Python 工具函数。"""
    return a + b


def open_readonly_database(db_path: str | Path) -> sqlite3.Connection:
    """只读打开已有数据库；不存在时绝不初始化或写入。"""
    path = Path(db_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"数据库不存在：{path}。请先按 Stage 0 说明手动执行 main.py init。")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row  # Stage 0 的权限与汇总函数按列名读取结果。
    return connection


def _require_exact_int(arguments: dict[str, Any], name: str) -> int:
    value = arguments.get(name)
    if type(value) is not int:  # bool 在 Python 中是 int 的子类，因此必须严格判断。
        raise ToolValidationError(f"参数 {name} 必须是整数")
    return value


def execute_tool(request: ToolRequest, current_user: str, db_path: str | Path) -> dict[str, Any]:
    """Harness 白名单校验后执行工具；模型无法指定当前用户。"""
    if request.name not in {"add", "invoice_total"}:
        raise ToolValidationError(f"工具不在白名单中：{request.name}")
    try:
        arguments = json.loads(request.arguments)
    except json.JSONDecodeError as error:
        raise ToolValidationError("工具参数不是合法 JSON") from error
    if not isinstance(arguments, dict):
        raise ToolValidationError("工具参数必须是 JSON 对象")

    if request.name == "add":
        allowed = {"a", "b"}
        if set(arguments) != allowed:
            raise ToolValidationError("add 必须且只能包含 a、b 两个参数")
        result = add(_require_exact_int(arguments, "a"), _require_exact_int(arguments, "b"))
        return {"ok": True, "tool": "add", "result": result}

    allowed = {"company_id", "year", "month"}
    if set(arguments) != allowed or not isinstance(arguments["company_id"], str):
        raise ToolValidationError("invoice_total 必须包含 company_id、year、month，且企业编号必须是文本")
    year, month = _require_exact_int(arguments, "year"), _require_exact_int(arguments, "month")
    try:
        connection = open_readonly_database(db_path)
        try:
            # current_user 来自 CLI 可信上下文，绝不读取模型传入的 user_id。
            result = invoice_total(connection, current_user, arguments["company_id"], year, month)
        finally:
            connection.close()
    except QueryError as error:
        if "查询被拒绝" in str(error):
            raise PermissionDenied(str(error)) from error
        raise ToolValidationError(str(error)) from error
    return {"ok": True, "tool": "invoice_total", "company_id": arguments["company_id"], "year": year, "month": month, "amount": result}


def make_tool_result_message(request: ToolRequest, result: dict[str, Any]) -> dict[str, str]:
    """把程序真实执行结果封装为 Chat Completions 的 tool 消息。"""
    return {"role": "tool", "tool_call_id": request.call_id, "content": json.dumps(result, ensure_ascii=False)}


def mock_reply(case: str, after_tool: bool = False) -> ModelReply:
    """显式预构造响应，仅用于演示 Harness；不是模型决策。"""
    if after_tool:
        return ModelReply("MOCK 最终回答：已收到 Python 工具的真实结果。")
    if case == "add":
        return ModelReply(tool_calls=[ToolRequest("mock_add_1", "add", '{"a": 12, "b": 35}')])
    return ModelReply(tool_calls=[ToolRequest("mock_invoice_1", "invoice_total", '{"company_id": "C001", "year": 2026, "month": 9}')])


def live_reply(messages: list[dict[str, Any]]) -> ModelReply:
    """调用 OpenAI-compatible Chat Completions；缺配置或 API 失败会明确报错。"""
    api_key, base_url, model = (os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_BASE_URL"), os.getenv("OPENAI_MODEL"))
    if not all((api_key, base_url, model)):
        raise RuntimeError("live 模式需要 OPENAI_API_KEY、OPENAI_BASE_URL、OPENAI_MODEL 三个环境变量")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        message = client.chat.completions.create(model=model, messages=messages, tools=TOOLS, tool_choice="auto").choices[0].message
    except Exception as error:
        raise RuntimeError(f"LLM API 请求失败或服务商不支持 Chat Completions Tool Calling：{error}") from error
    calls = [ToolRequest(call.id, call.function.name, call.function.arguments) for call in (message.tool_calls or [])]
    return ModelReply(message.content, calls)


def run_demo(mode: str, case: str, user_text: str, current_user: str, db_path: str | Path, emit=print) -> str:
    """最小循环：模型请求 -> Harness 校验执行 -> 工具结果回传 -> 模型回答。"""
    if mode not in {"mock", "live"}:
        raise ValueError("mode 只能是 mock 或 live")
    if mode == "mock":
        emit("=== MOCK / 模拟模型响应：不调用真实 LLM API ===")
    emit(f"[1] 用户输入：{user_text}")
    emit("[2] 工具定义摘要：add(a:int,b:int)；invoice_total(company_id:str,year:int,month:int)")
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_text}]
    from app.agent import Agent, live_model
    def model(history, tools):
        if mode == "live":
            return live_model(history, tools)
        reply = mock_reply(case, after_tool=history[-1]["role"] == "tool")
        return {"role": "assistant", "content": json.dumps({"kind":"information", "text":reply.content}, ensure_ascii=False) if reply.content else None,
                "tool_calls": [{"id": c.call_id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in (reply.tool_calls or [])]}
    agent = Agent(current_user, db_path, model, mode, max_tools=3, teaching=True)
    final = agent.ask(user_text)
    for message in agent.messages:
        if message["role"] == "tool":
            emit("[6] 工具实际结果：" + message["content"])
    emit("[7] LLM 最终回答：" + final)
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description="最小 Tool Calling 教学 Demo")
    parser.add_argument("--mode", choices=("mock", "live"), required=True)
    parser.add_argument("--case", choices=("add", "finance"), required=True)
    parser.add_argument("--user", default="U001", help="教学中的可信当前身份，不是生产登录认证")
    parser.add_argument("--db", type=Path, default=PROJECT_ROOT / "data" / "finance.db")
    parser.add_argument("--prompt", help="覆盖示例用户输入")
    args = parser.parse_args()
    default_prompt = "帮我计算 12 加 35" if args.case == "add" else "查询甲企业 2026 年 9 月的发票总额"
    run_demo(args.mode, args.case, args.prompt or default_prompt, args.user, args.db)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, PermissionError, RuntimeError) as error:
        print(f"错误：{error}", file=sys.stderr)
        raise SystemExit(2)
