"""TUI regressions for bounded rendering, profile recovery and trusted focus."""
import asyncio
import shutil
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import httpx

from app.tui_screens import Approval, Settings
from tests import test_tui_p0 as fixture

SCOPE = fixture.SCOPE
PROMPT = "帮我查一下甲企业 2026 年 9 月的发票和银行收支。"


class WorkspaceUXTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.h = fixture.P0Test()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        env = patch.dict(os.environ, {"FINANCE_MODEL_PROFILE": "", "UX_TEST_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        guard = patch.object(httpx.HTTPTransport, "handle_request", side_effect=AssertionError("external HTTP disabled"))
        network = guard.start()
        self.addCleanup(guard.stop)
        self.addCleanup(network.assert_not_called)

    def app(self, replies=None, *, persist=False):
        app = self.h.app(replies)
        if persist:
            app.recent_path = self.h.directory / "recent-workbooks.json"
            app.session_path = self.h.directory / "conversations.sqlite3"
        return app

    async def send(self, app, pilot, prompt=PROMPT):
        start = len(app.records)
        await self.h.send(app, pilot, prompt)
        await self.h.await_state(pilot, lambda: len(app.records) == start + 1 and not app.busy)

    @staticmethod
    def log(app):
        return app.workspace_widget("#chat-log")

    @staticmethod
    def status(app):
        return str(app.workspace_widget("#status").renderable)

    async def test_query_cards_wrap_and_restore_original_roles(self):
        ask = {"role": "assistant", "content": '{"kind":"clarification","text":"请补充账期","missing_fields":["year","month"]}'}
        app = self.app([ask, fixture.tool("get_finance_summary", SCOPE), fixture.FINAL], persist=True)
        async with app.run_test(size=(80, 24)) as pilot:
            await self.h.sign_in(app, pilot)
            await self.send(app, pilot, "查甲企业收支。")
            await self.send(app, pilot)
            self.assert_cards(app)
            results = app.agent.last_response["tool_results"]
            self.log(app).clear()
            app.show_turn_results(results + results)
            self.assertEqual("".join(line.text for line in self.log(app).lines).count("9622.06"), 1)
        for size in ((90, 26), (120, 35)):
            reopened = self.app([], persist=True)
            async with reopened.run_test(size=size) as pilot:
                await self.h.sign_in(reopened, pilot)
                self.assert_cards(reopened)
                self.assertIn("最近可信查询焦点：甲企业（比赛模拟） / 2026-09", self.status(reopened))

    def assert_cards(self, app):
        log = self.log(app)
        shown = "\n".join(line.text for line in log.lines)
        self.assertIn("你", shown)
        self.assertIn("Agent", shown)
        self.assertIn("请提供年份和月份", shown)
        self.assertIn("业务核验 / 账期合计", shown)
        self.assertIn("╭", shown)
        self.assertIn("╰", shown)
        self.assertEqual(shown.count("9622.06"), 1)
        self.assertEqual(shown.count("R001"), 1)
        self.assertLessEqual(max(line.cell_length for line in log.lines), log.scrollable_content_region.width)

    async def test_explicit_profile_persists_across_login_and_process(self):
        self.h.configured_profile()
        app = self.app(persist=True)
        async with app.run_test(size=(100, 34)) as pilot:
            await self.h.sign_in(app, pilot)
            app.open_settings()
            await self.h.open_model_detail(app, pilot)
            await self.h.press_button(app, pilot, "#use-profile")
            await self.h.await_state(pilot, lambda: isinstance(app.screen, Settings))
            await pilot.press("escape")
            app.logout()
            await pilot.pause()
            await self.h.sign_in(app, pilot)
            self.assertEqual(app.profile, "first-ai")
            self.assertEqual(app.model_state()[0], "missing-key")
            app.logout()
            await pilot.pause()
            await self.h.sign_in(app, pilot, "U002")
            self.assertIsNone(app.profile)

        program = """
import asyncio, sys
from pathlib import Path
from unittest.mock import patch
import httpx
from app.tui import AgentWorkspace
from tests.test_tui_p0 import P0Test
async def check():
    db, template, local, recent, sessions = map(Path, sys.argv[1:])
    app = AgentWorkspace(db, template, local, recent_path=recent, session_path=sessions)
    async with app.run_test(size=(100, 34)) as pilot:
        await P0Test().sign_in(app, pilot)
        assert app.profile == 'first-ai'
        assert app.model_state()[0] == 'unverified'
        assert app.agent is None and app.model_requests == 0
with patch.object(httpx.HTTPTransport, 'handle_request', side_effect=AssertionError('network disabled')) as guard:
    asyncio.run(check())
    guard.assert_not_called()
"""
        with patch.dict(os.environ, {"UX_TEST_API_KEY": "synthetic-test-only"}):
            child = await asyncio.to_thread(subprocess.run, [
                sys.executable, "-X", "utf8", "-c", program, str(self.h.path),
                str(app.profile_options["template"]), str(self.h.local),
                str(app.recent_path), str(app.session_path),
            ], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
        self.assertEqual(child.returncode, 0, child.stderr)

        duplicate = self.h.directory / "copied.sqlite3"
        shutil.copy2(self.h.path, duplicate)
        different = self.app(persist=True)
        different.db = duplicate
        async with different.run_test(size=(100, 34)) as pilot:
            await self.h.sign_in(different, pilot)
            self.assertIsNone(different.profile)
        self.h.configured_profile("fallback")
        self.h.local.write_text(self.h.local.read_text(encoding="utf-8").replace('"first-ai"', '"removed"'), encoding="utf-8")
        reopened = self.app(persist=True)
        with patch.dict(os.environ, {"FINANCE_MODEL_PROFILE": "fallback"}):
            async with reopened.run_test(size=(100, 34)) as pilot:
                await self.h.sign_in(reopened, pilot)
                self.assertEqual(reopened.profile, "first-ai")
                self.assertIn("不存在", reopened.profile_status())
                self.assertIsNone(reopened.agent)

    async def test_recent_scope_is_distinct_and_resets_at_session_boundaries(self):
        other = {**SCOPE, "company_id": "C002", "month": 8}
        self.h.configured_profile()
        app = self.app([fixture.tool("get_finance_summary", SCOPE), fixture.FINAL,
                        fixture.tool("get_finance_summary", other), fixture.FINAL,
                        fixture.tool("get_finance_summary", SCOPE), fixture.FINAL])
        async with app.run_test(size=(90, 26)) as pilot:
            await self.h.sign_in(app, pilot)
            await self.send(app, pilot)
            self.assertIsNone(app.read_workspace)
            self.assertIn("预选只读", app.workspace_widget("#query-scope").label.plain)
            self.assertIn("最近可信查询焦点：甲企业（比赛模拟） / 2026-09", self.status(app))
            await self.send(app, pilot, "改查乙企业 2026 年 8 月收支。")
            self.assertIn("乙企业（比赛模拟） / 2026-08", self.status(app))
            self.assertNotIn("2026-09", self.status(app))
            app.read_workspace = ("C001", 2026, 9)
            app.set_model("live", "first-ai")
            self.assertIn("最近可信查询焦点：无", self.status(app))
            self.assertIn("2026-09", app.workspace_widget("#query-scope").label.plain)
            await self.send(app, pilot)
            self.assertIn("最近可信查询焦点：甲企业（比赛模拟） / 2026-09", self.status(app))
            app.request_new_chat()
            await self.h.await_state(pilot, lambda: isinstance(app.screen, Approval) and app.screen.focused)
            await pilot.press("tab", "enter")
            await self.h.await_state(pilot, lambda: app.agent is None)
            self.assertIn("最近可信查询焦点：无", self.status(app))
            self.assertIn("2026-09", app.workspace_widget("#query-scope").label.plain)
            app.logout()
            await pilot.pause()
            await self.h.sign_in(app, pilot, "U002")
            self.assertIn("最近可信查询焦点：无", self.status(app))
