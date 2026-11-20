"""Temporary SQLite and synthetic Word evidence, without paid model calls."""
from pathlib import Path
from zipfile import ZipFile
import unittest
from app.materials import import_docx, get_paragraph, list_materials
from app.rules import make_rule, publish_material_rule, resolve_rule, RuleError
from app.stage2_schema import migrate
from tests.helpers import DatabaseTestCaseMixin

ADMIN = frozenset({"rule.manage"})


class MaterialTests(DatabaseTestCaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        migrate(self.db_path)
        self.word = Path(self.temp.name) / "制度.docx"

    def upload(self, text="全部发票必填用途", user="U001", company="C001", material_id=None):
        with ZipFile(self.word, "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
        return import_docx(self.db_path, user, company, self.word, material_id=material_id)

    def ref(self, result):
        return {"material_id": result["material_id"], "version": result["version"], "paragraph_id": 1}

    def rule(self, version="1", effective="2026-01-01"):
        return make_rule("DOC01", version, "制度", "C001", effective, "ACTIVE", "purpose", {"mode": "all", "threshold_cents": 0})

    def publish(self, result, rule=None, **kwargs):
        return publish_material_rule(self.db_path, rule or self.rule(), self.ref(result), ADMIN, actor="U001", **kwargs)

    def test_upload_is_inert_dedup_and_exact_paragraph(self):
        first = self.upload()
        duplicate = import_docx(self.db_path, "U001", "C001", self.word)
        self.assertEqual(duplicate["status"], "NO_CHANGE")
        self.assertEqual(first["material_id"], duplicate["material_id"])
        with self.assertRaisesRegex(RuleError, "NO_APPLICABLE"):
            resolve_rule(self.connection, "U001", "C001", "purpose", "2026-09-01")
        self.publish(first)
        decision = resolve_rule(self.connection, "U001", "C001", "purpose", "2026-09-01")
        self.assertEqual(decision.source, self.ref(first))
        self.assertEqual(get_paragraph(self.connection, "U001", **decision.source)["text"], "全部发票必填用途")

    def test_explicit_v2_upload_not_active_old_reference_survives_publication(self):
        first = self.upload()
        self.publish(first)
        second = self.upload("新版制度原段", material_id=first["material_id"])
        self.assertEqual(second["version"], 2)
        self.assertEqual(resolve_rule(self.connection, "U001", "C001", "purpose", "2026-09-01").version, "1")
        self.publish(second, self.rule("2", "2026-09-01"), supersedes=("DOC01", "1"))
        self.assertEqual(resolve_rule(self.connection, "U001", "C001", "purpose", "2026-08-31").version, "1")
        self.assertEqual(resolve_rule(self.connection, "U001", "C001", "purpose", "2026-09-01").version, "2")
        self.assertEqual(get_paragraph(self.connection, "U001", **self.ref(first))["text"], "全部发票必填用途")

    def test_overlap_conflict_not_latest(self):
        first = self.upload()
        self.publish(first)
        second = self.upload("新版", material_id=first["material_id"])
        self.publish(second, self.rule("2", "2026-09-01"))
        with self.assertRaisesRegex(RuleError, "RULE_CONFLICT"):
            resolve_rule(self.connection, "U001", "C001", "purpose", "2026-09-01")

    def test_same_name_does_not_update_and_other_user_isolated(self):
        first = self.upload()
        same_name = self.upload("另一份内容")
        self.assertNotEqual(first["material_id"], same_name["material_id"])
        other = self.upload(user="U002")
        self.assertNotEqual(first["material_id"], other["material_id"])
        with self.assertRaises(PermissionError):
            get_paragraph(self.connection, "U002", **self.ref(first))
        self.assertEqual(len(list_materials(self.connection, "U002", "C001")), 1)
        with self.assertRaises(PermissionError):
            self.upload("盗更新", user="U002", material_id=first["material_id"])

    def test_parse_failure_does_not_create_or_activate_version(self):
        first = self.upload()
        self.publish(first)
        self.word.write_bytes(b"bad word")
        with self.assertRaises(ValueError):
            import_docx(self.db_path, "U001", "C001", self.word, material_id=first["material_id"])
        self.assertEqual(len(list_materials(self.connection, "U001", "C001")), 1)
        self.assertEqual(resolve_rule(self.connection, "U001", "C001", "purpose", "2026-09-01").version, "1")

    def test_publish_requires_capability_owner_company_and_immutable_reference(self):
        first = self.upload()
        with self.assertRaises(PermissionError):
            publish_material_rule(self.db_path, self.rule(), self.ref(first), actor="U001")
        with self.assertRaises(PermissionError):
            publish_material_rule(self.db_path, self.rule(), self.ref(first), ADMIN, actor="U002")
        self.publish(first)
        second = self.upload("另一个段落", material_id=first["material_id"])
        with self.assertRaisesRegex(RuleError, "引用冲突"):
            self.publish(second)
        self.assertEqual(get_paragraph(self.connection, "U001", **self.ref(first))["text"], "全部发票必填用途")

    def test_permission_revocation_blocks_old_reference(self):
        first = self.upload()
        self.connection.execute("UPDATE permissions SET can_read=0 WHERE user_id='U001' AND company_id='C001'")
        self.connection.commit()
        with self.assertRaises(PermissionError):
            get_paragraph(self.connection, "U001", **self.ref(first))

    def test_invalid_supersession_rolls_back_rule_and_audit(self):
        first = self.upload()
        self.publish(first)
        second = self.upload("新版", material_id=first["material_id"])
        with self.assertRaises(RuleError):
            self.publish(second, self.rule("2", "2025-01-01"), supersedes=("DOC01", "1"))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM rules").fetchone()[0], 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM rule_management_audit").fetchone()[0], 1)

    def test_published_rule_company_acl_does_not_grant_private_original(self):
        first = self.upload()
        self.publish(first)
        decision = resolve_rule(self.connection, "U002", "C001", "purpose", "2026-09-01")
        self.assertEqual(decision.version, "1")
        with self.assertRaises(PermissionError):
            get_paragraph(self.connection, "U002", **decision.source)

    def test_supersession_cannot_rewrite_existing_published_history(self):
        first = self.upload()
        self.publish(first)
        second = self.upload("新版", material_id=first["material_id"])
        self.publish(second, self.rule("2", "2026-09-01"))
        with self.assertRaisesRegex(RuleError, "事后更改"):
            self.publish(second, self.rule("2", "2026-09-01"), supersedes=("DOC01", "1"))
        with self.assertRaisesRegex(RuleError, "RULE_CONFLICT"):
            resolve_rule(self.connection, "U001", "C001", "purpose", "2026-09-01")
