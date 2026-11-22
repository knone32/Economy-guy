"""Unbounded accounting: preserve explicitly acknowledged unknown attempts separately."""
from copy import deepcopy
from pathlib import Path
import hashlib, importlib.util, json
_original=Path(__file__).resolve().parent/'v3_shared_budget.py'
if not _original.is_file():
    _original=Path(__file__).resolve().parents[2]/'pending-relationship-fix/tools/v3_shared_budget.py'
_spec=importlib.util.spec_from_file_location('original_budget',_original)
base=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(base)
for _key in dir(base):
    if not _key.startswith('_'):globals()[_key]=getattr(base,_key)

class SharedBudget(base.SharedBudget):
    def validate(self,data):
        policy=self.auth.get('unknown_attempt_policy') or {}
        if (self.policy!=base.UNBOUNDED_POLICY or policy.get('authorized_by')!='user'
                or policy.get('authorized') is not True or not policy.get('instruction')):
            return super().validate(data)
        entries=data.get('entries');prefix=self.auth['preserved_prefix']
        if (not isinstance(entries,list) or len(entries)<prefix['entry_count']
                or base.prefix_digest(entries[:prefix['entry_count']])!=prefix['entries_sha256']):
            raise base.BudgetStop('preserved_prefix_changed_or_reset')
        acknowledged=policy.get('entries',{})
        unknown=[]
        for entry in entries:
            if not isinstance(entry,dict):raise base.BudgetStop('invalid_entry')
            if entry.get('status')=='complete':continue
            digest=hashlib.sha256(json.dumps(entry,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            if (entry.get('status') not in {'pending','unknown'} or acknowledged.get(entry.get('id'))!=digest
                    or not base.integer(entry.get('reserved_tokens')) or not base.integer(entry.get('reserved_cost_micros'))
                    or any(key in entry for key in ('usage','receipt_id','tokens','cost_micros'))):
                raise base.BudgetStop('unacknowledged_or_misrepresented_unknown_attempt')
            unknown.append(entry)
        # Validate all original metadata and every received usage against the
        # original validator. Only its complete-receipt projection is temporary;
        # the durable ledger, prefix and historical entries are never rewritten.
        known=[e for e in entries if e.get('status')=='complete']
        opening=[e for e in entries[:prefix['entry_count']] if e.get('status')=='complete']
        opening_totals={'requests':len(opening),'tokens':sum(e['tokens'] for e in opening),'cost_micros':sum(e['cost_micros'] for e in opening)}
        if opening_totals!=prefix['totals']:raise base.BudgetStop('preserved_prefix_totals_changed')
        projected=deepcopy(data);projected.update(entries=known,unknown_usage=False)
        auth=self.auth
        self.auth={**auth,'preserved_prefix':{'entry_count':len(opening),'entries_sha256':base.prefix_digest(opening),'totals':opening_totals}}
        try:return super().validate(projected)
        finally:self.auth=auth

    def inspect(self):
        with base.exclusive(self.path):
            data=base.load(self.path);totals=self.validate(data)
            unknown=[e for e in data['entries'] if e.get('status')!='complete']
            return {'totals':totals,'known_receipt_totals':totals,'physical_attempts':len(data['entries']),
                'unknown_usage':bool(unknown),'unknown_attempts':len(unknown),
                'unknown_reserved_upper_bounds':{'tokens':sum(e['reserved_tokens'] for e in unknown),
                    'cost_micros':sum(e['reserved_cost_micros'] for e in unknown)},
                'reservation_is_actual_usage':False,'unknown_entries':deepcopy(unknown),
                'limits':data['limits'],'budget_id':data['budget_id'],'cumulative_policy':self.policy,
                'accounting_basis':base.ACCOUNTING_BASIS,'prior_consumption_status':'unknown_preserved'}
