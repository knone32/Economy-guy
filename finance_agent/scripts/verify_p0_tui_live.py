"""Bounded final acceptance through the real Textual widgets and DeepSeek transport."""
import argparse
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from tempfile import mkdtemp
from unittest.mock import patch

import verify_sec_b4 as evidence
from demo_stepper import finance_facts
from app.model_config import DEFAULT_LOCAL, DEFAULT_TEMPLATE, ProfileError, resolve_connection
from app.tui import AgentWorkspace
from app.tui_screens import Approval
from app.win_vault import CredentialError, WindowsVault, profile_target
from tests.closure_approval import facts
from textual.widgets import DataTable, Input, Select

ROOT = evidence.ROOT / "artifacts" / "p0_final_live"
URL = "https://api.deepseek.com"
MODEL = "deepseek-flash"
ACTOR = "U001"
VALUE = "资料打印"
EDIT = "把甲企业 F002 的用途改成资料打印。"
PHASES = {"A": "A", "B": "B", "C12": "C", "C34": "C", "C5": "C", "D": "D"}
LIMIT = 30
PROTOCOL_ERRORS = {"API_OR_RESPONSE_ERROR", "PROTOCOL_ERROR", "INVALID_RESPONSE"}
# Micro-yuan, using official peak Flash rates and treating all input as cache misses.
# https://api-docs.deepseek.com/zh-cn/quick_start/pricing/
COST_LIMIT = 10_000_000
MAX_REQUEST_COST = 2 * 1_048_576 + 8 * 393_216


def upper_cost(usage):
    if isinstance(usage, dict):
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        if type(input_tokens) is int and type(output_tokens) is int and input_tokens >= 0 and output_tokens >= 0:
            return 2 * input_tokens + 8 * output_tokens
    return MAX_REQUEST_COST


def budget_allows(known_usage, attempts):
    if len(known_usage) > attempts or attempts >= LIMIT:
        return False
    pending = attempts - len(known_usage)
    return sum(map(upper_cost, known_usage)) + (pending + 1) * MAX_REQUEST_COST <= COST_LIMIT


def api_responses(path):
    if not path.exists():
        return []
    rows = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return [row["data"] for row in rows if row["event"] == "api.response"]


def connection(args, require_key=True):
    bound = resolve_connection(ACTOR, args.profile, template=args.profiles_file,
                               local=args.profiles_local, require_key=require_key)
    profile = bound.profile
    if (profile.provider, profile.model, profile.base_url) != ("deepseek", MODEL, URL):
        raise ProfileError("Only the configured official DeepSeek Flash endpoint is authorized")
    return bound


def changes(before, after):
    return {name for name in before if before[name] != after[name]} - {"reference_anchors"}


def valid_commit(before, after, draft):
    if changes(before, after) != {"invoices", "invoice_audit"}:
        return False
    expected = [{**row, "purpose": VALUE} if (row["company_id"], row["invoice_no"]) == ("C001", "F002")
                else row for row in before["invoices"]]
    audits = after["invoice_audit"]
    return (after["invoices"] == expected and len(audits) == len(before["invoice_audit"]) + 1
            and audits[:-1] == before["invoice_audit"] and all(audits[-1][key] == value for key, value in {
                "actor": ACTOR, "company_id": "C001", "invoice_no": "F002", "field": "purpose",
                "old_value": draft.old_value, "new_value": VALUE, "status": "COMMITTED",
                "request_id": draft.request_id, "fingerprint": draft.fingerprint(),
            }.items()))


class CheckFailed(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise CheckFailed(reason)


class Run:
    def __init__(self, folder, phase, args):
        self.folder, self.phase = folder, phase
        self.db = folder / f"{PHASES[phase]}.sqlite"
        self.trace = folder / f"{phase}.jsonl"
        self.budget = folder / "budget.sqlite"
        self.app = AgentWorkspace(self.db, args.profiles_file, args.profiles_local, trace_path=self.trace)
        self.profile = args.profile
        self.case = phase
        self.monthly_sql = []
        self.steps = []
        self.original_http = evidence.httpx.HTTPTransport.handle_request
        self.requests = []
        self.halt = False

    def dispatch(self, transport, request):
        if (request.method != "POST" or str(request.url) != URL + "/chat/completions"
                or json.loads(request.content).get("model") != MODEL):
            self.halt = True
            raise RuntimeError("Unexpected API target")
        try:
            observed = [entry.get("usage") for path in self.folder.glob("*.result.json")
                        for entry in json.loads(path.read_text(encoding="utf-8"))["requests"]]
            observed.extend(row.get("usage") for row in api_responses(self.trace))
            if not budget_allows(observed, len(evidence.ledger(self.budget))):
                raise RuntimeError("Acceptance cost or attempt limit reached")
            attempt = evidence.claim(self.budget, self.case, LIMIT)
        except (RuntimeError, OSError, ValueError, sqlite3.Error):
            self.halt = True
            raise
        row = {"number": attempt, "scene": self.case, "profile": self.profile, "model": MODEL,
               "started_utc": datetime.now(timezone.utc).isoformat(), "http": 0}
        self.requests.append(row)
        try:
            response = self.original_http(transport, request)
            row["http"] = response.status_code
            return response
        finally:
            evidence.mark(self.budget, attempt, row["http"])
            self.halt = row["http"] != 200

    def connect(self, *args, **kwargs):
        db = evidence.CONNECT(*args, **kwargs)
        if str(args[0]).split("?")[0] == self.db.as_uri():
            def observe(sql):
                if re.search(r"\bFROM\s+(invoices|bank_transactions)\b", sql, re.I):
                    company = re.search(r"\bcompany_id\s*=\s*'(C\d+)'", sql, re.I)
                    month = re.search(r"\b(?:invoice_date|transaction_date)\s+LIKE\s+'(\d{4}-\d{2})%'", sql, re.I)
                    if month and self.case in {"A1", "A2"}:
                        self.monthly_sql.append((company[1] if company else None, month[1]))
            db.set_trace_callback(observe)
        return db

    async def wait(self, pilot, condition):
        async with asyncio.timeout(200):
            while not condition():
                await pilot.pause(0.05)

    async def send(self, pilot, case, text, *, approval=None):
        self.case = case
        record_start = len(self.app.records)
        field = self.app.workspace_widget("#prompt", Input)
        field.value = text
        field.focus()
        await pilot.pause()
        await pilot.press("enter")
        await self.wait(pilot, lambda: not field.value)
        await self.wait(pilot, lambda: not self.app.busy or isinstance(self.app.screen, Approval))
        draft = None
        if isinstance(self.app.screen, Approval):
            modal = self.app.screen
            await self.wait(pilot, lambda: bool(modal.query("#cancel")) and modal.focused is not None)
            await pilot.pause()
            okay = approval is not None and modal.title_text == approval and modal.focused.id == "cancel"
            if approval == "确认发票修改":
                candidates = list(self.app.agent.update_session.drafts.values())
                draft = candidates[0] if len(candidates) == 1 else None
                okay = (okay and draft is not None and
                        (draft.actor, draft.company_id, draft.invoice_no, draft.field, draft.new_value) ==
                        (ACTOR, "C001", "F002", "purpose", VALUE))
            if not okay:
                await pilot.press("escape")
                await self.wait(pilot, lambda: not self.app.busy)
                raise CheckFailed("Unexpected confirmation preview; cancelled")
            await pilot.click("#approve")
            await self.wait(pilot, lambda: not self.app.busy)
        elif approval:
            self.note_turn(case, record_start)
            raise CheckFailed("No expected confirmation modal")
        self.note_turn(case, record_start)
        return draft

    def note_turn(self, case, record_start):
        if len(self.app.records) != record_start + 1:
            raise CheckFailed("TUI did not complete an Agent turn")
        status, calls, api = self.app.records[-1]
        response = self.app.agent.last_response or {}
        self.steps.append({"step": case, "status": status, "tools": calls,
                           "execution": response.get("execution"), "api": api,
                           "clarification": response.get("category") == "clarification"})
        if status in PROTOCOL_ERRORS or response.get("execution", {}).get("stop_reason") in PROTOCOL_ERRORS or self.halt:
            self.halt = True
            raise CheckFailed("Transport or protocol failure; further dispatch stopped")

    async def query(self, pilot):
        before = evidence.snapshot(self.db)
        await self.send(pilot, "A1", "帮我查一下甲企业的发票和银行收支情况。")
        step = self.steps[-1]
        require(step["clarification"] and not self.monthly_sql, "A1 did not safely clarify the period")
        natural = not step["tools"]
        await self.send(pilot, "A2", "2026 年 9 月。")
        step = self.steps[-1]
        require(bool(self.monthly_sql) and all(x == ("C001", "2026-09") for x in self.monthly_sql),
                "A2 SQL scope was not the frozen month")
        invoice, *bank = finance_facts(self.db)
        require(invoice == [962206, 10] and {name: (amount, count) for name, amount, count in bank}
                == {"收入": (1300050, 4), "支出": (718074, 8)}, "Independent SQL totals differ")
        answer = self.app.agent.last_response["text"]
        require(any(c.get("rule") == ("R001", "1.0") and c["status"] == "SUCCESS" for c in step["tools"])
                and all(token in answer for token in ("9622.06", "13000.50", "7180.74"))
                and not changes(before, evidence.snapshot(self.db)), "A2 tool, displayed totals or side effects differ")
        return "PASS" if natural and step["status"] in {"ANSWERED", "COMPLETED"} else "PARTIAL"

    async def invoice(self, pilot, step):
        before = evidence.snapshot(self.db)
        draft = await self.send(pilot, step, EDIT, approval="确认发票修改")
        require(draft is not None and self.app.agent.write_receipt["status"] == "COMMITTED"
                and self.app.agent.write_receipt["readback_verified"]
                and valid_commit(before, evidence.snapshot(self.db), draft), "Commit, audit or readback mismatch")

    async def task(self, pilot):
        before = evidence.snapshot(self.db)
        await self.send(pilot, "C1", "甲企业 2026 年 9 月哪些发票没有填写用途？")
        require(len(facts(self.db)["missing"]) == 5
                and any(c["tool"] == "check_missing_purpose" and c["status"] == "SUCCESS"
                        and c.get("rule") == ("R002", "2.0") for c in self.steps[-1]["tools"])
                and "5张" in self.app.agent.last_response["text"]
                and not changes(before, evidence.snapshot(self.db)), "C1 current missing count, rule or side effects differ")
        note = "这些没填用途的发票明天继续，帮我记一下。"
        await self.send(pilot, "C2", note, approval="确认待办")
        after = evidence.snapshot(self.db)
        require(changes(before, after) == {"tasks"} and len(after["tasks"]) == 1, "C2 task not saved or unexpected writes")
        row = after["tasks"][0]
        require((row["user_id"], row["company_id"], row["year"], row["month"], row["task_type"], row["status"])
                == (ACTOR, "C001", 2026, 9, "missing_purpose", "ACTIVE")
                and json.loads(row["context_json"])["note"] == note, "C2 bound task facts differ")
        self.steps[-1]["task_id"] = row["task_id"]

    async def restored(self, pilot, count):
        prior = json.loads((self.folder / "C12.result.json").read_text(encoding="utf-8"))
        task_id = prior["steps"][-1]["task_id"]
        require(os.getpid() != prior["pid"], "C task did not restart in a new process")
        if self.phase == "C5":
            second = json.loads((self.folder / "C34.result.json").read_text(encoding="utf-8"))
            require(second["pid"] != os.getpid(), "C5 did not restart in a new process")
        before = evidence.snapshot(self.db)
        require(self.app.agent is None, "Old Agent was restored")
        await pilot.click("#go-tasks")
        await self.wait(pilot, lambda: bool(self.app.workspace_widget("#task-body").query("#todo-0")))
        await pilot.click("#todo-0")
        await self.wait(pilot, lambda: bool(self.app.workspace_widget("#task-body").query("#linked-finance")))
        await pilot.click("#linked-finance")
        await self.wait(pilot, lambda: bool(self.app.workspace_widget("#finance-body").query("#invoice-table")))
        require(self.app.workspace_widget("#invoice-table", DataTable).row_count == 10
                and any(t["task_id"] == task_id and t["status"] == "ACTIVE" for t in before["tasks"])
                and len(facts(self.db)["missing"]) == count, "Restored task, invoices or missing count mismatch")
        await pilot.click("#back-detail")
        await self.wait(pilot, lambda: bool(self.app.workspace_widget("#task-body").query("#continue-task")))
        await pilot.click("#continue-task")
        await self.wait(pilot, lambda: self.app.agent is not None)
        require(self.app.agent.context.scope.get("task_id") == [task_id]
                and not self.app.agent.update_session.drafts and not self.app.agent.update_session.confirmations
                and not changes(before, evidence.snapshot(self.db)), "Restored focus or permission boundary differs")
        self.steps.append({"step": "C3" if count == 5 else "C5", "task_id": task_id, "missing": count,
                           "status": "ACTIVE", "requests_before_restore": self.app.model_requests})

    async def directory(self, pilot):
        before = evidence.snapshot(self.db)
        await self.send(pilot, "D1", "列出甲企业目前所有发票。")
        calls = self.steps[-1]["tools"]
        require(any(c["tool"] == "list_invoice_directory" and c["status"] == "SUCCESS"
                    and c["scope"] == {"company_id": "C001"} for c in calls), "D1 did not use the company directory")
        require(self.app.chat_invoice_route == ("C001", 0, 0, 1), "D1 did not present the first directory page")
        link = self.app.workspace_widget("#chat-invoices")
        await self.wait(pilot, lambda: link.display and link.region.width > 0 and link.region.height > 0)
        link.focus()
        await pilot.pause()
        await pilot.press("enter")
        await self.wait(pilot, lambda: bool(self.app.workspace_widget("#finance-body").query("#invoice-table")))
        actual = [(row["invoice_date"], row["invoice_no"]) for row in self.app.invoice_rows]
        expected = sorted((row["invoice_date"], row["invoice_no"])
                          for row in before["invoices"] if row["company_id"] == "C001")
        shown = "".join(line.text for line in self.app.workspace_widget("#chat-log").lines)
        require(actual == expected[:10] and f"共 {len(expected)} 张" in shown,
                "D1 displayed directory differs from independent SQL")
        await pilot.click("#go-chat")
        await self.wait(pilot, lambda: self.app.workspace_widget("#prompt").region.width > 0)
        await self.send(pilot, "D2", "告诉我甲企业 F002 的发票详情。")
        calls = self.steps[-1]["tools"]
        row = next(item for item in before["invoices"] if item["company_id"] == "C001" and item["invoice_no"] == "F002")
        shown = "".join(line.text for line in self.app.workspace_widget("#chat-log").lines)
        require(any(c["tool"] == "get_invoice" and c["status"] == "SUCCESS"
                    and c["scope"]["invoice_no"] == "F002" for c in calls)
                and all(text in shown for text in ("发票编号", "F002", row["invoice_date"],
                                                   row["seller_name"], row["item_name"], "价税合计", "用途", "备注"))
                and not changes(before, evidence.snapshot(self.db)), "D2 detail or read-only boundary differs")

    async def drive(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.screen.query_one("#login-user", Select).value = ACTOR
            await pilot.click("#sign-in")
            require(self.app.user == ACTOR and self.app.mode == "live", "TUI login did not start Live")
            self.app.profile = self.profile
            if self.phase == "A":
                return await self.query(pilot)
            if self.phase == "D":
                await self.directory(pilot)
            if self.phase == "B":
                await self.invoice(pilot, "B")
            if self.phase == "C12":
                await self.task(pilot)
            if self.phase == "C34":
                await self.restored(pilot, 5)
                await self.invoice(pilot, "C4")
                require(len(facts(self.db)["missing"]) == 4, "C4 did not reduce current missing count")
            if self.phase == "C5":
                await self.restored(pilot, 4)
        return "PASS"

    def execute(self):
        before = evidence.snapshot(self.db)
        status, failure = "FAIL", None
        try:
            with (patch.object(evidence.httpx.HTTPTransport, "handle_request",
                               lambda transport, request: self.dispatch(transport, request)),
                  patch.object(sqlite3, "connect", self.connect)):
                status = asyncio.run(self.drive())
        except CheckFailed as error:
            failure = str(error)
        except (TimeoutError, OSError, ValueError, sqlite3.Error) as error:
            failure = type(error).__name__
        finally:
            responses = api_responses(self.trace)
            for sent, response in zip(self.requests, responses):
                sent.update(usage=response.get("usage"), success=response.get("success"),
                            response_model=response.get("response_model"), category=response.get("http_category"),
                            latency_ms=response.get("latency_ms"))
            evidence.save(self.folder / f"{self.phase}.result.json",
                          {"phase": self.phase, "pid": os.getpid(), "status": status, "failure": failure,
                           "stop_live": self.halt, "actor": "SIMULATED_TEST_USER / Textual Pilot",
                           "steps": self.steps, "requests": self.requests, "changed_tables":
                               sorted(changes(before, evidence.snapshot(self.db)))})
        return 3 if self.halt else 0 if status == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="shared-flash")
    parser.add_argument("--profiles-file", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--profiles-local", type=Path, default=DEFAULT_LOCAL)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--p0-windows-vault", action="store_true",
                        help="允许从 Windows 普通凭据 Economy-guy/P0-Live/shared-flash 读取验收密钥")
    parser.add_argument("--worker", choices=PHASES, help=argparse.SUPPRESS)
    parser.add_argument("--run", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        bound = connection(args, require_key=False)
    except ProfileError:
        print("BLOCKED_PROFILE · 配置不可见、无效或不匹配 DeepSeek Flash。")
        return 3
    key_env = bound.profile.api_key_env
    if not os.environ.get(key_env, "").strip():
        try:
            vault = WindowsVault()
            saved = vault.read(profile_target(bound.profile))
            if not saved and args.p0_windows_vault and bound.profile.profile_name == "shared-flash":
                saved = vault.read("Economy-guy/P0-Live/shared-flash")
            if saved and saved.strip():
                os.environ[key_env] = saved.strip()
        except CredentialError:
            pass
    if not os.environ.get(key_env, "").strip():
        print("BLOCKED_CREDENTIALS · 已验证可见模型配置；当前进程和允许的 Windows 凭据均未就绪。实际 API 尝试 0。")
        return 3
    if args.preflight:
        print("READY · 仅离线核对 Profile、模型、端点和凭据就绪。实际 API 尝试 0。")
        return 0
    if args.worker:
        if args.run is None:
            parser.error("Missing internal run directory")
        folder = args.run.resolve()
        paths = (folder / "budget.sqlite", folder / f"{PHASES[args.worker]}.sqlite")
        if (folder.parent != ROOT.resolve() or not folder.name.startswith("run-")
                or any(not p.is_file() or p.resolve() != p or p.stat().st_nlink != 1 for p in paths)):
            parser.error("Invalid internal run directory")
        return Run(folder, args.worker, args).execute()
    ROOT.mkdir(parents=True, exist_ok=True)
    folder = Path(mkdtemp(prefix="run-", dir=ROOT)).resolve()
    for scene in "ABCD":
        evidence.new_database(folder / f"{scene}.sqlite")
    evidence.init_budget(folder / "budget.sqlite")
    results = {}
    for phase in PHASES:
        if phase in {"C34", "C5"} and results.get("C12" if phase == "C34" else "C34") != "PASS":
            results[phase] = "NOT_TESTED"
            continue
        command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--profile", args.profile,
                   "--profiles-file", str(args.profiles_file.resolve()), "--profiles-local",
                   str(args.profiles_local.resolve()), "--worker", phase, "--run", str(folder)]
        code = subprocess.run(command, check=False).returncode
        result_path = folder / f"{phase}.result.json"
        results[phase] = json.loads(result_path.read_text(encoding="utf-8"))["status"] if result_path.exists() else "FAIL"
        if code not in {0, 1}:
            break
    total = len(evidence.ledger(folder / "budget.sqlite"))
    results = {phase: results.get(phase, "NOT_TESTED") for phase in PHASES}
    sent = [entry for path in folder.glob("*.result.json")
            for entry in json.loads(path.read_text(encoding="utf-8"))["requests"]]
    usage = [entry.get("usage") for entry in sent]
    reserve = max(0, total - len(usage)) * MAX_REQUEST_COST
    upper = sum(map(upper_cost, usage)) + reserve
    evidence.save(folder / "summary.json", {"results": results, "attempts": total,
                  "upper_estimated_cost_cny": upper / 1_000_000,
                  "billing_receipt": "NOT_OBSERVED"})
    print(json.dumps({"results": results, "attempts": total, "evidence": str(folder)}, ensure_ascii=False))
    return 0 if all(value == "PASS" for value in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
