import importlib.util
from pathlib import Path
import sys
import unittest
from tests.helpers import DatabaseTestCaseMixin

DEMO = Path(__file__).resolve().parents[1] / "examples" / "tool_call_demo.py"
spec = importlib.util.spec_from_file_location("tool_call_demo", DEMO)
demo = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = demo
spec.loader.exec_module(demo)


class ToolCallDemoTests(DatabaseTestCaseMixin, unittest.TestCase):
    def test_add_tool_executes(self):
        result = demo.execute_tool(demo.ToolRequest("x", "add", '{"a": 12, "b": 35}'), "U001", "ignored.db")
        self.assertEqual(result["result"], 47)

    def test_missing_parameter_is_rejected(self):
        with self.assertRaises(demo.ToolValidationError):
            demo.execute_tool(demo.ToolRequest("x", "add", '{"a": 12}'), "U001", "ignored.db")

    def test_unknown_tool_is_rejected(self):
        with self.assertRaises(demo.ToolValidationError):
            demo.execute_tool(demo.ToolRequest("x", "delete_everything", "{}"), "U001", "ignored.db")

    def test_permission_denial_is_not_bypassed(self):
        db = self.db_path
        request = demo.ToolRequest("x", "invoice_total", '{"company_id": "C002", "year": 2026, "month": 9}')
        with self.assertRaises(demo.PermissionDenied): demo.execute_tool(request, "U002", db)

    def test_tool_result_message_shape(self):
        message = demo.make_tool_result_message(demo.ToolRequest("call_1", "add", "{}"), {"ok": True, "result": 47})
        self.assertEqual(message["role"], "tool"); self.assertEqual(message["tool_call_id"], "call_1"); self.assertIn('47', message["content"])

    def test_mock_mode_runs_without_api_key(self):
        lines = []
        final = demo.run_demo("mock", "add", "帮我计算 12 加 35", "U001", "ignored.db", emit=lines.append)
        self.assertIn("MOCK", lines[0]); self.assertIn("47", "\n".join(lines)); self.assertIn("MOCK 最终回答", final)
