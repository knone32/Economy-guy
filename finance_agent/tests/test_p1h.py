"""P1-H isolated Profile, Qwen and Textual regressions."""
from dataclasses import asdict, replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx

from app.model_config import ProfileError, add_profile, resolve_connection, update_user_profile, visible_profiles
from app.tui_local import remember_profile_choice
from app.win_vault import profile_target
from tests import test_p05_sessions as sessions
from tests import test_qwen as qwen
from tests import test_stage4pd as profiles
from tests import test_tui_p0 as fixture


class PersonalProfileTests(unittest.TestCase):
    def test_same_name_isolated_and_global_conflict_rejected(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        template = root / "profiles.toml"
        template.write_text("profiles=[]", encoding="utf-8")
        local = root / "profiles.json"
        options = {"template": template, "local": local}
        first = profiles.profile("finance", "user", "U001", env="P1H_ONE_KEY")
        second = profiles.profile("finance", "user", "U002", env="P1H_TWO_KEY")
        add_profile(first, "U001", **options)
        legacy = resolve_connection("U001", "finance", require_key=False, **options).profile
        add_profile(second, "U002", **options)
        with patch.dict(os.environ, {"P1H_ONE_KEY": "fixture-key-one", "P1H_TWO_KEY": "fixture-key-two"}):
            one = resolve_connection("U001", "finance", **options)
            two = resolve_connection("U002", "finance", **options)
        self.assertEqual((one.profile, two.profile.owner_user_id), (legacy, "U002"))
        self.assertTrue(one.api_key != two.api_key)
        self.assertNotEqual(profile_target(one.profile, "U001"), profile_target(two.profile, "U002"))
        with self.assertRaises(ProfileError):
            two.authorize("U001")
        with self.assertRaises(ProfileError):
            add_profile(first, "U001", **options)
        with self.assertRaises(ProfileError):
            add_profile(profiles.profile("finance"), simulate_manager=True, **options)
        with self.assertRaises(ProfileError):
            add_profile(profiles.profile("alias", "user", "U002", env="P1H_ONE_KEY"), "U002", **options)
        edited = replace(one.profile, model="deepseek-v4-pro")
        with self.assertRaises(ProfileError):
            update_user_profile(one.profile, asdict(edited), "U002", **options)
        update_user_profile(one.profile, asdict(edited), "U001", **options)
        self.assertEqual(visible_profiles("U001", **options), [asdict(edited)])
        self.assertEqual(visible_profiles("U002", **options), [asdict(two.profile)])
        self.assertEqual(resolve_connection("U001", "finance", require_key=False, **options).profile, edited)
        self.assertNotIn("fixture-key-", local.read_text(encoding="utf-8"))


class WorkbenchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.h = sessions.SessionTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    async def test_qwen_keeps_verified_result_and_separates_format_from_http_failure(self):
        h = self.h
        app = h.app()
        fake = qwen.connection()
        sent, wire = qwen.exchange([
            {"tool_calls": [qwen.call()]},
            {"content": "伪造财务成功"},
            httpx.Response(503, json={"error": {"message": "offline fixture"}}),
        ])
        with patch.object(app, "resolve_profile", return_value=fake), patch.object(app, "current_key", return_value=qwen.KEY), wire:
            async with app.run_test(size=(100, 34)) as pilot:
                await h.helper.sign_in(app, pilot)
                app.mode = "live"
                await h.helper.send(app, pilot, qwen.QUERY)
                await h.helper.await_state(pilot, lambda: len(app.records) == 1 and not app.busy)
                self.assertEqual(app.records[-1][0], "EVIDENCE_RETURNED")
                self.assertIn("9622.06", h.log(app))
                self.assertIn("仅覆盖", h.log(app))
                self.assertNotIn("伪造财务成功", h.log(app))
                self.assertIs(app.last_api_ok, True)
                await h.helper.send(app, pilot, qwen.QUERY)
                await h.helper.await_state(pilot, lambda: len(app.records) == 2 and not app.busy)
                self.assertIn("HTTP 503", app.last_api_status)
        self.assertEqual(len(sent), 3)
        self.assertIn("不要附加字段", sent[1]["messages"][0]["content"])

    async def test_task_link_underlines_label_without_underlining_blank_row(self):
        from app.persistence import ManagementIntent
        from app.tasks import manage_task
        h = self.h
        result = manage_task(h.book, "U001", "C001", "create", year=2026, month=9, note="虚构待办",
                             intent=ManagementIntent("U001", "task", "可信测试"))
        app = h.app()
        async with app.run_test(size=(100, 34)) as pilot:
            await h.helper.sign_in(app, pilot)
            app.open_task(("C001", result["data"]["task"]["task_id"]))
            await h.helper.await_state(pilot, lambda: bool(app.workspace_widget("#task-body").query("#linked-finance")))
            link = app.workspace_widget("#linked-finance")
            self.assertFalse(link.rich_style.underline)
            self.assertEqual(link.size.height, 1)
            self.assertEqual([str(span.style) for span in link.render().spans].count("underline"), 1)
            app.workspace_widget("#back-tasks").focus()
            await pilot.press("tab")
            self.assertIs(app.screen.focused, link)
            await pilot.press("enter")
            await h.helper.await_state(pilot, lambda: bool(app.workspace_widget("#finance-body").query("#invoice-table")))

    async def test_chat_uses_available_width_and_reflows_after_resize(self):
        app = self.h.app()
        async with app.run_test(size=(120, 35)) as pilot:
            await self.h.helper.sign_in(app, pilot)
            log = app.workspace_widget("#chat-log")
            text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 6
            app.chat_message("Agent", text)
            app.chat_message("业务核验 / 测试", text)
            for width in (120, 100, 80, 150):
                await pilot.resize_terminal(width, 35)
                await pilot.pause()
                lines = [line.cell_length for line in log.lines]
                self.assertLessEqual(max(lines), log.scrollable_content_region.width)
                self.assertGreater(max(lines), {120: 95, 100: 74, 80: 50, 150: 95}[width])
                self.assertIn(text, "".join(line.text for line in log.lines))
                self.assertTrue(app.workspace_widget("#prompt").visible)

    async def test_legacy_saved_name_restores_only_signed_in_owners_profile(self):
        h = self.h
        initial = h.app()
        for actor, model in (("U001", "deepseek-flash"), ("U002", "deepseek-v4-pro")):
            add_profile(profiles.profile("same", "user", actor, model=model, env=f"P1H_{actor}_KEY"),
                        actor, **initial.profile_options)
        initial.recent_path = h.directory / "recent.json"
        async with initial.run_test(size=(100, 34)) as pilot:
            await h.helper.sign_in(initial, pilot)
            remember_profile_choice(initial.profile_choice_file(), "same")
            initial.logout()
            await h.helper.await_state(pilot, lambda: bool(initial.screen.query("#login-user")))
            await h.helper.sign_in(initial, pilot, "U002")
            remember_profile_choice(initial.profile_choice_file(), "same")
        reopened = h.app()
        reopened.recent_path = initial.recent_path
        async with reopened.run_test(size=(100, 34)) as pilot:
            await h.helper.sign_in(reopened, pilot)
            self.assertEqual(reopened.resolve_profile(require_key=False).profile.model, "deepseek-flash")
            reopened.logout()
            await h.helper.await_state(pilot, lambda: bool(reopened.screen.query("#login-user")))
            await h.helper.sign_in(reopened, pilot, "U002")
            selected = reopened.resolve_profile(require_key=False).profile
            self.assertEqual((selected.owner_user_id, selected.model), ("U002", "deepseek-v4-pro"))
            self.assertEqual(reopened.model_requests, 0)


class FinalEnvelopeTests(qwen.DatabaseTestCaseMixin, unittest.TestCase):
    def test_extra_fields_invalid_json_and_correct_envelope(self):
        from app.agent import Agent
        for content, stop in (
            ('{"kind":"information","text":"伪造成功","status":"COMMITTED"}', "EVIDENCE_RETURNED"),
            ('{"kind":"information","text":', "EVIDENCE_RETURNED"),
            ('{"kind":"information","text":"已核对"}', "ANSWERED"),
        ):
            with self.subTest(stop=stop, content=content):
                agent = Agent("U001", self.db_path, connection=qwen.connection())
                sent, wire = qwen.exchange([{"tool_calls": [qwen.call()]}, {"content": content}])
                with wire:
                    answer = agent.ask(qwen.QUERY)
                self.assertEqual(agent.last_response["execution"]["stop_reason"], stop)
                self.assertIn("9622.06", answer)
                self.assertNotIn("伪造成功", answer)
                self.assertEqual(agent.last_response["operation_receipt"]["status"], "NOT_SUBMITTED")
                self.assertEqual(len(sent), 2)
