"""Qwen snapshot checks through the installed SDK and synthetic HTTP only."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx

from app.agent import Agent
from app.model_config import ModelConnection, ProfileError, profile_data_legacy, validate_profile
from app.tui_intent import edit_turn
from tests import test_p05_sessions as sessions
from tests.helpers import DatabaseTestCaseMixin
from tests.test_agent import call


MODEL = "qwen3.8-max-0902"
BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
KEY = "synthetic-qwen-credential-only"
PRIVATE = "synthetic-private-qwen-field"
FINAL = {"content": '{"kind":"information","text":"已核对"}'}
SCOPE = {"company_id": "C001", "year": 2026, "month": 9}
QUERY = "查询 C001 2026-09 发票与银行收支。"


def connection(mode="standard", base=BASE, model=MODEL):
    profile = profile_data_legacy(base, model, "TEST_QWEN_KEY")
    return ModelConnection(validate_profile({**profile, "protocol": mode}), KEY)


def exchange(replies, *, usage=True, status=200):
    sent = []
    replies = iter(replies)

    def receive(_transport, request):
        sent.append(json.loads(request.content))
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, httpx.Response):
            return reply
        data = {"id": "synthetic", "created": 1, "object": "chat.completion", "model": MODEL, "choices": [
            {"index": 0, "finish_reason": "tool_calls" if "tool_calls" in reply else "stop",
             "message": {"role": "assistant", **reply}}]}
        if usage:
            data["usage"] = {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}
        return httpx.Response(status, json=data)

    return sent, patch.object(httpx.HTTPTransport, "handle_request", new=receive)


class QwenTests(DatabaseTestCaseMixin, unittest.TestCase):
    def agent(self, mode="standard", user="U001", **kwargs):
        self.trace = Path(self.temp.name) / "qwen.jsonl"
        return Agent(user, self.db_path, connection=connection(mode), trace_path=self.trace, **kwargs)

    def responses(self):
        return [row["data"] for line in self.trace.read_text(encoding="utf-8").splitlines()
                if (row := json.loads(line))["event"] == "api.response"]

    def test_standard_plain_and_json_replies_with_usage(self):
        a = self.agent()
        sent, wire = exchange([{"content": "普通助理回复"}, {"content": '{"kind":"general","text":"你好"}'}])
        with wire:
            self.assertNotIn("普通助理回复", a.ask("你好。"))
            self.assertEqual(a.last_response["execution"]["stop_reason"], "INVALID_RESPONSE")
            self.assertIn("你好", a.ask("再打个招呼。"))
        self.assertEqual([p["model"] for p in sent], [MODEL, MODEL])
        self.assertTrue(all(p["enable_thinking"] is False for p in sent))
        self.assertTrue(all("thinking_budget" not in p and "reasoning_effort" not in p for p in sent))
        self.assertEqual([(r["response_model"], r["http_status"], r["usage"]["total_tokens"])
                          for r in self.responses()], [(MODEL, 200, 25)] * 2)

    def test_one_and_many_tools_pair_in_consecutive_sdk_requests(self):
        a = self.agent()
        sent, wire = exchange([{"tool_calls": [call(identifier="single")]}, FINAL,
                               {"tool_calls": [call(identifier="summary"),
                                               call("list_invoices", identifier="rows")]}, FINAL])
        with wire:
            self.assertIn("9622.06", a.ask(QUERY))
            self.assertIn("9622.06", a.ask(QUERY))
        for payload, ids in ((sent[1], ["single"]), (sent[3], ["summary", "rows"])):
            messages = payload["messages"]
            last_assistant = max(i for i, m in enumerate(messages) if m.get("tool_calls"))
            self.assertEqual([c["id"] for c in messages[last_assistant]["tool_calls"]], ids)
            self.assertEqual([m["tool_call_id"] for m in messages[last_assistant+1:]], ids)
            self.assertTrue(all(json.loads(m["content"])["status"] == "SUCCESS" for m in messages[last_assistant+1:]))

    def test_thinking_preflight_drops_private_reasoning_and_missing_usage_is_unknown(self):
        a = self.agent("qwen-thinking-preflight")
        sent, wire = exchange([{"tool_calls": [call()], "reasoning_content": PRIVATE}, FINAL], usage=False)
        with wire:
            self.assertIn("9622.06", a.ask(QUERY))
        for payload in sent:
            self.assertIs(payload["enable_thinking"], True)
            self.assertIs(payload["preserve_thinking"], False)
            self.assertEqual(payload["reasoning_effort"], "low")
            self.assertNotIn("thinking_budget", payload)
            self.assertNotIn(PRIVATE, json.dumps(payload))
        self.assertNotIn(PRIVATE, self.trace.read_text(encoding="utf-8"))
        self.assertTrue(all(r["usage_status"] == "UNKNOWN" and r["usage"]["total_tokens"] is None for r in self.responses()))

    def test_allowlist_keeps_unofficial_and_other_model_payloads_generic(self):
        for base, model in ((BASE + "/other", MODEL),
                            ("https://dashscope.aliyuncs.com.example.test/compatible-mode/v1", MODEL),
                            ("https://ws-demo.cn-other.maas.aliyuncs.com/compatible-mode/v1", MODEL),
                            (BASE, "another-model")):
            with self.subTest(base=base, model=model):
                with self.assertRaises(ProfileError):
                    connection("qwen-thinking-preflight", base, model)
                a = Agent("U001", self.db_path, connection=connection("standard", base, model))
                sent, wire = exchange([FINAL])
                with wire:
                    a.ask("你好")
                self.assertNotIn("enable_thinking", sent[0])
        a = Agent("U001", self.db_path, connection=connection(
            "auto", "https://ws-demo.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/"))
        sent, wire = exchange([FINAL])
        with wire:
            a.ask("你好")
        self.assertIs(sent[0]["enable_thinking"], False)

    def test_timeout_redirect_malformed_and_credential_echo_fail_without_retry(self):
        cases = [
            (httpx.ReadTimeout("synthetic"), "TIMEOUT"),
            (httpx.Response(307, headers={"Location": "https://not-official.example.test/v1"}), "HTTP_ERROR"),
            (httpx.Response(200, json={"choices": []}), "SDK_OR_RESPONSE_ERROR"),
            ({"content": json.dumps({"kind": "general", "text": KEY})}, "SDK_OR_RESPONSE_ERROR"),
            ({"tool_calls": [call(), call()]}, "SDK_SUCCESS"),
        ]
        for reply, category in cases:
            with self.subTest(category=category):
                a = self.agent()
                sent, wire = exchange([reply])
                with wire:
                    answer = a.ask(QUERY)
                self.assertEqual(len(sent), 1)
                self.assertEqual(self.responses()[-1]["http_category"], category)
                self.assertEqual(a.last_response["execution"]["stop_reason"], "API_OR_RESPONSE_ERROR")
                self.assertIn("未确认业务成功", answer)
                self.assertFalse(a.last_response["tool_results"])
                self.assertFalse(KEY in self.trace.read_text(encoding="utf-8"))

    def test_denied_read_and_unconfirmed_update_leave_workbook_unchanged(self):
        actor = self.agent(user="U002")
        sent, wire = exchange([{"tool_calls": [call(arguments=json.dumps({**SCOPE, "company_id": "C002"}))]}])
        with wire:
            answer = actor.ask("查询 C002 2026-09 发票与银行收支。")
        self.assertEqual(len(sent), 1)
        self.assertEqual(actor.last_response["tool_results"][0][1]["status"], "DENIED")
        self.assertNotIn("9622.06", answer)
        before = self.connection.execute("SELECT purpose FROM invoices WHERE company_id='C001' AND invoice_no='F002'").fetchone()[0]
        actor = self.agent()
        edit = "把甲企业 F002 的用途改成资料打印。"
        sent, wire = exchange([{"tool_calls": [call("prepare_invoice_update", json.dumps({
            "company_id": "C001", "invoice_no": "F002", "field": "purpose", "new_value": "资料打印"}))]}])
        with wire:
            actor.ask(edit, **edit_turn(edit, None))
        self.assertEqual(len(actor.update_session.drafts), 1)
        self.assertFalse(actor.update_session.confirmations)
        self.assertEqual(actor.cancel_update()["status"], "CANCELLED")
        self.assertEqual(self.connection.execute(
            "SELECT purpose FROM invoices WHERE company_id='C001' AND invoice_no='F002'").fetchone()[0], before)


class QwenPilotTests(unittest.IsolatedAsyncioTestCase):
    async def test_official_transport_keeps_credential_and_private_text_out_of_saved_history(self):
        h = sessions.SessionTests()
        h.setUp()
        self.addCleanup(h.doCleanups)
        app = h.app()
        private = connection("qwen-thinking-preflight")
        sent, wire = exchange([{"content": '{"kind":"general","text":"您好。"}', "reasoning_content": PRIVATE}])
        with patch.object(app, "resolve_profile", return_value=private), wire:
            async with app.run_test(size=(100, 34)) as pilot:
                await h.helper.sign_in(app, pilot)
                app.mode = "live"
                await h.helper.send(app, pilot, "你好。")
                await h.helper.await_state(pilot, lambda: bool(app.records) and not app.busy)
                self.assertIn("您好", h.log(app))
                history = json.dumps(app.conversation.history(), ensure_ascii=False)
                self.assertFalse(any(marker in history or marker in h.log(app) for marker in (KEY, PRIVATE)))
        self.assertEqual(len(sent), 1)
        trace = h.trace.read_text(encoding="utf-8")
        self.assertFalse(any(marker in trace for marker in (KEY, PRIVATE)))
