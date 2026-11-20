"""Only uniquely registered read spellings may be canonicalized; zero API."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.agent import Agent, scripted_model
from app.business_object_sources import amendment_sources, read_invoice_sources, ReadInvoiceAmbiguity
from app.cli_workspaces import import_workspace
from app.stage2_schema import open_existing
from tests.test_tui_p0 import FIXTURE, FINAL, tool


class ReadInvoiceCasefoldTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.book = self.root / 'fictional.sqlite3'
        import_workspace(FIXTURE, self.book)

    def test_unique_read_key_is_company_scoped_and_does_not_widen_write_sources(self):
        current, _, _ = read_invoice_sources('甲企业f002当前用途', actor='U001', book=self.book)
        self.assertEqual(current['invoice_no'], ['F002'])
        exact, _, _ = amendment_sources('甲企业f002用途填「复核」', '复核', actor='U001', book=self.book,
                                        invoice_candidates=('F002',))
        self.assertNotIn('invoice_no', exact)
        agent = Agent('U001', self.book, scripted_model([tool('change_invoice', {
            'company_id':'C001', 'invoice_no':'F002', 'year':2026, 'month':9,
            'field':'purpose', 'new_value':'复核'})]), mode='mock')
        agent.ask('甲企业2026年9月f002用途填「复核」。')
        self.assertIsNone(agent.last_response.get('invoice_change'))
        self.assertFalse(agent.update_session.drafts)

    def test_company_without_current_source_and_longer_tokens_are_not_normalized(self):
        for text in ('f002当前用途', '甲企业xf002x当前用途'):
            with self.subTest(text=text):
                current, _, _ = read_invoice_sources(text, actor='U001', book=self.book)
                self.assertNotIn('invoice_no', current)

    def test_real_casefold_collision_rejects_stale_key_but_exact_keys_stay_separate(self):
        with closing(open_existing(self.book)) as db, db:
            for number in ('AbC-X', 'ABC-X'):
                db.execute('''INSERT INTO invoices SELECT company_id,?,invoice_date,seller_name,item_name,
                    amount_cents,purpose,remark FROM invoices WHERE company_id='C001' AND invoice_no='F001' ''', (number,))
        with self.assertRaises(ReadInvoiceAmbiguity):
            read_invoice_sources('甲企业abc-x用途', actor='U001', book=self.book)
        current, _, _ = read_invoice_sources('甲企业AbC-X用途', actor='U001', book=self.book)
        self.assertEqual(current['invoice_no'], ['AbC-X'])
        agent = Agent('U001', self.book, scripted_model([
            tool('get_invoice', {'company_id':'C001', 'invoice_no':'AbC-X'}), FINAL]), mode='mock')
        agent.ask('甲企业2026年9月AbC-X用途。')
        agent.model = scripted_model([tool('get_invoice', {'company_id':'C001', 'invoice_no':'AbC-X'}), FINAL])
        agent.ask('甲企业abc-x当前用途。')
        self.assertFalse(any(r['status'] == 'SUCCESS' for _, r in agent.last_response['tool_results']))
        self.assertTrue(any(r['status'] == 'AMBIGUOUS' for _, r in agent.last_response['tool_results']))

    def test_collisions_in_another_company_cannot_expand_or_block_the_selected_company(self):
        with closing(open_existing(self.book)) as db, db:
            db.execute("UPDATE invoices SET invoice_no='f002' WHERE company_id='C002' AND invoice_no='F002'")
        current, _, _ = read_invoice_sources('甲企业f002当前用途', actor='U001', book=self.book)
        self.assertEqual(current['invoice_no'], ['F002'])
        with closing(open_existing(self.book, readonly=True)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0], 0)

    def test_normalized_current_detail_is_verified_from_fresh_read_not_initial_write_scope(self):
        agent = Agent('U001', self.book, scripted_model([
            tool('get_invoice', {'company_id':'C001', 'invoice_no':'F002'}),
            {'role':'assistant', 'content':'invalid final JSON'}]), mode='mock')
        answer = agent.ask('查看甲企业f002当前用途')
        self.assertTrue(any(name == 'get_invoice' and result['status'] == 'SUCCESS'
                            for name, result in agent.last_response['tool_results']))
        self.assertTrue(agent.last_response['single_query_verified'])
        self.assertEqual(agent.last_response['execution']['stop_reason'], 'EVIDENCE_RETURNED')
        self.assertIn('F002', answer)
        self.assertFalse(agent.update_session.drafts)

    def test_unicode_casefold_preserves_whole_identifier_spans(self):
        with closing(open_existing(self.book)) as db, db:
            for number in ('STRASSE-3', 'SS'):
                db.execute('''INSERT INTO invoices SELECT company_id,?,invoice_date,seller_name,item_name,
                    amount_cents,purpose,remark FROM invoices WHERE company_id='C001' AND invoice_no='F001' ''', (number,))
        current, _, _ = read_invoice_sources('甲企业straße-3当前用途', actor='U001', book=self.book)
        self.assertEqual(current['invoice_no'], ['STRASSE-3'])
        longer, _, _ = read_invoice_sources('甲企业ßß当前用途', actor='U001', book=self.book)
        self.assertNotIn('invoice_no', longer)


if __name__ == '__main__':
    unittest.main()
