from contextlib import closing, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import main
from app.agent import Agent, scripted_model
from app.cli_home import Home
from app.cli_workspaces import import_workspace, invoice_history, missing_migrations
from app.importer import initialize_database
from app.model_config import add_profile
from app.stage2_schema import open_existing


FIXTURE = Path(__file__).parent / "fixtures" / "example.xlsx"
EDIT = "把甲企业 F002 发票的用途改成项目资料核对。"


class HomeTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.db = self.root / "finance.db"
        import_workspace(FIXTURE, self.db)
        self.template = self.root / "profiles.toml"
        self.template.write_text("profiles = []", encoding="utf-8")
        self.local = self.root / "model_profiles.local.json"
        self.home = Home(self.db, self.template, self.local, FIXTURE, self.root / "managed")
        env = patch.dict(os.environ, {"FINANCE_MODEL_PROFILE": "", "HOME_TEST_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)

    def run_menu(self, values):
        stream = io.StringIO()
        replies = iter(values)

        def answer(prompt):
            print(prompt)
            value = next(replies)
            if isinstance(value, BaseException):
                raise value
            return value

        with patch("builtins.input", side_effect=answer), redirect_stdout(stream):
            self.home.run()
        return stream.getvalue()

    def add_profile(self):
        data = dict(profile_name="home-test", scope="user", owner_user_id="U001", provider="deepseek",
                    service_account_ref="home-test", model="deepseek-flash", base_url="https://api.deepseek.com",
                    api_key_env="HOME_TEST_API_KEY")
        add_profile(data, "U001", template=self.template, local=self.local)
        self.home.profile = "home-test"

    def test_no_arguments_opens_home_and_old_summary_still_works(self):
        with (patch.object(main.sys, "argv", ["main.py"]), patch.object(main, "DEFAULT_DB", self.db),
              patch("builtins.input", return_value="0"), redirect_stdout(io.StringIO()) as out):
            main.main()
        self.assertIn("财税 Agent 主页", out.getvalue())
        self.assertIn("已退出", out.getvalue())
        with (patch.object(main.sys, "argv", ["main.py", "--db", str(self.db), "summary", "--user", "U001",
                                            "--company", "C001", "--year", "2026", "--month", "9"]),
              redirect_stdout(io.StringIO()) as out):
            main.main()
        self.assertEqual(json.loads(out.getvalue())["invoice_total"], "9622.06")

    def test_live_missing_key_and_missing_profile_never_create_agent(self):
        self.add_profile()
        with patch("app.agent.Agent") as factory:
            out = self.run_menu(["1", "3", "2", "4", "/home", "0"])
            factory.assert_not_called()
        self.assertIn("Live 的 Key 未设置", out)
        self.assertIn("HOME_TEST_API_KEY", out)
        self.assertIn("安全输入", out)
        self.assertNotIn("MOCK / 固定模拟响应", out)
        self.home.profile = "absent"
        with patch("app.agent.Agent") as factory:
            out = self.run_menu(["1", "4", "/home", "0"])
            factory.assert_not_called()
        self.assertIn("不存在或对该用户不可见", out)

    def test_user_switch_hides_profile_and_forbidden_company(self):
        self.add_profile()
        self.home.remember("先前交互", {}, [], "NOT_SUBMITTED")
        out = self.run_menu(["2", "1", "2", "2", "3", "2", "0", "/home", "0"])
        self.assertEqual(self.home.user, "U002")
        self.assertFalse(self.home.recent)
        self.assertEqual(self.home.profile_rows(), [])
        self.assertIn("读取 允许 · 修改 拒绝", out)
        self.assertIn("输入无效。请输入列表中的数字。", out)
        after_switch = out.split("当前模拟用户 U002", 1)[1]
        self.assertNotIn("C002", after_switch)
        self.assertNotIn("home-test", after_switch)

    def test_history_redacts_text_and_ignores_raw_traces(self):
        self.home.remember("Cookie: sid=synthetic_cookie; attr=hidden\n正常信息", {},
                           [{"tool": "list_tasks", "status": "SUCCESS"}], "NOT_SUBMITTED")
        logs = self.root / "logs"
        logs.mkdir()
        (logs / "cli_home_trace.jsonl").write_text(
            '{"event":"model_input","reasoning_content":"synthetic_private"}\n', encoding="utf-8")
        out = self.run_menu(["3", "1", "2", "0", "0"])
        self.assertIn("正常信息", out)
        self.assertIn("暂无记录", out)
        self.assertNotIn("synthetic_cookie", out)
        self.assertNotIn("attr=hidden", out)
        self.assertNotIn("synthetic_private", out)
        self.assertNotIn("model_input", out)

    def test_successful_import_and_switch_does_not_overwrite(self):
        before = self.db.read_bytes()
        target = self.root / "managed" / "new.db"
        out = self.run_menu(["4", "1", str(FIXTURE), str(target), "import", "switch", "0", "0"])
        self.assertIn("导入及核对通过", out)
        self.assertEqual(self.home.db, target)
        self.assertFalse(missing_migrations(target))
        self.assertEqual(self.db.read_bytes(), before)
        with self.assertRaises(FileExistsError):
            import_workspace(FIXTURE, self.db)
        self.assertEqual(self.db.read_bytes(), before)
        with closing(open_existing(target, readonly=True)) as db:
            self.assertGreater(db.execute("SELECT count(*) FROM rules").fetchone()[0], 0)

    def test_bad_excel_failed_migration_and_invalid_switch_leave_current_database(self):
        bad = self.root / "bad.xlsx"
        bad.write_bytes(b"invalid xlsx")
        target = self.root / "new.db"
        out = self.run_menu(["4", "1", str(bad), str(target), "import", "3", str(bad), "0", "0"])
        self.assertIn("官方结构", out)
        self.assertIn("工作库无法读取", out)
        self.assertEqual(self.home.db, self.db)
        self.assertFalse(target.exists())
        with patch("app.cli_workspaces.upgrade_workspace", side_effect=OSError):
            with self.assertRaises(OSError):
                import_workspace(FIXTURE, target)
        self.assertFalse(target.exists())
        self.assertEqual(self.home.db, self.db)

    def test_legacy_work_database_additive_upgrade_is_explicit(self):
        legacy = self.root / "legacy.db"
        initialize_database(FIXTURE, legacy)
        self.home.switch_db(legacy)
        self.assertEqual(self.home.user, "U001")
        out = self.run_menu(["4", "4", "", "0", "0"])
        self.assertIn("工作库为旧结构", out)
        self.assertTrue(missing_migrations(legacy))
        out = self.run_menu(["4", "4", "upgrade", "0", "0"])
        self.assertIn("加法升级完成", out)
        self.assertFalse(missing_migrations(legacy))

    def test_admin_is_explicit_and_rule_preview_can_cancel(self):
        self.home.switch_user("U002")
        with patch("app.cli_home.disable_rule") as disable:
            out = self.run_menu(["2", "5", "0", "6", "", "6", "admin", "3", "1", "", "0", "0"])
            disable.assert_not_called()
        self.assertIn("S4-UX-B", out)
        self.assertIn("SIMULATED_ADMIN", out)
        self.assertIn("确认将上述版本停用", out)
        with self.assertRaises(PermissionError):
            self.home.new_profile("global")
        out = self.run_menu(["6", "admin", "3", "1", "disable", "4", "0", "0"])
        self.assertIn("SUCCESS_CHANGED", out)
        with closing(open_existing(self.db, readonly=True)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM rule_management_audit WHERE operation='disable'").fetchone()[0], 1)

    def test_chat_exit_discards_actual_draft_before_user_switch(self):
        agents = []
        drafts = []

        def factory(*args, **kwargs):
            model = scripted_model([{"role": "assistant", "tool_calls": [{
                "id": "edit1", "type": "function",
                "function": {"name": "prepare_invoice_update", "arguments": json.dumps({
                    "company_id": "C001", "invoice_no": "F002", "field": "purpose", "new_value": "项目资料核对"})},
            }]}])
            agent = Agent(args[0], args[1], model, *args[3:], **kwargs)
            agents.append(agent)
            return agent

        def answer(label):
            if label == "最终确认：":
                drafts.extend(agents[-1].update_session.drafts.values())
                raise KeyboardInterrupt
            return next(keys)

        keys = iter(["1", "4", "1", EDIT, "0", "1", "2", "4", "0", "/home", "0"])
        with (patch("app.agent.Agent", side_effect=factory), patch("builtins.input", side_effect=answer),
              redirect_stdout(io.StringIO()) as out):
            self.home.run()
        draft, = drafts
        self.assertEqual([agent.user_id for agent in agents], ["U001", "U002"])
        self.assertTrue(all(not agent.update_session.drafts and not agent.update_session.confirmations for agent in agents))
        self.assertEqual(agents[-1].commit_update(draft.request_id, draft.fingerprint())["status"], "DENIED")
        self.assertEqual(invoice_history(self.db, "U001"), [])
        self.assertIn("edit1", out.getvalue())

    def test_invoice_history_checks_actor_and_current_acl(self):
        with closing(open_existing(self.db)) as db, db:
            db.execute("""INSERT INTO invoice_audit
                (request_id,fingerprint,actor,company_id,invoice_no,field,new_value,status)
                VALUES ('r','f','U001','C001','F002','purpose','audit test','COMMITTED')""")
        self.assertEqual(len(invoice_history(self.db, "U001")), 1)
        self.assertEqual(invoice_history(self.db, "U002"), [])
        with closing(open_existing(self.db)) as db, db:
            db.execute("UPDATE permissions SET can_read=0 WHERE user_id='U001' AND company_id='C001'")
        self.assertEqual(invoice_history(self.db, "U001"), [])

    def test_navigation_invalid_and_ctrl_c(self):
        out = self.run_menu(["nonsense", "2", KeyboardInterrupt(), "5", "/home", "0"])
        self.assertIn("输入无效", out)
        self.assertIn("用户与权限", out)
        self.assertIn("Profile 设置", out)
        self.assertIn("已退出", out)
        self.assertIn("已退出", self.run_menu([KeyboardInterrupt()]))

    def test_user_profile_creation_selection_and_hidden_process_key(self):
        out = self.run_menu(["5", "3", "new-user", "deepseek", "local-reference", "deepseek-flash",
                             "https://api.deepseek.com", "HOME_TEST_API_KEY", "standard", "save",
                             "4", "1", "2", "0", "0"])
        self.assertEqual(self.home.profile, "new-user")
        self.assertIn("本地模型/端点配置合法 · Key 就绪 否", out)
        with (patch("app.cli_home.sys.stdin.isatty", return_value=True),
              patch("app.cli_home.getpass", return_value="synthetic_offline_marker"),
              redirect_stdout(io.StringIO()) as output):
            self.home.set_key()
        self.assertEqual(os.environ["HOME_TEST_API_KEY"], "synthetic_offline_marker")
        self.assertNotIn("synthetic_offline_marker", output.getvalue())
        self.assertNotIn("synthetic_offline_marker", self.local.read_text(encoding="utf-8"))
        self.assertIn("尚未发起联网", self.home.connection_status)

    def test_demo_navigation_dispatches_only_explicit_mock(self):
        with patch("app.cli_home.subprocess.run") as spawn:
            spawn.return_value.returncode = 0
            out = self.run_menu(["7", "1", "3", "0"])
        self.assertIn("SIMULATED_TEST_USER", out)
        command = spawn.call_args.args[0]
        self.assertTrue(command[1].endswith("demo_stepper.py"))
        self.assertEqual(command[2:], ["--mode", "mock", "--scenario", "B"])

    def test_dependency_and_python_setup_instructions(self):
        with redirect_stderr(io.StringIO()) as err:
            self.assertFalse(main.check_runtime((3, 10), lambda _: self.fail("checked imports too early")))
            self.assertFalse(main.check_runtime((3, 11), lambda name: None if name == "openai" else object()))
        self.assertIn("py -3.11 main.py", err.getvalue())
        self.assertIn("缺少依赖 openai", err.getvalue())
        self.assertIn("python -m pip install -r requirements.txt", err.getvalue())


if __name__ == "__main__":
    unittest.main()
