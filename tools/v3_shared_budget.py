"""Append-only V3 adapter for an existing main-control ledger; no HTTP/bootstrap.

Costs are conservative peak-price ceilings derived from received usage, never a
provider bill. Historical unknown spending and the original entry prefix remain
preserved. The caller owns physical transport retry prevention and authorization.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import os
from pathlib import Path
import time
import uuid


PEAK_RATES = {'input_hit': 0.04, 'input_miss': 2, 'output': 8}
ACCOUNTING_BASIS = 'conservative_peak_price_upper_bound_not_provider_bill'
BOUNDED_POLICY = 'bounded-cumulative-v1'
UNBOUNDED_POLICY = 'explicit-unbounded-cumulative-v1'
CUMULATIVE_FIELDS = ('max_c_requests', 'max_c_tokens', 'incremental_cost_limit_micros')


class BudgetStop(RuntimeError):
    pass


class LocalLogError(BudgetStop):
    """HTTP usage is durably accounted; local evidence saving failed. Never resend."""


def now():
    return datetime.now(timezone.utc).isoformat()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def prefix_digest(entries):
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def atomic(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@contextmanager
def exclusive(path, timeout=60):
    """Use the original ledger's same byte lock through send and receipt storage."""
    lock = Path(str(path) + '.lock').open('a+b')
    lock.seek(0, 2)
    if lock.tell() == 0:
        lock.write(b'0')
        lock.flush()
    deadline, acquired = time.monotonic() + timeout, False
    try:
        while not acquired:
            lock.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise BudgetStop('shared_budget_lock_timeout')
                time.sleep(0.1)
        yield
    finally:
        if acquired:
            lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def integer(value):
    return type(value) is int and value >= 0


def charge(tokens, rate):
    return int((Decimal(tokens) * Decimal(str(rate))).to_integral_value(rounding=ROUND_CEILING))


def usage_charge(usage):
    if not isinstance(usage, dict):
        raise BudgetStop('http_or_usage_unknown')
    prompt, output, total = (usage.get(key) for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'))
    if not all(integer(value) for value in (prompt, output, total)) or prompt + output != total:
        raise BudgetStop('http_or_usage_unknown')
    hit, miss = usage.get('prompt_cache_hit_tokens'), usage.get('prompt_cache_miss_tokens')
    missing_cache = hit is None and miss is None
    if missing_cache:
        hit, miss = 0, prompt
    if not integer(hit) or not integer(miss) or hit + miss != prompt:
        raise BudgetStop('cache_usage_inconsistent')
    cost = charge(hit, PEAK_RATES['input_hit']) + charge(miss, PEAK_RATES['input_miss']) + charge(output, PEAK_RATES['output'])
    return prompt, output, total, cost, missing_cache


class SharedBudget:
    def __init__(self, authorization, owner='C'):
        self.auth, self.owner = load(authorization), owner
        self.path = Path(self.auth['shared_ledger_path']).resolve()
        if (self.auth.get('authorized') is not True or self.auth.get('template_only')
                or self.auth.get('owner') != owner or owner != 'C'):
            raise BudgetStop('no_main_control_authorization')
        if self.auth.get('budget_mode') != 'incremental-cohort-budget-v1':
            raise BudgetStop('existing_incremental_cohort_required')
        self.policy = self.auth.get('cumulative_policy', BOUNDED_POLICY)
        if type(self.policy) is not str or self.policy not in {BOUNDED_POLICY, UNBOUNDED_POLICY}:
            raise BudgetStop('unknown_cumulative_policy')
        if self.policy == UNBOUNDED_POLICY:
            authority = self.auth.get('cumulative_policy_authorization')
            if (not isinstance(authority, dict) or authority.get('authorized') is not True
                    or authority.get('authorized_by') != 'user'
                    or not isinstance(authority.get('instruction'), str) or not authority['instruction'].strip()
                    or any(key not in self.auth or self.auth[key] is not None for key in CUMULATIVE_FIELDS)):
                raise BudgetStop('explicit_unbounded_cumulative_authorization_required')
            bounded_fields = (('max_output_tokens', 8192),)
        else:
            bounded_fields = (('max_c_requests', 64), ('max_c_tokens', 700000),
                              ('max_output_tokens', 8192), ('incremental_cost_limit_micros', 2200000))
        for key, ceiling in bounded_fields:
            if not integer(self.auth.get(key)) or not 0 < self.auth[key] <= ceiling:
                raise BudgetStop('invalid_allocation_limits')
        if self.auth.get('accounting_scope') != 'new_explicit_authorization':
            raise BudgetStop('explicit_incremental_authorization_required')
        if not self.path.is_file():
            raise BudgetStop('main_control_shared_ledger_required_no_bootstrap')
        preserved = self.auth.get('preserved_prefix') or {}
        if (not integer(preserved.get('entry_count')) or preserved['entry_count'] < 1
                or not isinstance(preserved.get('entries_sha256'), str)
                or len(preserved['entries_sha256']) != 64 or not isinstance(preserved.get('totals'), dict)):
            raise BudgetStop('preserved_existing_prefix_required')
        self.validate_prior_index(self.auth.get('prior_consumption'))

    def validate_prior_index(self, prior):
        if not isinstance(prior, dict) or prior.get('status') != 'unknown_preserved':
            raise BudgetStop('prior_unknown_must_be_preserved')
        path, digest = prior.get('evidence_index_path'), prior.get('evidence_index_sha256')
        if (not isinstance(path, str) or not Path(path).is_absolute() or not Path(path).is_file()
                or hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest):
            raise BudgetStop('prior_unknown_evidence_index_changed_or_missing')

    def validate(self, data):
        if (data.get('schema') != self.auth['budget_mode'] or data.get('budget_id') != self.auth.get('budget_id')
                or data.get('initialized_by') != 'main_control' or data.get('template_only')):
            raise BudgetStop('shared_ledger_identity_mismatch')
        if data.get('unknown_usage') is not False:
            raise BudgetStop('shared_ledger_not_reconciled')
        if data.get('cumulative_policy', BOUNDED_POLICY) != self.policy:
            raise BudgetStop('cumulative_policy_mismatch')
        if self.policy == UNBOUNDED_POLICY and (
                data.get('cumulative_policy_authorization') != self.auth['cumulative_policy_authorization']):
            raise BudgetStop('cumulative_policy_authorization_mismatch')
        if (data.get('accounting_scope') != self.auth['accounting_scope']
                or data.get('prior_consumption') != self.auth.get('prior_consumption')):
            raise BudgetStop('incremental_scope_or_prior_index_mismatch')
        self.validate_prior_index(data['prior_consumption'])
        if 'carry_forward' in data or data.get('cohort_opening') != {'requests': 0, 'tokens': 0, 'cost_micros': 0}:
            raise BudgetStop('existing_cohort_opening_changed')
        entries, preserved = data.get('entries'), self.auth['preserved_prefix']
        if (not isinstance(entries, list) or len(entries) < preserved['entry_count']
                or prefix_digest(entries[:preserved['entry_count']]) != preserved['entries_sha256']):
            raise BudgetStop('preserved_prefix_changed_or_reset')
        if any(not isinstance(entry, dict) or entry.get('status') != 'complete' for entry in entries):
            raise BudgetStop('pending_or_unknown_prior_request_stop')
        if data.get('rates_cny_per_million') != PEAK_RATES:
            raise BudgetStop('conservative_peak_rate_card_required')
        for position, entry in enumerate(entries):
            _, output, total, cost, _ = usage_charge(entry.get('usage'))
            bound = entry.get('max_output_tokens', 2048)
            if (entry.get('owner') != self.owner or not integer(bound) or not 1 <= bound <= 8192
                    or not isinstance(entry.get('receipt_id'), str) or not entry['receipt_id']
                    or not integer(entry.get('tokens')) or not integer(entry.get('cost_micros'))
                    or total != entry.get('tokens') or cost != entry.get('cost_micros') or output > bound):
                raise BudgetStop('prior_receipt_usage_or_cost_invalid')
            if position >= preserved['entry_count'] and entry.get('adapter_version') != 'v3':
                raise BudgetStop('unrecognized_post_prefix_accounting')
            if entry.get('adapter_version') == 'v3' and (
                    entry.get('rates_cny_per_million') != PEAK_RATES
                    or entry.get('accounted_cost_ceiling_micros') != cost
                    or entry.get('accounting_basis') != ACCOUNTING_BASIS):
                raise BudgetStop('v3_accounting_basis_changed')
        prefix = entries[:preserved['entry_count']]
        opening = {'requests': len(prefix), 'tokens': sum(e['tokens'] for e in prefix),
                   'cost_micros': sum(e['cost_micros'] for e in prefix)}
        if opening != preserved['totals']:
            raise BudgetStop('preserved_prefix_totals_changed')
        totals = {'requests': len(entries), 'tokens': sum(e['tokens'] for e in entries),
                  'cost_micros': sum(e['cost_micros'] for e in entries)}
        if totals != data.get('totals'):
            raise BudgetStop('cumulative_ledger_inconsistent')
        ceilings = {'requests': self.auth['max_c_requests'], 'tokens': self.auth['max_c_tokens'],
                    'cost_micros': self.auth['incremental_cost_limit_micros']}
        for key, ceiling in ceilings.items():
            limit = data.get('limits', {}).get(key)
            if self.policy == UNBOUNDED_POLICY:
                if key not in data.get('limits', {}) or limit is not None:
                    raise BudgetStop('explicit_null_unbounded_limits_required')
            elif not integer(limit) or not totals[key] <= limit <= ceiling:
                raise BudgetStop('shared_account_ceiling')
        expiration = datetime.fromisoformat(self.auth['expires_at_utc'])
        if expiration.tzinfo is None or datetime.now(timezone.utc) >= expiration:
            raise BudgetStop('authorization_expired')
        return totals

    def inspect(self):
        with exclusive(self.path):
            data = load(self.path)
            return {'totals': self.validate(data), 'limits': data['limits'], 'budget_id': data['budget_id'],
                    'cumulative_policy': self.policy,
                    'accounting_basis': ACCOUNTING_BASIS, 'prior_consumption_status': 'unknown_preserved',
                    'historical_cumulative_limit_micros': (None if self.policy == UNBOUNDED_POLICY else 42000000),
                    'historical_cumulative_compliance': 'UNKNOWN_NOT_ZERO'}

    def _save_local(self, data, entry, save_local):
        try:
            save_local(deepcopy(entry))
        except BaseException as error:
            entry.update(local_log_status='failed', local_log_error_type=type(error).__name__)
            atomic(self.path, data)
            raise LocalLogError('local_log_failed_usage_accounting_preserved_do_not_resend') from error
        entry['local_log_status'] = 'saved'
        atomic(self.path, data)

    def execute(self, request_body, case_id, send, save_local, *, max_output_tokens=None):
        """One send of exact JSON bytes; body max_tokens must match the reservation."""
        try:
            body = json.loads(request_body)
            bound = self.auth['max_output_tokens'] if max_output_tokens is None else max_output_tokens
            if (type(request_body) is not bytes or not integer(bound) or not 1 <= bound <= self.auth['max_output_tokens']
                    or not isinstance(body, dict) or type(body.get('max_tokens')) is not int
                    or body['max_tokens'] != bound or 'max_completion_tokens' in body):
                raise ValueError('output ceiling mismatch')
        except (ValueError, TypeError, UnicodeError):
            raise BudgetStop('request_output_ceiling_mismatch') from None
        reserve_input = len(request_body) + 8192
        reserve_tokens = reserve_input + bound
        reserve_cost = charge(reserve_input, PEAK_RATES['input_miss']) + charge(bound, PEAK_RATES['output'])
        with exclusive(self.path):
            data = load(self.path)
            totals = self.validate(data)
            reservation = {'requests': 1, 'tokens': reserve_tokens, 'cost_micros': reserve_cost}
            if any(data['limits'][key] is not None and totals[key] + value > data['limits'][key]
                   for key, value in reservation.items()):
                raise BudgetStop('shared_remaining_balance_or_reservation')
            entry = {'id': uuid.uuid4().hex, 'owner': self.owner, 'case': case_id, 'status': 'pending',
                     'adapter_version': 'v3', 'started_at': now(), 'pid': os.getpid(),
                     'body_sha256': hashlib.sha256(request_body).hexdigest(), 'max_output_tokens': bound,
                     'rates_cny_per_million': dict(PEAK_RATES), 'accounting_basis': ACCOUNTING_BASIS,
                     'reserved_tokens': reserve_tokens, 'reserved_cost_micros': reserve_cost}
            data['entries'].append(entry)
            atomic(self.path, data)  # Durable before HTTP; a crash blocks subsequent requests.
            try:
                status, payload, receipt_id = send(request_body)
                if (status != 200 or not isinstance(payload, dict) or not isinstance(receipt_id, str)
                        or not receipt_id or payload.get('id') != receipt_id):
                    raise BudgetStop('http_or_usage_unknown')
                prompt, output, total, cost, missing_cache = usage_charge(payload.get('usage'))
            except BaseException as error:
                data['unknown_usage'] = True
                entry.update(status='unknown', error_type=type(error).__name__, ended_at=now())
                atomic(self.path, data)
                raise
            violated = prompt > reserve_input or output > bound or total > reserve_tokens or cost > reserve_cost
            entry.update(status='violation' if violated else 'complete', tokens=total, cost_micros=cost,
                         accounted_cost_ceiling_micros=cost, usage=deepcopy(payload['usage']),
                         cost_basis=('all_input_cache_miss_at_peak_price_upper_bound' if missing_cache else
                                     'provider_cache_usage_at_peak_price_upper_bound'),
                         receipt_id=receipt_id, ended_at=now(), local_log_status='not_attempted')
            data['totals'] = {key: totals[key] + value for key, value in
                              {'requests': 1, 'tokens': total, 'cost_micros': cost}.items()}
            atomic(self.path, data)  # Known usage must never be overwritten by local-log errors.
            self._save_local(data, entry, save_local)
            if violated:
                raise BudgetStop('reservation_or_output_violation_known_usage_preserved')
            return status, payload
