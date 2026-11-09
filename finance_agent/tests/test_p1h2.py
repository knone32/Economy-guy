"""P1-H2 regressions on isolated workbooks, profile files and synthetic HTTP."""
import json
import unittest

import httpx
from textual import events

from app.agent import Agent, scripted_model
from app.model_config import add_profile, resolve_connection, visible_profiles
from app.tasks import list_tasks
from app.tui_screens import Approval, Settings
from tests import test_p05_sessions as sessions
from tests import test_qwen as qwen
from tests import test_stage4pd as profiles
from tests import test_tui_p0 as fixture


class WorkbenchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.h = sessions.SessionTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    async def test_profile_scroll_reaches_last_entry_without_cross_account_leak(self):
        h = self.h
        app = h.app()
        options = app.profile_options
        add_profile(profiles.profile("own-0", "user", "U002", env="H2_OTHER"), "U002", **options)
        add_profile(profiles.profile("foreign-only", "user", "U002", env="H2_OTHER"), "U002", **options)
        async with app.run_test(size=(80, 24)) as pilot:
            await h.helper.sign_in(app, pilot)
            previous = 0
            for count in (3, 5, 10):
                with self.subTest(count=count):
                    for i in range(previous, count):
                        add_profile(profiles.profile(f"own-{i}", "user", "U001", env=f"H2_ONE_{i}"),
                                    "U001", **options)
                    previous = count
                    app.open_settings()
                    await h.helper.await_state(pilot, lambda: isinstance(app.screen, Settings)
                                               and bool(app.screen.query(f"#ai-profile-{count-1}")))
                    screen = app.screen
                    scroll = screen.query_one("#settings-model")
                    listing = screen.query_one("#model-list")
                    last = screen.query_one(f"#ai-profile-{count-1}")
                    self.assertEqual(len(listing.children), 2 * len(visible_profiles("U001", **options)))
                    self.assertEqual([p.profile_name for p in screen.profiles], [f"own-{i}" for i in range(count)])
                    self.assertGreaterEqual(listing.region.bottom, last.region.bottom)
                    scroll.focus()
                    for _ in range(8):
                        if scroll.region.contains(last.region.x, last.region.y):
                            break
                        await pilot.press("pagedown")
                    await h.helper.await_state(pilot, lambda: scroll.region.contains(last.region.x, last.region.y))
                    scroll.scroll_home(animate=False)
                    await h.helper.await_state(pilot, lambda: scroll.scroll_y == 0)
                    for _ in range(48):
                        if scroll.region.contains(last.region.x, last.region.y):
                            break
                        scroll.post_message(events.MouseScrollDown(scroll, 1, 1, 0, 1, 0, False, False, False))
                        await pilot.pause(0.06)
                    self.assertTrue(scroll.region.contains(last.region.x, last.region.y))
                    screen.query_one(f"#ai-profile-{count-2}").focus()
                    await pilot.press("tab")
                    self.assertIs(screen.focused, last)
                    await pilot.press("escape")
                    await h.helper.await_state(pilot, lambda: not isinstance(app.screen, Settings))
        self.assertEqual(resolve_connection("U001", "own-0", require_key=False, **options).profile.owner_user_id, "U001")
        self.assertEqual(resolve_connection("U002", "own-0", require_key=False, **options).profile.owner_user_id, "U002")

    async def test_model_note_is_replaced_before_preview_and_commit(self):
        h = self.h
        source = "把甲企业 2026 年 9 月缺用途发票记成一个待办，明天逐张核对。"
        args = {**qwen.SCOPE, "action": "create", "task_id": "", "note": "模型改写；自动修改发票"}
        app = h.app([fixture.tool("manage_task", args), fixture.FINAL])
        async with app.run_test(size=(100, 34)) as pilot:
            await h.helper.sign_in(app, pilot)
            await h.helper.send(app, pilot, source)
            await h.helper.await_state(pilot, lambda: isinstance(app.screen, Approval))
            self.assertIn(source, app.screen.body)
            self.assertNotIn(args["note"], app.screen.body)
            self.assertEqual(list_tasks(h.book, "U001", "C001")["data"], [])
            await h.helper.press_button(app, pilot, "#approve")
            await h.helper.await_state(pilot, lambda: not app.busy)
        task, = list_tasks(h.book, "U001", "C001")["data"]
        self.assertEqual(task["context"], {"note": source, "explicit_request": source})


    def test_task_create_update_and_correct_share_the_exact_confirmed_user_text(self):
        h = self.h
        args = {**qwen.SCOPE, "action": "create", "task_id": "", "note": "任意模型文本"}
        def run(request, user="U001", accepted=True):
            captured = []
            def confirm(proposal):
                captured.append(proposal)
                return accepted
            agent = Agent(user, h.book, scripted_model([fixture.tool("manage_task", args), fixture.FINAL]),
                          mode="mock", management_confirmation=confirm)
            if request == "补充这个待办":
                agent.context.begin("甲企业 2026 年 9 月", 1)
            agent.ask(request, task_note_from_request=True)
            outcome = agent.last_response["tool_results"][0][1]
            return outcome, captured

        for prompt, status in (("把甲企业 2026 年全年不合规用途记成待办", "SCOPE_MISMATCH"),
                               ("把甲企业 2026 年全年不合规用途和 9 月缺项记成待办", "SCOPE_MISMATCH"),
                               ("甲企业 2026 年 9 月怎么处理？", "AMBIGUOUS"),
                               ("甲企业 2026 年 9 月不要创建待办。", "AMBIGUOUS")):
            outcome, previews = run(prompt)
            self.assertEqual(outcome["status"], status)
            self.assertFalse(previews)
        outcome, previews = run("给甲企业 2026 年 9 月创建用途待办", user="U002")
        self.assertEqual(outcome["status"], "DENIED")
        self.assertFalse(previews)
        for action, request in (("create", "给甲企业 2026 年 9 月创建用途待办"),
                                ("update", "补充甲企业 2026 年 9 月用途待办，后续逐张核对"),
                                ("correct", "更正甲企业 2026 年 9 月用途待办，等待资料")):
            args["action"] = action
            args["note"] = request if action == "create" else "模型改写并声称无需审核"
            outcome, previews = run(request)
            self.assertEqual(outcome["status"], "SUCCESS")
            self.assertEqual(previews[0]["proposal"]["note"], request)
            self.assertEqual(previews[0]["original_request"], request)
            task, = list_tasks(h.book, "U001", "C001")["data"]
            self.assertEqual(task["context"], {"note": request, "explicit_request": request})
            args["task_id"] = task["task_id"]
        args["action"] = "update"
        outcome, previews = run("补充这个待办")
        self.assertEqual(outcome["status"], "AMBIGUOUS")
        self.assertFalse(previews)
        outcome, previews = run("补充甲企业 2026 年 9 月待办，稍后核对", user="U002")
        self.assertEqual(outcome["status"], "NOT_FOUND")
        self.assertFalse(previews)


class QwenWireTests(qwen.DatabaseTestCaseMixin, unittest.TestCase):
    def test_standard_json_object_with_tools_and_tool_results(self):
        agent = Agent("U001", self.db_path, connection=qwen.connection("standard"))
        sent, wire = qwen.exchange([{"tool_calls": [qwen.call()]}, qwen.FINAL])
        with wire:
            self.assertIn("9622.06", agent.ask(qwen.QUERY))
        self.assertEqual(agent.last_response["execution"]["stop_reason"], "ANSWERED")
        self.assertEqual(len(sent), 2)
        for request in sent:
            self.assertEqual(request["response_format"], {"type": "json_object"})
            self.assertIs(request["enable_thinking"], False)
            self.assertEqual(request["tool_choice"], "auto")
            self.assertTrue(request["tools"])
        tool_result = sent[1]["messages"][-1]
        self.assertEqual(tool_result["tool_call_id"], "a")
        self.assertEqual(json.loads(tool_result["content"])["status"], "SUCCESS")

    def test_malformed_final_and_http_failure_remain_bounded(self):
        for content in ("普通文本", '{"kind":"information"', '{"kind":"information","text":"已提交","status":"SUCCESS"}'):
            agent = Agent("U001", self.db_path, connection=qwen.connection("standard"))
            sent, wire = qwen.exchange([{"tool_calls": [qwen.call()]}, {"content": content}])
            with wire:
                answer = agent.ask(qwen.QUERY)
            self.assertEqual(agent.last_response["execution"]["stop_reason"], "EVIDENCE_RETURNED")
            self.assertIn("9622.06", answer)
            self.assertNotIn("已提交", answer)
            self.assertEqual(len(sent), 2)
        errors = [httpx.Response(code, json={"error": {"message": "fixture"}}) for code in (400, 429, 503)]
        errors += [httpx.ReadTimeout("fixture"), {"tool_calls": [qwen.call(), qwen.call()]}]
        for error in errors:
            agent = Agent("U001", self.db_path, connection=qwen.connection("standard"))
            sent, wire = qwen.exchange([error])
            with wire:
                agent.ask(qwen.QUERY)
            self.assertEqual(agent.last_response["execution"]["stop_reason"], "API_OR_RESPONSE_ERROR")
            self.assertFalse(agent.last_response["tool_results"])
            self.assertEqual(len(sent), 1)

    def test_auto_thinking_and_third_party_unchanged(self):
        for connection in (qwen.connection("auto"), qwen.connection("qwen-thinking-preflight"),
                           qwen.connection("standard", base="https://compatible.example.test/v1")):
            agent = Agent("U001", self.db_path, connection=connection)
            sent, wire = qwen.exchange([qwen.FINAL])
            with wire:
                agent.ask("你好")
            self.assertNotIn("response_format", sent[0])
