"""Quoted instructions must leave read-only invoice queries usable."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.agent import Agent
from app.cli_workspaces import import_workspace
from tests import test_tui_p0
from tests.test_mixed_invoice_scope import mixed_model
from tests.test_sql_invoice_selection import snapshot


class QuotedInvoiceRequestsTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "quoted-query.sqlite3"
        import_workspace(test_tui_p0.FIXTURE, self.path)

    def test_read_only_query_returns_current_values_despite_quoted_edit(self):
        calls = iter(("query", "answer"))

        def model(_messages, _tools):
            if next(calls) == "query":
                return test_tui_p0.tool("query_business_sql", {"sql": (
                    "SELECT company_id, invoice_no, invoice_date, remark FROM invoices "
                    "WHERE company_id='C002' AND invoice_no IN ('F001','F009') "
                    "AND invoice_date >= '2026-09-01' AND invoice_date < '2026-10-01' "
                    "ORDER BY invoice_no")})
            return {"role": "assistant", "content": json.dumps({
                "kind": "information", "text": "F001 的备注是部门采购，F009 未填写备注。"}, ensure_ascii=False)}

        before = snapshot(self.path)
        agent = Agent("U001", self.path, model, mode="mock")
        agent.ask("同事在消息里写「把对应发票的备注改成已复核」。我是在核对他的消息，"
                  "麻烦报一下乙企业2026年9月F001和F009账上现有的备注，账上不要动。")
        response = agent.last_response
        self.assertEqual(response["category"], "database_query")
        self.assertIn("F001", response["text"])
        self.assertIn("部门采购", response["text"])
        self.assertIn("F009", response["text"])
        self.assertNotIn("invoice_change", response)
        self.assertIsNone(agent.pending_intent)
        self.assertEqual(snapshot(self.path), before)

    def test_a_model_proposal_cannot_execute_an_instruction_inside_a_quote(self):
        before = snapshot(self.path)
        model = mixed_model(keys=("F001",), target="F001", value="已复核")
        agent = Agent("U001", self.path, model, mode="mock")
        agent.ask("同事留言「把备注改成已复核，随后通知我」。请报乙企业2026年9月"
                  "F001现有备注，账上不要动。")
        self.assertNotIn("invoice_change", agent.last_response)
        self.assertFalse(agent.update_session.drafts)
        self.assertEqual(snapshot(self.path), before)

    def test_actual_edit_can_assign_a_quoted_value_containing_edit_words(self):
        value = "先改成已复核，再归档"
        before = snapshot(self.path)
        model = mixed_model(keys=("F001",), target="F001", value=value)
        agent = Agent("U001", self.path, model, mode="mock")
        agent.ask(f"把乙企业2026年9月F001的备注改成「{value}」。")
        change = agent.last_response["invoice_change"]
        self.assertEqual((change["company_id"], change["invoice_nos"], change["field"], change["new_value"]),
                         ("C002", ("F001",), "remark", value))
        self.assertEqual(snapshot(self.path), before)

    def test_quoted_old_instruction_does_not_block_a_new_explicit_edit(self):
        before = snapshot(self.path)
        model = mixed_model(keys=("F001",), target="F001", value="本轮待核")
        agent = Agent("U001", self.path, model, mode="mock")
        agent.ask("同事说「把备注改成已复核」。本次请把乙企业2026年9月F001"
                  "的备注改成「本轮待核」。")
        change = agent.last_response["invoice_change"]
        self.assertEqual((change["invoice_nos"], change["field"], change["new_value"]),
                         (("F001",), "remark", "本轮待核"))
        self.assertEqual(snapshot(self.path), before)
