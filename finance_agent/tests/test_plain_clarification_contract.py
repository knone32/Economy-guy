"""A model question is not a server-owned pending workflow or permission."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from app.agent import Agent, scripted_model
from app.pending_transition import contract_error
from app.stage2_schema import migrate
from tests.helpers import DatabaseTestCaseMixin


class PlainClarificationTests(DatabaseTestCaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        migrate(self.db_path)

    def agent(self, missing, text='请说明要查的对象。'):
        envelope = {'kind': 'clarification', 'text': text, 'missing_fields': missing}
        return Agent('U001', self.db_path, scripted_model([
            {'role': 'assistant', 'content': json.dumps(envelope, ensure_ascii=False)}]), mode='mock')

    def assert_no_write_state(self, agent):
        # Harness may retain a read clarification, never an executable change.
        if agent.pending_intent:
            self.assertFalse(agent.pending_intent.get('change'))
            self.assertNotEqual(agent.pending_intent.get('business_action'), 'single_invoice')
        self.assertEqual(agent.write_receipt['status'], 'NOT_SUBMITTED')
        self.assertFalse(agent.update_session.drafts)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM invoice_audit').fetchone()[0], 0)

    def test_supported_plain_question_needs_no_pending_event_or_second_model_call(self):
        agent = self.agent(['company_id', 'year', 'month'])
        answer = agent.ask('帮我查一下发票。')
        self.assertEqual(agent.last_response['category'], 'clarification')
        self.assertEqual(agent.last_response['execution']['model_requests'], 1)
        self.assertIn('企业', answer)
        self.assertIn('年份', answer)
        self.assertNotIn('结构', answer)
        self.assert_no_write_state(agent)

    def test_followup_read_question_also_needs_no_server_request_id(self):
        agent = self.agent(['company_id', 'year', 'month'])
        agent.ask('帮我查一下发票。')
        agent.model = scripted_model([{'role': 'assistant', 'content': json.dumps({
            'kind': 'clarification', 'text': '还需要企业和月份。',
            'missing_fields': ['company_id', 'month']}, ensure_ascii=False)}])
        answer = agent.ask('2026年的。')
        self.assertEqual(agent.last_response['category'], 'clarification')
        self.assertEqual(agent.last_response['execution']['model_requests'], 1)
        self.assertIn('企业', answer)
        self.assertIn('月份', answer)
        self.assert_no_write_state(agent)

    def test_ambiguity_question_is_delivered_without_creating_write_candidate(self):
        agent = self.agent(['invoice_no'])
        answer = agent.ask('我还没有决定要看哪张发票。')
        self.assertEqual(agent.last_response['category'], 'clarification')
        self.assertEqual(agent.last_response['execution']['model_requests'], 1)
        self.assertIn('发票', answer)
        self.assert_no_write_state(agent)

    def test_question_text_never_supplies_a_commit_or_cancellation_receipt(self):
        agent = self.agent(['invoice_no'], '已经保存发票，取消已完成。请给票号。')
        answer = agent.ask('哪张发票还不确定。')
        self.assertNotIn('已经保存', answer)
        self.assertNotIn('取消已完成', answer)
        self.assertEqual(agent.last_response['execution']['model_requests'], 1)
        self.assert_no_write_state(agent)

    def test_real_pending_events_keep_their_strict_contract(self):
        plain = {'kind': 'clarification', 'text': '请补充。', 'missing_fields': ['invoice_no']}
        self.assertIsNone(contract_error(plain, False))
        self.assertEqual(contract_error(plain, True), 'pending_event_required_for_waiting')
        injected = {**plain, 'pending_change': {'field': 'remark', 'new_value': 'x'}}
        self.assertEqual(contract_error(injected, False), 'pending_event_required_for_waiting')
        self.assertEqual(contract_error({**plain, 'pending': {'action': 'create'}}, False),
                         'explicit_candidate_scope_required')


class PlainClarificationWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_workspace_delivers_one_safe_question_without_approval(self):
        from app.cli_workspaces import import_workspace
        from app.model_config import DEFAULT_TEMPLATE
        from app.tui import AgentWorkspace
        from app.tui_screens import Approval
        from tests.test_tui_p0 import P0Test, FIXTURE
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / 'book.db'
            import_workspace(FIXTURE, database)
            model = scripted_model([{'role': 'assistant', 'content': json.dumps({
                'kind': 'clarification', 'text': '已经保存，请给票号。',
                'missing_fields': ['invoice_no']}, ensure_ascii=False)}])
            app = AgentWorkspace(database, DEFAULT_TEMPLATE, root / 'no-profile.json',
                                 model=model, session_path=root / 'sessions.db')
            app.mode = 'mock'
            helper = P0Test()
            async with app.run_test(size=(150, 42)) as pilot:
                await helper.sign_in(app, pilot)
                await helper.send(app, pilot, '我还没有确定看哪张发票。')
                await helper.await_state(pilot, lambda: bool(app.records) and not app.busy)
                chat = '\n'.join(line.text for line in app.workspace_widget('#chat-log').lines)
                self.assertNotIn('已经保存', chat)
                self.assertIn('发票', chat)
                self.assertNotIsInstance(app.screen, Approval)
                self.assertEqual(app.agent.last_response['category'], 'clarification')
                self.assertEqual(app.agent.last_response['execution']['model_requests'], 1)
                self.assertEqual(app.agent.write_receipt['status'], 'NOT_SUBMITTED')


if __name__ == '__main__':
    unittest.main()
