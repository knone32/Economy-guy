"""Source-bounded clarification events, independent of prose kind or read sets."""
from copy import deepcopy


class PendingTransitionError(ValueError):
    pass


def contract_error(final, narrow):
    if final is None:
        return 'invalid_final_envelope' if narrow else None
    declared = any(k in final for k in ('missing_fields', 'pending', 'pending_change'))
    if (not narrow and not declared) or (final.get('kind') == 'general' and not declared):
        return None
    if 'missing_fields' not in final:
        return 'missing_fields_required'
    missing = final['missing_fields']
    if type(missing) is not list or any(type(v) is not str or not v.strip() for v in missing):
        return 'invalid_missing_fields'
    event = final.get('pending')
    if missing and not event:
        return 'pending_event_required_for_waiting'
    if event and event.get('action') == 'cancel' and (missing or final.get('pending_change') or event.get('scope')):
        return 'inconsistent_cancel_event'
    if event and event.get('action') in {'create', 'replace'} and missing and not event.get('scope'):
        return 'explicit_candidate_scope_required'
    return None


def transition(previous, event, *, actor, book, current_id, current_request,
               current_scope, missing_fields, change=None):
    """Validate a model slot patch; lexical mentions only bound admissibility.

    No assistant question text or tool-result rows become a write candidate set.
    Actual tools still require fresh selection, permissions and human approval.
    """
    if type(event) is not dict or set(event) - {'action', 'request_id', 'scope'}:
        raise PendingTransitionError('invalid_pending_event')
    action = event.get('action')
    if action not in {'create', 'continue', 'replace', 'cancel'}:
        raise PendingTransitionError('invalid_pending_action')
    if previous and (previous.get('actor') != actor or previous.get('workbook') != str(book)):
        raise PendingTransitionError('pending_context_mismatch')
    if action == 'create':
        if previous is not None:
            raise PendingTransitionError('pending_already_exists')
        if event.get('request_id', current_id) != current_id:
            raise PendingTransitionError('create_id_is_server_owned')
    elif previous is None or event.get('request_id') != previous.get('request_id'):
        raise PendingTransitionError('stale_pending_reference')
    if action == 'cancel':
        if missing_fields or change is not None or event.get('scope'):
            raise PendingTransitionError('inconsistent_cancel_event')
        return None
    if not missing_fields:
        raise PendingTransitionError('waiting_event_requires_missing_fields')
    prior = deepcopy((previous or {}).get('scope', {}))
    patch = event.get('scope', {})
    if type(patch) is not dict or set(patch) - {'company_id', 'invoice_no', 'year', 'month', 'periods'}:
        raise PendingTransitionError('invalid_pending_scope')
    if action in {'create', 'replace'} and not patch:
        raise PendingTransitionError('explicit_candidate_scope_required')
    # Retain unambiguous user-sourced owner/date slots on initial creation;
    # identities still require a declared candidate set, never the read set.
    scope = dict(prior) if previous else {k: deepcopy(v) for k, v in current_scope.items()
        if k != 'invoice_no' and len(v) == 1}
    if action == 'create' and current_scope.get('invoice_no') and 'invoice_no' not in patch:
        raise PendingTransitionError('explicit_invoice_candidates_required')
    for key, values in patch.items():
        if type(values) is not list or not values:
            raise PendingTransitionError('scope_slots_require_nonempty_lists')
        if key == 'periods':
            if any(not isinstance(v, (list, tuple)) or len(v) != 2 or
                   any(type(n) is not int for n in v) or not 1 <= v[0] <= 9999 or not 1 <= v[1] <= 12 for v in values):
                raise PendingTransitionError('invalid_pending_period')
            values = [tuple(v) for v in values]
        elif key in {'year', 'month'}:
            if any(type(v) is not int or not 1 <= v <= (9999 if key == 'year' else 12) for v in values):
                raise PendingTransitionError('invalid_pending_date')
        elif any(type(v) is not str for v in values):
            raise PendingTransitionError('invalid_pending_identifier')
        available = list(prior.get(key, ())) + list(current_scope.get(key, ()))
        if key == 'periods':
            available = [tuple(v) for v in available]
        if any(v not in available for v in values):
            raise PendingTransitionError('pending_scope_without_source')
        scope[key] = deepcopy(values)
    if 'periods' in patch:
        years = list(dict.fromkeys(y for y, _ in scope['periods']))
        months = list(dict.fromkeys(m for _, m in scope['periods']))
        if (('year' in patch and set(patch['year']) != set(years)) or
                ('month' in patch and set(patch['month']) != set(months))):
            raise PendingTransitionError('pending_period_slot_conflict')
        scope['year'], scope['month'] = years, months
    elif 'year' in patch or 'month' in patch:
        if len(scope.get('year', ())) == len(scope.get('month', ())) == 1:
            paired = (scope['year'][0], scope['month'][0])
            available_pairs = {tuple(v) for v in list(prior.get('periods', ())) + list(current_scope.get('periods', ()))}
            # One explicitly supplied date slot may amend a previously unique
            # complete date. Two separately supplied complete dates may not be
            # recombined through their year/month projections.
            prior_pairs = list(prior.get('periods', ()))
            if len(prior_pairs) == 1 and not current_scope.get('periods'):
                old_year, old_month = prior_pairs[0]
                if len(current_scope.get('year', ())) == 1 and not current_scope.get('month'):
                    available_pairs.add((current_scope['year'][0], old_month))
                if len(current_scope.get('month', ())) == 1 and not current_scope.get('year'):
                    available_pairs.add((old_year, current_scope['month'][0]))
            if paired not in available_pairs:
                raise PendingTransitionError('pending_date_pair_without_source')
            scope['periods'] = [paired]
        else:
            scope.pop('periods', None)
    source = ((previous or {}).get('source_request') or (previous or {}).get('request') or '')
    source = '\n'.join(s for s in (source, current_request) if s)
    pending = {'request_id': current_id, 'request': source, 'source_request': source,
               'scope': scope, 'actor': actor, 'workbook': str(book),
               'missing_fields': tuple(missing_fields), 'model_managed': True}
    if change is not None:
        if (type(change) is not dict or set(change) != {'field', 'new_value'} or
                change['field'] not in {'purpose', 'remark'} or type(change['new_value']) is not str):
            raise PendingTransitionError('invalid_pending_change')
        if change['new_value'] and change['new_value'] not in source:
            raise PendingTransitionError('pending_value_without_source')
        pending['change'] = {k: [v] for k, v in change.items()}
    elif previous and previous.get('change'):
        pending['change'] = deepcopy(previous['change'])
    return pending
