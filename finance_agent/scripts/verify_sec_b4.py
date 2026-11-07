"""Bounded public Live verification. Uses the production CLI and temporary fictional databases."""
import argparse
from contextlib import closing, redirect_stdout
from dataclasses import asdict, replace
from decimal import Decimal
import hashlib
import inspect
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from tempfile import mkdtemp
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "finance_agent"
sys.path.insert(0, str(PROJECT))
from app.agent import Agent, scripted_model
from app.importer import initialize_database
from app.model_config import load_profiles, resolve_connection
from app.references import migrate as references
from app.rules import SEED_RULES, import_rules
from app.stage2_schema import migrate as stage2
from app.stage3_schema import migrate as stage3
from tests.closure_approval import OLD_REQUEST_ID, OLD_FINGERPRINT, SimulatedApproval, digest, facts
import main as cli

CASES = ROOT / "docs/verification/security/S4-SEC-B4-LIVE-CASES.md"
RUN_ROOT = ROOT / "artifacts/s4_sec_b4"
PHASES = (("A1", "A2"), ("B1", "BQ", "B2"), ("C1", "C2"), ("C3", "C4", "C5"), ("C6",),
          ("P1", "P2", "P3", "P4", "P5"))
EDITS = {"B1", "B2", "C4"}
VALUE = "项目资料核对"
PREF = {"P1": ("create", "简洁", None), "P3": ("update", "条目式", "简洁"),
        "P4": ("delete", "", "条目式")}
CONNECT = sqlite3.connect


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def frozen():
    return {case: (text, int(cap)) for case, text, _, cap in re.findall(
        r"^\| (A[12]|B[12Q]|C[1-6]|P[1-5]|H2) \| (.*?) \| (.*?) \| (\d+) \|$", CASES.read_text(encoding="utf-8"), re.M)}


def snapshot(path):
    with closing(CONNECT(path.as_uri()+"?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {name: [dict(row) for row in db.execute(f"SELECT * FROM {name} ORDER BY rowid")] for name in names}


def invoice(state):
    return next(row for row in state["invoices"] if (row["company_id"], row["invoice_no"]) == ("C001", "F002"))


def new_database(path):
    initialize_database(PROJECT/"tests/fixtures/example.xlsx", path)
    stage2(path)
    stage3(path)
    references(path)
    import_rules(path, SEED_RULES, {"rule.manage"})


def init_budget(path):
    with closing(CONNECT(path)) as db, db:
        db.execute("CREATE TABLE attempts (id INTEGER PRIMARY KEY, case_id TEXT NOT NULL, status INTEGER)")


def claim(path, case, cap):
    with closing(CONNECT(path.as_uri()+"?mode=rw", uri=True)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        total, own, failed = db.execute(
            "SELECT count(*),count(CASE WHEN case_id=? THEN 1 END),count(CASE WHEN status IS NULL OR status!=200 THEN 1 END) FROM attempts",
            (case,)).fetchone()
        if total >= 30 or own >= cap or failed:
            raise RuntimeError("API ledger refused dispatch")
        return db.execute("INSERT INTO attempts(case_id) VALUES(?)", (case,)).lastrowid


def mark(path, attempt, status):
    with closing(CONNECT(path.as_uri()+"?mode=rw", uri=True)) as db, db:
        if db.execute("UPDATE attempts SET status=? WHERE id=? AND status IS NULL", (status, attempt)).rowcount != 1:
            raise RuntimeError("API ledger lost dispatch")


def ledger(path):
    with closing(CONNECT(path.as_uri()+"?mode=ro", uri=True)) as db:
        return db.execute("SELECT id,case_id,status FROM attempts ORDER BY id").fetchall()


def review(case, source, proposal, db, agent, c2, used):
    turn_id = agent.management_proposals.turn_id
    if case == "C2":
        return c2.review(proposal, db, agent.user_id, turn_id)
    request_id = proposal["request_id"]
    approved = False
    if case in PREF:
        action, value, old_value = PREF[case]
        state = snapshot(db)
        old = next((row for row in state["preferences"]
                    if (row["user_id"], row["company_id"], row["preference_key"]) == ("U001", "C001", "reply_format")), None)
        payload = dict(company_id="C001", action=action, key="reply_format", value=value)
        allowed = any(p["user_id"]=="U001" and p["company_id"]=="C001" and p["can_read"] for p in state["permissions"])
        fp = digest(["U001", "preference", action, source, turn_id, request_id, payload, old])
        approved = (agent.user_id=="U001" and allowed and proposal["domain"]=="preference"
                    and proposal["original_request"]==source and proposal["proposal"]==payload
                    and proposal["current"]==old and (old["value"] if old else None)==old_value
                    and proposal["fingerprint"]==fp and request_id not in used
                    and re.fullmatch("[0-9a-f]{32}", request_id) is not None)
    if approved:
        used.add(request_id)
    return dict(approved=approved, confirmation_source="SIMULATED_TEST_USER",
                reasons=[] if approved else ["not_exact_frozen_proposal"])


def verify_changes(case, before, after, confirmations):
    changes = {name for name in before if before[name] != after[name]}
    business = changes - {"reference_anchors"}
    approvals = [item for item in confirmations if item["approved"]]
    if not business:
        return sorted(changes), False
    if len(approvals) != 1:
        return sorted(changes), True
    approval = approvals[0]
    if case in {"B1", "C4"}:
        new = [{**row, "purpose": VALUE} if (row["company_id"], row["invoice_no"])==("C001", "F002") else row
               for row in before["invoices"]]
        expected = {k: approval[k] for k in ("request_id", "fingerprint")}
        expected.update(actor="U001", company_id="C001", invoice_no="F002", field="purpose",
                        old_value=invoice(before)["purpose"], new_value=VALUE, status="COMMITTED")
        audit = after["invoice_audit"]
        okay = (business == {"invoices", "invoice_audit"} and after["invoices"] == new
                and len(audit)==len(before["invoice_audit"])+1 and audit[:-1]==before["invoice_audit"]
                and all(audit[-1][k]==v for k,v in expected.items()))
    elif case == "C2":
        tasks = after["tasks"]
        expected = dict(user_id="U001",company_id="C001",year=2026,month=9,status="ACTIVE",task_type="missing_purpose")
        okay = (business=={"tasks"} and not before["tasks"] and len(tasks)==1
                and all(tasks[0][k]==v for k,v in expected.items())
                and json.loads(tasks[0]["context_json"])["note"]==approval["payload"]["note"])
    elif case in PREF:
        action, value, _ = PREF[case]
        prefs = after["preferences"]
        okay = business=={"preferences"} and (not prefs if action=="delete" else
               len(prefs)==1 and tuple(prefs[0][k] for k in ("user_id","company_id","preference_key","value"))
               ==("U001","C001","reply_format",value))
    else:
        okay = False
    return sorted(changes), not okay


def execute(folder, phase, profiles):
    manifest = json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
    if sha(CASES)!=manifest["cases"] or sha(Path(__file__))!=manifest["driver"]:
        raise RuntimeError("Frozen Live files changed")
    steps = PHASES[phase]
    db = folder/f"scenario_{steps[0][0]}.sqlite"
    trace = folder/f"trace_{phase}.jsonl"
    budget = folder/"budget.sqlite"
    cases = frozen()
    c2 = SimulatedApproval()
    used = {OLD_REQUEST_ID}
    agents, results, sql = [], [], []
    current = None
    halted = None
    iterator = iter(steps)
    console = io.StringIO()
    original_send = httpx.HTTPTransport.handle_request

    def send(transport, request):
        body = json.loads(request.content)
        if (current is None or str(request.url)!="https://api.deepseek.com/chat/completions"
                or request.method!="POST" or body.get("model")!="deepseek-flash"):
            raise RuntimeError("Unexpected HTTP dispatch")
        attempt = claim(budget, current["case"], cases[current["case"]][1])
        try:
            response = original_send(transport, request)
        except Exception:
            mark(budget, attempt, 0)
            raise
        mark(budget, attempt, response.status_code)
        return response

    def connect(*args, **kwargs):
        conn = CONNECT(*args, **kwargs)
        if str(args[0]).startswith(db.as_uri()):
            def observe(statement):
                if re.search(r"\bFROM (invoices|bank_transactions)\b", statement, re.I):
                    scope = re.search(r"company_id\s*=\s*'(C\d+)'", statement, re.I)
                    period = re.search(r"LIKE\s*'(\d{4}-\d{2})%'", statement, re.I)
                    sql.append([scope[1] if scope else None, period[1] if period else None])
            conn.set_trace_callback(observe)
        return conn

    def factory(*args, **kwargs):
        agent = Agent(*args, **kwargs)
        agents.append(agent)
        return agent

    def finish():
        nonlocal current, halted
        if current is None:
            return
        agent = agents[-1]
        after = snapshot(db)
        changed, unauthorized = verify_changes(current["case"], current["before"], after, current["confirmations"])
        if unauthorized:
            halted = "UNAUTHORIZED_CHANGE"
        elif any(not event["approved"] for event in current["confirmations"]):
            halted = "CONFIRMATION_REJECTED"
        response = agent.last_response or {}
        if response.get("execution", {}).get("stop_reason") in {"API_OR_RESPONSE_ERROR","PROTOCOL_ERROR"}:
            halted = halted or "API_OR_PROTOCOL_STOP"
        current.update(after=after, changed=changed, unauthorized=unauthorized, response=response,
                       receipt=agent.write_receipt, trace_id=agent.trace_id, sql=list(sql),
                       missing=facts(db)["missing"], anchor_rows=len(after["reference_anchors"]))
        results.append(current)
        current = None

    def read_input(prompt):
        nonlocal current
        agent = agents[-1]
        if prompt == "你：":
            finish()
            case = next(iterator, None)
            if halted or case is None:
                return "exit"
            text, cap = cases[case]
            agent.max_requests = cap
            agent.budget_policy = replace(agent.budget_policy, max_requests=cap)
            sql.clear()
            current = dict(case=case, pid=os.getpid(), before=snapshot(db), confirmations=[],
                           session=agent.update_session.session_id, start_drafts=len(agent.update_session.drafts),
                           start_confirmations=len(agent.update_session.confirmations))
            return ("/edit " if case in EDITS else "")+text
        case = current["case"]
        source = cases[case][0]
        if "核对原始要求及实际对象/内容" in prompt:
            frame = inspect.currentframe().f_back
            while frame is not None and frame.f_code.co_name != "confirm_long_term":
                frame = frame.f_back
            if frame is None:
                raise RuntimeError("Missing trusted CLI proposal")
            proposal = frame.f_locals["proposal"]
            decision = review(case, source, proposal, db, agent, c2, used)
            event = {k:decision[k] for k in ("approved","reasons","confirmation_source")}
            if json.dumps(proposal, ensure_ascii=False, indent=2) not in console.getvalue():
                event["approved"] = False
                event["reasons"].append("proposal_not_displayed")
            event.update(request_id=proposal["request_id"], fingerprint=proposal["fingerprint"],
                         payload=proposal["proposal"], current=proposal["current"])
        elif prompt == "最终确认：":
            session = agent.update_session
            draft = next(iter(session.drafts.values()))
            data = asdict(draft)
            state = snapshot(db)
            expected = dict(actor="U001",company_id="C001",invoice_no="F002",field="purpose",
                            new_value=VALUE,old_value=invoice(state)["purpose"],source_request=source,
                            session_id=session.session_id,turn_id=session.turn_id)
            fp = digest(data)
            shown = json.dumps(data, ensure_ascii=False, indent=2) in console.getvalue()
            approved = (case in {"B1","C4"} and len(session.drafts)==1 and not state["invoice_audit"] and shown
                        and all(data[k]==v for k,v in expected.items()) and draft.fingerprint()==fp
                        and fp!=OLD_FINGERPRINT and draft.request_id not in used
                        and re.fullmatch("[0-9a-f]{32}", draft.request_id) is not None
                        and invoice(state)["invoice_date"].startswith("2026-09")
                        and any(p["user_id"]=="U001" and p["company_id"]=="C001" and p["can_modify"] for p in state["permissions"]))
            if approved:
                used.add(draft.request_id)
            event = dict(approved=approved, confirmation_source="SIMULATED_TEST_USER",
                         request_id=draft.request_id, fingerprint=fp, payload=data)
        elif "本条是补充该修改" in prompt:
            return "新主题"
        else:
            raise RuntimeError("Unexpected trusted prompt")
        current["confirmations"].append(event)
        return "confirm "+event["request_id"] if event["approved"] else "取消"

    argv = ["main.py","--db",str(db),"--profiles-local",str(profiles),"chat","--mode","live",
            "--user","U001","--profile","shared-flash","--trace",str(trace),
            "--max-requests","3","--max-extensions","0","--max-replans","0"]
    try:
        with (patch("app.agent.Agent",side_effect=factory),patch("builtins.input",side_effect=read_input),
              patch.object(sys,"argv",argv),patch.object(httpx.HTTPTransport,"handle_request",send),
              patch.object(sqlite3,"connect",connect),redirect_stdout(console)):
            cli.main()
    finally:
        finish()
        save(folder/f"phase_{phase}.json", dict(pid=os.getpid(), halted=halted, turns=results))
        (folder/f"console_{phase}.txt").write_text(console.getvalue(),encoding="utf-8")


def h2(db):
    before = snapshot(db)
    call = {"id":"h2-denied", "type":"function", "function":{"name":"prepare_invoice_update","arguments":json.dumps(
        dict(company_id="C001",invoice_no="F002",field="purpose",new_value=VALUE))}}
    agent = Agent("U002",db,scripted_model([{"role":"assistant","tool_calls":[call]}]),mode="mock")
    agent.ask(frozen()["H2"][0], allow_prepare=True)
    tools = [(m["tool_call_id"],json.loads(m["content"])["status"]) for m in agent.messages if m["role"]=="tool"]
    return dict(passed=tools==[("h2-denied","DENIED")] and snapshot(db)==before and not agent.update_session.drafts,
                tools=tools, execution=agent.last_response["execution"])


def batch(args):
    cases = frozen()
    if set(cases)!={case for phase in PHASES for case in phase}|{"H2"} or sum(cap for _,cap in cases.values())!=30:
        raise RuntimeError("Frozen budget mismatch")
    if sha(CASES)!=args.cases_sha256:
        raise RuntimeError("Frozen cases hash mismatch")
    profile = load_profiles(local=args.profiles)[0]["shared-flash"]
    if (profile.provider,profile.model,profile.base_url)!=("deepseek","deepseek-flash","https://api.deepseek.com"):
        raise RuntimeError("Unexpected profile")
    resolve_connection("U001","shared-flash",local=args.profiles)
    RUN_ROOT.mkdir(parents=True,exist_ok=True)
    folder = Path(mkdtemp(prefix="run-",dir=RUN_ROOT))
    print(str(folder),flush=True)
    save(folder/"manifest.json",dict(cases=sha(CASES),driver=sha(Path(__file__))))
    for name in "ABCPH":
        new_database(folder/f"scenario_{name}.sqlite")
    save(folder/"h2.json",h2(folder/"scenario_H.sqlite"))
    if not json.loads((folder/"h2.json").read_text(encoding="utf-8"))["passed"]:
        raise RuntimeError("H2 failed before Live")
    budget = folder/"budget.sqlite"
    init_budget(budget)
    blocked = set()
    runs = []
    for phase, steps in enumerate(PHASES):
        group = steps[0][0]
        if group in blocked:
            continue
        process = subprocess.run([sys.executable,str(Path(__file__)),"--profiles",str(args.profiles),
                                  "--worker",str(phase),"--folder",str(folder)],capture_output=True)
        (folder/f"worker_{phase}.txt").write_bytes(process.stdout+process.stderr)
        runs.append(dict(phase=phase,exit=process.returncode))
        path = folder/f"phase_{phase}.json"
        if not path.exists() or process.returncode:
            break
        result = json.loads(path.read_text(encoding="utf-8"))
        if result["halted"] in {"UNAUTHORIZED_CHANGE","API_OR_PROTOCOL_STOP"}:
            break
        if result["halted"] or (phase==2 and not snapshot(folder/"scenario_C.sqlite")["tasks"]):
            blocked.add(group)
        if any(status!=200 for _,_,status in ledger(budget)):
            break
    save(folder/"workers.json",runs)
    print(json.dumps(dict(attempts=len(ledger(budget)),workers=runs)),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles",type=Path,required=True)
    parser.add_argument("--cases-sha256")
    parser.add_argument("--worker",type=int)
    parser.add_argument("--folder",type=Path)
    args = parser.parse_args()
    args.profiles = args.profiles.resolve()
    if args.worker is None:
        batch(args)
    else:
        folder = args.folder.resolve()
        if not folder.is_relative_to(RUN_ROOT) or not folder.name.startswith("run-"):
            raise ValueError("Use an isolated SEC-B4 run directory")
        execute(folder,args.worker,args.profiles)


if __name__ == "__main__":
    main()
