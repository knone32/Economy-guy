"""Registered read objects share one literal source contract; zero model/API."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from app.agent import Agent
from app.cli_workspaces import import_workspace
from app.context import ContextBuilder
from app.intent_contract import validate, read_proof, IntentContractError
from app.provenance import ScopeProof, SOURCES, validate_scope
from tests.test_answer_evidence import tool, final, facts


class RegisteredReadSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.book = Path(temporary.name) / 'fictional.sqlite3'
        import_workspace(Path(__file__).parent / 'fixtures/example.xlsx', self.book)
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute("UPDATE companies SET name=?,short_name=? WHERE company_id='C001'",
                       ('栖岭数控设备有限责任公司', '栖岭数控'))
            db.execute("UPDATE companies SET name=?,short_name=? WHERE company_id='C002'",
                       ('漾川物流有限公司', '漾川物流'))
        self.request = '栖岭数控2026年9月发票金额与银行收支分别多少？'

    def candidate(self, company='C001', quote='栖岭数控'):
        return {'action': 'read', 'target': {'company_id': company, 'year': 2026, 'month': 9},
                'sources': {'company_id': {'kind': 'current', 'text': quote},
                            'year': {'kind': 'current', 'text': '2026年'},
                            'month': {'kind': 'current', 'text': '9月'}}}

    def bind(self, raw, request=None, actor='U001', anchor=None):
        return validate(raw, actor=actor, book=self.book, request=request or self.request,
                        turn_id='synthetic', anchor=anchor)

    def test_correct_dedicated_query_needs_no_redundant_intent_sidecar(self):
        calls = []
        def model(messages, tools):
            calls.append(messages)
            if len(calls) == 1:
                return tool('get_finance_summary', company_id='C001', year=2026, month=9)
            return final(answer=[f['ref'] for f in facts(messages) if f['ref'].endswith('.invoice_total')])
        agent = Agent('U001', self.book, model, mode='mock', trace_path=self.book.with_suffix('.jsonl'))
        answer = agent.ask(self.request)
        self.assertEqual(len(calls), 2)
        self.assertEqual(agent.last_response['tool_results'][0][1]['status'], 'SUCCESS')
        self.assertIn('9622.06', answer)
        self.assertNotIn('请补充企业', answer)

    def test_sidecar_quote_must_match_actual_registered_company(self):
        self.assertEqual(self.bind(self.candidate()).target['company_id'], 'C001')
        for raw in (self.candidate('C002'), self.candidate('C001', '栖岭')):
            with self.subTest(raw=raw), self.assertRaises(IntentContractError):
                self.bind(raw)
        with self.assertRaises(IntentContractError):
            self.bind(self.candidate('C002', 'C001'), request='C0012026年9月财务汇总')

    def test_quoted_registered_read_source_is_legal_without_creating_write_source(self):
        request = '请查询“栖岭数控”2026年9月财务汇总。'
        builder = ContextBuilder('U001', self.book)
        builder.begin(request, 1)
        self.assertNotIn('company_id', builder.proof().values)
        candidate = self.bind(self.candidate(), request=request)
        proof, _ = read_proof(candidate, builder.proof(), {}, actor='U001', book=self.book,
                              turn_id='synthetic', request=request)
        self.assertEqual(validate_scope(proof, 'U001', 'get_finance_summary', candidate.target), None)
        self.assertNotIn(proof.sources['company_id'], SOURCES)
        self.assertEqual(validate_scope(proof, 'U001', 'prepare_invoice_update',
                         {'company_id': 'C001'})['status'], 'AMBIGUOUS')

    def test_registered_dynamic_context_remains_read_only_across_turns(self):
        builder = ContextBuilder('U001', self.book)
        builder.begin(self.request, 1)
        for _ in range(2):
            proof = builder.proof()
            self.assertEqual(proof.values['company_id'], ['C001'])
            self.assertNotIn(proof.sources['company_id'], SOURCES)
            self.assertIsNone(validate_scope(proof, 'U001', 'get_finance_summary',
                              {'company_id': 'C001', 'year': 2026, 'month': 9}))
            self.assertEqual(validate_scope(proof, 'U001', 'prepare_invoice_update',
                             {'company_id': 'C001'})['status'], 'AMBIGUOUS')
            builder.begin('继续核对', 2)

    def test_shared_registered_alias_cannot_select_either_company_or_restore_old_target(self):
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute("UPDATE companies SET short_name='栖岭数控' WHERE company_id='C002'")
        builder = ContextBuilder('U001', self.book)
        builder.begin('C001 2026年9月', 1)
        builder.begin(self.request, 2)
        outcome = validate_scope(builder.proof(), 'U001', 'get_finance_summary',
                                 {'company_id': 'C001', 'year': 2026, 'month': 9})
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome['status'], 'AMBIGUOUS')
        with self.assertRaises(IntentContractError):
            self.bind(self.candidate())

    def test_two_distinct_registered_mentions_allow_model_to_select_each_read_target(self):
        request = '栖岭数控和漾川物流2026年9月财务汇总分别是多少？'
        builder = ContextBuilder('U001', self.book)
        builder.begin(request, 1)
        for company, quote in (('C001', '栖岭数控'), ('C002', '漾川物流')):
            with self.subTest(company=company):
                candidate = self.bind(self.candidate(company, quote), request=request)
                self.assertEqual(candidate.target['company_id'], company)
                self.assertIsNone(validate_scope(builder.proof(), 'U001', 'get_finance_summary', candidate.target))

    def test_unreadable_company_and_conflicting_trusted_reference_are_rejected(self):
        with self.assertRaises(IntentContractError):
            self.bind(self.candidate('C002', '漾川物流'), request='漾川物流2026年9月财务汇总', actor='U002')
        anchor = ScopeProof('U001', {'company_id': ['C001']}, {'company_id': 'trusted_reference'})
        with self.assertRaises(IntentContractError):
            self.bind(self.candidate('C002', '漾川物流'), request='漾川物流2026年9月财务汇总', anchor=anchor)

    def test_unregistered_or_quoted_only_names_do_not_automatically_bind_context(self):
        for request in ('栖岭2026年9月财务汇总', '备注内容“栖岭数控”，2026年9月先核对。'):
            with self.subTest(request=request):
                builder = ContextBuilder('U001', self.book)
                builder.begin(request, 1)
                self.assertNotIn('company_id', builder.proof().values)

    def test_actual_nonstandard_invoice_and_date_shaped_identifier_can_be_read(self):
        number = 'DOC-82/2034-07'
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute("UPDATE invoices SET invoice_no=? WHERE company_id='C001' AND invoice_no='F002'", (number,))
        calls = []
        def model(messages, tools):
            calls.append(messages)
            if len(calls) == 1:
                return tool('get_invoice', company_id='C001', invoice_no=number)
            return final(answer=[f['ref'] for f in facts(messages) if f.get('label') == '发票编号'])
        agent = Agent('U001', self.book, model, mode='mock', trace_path=self.book.with_suffix('.jsonl'))
        answer = agent.ask('栖岭数控这张 ' + number + ' 的当前用途是什么？')
        self.assertEqual(agent.last_response['tool_results'][0][1]['status'], 'SUCCESS')
        self.assertIn(number, answer)
        proof = agent.context.proof()
        self.assertEqual(proof.values['invoice_no'], [number])
        self.assertNotIn(proof.sources['invoice_no'], SOURCES)
        self.assertNotIn(2034, proof.values.get('year', ()))

    def test_nonstandard_invoice_sidecar_accepts_exact_quote_and_rejects_prefix_fragment(self):
        number = 'DOC-82/2034-07'
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute("UPDATE invoices SET invoice_no=? WHERE company_id='C001' AND invoice_no='F002'", (number,))
        raw = self.candidate()
        raw['target']['invoice_no'] = number
        raw['sources']['invoice_no'] = {'kind': 'current', 'text': number}
        request = '栖岭数控2026年9月，请读取“' + number + '”的用途。'
        self.assertEqual(self.bind(raw, request=request).target['invoice_no'], number)
        bad = deepcopy(raw)
        bad['target']['invoice_no'] = 'DOC-82/2034'
        with self.assertRaises(IntentContractError):
            self.bind(bad, request=request)

    def test_quoted_invoice_literal_does_not_automatically_create_write_source(self):
        number = 'REF-Q82'
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute("UPDATE invoices SET invoice_no=? WHERE company_id='C001' AND invoice_no='F002'", (number,))
        builder = ContextBuilder('U001', self.book)
        builder.begin('栖岭数控2026年9月，文字内容“' + number + '”。', 1)
        self.assertNotIn('invoice_no', builder.proof().values)
        builder.begin('栖岭数控2026年9月 ' + number + ' 当前用途', 2)
        self.assertEqual(builder.proof().values['invoice_no'], [number])
        self.assertNotIn(builder.proof().sources['invoice_no'], SOURCES)

    def test_prefixed_invented_invoice_text_cannot_bind_an_actual_invoice(self):
        number = 'REF-Q82'
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute("UPDATE invoices SET invoice_no=? WHERE company_id='C001' AND invoice_no='F002'", (number,))
        builder = ContextBuilder('U001', self.book)
        builder.begin('栖岭数控2026年9月 X-' + number + ' 当前用途', 1)
        self.assertNotIn('invoice_no', builder.proof().values)

    def test_caller_date_sources_do_not_promote_new_read_object_sources(self):
        number = 'REF-Q82'
        with closing(sqlite3.connect(self.book)) as db, db:
            db.execute("UPDATE invoices SET invoice_no=? WHERE company_id='C001' AND invoice_no='F002'", (number,))
        builder = ContextBuilder('U001', self.book)
        request = '栖岭数控2026年9月 ' + number
        builder.begin(request, 1,
                      date_sources={'company_id': 'current_sqlite', 'invoice_no': 'current_sqlite'})
        for slot in ('company_id', 'invoice_no'):
            self.assertNotIn(builder.proof().sources[slot], SOURCES)
        self.assertTrue(builder.object_source_metadata['read_only'])
        span, = builder.object_source_metadata['invoice_mentions'][number]
        self.assertEqual(request[span[0]:span[1]], number)
