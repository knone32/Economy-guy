"""Public failure-derived contracts; not hidden tests or NLU scores."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from app.agent import Agent
from app.answer_evidence import catalog
from app.business_sql import BusinessSQL
from app.cli_workspaces import import_workspace
from app.provenance import ScopeProof


def tool(name, **args):
    return {'role': 'assistant', 'tool_calls': [{'id': 'read-or-proposal', 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(args)}}]}


class IterationTwoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.book = Path(self.tmp.name) / 'sample.sqlite3'
        import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', self.book)

    def agent(self, model, user='U001'):
        return Agent(user, self.book, model, mode='mock', trace_path=self.book.with_suffix('.jsonl'))

    def test_modify_denial_does_not_falsely_deny_existing_read_permission(self):
        def model(messages, tools):
            prior = [json.loads(m['content']) for m in messages if m['role'] == 'tool']
            if not prior:
                return tool('get_invoice', company_id='C001', invoice_no='F004')
            selection = prior[-1]['data']['selection_id']
            return tool('propose_invoice_changes', selection_id=selection, field='remark',
                        new_value='归档测试', mode='item', excluded_invoice_ids=[])
        agent = self.agent(model, 'U002')
        answer = agent.ask('甲企业2026年9月F004，备注改为“归档测试”，先核对当前值。')
        results = agent.last_response['tool_results']
        self.assertTrue(any(n == 'get_invoice' and r['status'] == 'SUCCESS' for n,r in results))
        self.assertTrue(any(n == 'propose_invoice_changes' and r['status'] == 'DENIED' for n,r in results))
        self.assertNotIn('没有该企业的发票读取和修改权限', answer)
        self.assertEqual(agent.write_receipt['status'], 'NOT_SUBMITTED')

    def test_read_literals_fill_missing_slots_without_cross_quote_cartesian_scope(self):
        for request, company, number, allowed in (
            ('转述“把甲企业2026年9月F004备注改了”，现在只查这张票用途与备注。', 'C001', 'F004', True),
            ('甲企业2026年9月，只读引用“乙企业F004”的背景票，先不要改。', 'C001', 'F004', False),
            ('甲企业2026年9月，只读引用“2026年8月F004”的背景票，先不要改。', 'C001', 'F004', False),
        ):
            with self.subTest(request=request):
                replies = iter((tool('get_invoice', company_id=company, invoice_no=number),
                    {'role': 'assistant', 'content': '{"kind":"information","text":"本轮只读结果。"}'}))
                agent = self.agent(lambda *_: next(replies))
                agent.ask(request)
                success = any(n == 'get_invoice' and r['status'] == 'SUCCESS'
                              for n,r in agent.last_response['tool_results'])
                self.assertEqual(success, allowed)
                self.assertEqual(agent.write_receipt['status'], 'NOT_SUBMITTED')

    def test_returned_invoice_set_counts_have_actual_parents_and_limits(self):
        proof = ScopeProof('U001', {'company_id': ['C001','C002'], 'periods': [(2026,9)]},
                           {'company_id': 'user_current', 'periods': 'user_current'})
        workspace = BusinessSQL(self.book, 'U001', proof); self.addCleanup(workspace.close)
        sql = ("SELECT company_id,invoice_no,invoice_date,amount_cents,purpose FROM invoices "
               "WHERE is_blank(purpose) AND amount_cents>=100000 ORDER BY company_id,invoice_no")
        scope, data, _ = workspace.query(sql)
        result = {'status': 'SUCCESS', 'data': data, 'evidence': {'source': 'current_sqlite',
                  'scope': scope, 'query_scope': data.pop('query_scope')}}
        fs = catalog([('query_business_sql', result)], {'message': '未提交'}, 'turn-derive')
        derived = [f for f in fs.values() if '.returned_invoice_count.' in f['ref']]
        self.assertEqual(len(derived), 2)
        with closing(sqlite3.connect(self.book.as_uri() + '?mode=ro', uri=True)) as db:
            expected_counts = dict(db.execute(
                "SELECT company_id,count(*) FROM invoices WHERE invoice_date>='2026-09-01' "
                "AND invoice_date<'2026-10-01' AND (purpose IS NULL OR trim(purpose)='') "
                "AND amount_cents>=100000 GROUP BY company_id"))
        for company in ('C001', 'C002'):
            expected = expected_counts.get(company, 0)
            fact = next(f for f in derived if f['ref'].endswith('.' + company))
            self.assertIn(f'{company} 发票 {expected} 张', fact['text'])
            self.assertIn('本次返回明细', fact['text'])
        self.assertTrue(any('.returned_invoice_difference.' in f['ref'] for f in fs.values()))
        for mutate in ('truncated', 'paginated', 'duplicate', 'no_identity'):
            bad = deepcopy(result)
            if mutate == 'truncated': bad['data']['truncated'] = True
            elif mutate == 'paginated': bad['data']['invoice_coverage']['sql_paginated'] = True
            elif mutate == 'duplicate': bad['data']['rows'].append(bad['data']['rows'][0])
            else: bad['data']['invoice_projection'].pop('company_id')
            with self.subTest(mutate=mutate):
                self.assertFalse(any('.returned_invoice_' in f['ref'] for f in
                    catalog([('query_business_sql', bad)], {'message': '未提交'}, 'turn-derive').values()))

    def test_current_read_literals_can_match_selected_workspace_without_being_lost(self):
        replies = iter((tool('get_invoice', company_id='C001', invoice_no='F004'),
            {'role': 'assistant', 'content': '{"kind":"information","text":"本轮只读结果。"}'}))
        agent = self.agent(lambda *_: next(replies))
        agent.ask('客户留言是“把甲企业2026年9月F004的备住改成已收齐”。这只是转述，我现在不让你修改；先把这张票当前的用途、备注给我看看。',
                  read_workspace=('C001', 2026, 9))
        outcomes = [r for n,r in agent.last_response['tool_results'] if n == 'get_invoice']
        self.assertTrue(any(r['status'] == 'SUCCESS' for r in outcomes))
        self.assertEqual(agent.write_receipt['status'], 'NOT_SUBMITTED')


if __name__ == '__main__': unittest.main()
