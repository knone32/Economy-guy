"""Focused regressions from recorded route-one failures, not wording fixtures."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.business_sql import BusinessSQL
from app.cli_workspaces import import_workspace
from app.provenance import ScopeProof
from app.responses import reply_evidence_conflict
from app.tool_registry import handle_tool, TOOLS

FIXTURE = Path(__file__).parent / 'fixtures/example.xlsx'


class EvidenceContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.book = Path(self.tmp.name) / 'sample.sqlite3'
        import_workspace(FIXTURE, self.book)

    def proof(self, company='C001', month=9):
        scope = {'company_id': [company], 'year': [2026], 'month': [month], 'periods': [(2026, month)]}
        return ScopeProof('U001', scope, dict.fromkeys(scope, 'user_current'))

    def summary(self):
        return handle_tool('get_finance_summary', json.dumps({'company_id': 'C001', 'year': 2026, 'month': 9}),
                           'U001', self.book, provenance=self.proof())

    def query(self, sql, company='C001', annual=False):
        proof = self.proof(company)
        if annual:
            proof = ScopeProof('U001', {'company_id': [company]}, {'company_id': 'user_current'}, annual_year=2026)
        workspace = BusinessSQL(self.book, 'U001', proof)
        self.addCleanup(workspace.close)
        return workspace.query(sql)[1]

    def test_list_layout_is_not_business_quantity(self):
        results = [('get_finance_summary', self.summary())]
        text = '1. 发票10张\n2. 发票价税合计9622.06元\n3. 银行收入4笔\n4. 收入13000.50元\n5. 支出8笔\n6. 支出7180.74元'
        self.assertIsNone(reply_evidence_conflict(text, results, '甲企业2026年9月六项汇总'))
        self.assertIsNotNone(reply_evidence_conflict('1. 发票6张', results, '甲企业2026年9月六项汇总'))

    def test_complete_missing_total_has_current_parents(self):
        result = handle_tool('check_missing_purpose', json.dumps({'company_id': 'C001', 'year': 2026, 'month': 9}),
                             'U001', self.book, provenance=self.proof())
        self.assertIsNone(reply_evidence_conflict('缺用途5张，合计3780.68元。', [('check_missing_purpose', result)], '甲企业2026年9月缺用途'))

    def test_same_sql_blank_filter_and_money_lineage(self):
        data = self.query("SELECT invoice_no, amount_cents FROM invoices WHERE company_id='C002' AND invoice_date>='2026-09-01' AND invoice_date<'2026-10-01' AND is_blank(purpose) AND amount_cents>100000 ORDER BY amount_cents DESC", 'C002')
        self.assertIsNotNone(data['query_scope']['scope'])
        self.assertEqual({r[0] for r in data['rows']}, {'F005', 'F006'})
        self.assertIn('1280.50', json.dumps(data['derived']))
        self.assertIn('1000.01', json.dumps(data['derived']))

    def test_literal_between_keeps_original_sql_and_inclusive_conditions(self):
        # Public R2Q.1's first correctly executed read was downgraded to UNKNOWN.
        sql = ("SELECT company_id, transaction_no, transaction_date, amount_cents FROM bank_transactions "
               "WHERE company_id IN ('C001','C002') AND direction = '收入' "
               "AND transaction_date >= '2026-09-01' AND transaction_date <= '2026-09-20' "
               "AND amount_cents BETWEEN 50000 AND 150000 AND transaction_no <> 'T003' "
               "ORDER BY company_id, transaction_no")
        values = {'company_id': ['C001', 'C002'], 'periods': [(2026, 9)]}
        proof = ScopeProof('U001', values, dict.fromkeys(values, 'user_current'))
        workspace = BusinessSQL(self.book, 'U001', proof)
        self.addCleanup(workspace.close)
        _, data, _ = workspace.query(sql)
        self.assertEqual(data['rows'], [])
        self.assertEqual(data['sql'], sql)
        self.assertEqual(data['query_scope']['status'], 'VERIFIED')
        for operator, value in (('>=', 50000), ('<=', 150000)):
            self.assertIn({'field': 'amount_cents', 'operator': operator, 'value': value},
                          data['query_scope']['conditions'])
        # A different table, qualified field and date bounds use the same AST path.
        bounded = self.query("SELECT invoice_no,amount_cents FROM invoices i "
            "WHERE i.invoice_date BETWEEN '2026-09-01' AND '2026-09-20' "
            "AND i.amount_cents BETWEEN 50000 AND 100000 ORDER BY invoice_no")
        explicit = self.query("SELECT invoice_no,amount_cents FROM invoices i "
            "WHERE i.invoice_date>='2026-09-01' AND i.invoice_date<='2026-09-20' "
            "AND i.amount_cents>=50000 AND i.amount_cents<=100000 ORDER BY invoice_no")
        self.assertEqual(bounded['rows'], explicit['rows'])
        self.assertEqual(bounded['query_scope']['conditions'], explicit['query_scope']['conditions'])
        self.assertIn(('F001', 50000), bounded['rows'])
        self.assertIn(('F005', 100000), bounded['rows'])

    def test_unsupported_between_expressions_remain_unknown(self):
        for predicate in ("amount_cents NOT BETWEEN 50000 AND 100000",
                          "amount_cents BETWEEN 50000 AND amount_cents",
                          "amount_cents BETWEEN 50000 AND 100000 OR invoice_no='F001'"):
            with self.subTest(predicate=predicate):
                data = self.query('SELECT invoice_no,amount_cents FROM invoices WHERE ' + predicate)
                self.assertEqual(data['query_scope']['status'], 'UNKNOWN')
                self.assertIsNone(data['query_scope']['scope'])

    def test_agent_delivers_zero_comparison_from_current_between_aggregates(self):
        from app.agent import Agent
        from tests.test_answer_evidence import tool, final, facts

        stage = 0
        def model(messages, tools):
            nonlocal stage
            stage += 1
            if stage <= 2:
                company = ('C001', 'C002')[stage - 1]
                return tool('query_business_sql', sql=(
                    "SELECT COUNT(*) AS cnt, COALESCE(SUM(amount_cents),0) AS total_cents "
                    f"FROM bank_transactions WHERE company_id='{company}' AND direction='收入' "
                    "AND transaction_date BETWEEN '2026-09-01' AND '2026-09-20' "
                    "AND amount_cents BETWEEN 50000 AND 150000 AND transaction_no<>'T003'"))
            fs = facts(messages)
            counts = [f['ref'] for f in fs if f.get('metric') == ['bank_transactions', 'count_rows', None]]
            totals = [f['ref'] for f in fs if f.get('metric') == ['bank_transactions', 'sum', 'amount_cents']]
            return final(answer=[*counts, *totals, {'op': 'compare', 'left': totals[0], 'right': totals[1]}])

        agent = Agent('U001', self.book, model, mode='mock', trace_path=self.book.with_suffix('.jsonl'))
        answer = agent.ask('甲企业与乙企业2026年9月1日到20日银行收入，单笔500至1500元含边界，'
                           '排除T003。分别给笔数和小计，再比较两家小计。')
        self.assertIn('C001', answer)
        self.assertIn('C002', answer)
        self.assertEqual(answer.count('银行流水数量 0 笔'), 2)
        self.assertEqual(answer.count('银行流水金额合计 0.00 元'), 2)
        self.assertIn('相同，差额 0.00 元', answer)
        self.assertIn('按交易日期归属账期', answer)
        self.assertEqual(stage, 3)
        self.assertEqual(agent.last_response['delivery_source'], 'model_ordered_current_evidence')
        self.assertEqual(agent.write_receipt['status'], 'NOT_SUBMITTED')

    def test_window_count_has_page_and_full_set_distinction(self):
        data = self.query("SELECT company_id,invoice_no,invoice_date,amount_cents,COUNT(*) OVER() AS total_count FROM invoices WHERE company_id='C001' AND invoice_date>='2026-01-01' AND invoice_date<'2027-01-01' ORDER BY invoice_no LIMIT 10", annual=True)
        self.assertIsNotNone(data['query_scope']['scope'])
        self.assertTrue(data['query_scope']['limited'])
        self.assertEqual(len(data['rows']), 10)
        self.assertEqual({r[-1] for r in data['rows']}, {20})

    def test_conditional_window_sum_units(self):
        data = self.query("SELECT transaction_no,amount_cents,SUM(CASE WHEN direction='收入' THEN amount_cents ELSE 0 END) OVER() AS income_total_cents,SUM(CASE WHEN direction='收入' THEN 1 ELSE 0 END) OVER() AS income_count FROM bank_transactions WHERE company_id='C002' AND transaction_date>='2026-09-01' AND transaction_date<'2026-10-01'", 'C002')
        self.assertIsNotNone(data['query_scope']['scope'])
        self.assertEqual({r[-2] for r in data['rows']}, {1370075})
        self.assertEqual(data['query_scope']['columns'][2]['unit'], 'cents')
        self.assertEqual(data['query_scope']['columns'][3]['unit'], 'count')

    def test_unattributed_constant_not_money_proof(self):
        data = self.query("SELECT 123 AS amount_cents FROM invoices WHERE company_id='C001' AND invoice_date LIKE '2026-09-%'")
        self.assertIsNone(data['query_scope']['scope'])
        self.assertNotIn('1.23', json.dumps(data['derived']))

    def test_native_bank_direction_is_backward_compatible_and_filtered(self):
        args = {'company_id': 'C002', 'year': 2026, 'month': 9}
        all_rows = handle_tool('list_bank_transactions', json.dumps(args), 'U001', self.book, provenance=self.proof('C002'))
        filtered = handle_tool('list_bank_transactions', json.dumps({**args, 'direction': '收入'}), 'U001', self.book, provenance=self.proof('C002'))
        self.assertEqual(len(all_rows['data']), 12)
        self.assertEqual(filtered['status'], 'SUCCESS')
        self.assertEqual(len(filtered['data']), 4)
        self.assertEqual({r['direction'] for r in filtered['data']}, {'收入'})
        self.assertEqual(filtered['evidence']['finance_summary']['bank_income_count'], 4)
        self.assertNotIn('bank_expense_total', filtered['evidence']['finance_summary'])

    def test_direction_contract_rejects_unknown_enum(self):
        tool = next(x for x in TOOLS if x['function']['name'] == 'list_bank_transactions')
        self.assertEqual(set(tool['function']['parameters']['properties']['direction']['enum']), {'收入', '支出'})
        result = handle_tool('list_bank_transactions', json.dumps({'company_id': 'C002', 'year': 2026, 'month': 9, 'direction': 'income'}), 'U001', self.book, provenance=self.proof('C002'))
        self.assertEqual(result['status'], 'INVALID_ARGUMENTS')

    def test_reference_source_must_match_actor_and_company(self):
        result = {'status': 'SUCCESS', 'data': {'rows': [['F010', '现值']]},
                  'evidence': {'source': 'current_sqlite', 'query_scope': {
                      'scope': {'company_ids': ['C001'], 'periods': [[2026, 9]]},
                      'conditions': [{'field': 'company_id', 'operator': '=', 'value': 'C001'},
                                     {'field': 'invoice_no', 'operator': '=', 'value': 'F010'}]}}}
        call = [('query_business_sql', result)]
        kwargs = {'trusted_scope': self.proof(), 'actor': 'U001',
                  'trusted_references': [{'company_id': 'C001', 'invoice_no': 'F010'}]}
        self.assertIsNone(reply_evidence_conflict('F010备注为现值。', call, '刚才那张现在呢？', **kwargs))
        self.assertEqual(reply_evidence_conflict('现值', call, '刚才那张现在呢？',
                         **{**kwargs, 'actor': 'U002'}), 'unbound_query_filter')
        self.assertEqual(reply_evidence_conflict('现值', call, '刚才那张现在呢？',
                         **{**kwargs, 'trusted_references': [{'company_id': 'C002', 'invoice_no': 'F010'}]}), 'unbound_query_filter')

    def test_partial_or_invented_missing_total_not_accepted(self):
        result = handle_tool('check_missing_purpose', json.dumps({'company_id': 'C001', 'year': 2026, 'month': 9}),
                             'U001', self.book, provenance=self.proof())
        self.assertIsNotNone(reply_evidence_conflict('合计3780.69元。', [('check_missing_purpose', result)], '甲企业2026年9月缺用途'))
        result['evidence'].pop('derived', None)
        result['data']['missing_invoices'] = result['data']['missing_invoices'][:1]
        self.assertIsNotNone(reply_evidence_conflict('合计3780.68元。', [('check_missing_purpose', result)], '甲企业2026年9月缺用途'))

    def test_display_truncation_never_claims_complete_query_set(self):
        with patch('app.business_sql.MAX_RESULT_ROWS', 2):
            data = self.query("SELECT invoice_no,amount_cents FROM invoices WHERE company_id='C001' AND invoice_date LIKE '2026-09-%'")
        self.assertTrue(data['truncated'])
        self.assertFalse(data['query_scope']['query_set_complete'])
        self.assertTrue(data['query_scope']['display_truncated'])

    def test_unattributed_company_operator_stays_unknown(self):
        proof = ScopeProof('U001', {'company_id': ['C001', 'C002'], 'year': [2026], 'month': [9], 'periods': [(2026, 9)]},
                           dict.fromkeys(('company_id', 'year', 'month', 'periods'), 'user_current'))
        workspace = BusinessSQL(self.book, 'U001', proof)
        self.addCleanup(workspace.close)
        data = workspace.query("SELECT company_id,invoice_no FROM invoices WHERE company_id!='C001' AND invoice_date LIKE '2026-09-%'")[1]
        self.assertEqual({r[0] for r in data['rows']}, {'C002'})
        self.assertIsNone(data['query_scope']['scope'])

    def test_iso_year_prefix_and_window_count_attribute_original_sql(self):
        data = self.query("SELECT invoice_no,amount_cents,COUNT(*) OVER() AS total_count FROM invoices WHERE company_id='C001' AND invoice_date LIKE '2026%' ORDER BY invoice_no LIMIT 10", annual=True)
        self.assertIsNotNone(data['query_scope']['scope'])
        self.assertEqual(len(data['rows']), 10)
        self.assertEqual({r[-1] for r in data['rows']}, {20})
        self.assertEqual(len(data['query_scope']['scope']['periods']), 12)


if __name__ == '__main__':
    unittest.main()
