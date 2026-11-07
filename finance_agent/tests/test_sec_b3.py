"""Offline Profile validation and real rules CLI on the official temporary fixture."""
from contextlib import closing, redirect_stdout
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import UUID

import main
from app.model_config import ProfileError, add_profile, resolve_connection, safe_url, visible_profiles
from app.rules import RuleError, SEED_RULES, import_rules, resolve_rule
from app.stage2_schema import migrate
from tests.helpers import DatabaseTestCaseMixin
from tests.test_stage4pd import profile


UNSAFE_HOSTS = ("127.0.0.1", "127.1", "2130706433", "0x7f000001", "0177.0.0.1",
                "127.000.000.001", "10.0.0.1", "192.168.1.1", "[::1]",
                "0x7f.0.0.01", "127.1.", "１２７。１", "%31%32%37.1", "[::ffff:127.0.0.1]")


class OfflineProfileTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.template = Path(directory) / "profiles.toml"
        self.template.write_text("profiles = []\n", encoding="utf-8")
        self.local = Path(directory) / "profiles.json"
        self.config = {"template": self.template, "local": self.local}
        self.enterContext(patch.dict(os.environ, {"TEST_DS_KEY": "synthetic-profile-key"}, clear=True))
        self.sdk = self.enterContext(patch("openai.OpenAI", side_effect=AssertionError("no SDK")))
        self.transport = self.enterContext(patch("app.agent.ModelTransport", side_effect=AssertionError("no transport")))
        self.dns = self.enterContext(patch("socket.getaddrinfo", side_effect=AssertionError("no DNS")))
        self.socket = self.enterContext(patch("socket.socket.connect", side_effect=AssertionError("no socket")))

    def tearDown(self):
        for blocked in (self.sdk, self.transport, self.dns, self.socket):
            blocked.assert_not_called()

    def test_rejects_ambiguous_numeric_and_nonglobal_literal_hosts(self):
        for host in UNSAFE_HOSTS:
            with self.subTest(host=host), self.assertRaises(ProfileError):
                safe_url(f"https://{host}/v1")
        for url in ("http://example.com", "https://@example.com", "https://example.com:8443",
                    "https://example.com?", "https://example.com#", "https://bad..example"):
            with self.subTest(url=url), self.assertRaises(ProfileError):
                safe_url(url)

    def test_invalid_legacy_and_stored_profiles_fail_before_transport(self):
        config = ["main.py", "--db", str(self.local.with_suffix(".db")), "--profiles-file", str(self.template),
                  "--profiles-local", str(self.local)]
        chat = ["chat", "--mode", "live", "--user", "U001"]
        for group in (
            {"OPENAI_API_KEY": "synthetic-profile-key", "OPENAI_BASE_URL": "https://127.1", "OPENAI_MODEL": "model"},
            {"KEY": "synthetic-profile-key", "BASE_URL": "https://0x7f000001", "MODEL": "model"},
        ):
            with patch.dict(os.environ, group, clear=True), patch.object(sys, "argv", config + chat):
                with self.assertRaises(ProfileError) as error:
                    main.main()
                self.assertNotIn("synthetic-profile-key", str(error.exception))
        self.local.write_text(json.dumps({"profiles": [profile(model="mock", base="https://2130706433")]}),
                              encoding="utf-8")
        with patch.object(sys, "argv", config + chat + ["--profile", "shared"]), self.assertRaises(ProfileError):
            main.main()

    def test_valid_profiles_and_scope_preserve_config_on_rejection(self):
        valid = ("https://api.deepseek.com", "https://api.openai.com/v1",
                 "https://123-provider.example/v1", "https://12.api.example:443", "https://8.8.8.8/v1")
        for url in valid:
            self.assertEqual(safe_url(url), url)
        add_profile(profile(), simulate_manager=True, **self.config)
        mine = profile("mine", "user", "U001", model="mock", provider="openai", base=valid[1])
        add_profile(mine, user_id="U001", **self.config)
        self.assertEqual(resolve_connection("U001", "mine", **self.config).profile.base_url, valid[1])
        self.assertEqual(resolve_connection("U002", "shared", **self.config).profile.base_url, valid[0])
        self.assertEqual([p["profile_name"] for p in visible_profiles("U002", **self.config)], ["shared"])
        with self.assertRaises(ProfileError):
            resolve_connection("U002", "mine", **self.config)
        before = self.local.read_bytes()
        with self.assertRaises(ProfileError):
            add_profile(profile("new", base="https://0177.0.0.1"), simulate_manager=True, **self.config)
        self.assertEqual(self.local.read_bytes(), before)
        self.assertNotIn(b"synthetic-profile-key", before)


class RuleAuditTests(DatabaseTestCaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        migrate(self.db_path)

    def cli(self, action, *options, authorized=True):
        args = ["main.py", "--db", str(self.db_path), "rules", action, *options]
        if authorized:
            args.append("--simulate-rule-manager")
        stream = io.StringIO()
        with patch.object(sys, "argv", args), redirect_stdout(stream):
            main.main()
        return json.loads(stream.getvalue())

    def import_file(self, rules):
        path = self.db_path.with_suffix(".json")
        path.write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
        return ("--file", str(path))

    def read(self, query, args=()):
        with closing(sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True)) as db:
            return db.execute(query, args).fetchall()

    def audit(self):
        return self.read("""SELECT actor,operation,rule_id,version,old_status,new_status,result
                            FROM rule_management_audit ORDER BY rowid""")

    def business(self):
        return [self.read(f"SELECT * FROM {table} ORDER BY rowid")
                for table in ("invoices", "bank_transactions", "invoice_audit", "permissions")]

    def disable(self, rule_id="R002", version="2.0", **kwargs):
        return self.cli("disable", "--rule-id", rule_id, "--version", version, **kwargs)

    def test_cli_disable_has_audit_and_repeat_does_not_claim_change(self):
        self.cli("seed")
        business, before = self.business(), self.audit()
        self.assertEqual(self.read("SELECT status FROM rules WHERE rule_id='R002' AND version='2.0'"), [("ACTIVE",)])
        self.assertEqual(self.disable()["status"], "SUCCESS_CHANGED")
        self.assertEqual(self.read("SELECT status FROM rules WHERE rule_id='R002' AND version='2.0'"), [("DISABLED",)])
        expected = ("simulated_rule_manager", "disable", "R002", "2.0", "ACTIVE", "DISABLED", "SUCCESS_CHANGED")
        self.assertEqual(self.audit(), [*before, expected])
        self.assertEqual(self.disable()["status"], "NO_CHANGE")
        self.assertEqual(self.audit(), [*before, expected])
        self.assertEqual(self.business(), business)
        with self.assertRaisesRegex(RuleError, "NO_APPLICABLE_RULE"):
            resolve_rule(self.connection, "U001", "C001", "purpose", "2026-09-01")
        for company, kind, expected_id in (("C001", "amount", "R001"), ("C002", "purpose", "R003"),
                                            ("C001", "bank", "R004")):
            decision = resolve_rule(self.connection, "U001", company, kind, "2026-09-01")
            self.assertEqual((decision.rule_id, decision.version), (expected_id, "1.0"))

    def test_seed_and_import_log_only_new_versions(self):
        self.assertEqual(self.cli("seed"), {"status": "SUCCESS_CHANGED", "changed": 5, "unchanged": 0})
        keys = [("R001", "1.0", "ACTIVE"), ("R002", "1.0", "DISABLED"), ("R002", "2.0", "ACTIVE"),
                ("R003", "1.0", "ACTIVE"), ("R004", "1.0", "ACTIVE")]
        before = [("simulated_rule_manager", "seed", rid, v, None, s, "SUCCESS_CHANGED") for rid, v, s in keys]
        self.assertEqual(self.audit(), before)
        self.assertEqual(self.cli("seed"), {"status": "NO_CHANGE", "changed": 0, "unchanged": 5})
        new = {**SEED_RULES[0], "version": "fixture"}
        self.assertEqual(self.cli("import", *self.import_file([SEED_RULES[0], new])),
                         {"status": "SUCCESS_CHANGED", "changed": 1, "unchanged": 1})
        self.assertEqual(self.cli("import", *self.import_file([new]))["status"], "NO_CHANGE")
        self.assertEqual(self.audit(), [*before, ("simulated_rule_manager", "import", "R001", "fixture",
                                                 None, "ACTIVE", "SUCCESS_CHANGED")])
        rows = self.read("SELECT event_id, occurred_at FROM rule_management_audit")
        self.assertEqual(len({UUID(event_id) for event_id, _ in rows}), 6)
        self.assertTrue(all(timestamp for _, timestamp in rows))

    def test_rejected_operations_and_batch_conflict_leave_no_audit_or_changes(self):
        self.cli("seed")
        before = (self.business(), self.audit(), self.read("SELECT * FROM rules"))
        with self.assertRaises(PermissionError):
            self.disable(authorized=False)
        with self.assertRaisesRegex(RuleError, "不存在"):
            self.disable("missing")
        with self.assertRaises(ValueError):
            self.cli("import", *self.import_file([{**SEED_RULES[0], "params": {"unit": "bad"}}]))
        with self.assertRaises(RuleError):
            self.cli("import", *self.import_file([{"bogus": True}]))
        with self.assertRaisesRegex(RuleError, "冲突"):
            self.cli("import", *self.import_file([{**SEED_RULES[0], "version": "new"},
                                                 {**SEED_RULES[0], "name": "conflicting fixture"}]))
        self.assertEqual((self.business(), self.audit(), self.read("SELECT * FROM rules")), before)

    def test_old_database_fails_closed_then_idempotent_migration_preserves_rows(self):
        self.cli("seed")
        with self.connection:
            self.connection.execute("DROP TABLE IF EXISTS rule_management_audit")
        before = (self.business(), self.read("SELECT * FROM rules"))
        for operation in (self.disable, lambda: import_rules(self.db_path, [{**SEED_RULES[0], "version": "new"}],
                                                              {"rule.manage"})):
            with self.assertRaisesRegex(RuleError, "migrate-stage2"):
                operation()
        self.assertEqual((self.business(), self.read("SELECT * FROM rules")), before)
        migrate(self.db_path)
        self.disable()
        state = (self.business(), self.read("SELECT * FROM rules"), self.audit())
        migrate(self.db_path)
        self.assertEqual((self.business(), self.read("SELECT * FROM rules"), self.audit()), state)
        self.assertEqual(self.read("PRAGMA integrity_check"), [("ok",)])

    def test_database_and_audit_write_faults_roll_back_rule_and_event(self):
        self.cli("seed")
        before = (self.business(), self.read("SELECT * FROM rules"), self.audit())
        # A failed second audit row must also roll back the first rule and its successful audit.
        with self.connection:
            self.connection.executescript("""
                CREATE TRIGGER audit_fault BEFORE INSERT ON rule_management_audit
                WHEN NEW.operation='disable' OR NEW.version='second'
                BEGIN SELECT RAISE(ABORT,'synthetic audit write failure'); END;
                CREATE TRIGGER rule_fault BEFORE INSERT ON rules WHEN NEW.version='database-fault'
                BEGIN SELECT RAISE(ABORT,'synthetic rule write failure'); END;
            """)
        with self.assertRaisesRegex(RuleError, "数据库"):
            self.disable()
        for version in ("second", "database-fault"):
            with self.subTest(version=version), self.assertRaisesRegex(RuleError, "数据库"):
                self.cli("import", *self.import_file([{**SEED_RULES[0], "version": "first"},
                                                     {**SEED_RULES[0], "version": version}]))
        self.assertEqual((self.business(), self.read("SELECT * FROM rules"), self.audit()), before)
        self.assertEqual(self.read("PRAGMA integrity_check"), [("ok",)])
