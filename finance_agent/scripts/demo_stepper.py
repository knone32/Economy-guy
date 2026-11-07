"""Interactive, isolated acceptance driver for the production Agent."""
import argparse
from contextlib import closing
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from tempfile import mkdtemp
from time import perf_counter
from unittest.mock import patch

import verify_sec_b4 as evidence
from app.agent import Agent, scripted_model
from app.model_config import DEFAULT_LOCAL, DEFAULT_TEMPLATE, resolve_connection
from app.trace import redact
from tests import closure_approval as approval


RUN_ROOT = evidence.ROOT / "artifacts/demo_runs"
BUDGET = 24
ACTOR = "U001"
MODEL = "deepseek-flash"
BASE_URL = "https://api.deepseek.com"
SCOPE = dict(company_id="C001", year=2026, month=9)
TARGET = dict(actor=ACTOR, company_id="C001", invoice_no="F002", field="purpose",
              new_value=evidence.VALUE)
EDIT = "把甲企业 F002 发票的用途改成项目资料核对。"
PHASES = (("A1", "A2", "A3"), ("B1", "B2", "B3", "B4", "B5"),
          ("C1", "C2"), ("C3", "C4", "C5"), ("C6",))
REQUESTS = {
    "A1": ("帮我查一下甲企业的发票和银行收支情况。", 1),
    "A2": ("2026 年 9 月。", 3),
    "B1": (EDIT, 3),
    "B5": (EDIT, 2),
    "C1": ("甲企业 2026 年 9 月哪些发票还没有填写用途？", 2),
    "C2": ("把这些没补完用途的发票记成一个待办，我下次再继续处理。", 3),
    "C3": ("继续我在 C001 2026 年 9 月的用途待办。请只读取当前待办和缺失用途，不修改任务。", 2),
    "C4": (EDIT, 2),
    "C5": ("现在还差哪些用途没补？接下来我该怎么做？", 3),
    "C6": ("查询我在 C001 2026 年 9 月尚未完成的任务和当前缺失用途。", 3),
}
LABELS = {
    "A1": "缺失年月", "A2": "跨轮补充年月", "A3": "核对对话和业务结果",
    "B1": "模型提出修改草稿", "B2": "展示正式草稿", "B3": "模拟确认和提交",
    "B4": "独立读取目标和审计", "B5": "重复修改核验",
    "C1": "检查缺失用途", "C2": "模型提出并创建待办", "C3": "新进程恢复待办",
    "C4": "受控补齐一张发票", "C5": "核对剩余事项和下一步", "C6": "第二次重启恢复",
}
SIMULATED = ("SIMULATED_TEST_USER · 此处使用演示器代替人工输入确认，但保留正式确认和事务流程，"
             "不属于真实人工授权验收。")


class Quit(Exception):
    pass


def read_key(getwch=None, read=None):
    if getwch is None and read is None and os.name == "nt" and sys.stdin.isatty():
        import msvcrt
        getwch = msvcrt.getwch
    if getwch:
        while True:
            key = getwch()
            if key in ("\x00", "\xe0"):
                getwch()
            elif key in ("\r", " "):
                return True
            elif key.lower() == "q":
                return False
            elif key == "\x03":
                raise KeyboardInterrupt
    while True:
        try:
            key = (read or input)()
        except EOFError:
            return False
        if key in ("", " "):
            return True
        if key.strip().lower() == "q":
            return False


def pipe_line():
    # A worker must leave the next worker's redirected input in the shared pipe.
    line = bytearray()
    while True:
        char = os.read(sys.stdin.fileno(), 1)
        if not char:
            if not line:
                raise EOFError
            break
        if char == b"\n":
            break
        line.extend(char)
    return line.rstrip(b"\r").decode("ascii", errors="replace")


def pause():
    print("[Enter / Space] 推进（行输入终端按 Enter）    [Q] 退出", flush=True)
    if not read_key(read=None if sys.stdin.isatty() else pipe_line):
        raise Quit


def reserve(path, case):
    with closing(evidence.CONNECT(path.as_uri() + "?mode=rw", uri=True)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        total, own, failed = db.execute(
            "SELECT count(*), count(CASE WHEN case_id=? THEN 1 END), "
            "count(CASE WHEN status IS NULL OR status != 200 THEN 1 END) FROM attempts",
            (case,)).fetchone()
        if total >= BUDGET or own >= REQUESTS[case][1] or failed:
            raise RuntimeError("API budget refused dispatch")
        return db.execute("INSERT INTO attempts(case_id) VALUES(?)", (case,)).lastrowid


def connection(args):
    resolved = resolve_connection(ACTOR, args.profile, template=args.profiles_file,
                                  local=args.profiles_local)
    p = resolved.profile
    if (p.provider, p.model, p.base_url.rstrip("/")) != ("deepseek", MODEL, BASE_URL):
        raise ValueError("Unexpected demo model binding")
    return resolved


def safe(value):
    """Keep terminal controls out of output as well as secrets covered by Trace."""
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\ud800-\udfff]", "", redact(value))


def load_lines(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def log(path, record):
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(redact(record), ensure_ascii=True) + "\n")


def mock_replies(case):
    def call(name, arguments, n):
        return dict(id=f"mock_{case}_{n}", type="function",
                    function=dict(name=name, arguments=json.dumps(arguments, ensure_ascii=False)))

    def tools(*calls):
        return dict(role="assistant", tool_calls=[call(*c, n) for n, c in enumerate(calls, 1)])

    def answer(content):
        return dict(role="assistant", content=content)

    if case == "A1":
        return [answer(json.dumps(dict(kind="clarification", text="请问要查询哪一年、哪一月？",
                                       missing_fields=["year", "month"]), ensure_ascii=False))]
    if case == "A2":
        return [tools(("get_finance_summary", SCOPE)), answer('{"kind":"information","text":"已查询。"}')]
    if case == "B5":
        return [tools(("get_invoice", {"company_id": "C001", "invoice_no": "F002"})),
                answer('{"kind":"information","text":"已核对当前值。"}')]
    if case in {"B1", "C4"}:
        return [tools(("prepare_invoice_update", {k: TARGET[k] for k in
                      ("company_id", "invoice_no", "field", "new_value")})), answer("已核对当前目标。")]
    if case == "C2":
        return [tools(("manage_task", dict(**SCOPE, action="create", task_id="",
                                          note="用途未填写的发票记成待办，下次继续处理。"))),
                answer('{"kind":"information","text":"已处理待办请求。"}')]
    check = ("check_missing_purpose", SCOPE)
    if case == "C1":
        return [tools(check), answer('{"kind":"information","text":"已检查。"}')]
    return [tools(("list_tasks", {"company_id": "C001"}), check), answer('{"kind":"information","text":"已核对当前进度。"}')]


def observations(messages):
    calls, outcomes = [], []
    for msg in messages:
        for call in msg.get("tool_calls", []):
            fn = call["function"]
            try:
                args = json.loads(fn.get("arguments", ""))
            except (TypeError, ValueError):
                args = None
            args = args if isinstance(args, dict) else {}
            shown = {}
            for key, value in args.items():
                if key in {"year", "month"} and type(value) is int:
                    shown[key] = value
                elif key in {"company_id", "invoice_no", "field", "new_value", "action", "task_id"}:
                    if isinstance(value, str) and (value in ("", "purpose", evidence.VALUE, "create", "show")
                            or re.fullmatch(r"[CF]\d{3}|[a-f0-9]{32}", value)):
                        shown[key] = value
                    else:
                        shown[key] = "[未展示]"
            calls.append(dict(id=call["id"], tool=fn.get("name", ""), args=shown))
        if msg.get("role") == "tool":
            outcomes.append((msg["tool_call_id"], json.loads(msg["content"])))
    paired = [c["id"] for c in calls] == [key for key, _ in outcomes]
    for call, (key, outcome) in zip(calls, outcomes):
        if call["id"] == key:
            call["status"] = outcome["status"]
            call["scope"] = outcome.get("evidence", {}).get("scope")
            rule = outcome.get("evidence", {}).get("rule") or {}
            call["rule"] = [rule.get("rule_id", rule.get("id")), rule.get("version")]
    return calls, paired, [outcome for _, outcome in outcomes]


def draft_matches(agent, state, case, used):
    session = agent.update_session
    if case not in {"B1", "B3", "C4"} or agent.user_id != ACTOR or len(session.drafts) != 1:
        return None
    key, draft = next(iter(session.drafts.items()))
    current = evidence.invoice(state)
    expected = dict(**TARGET, source_request=EDIT, old_value=current["purpose"],
                    session_id=session.session_id, turn_id=session.turn_id)
    if (not state["invoice_audit"] and current["invoice_date"].startswith("2026-09")
            and current["purpose"] != evidence.VALUE
            and any(p["user_id"] == ACTOR and p["company_id"] == "C001" and p["can_modify"]
                    for p in state["permissions"])
            and all(getattr(draft, k) == v for k, v in expected.items())
            and key == draft.request_id and draft.request_id not in used
            and re.fullmatch(r"[0-9a-f]{32}", key)
            and draft.fingerprint() == approval.digest(asdict(draft))
            and draft.fingerprint() != approval.OLD_FINGERPRINT):
        return draft
    return None


def finance_facts(path):
    with closing(evidence.CONNECT(path.as_uri() + "?mode=ro", uri=True)) as db:
        invoice = db.execute("SELECT sum(amount_cents), count(*) FROM invoices "
                             "WHERE company_id='C001' AND invoice_date LIKE '2026-09%'").fetchone()
        bank = db.execute("SELECT direction, sum(amount_cents), count(*) FROM bank_transactions "
                          "WHERE company_id='C001' AND transaction_date LIKE '2026-09%' "
                          "GROUP BY direction").fetchall()
        return [list(invoice), *[list(row) for row in bank]]


def task_facts(state):
    return [{k: row[k] for k in ("task_id", "status", "company_id", "year", "month")}
            for row in state["tasks"]]


class Phase:
    def __init__(self, folder, args, index):
        self.folder, self.args = folder, args
        self.steps = PHASES[index]
        self.db = folder / (self.steps[0][0] + ".sqlite")
        self.trace = folder / f"trace_{index}.jsonl"
        self.results = folder / "steps.jsonl"
        self.budget = folder / "budget.sqlite"
        self.mode = args.mode
        self.case = None
        self.previewed = None
        self.receipt = None
        self.used = {approval.OLD_REQUEST_ID}
        self.task_policy = approval.SimulatedApproval()
        self.agent = Agent(ACTOR, self.db, mode=self.mode, trace_path=self.trace,
                           connection=connection(args) if self.mode == "live" else None,
                           management_confirmation=self.confirm_task)
        self.confirmations = []
        self.sql = []
        self.transport_latency = {}
        self.original_send = evidence.httpx.HTTPTransport.handle_request

    def send(self, transport, request):
        if (self.mode != "live" or self.case not in REQUESTS or request.method != "POST"
                or str(request.url) != BASE_URL + "/chat/completions"
                or json.loads(request.content).get("model") != MODEL):
            raise RuntimeError("Unexpected demo dispatch")
        attempt = reserve(self.budget, self.case)
        started = perf_counter()
        status = 0
        try:
            response = self.original_send(transport, request)
            status = response.status_code
            return response
        finally:
            evidence.mark(self.budget, attempt, status)
            self.transport_latency[attempt] = round((perf_counter() - started) * 1000, 2)

    def connect(self, *args, **kwargs):
        db = evidence.CONNECT(*args, **kwargs)
        if str(args[0]).split("?")[0] == self.db.as_uri():
            db.set_trace_callback(self.observe_sql)
        return db

    def observe_sql(self, statement):
        table = re.search(r"\bFROM\s+(invoices|bank_transactions)\b", statement, re.I)
        if table is None:
            return
        company = re.search(r"\bcompany_id\s*=\s*'(C\d+)'", statement, re.I)
        month = re.search(r"\b(?:invoice_date|transaction_date)\s+LIKE\s+'(\d{4}-\d{2})%'", statement, re.I)
        self.sql.append([table[1], company[1] if company else None, month[1] if month else None])

    def confirm_task(self, proposal):
        if self.case != "C2":
            return False
        # Rebind the frozen policy to this prompt; only the frozen wording gains a token.
        with (patch.object(approval, "C2_REQUEST", REQUESTS["C2"][0]),
              patch.object(approval, "WORDS", approval.WORDS | {"没补完"})):
            decision = self.task_policy.review(proposal, self.db, self.agent.user_id,
                                               self.agent.management_proposals.turn_id)
        record = {k: decision[k] for k in ("request_id", "fingerprint", "approved", "reasons")}
        record["confirmation_source"] = "SIMULATED_TEST_USER"
        self.confirmations.append(record)
        if not decision["approved"]:
            print("模拟任务确认拒绝 · " + ", ".join(decision["reasons"]))
            return False
        record["payload"] = proposal["proposal"]
        print(SIMULATED)
        print("U001 / C001 / 2026-09 / missing_purpose · 只创建待办，不自动修改发票")
        print(f"说明 · {safe(record['payload']['note'])}\n请求编号 · {record['request_id']}")
        before = evidence.snapshot(self.db)
        try:
            pause()
        except (Quit, KeyboardInterrupt):
            record["approved"] = False
            record["reasons"] = ["cancelled"]
            self.cancelled = True
            return False
        record["approved"] = before == evidence.snapshot(self.db)
        if not record["approved"]:
            record["reasons"] = ["database_changed"]
        return record["approved"]

    @staticmethod
    def show_draft(draft):
        print(f"{draft.actor} / {draft.company_id} / {draft.invoice_no} / {draft.field} · 权限已核对")
        print(f"原值 · {safe(str(draft.old_value))}    新值 · {safe(draft.new_value)}")
        print(f"请求编号 · {draft.request_id}")

    def commit(self, draft):
        if draft is None:
            return "FAIL", "当前草稿与冻结目标、权限或会话不符"
        self.show_draft(draft)
        print(SIMULATED)
        before = evidence.snapshot(self.db)
        pause()
        if (before != evidence.snapshot(self.db)
                or draft is not draft_matches(self.agent, before, self.case, self.used)):
            return "FAIL", "草稿或数据库在模拟确认前已改变"
        self.used.add(draft.request_id)
        fingerprint = draft.fingerprint()
        self.confirmations.append(dict(approved=True, confirmation_source="SIMULATED_TEST_USER",
                                       request_id=draft.request_id, fingerprint=fingerprint))
        self.receipt = self.agent.commit_update(draft.request_id, fingerprint)
        if self.receipt["status"] != "COMMITTED" or not self.receipt["readback_verified"]:
            return "FAIL", "正式 Commit/Audit/Readback 未同时核实"
        return "PASS", "COMMITTED · 正式 Commit/Audit/Readback 一致"

    def read_only_facts(self, answer, calls, outcomes, state, stop):
        case = self.case
        if case == "A1":
            if self.sql:
                return "FAIL", "缺年月时执行了业务读取"
            if not calls and stop == "WAITING_USER" and all(word in answer for word in ("年份", "月份")):
                return "PASS", "主动追问年月，业务 SQL 为零"
            if any(c.get("status") in {"AMBIGUOUS", "SCOPE_MISMATCH"} for c in calls):
                return "PARTIAL", "模型先提案，Harness 拦截，业务 SQL 为零"
            return "FAIL", "未识别缺失年月"
        if case == "A2":
            expected = [[962206, 10], ["支出", 718074, 8], ["收入", 1300050, 4]]
            required = ("9622.06 元（10张）", "13000.50 元（4条）", "7180.74 元（8条）")
            rules = any(c.get("rule") == ["R001", "1.0"] and c.get("scope") == SCOPE
                        and c.get("status") == "SUCCESS" for c in calls)
            if (finance_facts(self.db) != expected or not rules or
                    not all(part in answer for part in required) or not self.sql
                    or any(scope[1:] != ["C001", "2026-09"] for scope in self.sql)):
                return "FAIL", "本轮工具、展示或独立 SQL 未核实预期财务结果"
            if stop not in {"ANSWERED", "COMPLETED"}:
                return "PARTIAL", f"金额、笔数、范围和 R001 v1.0 正确；对话停止原因 {stop}"
            return "PASS", "金额、笔数、范围和 R001 v1.0 正确，且自然结束"
        count = 5 if case in {"C1", "C3"} else 4
        facts = approval.facts(self.db)["missing"]
        valid_check = any(
            c["tool"] == "check_missing_purpose" and c["status"] == "SUCCESS"
            and c["scope"] == SCOPE and c["rule"] == ["R002", "2.0"]
            and r["data"]["count"] == count
            and sorted(item["invoice_no"] for item in r["data"]["missing_invoices"]) == sorted(facts)
            for c, r in zip(calls, outcomes))
        if len(facts) != count or not valid_check:
            return "FAIL", "本轮缺项工具、R002 v2.0 或独立 SQL 不符"
        if case == "C1":
            if stop in {"ANSWERED", "COMPLETED"} and "5张必填用途缺失" in answer:
                return "PASS", "模型工具与独立 SQL 一致，R002 v2.0 缺 5 张"
            return "PARTIAL", f"工具与 SQL 缺 5 张；展示或收尾未达到预期（{stop}）"
        history = {row["step"]: row for row in load_lines(self.results)}
        original = history["C2"]["tasks"]
        tasks = task_facts(state)
        if len(tasks) != 1 or original != tasks or tasks[0]["status"] != "ACTIVE":
            return "FAIL", "未核实同一 ACTIVE 任务"
        task_id = tasks[0]["task_id"]
        read = any(c["tool"] in {"list_tasks", "manage_task"} and r["status"] == "SUCCESS"
                   and r.get("evidence", {}).get("source") == "current_sqlite"
                   and any(row.get("task_id") == task_id and row.get("status") == "ACTIVE"
                           for row in (r["data"] if isinstance(r["data"], list)
                                       else [r["data"].get("task", {})]))
                   for c, r in zip(calls, outcomes))
        if not read:
            return "FAIL", "本轮缺少实际任务工具读取"
        if case in {"C3", "C6"}:
            previous = "C2" if case == "C3" else "C5"
            if history[previous]["pid"] == os.getpid():
                return "FAIL", "没有启动新 Python 进程"
        if (stop not in {"ANSWERED", "COMPLETED"} or
                f"当前剩余 {count} 张必填用途缺失" not in answer or "下一步：" not in answer):
            return "PARTIAL", f"已重查同一 ACTIVE 任务，缺 {count} 张；对话未给出完整进度或收尾"
        return "PASS", f"已重查同一 ACTIVE 任务，缺 {count} 张，展示下一步"

    def ask(self, state):
        case = self.case
        source, cap = REQUESTS[case]
        self.agent.max_requests = cap
        self.agent.budget_policy = replace(self.agent.budget_policy, max_requests=cap)
        if self.mode == "mock":
            self.agent.model = scripted_model(mock_replies(case))
        offset = len(self.agent.messages)
        answer = self.agent.ask(source, allow_prepare=case in {"B1", "B5", "C4"})
        calls, paired, outcomes = observations(self.agent.messages[offset:])
        response = self.agent.last_response
        stop = response["execution"]["stop_reason"]
        if not paired:
            verdict = "FAIL", "模型工具 ID 未逐一配对"
        elif stop in {"API_OR_RESPONSE_ERROR", "PROTOCOL_ERROR"}:
            verdict = ("BLOCKED" if self.mode == "live" else "FAIL"), stop
        elif case in {"B1", "C4"}:
            draft = draft_matches(self.agent, state, case, self.used)
            expected = [(c["tool"], c["status"]) for c in calls]
            if draft is None or expected != [("prepare_invoice_update", "WAITING_CONFIRMATION")] or stop != "WAITING_CONFIRMATION":
                verdict = "FAIL", "未由模型产生唯一合规 Prepare，或 Harness 未等待确认"
            else:
                verdict = self.commit(draft) if case == "C4" else ("PASS", "模型实际生成合规草稿")
        elif case == "B5":
            if self.agent.write_receipt["status"] == "CURRENT_VALUE_MATCHES" and not self.confirmations and stop == "ANSWERED":
                verdict = "PASS", "CURRENT_VALUE_MATCHES · 无第二次提交"
            else:
                verdict = "FAIL", "未取得可信 CURRENT_VALUE_MATCHES 回执"
        elif case == "C2":
            if (len(self.confirmations) == 1 and self.confirmations[0]["approved"]
                    and any(c["tool"] == "manage_task" and c["status"] == "SUCCESS" for c in calls)
                    and len(task_facts(evidence.snapshot(self.db))) == 1):
                verdict = (("PASS", "具体候选通过模拟确认，SQLite 已保存唯一 ACTIVE 待办")
                           if stop in {"ANSWERED", "COMPLETED"}
                           else ("PARTIAL", f"待办已真实保存；模型收尾 {stop}"))
            else:
                verdict = "FAIL", "没有合规候选、未确认，或未保存真实待办"
        else:
            verdict = self.read_only_facts(answer, calls, outcomes, state, stop)
        return verdict, response, calls, answer


    def local_step(self, before):
        if self.case == "A3":
            a1, a2 = load_lines(self.results)
            print(f"A1 用户 · {REQUESTS['A1'][0]}    A2 用户 · {REQUESTS['A2'][0]}")
            print(f"追问 · {a1['status']}    工具 · {a2['execution']['actual_tool_calls']} 次实际调用")
            stop = a2["execution"]["stop_reason"]
            print(f"自然结束 · {stop in {'ANSWERED', 'COMPLETED'}}    MODEL_LIMIT · {stop == 'MODEL_LIMIT'}")
            status = "PASS" if a1["status"] == a2["status"] == "PASS" else "PARTIAL"
            return status, a2["detail"]
        draft = draft_matches(self.agent, before, "B1", self.used)
        if self.case == "B2":
            if draft is None:
                return "FAIL", "没有可展示的唯一合法草稿"
            self.previewed = draft
            self.show_draft(draft)
            return "PASS", "仅展示草稿，尚未提交"
        if self.case == "B3":
            return self.commit(draft if draft is self.previewed else None)
        audits = before["invoice_audit"]
        okay = (len(audits) == 1 and self.receipt and self.receipt["readback_verified"]
                and evidence.invoice(before)["purpose"] == evidence.VALUE
                and audits[0]["request_id"] == self.previewed.request_id
                and audits[0]["fingerprint"] == self.previewed.fingerprint())
        return ("PASS", "COMMITTED · 目标字段、独立回读和唯一审计一致") if okay else (
            "FAIL", "独立连接未核实目标字段和唯一审计")

    def api_metrics(self, offset):
        if self.mode != "live":
            return []
        trace = [row["data"] for row in load_lines(self.trace)[offset:] if row["event"] == "api.response"]
        attempts = []
        for number, case, status in evidence.ledger(self.budget):
            if case != self.case:
                continue
            observed = trace[len(attempts)] if len(trace) > len(attempts) else {}
            response_model = observed.get("response_model")
            attempts.append(dict(number=number, step=case, model=MODEL,
                                 response_model=safe(response_model) if response_model else None,
                                 http_status=status or None,
                                 usage=observed.get("usage"),
                                 latency_ms=observed.get("latency_ms", self.transport_latency.get(number)),
                                 failure=None if observed.get("success") else
                                 observed.get("http_category", "NO_OBSERVED_RESPONSE")))
        return attempts

    def step(self, case):
        self.case = case
        self.confirmations = []
        self.sql = []
        print(f"\n━━ {self.mode.upper()} · {case} / {LABELS[case]} ━━")
        if case in REQUESTS:
            print(f"用户 · {REQUESTS[case][0]}")
        if case in {"C3", "C6"}:
            print(f"新 Python 进程 PID {os.getpid()} · 读取同一个 C 库")
        pause()
        before = evidence.snapshot(self.db)
        trace_offset = len(load_lines(self.trace))
        response, calls, answer = {}, [], ""
        started = perf_counter()
        try:
            if case in REQUESTS:
                verdict, response, calls, answer = self.ask(before)
            else:
                verdict = self.local_step(before)
        except (Quit, KeyboardInterrupt):
            self.record(before, ("NOT_TESTED", "确认前退出或请求中断；以下为已观察事实"),
                        response, calls, answer, trace_offset, started)
            raise
        if self.cancelled:
            verdict = "NOT_TESTED", "观看者在任务确认前退出"
        self.record(before, verdict, response, calls, answer, trace_offset, started)
        if self.cancelled:
            raise Quit
        return verdict[0] if not self.unexpected_change else "FAIL"

    def record(self, before, verdict, response, calls, answer, trace_offset, started):
        after = evidence.snapshot(self.db)
        case = self.case
        changed, unexpected = evidence.verify_changes(
            "B1" if case == "B3" else case, before, after, self.confirmations)
        if (case in {"B3", "C4"} and verdict[0] == "PASS"
                and not {"invoices", "invoice_audit"} <= set(changed)):
            unexpected = True
        status, detail = verdict
        if unexpected:
            status, detail = "FAIL", "独立 SQLite 快照发现非预期变化"
        self.unexpected_change = unexpected
        elapsed = round(perf_counter() - started, 2)
        # Display bounded Harness evidence; bulk rows and model wire messages stay in local redacted Trace.
        prefixes = ("实际查询范围：", "本轮查询：", "本轮发票价税合计", "本轮银行收入",
                    "本轮检查：", "任务 ", "下一步：", "请提供", "无需再次修改：")
        visible = list(dict.fromkeys(safe(line)[:500] for line in answer.splitlines()
                                     if line.startswith(prefixes)))[:12]
        receipt = self.receipt if case in {"B3", "B4", "C4"} else response.get("operation_receipt")
        execution = {k: response.get("execution", {}).get(k) for k in
                     ("model_requests", "actual_tool_calls", "extensions", "replans", "stop_reason")}
        state = dict(purpose=evidence.invoice(after)["purpose"], success_audits=sum(
            row["status"] == "COMMITTED" for row in after["invoice_audit"]))
        if case in {"B3", "B4", "C4"} and after["invoice_audit"]:
            state["latest_audit_request_id"] = after["invoice_audit"][-1]["request_id"]
        api = self.api_metrics(trace_offset)
        record = dict(step=case, status=status, detail=detail, mode=self.mode.upper(),
                      pid=os.getpid(), source=REQUESTS.get(case, (None,))[0], tools=calls,
                      execution=execution, sql=self.sql.copy(), elapsed_seconds=elapsed,
                      changed_tables=changed, unexpected_change=unexpected,
                      invoice=state, audit_increment=len(after["invoice_audit"]) - len(before["invoice_audit"]),
                      tasks=task_facts(after), missing=approval.facts(self.db)["missing"],
                      simulated_confirmations=self.confirmations, api=api, visible=visible,
                      receipt=receipt["status"] if receipt else None,
                      readback_verified=receipt.get("readback_verified") if receipt else None,
                      trace_id=self.agent.trace_id if case in REQUESTS else None,
                      trace_degraded=self.agent.trace_degraded)
        log(self.results, record)
        label = "实际模型" if self.mode == "live" else "Mock 提案"
        for call in calls:
            print(f"{label} · {safe(call['tool'])} · {safe(call['id'])} → {safe(call.get('status', 'UNPAIRED'))}"
                  f" · {json.dumps(redact(call['args']), ensure_ascii=False)}")
            if call.get("scope"):
                print(f"  实际范围 {safe(str(call['scope']))} · 规则 {safe(str(call['rule']))}")
        for line in visible:
            print(line)
        if case[0] in "BC":
            print(f"SQLite · F002 用途 {safe(str(state['purpose']))} · 成功审计 {state['success_audits']}"
                  f"（本步 {record['audit_increment']:+}）")
        if record["tasks"]:
            for task in record["tasks"]:
                print(f"SQLite · 任务 {task['task_id']} · {task['status']} · 缺项 {len(record['missing'])}"
                      f"（{'、'.join(record['missing'])}）")
        if case in REQUESTS:
            model = MODEL if self.mode == "live" else "scripted/mock"
            print(f"{model} · 模型 {execution['model_requests']} / 实际工具 {execution['actual_tool_calls']}"
                  f" · HTTP 尝试 {len(api)} · {execution['stop_reason']}")
        if changed:
            print(f"SQLite 变化 · {', '.join(changed)}")
        print(f"{status} · {detail} · {elapsed:.2f}s", flush=True)

    def run(self):
        self.cancelled = False
        def send(transport, request):
            return self.send(transport, request)

        with (patch.object(evidence.httpx.HTTPTransport, "handle_request", send),
              patch.object(sqlite3, "connect", self.connect)):
            for case in self.steps:
                status = self.step(case)
                if status == "BLOCKED":
                    return 3
                if status == "FAIL" or (status == "PARTIAL" and case not in {"A1", "A2", "A3"}):
                    return 1
        return 0


def summary(folder, mode, scenes, interrupted, blocked=None):
    rows = load_lines(folder / "steps.jsonl")
    by_step = {row["step"]: row for row in rows}
    ledger = evidence.ledger(folder / "budget.sqlite")
    usage = {m["number"]: m for row in rows for m in row["api"]}
    known = sum((usage.get(attempt, {}).get("usage") or {}).get("total_tokens") or 0
                for attempt, _, _ in ledger)
    known_count = sum((usage.get(attempt, {}).get("usage") or {}).get("total_tokens") is not None
                      for attempt, _, _ in ledger)
    count = sum(item["approved"] for row in rows for item in row["simulated_confirmations"])
    lines = [f"# Economy-guy · {mode.upper()} Demo", "",
             f"- 实际 API 尝试 **{len(ledger)}/{BUDGET}**。已知总 Token **{known}**（{known_count}/{len(ledger)} 次可观测）。",
             f"- 可信模拟确认 **{count}** 次。操作者为 SIMULATED_TEST_USER。",
             f"- 用户退出或中断：{'是' if interrupted else '否'}。",
             f"- Trace 降级：{'是' if any(row['trace_degraded'] for row in rows) else '否'}。",
             "", "| 场景 | 理解证据 | 实际 Handler 次数 | SQLite 最终事实 | 用户可见结果 | 结论 |",
             "| --- | --- | --- | --- | --- | --- |"]
    if blocked:
        lines[6:6] = [f"- BLOCKED · {blocked}"]
    overall = []
    for scene in scenes:
        planned = [step for phase in PHASES for step in phase if step[0] == scene]
        observed = [by_step[step] for step in planned if step in by_step]
        statuses = {row["status"] for row in observed}
        result = next((s for s in ("FAIL", "BLOCKED", "PARTIAL") if s in statuses),
                      "PASS" if len(observed) == len(planned) and statuses == {"PASS"} else "NOT_TESTED")
        overall.append(result)
        db = folder / f"{scene}.sqlite"
        final = evidence.snapshot(db)
        if scene == "A":
            facts = "C001 2026-09（金额以分计）" + json.dumps(finance_facts(db), ensure_ascii=False)
        else:
            tasks = task_facts(final)
            task_text = ", ".join(f"{task['task_id']} {task['status']}" for task in tasks) or "无"
            missing = approval.facts(db)["missing"]
            audits = sum(row["status"] == "COMMITTED" for row in final["invoice_audit"])
            facts = (f"F002 用途={safe(str(evidence.invoice(final)['purpose']))}，"
                     f"成功审计 {audits}，任务 {task_text}，缺项 {len(missing)}（{'、'.join(missing)}）")
        tools = sum(row["execution"]["actual_tool_calls"] or 0 for row in observed)
        understanding = "Mock 仅验证流程" if mode == "mock" else "见步骤工具、追问和收尾"
        details = "；".join(f"{row['step']} {row['status']}" for row in observed) or "无"
        lines.append(f"| {scene} | {understanding} | {tools} | {facts} | {details} | {result} |")
    ready = (mode == "live" and scenes == "ABC" and overall == ["PASS"] * 3 and not interrupted
             and known_count == len(ledger) and not any(row["trace_degraded"] for row in rows))
    lines += ["", f"- 后续完整三场景录屏条件：{'已具备' if ready else '待满足'}。", "", "## 步骤与副作用", ""]
    for phase in PHASES:
        for step in phase:
            if step[0] not in scenes:
                continue
            row = by_step.get(step)
            if not row:
                lines.append(f"- {step} **NOT_TESTED**")
                continue
            changes = ", ".join(row["changed_tables"]) or "无"
            lines.append(f"- {step} **{row['status']}** · {row['detail']} · PID {row['pid']}"
                         f" · 变化表 {changes} · 审计 {row['audit_increment']:+}")
    lines += ["", "## HTTP 尝试", ""]
    for attempt, case, status in ledger:
        observed = usage.get(attempt, {})
        lines.append(f"- #{attempt} {case} · {MODEL}（响应 {observed.get('response_model') or '未知'}）"
                     f" · HTTP {status or '未收到'} · {observed.get('latency_ms')} ms"
                     f" · 用量 {observed.get('usage') or '未知'} · {observed.get('failure') or '无已知故障'}")
    lines += ["", "逐 ID 工具配对、查询范围、计数、模拟确认和每步耗时见 steps.jsonl。"
               " reference_anchors 是展示会话元数据。"]
    (folder / "summary.md").write_text(safe("\n".join(lines)) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("live", "mock"), required=True)
    parser.add_argument("--profile", default="shared-flash")
    parser.add_argument("--profiles-file", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--profiles-local", type=Path, default=DEFAULT_LOCAL)
    parser.add_argument("--scenario", choices=("all", "A", "B", "C"), default="all")
    parser.add_argument("--worker", type=int, choices=range(len(PHASES)), help=argparse.SUPPRESS)
    parser.add_argument("--run", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.profile.strip():
        parser.error("--profile must name an existing profile")
    if args.run is not None and args.worker is None:
        parser.error("--run is internal")
    try:
        if args.mode == "live":
            connection(args)
    except (ValueError, OSError, RuntimeError):
        print("BLOCKED · 无法绑定已配置且有凭据的 DeepSeek Flash Profile。"
              "请核对 Profile、授权和环境变量。", flush=True)
        return 3
    if args.worker is not None:
        if args.run is None:
            parser.error("missing internal run directory")
        folder = args.run.resolve()
        db = folder / (PHASES[args.worker][0][0] + ".sqlite")
        manifest = folder / "manifest.json"
        if (folder.parent != RUN_ROOT.resolve() or not manifest.is_file()
                or json.loads(manifest.read_text(encoding="utf-8"))["mode"] != args.mode
                or not db.is_file() or db.resolve() != db or db.stat().st_nlink != 1
                or not folder.name.startswith("run-")):
            parser.error("invalid internal run directory")
        try:
            with (folder / f"phase_{args.worker}.started").open("x", encoding="utf-8") as marker:
                marker.write(str(os.getpid()))
            return Phase(folder, args, args.worker).run()
        except (Quit, KeyboardInterrupt):
            return 2
        except (OSError, ValueError, sqlite3.Error, RuntimeError):
            print("BLOCKED · 演示执行异常，已停止依赖步骤。请检查本地脱敏证据。", flush=True)
            return 3

    scenes = "ABC" if args.scenario == "all" else args.scenario
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    folder = Path(mkdtemp(prefix="run-", dir=RUN_ROOT)).resolve()
    for scene in scenes:
        evidence.new_database(folder / f"{scene}.sqlite")
    evidence.init_budget(folder / "budget.sqlite")
    evidence.save(folder / "manifest.json", dict(mode=args.mode, scenarios=scenes, budget=BUDGET,
                                               fixture_sha256=evidence.sha(evidence.PROJECT / "tests/fixtures/example.xlsx")))
    description = f"{MODEL} · HTTP 尝试上限 {BUDGET} · SDK 重试 0" if args.mode == "live" else "离线流程验证 · API 请求 0"
    print(f"Economy-guy · {args.mode.upper()} · {description}\n运行目录 · {folder}", flush=True)
    status = 0
    blocked = None
    try:
        for index, phase in enumerate(PHASES):
            scene = phase[0][0]
            if scene not in scenes:
                continue
            if index in {3, 4}:
                prior = "C2" if index == 3 else "C5"
                if not any(row["step"] == prior and row["status"] == "PASS"
                           for row in load_lines(folder / "steps.jsonl")):
                    continue
            child = subprocess.run([
                sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--mode", args.mode,
                "--profile", args.profile, "--profiles-file", str(args.profiles_file.resolve()),
                "--profiles-local", str(args.profiles_local.resolve()), "--worker", str(index),
                "--run", str(folder),
            ], check=False)
            if child.returncode not in {0, 1}:
                status = 2 if child.returncode == 2 else 3
                if status == 3:
                    blocked = f"{scene} 场景工作进程停止，未再调用模型。详见逐步证据。"
                break
            status = max(status, child.returncode)
    except KeyboardInterrupt:
        status = 2
    finally:
        summary(folder, args.mode, scenes, status == 2, blocked)
        print(f"脱敏报告 · {folder / 'summary.md'}", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
