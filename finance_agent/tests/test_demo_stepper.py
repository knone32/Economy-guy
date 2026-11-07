import argparse
from dataclasses import replace
import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import demo_stepper as demo


class DemoStepperTests(unittest.TestCase):
    def invoke(self, *args, keys=""):
        return subprocess.run([sys.executable, "-X", "utf8", str(SCRIPTS / "demo_stepper.py"), *args],
                              input=keys, encoding="utf-8", capture_output=True, timeout=40)

    def folder(self, result):
        match = re.search(r"^运行目录 · (.+)$", result.stdout, re.M)
        self.assertIsNotNone(match, result.stdout + result.stderr)
        return Path(match[1])

    def test_keypresses(self):
        for key, expected in ((" ", True), ("\r", True), ("q", False), ("Q", False)):
            with self.subTest(key=key):
                with patch("builtins.input", side_effect=AssertionError("waited for Enter")):
                    self.assertEqual(demo.read_key(getwch=iter([key]).__next__), expected)
        self.assertTrue(demo.read_key(getwch=iter(["\xe0", "q", " "]).__next__))
        with self.assertRaises(KeyboardInterrupt):
            demo.read_key(getwch=lambda: "\x03")
        self.assertTrue(demo.read_key(read=lambda: ""))
        self.assertFalse(demo.read_key(read=lambda: "Q"))
        with patch("builtins.input", side_effect=EOFError):
            self.assertFalse(demo.read_key(read=input))

    def test_mock_all_and_isolated_databases(self):
        work = demo.evidence.PROJECT / "data/finance.db"
        original = demo.evidence.sha(work) if work.is_file() else None
        result = self.invoke("--mode", "mock", "--scenario", "all", keys="\n" * 25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Economy-guy · MOCK", result.stdout)
        self.assertIn("Mock 提案", result.stdout)
        self.assertNotIn("实际模型 ·", result.stdout)
        self.assertIn("CURRENT_VALUE_MATCHES", result.stdout)
        folder = self.folder(result)
        steps = {row["step"]: row for row in demo.load_lines(folder / "steps.jsonl")}
        self.assertEqual(list(steps), [step for phase in demo.PHASES for step in phase])
        self.assertTrue(all(r["mode"] == "MOCK" and r["status"] == "PASS" for r in steps.values()))
        self.assertEqual(steps["A1"]["sql"], [])
        self.assertEqual(steps["B5"]["audit_increment"], 0)
        self.assertEqual(steps["B5"]["receipt"], "CURRENT_VALUE_MATCHES")
        self.assertEqual(len({steps[k]["pid"] for k in ("C2", "C3", "C6")}), 3)
        self.assertEqual(steps["C2"]["tasks"], steps["C6"]["tasks"])
        self.assertEqual([len(steps[k]["missing"]) for k in ("C3", "C5", "C6")], [5, 4, 4])
        self.assertEqual(sum(len(r["simulated_confirmations"]) for r in steps.values()), 3)
        self.assertFalse(any(r["unexpected_change"] for r in steps.values()))
        for scene, counts in (("A", (0, 0)), ("B", (1, 0)), ("C", (1, 1))):
            state = demo.evidence.snapshot(folder / f"{scene}.sqlite")
            self.assertEqual((len(state["invoice_audit"]), len(state["tasks"])), counts)
        self.assertEqual(demo.evidence.ledger(folder / "budget.sqlite"), [])
        self.assertIn("后续完整三场景录屏条件：待满足", (folder / "summary.md").read_text(encoding="utf-8"))
        self.assertEqual(demo.evidence.sha(work) if work.is_file() else None, original)

    def test_quit_at_invoice_confirmation(self):
        result = self.invoke("--mode", "mock", "--scenario", "B", keys="\n\n\nQ\n")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("SIMULATED_TEST_USER", result.stdout)
        folder = self.folder(result)
        steps = demo.load_lines(folder / "steps.jsonl")
        self.assertEqual([r["status"] for r in steps], ["PASS", "PASS", "NOT_TESTED"])
        self.assertFalse(any(r["simulated_confirmations"] for r in steps))
        state = demo.evidence.snapshot(folder / "B.sqlite")
        self.assertIsNone(demo.evidence.invoice(state)["purpose"])
        self.assertEqual(state["invoice_audit"], [])
        self.assertIn("B4 **NOT_TESTED**", (folder / "summary.md").read_text(encoding="utf-8"))

    def test_draft_checks_target_acl_fingerprint_and_replay(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "B.sqlite"
            demo.evidence.new_database(path)
            state = demo.evidence.snapshot(path)
            agent = demo.Agent("U001", path, demo.scripted_model(demo.mock_replies("B1")), mode="mock")
            agent.ask(demo.EDIT, allow_prepare=True)
            draft = demo.draft_matches(agent, state, "B1", set())
            self.assertIsNotNone(draft)
            self.assertIsNone(demo.draft_matches(agent, state, "B1", {draft.request_id}))
            for update in (dict(invoice_no="F003"), dict(new_value="其他用途"), dict(actor="U002"),
                           dict(session_id="other"), dict(turn_id="other"), dict(source_request="other")):
                with self.subTest(update=update):
                    agent.update_session.drafts[draft.request_id] = replace(draft, **update)
                    self.assertIsNone(demo.draft_matches(agent, state, "B1", set()))
            agent.update_session.drafts[draft.request_id] = draft
            with patch.object(demo.approval, "digest", return_value="invalid"):
                self.assertIsNone(demo.draft_matches(agent, state, "B1", set()))
            state["permissions"] = []
            self.assertIsNone(demo.draft_matches(agent, state, "B1", set()))

    def test_wrong_task_candidate_halts_dependent_chain(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            path = folder / "C.sqlite"
            demo.evidence.new_database(path)
            demo.evidence.init_budget(folder / "budget.sqlite")
            good = demo.mock_replies

            def replies(case):
                messages = good(case)
                if case == "C2":
                    fn = messages[0]["tool_calls"][0]["function"]
                    arguments = json.loads(fn["arguments"])
                    arguments["note"] = "自动填写用途"
                    fn["arguments"] = json.dumps(arguments)
                return messages

            with (patch.object(demo, "pause") as pause,
                  patch.object(demo, "mock_replies", side_effect=replies)):
                self.assertEqual(demo.Phase(folder, argparse.Namespace(mode="mock"), 2).run(), 1)
            self.assertEqual(pause.call_count, 2)
            state = demo.evidence.snapshot(path)
            self.assertEqual(state["tasks"], [])
            self.assertEqual(state["invoice_audit"], [])
            steps = demo.load_lines(folder / "steps.jsonl")
            self.assertFalse(steps[-1]["simulated_confirmations"][0]["approved"])
            demo.summary(folder, "mock", "C", False)
            report = (folder / "summary.md").read_text(encoding="utf-8")
            self.assertIn("C2 **FAIL**", report)
            self.assertIn("C3 **NOT_TESTED**", report)

    def test_shared_budget_is_charged_before_dispatch_and_persists(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "budget.sqlite"
            demo.evidence.init_budget(path)
            for case, (_, cap) in demo.REQUESTS.items():
                for _ in range(cap - (case == "C6")):
                    demo.evidence.mark(path, demo.reserve(path, case), 200)
            code = ("from pathlib import Path; import demo_stepper as d; import sys; "
                    "p=Path(sys.argv[1]); n=d.reserve(p,'C6'); d.evidence.mark(p,n,503)")
            proc = subprocess.run([sys.executable, "-c", code, str(path)], cwd=SCRIPTS,
                                  capture_output=True, timeout=15)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(demo.evidence.ledger(path)[-1], (24, "C6", 503))
            with self.assertRaises(RuntimeError):
                demo.reserve(path, "C6")
            self.assertEqual(len(demo.evidence.ledger(path)), 24)

    def test_live_transport_records_http_and_usage_without_network(self):
        from app.model_config import ModelConnection, profile_data_legacy, validate_profile

        http = demo.evidence.httpx
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            demo.evidence.new_database(folder / "A.sqlite")
            budget = folder / "budget.sqlite"
            demo.evidence.init_budget(budget)
            data = profile_data_legacy(demo.BASE_URL, demo.MODEL)
            data["protocol"] = "standard"
            bound = ModelConnection(validate_profile(data), "synthetic-offline-only")
            draft = demo.mock_replies("A1")[0]

            def receive(_transport, request):
                # The production SDK reached the guarded transport. No network is used.
                self.assertEqual(demo.evidence.ledger(budget), [(1, "A1", None)])
                self.assertEqual(str(request.url), demo.BASE_URL + "/chat/completions")
                return http.Response(200, json={
                    "id": "offline", "created": 1, "object": "chat.completion",
                    "model": demo.MODEL, "choices": [{"index": 0, "finish_reason": "stop",
                                                     "message": draft}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
                })

            with (patch.object(demo, "connection", return_value=bound),
                  patch.object(http.HTTPTransport, "handle_request", new=receive),
                  patch.object(demo, "pause")):
                phase = demo.Phase(folder, argparse.Namespace(mode="live"), 0)
                phase.steps = ("A1",)
                self.assertEqual(phase.run(), 0)
            row, = demo.load_lines(folder / "steps.jsonl")
            self.assertEqual(row["mode"], "LIVE")
            item, = row["api"]
            self.assertEqual((item["http_status"], item["response_model"]), (200, demo.MODEL))
            self.assertEqual(item["usage"]["total_tokens"], 18)
            self.assertIsNone(item["failure"])

    def test_live_profile_blocked_without_fallback(self):
        with TemporaryDirectory() as tmp:
            args = ["--profiles-file", str(demo.DEFAULT_TEMPLATE), "--profiles-local",
                    str(Path(tmp) / "missing.json"), "--profile", "missing-demo-profile"]
            result = self.invoke("--mode", "live", *args)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("BLOCKED", result.stdout)
        self.assertNotIn("MOCK", result.stdout)
        self.assertNotIn("运行目录", result.stdout)

    def test_local_log_redaction(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.jsonl"
            demo.log(path, {"reasoning_content": "SYNTH_PRIVATE", "message": "Cookie: one=SYNTH_COOKIE; a=hidden\n业务",
                            "usage": {"total_tokens": 19}, "invoice_no": "F002"})
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("SYNTH_", raw)
            self.assertNotIn("a=hidden", raw)
            clean, = demo.load_lines(path)
            self.assertIn("业务", clean["message"])
            self.assertEqual(clean["usage"]["total_tokens"], 19)
            self.assertEqual(clean["invoice_no"], "F002")


if __name__ == "__main__":
    unittest.main()
