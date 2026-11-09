"""Scope negotiation retains read evidence and creates no carry-over permission."""
import unittest

from app.agent import Agent, scripted_model
from app.tasks import list_tasks
from app.tui_screens import Approval
from tests import test_p05_sessions as sessions
from tests import test_tui_p0 as fixture


SCOPE = {"company_id": "C001", "year": 2026, "month": 9}
ANNUAL = "把甲企业2026年全年未填写用途的发票创建成一个待办"
MONTH = "按甲企业2026年9月创建待办"


def create(*, scope=SCOPE, id="create"):
    return fixture.tool("manage_task", {**scope, "action": "create", "task_id": "", "note": ""}, id)


def blank_page():
    return fixture.tool("list_annual_blank_purpose", {"company_id": "C001", "year": 2026, "page": 1}, "blank")


class NegotiationPilotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.h = sessions.SessionTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    async def send_finished(self, app, pilot, prompt):
        count = len(app.records)
        await self.h.helper.send(app, pilot, prompt)
        await self.h.helper.await_state(pilot, lambda: len(app.records) == count + 1 and not app.busy)

    async def test_annual_read_and_rejection_then_explicit_month_confirmation(self):
        h = self.h
        app = h.app([blank_page(), create(scope={**SCOPE, "month": 0}), create(id="vague"),
                     create(id="accepted"), fixture.FINAL])
        async with app.run_test(size=(110, 36)) as pilot:
            await h.helper.sign_in(app, pilot)
            await self.send_finished(app, pilot, ANNUAL)
            text = h.log(app)
            self.assertIn("年度用途空值", text)
            self.assertIn("共 10 张", text)
            self.assertIn("当前仅支持2026年9月用途合规检查", text)
            self.assertIn("尚未创建待办", text)
            self.assertIn("是否改为该月创建待办", text)
            self.assertNotIn("张必填用途缺失", text)
            self.assertEqual(app.records[-1][0], "SCOPE_MISMATCH")
            outcome = app.agent.last_response["tool_results"][-1][1]
            self.assertEqual(outcome["evidence"]["scope_negotiation"]["alternative_scope"], SCOPE)
            self.assertIsNone(outcome["data"])
            self.assertEqual(list_tasks(h.book, "U001", "C001")["data"], [])
            await self.send_finished(app, pilot, "好")
            self.assertEqual(app.records[-1][0], "AMBIGUOUS")
            self.assertEqual(list_tasks(h.book, "U001", "C001")["data"], [])
            await h.helper.send(app, pilot, MONTH)
            await h.helper.await_state(pilot, lambda: isinstance(app.screen, Approval))
            self.assertIn(MONTH, app.screen.body)
            self.assertNotIn("全年", app.screen.body)
            self.assertEqual(list_tasks(h.book, "U001", "C001")["data"], [])
            await h.helper.press_button(app, pilot, "#approve")
            await h.helper.await_state(pilot, lambda: not app.busy)
        task, = list_tasks(h.book, "U001", "C001")["data"]
        self.assertEqual((task["year"], task["month"], task["context"]["note"]), (2026, 9, MONTH))

    async def test_reject_switch_restart_and_cancel_do_not_inherit_permission(self):
        h = self.h
        app = h.app([create(), create(id="reject"), create(id="switched")])
        async with app.run_test(size=(110, 36)) as pilot:
            await h.helper.sign_in(app, pilot)
            original = app.conversation.chat
            await self.send_finished(app, pilot, ANNUAL)
            await self.send_finished(app, pilot, "不要改为9月创建待办")
            self.assertEqual(app.records[-1][0], "AMBIGUOUS")
            app.request_new_chat()
            await h.helper.press_button(app, pilot, "#approve")
            self.assertNotEqual(app.conversation.chat, original)
            await self.send_finished(app, pilot, "随便")
            self.assertEqual(app.records[-1][0], "AMBIGUOUS")
            app.choose_conversation(original)
            self.assertEqual(app.conversation.chat, original)
        reopened = h.app([create(id="restarted"), create(id="cancel")])
        async with reopened.run_test(size=(110, 36)) as pilot:
            await h.helper.sign_in(reopened, pilot)
            self.assertEqual(reopened.conversation.chat, original)
            await self.send_finished(reopened, pilot, "好")
            self.assertEqual(reopened.records[-1][0], "AMBIGUOUS")
            await h.helper.send(reopened, pilot, MONTH)
            await h.helper.await_state(pilot, lambda: isinstance(reopened.screen, Approval))
            await pilot.press("escape")
            await h.helper.await_state(pilot, lambda: not reopened.busy)
            self.assertEqual(reopened.records[-1][1][0]["status"], "CANCELLED")
        self.assertEqual(list_tasks(h.book, "U001", "C001")["data"], [])

    async def test_annual_read_survives_invalid_final(self):
        h = self.h
        app = h.app([blank_page(), {"role": "assistant", "content": "伪造已完成全年合规"}])
        async with app.run_test(size=(110, 36)) as pilot:
            await h.helper.sign_in(app, pilot)
            await self.send_finished(app, pilot, "查甲企业2026年全年用途为空的发票")
            self.assertEqual(app.records[-1][0], "EVIDENCE_RETURNED")
            self.assertIn("共 10 张", h.log(app))
            self.assertIn("仅覆盖", h.log(app))
            self.assertNotIn("伪造已完成", h.log(app))
        self.assertEqual(list_tasks(h.book, "U001", "C001")["data"], [])

    def test_monthly_evidence_and_alternatives_stay_company_specific(self):
        h = self.h
        for company, alias, rule in (("C001", "甲企业", "R002"), ("C002", "乙企业", "R003")):
            with self.subTest(company=company):
                scope = {**SCOPE, "company_id": company}
                check = fixture.tool("check_missing_purpose", scope, "checked")
                agent = Agent("U001", h.book, scripted_model([check, create(scope=scope)]), mode="mock",
                              management_confirmation=lambda _: self.fail("annual request must not reach confirmation"))
                answer = agent.ask(f"先检查{alias}2026年9月用途，再把全年缺用途发票创建待办", task_note_from_request=True)
                verified = agent.last_response["tool_results"][0][1]
                self.assertEqual(verified["evidence"]["rule"]["rule_id"], rule)
                self.assertIn(f"本轮已核验该月有 {verified['data']['count']} 张", answer)
                self.assertIn(f"按 {company} 2026年9月创建待办", answer)
                self.assertEqual(list_tasks(h.book, "U001", company)["data"], [])
        denied = Agent("U002", h.book, scripted_model([create()]), mode="mock")
        text = denied.ask(ANNUAL, task_note_from_request=True)
        self.assertEqual(denied.last_response["execution"]["stop_reason"], "DENIED")
        self.assertNotIn("是否改为", text)
        self.assertEqual(list_tasks(h.book, "U002", "C001")["data"], [])

    def test_annual_task_conflict_also_guides_when_model_attempts_compliance_read(self):
        h = self.h
        wrong_read = fixture.tool("check_missing_purpose", SCOPE, "wrong-month")
        agent = Agent("U001", h.book, scripted_model([wrong_read]), mode="mock")
        answer = agent.ask(ANNUAL, task_note_from_request=True)
        self.assertEqual(agent.last_response["execution"]["stop_reason"], "SCOPE_MISMATCH")
        self.assertIn("是否改为该月创建待办", answer)
        self.assertNotIn("本轮已核验该月", answer)
