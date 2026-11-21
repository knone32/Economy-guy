"""Verified statistics close on the original loop; no synthetic final model reply."""
from contextlib import closing
from copy import deepcopy
import json
import sqlite3
import unittest

from app.agent import Agent
from app.answer_evidence import catalog, select
from app.business_request_delivery import accept_result, verified_statistics_answer, assess_selection
from tests import test_business_request_delivery as delivery_fixture


class VerifiedFactFinishTests(unittest.TestCase):
    setUp = delivery_fixture.BusinessRequestDeliveryTests.setUp
    requirement = delivery_fixture.BusinessRequestDeliveryTests.requirement
    actual_result = delivery_fixture.BusinessRequestDeliveryTests.actual_result

    def accepted(self, request, sql=None):
        return accept_result(request, 'query_business_sql', self.actual_result(sql or self.sql), 'U002', self.book)

    def test_actual_agent_delivers_months_counts_and_directed_difference_without_final_model_call(self):
        target = deepcopy(self.target)
        target['comparisons'] = [{'operation': 'subtract', 'metric_operation': 'sum',
            'metric_field': 'amount_cents', 'left_period': [2026, 10], 'right_period': [2026, 9],
            'quote': '十月比九月'}]
        replies = iter([
            {'role': 'assistant', 'content': json.dumps({'kind': 'read', 'targets': [target], 'unresolved': []}, ensure_ascii=False)},
            {'role': 'assistant', 'tool_calls': [{'id': 'real-query', 'type': 'function', 'function': {
                'name': 'query_business_sql', 'arguments': json.dumps({'sql': self.sql}, ensure_ascii=False)}}]},
        ])
        calls = []
        def model(messages, tools):
            calls.append(1)
            return next(replies)
        agent = Agent('U002', self.book, model, mode='mock', trace_path=self.book.parent/'trace.jsonl')
        answer = agent.ask(self.text)
        self.assertEqual(len(calls), 2, answer)
        self.assertEqual(agent.last_response['delivery_source'], 'runtime_ordered_current_evidence')
        self.assertTrue(agent.last_response['business_request_final_coverage']['complete'])
        self.assertEqual(agent.last_response['fulfillment']['status'], 'VERIFIED_GOALS')
        for value in ('1797.00', '2357.00', '560.00', '1 张', '玄野服务有限公司'):
            self.assertIn(value, answer)
        call_ids = [c['id'] for m in agent.messages for c in m.get('tool_calls') or []]
        result_ids = [m['tool_call_id'] for m in agent.messages if m.get('role') == 'tool']
        self.assertCountEqual(call_ids, result_ids)
        self.assertEqual(agent.write_receipt['status'], 'NOT_SUBMITTED')
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0], 0)

    def test_partial_or_stale_execution_cannot_auto_complete(self):
        request = self.requirement()
        partial = self.accepted(request, self.sql.replace('GROUP BY', "AND invoice_date<'2026-10-01' GROUP BY"))
        results = [('query_business_sql', partial)]
        self.assertIsNone(verified_statistics_answer(request, catalog(results, {}, 'partial'), results))
        stale = self.accepted(request)
        stale['evidence']['business_request']['revision'] += 1
        results = [('query_business_sql', stale)]
        self.assertIsNone(verified_statistics_answer(request, catalog(results, {}, 'stale'), results))

    def test_conflicting_actual_readings_are_not_silently_selected(self):
        request = self.requirement()
        first = self.accepted(request)
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute("UPDATE invoices SET amount_cents=amount_cents+1 WHERE invoice_no='A'")
        results = [('query_business_sql', first), ('query_business_sql', self.accepted(request))]
        self.assertIsNone(verified_statistics_answer(request, catalog(results, {}, 'changed'), results))

    def test_legal_collection_remains_deliverable_and_keeps_every_group(self):
        text = self.text.replace('销售方玄野服务有限公司', '所有名称包含玄野的销售方')
        target = deepcopy(self.target)
        target['seller'] = {'mode': 'set', 'quote': '所有名称包含玄野的销售方', 'value': '玄野'}
        target['group_by'].append('seller_name')
        request = self.requirement(target, text)
        sql = self.sql.replace("seller_name='玄野服务有限公司'", "seller_name LIKE '%玄野%'").replace(
            ' AS ym,COUNT', ' AS ym,seller_name,COUNT').replace('GROUP BY ym ORDER BY ym', 'GROUP BY ym,seller_name ORDER BY ym,seller_name')
        results = [('query_business_sql', self.accepted(request, sql))]
        facts = catalog(results, {}, 'collection')
        answer = verified_statistics_answer(request, facts, results)
        self.assertIsNotNone(answer)
        self.assertTrue(assess_selection(request, answer, facts, results)['complete'])
        rendered = select(answer, facts)
        for value in ('玄野服务有限公司', '玄野设备有限公司', '1000.00', '9000.00'):
            self.assertIn(value, rendered)

    def test_rejected_scope_and_details_do_not_become_complete_statistics(self):
        from app.business_request_delivery import RequestDeliveryError
        request = self.requirement()
        with self.assertRaises(RequestDeliveryError):
            self.accepted(request, self.sql.replace("seller_name='玄野服务有限公司'", "seller_name LIKE '%玄野%'"))
        failed = {'status': 'SCOPE_MISMATCH', 'data': None, 'evidence': {}}
        self.assertIsNone(verified_statistics_answer(request, {}, [('query_business_sql', failed)]))
        details = deepcopy(self.target)
        details['metrics'] = [{'operation': 'details', 'field': '*', 'quote': '发票金额与张数'}]
        details['group_by'] = []
        self.assertIsNone(verified_statistics_answer(self.requirement(details), {}, []))
