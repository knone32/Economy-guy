"""财税 Agent 主页与兼容的 argparse 子命令。"""
import argparse
import json
import sqlite3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
DEFAULT_EXCEL = ROOT.parent / "赛题二：财税Harness初赛材料包-v1.1.0 2" / "02_示例数据.xlsx"
DEFAULT_DB = ROOT / "data" / "finance.db"


def check_runtime(version=None, discover=None, *, dependencies=("openpyxl", "openai")):
    from importlib.util import find_spec
    if (version if version is not None else sys.version_info) < (3, 11):
        print("需要 Python 3.11 或更新版本。Windows 可用 py -3.11 main.py 启动。", file=sys.stderr)
        return False
    discover = discover or find_spec
    missing = [name for name in dependencies if discover(name) is None]
    if missing:
        print("缺少依赖 " + "、".join(missing)
              + "。请在 finance_agent 目录执行 python -m pip install -r requirements.txt。",
              file=sys.stderr)
        return False
    return True


def launch_tui(args):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("全屏工作台需要交互终端。请在 Windows Terminal / PowerShell 运行 python main.py，"
              "或使用 python main.py home 和原有参数子命令。", file=sys.stderr)
        raise SystemExit(2)
    from app.tui import AgentWorkspace
    log = ROOT / "data" / "logs" / "tui_trace.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    application = AgentWorkspace(args.db, args.profiles_file, args.profiles_local, trace_path=log)
    if application.run() == "legacy_home":
        from app.cli_home import Home
        home = Home(application.db, args.profiles_file, args.profiles_local, DEFAULT_EXCEL)
        if application.user:
            home.switch_user(application.user)
        home.run()


def main() -> None:
    if not check_runtime(dependencies=()):
        raise SystemExit(2)
    parser = argparse.ArgumentParser(description="财税 Agent Harness（无子命令时打开全屏工作台）")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite 数据库路径")
    from app.model_config import DEFAULT_TEMPLATE,DEFAULT_LOCAL
    parser.add_argument('--profiles-file',type=Path,default=DEFAULT_TEMPLATE,help='无密钥TOML模板')
    parser.add_argument('--profiles-local',type=Path,default=DEFAULT_LOCAL,help='本地新增Profile JSON；不提交Git')
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("tui", help="全屏 Agent 工作台")
    sub.add_parser("home", help="原数字菜单与管理入口")
    profiles=sub.add_parser('profiles',help='可信本地模型配置；不调用模型API')
    profiles.add_argument('action',choices=('list','check','add'))
    profiles.add_argument('--user',help='可信模拟业务身份，不是生产认证')
    profiles.add_argument('--profile')
    profiles.add_argument('--name')
    profiles.add_argument('--scope',choices=('global','user'))
    profiles.add_argument('--simulate-profile-manager',action='store_true',help='显式模拟独立profile.manage，不自动授予U001')
    for key in ('provider','service-account-ref','model','base-url','api-key-env'):
        profiles.add_argument('--'+key)
    profiles.add_argument('--protocol',choices=('auto','standard','deepseek-thinking'),default='auto')
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
    chat.add_argument('--profile',help='只选择当前模拟用户可见的完整Profile')
    chat.add_argument("--mode", choices=("live", "mock"), default="live")
    chat.add_argument("--trace", type=Path, default=ROOT / "agent_trace.jsonl")
    chat.add_argument("--max-context-chars",type=int,default=48000,help="序列化消息字符上限；不含工具Schema，不是token估算")
    chat.add_argument("--block-requests",type=int,default=3,help="模型请求块长，默认3")
    chat.add_argument("--max-requests",type=int,default=9,help="每条消息模型硬限，至多9")
    chat.add_argument("--max-tools",type=int,default=12,help="实际进入Handler的工具硬限，至多12")
    chat.add_argument("--max-extensions",type=int,default=2,help="至多两次证据驱动续期")
    chat.add_argument("--max-replans",type=int,default=1,help="至多一次显式重规划")
    args = parser.parse_args()
    dependencies = ()
    if args.command in {None, "tui"}:
        dependencies = ("openpyxl", "openai", "textual")
    elif args.command == "home":
        dependencies = ("openpyxl", "openai")
    elif args.command == "init":
        dependencies = ("openpyxl",)
    elif args.command == "chat" and args.mode == "live":
        dependencies = ("openai",)
    if dependencies and not check_runtime(dependencies=dependencies):
        raise SystemExit(2)
    if args.command in {None, "tui"}:
        launch_tui(args)
        return
    if args.command == "home":
        from app.cli_home import Home
        Home(args.db, args.profiles_file, args.profiles_local, DEFAULT_EXCEL).run()
        return
    if args.command=='profiles':
        from app.model_config import add_profile,visible_profiles,resolve_connection,ProfileError
        options={'template':args.profiles_file,'local':args.profiles_local}
        if args.action=='add':
            data={'profile_name':args.name,'scope':args.scope,'owner_user_id':args.user if args.scope=='user' else None,
                'provider':args.provider,'service_account_ref':args.service_account_ref,'model':args.model,
                'base_url':args.base_url,'api_key_env':args.api_key_env,'protocol':args.protocol}
            output=add_profile(data,args.user,args.simulate_profile_manager,**options)
        elif not args.user:
            raise ProfileError('list/check需要可信模拟--user')
        elif args.action=='list':
            output=visible_profiles(args.user,**options)
        else:
            if not args.profile: raise ProfileError('check需要--profile，默认不发API请求')
            output={'status':'VALID_LOCAL_ONLY','connection':resolve_connection(args.user,args.profile,**options).metadata(),'api_requests':0}
        print(json.dumps(output,ensure_ascii=False,indent=2))
        return
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
        from app.rules import RuleError, import_rules, disable_rule, find_rules, SEED_RULES
        if not args.simulate_rule_manager:
            raise PermissionError("缺少独立 rule.manage 权限")
        capabilities = {"rule.manage"}
        actor = "simulated_rule_manager"
        try:
            if args.action == "find":
                outcome = find_rules(args.db, capabilities)
            elif args.action == "disable":
                if not args.rule_id or not args.version:
                    parser.error("disable需要--rule-id和--version")
                outcome = disable_rule(args.db, args.rule_id, args.version, capabilities, actor=actor)
            else:
                rules = SEED_RULES
                if args.action == "import":
                    if not args.file:
                        parser.error("import需要--file（JSON规则列表）")
                    rules = json.loads(args.file.read_text(encoding="utf-8"))
                    if type(rules) is not list:
                        raise RuleError("导入文件必须是JSON规则列表")
                outcome = import_rules(args.db, rules, capabilities, actor=actor, operation=args.action)
        except sqlite3.Error:
            raise RuleError("规则管理数据库操作失败，未确认变更") from None
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
        return
    if args.command == "inspect-update":
        from app.updates import inspect_request
        print(json.dumps(inspect_request(args.db, args.user, args.request_id), ensure_ascii=False, indent=2))
        return
    if args.command == "chat":
        from app.cli_chat import run_chat
        run_chat(args)
        return
    if args.command == "init":
        from app.importer import initialize_database
        print(json.dumps(initialize_database(args.excel, args.db), ensure_ascii=False))
        return
    if args.command == "test":
        import unittest
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests")); result = unittest.TextTestRunner(verbosity=2).run(suite); raise SystemExit(not result.wasSuccessful())
    from app.database import connect
    from app.finance import bank_expense_total, bank_income_total, invoice_total
    from app.queries import list_bank_transactions, list_invoices
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
