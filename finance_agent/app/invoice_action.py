"""Single-invoice business action. Runtime owns state and execution references.

No model selection token, lifecycle event or authorization enters this adapter.
It delegates facts, permissions, planning and later preview to existing services.
"""
from contextlib import closing
from datetime import date
import sqlite3

from .pending_transition import request_change, PendingTransitionError
from .queries import get_invoice
from .stage2_schema import open_existing
from .tool_registry import tool_result
from .intent_contract import BoundIntent
from .invoice_batch import plan_invoice_change
from .tui_intent import excluded_invoice_ids


BUSINESS_KEYS = ('company_id', 'invoice_no', 'year', 'month', 'field', 'new_value')


def public_state(pending):
    known = {}
    for key in BUSINESS_KEYS:
        values = pending.get('change' if key in ('field', 'new_value') else 'scope', {}).get(key, ())
        if len(values) == 1:
            known[key] = values[0]
    return {'known': known, 'missing_fields': list(pending.get('missing_fields', ()))}


def change_invoice(agent, args, previous, request):
    """Return result, pending state, candidate and actual runtime read evidence."""
    try:
        internal_args = {({'year':'target_year','month':'target_month'}.get(k,k)):v for k,v in args.items()}
        candidate = request_change(internal_args, previous, actor=agent.user_id, book=agent.db_path,
            current_id=agent.trace_id, current_request=request, business_continuation=True)
    except PendingTransitionError as error:
        return tool_result(getattr(error, 'status', 'SCOPE_MISMATCH'), error=str(error)), previous, None, []
    candidate['business_action'] = 'single_invoice'
    known = public_state(candidate)['known']
    if any(key not in known for key in BUSINESS_KEYS):
        return tool_result('WAITING_USER', data=public_state(candidate), evidence={
            'source':'harness_business_action', 'missing_fields':list(candidate['missing_fields']),
            'business_authorization':False}), candidate, None, []
    if not agent.workbook_available():
        return tool_result('ERROR', error='账簿身份已变化，未生成预览。'), previous, None, []
    company, number = known['company_id'], known['invoice_no']
    try:
        with closing(open_existing(agent.db_path, readonly=True)) as db:
            row = get_invoice(db, agent.user_id, company, number)
    except (PermissionError, ValueError) as error:
        return tool_result('DENIED', error=str(error)), previous, None, []
    except (OSError, sqlite3.Error):
        return tool_result('ERROR', error='无法读取当前账簿，未生成预览。'), previous, None, []
    if row is None:
        return tool_result('NO_DATA', error='明确指定的发票不存在，未选择替代对象。'), previous, None, []
    day = date.fromisoformat(row['invoice_date'])
    scope = {'company_id':company, 'invoice_no':number, 'year':day.year, 'month':day.month}
    read = tool_result('SUCCESS', data=row, evidence={'source':'current_sqlite', 'scope':scope})
    agent.trace('business.invoice_read', {'arguments':{'company_id':company,'invoice_no':number}, 'result':read})
    reads = [('get_invoice', read)]
    if (day.year, day.month) != (known['year'], known['month']):
        return tool_result('SCOPE_MISMATCH', error='实际发票账期与可信办理要求不一致。'), previous, None, reads
    # This witness is constructed by trusted runtime after request_change has
    # validated every supplied/inherited slot. It is never model-supplied data.
    witness = BoundIntent('amend', agent.user_id, str(agent.db_path), agent.trace_id,
        request, dict(known), {'source':'runtime_validated_business_state'}, candidate['request_id'])
    write_scope = {key:[known[key]] for key in ('company_id','invoice_no','year','month')}
    write_scope['periods'] = [(known['year'], known['month'])]
    excluded = excluded_invoice_ids(candidate['source_request'])
    proposal = {'field':known['field'], 'new_value':known['new_value'], 'mode':'item',
        'excluded_invoice_ids':list(excluded), 'target_year':known['year'], 'target_month':known['month']}
    selection = (((company, number),), scope, 'get_invoice')
    bound = {'write':candidate['source_request'], 'write_scope':write_scope, 'excluded':excluded,
        'field_evidence':{key:[known[key]] for key in ('field','new_value')}, 'bound_intent':witness}
    planned, status, error = plan_invoice_change(agent, candidate['source_request'], proposal, selection,
        authorized_periods=((day.year,day.month),), read_results=reads, scoped_edit=bound)
    result = tool_result(status, data=public_state(candidate), evidence={
        'source':'harness_business_action', 'business_authorization':False}, error=error)
    if planned:
        agent.trace('business.invoice_preview_candidate', {'candidate':planned})
        return result, None, planned, reads
    return result, previous, None, reads
