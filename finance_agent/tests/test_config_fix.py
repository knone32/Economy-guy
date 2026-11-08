"""AI manager acceptance without real credentials, Windows vault writes or HTTP."""
import asyncio
from dataclasses import asdict
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import httpx
from textual.widgets import Collapsible, Input, Select, Static

from app.model_config import ProfileError, add_profile, resolve_connection, update_user_profile, visible_profiles
from app.tui_screens import Approval, NewUserProfile, Settings
from app.win_vault import profile_target
from tests import test_tui_p0 as fixture


class ConfigManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.h = fixture.P0Test()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        env = patch.dict(os.environ, {"FINANCE_MODEL_PROFILE": "", "UX_TEST_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        guard = patch.object(httpx.HTTPTransport, "handle_request", side_effect=AssertionError("HTTP disabled"))
        network = guard.start()
        self.addCleanup(guard.stop)
        self.addCleanup(network.assert_not_called)

    async def open_center(self, app, pilot):
        app.open_settings()
        await self.h.await_state(pilot, lambda: isinstance(app.screen, Settings)
                                 and bool(app.screen.query("#model-list Static")))

    async def open_form(self, app, pilot):
        await self.h.press_button(app, pilot, "#new-profile")
        await self.h.await_state(pilot, lambda: isinstance(app.screen, NewUserProfile))
        return app.screen

    async def test_provider_defaults_and_manual_fields_at_small_size(self):
        app = self.h.app()
        async with app.run_test(size=(80, 24)) as pilot:
            await self.h.sign_in(app, pilot)
            await self.open_center(app, pilot)
            for selector in ("#profile", "#key", "#key-mode"):
                self.assertFalse(app.screen.query(selector))
            action = app.screen.query_one("#new-profile")
            self.assertGreater(action.region.y, 0)
            self.assertLess(action.region.bottom, 24)
            form = await self.open_form(app, pilot)
            provider = form.query_one("#provider", Select)
            model = form.query_one("#model-name", Input)
            endpoint = form.query_one("#endpoint", Input)
            ref = form.query_one("#key-env", Input)
            self.assertTrue(form.query_one("#profile-advanced", Collapsible).collapsed)
            self.assertEqual((model.value, endpoint.value, ref.value), ("", "", ""))
            provider.value = "deepseek"
            await pilot.pause()
            self.assertEqual(endpoint.value, "https://api.deepseek.com")
            self.assertEqual(model.value, "")
            provider.value = "openai"
            await pilot.pause()
            self.assertEqual(endpoint.value, "https://api.openai.com/v1")
            model.value = "vendor-model"
            endpoint.value = "https://custom.example/v1"
            ref.value = "CUSTOM_KEY_REFERENCE"
            provider.value = "openai-compatible"
            await pilot.pause()
            self.assertEqual((model.value, endpoint.value, ref.value),
                             ("vendor-model", "https://custom.example/v1", "CUSTOM_KEY_REFERENCE"))

    async def test_save_without_key_reselect_edit_relogin_and_fresh_process(self):
        app = self.h.app()
        async with app.run_test(size=(110, 38)) as pilot:
            await self.h.sign_in(app, pilot)
            await self.open_center(app, pilot)
            form = await self.open_form(app, pilot)
            form.query_one("#profile-name", Input).value = "my-finance"
            form.query_one("#model-name", Input).value = "model-abc"
            form.query_one("#endpoint", Input).value = "https://vendor.example/v1"
            await self.h.press_button(app, pilot, "#save-profile")
            await self.h.await_state(pilot, lambda: isinstance(app.screen, Settings))
            self.assertEqual(app.profile, "my-finance")
            self.assertEqual(app.model_state()[0], "missing-key")
            await pilot.press("escape")
            await self.h.await_state(pilot, lambda: not isinstance(app.screen, Settings))
            await self.open_center(app, pilot)
            await self.h.open_model_detail(app, pilot)
            await self.h.press_button(app, pilot, "#edit-profile")
            await self.h.await_state(pilot, lambda: isinstance(app.screen, NewUserProfile))
            app.screen.query_one("#model-name", Input).value = "model-xyz"
            await self.h.press_button(app, pilot, "#save-profile")
            await self.h.await_state(pilot, lambda: isinstance(app.screen, Settings))
            self.assertEqual(app.resolve_profile(require_key=False).profile.model, "model-xyz")
            await self.h.open_model_detail(app, pilot)
            await self.h.enter_model_key(app, pilot, "synthetic-session-key")
            await self.h.await_state(pilot, lambda: isinstance(app.screen, Settings))
            self.assertEqual(app.model_state()[0], "unverified")
            self.assertNotIn("synthetic-session-key", self.h.local.read_text(encoding="utf-8"))
            await pilot.press("escape")
            app.logout()
            await pilot.pause()
            await self.h.sign_in(app, pilot, "U002")
            await self.open_center(app, pilot)
            self.assertFalse(app.screen.query("#ai-profile-0"))
            self.assertEqual(app.session_keys, {})
            self.assertEqual(app.model_state()[0], "unconfigured")
            await pilot.press("escape")
            app.logout()
            await pilot.pause()
            await self.h.sign_in(app, pilot)
            await self.open_center(app, pilot)
            await self.h.open_model_detail(app, pilot)
            await self.h.press_button(app, pilot, "#use-profile")
            await self.h.await_state(pilot, lambda: app.profile == "my-finance")
            self.assertEqual(app.model_state()[0], "missing-key")

        program = """
import asyncio, sys
from pathlib import Path
from unittest.mock import patch
import httpx
from app.tui import AgentWorkspace
from app.tui_screens import Settings
from tests.test_tui_p0 import P0Test
async def check():
    app = AgentWorkspace(*map(Path, sys.argv[1:]))
    h = P0Test()
    async with app.run_test(size=(100, 36)) as pilot:
        await h.sign_in(app, pilot)
        app.open_settings()
        await h.open_model_detail(app, pilot)
        await h.press_button(app, pilot, '#use-profile')
        await h.await_state(pilot, lambda: isinstance(app.screen, Settings))
        assert app.profile == 'my-finance'
        assert app.resolve_profile(require_key=False).profile.model == 'model-xyz'
        assert app.model_state()[0] == 'missing-key'
with patch.object(httpx.HTTPTransport, 'handle_request', side_effect=AssertionError('network disabled')) as guard:
    asyncio.run(check())
    guard.assert_not_called()
"""
        run = await asyncio.to_thread(subprocess.run, [
            sys.executable, "-X", "utf8", "-c", program, str(self.h.path),
            str(app.profile_options["template"]), str(self.h.local),
        ], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)

    async def test_corrupt_duplicate_unsafe_and_missing_model_are_explained(self):
        self.h.configured_profile()
        app = self.h.app()
        original = self.h.local.read_bytes()
        async with app.run_test(size=(110, 38)) as pilot:
            await self.h.sign_in(app, pilot)
            await self.open_center(app, pilot)
            form = await self.open_form(app, pilot)
            form.query_one("#profile-name", Input).value = "first-ai"
            form.query_one("#endpoint", Input).value = "http://localhost/v1"
            await self.h.press_button(app, pilot, "#save-profile")
            error = form.query_one("#profile-error", Static)
            self.assertIn("模型 ID", str(error.renderable))
            form.query_one("#model-name", Input).value = "vendor-model"
            await self.h.press_button(app, pilot, "#save-profile")
            self.assertIn("URL不安全", str(error.renderable))
            form.query_one("#endpoint", Input).value = "https://vendor.example/v1"
            await self.h.press_button(app, pilot, "#save-profile")
            self.assertIn("同名", str(error.renderable))
            self.assertEqual(self.h.local.read_bytes(), original)
            await pilot.press("escape", "escape")
            await self.h.await_state(pilot, lambda: not isinstance(app.screen, Settings))
            self.h.local.write_text("{broken", encoding="utf-8")
            await self.open_center(app, pilot)
            self.assertIn("无法读取 AI 配置", str(app.screen.query_one("#model-list Static").renderable))
            self.assertEqual(self.h.local.read_text(encoding="utf-8"), "{broken")

    def test_personal_edit_cannot_overwrite_stale_or_shared_profile(self):
        self.h.configured_profile()
        app = self.h.app()
        opts = app.profile_options
        old = resolve_connection("U001", "first-ai", require_key=False, **opts).profile
        data = asdict(old)
        with self.assertRaises(ProfileError):
            update_user_profile(old, data, "U002", **opts)
        with self.assertRaises(ProfileError):
            update_user_profile(old, {**data, "base_url": "https://vendor.example/v1"}, "U001", **opts)
        with patch("app.model_config.os.replace", side_effect=OSError("fault")):
            before = self.h.local.read_bytes()
            with self.assertRaises(ProfileError):
                update_user_profile(old, {**data, "model": "first-change"}, "U001", **opts)
            self.assertEqual(self.h.local.read_bytes(), before)
        update_user_profile(old, {**data, "model": "first-change"}, "U001", **opts)
        with self.assertRaises(ProfileError):
            update_user_profile(old, {**data, "model": "stale"}, "U001", **opts)
        shared = {**data, "profile_name": "shared", "scope": "global", "owner_user_id": None}
        add_profile(shared, simulate_manager=True, **opts)
        glob = resolve_connection("U002", "shared", require_key=False, **opts).profile
        self.assertNotEqual(profile_target(glob, "U001"), profile_target(glob, "U002"))
        self.assertEqual(profile_target(old, "U001"), profile_target(old))
        with self.assertRaises(ProfileError):
            update_user_profile(glob, shared, "U001", **opts)
        self.assertEqual([p["profile_name"] for p in visible_profiles("U002", **opts)], ["shared"])
