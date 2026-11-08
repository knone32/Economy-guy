"""P1-F regressions on isolated official fixtures and offline Textual Pilot."""
from contextlib import closing
import unittest

from textual.widgets import Input, Select

from app.agent import scripted_model
from app.model_config import load_profiles
from app.stage2_schema import open_existing
from app.tui_screens import NewUserProfile
from tests import test_p05_sessions as sessions
from tests import test_s4_br as br


YEAR = {"company_id": "C001", "year": 2026}
DIRECTORY = "list_invoice_directory"
INCOME = "list_annual_bank_income"


class AnnualTests(br.ReviewCase):
    def test_annual_directory_and_followup_use_current_bounded_rows(self):
        a = self.agent([br.call(DIRECTORY, {**YEAR, "month": 0, "page": 1}, "first"),
                        br.call(DIRECTORY, {**YEAR, "month": 0, "page": 2}, "second"), br.FINAL])
        a.ask("甲企业 2026 年所有发票")
        first, second = br.outcomes(a)
        self.assertEqual(br.tool_pairs(a), ["first", "second"])
        self.assertEqual([r["status"] for r in (first, second)], ["SUCCESS", "SUCCESS"])
        rows = [row["invoice_no"] for r in (first, second) for row in r["data"]["rows"]]
        self.assertEqual(len(set(rows)), 20)
        self.assertEqual([r["data"]["total"] for r in (first, second)], [20, 20])
        self.assertEqual(first["evidence"]["scope"], YEAR)
        with self.connection:
            self.connection.executemany(
                """INSERT INTO bank_transactions(company_id,transaction_no,transaction_date,direction,amount_cents,counterparty_name)
                   VALUES ('C001',?,'2026-01-01','收入',101,'虚构对手')""",
                [(f"P1F-{i}",) for i in range(12)])
        incomes = []
        for prompt, page in (("列出该年度银行收入流水", 1), ("再看第2页收入流水", 2)):
            a.model = scripted_model([br.call(INCOME, {**YEAR, "page": page}, f"income-{page}"), br.FINAL])
            a.ask(prompt)
            result = br.outcomes(a)[-1]
            self.assertEqual(result["evidence"]["scope"], YEAR)
            self.assertEqual(result["data"]["page"], page)
            self.assertLessEqual(len(result["data"]["rows"]), 10)
            self.assertTrue(result["data"]["rows"])
            self.assertTrue(all(row["direction"] == "收入" for row in result["data"]["rows"]))
            incomes.extend(row["transaction_no"] for row in result["data"]["rows"])
        self.assertEqual(len(incomes), len(set(incomes)))
        expected = self.connection.execute(
            "SELECT count(*) FROM bank_transactions WHERE company_id='C001' AND transaction_date LIKE '2026-%' AND direction='收入'"
        ).fetchone()[0]
        self.assertEqual(result["data"]["total"], expected)

    def test_model_can_clarify_business_object_without_reasking_known_scope(self):
        a = self.agent([{"role": "assistant", "content":
                         '{"kind":"clarification","text":"未验证自由文本","missing_fields":["company_id","year","business_object"]}'}])
        answer = a.ask("甲企业 2026 年银行收入发票")
        self.assertIn("银行收入流水还是发票", answer)
        for fragment in ("企业", "年份", "未验证自由文本"):
            self.assertNotIn(fragment, answer)
        self.assertFalse(br.outcomes(a))


    def test_scope_change_empty_and_denied_results(self):
        directory = {**YEAR, "month": 0, "page": 1}
        a = self.agent([br.call("get_finance_summary", br.SCOPE), br.FINAL,
                        br.call(DIRECTORY, directory), br.FINAL])
        a.ask("甲企业 2026 年 9 月财务汇总")
        a.ask("甲企业 2026 年所有发票")
        # A model cannot invent a month from an annual grant.
        a.model = scripted_model([br.call("check_missing_purpose", br.SCOPE)])
        a.ask("哪些用途还没填写？")
        self.assertEqual(br.outcomes(a)[-1]["status"], "SCOPE_MISMATCH")
        a.model = scripted_model([br.call("get_finance_summary", br.SCOPE)])
        a.ask("改查 2026 年第一季度")
        self.assertEqual(br.outcomes(a)[-1]["status"], "AMBIGUOUS")
        self.assertIsNone(br.outcomes(a)[-1]["data"])
        a.model = scripted_model([br.call(DIRECTORY, {**directory, "company_id": "C002", "year": 2025}), br.FINAL])
        a.ask("改查乙企业 2025 年所有发票")
        last = br.outcomes(a)[-1]
        self.assertEqual((last["status"], last["data"]["total"]), ("NO_DATA", 0))
        self.assertEqual(last["evidence"]["scope"], {"company_id": "C002", "year": 2025})
        a.model = scripted_model([br.call(DIRECTORY, {**directory, "company_id": "C002", "month": 9}), br.FINAL])
        a.ask("改查乙企业 2026 年 9 月发票")
        last = br.outcomes(a)[-1]
        self.assertEqual(last["status"], "SUCCESS")
        self.assertEqual(last["evidence"]["scope"], {"company_id": "C002", "year": 2026, "month": 9})
        self.assertIsNone(a.context.annual_focus)
        denied = self.agent([br.call(INCOME, {"company_id": "C002", "year": 2026, "page": 1})], user="U002")
        denied.ask("查乙企业 2026 年银行收入流水")
        self.assertEqual((br.outcomes(denied)[-1]["status"], br.outcomes(denied)[-1]["data"]), ("DENIED", None))

    def test_company_only_change_does_not_borrow_previous_year(self):
        directory = {**YEAR, "month": 0, "page": 1}
        a = self.agent([br.call(DIRECTORY, directory), br.FINAL])
        a.ask("甲企业 2026 年所有发票")
        a.model = scripted_model([br.call(INCOME, {**YEAR, "company_id": "C002", "page": 1})])
        a.ask("改查乙企业的银行收入流水")
        self.assertEqual(br.outcomes(a)[-1]["status"], "AMBIGUOUS")
        self.assertIsNone(a.context.annual_focus)


class PilotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.h = sessions.SessionTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    async def test_deepseek_presets_custom_provider_switch_and_cancel(self):
        h = self.h
        app = h.app()
        async with app.run_test(size=(110, 40)) as pilot:
            await h.helper.sign_in(app, pilot)
            results = []
            form = NewUserProfile("U001")
            app.push_screen(form, results.append)
            await pilot.pause()
            form.query_one("#provider", Select).value = "deepseek"
            await pilot.pause()
            preset = form.query_one("#deepseek-model", Select)
            manual = form.query_one("#model-name", Input)
            name = form.query_one("#profile-name", Input)
            name.value = "offline-p1f"
            self.assertEqual(preset.value, "deepseek-flash")
            self.assertFalse(manual.display)
            self.assertEqual(form.candidate("").model, "deepseek-flash")
            preset.value = "deepseek-v4-pro"
            await pilot.pause()
            self.assertEqual(form.candidate("").model, "deepseek-v4-pro")
            preset.value = "custom"
            await pilot.pause()
            self.assertTrue(manual.display)
            manual.value = "invalid model"
            await h.helper.press_button(app, pilot, "#save-profile")
            self.assertIn("有效的模型 ID", str(form.query_one("#profile-error").renderable))
            manual.value = "custom-example"
            form.query_one("#provider", Select).value = "openai"
            await pilot.pause()
            self.assertFalse(preset.display)
            self.assertEqual(form.candidate("").model, "custom-example")
            form.query_one("#provider", Select).value = "deepseek"
            await pilot.pause()
            self.assertEqual(preset.value, "custom")
            candidate = form.candidate("")
            self.assertEqual(candidate.model, "custom-example")
            await h.helper.press_button(app, pilot, "#cancel")
            self.assertEqual(results, [None])
            self.assertFalse((h.directory / "local.json").exists())
            edited = NewUserProfile("U001", previous=candidate)
            app.push_screen(edited)
            await pilot.pause()
            self.assertEqual(edited.query_one("#deepseek-model", Select).value, "custom")
            self.assertEqual(edited.query_one("#model-name", Input).value, "custom-example")

            await h.helper.press_button(app, pilot, "#cancel")
            saved = NewUserProfile("U001")
            app.push_screen(saved)
            await pilot.pause()
            saved.query_one("#profile-name", Input).value = "offline-v4"
            saved.query_one("#provider", Select).value = "deepseek"
            await pilot.pause()
            saved.query_one("#deepseek-model", Select).value = "deepseek-v4-pro"
            await pilot.pause()
            await h.helper.press_button(app, pilot, "#save-profile")
            await h.helper.await_state(pilot, lambda: app.screen is not saved)
            profiles, _ = load_profiles(**app.profile_options)
            self.assertEqual(profiles["offline-v4"].model, "deepseek-v4-pro")
            self.assertEqual(app.model_requests, 0)

    async def test_annual_directory_resumes_only_in_original_conversation(self):
        h = self.h
        args = {**YEAR, "month": 0, "page": 1}
        app = h.app([sessions.pilot_helpers.tool(DIRECTORY, args), sessions.pilot_helpers.FINAL])
        async with app.run_test(size=(100, 34)) as pilot:
            await h.helper.sign_in(app, pilot)
            old = app.conversation.chat
            await h.helper.send(app, pilot, "甲企业 2026 年所有发票")
            await h.helper.await_state(pilot, lambda: not app.busy and bool(app.records))
            self.assertIn("共 20 张", h.log(app))
            self.assertEqual(app.resume_focus, ("C001", 2026, 0))
            self.assertEqual(app.chat_invoice_route, ("C001", 2026, 0, 1))
        with closing(open_existing(h.book)) as db, db:
            db.execute("""INSERT INTO bank_transactions(company_id,transaction_no,transaction_date,direction,amount_cents,counterparty_name)
                          VALUES ('C001','P1F-NEW','2026-01-01','收入',123,'虚构对手')""")
        call = sessions.pilot_helpers.tool(INCOME, {**YEAR, "page": 1})
        restarted = h.app([call, sessions.pilot_helpers.FINAL, call])
        async with restarted.run_test(size=(100, 34)) as pilot:
            await h.helper.sign_in(restarted, pilot)
            self.assertEqual(restarted.conversation.chat, old)
            self.assertIsNone(restarted.agent)
            await h.helper.send(restarted, pilot, "列出银行收入流水")
            await h.helper.await_state(pilot, lambda: not restarted.busy and bool(restarted.records))
            self.assertIn("P1F-NEW", h.log(restarted))
            self.assertFalse(restarted.agent.update_session.drafts)
            self.assertFalse(restarted.agent.update_session.confirmations)
            self.assertIsNone(restarted.agent.pending_edit)
            restarted.request_new_chat()
            await h.helper.press_button(restarted, pilot, "#approve")
            self.assertNotEqual(restarted.conversation.chat, old)
            await h.helper.send(restarted, pilot, "列出银行收入流水")
            await h.helper.await_state(pilot, lambda: not restarted.busy and bool(restarted.records))
            self.assertEqual(restarted.records[-1][1][0]["status"], "AMBIGUOUS")
            self.assertNotIn("P1F-NEW", h.log(restarted))
