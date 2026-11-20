"""Current catalog and literal sources, scripted decisions only; no API/approval."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.invoice_batch import run_invoice_batch
from app.stage2_schema import open_existing
from app.model_config import DEFAULT_TEMPLATE
from app.tui import AgentWorkspace
from app.tui_screens import Approval
from tests import test_tui_p0 as helpers
from tests.test_model_intent import call
from tests.test_sql_invoice_selection import snapshot
from tests.test_tui_p0 import FIXTURE


class BusinessObjectSourceTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.book = self.root / 'fictional.sqlite3'
        import_workspace(FIXTURE, self.book)
        with closing(open_existing(self.book)) as db, db:
            db.execute("UPDATE companies SET name='清河研制中心',short_name='清河' WHERE company_id='C001'")
            db.execute("UPDATE companies SET name='青峰服务中心',short_name='青峰' WHERE company_id='C002'")
            db.execute("UPDATE invoices SET invoice_no='INV/9-A',purpose='原用途',remark='独立原备注' WHERE company_id='C001' AND invoice_no='F006'")
        self.before = snapshot(self.book)
        self.agent = Agent('U001', self.book, lambda *_: call('change_invoice', {}),
            mode='mock', trace_path=self.root / 'trace.jsonl')

    def tearDown(self):
        self.assertEqual(snapshot(self.book), self.before)

    def ask(self, text, **args):
        self.agent.model = lambda *_: call('change_invoice', args)
        return self.agent.ask(text)

    def preview(self):
        planned = self.agent.last_response.get('invoice_change')
        self.assertIsNotNone(planned)
        bodies = []
        def reject(body):
            bodies.append(body)
            return False
        run_invoice_batch(self.agent, planned['source_request'], planned,
            approve_item=reject, approve_batch=reject,
            checkpoint=lambda *_: self.fail('Unconfirmed source checks may not submit'))
        self.assertEqual(len(bodies), 1)
        self.assertFalse(self.agent.update_session.confirmations)
        return planned, bodies[0]

    def test_registered_short_name_and_nonstandard_invoice_get_fresh_period_and_preview(self):
        self.ask('清河的INV/9-A用途填「项目复核」，先给我预览。',
            company_id='C001', invoice_no='INV/9-A', field='purpose', new_value='项目复核')
        plan, body = self.preview()
        self.assertEqual((plan['company_id'], plan['invoice_nos'], plan['year'], plan['month']),
                         ('C001', ('INV/9-A',), 2026, 9))
        self.assertIn('原值　原用途', body)
        self.assertIn('新值　项目复核', body)

    def test_real_ambiguity_blocks_alias_but_exact_full_name_is_distinct(self):
        with closing(open_existing(self.book)) as db, db:
            db.execute("UPDATE companies SET short_name='清河' WHERE company_id='C002'")
        self.ask('清河的INV/9-A用途填「复核」。', company_id='C001', invoice_no='INV/9-A',
                 field='purpose', new_value='复核')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))
        self.assertEqual(self.agent.last_response['tool_results'][-1][1]['status'], 'AMBIGUOUS')
        self.agent.cancel_update()
        self.ask('清河研制中心的INV/9-A用途填「复核」。', company_id='C001', invoice_no='INV/9-A',
                 field='purpose', new_value='复核')
        self.preview()

    def test_unknown_literal_invoice_is_fresh_no_data_and_prefix_is_not_a_source(self):
        self.ask('清河的N/404-X用途填「复核」。', company_id='C001', invoice_no='N/404-X',
                 field='purpose', new_value='复核')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))
        first = next(result for name, result in self.agent.last_response['tool_results'] if name == 'change_invoice')
        self.assertEqual(first['status'], 'NO_DATA')
        self.agent.cancel_update()
        self.ask('清河的INV/9-A-EXTRA用途填「复核」。', company_id='C001', invoice_no='INV/9-A',
                 field='purpose', new_value='复核')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))

    def test_value_only_names_and_identifiers_never_supply_the_target(self):
        value = '参照清河INV/9-A的旧台账'
        for text in (f'备注填写「{value}」。', f'备注填写{value}。'):
            with self.subTest(text=text):
                self.agent.cancel_update()
                self.ask(text, company_id='C001', invoice_no='INV/9-A', field='remark', new_value=value)
                self.assertIsNone(self.agent.last_response.get('invoice_change'))
                self.assertFalse(self.agent.update_session.drafts)

    def test_value_containing_other_objects_does_not_change_explicit_target(self):
        value = '参照青峰F010资料'
        self.ask(f'清河INV/9-A备注填写{value}，先预览。',
                 company_id='C001', invoice_no='INV/9-A', field='remark', new_value=value)
        plan, body = self.preview()
        self.assertEqual((plan['company_id'], plan['invoice_nos']), ('C001', ('INV/9-A',)))
        self.assertIn('新值　' + value, body)

    def test_explicit_period_conflicts_cannot_be_overwritten_by_fresh_date(self):
        for extra, text in (({'year':2025}, '2025年'), ({'month':8}, '8月')):
            with self.subTest(extra=extra):
                self.agent.cancel_update()
                self.ask(f'清河{text}的INV/9-A用途填「复核」。', company_id='C001',
                         invoice_no='INV/9-A', field='purpose', new_value='复核', **extra)
                self.assertIsNone(self.agent.last_response.get('invoice_change'))
                self.assertEqual(self.agent.last_response['tool_results'][-1][1]['status'], 'SCOPE_MISMATCH')

    def test_incremental_target_derives_period_but_cancel_cannot_restore_the_change(self):
        self.ask('清河有张票用途填「待核」，编号稍后给。', company_id='C001', field='purpose', new_value='待核')
        self.assertIsNotNone(self.agent.pending_intent)
        self.ask('编号INV/9-A，按刚才要求先预览。', invoice_no='INV/9-A')
        self.preview()
        self.agent.cancel_update()
        self.ask('INV/9-A。', invoice_no='INV/9-A')
        self.assertIsNone(self.agent.last_response.get('invoice_change'))
        self.assertFalse(self.agent.pending_intent['change'])

    def test_acl_and_wrong_company_or_unregistered_alias_stay_closed(self):
        for text, company, actor in (
                ('清河INV/9-A用途填「复核」。', 'C002', 'U001'),
                ('未登记INV/9-A用途填「复核」。', 'C001', 'U001'),
                ('清河INV/9-A用途填「复核」。', 'C001', 'U002')):
            with self.subTest(text=text, actor=actor):
                self.agent = Agent(actor, self.book, lambda *_: None, mode='mock')
                self.ask(text, company_id=company, invoice_no='INV/9-A', field='purpose', new_value='复核')
                self.assertIsNone(self.agent.last_response.get('invoice_change'))
                self.assertFalse(self.agent.update_session.drafts)

    def test_literal_identifiers_are_not_restricted_to_a_prefix_or_interpreted_as_dates(self):
        old = 'INV/9-A'
        for number in ('ARCH/2031-04', '90281467', 'N_A-02'):
            with self.subTest(number=number):
                self.agent.cancel_update()
                with closing(open_existing(self.book)) as db, db:
                    db.execute('UPDATE invoices SET invoice_no=? WHERE company_id=? AND invoice_no=?',
                               (number, 'C001', old))
                self.before = snapshot(self.book)
                self.ask(f'清河研制中心的{number}用途改为「核验」，先预览。',
                    company_id='C001', invoice_no=number, field='purpose', new_value='核验')
                plan, _ = self.preview()
                self.assertEqual((plan['invoice_nos'], plan['year'], plan['month']), ((number,), 2026, 9))
                old = number

    def test_canonical_joint_key_keeps_its_exact_company_and_invoice_components(self):
        self.ask('C001/INV/9-A用途填「复核」，先预览。', company_id='C001', invoice_no='INV/9-A',
                 field='purpose', new_value='复核')
        self.assertEqual(self.preview()[0]['invoice_nos'], ('INV/9-A',))


class BusinessObjectWorkbenchTests(unittest.IsolatedAsyncioTestCase):
    setUp = BusinessObjectSourceTests.setUp
    tearDown = BusinessObjectSourceTests.tearDown

    async def test_registered_objects_without_dates_mount_real_preview_and_reject_without_write(self):
        app = AgentWorkspace(self.book, DEFAULT_TEMPLATE, self.root / 'none.json',
            model=lambda *_: call('change_invoice', {'company_id':'C001', 'invoice_no':'INV/9-A',
                'field':'purpose', 'new_value':'项目复核'}),
            trace_path=self.root / 'ui-trace.jsonl', session_path=self.root / 'sessions.sqlite3')
        app.mode = 'mock'
        async with app.run_test(size=(150, 42)) as pilot:
            await helpers.P0Test.sign_in(self, app, pilot)
            await helpers.P0Test.send(self, app, pilot, '清河的INV/9-A用途填「项目复核」，先准备待确认。')
            await helpers.P0Test.await_state(self, pilot, lambda: isinstance(app.screen, Approval)
                and app.screen.is_mounted and bool(app.screen.query('#cancel')))
            self.assertIn('INV/9-A', app.screen.body)
            self.assertIn('原值　原用途', app.screen.body)
            self.assertIn('新值　项目复核', app.screen.body)
            self.assertEqual(app.agent.ticket_preview_candidate['provenance']['year']['kind'], 'current_sqlite')
            self.assertEqual(app.agent.ticket_preview_candidate['provenance']['month']['kind'], 'current_sqlite')
            self.assertFalse(app.agent.update_session.confirmations)
            app.screen.answer(False)
            await helpers.P0Test.await_state(self, pilot, lambda: not app.busy)


if __name__ == '__main__':
    unittest.main()
