"""S4-BR incremental verification using the frozen B4 CLI observation harness."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import mkdtemp

import verify_sec_b4 as live
from app.persistence import ManagementIntent
from app.preferences import manage_preference
from app.tasks import manage_task
from tests.closure_approval import facts

CASES = live.ROOT / "docs/verification/stage4/S4-BR-CASES.md"
RUN_ROOT = live.ROOT / "artifacts/s4_br"
PHASES = (("B2",), ("C5",), ("A1", "A2"), ("P2",))
MAX_ATTEMPTS = 14


def frozen():
    return {case: (text, int(cap)) for case, text, _, cap in re.findall(
        r"^\| (B2|C5|A[12]|P2) \| (.*?) \| (.*?) \| (\d+) \|$", CASES.read_text(encoding="utf-8"), re.M)}


def claim(path, case, cap):
    """Reserve an attempt before sending, including failed HTTP attempts."""
    with closing(live.CONNECT(path.as_uri()+"?mode=rw", uri=True)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        total, own, failed = db.execute(
            "SELECT count(*),count(CASE WHEN case_id=? THEN 1 END),"
            "count(CASE WHEN status IS NULL OR status!=200 THEN 1 END) FROM attempts", (case,)).fetchone()
        if total >= MAX_ATTEMPTS or own >= cap or failed:
            raise RuntimeError("BR API ledger refused dispatch")
        return db.execute("INSERT INTO attempts(case_id) VALUES(?)", (case,)).lastrowid


def prepare_invoice(db):
    target = dict(company_id="C001", invoice_no="F002", field="purpose", new_value=live.VALUE)
    message = {"role": "assistant", "tool_calls": [{"id": "fixture-prepare", "type": "function", "function":
               {"name": "prepare_invoice_update", "arguments": json.dumps(target)}}]}
    agent = live.Agent("U001", db, live.scripted_model([message]), mode="mock")
    source = "将 C001 企业 2026 年 9 月 F002 发票的用途改为项目资料核对。"
    agent.ask(source, allow_prepare=True)
    draft, = agent.update_session.drafts.values()
    if (draft.actor, draft.company_id, draft.invoice_no, draft.field, draft.new_value, draft.source_request) != (
            "U001", "C001", "F002", "purpose", live.VALUE, source):
        raise RuntimeError("Fixture draft did not match")
    receipt = agent.commit_update(draft.request_id, draft.fingerprint())
    audit, = live.snapshot(db)["invoice_audit"]
    if (receipt["status"], receipt["readback_verified"], audit["request_id"], audit["fingerprint"]) != (
            "COMMITTED", True, draft.request_id, draft.fingerprint()):
        raise RuntimeError("Fixture historical audit did not match")


def prepare(folder):
    for scenario in "BCAP":
        live.new_database(folder/f"scenario_{scenario}.sqlite")
    db = folder/"scenario_C.sqlite"
    task = manage_task(db, "U001", "C001", "create", year=2026, month=9,
                       note="继续补齐用途", intent=ManagementIntent("U001","task","BR 可信准备夹具"))
    if task["status"] != "SUCCESS" or len(facts(db)["missing"]) != 5:
        raise RuntimeError("Fixture task did not start with five missing purposes")
    prepare_invoice(db)
    prepare_invoice(folder/"scenario_B.sqlite")
    if len(facts(db)["missing"]) != 4:
        raise RuntimeError("Fixture task did not have four missing purposes")
    out = manage_preference(folder/"scenario_P.sqlite", "U001", "C001", "create", "reply_format", "简洁",
                            ManagementIntent("U001","preference","BR 可信准备夹具"))
    if out["status"] != "SUCCESS":
        raise RuntimeError("Fixture preference was not created")


def batch(args):
    if live.sha(CASES) != args.cases_sha256 or set(frozen()) != {case for phase in PHASES for case in phase}:
        raise RuntimeError("BR cases hash mismatch")
    if sum(cap for _, cap in frozen().values()) > MAX_ATTEMPTS:
        raise RuntimeError("BR budget mismatch")
    profile = live.load_profiles(local=args.profiles)[0]["shared-flash"]
    if (profile.provider, profile.model, profile.base_url) != ("deepseek","deepseek-flash","https://api.deepseek.com"):
        raise RuntimeError("Unexpected Flash profile")
    live.resolve_connection("U001", "shared-flash", local=args.profiles)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    folder = Path(mkdtemp(prefix="run-", dir=RUN_ROOT))
    print(str(folder), flush=True)
    live.save(folder/"manifest.json", dict(cases=live.sha(CASES), driver=live.sha(Path(live.__file__)),
                                           br_driver=live.sha(Path(__file__))))
    prepare(folder)
    budget = folder/"budget.sqlite"
    live.init_budget(budget)
    workers = []
    for phase in range(len(PHASES)):
        run = subprocess.run([sys.executable, str(Path(__file__)), "--profiles", str(args.profiles),
                              "--worker", str(phase), "--folder", str(folder)], capture_output=True)
        (folder/f"worker_{phase}.txt").write_bytes(run.stdout+run.stderr)
        workers.append(dict(phase=phase, exit=run.returncode))
        path = folder/f"phase_{phase}.json"
        if run.returncode or not path.exists():
            break
        result = json.loads(path.read_text(encoding="utf-8"))
        if result["halted"] in {"UNAUTHORIZED_CHANGE", "API_OR_PROTOCOL_STOP"} or any(
                status != 200 for _, _, status in live.ledger(budget)):
            break
    live.save(folder/"workers.json",workers)
    print(json.dumps(dict(attempts=len(live.ledger(budget)),workers=workers)),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--cases-sha256")
    parser.add_argument("--worker", type=int)
    parser.add_argument("--folder", type=Path)
    args = parser.parse_args()
    args.profiles = args.profiles.resolve()
    if args.worker is None:
        batch(args)
        return
    folder = args.folder.resolve()
    if not folder.is_relative_to(RUN_ROOT) or not folder.name.startswith("run-"):
        raise RuntimeError("Use a BR temporary run folder")
    manifest = json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
    if manifest["br_driver"] != live.sha(Path(__file__)):
        raise RuntimeError("BR driver changed")
    live.CASES, live.PHASES, live.frozen, live.claim = CASES, PHASES, frozen, claim
    live.execute(folder,args.worker,args.profiles)


if __name__ == "__main__":
    main()
