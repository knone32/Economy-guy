"""Finite evidence arithmetic and compact prompts; no language-accuracy claims."""
import json
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import sqlite3
from copy import deepcopy

from app.answer_evidence import catalog, prompt, select
from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.provenance import ScopeProof
from app.business_sql import BusinessSQL
from app.tool_registry import handle_tool


class TypedDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.book = Path(self.tmp.name) / 'sample.sqlite3'
        import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', self.book)

    def summaries(self):
        results = []
        for company in ('C001', 'C002'):
            values = {'company_id': [company], 'year': [2026], 'month': [9], 'periods': [(2026,9)]}
            proof = ScopeProof('U001', values, dict.fromkeys(values, 'user_current'))
            result = handle_tool('get_finance_summary', json.dumps({'company_id': company, 'year': 2026, 'month': 9}),
                                 'U001', self.book, provenance=proof)
            results.append(('get_finance_summary', result))
        return catalog(results, {'status': 'NOT_SUBMITTED', 'message': '尚未提交'}, 'typed-turn')

    def test_comparison_and_subtraction_bind_real_metric_parents(self):
        fs = self.summaries()
        left, right = 'typed-turn:r0.invoice_total', 'typed-turn:r1.invoice_total'
        text = select([{'op': 'compare', 'left': left, 'right': right}], fs)
        self.assertIsNotNone(text)
        self.assertIn('C002', text)
        self.assertIn('C001', text)
        with closing(sqlite3.connect(self.book.as_uri() + '?mode=ro', uri=True)) as db:
            totals = dict(db.execute("SELECT company_id,sum(amount_cents) FROM invoices "
                                     "WHERE invoice_date LIKE '2026-09-%' GROUP BY company_id"))
        difference_value = totals['C001'] - totals['C002']
        self.assertIn(f'{abs(Decimal(difference_value))/100:.2f}', text)
        self.assertIn('高于', text)
        difference = select([{'op': 'subtract', 'left': left, 'right': right}], fs)
        self.assertIn(f'{Decimal(difference_value)/100:.2f}', difference)

    def test_untrusted_metric_unit_ref_and_label_are_not_comparable(self):
        fs = self.summaries()
        left = 'typed-turn:r0.invoice_total'
        for item in (
            {'op': 'compare', 'left': left, 'right': 'typed-turn:r1.invoice_count'},
            {'op': 'compare', 'left': left, 'right': 'typed-turn:r1.bank_income_total'},
            {'op': 'compare', 'left': left, 'right': 'previous:r1.invoice_total'},
            {'op': 'compare', 'left': left, 'right': 'typed-turn:receipt'},
            {'op': 'compare', 'left': left, 'right': 'typed-turn:r1.invoice_total', 'label': '已保存'},
        ):
            with self.subTest(item=item): self.assertIsNone(select([item], fs))
        bad_scope = deepcopy(fs)
        bad_scope['typed-turn:r1.invoice_total']['scope'] = {'company_id': 'C002', 'year': 2026}
        self.assertIsNone(select([{'op': 'compare', 'left': left, 'right': 'typed-turn:r1.invoice_total'}], bad_scope))

    def test_prompt_keeps_reference_metadata_without_repeating_rendered_results(self):
        fs = self.summaries()
        wire = prompt(fs)['content']
        view = json.loads(wire.rsplit('\n', 1)[-1])
        self.assertEqual({f['ref'] for f in view}, set(fs))
        self.assertTrue(all('text' not in f for f in view))
        self.assertLess(len(wire), len(json.dumps(list(fs.values()), ensure_ascii=False)))
        self.assertIn('962206', wire)
        # Prompt projection must not modify the execution-side rendered facts.
        self.assertIn('9622.06', fs['typed-turn:r0.invoice_total']['text'])

    def test_real_filtered_rows_can_deliver_the_comparison_not_just_a_table(self):
        sql = ("SELECT company_id,invoice_no,invoice_date,amount_cents,purpose FROM invoices "
               "WHERE amount_cents<200000 AND NOT is_blank(purpose) AND invoice_no<>'F004' "
               "ORDER BY company_id,invoice_no")
        n = 0
        def model(messages, tools):
            nonlocal n
            n += 1
            if n == 1:
                return {'role': 'assistant', 'tool_calls': [{'id': 'filtered', 'type': 'function',
                    'function': {'name': 'query_business_sql', 'arguments': json.dumps({'sql': sql})}}]}
            fs = json.loads(next(m['content'] for m in reversed(messages)
                if m.get('name') == 'answer_catalog').rsplit('\n', 1)[-1])
            left = next(f['ref'] for f in fs if f['ref'].endswith('.returned_invoice_total.C001'))
            right = next(f['ref'] for f in fs if f['ref'].endswith('.returned_invoice_total.C002'))
            return {'role': 'assistant', 'content': json.dumps({'kind': 'information', 'text': '已保存。',
                'answer': [{'op': 'compare', 'left': left, 'right': right}]})}
        agent = Agent('U001', self.book, model, mode='mock', trace_path=self.book.with_suffix('.jsonl'))
        answer = agent.ask('2026年9月，甲企业和乙企业，价税不到两千、用途已填的票排除F004，比较这两家的入选金额。')
        self.assertIn('C002', answer)
        self.assertIn('高于', answer)
        self.assertIn('819.49', answer)
        self.assertNotIn('已保存。', answer)
        self.assertEqual(n, 2)
        self.assertEqual(agent.write_receipt['status'], 'NOT_SUBMITTED')

    def test_subtraction_of_distinct_monetary_metrics_retains_both_parent_labels(self):
        fs = self.summaries()
        answer = select([{'op': 'subtract', 'left': 'typed-turn:r0.bank_income_total',
                          'right': 'typed-turn:r0.invoice_total'}], fs)
        self.assertIn('银行收入合计', answer)
        self.assertIn('发票价税合计', answer)
        self.assertIn('3378.44', answer)
        self.assertNotIn('利润', answer)

    def test_verified_sql_expression_defines_metric_instead_of_arbitrary_alias(self):
        proof = ScopeProof('U001', {'company_id': ['C001','C002'], 'periods': [(2026,9)]},
                           {'company_id': 'user_current', 'periods': 'user_current'})
        workspace = BusinessSQL(self.book, 'U001', proof); self.addCleanup(workspace.close)
        scope, data, _ = workspace.query('SELECT company_id,SUM(amount_cents) AS invoice_count FROM invoices GROUP BY company_id')
        result = {'status': 'SUCCESS', 'data': data, 'evidence': {'source': 'current_sqlite',
                  'scope': scope, 'query_scope': data.pop('query_scope')}}
        fs = catalog([('query_business_sql', result)], {'status': 'NOT_SUBMITTED', 'message': '未提交'}, 'sql-typed')
        measure = fs['sql-typed:r0.cell.0.1']
        self.assertEqual(measure['unit'], 'cents')
        self.assertEqual(measure['metric'], ('invoices', 'sum', 'amount_cents'))
        self.assertIn('金额', measure['label'])
        scope, unknown, _ = workspace.query('SELECT 123 AS amount_cents FROM invoices')
        result = {'status': 'SUCCESS', 'data': unknown, 'evidence': {'source': 'current_sqlite',
                  'scope': scope, 'query_scope': unknown.pop('query_scope')}}
        fs = catalog([('query_business_sql', result)], {'message': '未提交'}, 'unknown')
        self.assertFalse(any(f.get('type') == 'scalar' for f in fs.values()))


if __name__ == '__main__': unittest.main()
