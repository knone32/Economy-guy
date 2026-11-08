"""Exercise the standard provider wire contract with synthetic HTTP and real SQLite."""
import json
import unittest
from unittest.mock import patch

import httpx

from app.agent import Agent
from app.model_config import ModelConnection, profile_data_legacy, validate_profile
from tests.helpers import DatabaseTestCaseMixin
from tests.test_agent import call


class StandardProtocolTests(DatabaseTestCaseMixin, unittest.TestCase):
    base_url = "https://synthetic.example.test/v1"

    def agent(self, **limits):
        profile = profile_data_legacy(self.base_url, "synthetic-standard")
        profile["protocol"] = "standard"
        connection = ModelConnection(validate_profile(profile), "synthetic-offline-only")
        return Agent("U001", self.db_path, connection=connection, **limits)

    def exchange(self, replies):
        sent = []

        def receive(_transport, request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(str(request.url), self.base_url + "/chat/completions")
            sent.append(json.loads(request.content))
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return httpx.Response(200, json={
                "id": "synthetic", "created": 1, "object": "chat.completion",
                "model": "synthetic-standard", "choices": [
                    {"index": 0, "finish_reason": "tool_calls" if "tool_calls" in reply else "stop",
                     "message": {"role": "assistant", **reply}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            })

        return sent, patch.object(httpx.HTTPTransport, "handle_request", new=receive)

    def test_multiple_tool_ids_pair_on_standard_sdk_wire(self):
        agent = self.agent()
        final = {"content": '{"kind":"information","text":"done"}'}
        sent, transport = self.exchange(iter([
            {"tool_calls": [call(identifier="summary"), call("list_invoices", identifier="list")]},
            final,
            final,
        ]))
        with transport:
            self.assertIn("9622.06", agent.ask("查询 C001 2026-09 发票与银行收支。"))
            agent.ask("继续说明。")
        self.assertEqual(len(sent), 3)
        for payload in sent:
            self.assertNotIn("thinking", payload)
            self.assertNotIn("response_format", payload)
            self.assertTrue(all("reasoning_content" not in message for message in payload["messages"]))
        messages = sent[1]["messages"]
        tool_reply = next(message for message in messages if message.get("tool_calls"))
        results = [message for message in messages if message["role"] == "tool"]
        self.assertEqual([c["id"] for c in tool_reply["tool_calls"]], ["summary", "list"])
        self.assertEqual([r["tool_call_id"] for r in results], ["summary", "list"])
        self.assertEqual([json.loads(r["content"])["status"] for r in results], ["SUCCESS", "SUCCESS"])

    def test_timeout_has_no_retry_and_budget_stop_keeps_tool_pair(self):
        agent = self.agent()
        sent, transport = self.exchange(iter([httpx.ReadTimeout("synthetic timeout")]))
        with transport:
            answer = agent.ask("查询 C001 2026-09 发票与银行收支。")
        self.assertIn("失败", answer)
        self.assertEqual(len(sent), 1)

        agent = self.agent(max_requests=1)
        sent, transport = self.exchange(iter([{"tool_calls": [call(identifier="once")]}]))
        with transport:
            answer = agent.ask("查询 C001 2026-09 发票与银行收支。")
        self.assertEqual(len(sent), 1)
        self.assertEqual(agent.last_response["execution"]["stop_reason"], "MODEL_LIMIT")
        self.assertIn("9622.06", answer)
        results = [message for message in agent.messages if message["role"] == "tool"]
        self.assertEqual([result["tool_call_id"] for result in results], ["once"])
