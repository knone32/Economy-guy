"""Program-contract regressions. Scripted replies are not NLU measurements."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from app.agent import Agent
from app.answer_evidence import catalog, select
from app.cli_workspaces import import_workspace
from app.responses import parse_final


def tool(name, **args):
    return {'role': 'assistant', 'tool_calls': [{'id': 'call-read', 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(args)}}]}


def final(text='已根据本轮证据回答。', **fields):
    return {'role': 'assistant', 'content': json.dumps({'kind': 'information', 'text': text, **fields}, ensure_ascii=False)}


def facts(messages):
    return json.loads(next(m['content'] for m in reversed(messages)
                          if m.get('name') == 'answer_catalog').rsplit('\n', 1)[-1])


class AnswerEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.book = Path(self.tmp.name) / 'sample.sqlite3'
        import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', self.book)

    def agent(self, model, user='U001'):
        return Agent(user, self.book, model, mode='mock', trace_path=self.book.with_suffix('.jsonl'))

    def summary_agent(self, answer):
        stage = 0
        def model(messages, tools):
            nonlocal stage
            stage += 1
            if stage % 2:
                return tool('get_finance_summary', company_id='C001', year=2026, month=9)
            return answer(facts(messages))
        return self.agent(model)

    def test_model_selects_metric_order_but_cannot_relabel_values(self):
        order = ('bank_income_count', 'bank_income_total', 'bank_expense_count',
                 'bank_expense_total', 'invoice_count', 'invoice_total')
        agent = self.summary_agent(lambda fs: final('已经保存全部修改，发票4张、收入10笔。',
            answer=[next(f['ref'] for f in fs if f['ref'].endswith('.' + key)) for key in order]))
        answer = agent.ask('甲企业2026年9月，银行先报收入和支出笔数及金额，再报发票张数和价税合计。')
        self.assertLess(answer.index('银行收入笔数'), answer.index('发票张数'))
        self.assertIn('银行收入笔数 4 笔', answer)
        self.assertIn('发票张数 10 张', answer)
        self.assertNotIn('已经保存', answer)
        self.assertNotIn('发票4张', answer)
        self.assertEqual(agent.last_response['delivery_source'], 'model_ordered_current_evidence')
        self.assertEqual(agent.write_receipt['status'], 'NOT_SUBMITTED')

    def test_legacy_text_falls_back_to_real_facts_without_false_success(self):
        agent = self.summary_agent(lambda fs: final('修改已经保存成功，银行收入为零。'))
        answer = agent.ask('查询甲企业2026年9月发票及银行汇总。')
        self.assertNotIn('修改已经保存成功', answer)
        self.assertIn('13000.50', answer)
        self.assertEqual(agent.write_receipt['status'], 'NOT_SUBMITTED')
        with closing(sqlite3.connect(self.book)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0], 0)

    def test_selected_summary_metrics_keep_their_date_and_rule_basis(self):
        agent = self.summary_agent(lambda fs: final(answer=[
            next(f['ref'] for f in fs if f['ref'].endswith('.bank_income_total')),
            next(f['ref'] for f in fs if f['ref'].endswith('.invoice_total'))]))
        answer = agent.ask('甲企业2026年9月，给出银行收入和发票价税合计，并说明归属日期和统计依据。')
        self.assertIn('13000.50', answer)
        self.assertIn('交易日期', answer)
        self.assertIn('开票日期', answer)
        self.assertIn('R001 v1.0', answer)
        self.assertIn('生效日期 2026-01-01', answer)
        self.assertIn('来源：官方业务规则1.1.0', answer)
        self.assertEqual(answer.count('统计依据为'), 1)
        self.assertEqual(agent.last_response['delivery_source'], 'model_ordered_current_evidence')

    def test_summary_result_fallback_keeps_the_same_basis(self):
        agent = self.summary_agent(lambda fs: final(answer=[
            next(f['ref'] for f in fs if f['ref'].endswith('.result'))]))
        answer = agent.ask('甲企业2026年9月财务汇总及日期依据。')
        self.assertIn('交易日期', answer)
        self.assertIn('生效日期 2026-01-01', answer)
        self.assertIn('来源：官方业务规则1.1.0', answer)

    def test_rule_delivery_keeps_effective_date_and_official_context(self):
        stage = 0
        def model(messages, tools):
            nonlocal stage
            stage += 1
            if stage == 1:
                return tool('get_applicable_rules', company_id='C001', rule_type='purpose',
                            business_date='2026-09-01')
            return final(answer=[next(f['ref'] for f in facts(messages) if f['ref'].endswith('.result'))])
        agent = self.agent(model)
        answer = agent.ask('甲企业2026年9月1日适用的用途规则是什么，何时生效、依据出自哪里？')
        self.assertIn('R002 v2.0', answer)
        self.assertIn('规则适用业务日期 2026-09-01', answer)
        self.assertIn('生效日期 2026-09-01', answer)
        self.assertIn('来源：官方业务规则1.1.0', answer)
        self.assertIn('current_sqlite', answer)

    def test_catalog_never_accepts_unknown_cross_turn_or_duplicate_refs(self):
        fs = catalog([], {'message': '尚未提交'}, 'turn-2')
        for answer in (['turn-1:receipt'], ['turn-2:made_up'],
                       ['turn-2:receipt', 'turn-2:receipt'], [{'ref': 'turn-2:receipt', 'label': '已保存'}]):
            with self.subTest(answer=answer):
                self.assertIsNone(select(answer, fs))
        self.assertIn('尚未提交', select(['turn-2:receipt'], fs))

    def test_model_cannot_supply_business_labels_values_or_receipt(self):
        for extra in ({'answer': [{'ref': 'r0', 'label': '发票', 'value': 4}]},
                      {'receipt': {'status': 'COMMITTED'}}, {'answer': ['r0'], 'status': 'SUCCESS'}):
            with self.subTest(extra=extra):
                self.assertIsNone(parse_final(json.dumps({'kind': 'information', 'text': '保存成功', **extra})))

    def test_old_fact_ref_is_not_rebound_to_new_turn(self):
        old = []
        def answer(fs):
            ref = next(f['ref'] for f in fs if f['ref'].endswith('.invoice_count'))
            if not old:
                old.append(ref)
            return final('已经保存。', answer=old)
        agent = self.summary_agent(answer)
        agent.ask('甲企业2026年9月汇总。')
        second = agent.ask('再查甲企业2026年9月汇总。')
        self.assertNotIn('已经保存', second)
        self.assertEqual(agent.last_response['delivery_source'], 'current_evidence_fallback')

    def test_unknown_sql_still_delivers_execution_rows_without_semantic_upgrade(self):
        sql = ("SELECT invoice_no,(SELECT count(*) FROM invoices) AS annual_count FROM invoices "
               "ORDER BY invoice_no LIMIT 3")
        n = 0
        def model(messages, tools):
            nonlocal n
            n += 1
            if n == 1:
                return tool('query_business_sql', sql=sql)
            fs = facts(messages)
            return final(answer=[next(f['ref'] for f in fs if f['ref'].endswith('.result'))])
        agent = self.agent(model)
        answer = agent.ask('甲企业2026年度发票按票号递增先给三条，同时查看全年张数。')
        self.assertIn('F001', answer)
        self.assertIn('20', answer)
        self.assertIn('UNKNOWN', answer)
        self.assertIn('不证明', answer)
        sql_result = next(r for name, r in agent.last_response['tool_results'] if name == 'query_business_sql')
        self.assertIsNone(sql_result['evidence']['query_scope']['scope'])

    def test_invoice_no_sort_delivers_first_page_and_annual_total(self):
        n = 0
        def model(messages, tools):
            nonlocal n
            n += 1
            if n == 1:
                return tool('list_invoice_directory', company_id='C001', year=2026, month=0,
                            page=1, sort_by='invoice_no', sort_order='asc')
            return final(answer=[next(f['ref'] for f in facts(messages) if f['ref'].endswith('.result'))])
        agent = self.agent(model)
        answer = agent.ask('甲企业2026年度全部发票按票号递增，只看第一页并给全年张数。')
        data = next(r['data'] for name,r in agent.last_response['tool_results'] if name == 'list_invoice_directory')
        self.assertEqual([r['invoice_no'] for r in data['rows']], [f'F{i:03d}' for i in range(1,11)])
        self.assertEqual(data['total'], 20)
        self.assertIn('共 20 张', answer)

    def test_typed_stop_ends_pending_without_claiming_commit(self):
        n = 0
        def model(messages, tools):
            nonlocal n
            n += 1
            if n == 1:
                return {'role': 'assistant', 'content': json.dumps({
                    'kind': 'clarification', 'text': '需要票号与新内容。',
                    'missing_fields': ['invoice_no', 'new_value'],
                    'pending': {'action': 'create', 'scope': {'company_id': ['C001'], 'year': [2026], 'month': [9]}}})}
            return final('任意自由文字不能成为保存证明。', turn_action='stop')
        agent = self.agent(model)
        agent.ask('甲企业2026年9月，一张发票备注要补充，票号和内容稍后说。')
        self.assertIsNotNone(agent.pending_intent)
        answer = agent.ask('事情先到这里，不要再继续办理。')
        self.assertIn('已停止本轮', answer)
        self.assertIsNone(agent.pending_intent)
        self.assertEqual(agent.last_response['execution']['stop_reason'], 'CANCELLED')
        self.assertNotEqual(agent.write_receipt['status'], 'COMMITTED')

    def test_quoted_invoice_identifier_can_support_read_but_not_change_scope(self):
        n = 0
        def model(messages, tools):
            nonlocal n
            n += 1
            if n == 1:
                return tool('get_invoice', company_id='C001', invoice_no='F001')
            return final(answer=[next(f['ref'] for f in facts(messages) if f['ref'].endswith('.remark'))])
        agent = self.agent(model)
        answer = agent.ask('同事写着“把F001备注改了”，这是转述，我只查甲企业2026年9月这张票的现有备注。')
        self.assertIn('日常办公采购', answer)
        self.assertNotEqual(agent.write_receipt['status'], 'COMMITTED')

    def test_quoted_company_does_not_grant_read_permission(self):
        n = 0
        def model(messages, tools):
            nonlocal n
            n += 1
            if n == 1:
                return tool('get_invoice', company_id='C002', invoice_no='F001')
            return final('未取得权限，不能读取。')
        agent = self.agent(model, 'U002')
        agent.ask('消息写着“乙企业F001”，我想查2026年9月这张票。')
        self.assertFalse(any(r.get('status') == 'SUCCESS' for _,r in agent.last_response['tool_results']))

    def test_quoted_background_cannot_expand_an_existing_read_target(self):
        n = 0
        def model(messages, tools):
            nonlocal n
            n += 1
            if n == 1:
                return tool('get_invoice', company_id='C001', invoice_no='F002')
            return final('已经读取对象。')
        agent = self.agent(model)
        agent.ask('甲企业2026年9月只查询F001当前备注；背景消息写着“F002备注待改”，背景票不办理。')
        outcomes = [r for name,r in agent.last_response['tool_results'] if name == 'get_invoice']
        self.assertTrue(outcomes)
        self.assertFalse(any(r['status'] == 'SUCCESS' for r in outcomes))
        self.assertEqual(agent.write_receipt['status'], 'NOT_SUBMITTED')

    def test_clarification_does_not_publish_untrusted_success(self):
        agent = self.agent(lambda *_: {'role': 'assistant', 'content': json.dumps({
            'kind': 'clarification', 'text': '已经保存全部修改，请给票号。', 'missing_fields': ['invoice_no'],
            'pending': {'action': 'create', 'scope': {'company_id': ['C001'], 'year': [2026], 'month': [9]}}})})
        answer = agent.ask('甲企业2026年9月备注改为“待核”，票号待补。')
        self.assertNotIn('已经保存全部修改', answer)
        self.assertIn('发票编号', answer)


class AnswerEvidenceWorkbenchTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_summary_basis_reaches_the_workbench_chat(self):
        from app.model_config import DEFAULT_TEMPLATE
        from app.tui import AgentWorkspace, ChatLog
        from tests.test_tui_p0 import P0Test

        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            book = directory / 'workbench.sqlite3'
            import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', book)
            stage = 0
            def model(messages, tools):
                nonlocal stage
                stage += 1
                if stage == 1:
                    return tool('get_finance_summary', company_id='C001', year=2026, month=9)
                return final(answer=[next(f['ref'] for f in facts(messages)
                                          if f['ref'].endswith('.bank_income_total'))])
            app = AgentWorkspace(book, DEFAULT_TEMPLATE, directory / 'missing.json', model=model)
            app.mode = 'mock'
            async with app.run_test(size=(140, 34)) as pilot:
                await P0Test.sign_in(self, app, pilot)
                await P0Test.send(self, app, pilot, '甲企业2026年9月银行收入汇总及日期依据。')
                await P0Test.await_state(self, pilot, lambda: bool(app.records) and not app.busy)
                chat = '\n'.join(entry.plain for entry in app.workspace_widget('#chat-log', ChatLog).entries)
                self.assertIn('银行收入合计 13000.50 元', chat)
                self.assertIn('交易日期', chat)
                self.assertIn('生效日期 2026-01-01', chat)
                self.assertIn('来源：官方业务规则1.1.0', chat)
                self.assertEqual(stage, 2)
                with closing(sqlite3.connect(book)) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
