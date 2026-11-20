"""Actual displayed singleton origins, never model scope or human approval."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.agent import Agent
from app.cli_workspaces import import_workspace
from tests.test_answer_evidence import facts, final, tool
from tests.test_sql_invoice_selection import snapshot
from tests.test_tui_p0 import FIXTURE


SQL = ("SELECT company_id, invoice_no, invoice_date, seller_name, item_name, amount_cents, purpose, remark "
       "FROM invoices WHERE company_id='C001' AND invoice_date>='2026-09-01' "
       "AND invoice_date<'2026-10-01' AND invoice_no LIKE '%006%' ORDER BY invoice_no")


class DisplayedBusinessTargetTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.book = Path(temp.name) / 'fictional.sqlite'
        import_workspace(FIXTURE, self.book)
        self.before = snapshot(self.book)

    def tearDown(self):
        self.assertEqual(snapshot(self.book), self.before, 'No human confirms in these program controls')

    def agent(self, actor='U001'):
        agent = Agent(actor, self.book, lambda *_: None, mode='mock',
                      trace_path=self.book.with_suffix('.jsonl'))
        agent.context.display_ids = []
        agent.defer_display_anchors = True
        return agent

    def read(self, agent, sql=SQL, *, display=True):
        count = 0
        def model(messages, tools):
            nonlocal count
            count += 1
            if count == 1:
                return tool('query_business_sql', sql=sql)
            result = next(f['ref'] for f in facts(messages) if f['type'] == 'result')
            return final(answer=[result])
        agent.model = model
        agent.ask('查看C001 2026年9月票号含006的票据当前用途和备注。')
        self.assertIn(agent.last_response['tool_results'][0][1]['status'], {'SUCCESS', 'NO_DATA'})
        if display:
            # Program control of the same callback used after real UI rendering.
            return agent.record_query_display(agent.last_response['tool_results'])

    def edit(self, agent, **overrides):
        args = {'company_id': 'C001', 'invoice_no': 'F006', 'year': 2026, 'month': 9,
                'field': 'remark', 'new_value': '样件已签收', **overrides}
        agent.model = lambda *_: tool('change_invoice', **args)
        return agent.ask('就这张，备注改成“样件已签收”，用途别动。')

    def test_actual_displayed_unique_row_binds_target_but_only_prepares_preview(self):
        agent = self.agent()
        anchors = self.read(agent)
        self.assertEqual(len(anchors), 1)
        self.edit(agent)
        self.assertEqual(agent.last_response['execution']['stop_reason'], 'WAITING_CONFIRMATION')
        plan = agent.last_response['invoice_change']
        self.assertEqual((plan['company_id'], plan['invoice_nos'], plan['field'], plan['new_value']),
                         ('C001', ('F006',), 'remark', '样件已签收'))
        self.assertEqual(agent.ticket_preview_candidate['provenance']['invoice_no']['kind'], 'trusted_reference')
        self.assertFalse(agent.update_session.confirmations)

    def test_raw_query_without_actual_display_has_no_object_origin(self):
        agent = self.agent()
        self.read(agent, display=False)
        self.edit(agent)
        self.assertIsNone(agent.last_response.get('invoice_change'))

    def test_other_session_or_retired_reference_cannot_restore_target(self):
        agent = self.agent()
        self.read(agent)
        other = self.agent()
        self.edit(other)
        self.assertIsNone(other.last_response.get('invoice_change'))
        agent.context.cancel_references(len(agent.messages), [])
        self.edit(agent)
        self.assertIsNone(agent.last_response.get('invoice_change'))

    def test_multiline_and_paginated_display_do_not_reuse_old_singleton(self):
        for sql in (SQL.replace("AND invoice_no LIKE '%006%'", ''), SQL + ' LIMIT 1',
                    SQL.replace("'%006%'", "'%NONEXISTING%'")):
            with self.subTest(sql=sql):
                agent = self.agent()
                self.read(agent)
                self.read(agent, sql)
                self.assertTrue(agent.context.references_blocked)
                self.edit(agent)
                self.assertIsNone(agent.last_response.get('invoice_change'))

    def test_target_or_period_mismatch_never_uses_display_origin(self):
        for overrides in ({'invoice_no': 'F005'}, {'year': 2025}, {'month': 10}):
            with self.subTest(overrides=overrides):
                agent = self.agent()
                self.read(agent)
                self.edit(agent, **overrides)
                self.assertIsNone(agent.last_response.get('invoice_change'))

    def test_display_reference_does_not_grant_modify_permission(self):
        agent = self.agent('U002')
        self.read(agent)
        self.edit(agent)
        self.assertEqual(agent.last_response['tool_results'][-1][1]['status'], 'DENIED')
        self.assertIsNone(agent.last_response.get('invoice_change'))

    def test_explicit_new_literal_target_wins_over_echoed_display_target(self):
        agent = self.agent()
        self.read(agent)
        agent.model = lambda *_: tool('change_invoice', company_id='C001', invoice_no='F006',
                                     field='remark', new_value='样件已签收')
        agent.ask('另改C001的F005，备注填“样件已签收”。')
        self.assertIsNone(agent.last_response.get('invoice_change'))

    def test_omitted_object_is_not_implicit_selection_of_last_display(self):
        for request in ('还有一张票要改备注，票号稍后给，内容“样件已签收”。',
                        '另改C001的F005，备注填“样件已签收”。'):
            with self.subTest(request=request):
                agent = self.agent()
                self.read(agent)
                agent.model = lambda *_: tool('change_invoice', field='remark', new_value='样件已签收')
                agent.ask(request)
                self.assertIsNone(agent.last_response.get('invoice_change'))


class DisplayedTargetWorkbenchTests(unittest.IsolatedAsyncioTestCase):
    setUp = DisplayedBusinessTargetTests.setUp
    tearDown = DisplayedBusinessTargetTests.tearDown

    async def test_real_workbench_display_then_relative_edit_mounts_preapproval(self):
        from app.model_config import DEFAULT_TEMPLATE
        from app.tui import AgentWorkspace
        from app.tui_screens import Approval
        from tests import test_tui_p0 as helpers
        count = 0

        def model(messages, tools):
            nonlocal count
            count += 1
            if count == 1:
                return tool('query_business_sql', sql=SQL)
            if count == 2:
                ref = next(f['ref'] for f in facts(messages) if f['type'] == 'result')
                return final(answer=[ref])
            return tool('change_invoice', company_id='C001', invoice_no='F006', year=2026, month=9,
                        field='remark', new_value='样件已签收')

        app = AgentWorkspace(self.book, DEFAULT_TEMPLATE, self.book.parent / 'none.json', model=model,
            trace_path=self.book.parent / 'trace.jsonl', session_path=self.book.parent / 'sessions.sqlite')
        app.mode = 'mock'
        async with app.run_test(size=(150, 42)) as pilot:
            await helpers.P0Test.sign_in(self, app, pilot)
            await helpers.P0Test.send(self, app, pilot, '查看C001 2026年9月票号含006的票据用途和备注。')
            await helpers.P0Test.await_state(self, pilot, lambda: not app.busy)
            self.assertTrue(app.agent.context.display_ids)
            await helpers.P0Test.send(self, app, pilot, '就这张，备注改成“样件已签收”，用途别动。')
            await helpers.P0Test.await_state(self, pilot, lambda: isinstance(app.screen, Approval)
                and app.screen.is_mounted and bool(app.screen.query('#cancel')))
            self.assertIn('F006', app.screen.body)
            self.assertIn('新值　样件已签收', app.screen.body)
            self.assertFalse(app.agent.update_session.confirmations)
            self.assertEqual(app.agent.ticket_preview_candidate['provenance']['invoice_no']['kind'], 'trusted_reference')
            app.screen.answer(False)  # Program rejection only, never human acceptance.
            await helpers.P0Test.await_state(self, pilot, lambda: not app.busy)
