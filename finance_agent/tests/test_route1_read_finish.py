import json
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.stage2_schema import open_existing
import app.agent as runtime


def call(ident):
    return {'role': 'assistant', 'content': None, 'tool_calls': [{'id': ident, 'type': 'function',
        'function': {'name': 'get_invoice', 'arguments': json.dumps({'company_id': 'C001', 'invoice_no': 'F008'})}}]}


def final(text):
    return {'role': 'assistant', 'content': json.dumps({'kind': 'information', 'text': text}, ensure_ascii=False)}


class ReadFinishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.book = Path(self.tmp.name) / 'sample.sqlite3'
        import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', self.book)

    def test_duplicate_read_has_one_final_only_slot_and_fresh_next_turn(self):
        sequence = iter([call('one'), call('duplicate'), final('F008备注为项目交流出差。'),
                         call('next-turn'), final('F008备注为新一轮读取。')])
        calls = []
        def model(_messages, tools):
            answer = next(sequence); calls.append((answer, tools)); return answer
        agent = Agent('U001', self.book, model=model, mode='mock', trace_path=self.book.with_suffix('.jsonl'))
        with patch.object(runtime, 'handle_tool', wraps=runtime.handle_tool) as handler:
            agent.ask('帮我过一眼甲企业2026年9月F008的备注。')
            self.assertEqual(agent.last_response['assistant_text'], 'F008备注为项目交流出差。')
            self.assertEqual(agent.last_response['execution']['actual_tool_calls'], 1)
            self.assertEqual(handler.call_count, 1)
            self.assertEqual(calls[-1][1], [])
            with closing(open_existing(self.book)) as db, db:
                db.execute("UPDATE invoices SET remark='新一轮读取' WHERE company_id='C001' AND invoice_no='F008'")
            agent.ask('再查甲企业2026年9月F008当前备注。')
            self.assertEqual(handler.call_count, 2)
            self.assertIn('新一轮读取', agent.last_response['assistant_text'])

    def test_final_only_model_cannot_dispatch_another_read(self):
        sequence = iter([call('one'), call('duplicate'), call('forbidden')])
        agent = Agent('U001', self.book, model=lambda *_: next(sequence), mode='mock', trace_path=self.book.with_suffix('.jsonl'))
        with patch.object(runtime, 'handle_tool', wraps=runtime.handle_tool) as handler:
            agent.ask('甲企业2026年9月F008备注查一下。')
            self.assertEqual(handler.call_count, 1)
            self.assertEqual(agent.last_response['execution']['stop_reason'], 'API_OR_RESPONSE_ERROR')

    def test_permission_or_book_change_never_borrows_final_slot(self):
        stage = {'n': 0}
        def model(*_):
            stage['n'] += 1
            if stage['n'] == 2:
                with closing(open_existing(self.book)) as db, db:
                    db.execute("UPDATE permissions SET can_read=0 WHERE user_id='U001' AND company_id='C001'")
            return call(str(stage['n']))
        agent = Agent('U001', self.book, model=model, mode='mock', trace_path=self.book.with_suffix('.jsonl'))
        agent.ask('甲企业2026年9月F008，读取备注。')
        self.assertEqual(stage['n'], 2)
        self.assertEqual(agent.last_response['execution']['stop_reason'], 'NO_PROGRESS')
        self.assertEqual(agent.last_response['execution']['actual_tool_calls'], 1)


if __name__ == '__main__':
    unittest.main()
