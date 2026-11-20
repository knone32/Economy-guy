"""Date source quotes must occur outside complete data-object identifiers."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from app.cli_workspaces import import_workspace
from app.intent_contract import validate, read_proof, IntentContractError
from app.provenance import ScopeProof
from app.tool_registry import handle_tool


class ReadPeriodObjectSpanTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.book = Path(temporary.name) / 'fictional.sqlite3'
        import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', self.book)
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute("UPDATE companies SET name='宁桐装备有限公司',short_name='宁桐装备' WHERE company_id='C001'")
            db.execute("UPDATE invoices SET invoice_no='DOC-82/2034-07' WHERE company_id='C001' AND invoice_no='F002'")

    def candidate(self, number='DOC-82/2034-07', *, year=2034, month=7, date_quote='2034-07', company_quote='宁桐装备'):
        return {'action': 'read', 'target': {'company_id': 'C001', 'year': year, 'month': month, 'invoice_no': number},
                'sources': {'company_id': {'kind': 'current', 'text': company_quote},
                            'invoice_no': {'kind': 'current', 'text': number},
                            'year': {'kind': 'current', 'text': date_quote},
                            'month': {'kind': 'current', 'text': date_quote}}}

    def bind(self, request, raw):
        return validate(raw, actor='U001', book=self.book, request=request, turn_id='synthetic')

    def test_date_only_inside_actual_invoice_identifier_is_not_a_period_source(self):
        with self.assertRaises(IntentContractError):
            self.bind('宁桐装备 DOC-82/2034-07 当前用途是什么？', self.candidate())

    def test_date_only_inside_quoted_actual_invoice_is_not_a_period_source(self):
        with self.assertRaises(IntentContractError):
            self.bind('宁桐装备，读取“DOC-82/2034-07”。', self.candidate())

    def test_repeat_inside_identifier_and_as_true_external_date_is_valid(self):
        request = '宁桐装备 DOC-82/2034-07，请按 2034-07 期间读取。'
        bound = self.bind(request, self.candidate())
        self.assertEqual((bound.target['year'], bound.target['month']), (2034, 7))

    def test_quoted_objects_with_external_date_remain_valid_read_sources(self):
        request = '请读取“宁桐装备”的“DOC-82/2034-07”，账期是2026-09。'
        bound = self.bind(request, self.candidate(year=2026, month=9, date_quote='2026-09'))
        self.assertEqual(bound.target['invoice_no'], 'DOC-82/2034-07')

    def test_date_inside_unknown_complete_invoice_candidate_is_also_masked(self):
        raw = self.candidate('NEW-19/2034-07')
        with self.assertRaises(IntentContractError):
            self.bind('宁桐装备 NEW-19/2034-07 当前用途是什么？', raw)

    def test_unknown_invoice_with_real_external_date_can_return_no_data(self):
        request = '宁桐装备 NEW-19/2034-07，2026-09的这张当前用途是什么？'
        bound = self.bind(request, self.candidate('NEW-19/2034-07', year=2026, month=9, date_quote='2026-09'))
        proof, scope = read_proof(bound, ScopeProof('U001', {}, {}), {}, actor='U001', book=self.book,
                                  turn_id='synthetic', request=request)
        result = handle_tool('get_invoice', json.dumps({'company_id': 'C001', 'invoice_no': 'NEW-19/2034-07'}),
                             'U001', self.book, provenance=proof, expected_scope=scope)
        self.assertEqual(result['status'], 'NO_DATA')

    def test_date_only_inside_registered_company_name_is_not_a_period_source(self):
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute("UPDATE companies SET short_name='宁桐2034-07装备' WHERE company_id='C001'")
        raw = self.candidate('F003', company_quote='宁桐2034-07装备')
        with self.assertRaises(IntentContractError):
            self.bind('宁桐2034-07装备 F003 当前用途是什么？', raw)

    def test_wrapping_identifier_in_a_larger_quote_does_not_create_date_evidence(self):
        raw = self.candidate(date_quote='这张DOC-82/2034-07')
        with self.assertRaises(IntentContractError):
            self.bind('宁桐装备，这张DOC-82/2034-07用途是什么？', raw)

    def test_wrapping_quote_with_real_external_date_still_has_a_carrier(self):
        quote = '这张DOC-82/2034-07，真正账期2034-07'
        bound = self.bind('宁桐装备，' + quote, self.candidate(date_quote=quote))
        self.assertEqual(bound.target['year'], 2034)

    def test_existing_relative_period_offset_contract_still_works(self):
        raw = self.candidate('F003', year=2026, month=8)
        for key in ('year', 'month'):
            raw['sources'][key] = {'kind': 'period_offset', 'text': '上个月', 'months': -1}
        anchor = ScopeProof('U001', {'periods': [(2026, 9)]}, {'periods': 'session_confirmed'})
        bound = validate(raw, actor='U001', book=self.book, request='宁桐装备 F003，往上个月查询。',
                         turn_id='synthetic', anchor=anchor)
        self.assertEqual((bound.target['year'], bound.target['month']), (2026, 8))
