"""SEC-B2 regressions using an isolated SQLite import of the official fixture."""
from contextlib import closing, redirect_stderr
from decimal import Decimal
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from openpyxl import load_workbook

from app.importer import ImportError, initialize_database
from app.queries import _money
from app.references import migrate as migrate_references
from app.tool_registry import handle_tool
from tests.helpers import EXCEL
from tests.test_sec_b1 import snapshot
from tests.test_stage4p0c import FINAL, SCOPE, HarnessCase, call, outcomes


QUERY = "查询 C001 2026-09 的金额"
PREFERENCE = {"company_id": "C001", "action": "get", "key": "format", "value": ""}


def raw_call(arguments, identifier="invalid"):
    reply = call("manage_preference", PREFERENCE, identifier)
    reply["tool_calls"][0]["function"]["arguments"] = arguments
    return reply


class AgentBoundaryTests(HarnessCase):
    def setUp(self):
        super().setUp()
        migrate_references(self.db_path)
        self.before = snapshot(self.db_path)

    def check_turn(self, agent, ids, statuses, requests, handlers):
        messages = [message for message in agent.messages if message["role"] == "tool"]
        self.assertEqual([m["tool_call_id"] for m in messages], ids)
        self.assertEqual([result["status"] for result in outcomes(agent)], statuses)
        execution = agent.last_response["execution"]
        self.assertEqual(execution["stop_reason"], "INVALID_ARGUMENTS")
        self.assertEqual(execution["model_requests"], requests)
        self.assertEqual(execution["actual_tool_calls"], handlers)
        self.assertEqual((execution["extensions"], execution["replans"]), (0, 0))
        self.assertEqual(snapshot(self.db_path), self.before)

    def test_invalid_parameter_shapes_each_receive_a_result(self):
        cases = {
            "array": "[]", "number": "42", "null": "null", "malformed": "{",
            "duplicate": '{"company_id":"C002",'+json.dumps(PREFERENCE)[1:],
            "type": json.dumps({**PREFERENCE, "value": []}),
            "escaped_unicode": json.dumps({**PREFERENCE, "key": chr(0xD800)}),
            "too_deep": "["*2000+"0"+"]"*2000,
        }
        for label, raw in cases.items():
            with self.subTest(case=label):
                agent = self.agent([raw_call(raw)])
                answer = agent.ask("查询 C001 的回复格式偏好")
                self.check_turn(agent, ["invalid"], ["INVALID_ARGUMENTS"], 1, 1)
                self.assertIn("INVALID_ARGUMENTS", answer)
                self.assertEqual(agent.execution.observed, [])

    def test_mixed_batch_pairs_executed_invalid_and_skipped_calls(self):
        reply = call("get_finance_summary", SCOPE, "good")
        reply["tool_calls"] += raw_call("[]")["tool_calls"]
        reply["tool_calls"] += call("list_invoices", SCOPE, "skipped")["tool_calls"]
        agent = self.agent([reply])
        answer = agent.ask(QUERY)
        self.check_turn(agent, ["good", "invalid", "skipped"], ["SUCCESS", "INVALID_ARGUMENTS", "DENIED"], 1, 2)
        self.assertIn("9622.06", answer)
        self.assertIn("INVALID_ARGUMENTS", answer)

    def test_invalid_later_reply_preserves_prior_read_evidence(self):
        agent = self.agent([call("get_finance_summary", SCOPE, "good"), raw_call("[]")])
        answer = agent.ask(QUERY)
        self.check_turn(agent, ["good", "invalid"], ["SUCCESS", "INVALID_ARGUMENTS"], 2, 2)
        self.assertEqual(agent.execution.progress, 1)
        self.assertEqual(len(agent.execution.seen), 2)
        self.assertIn("9622.06", answer)

    def test_isolated_surrogate_is_rejected_with_and_without_trace(self):
        trace = self.db_path.with_suffix(".jsonl")
        for content in (chr(0xD800), json.dumps({"kind": "general", "text": chr(0xD800)})):
            for path in (None, trace):
                with self.subTest(trace=path is not None, escaped=content.startswith("{")):
                    agent = self.agent([{"role": "assistant", "content": content}], trace_path=path)
                    agent.ask("你好")
                    self.assertIn(agent.execution.stop_reason, {"API_OR_RESPONSE_ERROR", "INVALID_RESPONSE"})
                    self.assertEqual(agent.execution.actual_tools, 0)
                    self.assertFalse(any(m["role"] == "assistant" and m.get("content") == content
                                         for m in agent.messages))
                    self.assertEqual(snapshot(self.db_path), self.before)
        events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sum(e["event"] == "turn.finished" for e in events), 2)

    def test_normal_unicode_trace_and_io_failure_preserve_result(self):
        text = "您好，已收到您的问题 🌱"
        reply = {"role": "assistant", "content": json.dumps({"kind": "general", "text": text}, ensure_ascii=False)}
        trace = self.db_path.with_suffix(".jsonl")
        agent = self.agent([reply], trace_path=trace)
        self.assertIn(text, agent.ask("你好 🌱"))
        events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(e["event"] == "turn.finished" and text in e["data"]["answer"] for e in events))
        self.assertFalse(agent.last_response["trace_degraded"])

        blocked = self.agent([reply], trace_path=trace / "unwritable.jsonl")
        with redirect_stderr(io.StringIO()):
            self.assertIn(text, blocked.ask("你好 🌱"))
        self.assertTrue(blocked.last_response["trace_degraded"])
        self.assertEqual(snapshot(self.db_path), self.before)

    def test_trace_encoding_failure_degrades_without_overwriting_read_result(self):
        trace = self.db_path.with_suffix(".jsonl")
        agent = self.agent([call("get_finance_summary", SCOPE), FINAL], trace_path=trace)
        with redirect_stderr(io.StringIO()):
            agent.trace("synthetic.encoding_error", {"text": chr(0xD800)})
            answer = agent.ask(QUERY)
        self.assertTrue(agent.last_response["trace_degraded"])
        self.assertEqual(outcomes(agent)[0]["status"], "SUCCESS")
        self.assertIn("9622.06", answer)
        self.assertEqual(snapshot(self.db_path), self.before)


class WorkbookBoundaryTests(unittest.TestCase):
    def workbook(self, source, duplicate=None):
        with closing(load_workbook(EXCEL, data_only=True)) as workbook:
            sheet = workbook["发票"]
            index, header = next((i, row) for i, row in enumerate(sheet.values, 1)
                                 if "发票编号" in row and "开票日期" in row)
            sample = next(row for row in sheet.values if row[:2] == ("C001", "F002"))
            if duplicate:
                column = sheet.max_column + 1
                sheet.cell(index, column, duplicate)
                sheet.cell(index+1, column, "synthetic duplicate data")
            workbook.save(source)
            return tuple(sample[header.index(field)] for field in ("用途", "备注"))

    def test_legal_cached_copy_and_original_keep_fields_and_refuse_overwrite(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            cached = folder / "cached.xlsx"
            expected = self.workbook(cached)
            for index, source in enumerate((EXCEL, cached)):
                target = folder / f"control{index}.db"
                initialize_database(source, target)
                with closing(sqlite3.connect(target.as_uri()+"?mode=ro", uri=True)) as conn:
                    self.assertEqual(conn.execute(
                        "SELECT purpose,remark,amount_cents FROM invoices WHERE company_id='C001' AND invoice_no='F002'"
                    ).fetchone(), (*expected, 80000))
                before = target.read_bytes()
                with self.assertRaises(FileExistsError):
                    initialize_database(source, target)
                self.assertEqual(target.read_bytes(), before)

    def test_duplicate_required_and_optional_headers_leave_no_partial_database(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            existing = folder / "existing.db"
            initialize_database(EXCEL, existing)
            before = existing.read_bytes()
            for index, field in enumerate(("用途", "备注", "发票编号")):
                with self.subTest(field=field):
                    source = folder / f"duplicate{index}.xlsx"
                    target = folder / f"rejected{index}.db"
                    self.workbook(source, field)
                    with self.assertRaisesRegex(ImportError, f"发票.*{field}"):
                        initialize_database(source, target)
                    self.assertFalse(target.exists())
                    self.assertEqual(list(folder.glob("finance-import-*")), [])
                    self.assertEqual(existing.read_bytes(), before)


class AmountTests(HarnessCase):
    def test_integer_cent_boundaries_match_decimal(self):
        for cents in (-2**63, -101, -100, -99, -1, 0, 1, 99, 100, 101, 2**63-1):
            with self.subTest(cents=cents):
                self.assertEqual(_money(cents), f"{Decimal(cents)/100:.2f}")

    def test_details_and_summaries_match_independent_sqlite_and_decimal(self):
        prefix = ("C001", "2026-09%")
        with self.connection:
            self.connection.execute("UPDATE invoices SET amount_cents=0 WHERE company_id=? AND invoice_date LIKE ?", prefix)
            self.connection.executemany("UPDATE invoices SET amount_cents=? WHERE company_id='C001' AND invoice_no=?",
                                        [(-101, "F002"), (1, "F003")])
            self.connection.execute("UPDATE bank_transactions SET amount_cents=-99 WHERE company_id=? AND transaction_date LIKE ? AND direction='收入'", prefix)
        args = json.dumps(SCOPE)
        for second in (1, 202):
            with self.subTest(second=second):
                with self.connection:
                    self.connection.execute("UPDATE invoices SET amount_cents=? WHERE company_id='C001' AND invoice_no='F003'", (second,))
                with closing(sqlite3.connect(self.db_path.as_uri()+"?mode=ro", uri=True)) as conn:
                    rows = dict(conn.execute("SELECT invoice_no,amount_cents FROM invoices WHERE company_id=? AND invoice_date LIKE ?", prefix))
                    bank = dict(conn.execute("SELECT direction,SUM(amount_cents) FROM bank_transactions WHERE company_id=? AND transaction_date LIKE ? GROUP BY direction", prefix))
                self.assertEqual((rows["F002"], rows["F003"]), (-101, second))
                self.assertLess(bank["收入"], 0)
                self.assertGreater(bank["支出"], 0)
                details = handle_tool("list_invoices", args, "U001", self.db_path)
                self.assertEqual(details["status"], "SUCCESS")
                self.assertEqual({r["invoice_no"]: r["amount"] for r in details["data"]},
                                 {k: f"{Decimal(v)/100:.2f}" for k, v in rows.items()})
                summary = handle_tool("get_finance_summary", args, "U001", self.db_path)
                self.assertEqual(summary["status"], "SUCCESS")
                for key, cents in (("invoice_total", sum(rows.values())), ("bank_income_total", bank["收入"]),
                                   ("bank_expense_total", bank["支出"])):
                    self.assertEqual(summary["data"][key], f"{Decimal(cents)/100:.2f}")

        with self.connection:
            self.connection.executemany("UPDATE invoices SET amount_cents=? WHERE company_id='C001' AND invoice_no=?",
                                        [(2**63-1, "F002"), (2**63-1, "F003")])
        result = handle_tool("get_finance_summary", args, "U001", self.db_path)
        self.assertEqual(result["status"], "ERROR")
        self.assertIsNone(result["data"])
