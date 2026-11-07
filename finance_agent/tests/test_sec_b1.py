"""SEC-B1 regressions through the production Agent and isolated official fixture."""
from contextlib import closing
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.agent import Agent, scripted_model
from app.model_config import ModelConnection, validate_profile
from app.references import migrate as migrate_references
from app.tool_registry import REGISTRY
from tests.test_stage4p0c import CLARIFY, FINAL, SCOPE, HarnessCase, call, outcomes


DOUBLE = "查询 C001 的 2026-09 和 2025-08 发票。"


def snapshot(path):
    tables = ("invoices", "bank_transactions", "rules", "tasks", "preferences",
              "invoice_audit", "reference_anchors")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        return {table: db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in tables}


def profile(name):
    return ModelConnection(validate_profile({
        "profile_name": name, "scope": "global", "provider": "openai-compatible",
        "service_account_ref": "fixture", "model": "mock", "protocol": "standard",
        "base_url": "https://example.com/v1", "api_key_env": "TEST_SEC_B1_KEY",
    }), "fixture")


class PeriodTests(HarnessCase):
    def setUp(self):
        super().setUp()
        migrate_references(self.db_path)

    def test_crossed_period_is_paired_and_never_reaches_query(self):
        before = snapshot(self.db_path)
        batch = call("list_invoices", {**SCOPE, "month": 8}, "crossed")
        batch["tool_calls"] += call("list_invoices", SCOPE, "remaining")["tool_calls"]
        agent = self.agent([batch, FINAL])
        query = Mock(side_effect=AssertionError("Unexpected invoice query"))
        with patch.dict(REGISTRY, {"list_invoices": (query, REGISTRY["list_invoices"][1])}):
            agent.ask(DOUBLE)
        query.assert_not_called()
        results = [m for m in agent.messages if m["role"] == "tool"]
        self.assertEqual([m["tool_call_id"] for m in results], ["crossed", "remaining"])
        self.assertEqual(outcomes(agent)[0]["status"], "SCOPE_MISMATCH")
        self.assertTrue(all(result["data"] is None for result in outcomes(agent)))
        self.assertEqual(snapshot(self.db_path), before)

    def test_explicit_pairs_and_control_keep_real_empty_and_nonempty_semantics(self):
        before = snapshot(self.db_path)
        for text, year, month, status in (
            (DOUBLE, 2026, 9, "SUCCESS"),
            (DOUBLE, 2025, 8, "NO_DATA"),
            ("查询 C001 2026-08 发票", 2026, 8, "SUCCESS"),
        ):
            with self.subTest(year=year, month=month):
                agent = self.agent([call("list_invoices", {**SCOPE, "year": year, "month": month}), FINAL])
                answer = agent.ask(text)
                result = outcomes(agent)[0]
                self.assertEqual(result["status"], status)
                self.assertEqual(result["evidence"]["scope"], {**SCOPE, "year": year, "month": month})
                count = self.connection.execute(
                    "SELECT COUNT(*) FROM invoices WHERE company_id=? AND invoice_date LIKE ?",
                    ("C001", f"{year}-{month:02d}%"),
                ).fetchone()[0]
                self.assertEqual(len(result["data"]), count)
                self.assertIn(f"{year}-{month:02d}", answer)
        after = snapshot(self.db_path)
        self.assertEqual(len(after.pop("reference_anchors")) - len(before.pop("reference_anchors")), 2)
        self.assertEqual(before, after)

    def test_partial_month_requires_unique_year_and_replaces_old_pair(self):
        agent = self.agent([CLARIFY])
        agent.ask("查询 C001 2026年发票")
        agent.model = scripted_model([call("list_invoices", SCOPE), FINAL])
        agent.ask("九月")
        self.assertEqual(outcomes(agent)[-1]["status"], "SUCCESS")
        agent.model = scripted_model([call("list_invoices", SCOPE)])
        agent.ask("改成八月")
        self.assertEqual(outcomes(agent)[-1]["status"], "SCOPE_MISMATCH")
        self.assertEqual(agent.context.proof().values["periods"], [(2026, 8)])

        ambiguous = self.agent([CLARIFY])
        ambiguous.ask(DOUBLE)
        ambiguous.model = scripted_model([call("list_invoices", {**SCOPE, "month": 7})])
        answer = ambiguous.ask("改成七月")
        self.assertEqual(outcomes(ambiguous)[-1]["status"], "AMBIGUOUS")
        self.assertIn("年份", answer)

    def test_profile_switch_preserves_pair_proof_without_current_literal_check(self):
        agent = self.agent([CLARIFY], connection=profile("before"))
        agent.ask(DOUBLE)
        switched = agent.switch_model(profile("after"))
        switched.model = scripted_model([call("list_invoices", {**SCOPE, "month": 8})])
        switched.ask("继续查询刚才的范围")
        result = outcomes(switched)[0]
        self.assertEqual(result["status"], "SCOPE_MISMATCH")
        self.assertEqual(result["evidence"]["conflicting_fields"], ["year", "month"])
        self.assertIsNone(result["data"])


class CookieTraceTests(HarnessCase):
    def test_agent_jsonl_redacts_entire_cookie_line_and_preserves_observability(self):
        markers = tuple(f"fixtureB1Marker{i}" for i in range(7))
        user = (f"查询 C001 回复格式偏好。附注 cOoKiE \t: \tfirst={markers[0]}; second={markers[1]},"
                f" third={markers[2]}\r\n业务后续行甲\n"
                f"\tSET-COOKIE: auth={markers[3]}; Path=/{markers[4]}; "
                f"Expires=Wed, {markers[5]}\n业务后续行乙")
        request = call("manage_preference", {"action": "get", "company_id": "C001",
                                            "key": "reply_format", "value": ""})
        request["content"] = f"embedded Cookie: repeated={markers[6]}\n模型后续行"
        trace = self.db_path.with_suffix(".jsonl")
        usage = {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}
        agent = Agent("U001", self.db_path, mode="live", trace_path=trace,
                      connection=profile("trace-fixture"))
        with patch("openai.OpenAI") as sdk:
            create = sdk.return_value.__enter__.return_value.chat.completions.create
            create.side_effect = [
                SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    model_dump=lambda reply=reply, **_: reply))], usage=usage, model="mock")
                for reply in (request, FINAL)
            ]
            agent.ask(user)

        raw = trace.read_text(encoding="utf-8")
        events = [json.loads(line) for line in raw.splitlines()]
        self.assertTrue(all(marker not in raw for marker in markers), "synthetic value leaked")
        self.assertEqual({event["trace_id"] for event in events}, {agent.trace_id})
        self.assertTrue({"turn.started", "model_input", "model_reply", "tool_result", "turn.finished"}
                        <= {event["event"] for event in events})
        self.assertTrue(all(line in raw for line in ("业务后续行甲", "业务后续行乙", "模型后续行", "reply_format")))
        self.assertEqual([event["data"]["usage"] for event in events
                          if event["event"] == "api.response"], [usage, usage])
