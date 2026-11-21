"""Bound user requirements, independent SQLite execution and result matching."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.business_request import bind
from app.business_request_delivery import check_sql, preflight, RequestDeliveryError, annotate, failure, accept_result
from app.business_sql import BusinessSQL
from app.cli_workspaces import import_workspace
from app.provenance import ScopeProof
from app.fact_arithmetic import sql_scalars, derive


class BusinessRequestDeliveryTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.book = Path(temp.name) / 'fictional.sqlite'
        import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', self.book)
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute('DELETE FROM invoices')
            for number, day, seller, amount in (
                ('A', '2026-09-02', '玄野服务有限公司', 179700),
                ('B', '2026-10-04', '玄野服务有限公司', 235700),
                ('C', '2026-09-03', '玄野设备有限公司', 100000),
                ('D', '2026-10-05', '玄野设备有限公司', 900000),
            ):
                db.execute('INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?)',
                           ('C001', number, day, seller, '项目', amount, '展会物料', ''))
        self.text = ('查C001 2026年9月和10月，销售方玄野服务有限公司用途展会物料的发票金额与张数，'
                     '按月比较十月比九月。')
        self.target = {'target_id': 'i1', 'object': 'invoices', 'company_ids': ['C001'],
            'company_quote': 'C001', 'periods': [[2026, 9], [2026, 10]], 'period_quote': '2026年9月和10月',
            'seller': {'mode': 'single', 'quote': '销售方玄野服务有限公司', 'value': '玄野服务有限公司'},
            'filters': [{'field': 'purpose', 'operator': '=', 'value': '展会物料', 'quote': '用途展会物料'}],
            'metrics': [{'operation': operation, 'field': field, 'quote': '金额与张数'}
                        for operation, field in [('sum', 'amount_cents'), ('count', '*')]],
            'group_by': ['period'], 'comparisons': []}
        self.sql = ("SELECT substr(invoice_date,1,7) AS ym,COUNT(*) AS n,SUM(amount_cents) AS cents "
                    "FROM invoices WHERE seller_name='玄野服务有限公司' AND purpose='展会物料' "
                    "GROUP BY ym ORDER BY ym")

    def requirement(self, target=None, text=None):
        return bind(json.dumps({'kind': 'read', 'targets': [target or self.target], 'unresolved': []}, ensure_ascii=False),
                    actor='U002', book=self.book, turn_id='turn1', request=text or self.text)

    def actual_result(self, sql):
        values = {'company_id': ['C001'], 'periods': [(2026, 9), (2026, 10)]}
        with closing(BusinessSQL(self.book, 'U002', ScopeProof('U002', values,
                             dict.fromkeys(values, 'user_current')))) as workspace:
            scope, data, _ = workspace.query(sql)
        return {'status': 'SUCCESS', 'data': data, 'evidence': {
            'source': 'current_sqlite', 'scope': scope, 'query_scope': data.pop('query_scope')}}

    def test_exact_period_amounts_counts_and_difference_have_same_requirement(self):
        request = self.requirement(); result = self.actual_result(self.sql)
        self.assertEqual(check_sql(request, result, 'U002', self.book), ('i1',))
        facts = {key: fact for key, (_, fact) in sql_scalars(result, 'result', '').items()}
        self.assertIn('560.00 元', derive({'op': 'subtract', 'left': 'cell.1.2', 'right': 'cell.0.2'}, facts))
        self.assertEqual(annotate(result, request, ('i1',))['evidence']['business_request']['coverage'], 'accepted_partial')

    def test_broad_seller_sql_cannot_define_the_user_requirement(self):
        result = self.actual_result(self.sql.replace("seller_name='玄野服务有限公司'", "seller_name LIKE '%玄野%'"))
        self.assertEqual(result['data']['rows'], [('2026-09', 2, 279700), ('2026-10', 2, 1135700)])
        with self.assertRaises(RequestDeliveryError):
            check_sql(self.requirement(), result, 'U002', self.book)

    def test_omitted_seller_condition_is_not_a_whole_company_requirement(self):
        result = self.actual_result(self.sql.replace("seller_name='玄野服务有限公司' AND ", ''))
        with self.assertRaises(RequestDeliveryError):
            check_sql(self.requirement(), result, 'U002', self.book)

    def test_dedicated_summary_and_list_cannot_drop_required_filters(self):
        request = self.requirement()
        for name in ('get_finance_summary', 'list_invoices'):
            with self.subTest(name=name), self.assertRaises(RequestDeliveryError) as caught:
                preflight(request, name, {'company_id': 'C001', 'year': 2026, 'month': 9}, 'U002', self.book)
            self.assertEqual(caught.exception.status, 'TOOL_CAPABILITY_MISMATCH')

    def test_conditional_measure_cannot_hide_a_seller_filter(self):
        text = '查C001 2026年9月和10月发票金额合计，不设置销售方条件。'
        target = {**self.target, 'seller': {'mode': 'none', 'quote': '不设置销售方条件', 'value': ''},
                  'filters': [], 'metrics': [{'operation': 'sum', 'field': 'amount_cents', 'quote': '金额合计'}],
                  'group_by': []}
        request = self.requirement(target, text)
        result = self.actual_result("SELECT SUM(CASE WHEN seller_name='玄野服务有限公司' THEN amount_cents ELSE 0 END) AS cents FROM invoices")
        with self.assertRaises(RequestDeliveryError):
            check_sql(request, result, 'U002', self.book)

    def test_count_cannot_satisfy_requested_money(self):
        target = {**self.target, 'metrics': [self.target['metrics'][0]]}
        result = self.actual_result(self.sql.replace(',SUM(amount_cents) AS cents', ''))
        with self.assertRaises(RequestDeliveryError):
            check_sql(self.requirement(target), result, 'U002', self.book)

    def test_merged_periods_cannot_satisfy_monthly_groups(self):
        result = self.actual_result("SELECT COUNT(*) AS n,SUM(amount_cents) AS cents FROM invoices "
                                   "WHERE seller_name='玄野服务有限公司' AND purpose='展会物料'")
        with self.assertRaises(RequestDeliveryError):
            check_sql(self.requirement(), result, 'U002', self.book)

    def test_other_actor_is_denied_without_disclosing_request_catalog(self):
        request = self.requirement()
        with self.assertRaises(RequestDeliveryError) as caught:
            preflight(request, 'list_invoices', {'company_id': 'C001', 'year': 2026, 'month': 9}, 'U001', self.book)
        self.assertEqual(caught.exception.status, 'DENIED')
        rejected = failure(caught.exception, request)
        self.assertIsNone(rejected['data'])
        self.assertNotIn('玄野', json.dumps(rejected, ensure_ascii=False))

    def test_registry_rejects_filter_omission_before_dedicated_execution(self):
        from app.tool_registry import handle_tool
        request = self.requirement()
        for tool in ('get_finance_summary', 'list_invoices'):
            with self.subTest(tool=tool), patch('app.tool_registry._handle_tool') as execute:
                result = handle_tool(tool, json.dumps({'company_id': 'C001', 'year': 2026, 'month': 9}),
                                     'U002', self.book, business_request=request)
                self.assertEqual(result['status'], 'TOOL_CAPABILITY_MISMATCH')
                self.assertIsNone(result['data'])
                execute.assert_not_called()

    def test_bank_summary_projects_only_requested_metric_without_fake_zero(self):
        from app.tool_registry import handle_tool
        from app.tui import AgentWorkspace
        from app.responses import render_information, render_query_conclusion
        from app.answer_evidence import catalog
        text = '查C001 2026年9月和10月银行收入合计，按月。'
        target = {**self.target, 'object': 'bank_transactions', 'seller': None,
                  'filters': [{'field': 'direction', 'operator': '=', 'value': '收入', 'quote': '银行收入合计'}],
                  'metrics': [{'operation': 'sum', 'field': 'amount_cents', 'quote': '银行收入合计'}]}
        request = self.requirement(target, text)
        result = handle_tool('get_finance_summary', json.dumps({'company_id': 'C001', 'year': 2026, 'month': 9}),
                             'U002', self.book, business_request=request)
        self.assertEqual(result['status'], 'SUCCESS', result)
        self.assertEqual(set(result['data']), {'bank_income_total'})
        with closing(sqlite3.connect(self.book)) as db:
            expected = db.execute("SELECT SUM(amount_cents) FROM bank_transactions WHERE company_id='C001' "
                                  "AND transaction_date LIKE '2026-09%' AND direction='收入'").fetchone()[0]
        from app.fact_arithmetic import cents
        self.assertEqual(cents(result['data']['bank_income_total']), expected)
        card = AgentWorkspace.business_card('get_finance_summary', result['data'], result['evidence'])
        self.assertIn('银行收入合计', card[1])
        self.assertNotIn('发票价税合计', card[1])
        self.assertNotIn('银行支出', card[1])
        results = [('get_finance_summary', result)]
        self.assertIn('银行收入合计', render_information(results))
        self.assertIn('银行收入合计', render_query_conclusion(results))
        facts = catalog(results, {}, 'turn1')
        scalar_facts = [fact for fact in facts.values() if fact.get('type') == 'scalar']
        self.assertEqual(len(scalar_facts), 1)
        self.assertEqual(scalar_facts[0]['metric'], ('bank_transactions', 'sum', 'amount_cents'))

    def test_model_like_request_dictionary_does_not_supply_runtime_authority(self):
        from app.tool_registry import handle_tool
        result = handle_tool('list_invoices', json.dumps({'company_id': 'C001', 'year': 2026, 'month': 9}),
                             'U002', self.book, business_request={'targets': [self.target]})
        self.assertEqual(result['status'], 'REQUEST_UNRESOLVED')
        self.assertIsNone(result['data'])

    def september(self):
        text = '查C001 2026年9月，销售方玄野服务有限公司用途展会物料的发票金额与张数。'
        target = {**self.target, 'periods': [[2026, 9]], 'period_quote': '2026年9月', 'group_by': []}
        return target, text

    def test_half_month_predicate_cannot_be_presented_as_month_total(self):
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute('INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?)',
                       ('C001', 'LATE', '2026-09-21', '玄野服务有限公司', '项目B', 88000, '展会物料', ''))
        target, text = self.september()
        request = self.requirement(target, text)
        result = self.actual_result("SELECT COUNT(*) AS n,SUM(amount_cents) AS cents FROM invoices "
            "WHERE seller_name='玄野服务有限公司' AND purpose='展会物料' "
            "AND invoice_date>='2026-09-15' AND invoice_date<'2026-10-01'")
        self.assertEqual(result['data']['rows'], [(1, 88000)])
        with self.assertRaises(RequestDeliveryError) as caught:
            accept_result(request, 'query_business_sql', result, 'U002', self.book)
        self.assertIn('日期', str(caught.exception))

    def test_unrequested_item_groups_are_identity_clues_without_financial_scalars(self):
        from app.answer_evidence import catalog
        from app.tui import AgentWorkspace
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute('INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?)',
                       ('C001', 'LATE', '2026-09-21', '玄野服务有限公司', '项目B', 88000, '展会物料', ''))
        target, text = self.september()
        request = self.requirement(target, text)
        result = self.actual_result("SELECT item_name,COUNT(*) AS n,SUM(amount_cents) AS cents FROM invoices "
            "WHERE seller_name='玄野服务有限公司' AND purpose='展会物料' "
            "AND invoice_date>='2026-09-01' AND invoice_date<'2026-10-01' GROUP BY item_name")
        accepted = accept_result(request, 'query_business_sql', result, 'U002', self.book)
        self.assertTrue(accepted['data']['request_identity_evidence_only'])
        self.assertEqual(accepted['data']['columns'], ['item_name'])
        self.assertEqual(accepted['data']['derived'], [{}, {}])
        card = AgentWorkspace.business_card('query_business_sql', accepted['data'], accepted['evidence'])
        self.assertEqual(card[0], '查询对象线索')
        self.assertIn('不是金额或张数统计', card[1])
        self.assertNotIn('880.00', card[1])
        facts = catalog([('query_business_sql', accepted)], {}, 'turn1')
        self.assertFalse(any(f.get('type') == 'scalar' for f in facts.values()))

    def test_summary_cannot_fulfill_seller_grouping(self):
        from app.tool_registry import handle_tool
        text = '查C001 2026年9月和10月，发票金额与张数按销售方分别列示，不设置销售方条件。'
        target = {**self.target, 'seller': {'mode': 'none', 'quote': '不设置销售方条件', 'value': ''},
                  'filters': [], 'group_by': ['seller_name']}
        request = self.requirement(target, text)
        with patch('app.tool_registry._handle_tool') as execute:
            result = handle_tool('get_finance_summary', json.dumps({'company_id': 'C001', 'year': 2026, 'month': 9}),
                                 'U002', self.book, business_request=request)
        self.assertEqual(result['status'], 'TOOL_CAPABILITY_MISMATCH')
        self.assertIsNone(result['data'])
        execute.assert_not_called()

    def test_execution_subscopes_do_not_replace_the_current_request(self):
        from app.tool_registry import handle_tool
        request = self.requirement()
        before = request.metadata()
        values = {'company_id': ['C001'], 'periods': [(2026, 9), (2026, 10)]}
        parent = BusinessSQL(self.book, 'U002', ScopeProof('U002', values, dict.fromkeys(values, 'user_current')))
        self.addCleanup(parent.close)
        sql = ("SELECT COUNT(*) AS n,SUM(amount_cents) AS cents FROM invoices "
               "WHERE seller_name='玄野服务有限公司' AND purpose='展会物料'")
        results = []
        for month, expected in ((9, 179700), (10, 235700)):
            scope = {'company_id': 'C001', 'periods': [{'year': 2026, 'month': month}],
                     'company_quote': 'C001', 'period_quote': '2026年9月和10月'}
            result = handle_tool('query_business_sql', json.dumps({'sql': sql, 'read_scope': scope}),
                                 'U002', self.book, sql_workspace=parent, business_request=request)
            self.assertEqual(result['status'], 'SUCCESS', result)
            self.assertEqual(result['data']['rows'], [(1, expected)])
            self.assertEqual(result['evidence']['scope']['month'], month)
            self.assertFalse(result['evidence']['read_version']['global_revision_known'])
            self.assertEqual(request.metadata(), before)
            results.append(('query_business_sql', result))
        self.assertEqual(parent.scope()['periods'], ((2026, 9), (2026, 10)))
        from app.business_request_delivery import assess_results
        coverage = assess_results(request, results)
        self.assertTrue(coverage['complete'], coverage)
        self.assertFalse(coverage['final_delivery_verified'])

    def test_discovery_discards_unrequested_purpose_buckets_without_new_numbers(self):
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute('INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?)',
                       ('C001', 'NOISE', '2026-09-25', '玄野服务有限公司', '项目', 998877, '无关用途', ''))
        request = self.requirement()
        result = self.actual_result("SELECT substr(invoice_date,1,7) AS ym,seller_name,purpose,"
            "COUNT(*) AS n,SUM(amount_cents) AS cents FROM invoices WHERE seller_name='玄野服务有限公司' "
            "GROUP BY ym,seller_name,purpose ORDER BY ym,purpose")
        accepted = accept_result(request, 'query_business_sql', result, 'U002', self.book)
        self.assertEqual(accepted['data']['rows'], [('2026-09', '玄野服务有限公司', '展会物料', 1, 179700),
                                                   ('2026-10', '玄野服务有限公司', '展会物料', 1, 235700)])
        self.assertNotIn(998877, [v for row in accepted['data']['rows'] for v in row])
        self.assertEqual(accepted['data']['sql'], result['data']['sql'])

    def test_explicit_set_discovery_keeps_only_identity_then_real_total_succeeds(self):
        text = self.text.replace('销售方玄野服务有限公司', '所有销售方名称包含玄野')
        target = json.loads(json.dumps(self.target))
        target['seller'] = {'mode': 'set', 'quote': '所有销售方名称包含玄野', 'value': '玄野'}
        request = self.requirement(target, text)
        discovered = self.actual_result("SELECT substr(invoice_date,1,7) AS ym,seller_name,purpose,"
            "COUNT(*) AS n,SUM(amount_cents) AS cents FROM invoices WHERE seller_name LIKE '%玄野%' "
            "GROUP BY ym,seller_name,purpose ORDER BY ym,seller_name")
        clues = accept_result(request, 'query_business_sql', discovered, 'U002', self.book)
        self.assertTrue(clues['data']['request_identity_evidence_only'])
        self.assertEqual(sql_scalars(clues, 'clues', ''), {})
        self.assertEqual(clues['data']['request_projection']['source_column_indices'], [0, 1, 2])
        self.assertFalse(any(type(value) is int for row in clues['data']['rows'] for value in row))
        total = accept_result(request, 'query_business_sql', self.actual_result(self.sql.replace(
            "seller_name='玄野服务有限公司'", "seller_name LIKE '%玄野%'")), 'U002', self.book)
        self.assertEqual(total['data']['rows'], [('2026-09', 2, 279700), ('2026-10', 2, 1135700)])
        # A single seller's ungrouped total still cannot satisfy the whole set.
        with self.assertRaises(RequestDeliveryError):
            accept_result(request, 'query_business_sql', self.actual_result(self.sql), 'U002', self.book)

    def test_final_selection_obeys_comparison_direction_and_reports_missing_values(self):
        from app.answer_evidence import catalog
        from app.business_request_delivery import assess_selection
        target = json.loads(json.dumps(self.target))
        target['comparisons'] = [{'operation': 'subtract', 'metric_operation': 'sum',
            'metric_field': 'amount_cents', 'left_period': [2026, 10], 'right_period': [2026, 9],
            'quote': '十月比九月'}]
        request = self.requirement(target)
        result = accept_result(request, 'query_business_sql', self.actual_result(self.sql), 'U002', self.book)
        results = [('query_business_sql', result)]
        facts = catalog(results, {}, 'selection')
        scalars = [f for f in facts.values() if f.get('type') == 'scalar']
        money = {next(iter(map(tuple, f['scope']['periods']))): f['ref'] for f in scalars if f['unit'] == 'cents'}
        left, right = money[(2026, 10)], money[(2026, 9)]
        comparison = {'op': 'subtract', 'left': left, 'right': right}
        complete = assess_selection(request, [f['ref'] for f in scalars] + [comparison], facts, results)
        self.assertTrue(complete['complete'], complete)
        for invalid in ({'op': 'subtract', 'left': right, 'right': left},
                        {'op': 'compare', 'left': left, 'right': right}):
            checked = assess_selection(request, [invalid], facts, results)
            self.assertFalse(checked['valid'], checked)
        partial = assess_selection(request, [right], facts, results)
        self.assertTrue(partial['valid']); self.assertFalse(partial['complete'])
        self.assertIn('i1:comparison.0', partial['missing'])
        # Merely using parents for arithmetic does not display their values.
        partial = assess_selection(request, [comparison], facts, results)
        self.assertTrue(partial['valid']); self.assertFalse(partial['complete'])
        whole = assess_selection(request, ['selection:r0.result', comparison], facts, results)
        self.assertTrue(whole['complete'], whole)

    def test_selecting_one_item_group_cannot_complete_all_requested_groups(self):
        from app.answer_evidence import catalog
        from app.business_request_delivery import assess_selection
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute('INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?)',
                ('C001', 'PART', '2026-09-25', '玄野服务有限公司', '配件', 12000, '展会物料', ''))
        target = json.loads(json.dumps(self.target))
        target['group_by'].append('item_name')
        request = self.requirement(target)
        sql = self.sql.replace(' AS ym,COUNT', ' AS ym,item_name,COUNT').replace(
            'GROUP BY ym ORDER BY ym', 'GROUP BY ym,item_name ORDER BY ym,item_name')
        result = accept_result(request, 'query_business_sql', self.actual_result(sql), 'U002', self.book)
        results = [('query_business_sql', result)]
        facts = catalog(results, {}, 'group')
        subset = [ref for ref, fact in facts.items() if fact.get('type') == 'scalar'
                  and fact['dimensions']['item_name'] == '项目']
        partial = assess_selection(request, subset, facts, results)
        self.assertFalse(partial['complete']); self.assertIn('i1:groups_not_delivered', partial['missing'])
        self.assertTrue(assess_selection(request, ['group:r0.result'], facts, results)['complete'])

    def test_unproved_display_projection_cannot_block_or_replace_proved_core(self):
        from app.tool_registry import handle_tool
        from app.answer_evidence import catalog
        from app.business_request_delivery import assess_selection
        request=self.requirement()
        sql=self.sql.replace('SUM(amount_cents) AS cents',
            'SUM(amount_cents) AS cents,ROUND(SUM(amount_cents)/100.0,2) AS yuan')
        legacy=self.actual_result(sql)
        self.assertEqual(legacy['evidence']['query_scope']['status'],'UNKNOWN')
        values={'company_id':['C001'],'periods':[(2026,9),(2026,10)]}
        with closing(BusinessSQL(self.book,'U002',ScopeProof('U002',values,
                     dict.fromkeys(values,'user_current')))) as workspace:
            accepted=handle_tool('query_business_sql',json.dumps({'sql':sql}),'U002',self.book,
                                sql_workspace=workspace,business_request=request)
        self.assertEqual(accepted['status'],'SUCCESS',accepted)
        self.assertEqual(accepted['data']['sql'],sql)
        self.assertEqual(accepted['data']['rows'],[('2026-09',1,179700),('2026-10',1,235700)])
        projection=accepted['data']['request_projection']
        self.assertEqual(projection['source_column_indices'],[0,1,2])
        self.assertFalse(projection['source_projection_complete'])
        self.assertEqual(projection['source_columns'][3]['kind'],'unattributed')
        results=[('query_business_sql',accepted)];facts=catalog(results,{},'display')
        self.assertTrue(assess_selection(request,['display:r0.result'],facts,results)['complete'])

    def test_unproved_projection_does_not_waive_filter_or_group_proof(self):
        from app.tool_registry import handle_tool
        request=self.requirement()
        sql=self.sql.replace('SUM(amount_cents) AS cents',
            'SUM(amount_cents) AS cents,ROUND(SUM(amount_cents)/100.0,2) AS yuan')
        values={'company_id':['C001'],'periods':[(2026,9),(2026,10)]}
        variants=[(sql.replace("seller_name='玄野服务有限公司'","seller_name LIKE '%玄野%'"),'SCOPE_MISMATCH'),
                  (sql.replace("purpose='展会物料'","purpose='展会物料' AND amount_cents+0>0"),'SQL_EVIDENCE_UNSUPPORTED')]
        for candidate,expected in variants:
            with self.subTest(sql=candidate),closing(BusinessSQL(self.book,'U002',ScopeProof('U002',values,
                    dict.fromkeys(values,'user_current')))) as workspace:
                result=handle_tool('query_business_sql',json.dumps({'sql':candidate}),'U002',self.book,
                                   sql_workspace=workspace,business_request=request)
                self.assertEqual(result['status'],expected,result);self.assertIsNone(result['data'])

    def test_partial_details_name_missing_columns_without_relaxing_coverage(self):
        from app.business_request_delivery import assess_results
        target={**self.target,'metrics':[{'operation':'details','field':'*','quote':'发票'}],'group_by':[]}
        request=self.requirement(target)
        columns='company_id,invoice_no,invoice_date,seller_name,amount_cents,purpose,remark'
        tail=" FROM invoices WHERE seller_name='玄野服务有限公司' AND purpose='展会物料'"
        partial=accept_result(request,'query_business_sql',self.actual_result('SELECT '+columns+tail),'U002',self.book)
        self.assertFalse(assess_results(request,[('query_business_sql',partial)])['complete'])
        self.assertEqual(partial['evidence']['business_request']['missing'],[
            {'target_id':'i1','operation':'details','field':'*','missing_columns':['item_name']}])
        without_company=accept_result(request,'query_business_sql',self.actual_result(
            'SELECT '+columns.removeprefix('company_id,')+tail),'U002',self.book)
        self.assertFalse(assess_results(request,[('query_business_sql',without_company)])['complete'])
        self.assertEqual(without_company['evidence']['business_request']['missing'],[
            {'target_id':'i1','operation':'details','field':'*','missing_columns':['company_id','item_name']}])
        full=accept_result(request,'query_business_sql',self.actual_result('SELECT '+columns+',item_name'+tail),'U002',self.book)
        self.assertTrue(assess_results(request,[('query_business_sql',full)])['complete'])
        self.assertEqual(full['evidence']['business_request']['missing'],[])


class RequestedDetailFieldsTests(unittest.TestCase):
    """Display coverage and fresh continuation identity are separate contracts."""
    # Reuse the fixture, not the aggregate tests, for this bounded regression.
    setUp = BusinessRequestDeliveryTests.setUp

    def detail(self, fields=('invoice_no', 'amount_cents', 'purpose', 'remark')):
        labels = {'invoice_no':'票号','amount_cents':'金额','purpose':'用途','remark':'备注'}
        requested = '列出全部业务字段' if fields == ('*',) else '列出' + '、'.join(labels[f] for f in fields)
        text = '查C001 2026年9月销售方玄野服务有限公司用途展会物料的发票，' + requested + '。'
        target = {**self.target, 'periods': [[2026, 9]], 'period_quote': '2026年9月',
                  'group_by': [], 'metrics': [
                      {'operation': 'details', 'field': field, 'quote': requested}
                      for field in fields]}
        request = bind({'kind': 'read', 'targets': [target], 'unresolved': []},
                       actor='U001', book=self.book, turn_id='detail', request=text)
        return request

    def detail_result(self, request, columns):
        from app.tool_registry import handle_tool
        values = {'company_id': ['C001'], 'periods': [(2026, 9)]}
        with closing(BusinessSQL(self.book, 'U001', ScopeProof('U001', values,
                     dict.fromkeys(values, 'user_current')))) as workspace:
            return handle_tool('query_business_sql', json.dumps({'sql': 'SELECT ' + columns +
                " FROM invoices WHERE seller_name='玄野服务有限公司' AND purpose='展会物料'"}),
                'U001', self.book, sql_workspace=workspace, business_request=request)

    def test_four_requested_fields_complete_in_first_card_and_final_fact(self):
        from app.answer_evidence import catalog, select
        from app.business_request_delivery import assess_selection
        from app.tui import AgentWorkspace
        request = self.detail()
        result = self.detail_result(request, 'invoice_no,amount_cents,purpose,remark')
        self.assertEqual(result['status'], 'SUCCESS', result)
        results = [('query_business_sql', result)]; facts = catalog(results, {}, 'detail')
        self.assertTrue(assess_selection(request, ['detail:r0.result'], facts, results)['complete'])
        _, card = AgentWorkspace.business_card('query_business_sql', result['data'], result['evidence'])
        final = select(['detail:r0.result'], facts)
        for text in (card, final):
            for value in ('发票编号：A', '1797.00 元', '用途：展会物料', '备注：未填写'):
                self.assertIn(value, text)
            self.assertNotIn('SQL 列名', text)
        self.assertEqual(result['data']['columns'], ['invoice_no','amount_cents','purpose','remark'])

    def test_missing_requested_field_and_full_record_are_still_partial(self):
        from app.business_request_delivery import assess_results
        for fields, columns, missing in (
                (('invoice_no','amount_cents','purpose','remark'), 'invoice_no,amount_cents,purpose', ['remark']),
                (('*',), 'invoice_no,amount_cents,purpose,remark', ['company_id','invoice_date','item_name','seller_name'])):
            with self.subTest(fields=fields):
                request = self.detail(fields); result = self.detail_result(request, columns)
                self.assertEqual(result['status'], 'SUCCESS', result)
                self.assertFalse(assess_results(request, [('query_business_sql', result)])['complete'])
                self.assertEqual(result['evidence']['business_request']['missing'][0]['missing_columns'], missing)

    def test_continuation_needs_real_display_identity_and_fresh_read(self):
        from app.agent import Agent
        from app.invoice_action import change_invoice
        from app.business_request_delivery import assess_results
        for fields in (('invoice_no','amount_cents','purpose','remark'), ('amount_cents','purpose','remark')):
            with self.subTest(fields=fields):
                request = self.detail(fields)
                result = self.detail_result(request, ','.join(fields))
                self.assertTrue(assess_results(request, [('query_business_sql', result)])['complete'])
                agent = Agent('U001', self.book, lambda *_: self.fail('No API'), mode='mock',
                              trace_path=self.book.with_suffix('.jsonl'))
                agent.trace_id = 'continuation'
                # Match the GUI's actual displayed-turn allowlist.
                agent.context.display_ids = []
                agent.record_query_display([('query_business_sql', result)])
                with closing(sqlite3.connect(self.book)) as db, db:
                    db.execute("UPDATE invoices SET remark='新读值' WHERE company_id='C001' AND invoice_no='A'")
                outcome, pending, planned, reads = change_invoice(agent,
                    {'company_id':'C001','invoice_no':'A','field':'purpose'}, None,
                    '这张先准备补充用途，具体内容稍后提供。')
                self.assertIsNone(planned)
                if 'invoice_no' in fields:
                    self.assertEqual(outcome['status'], 'WAITING_USER', outcome)
                    self.assertEqual(pending['scope']['invoice_no'], ['A'])
                    self.assertEqual(pending['missing_fields'], ('new_value',))
                    self.assertEqual(reads[0][1]['data']['remark'], '新读值')
                else:
                    self.assertEqual(outcome['status'], 'SCOPE_MISMATCH', outcome)
                    self.assertIsNone(pending)
                    self.assertFalse(reads)
                self.assertFalse(agent.update_session.drafts)
                with closing(sqlite3.connect(self.book)) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0], 0)

    def test_incomplete_change_route_after_read_reaches_original_pending_owner(self):
        from app.agent import Agent
        from tests.test_answer_evidence import facts, final, tool
        from tests.test_business_request_single_entry import semantic_input
        request = self.detail()
        target = {**self.target, 'periods':[[2026,9]], 'period_quote':'2026年9月', 'group_by':[],
                  'metrics':[{'operation':m.operation,'field':m.field,'quote':m.source.quote}
                             for m in request.targets[0].metrics]}
        phase = 'read'; calls = []
        def model(context, tools):
            calls.append(phase)
            if semantic_input(context):
                if phase == 'change':
                    payload = json.loads(context[1]['content'])
                    self.assertIsNotNone(payload['previous_requirement'])
                    routes = payload['business_definition']['protocol']['entry_routes']
                    self.assertEqual(routes['legacy']['output'], {'kind':'legacy'})
                    return {'role':'assistant','content':'{"kind":"legacy"}'}
                return {'role':'assistant','content':json.dumps(
                    {'kind':'read','targets':[target],'unresolved':[]},ensure_ascii=False)}
            if phase == 'change':
                return tool('change_invoice',company_id='C001',invoice_no='A',field='purpose')
            if any(f.get('type') == 'result' for f in facts(context)):
                return final(answer=[f['ref'] for f in facts(context) if f['type']=='result'])
            return tool('query_business_sql',sql='SELECT invoice_no,amount_cents,purpose,remark '
                "FROM invoices WHERE seller_name='玄野服务有限公司' AND purpose='展会物料'")
        agent = Agent('U001',self.book,model,mode='mock',trace_path=self.book.with_suffix('.jsonl'))
        agent.context.display_ids = []
        agent.ask(request.current_source.quote)
        self.assertTrue(agent.last_response['business_request_final_coverage']['complete'],agent.last_response)
        phase = 'change'
        agent.ask('就查询中编号A这一张，先准备补充用途，具体内容我稍后再给。')
        self.assertEqual(calls.count('change'),2,agent.last_response)
        self.assertEqual(agent.last_response['execution']['stop_reason'],'WAITING_USER')
        self.assertEqual(agent.pending_intent['scope']['invoice_no'],['A'])
        self.assertEqual(agent.pending_intent['missing_fields'],('new_value',))
        self.assertIsNone(agent.business_request)
        self.assertFalse(agent.update_session.drafts);self.assertFalse(agent.update_session.confirmations)
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0],0)
