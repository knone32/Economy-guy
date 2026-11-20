"""Deterministic SDK/HTTP fixtures; no network, private reasoning logs or model spend."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx

from app.agent import Agent
from app.model_config import ModelConnection, profile_data_legacy, validate_profile
from app.model_transport import ModelTransport
from tests.helpers import DatabaseTestCaseMixin


PRIVATE = 'synthetic-private-reasoning-must-not-be-logged'
USAGE = {'prompt_tokens': 9696, 'completion_tokens': 2048, 'total_tokens': 11744,
         'completion_tokens_details': {'reasoning_tokens': 2048}}


def connection(thinking=True):
    data = profile_data_legacy('https://api.deepseek.com', 'deepseek-flash', 'SYNTHETIC_KEY')
    return ModelConnection(validate_profile({**data, 'protocol': 'auto' if thinking else 'standard'}),
                           'synthetic-not-a-real-credential')


def fixture(replies):
    replies = iter(replies)
    sent = []

    def receive(_transport, request):
        sent.append(json.loads(request.content))
        reason, content, calls, usage = next(replies)
        message = {'role': 'assistant', 'content': content, 'reasoning_content': PRIVATE}
        if calls:
            message['tool_calls'] = calls
        payload = {'id':'synthetic-truncation', 'created':1, 'object':'chat.completion',
                   'model':'deepseek-flash', 'choices':[{'index':0, 'finish_reason':reason, 'message':message}]}
        if usage is not None:
            payload['usage'] = usage
        return httpx.Response(200, json=payload)

    return sent, patch.object(httpx.HTTPTransport, 'handle_request', new=receive)


class OutputTruncationTests(DatabaseTestCaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from app.stage2_schema import migrate
        from app.rules import import_rules, SEED_RULES
        migrate(self.db_path)
        import_rules(self.db_path, SEED_RULES, {'rule.manage'})

    def agent(self, **options):
        self.trace_path = Path(self.temp.name) / 'output-truncation.jsonl'
        return Agent('U001', self.db_path, connection=connection(), trace_path=self.trace_path, **options)

    def events(self, name):
        return [event['data'] for line in self.trace_path.read_text(encoding='utf-8').splitlines()
                if (event := json.loads(line))['event'] == name]

    def test_empty_length_reports_truncation_known_usage_and_no_retry(self):
        agent = self.agent()
        sent, wire = fixture([('length', '', None, USAGE)])
        with wire:
            answer = agent.ask('请说明当前能做什么。')
        self.assertIn('截断', answer)
        self.assertIn('未形成可用回复', answer)
        self.assertIn('未依据这条截断回复执行工具或保存修改', answer)
        self.assertIn('缩小本次请求范围后重试', answer)
        self.assertNotIn('格式无效', answer)
        self.assertEqual(agent.last_response['execution']['stop_reason'], 'OUTPUT_TRUNCATED')
        self.assertFalse(agent.last_response['tool_results'])
        self.assertEqual(len(sent), 1)
        self.assertEqual(agent.transport.counts(), {'attempts':1, 'successes':0, 'failures':1})
        response, = self.events('api.response')
        self.assertEqual(response['error_category'], 'OUTPUT_TRUNCATED')
        self.assertEqual(response['finish_reason'], 'length')
        self.assertTrue(response['physical_request_sent'])
        self.assertEqual(response['http_category'], 'SDK_SUCCESS')
        self.assertEqual(response['usage_status'], 'KNOWN')
        self.assertEqual(response['usage'], {k:USAGE[k] for k in ('prompt_tokens','completion_tokens','total_tokens')})
        self.assertEqual(response['reasoning_tokens'], 2048)
        self.assertNotIn(PRIVATE, self.trace_path.read_text(encoding='utf-8'))
        self.assertFalse(any(m['role'] == 'assistant' and m.get('content') == '' for m in agent.messages))
        self.assertFalse({'max_tokens', 'max_completion_tokens'} & sent[0].keys())

    def test_length_blocks_partial_json_and_even_complete_looking_tool_calls(self):
        call = {'id':'truncated-action', 'type':'function', 'function':{'name':'change_invoice',
                'arguments':json.dumps({'company_id':'C001','invoice_no':'F002', 'field':'remark',
                                        'new_value':'核对后暂存'})}}
        for content, calls in [('{' ,None), ('{"kind":"general","text":"完成"}', [call])]:
            with self.subTest(content=content):
                agent = self.agent()
                sent, wire = fixture([('length', content, calls, USAGE)])
                with wire:
                    agent.ask('C001 的 F002 备注改为“核对后暂存”。', allow_prepare=True)
                self.assertEqual(agent.last_response['execution']['stop_reason'], 'OUTPUT_TRUNCATED')
                self.assertFalse(agent.last_response['tool_results'])
                self.assertIsNone(agent.last_response.get('invoice_change'))
                self.assertEqual(len(sent), 1)
                self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM invoice_audit').fetchone()[0], 0)

    def test_non_length_bad_json_keeps_invalid_response_classification(self):
        agent = self.agent()
        sent, wire = fixture([('stop', '{', None, USAGE)])
        with wire:
            answer = agent.ask('请说明当前能做什么。')
        self.assertEqual(agent.last_response['execution']['stop_reason'], 'INVALID_RESPONSE')
        self.assertIn('格式无效', answer)
        self.assertNotIn('截断', answer)
        self.assertTrue(self.events('api.response')[-1]['success'])
        self.assertEqual(len(sent), 1)

    def test_successful_read_survives_later_truncation_without_write(self):
        agent = self.agent()
        call = {'id':'real-read', 'type':'function', 'function':{'name':'get_finance_summary',
                'arguments':json.dumps({'company_id':'C001','year':2026,'month':9})}}
        before = [tuple(r) for r in self.connection.execute('SELECT * FROM invoices')]
        sent, wire = fixture([('tool_calls', '', [call], USAGE), ('length', '', None, USAGE)])
        with wire:
            answer = agent.ask('查询 C001 2026-09 发票与银行收支。')
        self.assertEqual(agent.last_response['execution']['stop_reason'], 'OUTPUT_TRUNCATED')
        self.assertEqual(agent.last_response['tool_results'][0][1]['status'], 'SUCCESS')
        self.assertIn('9622.06', answer)
        self.assertIn('截断', agent.last_response['chat_notice'])
        self.assertEqual(agent.last_response['operation_receipt']['status'], 'NOT_SUBMITTED')
        self.assertEqual(len(sent), 2)
        self.assertEqual(before, [tuple(r) for r in self.connection.execute('SELECT * FROM invoices')])
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM invoice_audit').fetchone()[0], 0)
        self.assertNotIn(PRIVATE, self.trace_path.read_text(encoding='utf-8'))

    def test_transport_raw_response_keeps_http_status_and_missing_usage_unknown(self):
        for thinking in (True, False):
            with self.subTest(thinking=thinking):
                transport = ModelTransport(connection(thinking))
                sent, wire = fixture([('length', None, None, None)])
                with wire, self.assertRaisesRegex(RuntimeError, '截断'):
                    transport([{'role':'user','content':'synthetic'}], [], stage='connection')
                self.assertEqual(transport.last_response['http_status'], 200)
                self.assertEqual(transport.last_response['usage_status'], 'UNKNOWN')
                self.assertIsNone(transport.last_response['usage']['total_tokens'])
                self.assertIsNone(transport.last_response['reasoning_tokens'])
                self.assertEqual(len(sent), 1)
