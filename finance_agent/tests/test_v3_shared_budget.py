"""No HTTP: temporary synthetic 13-entry ledger, original schema/aggregate totals."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor
import unittest


SPEC = importlib.util.spec_from_file_location('v3_budget', Path(__file__).resolve().parents[2] / 'tools/v3_shared_budget.py')
budget = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(budget)


class V3SharedBudgetTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.index = self.root / 'historical-index.json'
        self.index.write_text('{"status":"unknown_preserved"}', encoding='utf-8')
        self.prior = {'status': 'unknown_preserved', 'evidence_index_path': str(self.index),
                      'evidence_index_sha256': hashlib.sha256(self.index.read_bytes()).hexdigest()}
        # Synthetic usage, no model data: totals intentionally match the existing
        # cohort's 13 requests / 135275 tokens / 134478 micro-CNY without copying it.
        self.entries = []
        for index in range(13):
            prompt, miss = (135263, 65844) if index == 12 else (1, int(index == 11))
            usage = {'prompt_tokens': prompt, 'completion_tokens': 0, 'total_tokens': prompt,
                     'prompt_cache_hit_tokens': prompt - miss, 'prompt_cache_miss_tokens': miss}
            cost = budget.usage_charge(usage)[3]
            self.entries.append({'id': str(index), 'owner': 'C', 'case': 'synthetic-old', 'status': 'complete',
                                 'receipt_id': 'synthetic-receipt-' + str(index), 'usage': usage,
                                 'tokens': prompt, 'cost_micros': cost})
        self.totals = {'requests': 13, 'tokens': 135275, 'cost_micros': 134478}
        self.path, self.auth_path = self.root / 'LEDGER.json', self.root / 'AUTHORIZATION.json'
        self.data = {'schema': 'incremental-cohort-budget-v1', 'budget_id': 'synthetic-existing-budget',
                     'initialized_by': 'main_control', 'unknown_usage': False,
                     'accounting_scope': 'new_explicit_authorization', 'prior_consumption': self.prior,
                     'cohort_opening': {'requests': 0, 'tokens': 0, 'cost_micros': 0},
                     'entries': self.entries, 'totals': self.totals,
                     'limits': {'requests': 64, 'tokens': 700000, 'cost_micros': 2200000},
                     'rates_cny_per_million': budget.PEAK_RATES}
        self.auth = {'authorized': True, 'owner': 'C', 'shared_ledger_path': str(self.path),
                     'budget_mode': self.data['schema'], 'budget_id': self.data['budget_id'],
                     'accounting_scope': self.data['accounting_scope'], 'prior_consumption': self.prior,
                     'expires_at_utc': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                     'max_c_requests': 64, 'max_c_tokens': 700000, 'max_output_tokens': 8192,
                     'incremental_cost_limit_micros': 2200000,
                     'preserved_prefix': {'entry_count': 13, 'entries_sha256': budget.prefix_digest(self.entries),
                                          'totals': dict(self.totals)}}
        self.save()
        self.sent = []

    def save(self):
        budget.atomic(self.path, self.data)
        budget.atomic(self.auth_path, self.auth)

    def guard(self):
        return budget.SharedBudget(self.auth_path)

    def body(self, bound=8192):
        return json.dumps({'max_tokens': bound, 'messages': [{'role': 'user', 'content': 'synthetic'}]}).encode()

    def send(self, body):
        self.sent.append(body)
        current = budget.load(self.path)
        self.assertEqual(current['entries'][-1]['status'], 'pending')
        usage = {'prompt_tokens': 100, 'completion_tokens': 6000, 'total_tokens': 6100}
        return 200, {'id': 'synthetic-new', 'usage': usage}, 'synthetic-new'

    def test_appends_to_same_13_entry_ledger_with_8192_reservation(self):
        original = deepcopy(self.entries)
        body = self.body()
        status, _ = self.guard().execute(body, 'synthetic', self.send, lambda entry: None)
        self.assertEqual(status, 200)
        current = budget.load(self.path)
        self.assertEqual(current['entries'][:13], original)
        self.assertEqual(current['budget_id'], self.data['budget_id'])
        self.assertEqual(current['totals'], {'requests': 14, 'tokens': 141375, 'cost_micros': 182678})
        entry = current['entries'][-1]
        self.assertEqual(entry['reserved_tokens'], len(body) + 8192 + 8192)
        self.assertEqual(entry['reserved_cost_micros'], (len(body) + 8192) * 2 + 8192 * 8)
        self.assertEqual(entry['max_output_tokens'], 8192)
        self.assertEqual(entry['accounted_cost_ceiling_micros'], 48200)
        self.assertEqual(entry['accounting_basis'], budget.ACCOUNTING_BASIS)
        self.assertEqual(entry['local_log_status'], 'saved')
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.guard().inspect()['historical_cumulative_compliance'], 'UNKNOWN_NOT_ZERO')

    def test_local_logging_failure_preserves_known_usage_and_never_calls_twice(self):
        logged = []
        def broken(entry):
            logged.append(entry)
            raise OSError('synthetic evidence disk failure')
        with self.assertRaises(budget.LocalLogError):
            self.guard().execute(self.body(), 'synthetic', self.send, broken)
        current = budget.load(self.path)
        self.assertEqual(current['entries'][:13], self.entries)
        self.assertFalse(current['unknown_usage'])
        entry = current['entries'][-1]
        self.assertEqual(entry['status'], 'complete')
        self.assertEqual(entry['usage']['total_tokens'], 6100)
        self.assertEqual(entry['local_log_status'], 'failed')
        self.assertEqual(entry['local_log_error_type'], 'OSError')
        self.assertEqual(len(logged), 1)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.guard().inspect()['totals']['requests'], 14)

    def test_callback_cannot_change_authoritative_usage(self):
        def malicious(entry):
            entry['cost_micros'] = 0
            entry['usage']['total_tokens'] = 0
        self.guard().execute(self.body(), 'synthetic', self.send, malicious)
        self.assertEqual(self.guard().inspect()['totals']['cost_micros'], 182678)

    def test_unknown_usage_is_durable_and_blocks_any_later_send(self):
        def unknown(body):
            self.sent.append(body)
            return 200, {'id': 'synthetic', 'usage': {}}, 'synthetic'
        with self.assertRaisesRegex(budget.BudgetStop, 'usage_unknown'):
            self.guard().execute(self.body(), 'synthetic', unknown, lambda entry: None)
        current = budget.load(self.path)
        self.assertTrue(current['unknown_usage'])
        self.assertEqual(current['entries'][-1]['status'], 'unknown')
        self.assertEqual(current['entries'][:13], self.entries)
        with self.assertRaises(budget.BudgetStop):
            self.guard().execute(self.body(), 'synthetic-again', unknown, lambda entry: None)
        self.assertEqual(len(self.sent), 1)

    def test_persisted_pending_after_crash_blocks_send(self):
        self.data['entries'].append({'status': 'pending'})
        self.save()
        with self.assertRaises(budget.BudgetStop):
            self.guard().execute(self.body(), 'synthetic', self.send, lambda entry: None)
        self.assertFalse(self.sent)

    def test_request_token_and_cost_limits_include_all_13_old_entries(self):
        reserve = len(self.body()) + 16384
        for key, value in (('requests', 13), ('tokens', 135275 + reserve - 1),
                           ('cost_micros', 134478 + (len(self.body()) + 8192) * 2 + 8192 * 8 - 1)):
            with self.subTest(key=key):
                original = deepcopy(self.data['limits'])
                self.data['limits'][key] = value
                self.save()
                with self.assertRaisesRegex(budget.BudgetStop, 'remaining_balance'):
                    self.guard().execute(self.body(), 'synthetic', self.send, lambda entry: None)
                self.assertEqual(budget.load(self.path)['entries'], self.entries)
                self.data['limits'] = original
        self.assertFalse(self.sent)

    def test_reset_or_modified_prefix_is_rejected(self):
        for mode in ('reset', 'change'):
            with self.subTest(mode=mode):
                self.data['entries'] = [] if mode == 'reset' else deepcopy(self.entries)
                if mode == 'change':
                    self.data['entries'][0]['case'] = 'changed'
                self.save()
                with self.assertRaisesRegex(budget.BudgetStop, 'prefix_changed'):
                    self.guard().inspect()
        self.assertFalse(self.sent)

    def test_historical_unknown_index_cannot_be_dropped_or_changed(self):
        self.index.write_text('{"status":"pretend_zero"}', encoding='utf-8')
        with self.assertRaisesRegex(budget.BudgetStop, 'prior_unknown'):
            self.guard()

    def test_global_hard_limits_cannot_be_expanded_by_authorization(self):
        for key, value in (('max_c_requests', 65), ('max_c_tokens', 700001),
                           ('max_output_tokens', 8193), ('incremental_cost_limit_micros', 2200001)):
            with self.subTest(key=key):
                original = self.auth[key]
                self.auth[key] = value
                self.save()
                with self.assertRaisesRegex(budget.BudgetStop, 'allocation_limits'):
                    self.guard()
                self.auth[key] = original

    def test_no_bootstrap_of_missing_ledger(self):
        self.path.unlink()
        with self.assertRaisesRegex(budget.BudgetStop, 'no_bootstrap'):
            self.guard()
        self.assertFalse(self.path.exists())

    def test_request_wire_ceiling_must_match_per_request_reservation(self):
        for body, bound in ((self.body(8193), 8193), (self.body(2048), 8192),
                            (b'{}', 8192), (self.body(8192), True)):
            with self.subTest(body=body, bound=bound), self.assertRaises(budget.BudgetStop):
                self.guard().execute(body, 'synthetic', self.send, lambda entry: None, max_output_tokens=bound)
        self.assertFalse(self.sent)

    def test_per_request_lower_output_bound_is_recorded(self):
        def small(body):
            self.sent.append(body)
            return 200, {'id': 'small', 'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}, 'small'
        self.guard().execute(self.body(512), 'synthetic', small, lambda entry: None, max_output_tokens=512)
        self.assertEqual(budget.load(self.path)['entries'][-1]['max_output_tokens'], 512)

    def test_provider_violation_keeps_known_usage_but_stops_future_calls(self):
        with self.assertRaisesRegex(budget.BudgetStop, 'violation_known_usage'):
            self.guard().execute(self.body(2048), 'synthetic', self.send, lambda entry: None, max_output_tokens=2048)
        current = budget.load(self.path)
        self.assertFalse(current['unknown_usage'])
        self.assertEqual(current['entries'][-1]['status'], 'violation')
        self.assertEqual(current['entries'][-1]['cost_micros'], 48200)
        with self.assertRaises(budget.BudgetStop):
            self.guard().inspect()

    def test_same_ledger_lock_prevents_two_consumers_spending_last_request(self):
        self.data['limits']['requests'] = 14
        self.save()
        def execute_one(_):
            try:
                self.guard().execute(self.body(), 'synthetic', self.send, lambda entry: None)
                return 'complete'
            except budget.BudgetStop:
                return 'stopped'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(execute_one, range(2)))
        self.assertEqual(sorted(results), ['complete', 'stopped'])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.guard().inspect()['totals']['requests'], 14)

    def test_expired_authorization_stops_before_send(self):
        self.auth['expires_at_utc'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.save()
        with self.assertRaisesRegex(budget.BudgetStop, 'expired'):
            self.guard().execute(self.body(), 'synthetic', self.send, lambda entry: None)
        self.assertFalse(self.sent)

    def test_legacy_entry_cannot_use_new_8192_ceiling_retroactively(self):
        entry = self.data['entries'][0]
        entry['usage'] = {'prompt_tokens': 1, 'completion_tokens': 3000, 'total_tokens': 3001}
        entry['tokens'], entry['cost_micros'] = 3001, 24002
        self.auth['preserved_prefix']['entries_sha256'] = budget.prefix_digest(self.data['entries'])
        self.save()
        with self.assertRaisesRegex(budget.BudgetStop, 'prior_receipt_usage_or_cost_invalid'):
            self.guard().inspect()

    def test_cache_inconsistency_unknown_and_future_calls_blocked(self):
        def invalid(body):
            self.sent.append(body)
            return 200, {'id': 'bad', 'usage': {'prompt_tokens': 10, 'completion_tokens': 1,
                        'total_tokens': 11, 'prompt_cache_hit_tokens': 9, 'prompt_cache_miss_tokens': 9}}, 'bad'
        with self.assertRaisesRegex(budget.BudgetStop, 'cache_usage'):
            self.guard().execute(self.body(), 'synthetic', invalid, lambda entry: None)
        self.assertTrue(budget.load(self.path)['unknown_usage'])
        with self.assertRaises(budget.BudgetStop):
            self.guard().inspect()
