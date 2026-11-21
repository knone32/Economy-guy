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
from .references import resolve_reference


BUSINESS_KEYS = ('company_id', 'invoice_no', 'year', 'month', 'field', 'new_value')


def public_state(pending):
    known = {}
    for key in BUSINESS_KEYS:
        values = pending.get('change' if key in ('field', 'new_value') else 'scope', {}).get(key, ())
        if len(values) == 1:
            known[key] = values[0]
    return {'known': known, 'missing_fields': list(pending.get('missing_fields', ()))}


def bind_clarification(agent, fields, previous, request, *, field=None):
    """Use structured field candidates and original display identity, never prose."""
    editable=set(fields)&{'purpose','remark'}
    args=({'field':field} if field is not None else
          {'field':next(iter(editable))} if len(editable)==1 else {})
    if not previous or previous.get('business_action')!='single_invoice':
        previous=None
        if not agent.context.references_blocked and agent.context.display_ids:
            reference=resolve_reference(agent.db_path,agent.user_id,None,
                display_ids=agent.context.display_ids,coalesce_identical_singletons=True)
            if reference['status']=='SUCCESS':
                scope=reference['evidence']['scope']
                args.update(company_id=scope['company_id'],invoice_no=scope['invoice_no'])
        if not args:
            return tool_result('WAITING_USER',evidence={'source':'harness_business_action',
                'missing_fields':['invoice_no'],'business_authorization':False},
                error='没有唯一可信的当前单票，请先明确要办理的发票。'),None,None,[]
    # A final clarification does not request a preview. The original owner
    # rechecks scope/ACL/current values and retains only unapproved slots.
    return change_invoice(agent,args,previous,request,defer_preview=True)


def change_invoice(agent, args, previous, request, *, defer_preview=False):
    """Return result, pending state, candidate and actual runtime read evidence."""
    try:
        target_origin = None
        displays = agent.context.display_ids
        if (previous is None and all(key in args for key in ('company_id', 'invoice_no'))
                and not agent.context.references_blocked
                and isinstance(displays, list) and displays):
            resolved = resolve_reference(agent.db_path, agent.user_id, None, display_ids=displays,
                                         coalesce_identical_singletons=True)
            if resolved['status'] == 'SUCCESS':
                scope = resolved['evidence']['scope']
                if all(key not in args or args[key] == scope[key]
                       for key in ('company_id', 'invoice_no', 'year', 'month')):
                    target_origin = BoundIntent('read', agent.user_id, str(agent.db_path), agent.trace_id,
                        request, dict(scope), {'source': 'runtime_display_reference',
                                              'reference': resolved['evidence']['reference']})
                    agent.trace('business.target_reference', resolved['evidence'])
        internal_args = {({'year':'target_year','month':'target_month'}.get(k,k)):v for k,v in args.items()}
        candidate = request_change(internal_args, previous, actor=agent.user_id, book=agent.db_path,
            current_id=agent.trace_id, current_request=request, business_continuation=True,
            target_origin=target_origin)
    except PendingTransitionError as error:
        return tool_result(getattr(error, 'status', 'SCOPE_MISMATCH'), error=str(error), evidence={
            'source':'harness_business_action','user_message':str(error),
            'reason':getattr(error,'reason','source_or_identity'),
            'business_state_updated':getattr(error,'state_updated',False),
            **({'needs_value_reference_decision':True} if getattr(error,'repairable_reference',False) else {}),
            'business_authorization':False}), getattr(error,'pending_state',previous), None, []
    candidate['business_action'] = 'single_invoice'
    def stopped(status, message, reads=()):
        # Binding a replacement takes effect even if fresh reading/planning
        # later fails. Never return the superseded previous change.
        return tool_result(status,error=message,evidence={
            'source':'harness_business_action','user_message':message,
            'business_state_updated':True,'business_authorization':False}), candidate, None, list(reads)
    known = public_state(candidate)['known']
    def waiting(reads=()):
        question = ('请明确要修改的字段和对应内容，或确认是否替换上一要求；原要求暂不继续。'
                    if candidate.get('blocked_reason') == 'ambiguous_business_choice' else None)
        return tool_result('WAITING_USER', data=public_state(candidate), evidence={
            'source':'harness_business_action', 'missing_fields':list(candidate['missing_fields']),
            'user_message':question, 'business_authorization':False}), candidate, None, list(reads)
    if any(key not in known for key in ('company_id', 'invoice_no')):
        return waiting()
    if not agent.workbook_available():
        return stopped('ERROR','账簿身份已变化，未生成预览。')
    company, number = known['company_id'], known['invoice_no']
    try:
        with closing(open_existing(agent.db_path, readonly=True)) as db:
            row = get_invoice(db, agent.user_id, company, number)
    except (PermissionError, ValueError) as error:
        return stopped('DENIED','当前无法核验这张发票的访问权限，未生成预览。')
    except (OSError, sqlite3.Error):
        return stopped('ERROR','无法读取当前账簿，未生成预览。')
    if row is None:
        candidate['scope'].pop('invoice_no',None)
        candidate['provenance'].pop('invoice_no',None)
        candidate['missing_fields'] = ('invoice_no',)
        return stopped('NO_DATA','明确指定的发票不存在，请核对票号；未选择替代对象。')
    day = date.fromisoformat(row['invoice_date'])
    scope = {'company_id':company, 'invoice_no':number, 'year':day.year, 'month':day.month}
    read = tool_result('SUCCESS', data=row, evidence={'source':'current_sqlite', 'scope':scope})
    agent.trace('business.invoice_read', {'arguments':{'company_id':company,'invoice_no':number}, 'result':read})
    reads = [('get_invoice', read)]
    if any(key in known and known[key] != value for key, value in (('year', day.year), ('month', day.month))):
        candidate['scope'].pop('invoice_no',None)
        candidate['provenance'].pop('invoice_no',None)
        candidate['missing_fields'] = ('invoice_no',)
        return stopped('SCOPE_MISMATCH','实际发票账期与本次办理要求不一致，请重新核对目标票号。',reads)
    for key, value in (('year', day.year), ('month', day.month)):
        if key not in known:
            candidate['scope'][key] = [value]
            candidate['provenance'][key] = {'kind': 'current_sqlite', 'company_id': company,
                'invoice_no': number, 'invoice_date': row['invoice_date'], 'turn_id': agent.trace_id}
    candidate['scope']['periods'] = [(day.year, day.month)]
    candidate['missing_fields'] = tuple(key for key in BUSINESS_KEYS
        if len(candidate.get('change' if key in ('field', 'new_value') else 'scope', {}).get(key, ())) != 1)
    known = public_state(candidate)['known']
    if (defer_preview or candidate['missing_fields']
            or candidate.get('blocked_reason') == 'ambiguous_business_choice'):
        return waiting(reads)
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
        # Only source-checked business slots survive interruption. Draft,
        # request/fingerprint approval and current invoice values never do.
        agent.ticket_preview_candidate = candidate
        agent.trace('business.invoice_preview_candidate', {'candidate':planned})
        return result, None, planned, reads
    return stopped(status,error or '当前办理未能形成预览，请补充核对要求。',reads)
