"""标准库AST检查业务服务不得反向导入Agent运行层。"""
import ast
from pathlib import Path
import unittest

BUSINESS = {"database", "finance", "importer", "permissions", "queries", "rules", "updates", "stage2_schema", "stage3_schema", "tasks", "preferences", "persistence", "references"}
RUNTIME = {"agent", "tool_registry", "write_coordination", "trace", "responses", "context", "scheduler"}


def forbidden_imports(source):
    """检测显式绝对/相对导入，不声称能识别任意动态导入。"""
    failures = []
    for node in ast.walk(ast.parse(source)):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] + [alias.name for alias in node.names]
        if any(set(name.split(".")) & RUNTIME for name in names):
            failures.append(node.lineno)
    return failures


class ArchitectureTests(unittest.TestCase):
    def test_business_never_imports_runtime(self):
        app = Path(__file__).resolve().parents[1] / "app"
        for module in BUSINESS:
            with self.subTest(module=module):
                self.assertEqual(forbidden_imports((app / (module + ".py")).read_text(encoding="utf-8")), [])

    def test_checker_detects_relative_and_absolute_reverse_imports(self):
        self.assertTrue(forbidden_imports("from .agent import Agent"))
        self.assertTrue(forbidden_imports("from . import agent"))
        self.assertTrue(forbidden_imports("import app.tool_registry"))
