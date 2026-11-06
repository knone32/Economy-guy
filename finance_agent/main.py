"""Stage 0–3C 命令行入口与可信模拟管理交互。"""
import argparse
import json
from pathlib import Path
import sys
from dataclasses import asdict
from app.database import connect
from app.finance import bank_expense_total, bank_income_total, invoice_total
from app.importer import initialize_database
from app.queries import list_bank_transactions, list_invoices

ROOT = Path(__file__).resolve().parent
DEFAULT_EXCEL = ROOT.parent / "赛题二：财税Harness初赛材料包-v1.1.0 2" / "02_示例数据.xlsx"
DEFAULT_DB = ROOT / "data" / "finance.db"


def main() -> None:
    parser = argparse.ArgumentParser(description="财税 Agent Harness Stage 0–3C")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite 数据库路径")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="安全首次导入，拒绝覆盖已有数据库"); init.add_argument("--excel", type=Path, default=DEFAULT_EXCEL)
    for name in ("invoices", "bank", "summary"):
        command = sub.add_parser(name); command.add_argument("--user", required=True); command.add_argument("--company", required=True); command.add_argument("--year", type=int, required=True); command.add_argument("--month", type=int, required=True)
    sub.add_parser("test", help="运行自动化测试")
    sub.add_parser("migrate-stage2", help="只新增规则与审计表，不重导业务数据")
    sub.add_parser("migrate-stage3", help="只新增持久任务/偏好表及未完成任务索引")
    sub.add_parser("migrate-stage3b", help="只新增展示引用锚点，不恢复写入确认")
    tasks_cli = sub.add_parser("tasks", help="可信模拟用户管理自己的持久待办")
    tasks_cli.add_argument("action",choices=("list","create","show","update","correct","wait","pause","resume","complete","cancel"))
    tasks_cli.add_argument("--user",required=True)
    tasks_cli.add_argument("--company",required=True)
    tasks_cli.add_argument("--task-id",default="")
    tasks_cli.add_argument("--year",type=int,default=2026)
    tasks_cli.add_argument("--month",type=int,default=9)
    tasks_cli.add_argument("--note",default="")
    prefs_cli = sub.add_parser("preferences", help="可信模拟用户明确保存、查询、更改或删除偏好")
    prefs_cli.add_argument("action",choices=("create","get","list","update","delete"))
    prefs_cli.add_argument("--user",required=True)
    prefs_cli.add_argument("--company",required=True)
    prefs_cli.add_argument("--key",default="")
    prefs_cli.add_argument("--value",default="")
    rules_cli = sub.add_parser("rules", help="独立模拟rule.manage管理入口")
    rules_cli.add_argument("action", choices=("seed", "find", "import", "disable"))
    rules_cli.add_argument("--simulate-rule-manager", action="store_true", help="显式模拟独立rule.manage授权，非生产认证")
    rules_cli.add_argument("--file", type=Path)
    rules_cli.add_argument("--rule-id")
    rules_cli.add_argument("--version")
    audit_cli = sub.add_parser("inspect-update", help="重启或未知提交后核查审计和当前值")
    audit_cli.add_argument("--user", required=True)
    audit_cli.add_argument("--request-id", required=True)
    chat = sub.add_parser("chat", help="单Agent连续会话与受控管理")
    chat.add_argument("--user", required=True, help="模拟身份，不是生产认证")
    chat.add_argument("--mode", choices=("live", "mock"), default="live")
    chat.add_argument("--trace", type=Path, default=ROOT / "agent_trace.jsonl")
    chat.add_argument("--max-context-chars",type=int,default=48000,help="序列化消息字符上限；不含工具Schema，不是token估算")
    chat.add_argument("--block-requests",type=int,default=3,help="模型请求块长，默认3")
    chat.add_argument("--max-requests",type=int,default=9,help="每条消息模型硬限，至多9")
    chat.add_argument("--max-tools",type=int,default=12,help="实际进入Handler的工具硬限，至多12")
    chat.add_argument("--max-extensions",type=int,default=2,help="至多两次证据驱动续期")
    chat.add_argument("--max-replans",type=int,default=1,help="至多一次显式重规划")
    args = parser.parse_args()
    if args.command == "migrate-stage3b":
        from app.references import migrate
        migrate(args.db)
        print("Stage 3B加法迁移完成，仅新增引用锚点。")
        return
    if args.command == "migrate-stage3":
        from app.stage3_schema import migrate
        migrate(args.db)
        print("Stage 3A加法迁移完成，现有发票、银行、规则和审计保留。")
        return
    if args.command in {"tasks","preferences"}:
        from app.persistence import ManagementIntent
        from app.tasks import list_tasks, manage_task
        from app.preferences import manage_preference
        if args.command == "tasks":
            intent = ManagementIntent(args.user,"task","可信CLI明确任务操作：" + args.action + " " + args.note,args.action)
            outcome = list_tasks(args.db,args.user,args.company) if args.action == "list" else manage_task(
                args.db,args.user,args.company,args.action,args.task_id,args.year,args.month,args.note,intent)
        else:
            intent = ManagementIntent(args.user,"preference","可信CLI明确偏好操作：" + args.action + " " + args.key,args.action)
            outcome = manage_preference(args.db,args.user,args.company,args.action,args.key,args.value,intent)
        print(json.dumps(outcome,ensure_ascii=False,indent=2))
        return
    if args.command == "migrate-stage2":
        from app.stage2_schema import migrate
        migrate(args.db)
        print("Stage 2加法迁移完成，原发票和银行数据保留。请使用rules seed导入规则。")
        return
    if args.command == "rules":
        from app.rules import import_rules, disable_rule, find_rules, SEED_RULES
        capabilities = {"rule.manage"} if args.simulate_rule_manager else set()
        if args.action == "seed":
            import_rules(args.db, SEED_RULES, capabilities)
        elif args.action == "import":
            if not args.file:
                parser.error("import需要--file（JSON规则列表）")
            import_rules(args.db, json.loads(args.file.read_text(encoding="utf-8")), capabilities)
        elif args.action == "disable":
            if not args.rule_id or not args.version:
                parser.error("disable需要--rule-id和--version")
            disable_rule(args.db, args.rule_id, args.version, capabilities)
        else:
            print(json.dumps(find_rules(args.db, capabilities), ensure_ascii=False, indent=2))
        return
    if args.command == "inspect-update":
        from app.updates import inspect_request
        print(json.dumps(inspect_request(args.db, args.user, args.request_id), ensure_ascii=False, indent=2))
        return
    if args.command == "chat":
        from app.agent import Agent, live_model
        model = live_model
        if args.mode == "mock":
            print("MOCK / 固定模拟响应：每轮查询 C001 2026-09，不代表自然语言理解")
            def model(messages, tools):
                if messages[-1]["role"] == "tool":
                    return {"role": "assistant", "content": json.dumps({"kind":"information", "text":"MOCK 结果：" + messages[-1]["content"]}, ensure_ascii=False)}
                return {"role": "assistant", "tool_calls": [{"id": "mock_query", "type": "function", "function": {"name": "get_finance_summary", "arguments": '{"company_id":"C001","year":2026,"month":9}'}}]}
        def confirm_long_term(proposal):
            """可信交互只确认本次展示的对象与内容，不让模型提供确认。"""
            print('长期状态待确认（尚未保存）：')
            print(json.dumps(proposal,ensure_ascii=False,indent=2))
            try:
                return input('核对原始要求及实际对象/内容，输入 confirm '+proposal['request_id']+' 才保存；其他输入取消：')=='confirm '+proposal['request_id']
            except (EOFError,KeyboardInterrupt):
                return False
        agent = Agent(args.user, args.db, model, args.mode, args.trace,max_context_chars=args.max_context_chars,
                      block_requests=args.block_requests,max_requests=args.max_requests,max_tools=args.max_tools,
                      max_extensions=args.max_extensions,max_replans=args.max_replans,management_confirmation=confirm_long_term)
        print("财税Agent（模拟身份）：普通自然语言可提出待办/偏好候选，核对具体内容并确认才保存；/task、/preference兼容。/edit准备发票草稿，仍须最终确认。exit退出。")
        while True:
            try:
                text = input("你：")
            except (EOFError, KeyboardInterrupt):
                break
            if text.strip().lower() == "exit":
                break
            if text.strip():
                if text.strip() == "/cancel":
                    print(json.dumps(agent.cancel_update(), ensure_ascii=False, indent=2))
                    continue
                allow_prepare = text.startswith("/edit ")
                request = text[6:] if allow_prepare else text
                management = None
                management_action = None
                if text.startswith("/task "):
                    management,request = "task",text[6:]
                elif text.startswith("/preference "):
                    management,request = "preference",text[12:]
                if management:
                    management_action,separator,request = request.partition(" ")
                    actions = {"create","show","update","correct","wait","pause","resume","complete","cancel","list","get","delete"}
                    if management_action not in actions or not separator or not request.strip():
                        print("请用明确管理动作和要求，例如 /task create 保存C001九月用途后续待办。未执行写入。")
                        continue
                continue_edit = False
                if agent.pending_edit and not allow_prepare:
                    print("尚有待补充修改意图：" + agent.pending_edit["inputs"][0])
                    try:
                        continue_edit = input("本条是补充该修改？输入 continue 关联；其他输入按新主题处理：") == "continue"
                    except (EOFError, KeyboardInterrupt):
                        continue_edit = False
                print("答复（一般说明会标明未核实；查询另附实际范围）：" + agent.ask(request, allow_prepare=allow_prepare, continue_edit=continue_edit,management=management,management_action=management_action))
                print("Harness发票写入回执：" + json.dumps(agent.write_receipt, ensure_ascii=False))
                for request_id, draft in list(agent.update_session.drafts.items()):
                    print("本轮原始要求：" + draft.source_request)
                    print(json.dumps(asdict(draft), ensure_ascii=False, indent=2))
                    print("请核对企业/发票/字段/旧值/新值。输入完整 confirm " + request_id + " 才提交，其余输入取消。")
                    try:
                        confirmation = input("最终确认：")
                    except (EOFError, KeyboardInterrupt):
                        confirmation = ""
                    if confirmation != "confirm " + request_id:
                        print(json.dumps(agent.cancel_update(), ensure_ascii=False, indent=2))
                        continue
                    outcome = agent.commit_update(request_id, draft.fingerprint())
                    print(json.dumps(outcome, ensure_ascii=False, indent=2))
        return
    if args.command == "init": print(json.dumps(initialize_database(args.excel, args.db), ensure_ascii=False)); return
    if args.command == "test":
        import unittest
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests")); result = unittest.TextTestRunner(verbosity=2).run(suite); raise SystemExit(not result.wasSuccessful())
    connection = connect(args.db)
    try:
        if args.command == "invoices": result = list_invoices(connection, args.user, args.company, args.year, args.month)
        elif args.command == "bank": result = list_bank_transactions(connection, args.user, args.company, args.year, args.month)
        else: result = {"invoice_total": invoice_total(connection, args.user, args.company, args.year, args.month), "bank_income_total": bank_income_total(connection, args.user, args.company, args.year, args.month), "bank_expense_total": bank_expense_total(connection, args.user, args.company, args.year, args.month)}
    finally:
        connection.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try: main()
    except (ValueError, FileNotFoundError, FileExistsError, PermissionError) as error:
        print(f"错误：{error}", file=sys.stderr); raise SystemExit(2)
