"""Actual CLI subprocesses against temporary fictional SQLite and Word files."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from zipfile import ZipFile

from app.rules import resolve_rule
from app.stage2_schema import migrate
from tests.helpers import DatabaseTestCaseMixin


class MaterialPublishCLITests(DatabaseTestCaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        migrate(self.db_path)
        self.word = Path(self.temp.name) / "制度.docx"
        self.rule_file = Path(self.temp.name) / "rule.json"
        self.rule = {"rule_id":"DOC-CLI", "version":"1", "name":"CLI制度", "company_scope":"C001",
                     "effective_from":"2026-01-01", "rule_type":"purpose", "params":{"mode":"all", "threshold_cents":0}}
        self.rule_file.write_text(json.dumps(self.rule, ensure_ascii=False), encoding="utf-8-sig")

    def cli(self, *arguments, user="U001"):
        return subprocess.run([sys.executable, "-m", "app.cli_materials", "--db", str(self.db_path),
                               "--user", user, *map(str, arguments)], cwd=Path(__file__).resolve().parents[1],
                              env={**os.environ, "PYTHONIOENCODING":"utf-8"},
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=30)

    def upload(self, text="第一版制度原文", material_id=None):
        with ZipFile(self.word, "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
        arguments = ["upload", "--company", "C001", "--file", self.word]
        if material_id:
            arguments += ["--material-id", material_id]
        result = self.cli(*arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def publish(self, uploaded, *options, user="U001"):
        return self.cli("publish-rule", "--rule-file", self.rule_file, "--material-id", uploaded["material_id"],
                        "--version", uploaded["version"], "--paragraph-id", 1, *options, user=user)

    def test_upload_default_stays_inert_and_publish_without_manager_is_denied(self):
        before = [tuple(row) for row in self.connection.execute("SELECT * FROM invoices")]
        uploaded = self.upload()
        self.assertFalse(uploaded["published"])
        rejected = self.publish(uploaded)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("rule.manage", rejected.stderr)
        self.assertEqual(rejected.stdout, "")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM rules").fetchone()[0], 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM rule_management_audit").fetchone()[0], 0)
        self.assertEqual(before, [tuple(row) for row in self.connection.execute("SELECT * FROM invoices")])
        help_result = self.cli("publish-rule", "--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("--simulate-manager", help_result.stdout)
        self.assertIn("--supersedes RULE_ID RULE_VERSION", help_result.stdout)

    def test_manager_publishes_and_explicitly_supersedes_without_activating_upload(self):
        first = self.upload()
        published = self.publish(first, "--simulate-manager")
        self.assertEqual(published.returncode, 0, published.stderr)
        receipt = json.loads(published.stdout)
        self.assertEqual(receipt["status"], "SUCCESS_CHANGED")
        self.assertEqual(receipt["source"], {"material_id":first["material_id"], "version":1, "paragraph_id":1})
        second = self.upload("第二版制度原文", first["material_id"])
        self.assertFalse(second["published"])
        self.assertEqual(resolve_rule(self.connection,"U001","C001","purpose","2026-09-01").version, "1")
        self.rule.update(version="2", effective_from="2026-09-01")
        self.rule_file.write_text(json.dumps(self.rule, ensure_ascii=False), encoding="utf-8")
        updated = self.publish(second, "--simulate-manager", "--supersedes", "DOC-CLI", "1")
        self.assertEqual(updated.returncode, 0, updated.stderr)
        self.assertEqual(resolve_rule(self.connection,"U001","C001","purpose","2026-08-31").version, "1")
        self.assertEqual(resolve_rule(self.connection,"U001","C001","purpose","2026-09-01").version, "2")
        old = self.cli("open", "--material-id", first["material_id"], "--version", 1, "--paragraph-id", 1)
        self.assertEqual(old.returncode, 0, old.stderr)
        self.assertEqual(json.loads(old.stdout)["text"], "第一版制度原文")
        duplicate = self.publish(second, "--simulate-manager", "--supersedes", "DOC-CLI", "1")
        self.assertEqual(duplicate.returncode, 0, duplicate.stderr)
        self.assertEqual(json.loads(duplicate.stdout)["status"], "NO_CHANGE")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM rule_management_audit").fetchone()[0], 2)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM invoice_audit").fetchone()[0], 0)

    def test_manager_flag_does_not_bypass_private_source_or_bad_rule_content(self):
        uploaded = self.upload()
        unauthorized = self.publish(uploaded, "--simulate-manager", user="U002")
        self.assertEqual(unauthorized.returncode, 2)
        self.assertIn("不可访问", unauthorized.stderr)
        self.rule["content"] = "与参数不一致的正文"
        self.rule_file.write_text(json.dumps(self.rule, ensure_ascii=False), encoding="utf-8")
        malformed = self.publish(uploaded, "--simulate-manager")
        self.assertEqual(malformed.returncode, 2)
        self.assertIn("正文与执行参数不一致", malformed.stderr)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM rules").fetchone()[0], 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM rule_management_audit").fetchone()[0], 0)
