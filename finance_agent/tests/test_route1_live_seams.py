"""First-attempt Live seams: no-tool finish protocol and typed ordinal syntax."""
import json
import unittest

from app.context import reference_hint
from app.thinking_protocol import ThinkingProtocol, PrivateAssistant, ProtocolError


class LiveSeamTests(unittest.TestCase):
    def protocol(self):
        return ThinkingProtocol('https://api.deepseek.com', 'deepseek-flash', bind_environment=False)

    def test_actual_no_tool_protocol_binding_survives_next_tool_turn(self):
        protocol = self.protocol()
        raw = {'role': 'assistant', 'content': '{"kind":"information","text":"fixture"}',
               'reasoning_content': 'synthetic-protocol-binding-not-model-reasoning'}
        message = protocol.normalize(raw, tools=False)
        self.assertIsInstance(message, PrivateAssistant)
        self.assertNotIn('reasoning_content', json.dumps(message))
        self.assertEqual(protocol.wire([message], tools=True)[0]['reasoning_content'], raw['reasoning_content'])
        self.assertEqual(protocol.normalize(message, tools=False).reasoning, raw['reasoning_content'])

    def test_missing_private_field_is_not_fabricated(self):
        protocol = self.protocol()
        message = protocol.normalize({'role': 'assistant', 'content': 'fixture'}, tools=False)
        self.assertNotIsInstance(message, PrivateAssistant)
        with self.assertRaises(ProtocolError):
            protocol.wire([message], tools=True)

    def test_page_number_and_size_never_become_invoice_ordinal(self):
        for text in ['第一页10张', '第 2 页，每页二十张', '第十页二十张', '先给第一页10张，再说全年总张数']:
            with self.subTest(text=text):
                self.assertIsNone(reference_hint(text))

    def test_actual_ordinals_and_invalid_numbers_stay_bounded(self):
        self.assertEqual(reference_hint('查看第2张发票')['ordinal'], 2)
        self.assertEqual(reference_hint('第二十二张')['ordinal'], 22)
        self.assertIs(reference_hint('第-1张')['ordinal'], False)
        self.assertIs(reference_hint('第2.5张')['ordinal'], False)
        self.assertEqual(reference_hint('那张发票')['ordinal'], None)


if __name__ == '__main__':
    unittest.main()
