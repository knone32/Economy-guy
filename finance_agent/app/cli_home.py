"""Guided terminal workflows. This module owns only the local UI session."""
import argparse
from collections import deque
from contextlib import closing
from dataclasses import asdict
from datetime import date
from getpass import getpass, GetPassWarning
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import warnings

from .cli_chat import run_chat, safe_text
from .cli_workspaces import (
    company_access, import_workspace, invoice_history, missing_migrations, rule_history,
    upgrade_workspace, workspace_users,
)
from .model_config import add_profile, load_profiles, ProfileError, resolve_connection, validate_profile, visible_profiles
from .preferences import manage_preference
from .rules import RuleError, disable_rule, find_rules, import_rules, resolve_rule
from .stage2_schema import open_existing
from .tasks import list_tasks
from .trace import redact


ROOT = Path(__file__).resolve().parents[1]
IDENTITY = "SIMULATED_IDENTITY / 比赛模拟身份"
ADMIN = "SIMULATED_ADMIN / 仅用于本地比赛演示，并非真实管理员认证"
ACL_LATER = "新增或禁用模拟用户、修改 ACL 留待 S4-UX-B。请联系本地管理员核对权限。"
API_ADVICE = {
    "HTTP_ERROR": "请核对凭据、模型权限和账户额度，再手动重试。",
    "TIMEOUT": "请求超时。请检查网络后手动重试。",
    "CONNECTION_ERROR": "连接失败。请检查网络、代理和端点。",
    "SDK_OR_RESPONSE_ERROR": "响应无法处理。请核对模型和协议配置。",
}


class Cancelled(Exception):
    pass


class HomeJump(Exception):
    pass


class ExitHome(Exception):
    pass


def display(value):
    cleaned = redact(value)
    text = cleaned if isinstance(cleaned, str) else json.dumps(cleaned, ensure_ascii=False, indent=2)
    return safe_text(text) if isinstance(cleaned, str) else text


def show_rows(rows):
    if not rows:
        print("暂无记录")
    for row in rows:
        print(display(row))


class Home:
    def __init__(self, db, template, local, default_excel, managed=None):
        self.db = Path(db).absolute()
        self.options = {"template": template, "local": local}
        self.default_excel = default_excel
        self.managed = Path(managed) if managed is not None else ROOT / "data" / "workspaces"
        self.user = None
        self.profile = None  # None follows the configured default.
        self.mode = "mock"
        self.recent = deque(maxlen=10)
        self.connection_status = "本次尚未发起联网请求。"
        try:
            self.switch_db(self.db)
        except (OSError, ValueError, sqlite3.Error):
            pass  # The home still opens so the user can choose or import a database.

    def reset_session(self):
        self.recent.clear()
        self.connection_status = "本次尚未发起联网请求。"

    def switch_db(self, path):
        path = Path(path).resolve()
        users = {row["user_id"] for row in workspace_users(path)}
        user = self.user if self.user in users else "U001" if "U001" in users else None
        if (self.db, self.user) != (path, user):
            self.reset_session()
        if self.user != user:
            self.profile = None
        self.db, self.user = path, user

    def switch_user(self, user):
        if user not in {row["user_id"] for row in workspace_users(self.db)}:
            raise ValueError("用户已不可用。请重新打开用户列表。")
        if user != self.user:
            self.user, self.profile = user, None
            self.reset_session()

    def require_user(self):
        if not self.user or self.user not in {row["user_id"] for row in workspace_users(self.db)}:
            raise ValueError("请先在「用户与权限」选择当前工作库的模拟用户。")
        return self.user

    def configured_name(self, default):
        return self.profile or os.environ.get("FINANCE_MODEL_PROFILE") or default

    def config(self):
        _, default = load_profiles(**self.options)
        name = self.configured_name(default)
        try:
            profile = resolve_connection(self.user, name, require_key=False, **self.options).profile if name else None
        except ProfileError as error:
            selected = f" {self.profile}" if self.profile else ""
            raise ProfileError(f"当前 Profile{selected} 不存在或对该用户不可见。请在「Profile 设置」选择可见项。") from error
        return name, profile

    def status(self):
        user = self.user or "未选择"
        print(f"{IDENTITY} · {display(user)} · {self.mode.upper()}")
        try:
            workspace_users(self.db)
            companies = company_access(self.db, self.user) if self.user else []
            access = "、".join(display(row["company_id"]) for row in companies) or "无"
            print(f"工作库 {display(str(self.db))} · 可访问企业 {access}")
            if missing_migrations(self.db):
                print("工作库为旧结构。完整对话、任务与审计可在「Excel 导入与工作库」执行加法升级后使用。")
        except (ValueError, OSError, sqlite3.Error):
            print(f"工作库 {display(str(self.db))} · 不可用，请选择已有库或导入 Excel。")
        try:
            name, profile = self.config()
            if profile:
                key_ready = bool(os.environ.get(profile.api_key_env, "").strip())
                print(f"Profile {name} · 存在 是 · Key 就绪 {'是' if key_ready else '否'}"
                      f" · Provider {profile.provider} · 模型 {display(profile.model)}")
            else:
                print("Profile 未选择 · 存在 否 · Key 就绪 否 · Provider / 模型未配置")
        except ProfileError as error:
            print(f"Profile 不可用 · 存在或可见性未通过 · Key 就绪 否 · {display(str(error))}")

    def prompt(self, label):
        try:
            value = input(label).strip()
        except EOFError:
            raise ExitHome from None
        except KeyboardInterrupt:
            raise Cancelled from None
        match value.lower():
            case "/home":
                raise HomeJump
            case "/quit":
                raise ExitHome
            case "/cancel":
                raise Cancelled
        return value

    def menu(self, title, description, options):
        while True:
            print(f"\n━━ {title} ━━")
            self.status()
            print(description)
            for number, (label, _) in enumerate(options, 1):
                print(f"  {number}. {label}")
            print("  0. 返回上一级" if title != "财税 Agent 主页" else "  0. 安全退出")
            try:
                value = self.prompt("请选择数字（/home 主页，/cancel 取消，/quit 退出）：")
            except Cancelled:
                return
            if value == "0":
                return
            if value not in {str(i) for i in range(1, len(options) + 1)}:
                print("输入无效。请输入菜单中的数字。")
                continue
            try:
                options[int(value) - 1][1]()
            except (Cancelled, KeyboardInterrupt):
                print("操作已取消。")
            except ProfileError as error:
                print(display(str(error)) + "。请在「Profile 设置」核对配置。")
            except RuleError as error:
                print(display(str(error)) + "。请核对规则版本、企业范围和生效日期。")
            except (ValueError, PermissionError, FileExistsError) as error:
                print(display(str(error)))
            except sqlite3.Error:
                print("工作库无法读取或保存。请在「工作库」核对路径、库版本或文件权限。")
            except OSError:
                print("文件操作未完成。请核对路径、目录写入权限及工作库所在磁盘。")

    def pick(self, title, description, rows):
        """Select a listed value without accepting an arbitrary identifier."""
        chosen = []
        options = [(display(label), lambda value=value: chosen.append(value)) for label, value in rows]
        if not options:
            print("暂无可选项。请先完成相关配置或选择可访问的工作库。")
            raise Cancelled
        print(f"\n━━ {title} ━━")
        self.status()
        print(description)
        for number, (label, _) in enumerate(options, 1):
            print(f"  {number}. {label}")
        while not chosen:
            value = self.prompt("请选择数字（0 返回，/home 主页）：")
            if value == "0":
                raise Cancelled
            if value in {str(i) for i in range(1, len(options) + 1)}:
                options[int(value) - 1][1]()
            else:
                print("输入无效。请输入列表中的数字。")
        return chosen[0]

    def confirm(self, command, guidance):
        if self.prompt(f"{guidance} 输入 {command} 确认，其他输入取消：") != command:
            raise Cancelled

    def run(self):
        while True:
            try:
                self.menu("财税 Agent 主页", "首次使用可先设置工作库和模拟身份，再进入 Agent 或查看规则。",
                          [("Agent 智能对话", self.agent_menu), ("用户与权限", self.users_menu),
                           ("历史记录与审计", self.history_menu), ("Excel 导入与工作库", self.workspaces_menu),
                           ("Profile 设置", self.profiles_menu), ("高级管理员控制台", self.admin_entry),
                           ("交互演示", self.demo), ("查看当前企业适用规则", self.business_rule)])
                break
            except HomeJump:
                continue
            except (ExitHome, KeyboardInterrupt):
                break
        print("已退出财税 Agent。")

    def agent_menu(self):
        self.menu("Agent 智能对话", "进入对话后输入自然语言。先确认当前身份、工作库和模式。",
                  [("选择模拟用户", self.choose_user), ("选择 Profile", self.choose_profile),
                   ("选择 Live / Mock", self.choose_mode), ("开始多轮对话", self.chat)])

    def users_menu(self):
        self.menu("用户与权限", IDENTITY + "。身份和企业权限来自当前工作库。",
                  [("查看并选择模拟用户", self.choose_user), ("查看当前用户的企业权限", self.show_access),
                   ("查看当前用户任务", self.tasks), ("查看当前用户偏好", self.preferences),
                   ("用户与 ACL 管理说明", lambda: print(ACL_LATER))])

    def choose_user(self):
        users = workspace_users(self.db)
        user = self.pick("选择模拟用户", IDENTITY,
                         [(f"{u['user_id']} · {u['name']}", u["user_id"]) for u in users])
        self.switch_user(user)
        print("当前模拟用户 " + display(user))

    def show_access(self):
        companies = company_access(self.db, self.require_user())
        show_rows([f"{c['company_id']} {c['name']} · 读取 {'允许' if c['read'] else '拒绝'}"
                   f" · 修改 {'允许' if c['modify'] else '拒绝'}" for c in companies])

    def choose_company(self):
        companies = company_access(self.db, self.require_user())
        return self.pick("选择企业", "只列出当前模拟用户有读取权限的企业。",
                         [(f"{row['company_id']} · {row['name']}", row["company_id"])
                          for row in companies if row["read"]])


    def history_menu(self):
        self.menu("历史记录与审计", "此处为只读视图。发票审计仅显示当前用户本人且仍有企业读取权限的成功操作。",
                  [("当前会话最近交互", lambda: show_rows(self.recent)),
                   ("已保存的历史会话摘要", self.saved_history),
                   ("发票成功修改审计", lambda: show_rows(invoice_history(self.db, self.require_user()))),
                   ("规则成功变更审计", lambda: self.admin_entry(audit_only=True)),
                   ("持久任务列表与状态", self.tasks), ("偏好记录", self.preferences)])

    def saved_history(self):
        print("暂无记录。现有 Trace 是执行日志。持久会话摘要与检索留待 S4-UX-B。")

    def tasks(self):
        outcome = list_tasks(self.db, self.require_user(), self.choose_company())
        self.show_business_rows(outcome)

    def preferences(self):
        outcome = manage_preference(self.db, self.require_user(), self.choose_company(), "list")
        self.show_business_rows(outcome)

    @staticmethod
    def show_business_rows(outcome):
        if outcome["status"] in {"SUCCESS", "NO_DATA"}:
            show_rows(outcome["data"])
        else:
            print(display(outcome["status"]) + "。请重新选择有权限的企业，或核对工作库。")

    def workspaces_menu(self):
        self.menu("Excel 导入与工作库", "只支持官方或兼容结构 .xlsx。新库完成校验、迁移和规则初始化后才发布。",
                  [("导入 Excel 到新工作库", self.import_excel),
                   ("选择受管理的工作库", self.select_managed),
                   ("输入已有工作库路径", self.select_existing),
                   ("加法升级当前旧库结构", self.upgrade_existing)])

    def path(self, prompt, default=None):
        value = self.prompt(prompt).strip('"')
        if not value and default is None:
            raise Cancelled
        return Path(value or default).expanduser().absolute()

    def import_excel(self):
        if self.default_excel.is_file():
            print("Excel 路径留空可使用本地官方示例。")
        excel = self.path("Excel 文件路径：", self.default_excel)
        default = self.managed / (excel.stem + ".db")
        target = self.path(f"新库路径（留空为 {display(str(default))}）：", default)
        if target.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
            raise ValueError("请选择 .db、.sqlite 或 .sqlite3 工作库路径。")
        print(f"源文件 {display(str(excel))}\n新工作库 {display(str(target))}")
        self.confirm("import", "确认校验并导入到新路径。")
        counts = import_workspace(excel, target)
        print("导入及核对通过，迁移与规则初始化完成。")
        print(f"企业 {counts['companies']} · 用户 {counts['users']} · 发票 {counts['invoices']}"
              f" · 银行流水 {counts['bank_transactions']}")
        if self.prompt("输入 switch 切换到新工作库，直接回车保留当前库：") == "switch":
            self.switch_db(target)
            print("已切换工作库。请核对当前模拟用户。")

    def select_managed(self):
        files = sorted(p for p in self.managed.glob("*")
                       if p.suffix.lower() in {".db", ".sqlite", ".sqlite3"} and p.is_file())
        path = self.pick("受管理的工作库", f"列出 {display(str(self.managed))} 中的工作库。",
                         [(p.name, p) for p in files])
        self.switch_db(path)
        print("已切换工作库。")

    def select_existing(self):
        self.switch_db(self.path("已有工作库路径："))
        print("已切换工作库。")

    def upgrade_existing(self):
        workspace_users(self.db)
        missing = missing_migrations(self.db)
        if not missing:
            print("工作库结构已齐全。")
            return
        print("工作库 " + display(str(self.db)))
        print("待补齐表 " + "、".join(sorted(missing)))
        self.confirm("upgrade", "确认按现有迁移新增表和索引，保留业务记录。")
        upgrade_workspace(self.db)
        print("加法升级完成。若尚无规则，请由模拟管理员导入。")

    def profiles_menu(self):
        self.menu("Profile 设置", "默认仅离线校验。Key 状态只显示是否就绪，联网结果来自实际 Live 对话。",
                  [("查看可见 Profile", self.show_profiles), ("查看当前配置与端点检查", self.check_profile),
                   ("新增 User Profile", lambda: self.new_profile("user")), ("选择当前会话 Profile", self.choose_profile),
                   ("使用环境或配置默认 Profile", self.use_default),
                   ("安全输入当前 Profile 的 Key", self.set_key),
                   ("查看实际连接状态", lambda: print(self.connection_status))])

    def profile_rows(self):
        return visible_profiles(self.user, **self.options)

    def show_profiles(self):
        for profile in self.profile_rows() or [None]:
            if profile is None:
                print("暂无可见 Profile。请新增 User Profile，或由模拟管理员添加 Global Profile。")
                return
            env = profile["api_key_env"]
            print(display({**profile, "key_ready": bool(os.environ.get(env, "").strip())}))

    def check_profile(self):
        name, profile = self.config()
        if profile is None:
            raise ProfileError("当前未配置 Profile。请先新增或选择可见 Profile")
        resolved = resolve_connection(self.user, name, require_key=False, **self.options)
        print(display(resolved.metadata()))
        print(f"端点 {display(profile.base_url)} · 本地模型/端点配置合法 · Key 就绪 "
              + ("是" if os.environ.get(profile.api_key_env, "").strip() else "否"))
        print("凭据环境变量名 " + profile.api_key_env)
        print(self.connection_status)

    def choose_profile(self):
        items = self.profile_rows()
        name = self.pick("选择当前会话 Profile", "选择对当前模拟用户可见的 Profile。",
                         [(f"{p['profile_name']} · {p['provider']} / {p['model']}", p["profile_name"]) for p in items])
        resolve_connection(self.user, name, require_key=False, **self.options)
        self.profile = name
        self.connection_status = "本次尚未发起联网请求。"
        print("已选择 " + name)

    def use_default(self):
        old = self.profile
        self.profile = None
        try:
            name, _ = self.config()
        except ProfileError:
            self.profile = old
            raise
        self.connection_status = "本次尚未发起联网请求。"
        print("当前使用默认项 " + (name or "未配置。请先新增或选择 Profile。"))

    def set_key(self):
        _, profile = self.config()
        if profile is None:
            raise ProfileError("请先选择 Profile")
        env = profile.api_key_env
        if os.environ.get(env):
            print("凭据环境变量已设置。请从启动终端管理现有值。")
            return
        if env != "API_KEY" and not env.endswith("_API_KEY"):
            raise ValueError("该凭据名称请从启动终端设置。界面只输入 API_KEY 或以 _API_KEY 结尾的变量。")
        if not sys.stdin.isatty():
            raise ValueError("当前终端不能安全读取 Key。请在交互终端设置该环境变量。")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", GetPassWarning)
                key = getpass(f"为 {env} 输入 Key（隐藏，仅本进程，回车取消）：").strip()
        except (GetPassWarning, EOFError, KeyboardInterrupt):
            raise Cancelled from None
        if not key:
            raise Cancelled
        os.environ[env] = key
        print("Key 就绪 是。联网状态请在 Live 对话中验证。")

    def new_profile(self, scope, *, simulate_manager=False):
        if scope == "global" and not simulate_manager:
            raise PermissionError("Global Profile 需要独立的模拟管理员入口。")
        owner = self.require_user() if scope == "user" else None
        print("Profile 只保存凭据环境变量名。可用 Provider 为 deepseek、openai、openai-compatible。")
        prompts = {"profile_name": "名称", "provider": "Provider", "service_account_ref": "服务账户逻辑名称（留空生成）",
                   "model": "模型名称", "base_url": "HTTPS 端点", "api_key_env": "凭据环境变量名"}
        fields = {key: self.prompt(label + "：") for key, label in prompts.items()}
        protocol = self.prompt("协议 auto / standard / deepseek-thinking（留空 auto）：") or "auto"
        profile = validate_profile(dict(**fields, scope=scope, owner_user_id=owner, protocol=protocol), new=True)
        profiles, _ = load_profiles(**self.options)
        if any(other.api_key_env == profile.api_key_env and other.base_url != profile.base_url
               for other in profiles.values()):
            raise ProfileError("不同端点请配置独立的凭据环境变量")
        print("即将保存以下本地配置")
        print(display(asdict(profile)))
        self.confirm("save", "核对 Profile、归属和端点。")
        add_profile(asdict(profile), owner, simulate_manager, **self.options)
        print("已添加 Profile。可在「Profile 设置」选择它。")

    def choose_mode(self):
        self.mode = self.pick("选择对话模式", "Live 仅在发送对话消息时调用模型。Mock 使用固定离线响应。",
                              [("Mock 固定模拟", "mock"), ("Live 真实模型", "live")])

    def chat(self):
        user = self.require_user()
        name = None
        if self.mode == "live":
            name, profile = self.config()
            if not profile:
                raise ProfileError("Live 需要可见的 Profile。请先新增或选择")
            if not os.environ.get(profile.api_key_env, "").strip():
                raise ProfileError(f"Live 的 Key 未设置。请设置 {profile.api_key_env}，或使用安全输入")
        if missing_migrations(self.db):
            raise ValueError("完整对话需要新版工作库。请在「Excel 导入与工作库」加法升级或选择新版库。")
        trace_dir = self.managed.parent / "logs"
        trace_dir.mkdir(parents=True, exist_ok=True)
        args = argparse.Namespace(user=user, db=self.db, profile=name, mode=self.mode,
                                  profiles_file=self.options["template"], profiles_local=self.options["local"],
                                  trace=trace_dir / "cli_home_trace.jsonl", max_context_chars=48000,
                                  block_requests=3, max_requests=9, max_tools=12, max_extensions=2, max_replans=1)
        self.recent.clear()
        destination = run_chat(args, home=self)
        if destination == "/home":
            raise HomeJump
        if destination == "/quit":
            raise ExitHome

    def remember(self, source, execution, tools, receipt):
        self.recent.append(dict(user_input=display(source)[:200], stop=execution.get("stop_reason"),
                                tools=tools, invoice_receipt=receipt))

    def observe_connection(self, event, data):
        if event != "api.response":
            return
        if data["success"]:
            self.connection_status = "本次 Live 已收到模型响应。"
        else:
            category = data["http_category"]
            status = data.get("http_status")
            self.connection_status = f"最近 Live 请求失败（{category}" + (f"，HTTP {status}" if status else "") + "）。"
            self.connection_status += API_ADVICE.get(category, "请核对 Profile 和网络。")
            print(self.connection_status)


    def business_rule(self):
        company = self.choose_company()
        kind = self.pick("规则类型", "查看指定业务日期实际适用的有效规则。",
                         [("金额统计", "amount"), ("发票用途", "purpose"), ("银行只读", "bank")])
        day = self.prompt(f"业务日期 YYYY-MM-DD（留空为 {date.today().isoformat()}）：") or date.today().isoformat()
        try:
            with closing(open_existing(self.db, readonly=True)) as db:
                decision = resolve_rule(db, self.require_user(), company, kind, day)
        except RuleError:
            raise
        except ValueError:
            raise ValueError("日期无效。请输入 YYYY-MM-DD，例如 2026-09-01。") from None
        print(display(asdict(decision)))

    def admin_entry(self, *, audit_only=False):
        print(f"\n━━ 本地模拟管理员入口 ━━\n{ADMIN}")
        self.status()
        self.confirm("admin", "进入独立的本地模拟管理员会话。")
        capabilities = frozenset({"rule.manage"})
        if audit_only:
            show_rows(rule_history(self.db, capabilities))
            return
        self.menu("高级管理员控制台", ADMIN + "。规则和 Global Profile 的变更均需单独确认。",
                  [("查询所有规则", lambda: show_rows(find_rules(self.db, capabilities))),
                   ("从 JSON 导入规则", lambda: self.import_rule_file(capabilities)),
                   ("停用规则", lambda: self.disable_existing_rule(capabilities)),
                   ("规则操作审计", lambda: show_rows(rule_history(self.db, capabilities))),
                   ("Global Profile 管理", self.global_profiles),
                   ("模拟用户与权限设置说明", lambda: print(ACL_LATER)),
                   ("当前数据库与系统信息", self.system_info)])

    def import_rule_file(self, capabilities):
        workspace_users(self.db)
        path = self.path("规则 JSON 路径：")
        try:
            rules = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError("文件不是有效的 UTF-8 JSON。请提供规则对象数组。") from None
        if not isinstance(rules, list) or not rules:
            raise ValueError("规则文件需要非空 JSON 规则列表。")
        print("工作库 " + display(str(self.db)))
        print(display(rules))
        self.confirm("import rules", "核对规则列表。成功变更将写入规则审计。")
        print(display(import_rules(self.db, rules, capabilities, actor="simulated_rule_manager")))

    def disable_existing_rule(self, capabilities):
        rules = find_rules(self.db, capabilities)
        row = self.pick("选择要停用的规则", "只列出启用版本。停用将影响后续规则判定。",
                        [(f"{r['rule_id']} v{r['version']} · {r['name']} · {r['company_scope']}", r)
                         for r in rules if r["status"] == "ACTIVE"])
        print("工作库 " + display(str(self.db)))
        print(display(row))
        self.confirm("disable", "确认将上述版本停用并记录审计。")
        print(display(disable_rule(self.db, row["rule_id"], row["version"], capabilities,
                                   actor="simulated_rule_manager")))

    def global_profiles(self):
        self.menu("Global Profile 管理", ADMIN + "。新增项对所有模拟用户可见。",
                  [("查看 Global Profile", lambda: show_rows(
                      [p for p in self.profile_rows() if p["scope"] == "global"])),
                   ("新增 Global Profile", lambda: self.new_profile("global", simulate_manager=True))])

    def system_info(self):
        self.status()
        print(f"Python {sys.version.split()[0]} · SQLite {sqlite3.sqlite_version}")

    def demo(self):
        mode = self.pick("交互演示模式", "交互演示使用独立虚构库，确认标记 SIMULATED_TEST_USER。",
                         [("Mock 固定离线演示", "mock"), ("Live 真实模型演示", "live")])
        scene = self.pick("交互演示场景", "Enter 或空格推进，Q 退出。",
                          [("全部场景", "all"), ("A 查询", "A"), ("B 发票修改", "B"), ("C 持久任务", "C")])
        argv = [sys.executable, str(ROOT / "scripts" / "demo_stepper.py"), "--mode", mode, "--scenario", scene]
        if mode == "live":
            profiles = [p for p in self.profile_rows() if p["scope"] == "global" or p["owner_user_id"] == "U001"]
            profiles = [p for p in profiles if (p["provider"], p["model"], p["base_url"])
                        == ("deepseek", "deepseek-flash", "https://api.deepseek.com")]
            name = self.pick("演示 Profile", "Live 演示以冻结身份 U001 使用 DeepSeek Flash。",
                             [(p["profile_name"], p["profile_name"]) for p in profiles])
            resolve_connection("U001", name, **self.options)
            self.confirm("live", "启动 Live 演示。逐步推进时将消耗实际 API 额度。")
            argv += ["--profile", name, "--profiles-file", str(self.options["template"]),
                     "--profiles-local", str(self.options["local"])]
        code = subprocess.run(argv, check=False).returncode
        if code not in (0, 2):
            print("演示未完整通过。请查看演示摘要，或返回设置核对 Profile。")
