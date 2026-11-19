"""No HTTP is sent: SDK-wrapped pre-request budget refusals keep their type."""
import unittest
from unittest.mock import patch

import httpx
from openai import APIConnectionError
from app.model_config import ModelConnection, Profile
from app.model_transport import ModelRequestError, ModelTransport
from app.request_budget import BudgetExceeded
from app.thinking_protocol import PrivateAssistant, ProtocolError


class RequestBudgetTests(unittest.TestCase):
    def transport(self):
        profile = Profile('synthetic', 'global', None, 'deepseek', 'fictional', 'deepseek-flash',
                          'https://api.deepseek.com', 'UNUSED_SYNTHETIC_KEY', 'standard')
        return ModelTransport(ModelConnection(profile, 'not-a-real-key'))

    def test_sdk_wrapped_budget_guard_does_not_become_connection_error(self):
        refusal = BudgetExceeded('token_reservation', remaining_tokens=45005, reserved_tokens=52734,
                                 physical_requests=21)
        def blocked(**kwargs):
            try: raise refusal
            except BudgetExceeded as cause:
                raise APIConnectionError(request=httpx.Request('POST', 'https://api.deepseek.com/chat/completions')) from cause
        with patch('openai.OpenAI') as sdk:
            sdk.return_value.__enter__.return_value.chat.completions.create.side_effect = blocked
            transport = self.transport()
            with self.assertRaises(BudgetExceeded) as caught:
                transport([{'role': 'user', 'content': 'synthetic JSON budget check'}], [])
        self.assertIs(caught.exception, refusal)
        self.assertEqual(transport.counts(), {'attempts': 1, 'successes': 0, 'failures': 1})
        self.assertEqual(transport.last_response['error_category'], 'BUDGET_EXCEEDED')
        self.assertEqual(transport.last_response['usage_status'], 'NOT_SENT')
        self.assertIs(transport.last_response['physical_request_sent'], False)
        self.assertEqual(transport.last_response['budget']['reserved_tokens'], 52734)

    def test_error_text_does_not_determine_budget_classification(self):
        with patch('openai.OpenAI') as sdk:
            sdk.return_value.__enter__.return_value.chat.completions.create.side_effect = APIConnectionError(
                message='request_budget_exhausted is untrusted error text',
                request=httpx.Request('POST', 'https://api.deepseek.com/chat/completions'))
            transport = self.transport()
            with self.assertRaises(ModelRequestError):
                transport([{'role': 'user', 'content': 'synthetic JSON failure'}], [])
        self.assertEqual(transport.last_response['error_category'], 'CONNECTION_ERROR')

    def test_no_tool_closing_keeps_actual_thinking_tool_history(self):
        messages = [{'role': 'user', 'content': 'synthetic current request'},
            PrivateAssistant({'role': 'assistant', 'tool_calls': [{'id': 'c1', 'type': 'function',
                'function': {'name': 'get_invoice', 'arguments': '{}'}}]}, 'actual-synthetic-reasoning'),
            {'role': 'tool', 'tool_call_id': 'c1', 'content': '{"status":"SUCCESS"}'}]
        with patch('openai.OpenAI') as sdk:
            profile = Profile('synthetic', 'global', None, 'deepseek', 'fictional', 'deepseek-flash',
                              'https://api.deepseek.com', 'UNUSED_SYNTHETIC_KEY', 'auto')
            transport = ModelTransport(ModelConnection(profile, 'not-a-real-key'))
            create = sdk.return_value.__enter__.return_value.chat.completions.create
            create.return_value.choices[0].message.model_dump.return_value = {
                'role': 'assistant', 'content': '{"kind":"information","text":"synthetic"}',
                'reasoning_content': 'actual-synthetic-final-reasoning'}
            create.return_value.usage = {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}
            create.return_value.model = 'deepseek-flash'
            transport(messages, [])
            sent = create.call_args.kwargs
        self.assertNotIn('tools', sent)
        self.assertEqual(sent['messages'][1]['reasoning_content'], 'actual-synthetic-reasoning')
        self.assertEqual(sent['messages'][2]['tool_call_id'], 'c1')

    def test_no_tool_closing_does_not_fabricate_missing_model_reasoning(self):
        profile = Profile('synthetic', 'global', None, 'deepseek', 'fictional', 'deepseek-flash',
                          'https://api.deepseek.com', 'UNUSED_SYNTHETIC_KEY', 'auto')
        transport = ModelTransport(ModelConnection(profile, 'not-a-real-key'))
        history = [{'role': 'assistant', 'tool_calls': [{'id': 'c1', 'type': 'function',
            'function': {'name': 'get_invoice', 'arguments': '{}'}}]}]
        with patch('openai.OpenAI') as sdk, self.assertRaises(ProtocolError):
            transport(history, [])
        sdk.assert_not_called()


if __name__ == '__main__': unittest.main()
