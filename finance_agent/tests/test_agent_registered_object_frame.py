"""The Agent must not erase validated objects or read dates inside their IDs."""
import json
import unittest
from app.agent import Agent, scripted_model
from app.stage2_schema import migrate
from tests.helpers import DatabaseTestCaseMixin


class RegisteredObjectFrameTests(DatabaseTestCaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        migrate(self.db_path)
        self.number = 'DOC-82/2034-07'
        self.connection.execute("UPDATE companies SET name='晨岸机电有限公司',short_name='晨岸机电' WHERE company_id='C001'")
        self.connection.execute("UPDATE invoices SET invoice_no=? WHERE company_id='C001' AND invoice_no='F002'", (self.number,))
        self.connection.commit()

    def ask(self, text, **kwargs):
        agent = Agent('U001', self.db_path, scripted_model([
            {'role': 'assistant', 'tool_calls': [{'id': 'registered-read', 'type': 'function',
                'function': {'name': 'get_invoice', 'arguments': json.dumps({
                    'company_id': 'C001', 'invoice_no': self.number})}}]},
            {'role': 'assistant', 'content': json.dumps({'kind': 'information', 'text': '已取得本轮工具结果。'}, ensure_ascii=False)}
        ]), mode='mock')
        agent.ask(text, **kwargs)
        results = [outcome for name, outcome in agent.last_response['tool_results'] if name == 'get_invoice']
        self.assertEqual(len(results), 1)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM invoice_audit').fetchone()[0], 0)
        return agent, results[0]

    def test_exact_registered_identifier_is_kept_and_internal_date_is_not_a_period(self):
        agent, result = self.ask(f'查看晨岸机电的{self.number}发票详情。')
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['data']['invoice_no'], self.number)
        self.assertEqual(result['data']['invoice_date'], '2026-09-08')
        self.assertNotIn(2034, agent.context.scope.get('year', ()))
        self.assertEqual(agent.write_receipt['status'], 'NOT_SUBMITTED')

    def test_current_registered_object_overrides_other_selected_read_company(self):
        _, result = self.ask(f'查看晨岸机电的{self.number}发票详情。', read_workspace=('C002', 2026, 9))
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['data']['company_id'], 'C001')

    def test_identifier_prefix_does_not_authorize_a_model_completed_invoice(self):
        _, result = self.ask('查看晨岸机电的DOC-82发票详情。')
        self.assertNotEqual(result['status'], 'SUCCESS')


if __name__ == '__main__':
    unittest.main()
