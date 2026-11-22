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
from .references import resolve_reference, display_collection


BUSINESS_KEYS = ('company_id', 'invoice_no', 'year', 'month', 'field', 'new_value')


def public_state(pending):
    known = {}
    for key in BUSINESS_KEYS:
        values = pending.get('change' if key in ('field', 'new_value') else 'scope', {}).get(key, ())
        if len(values) == 1:
            known[key] = values[0]
    return {'known': known, 'missing_fields': list(pending.get('missing_fields', ()))}


def can_bind_selection(agent, previous, request, revision_origin):
    """Read-only eligibility for handing a sourced selection to this owner."""
    from .business_sources import checked_revision, checked_change
    revision=checked_revision(revision_origin,actor=agent.user_id,book=agent.db_path,
        current_id=agent.trace_id,current_request=request)
    change=revision.get('pending_change')
    if (revision.get('reference_relation')!='displayed' or change is None
            or revision.get('field') not in {'purpose','remark'}
            or checked_change(change,request)['field']!=revision['field']
            or agent.context.references_blocked):return False
    if previous:
        if (previous.get('business_action')!='single_invoice'
                or (previous.get('actor'),previous.get('workbook'))!=(agent.user_id,str(agent.db_path))
                or revision.get('matter_relation')!='continue'
                or previous.get('scope',{}).get('invoice_no')
                or previous.get('on_hold') or previous.get('blocked_reason')):return False
    elif revision.get('matter_relation')!='new':return False
    collection=(previous or {}).get('reference_collection')
    if collection:
        available=display_collection(agent.db_path,agent.user_id,**collection)
    elif agent.context.display_ids:
        available=display_collection(agent.db_path,agent.user_id,agent.context.display_ids)
    else:return False
    return (available['status']=='SUCCESS'
        and not available['evidence'].get('common_scope',{}).get('invoice_no')
        and len({tuple(sorted(entry['key'].items())) for entry in available['data']})>1)


def bind_clarification(agent, fields, previous, request, *, field=None, change=None, defer_preview=False,revision_origin=None):
    """Send source-bearing structured candidates to the original action owner."""
    editable=set(fields)&{'purpose','remark'}
    args=({'field':field} if field is not None else
          {'field':next(iter(editable))} if len(editable)==1 else {})
    if change is not None:
        from .business_sources import checked_change
        try:
            patch=checked_change(change,request)
        except PendingTransitionError as error:
            return tool_result('DENIED',error=str(error)),previous,None,[]
        if args.get('field',patch['field'])!=patch['field']:
            return tool_result('DENIED',error='待补新值缺少一致的本轮结构化来源；未采用正文中的内容。'),previous,None,[]
        args.update(patch)
        if not change['new_value']:
            args['value_ref']='clear'
    if not previous or previous.get('business_action')!='single_invoice':previous=None
    return change_invoice(agent,args,previous,request,defer_preview=defer_preview,revision_origin=revision_origin)


def change_invoice(agent, args, previous, request, *, defer_preview=False,revision_origin=None):
    """Return result, pending state, candidate and actual runtime read evidence."""
    collection=None
    matter=None
    try:
        from .business_sources import checked_revision
        revision=checked_revision(revision_origin,actor=agent.user_id,book=agent.db_path,current_id=agent.trace_id,current_request=request)
        # The independent stage owns its typed candidate until this original
        # owner binds it. A later proposal can omit it, never silently change it.
        if revision.get('pending_change') is not None:
            from .business_sources import checked_change
            patch=checked_change(revision['pending_change'],request)
            if any(key in args and args[key]!=value for key,value in patch.items()):
                return tool_result('DENIED',error='执行候选与独立阶段的当前新值或字段冲突。'),previous,None,[]
            args={**patch,**args}
            if not patch['new_value']:args['value_ref']='clear'
        matter=revision.get('matter_relation')
        if previous and (matter=='new' or previous.get('reference_collection') and matter!='continue'):
            message=('请先明确旧待选事项是保留暂缓还是取消；处置后才能独立办理新事项。' if matter=='new' else
                '请明确本次是在原集合中继续选票，还是发起新事项；原待补保持不变。')
            return tool_result('WAITING_USER',data=public_state(previous),error=message,evidence={
                'source':'harness_business_action','user_message':message,'matter_disposition_required':True,
                'business_state_updated':False,'business_authorization':False}),previous,None,[]
        target_origin = None
        displays = agent.context.display_ids
        collection=(previous or {}).get('reference_collection')
        reference=revision.get('reference_relation')
        if reference=='displayed' and agent.context.references_blocked and not collection:
            return tool_result('AMBIGUOUS',error='展示引用已失效，请重新查询候选。'),previous,None,[]
        if collection is None and reference not in {'none','unclear'} and (matter!='new' or reference=='displayed') and not agent.context.references_blocked and displays:
            available=display_collection(agent.db_path,agent.user_id,displays)
            if revision.get('reference_relation')=='displayed' and available['status']!='SUCCESS':
                return available,previous,None,[]
            if available['status']=='SUCCESS' and len({tuple(sorted(e['key'].items())) for e in available['data']})>1:
                collection=available['evidence']['reference_collection']
        if revision.get('reference_relation')=='displayed' and not displays and not collection:
            return tool_result('AMBIGUOUS',error='没有可信的已展示集合，请重新列出候选。'),previous,None,[]
        if collection:
            available=display_collection(agent.db_path,agent.user_id,**collection)
            if available['status']!='SUCCESS':
                return available,previous,None,[]
            if available['evidence'].get('common_scope'):
                target_origin=BoundIntent('read',agent.user_id,str(agent.db_path),agent.trace_id,request,
                    dict(available['evidence']['common_scope']),
                    {'source':'runtime_display_reference','reference':{'collection':collection}})
            if args.get('invoice_no'):
                from .business_object_sources import amendment_sources
                literal,_,_=amendment_sources(request,None,actor=agent.user_id,book=agent.db_path,
                    invoice_candidates=[args['invoice_no']])
                selected=[entry for entry in available['data'] if entry['key']['invoice_no']==args['invoice_no']
                    and (not literal.get('company_id') or entry['key']['company_id'] in literal['company_id'])]
                keys={tuple(sorted(entry['key'].items())) for entry in selected}
                if literal.get('invoice_no')!=[args['invoice_no']] or len(keys)!=1:
                    return tool_result('AMBIGUOUS',error='请在原展示集合中明确企业和票号；不会代选或选择集合外对象。'),previous,None,[]
                chosen=selected[-1]
                resolved=resolve_reference(agent.db_path,agent.user_id,chosen['ordinal'],anchor_id=chosen['anchor_id'],
                    display_ids=collection['display_ids'])
                if resolved['status']!='SUCCESS':return resolved,previous,None,[]
                target_origin=BoundIntent('read',agent.user_id,str(agent.db_path),agent.trace_id,request,
                    dict(resolved['evidence']['scope']),{'source':'runtime_display_reference','reference':resolved['evidence']['reference']})
        if (target_origin is None and previous is None and not collection
                and reference not in {'none','unclear'} and (matter!='new' or reference=='displayed')
                and not agent.context.references_blocked
                and isinstance(displays, list) and displays):
            # Both tool proposals and final clarifications may omit keys held
            # by the same unique trusted display. Supplied keys must still agree.
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
            target_origin=target_origin,revision_origin=revision_origin)
    except PendingTransitionError as error:
        partial=getattr(error,'pending_state',None)
        if collection and partial is not None:partial['reference_collection']=collection
        return tool_result(getattr(error, 'status', 'SCOPE_MISMATCH'), error=str(error), evidence={
            'source':'harness_business_action','user_message':str(error),
            'reason':getattr(error,'reason','source_or_identity'),
            'business_state_updated':getattr(error,'state_updated',False),
            'new_matter_accepted':previous is None and matter=='new' and partial is not None,
            **({'conflicting_slots':[{'target_year':'year','target_month':'month'}.get(key,key) for key in error.conflicting_slots],
                'retryable_after_slot_correction':True}
               if getattr(error,'conflicting_slots',None) else {}),
            **({'needs_value_reference_decision':True} if getattr(error,'repairable_reference',False) else {}),
            'business_authorization':False}), getattr(error,'pending_state',previous), None, []
    if collection:candidate['reference_collection']=collection
    candidate['business_action'] = 'single_invoice'
    def stopped(status, message, reads=()):
        # Binding a replacement takes effect even if fresh reading/planning
        # later fails. Never return the superseded previous change.
        return tool_result(status,error=message,evidence={
            'source':'harness_business_action','user_message':message,
            'business_state_updated':True,'new_matter_accepted':previous is None and matter=='new',
            'business_authorization':False}), candidate, None, list(reads)
    known = public_state(candidate)['known']
    def waiting(reads=()):
        question = ('请明确要修改的字段和对应内容，或确认是否替换上一要求；原要求暂不继续。'
                    if candidate.get('blocked_reason') == 'ambiguous_business_choice' else None)
        if collection and 'invoice_no' not in known:
            question=('修改内容与原展示候选已保留' if 'new_value' in known else '修改字段与原展示候选已保留，修改内容尚待补充')+'，尚未保存。请选择候选中的企业和票号；未选定前不读取单票或生成预览。'
        return tool_result('WAITING_USER', data=public_state(candidate), evidence={
            'source':'harness_business_action', 'missing_fields':list(candidate['missing_fields']),
            'user_message':question,'new_matter_accepted':previous is None and matter=='new', 'business_authorization':False}), candidate, None, list(reads)
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
        'source':'harness_business_action','new_matter_accepted':previous is None and matter=='new', 'business_authorization':False}, error=error)
    if planned:
        # Only source-checked business slots survive interruption. Draft,
        # request/fingerprint approval and current invoice values never do.
        agent.ticket_preview_candidate = candidate
        agent.trace('business.invoice_preview_candidate', {'candidate':planned})
        return result, None, planned, reads
    return stopped(status,error or '当前办理未能形成预览，请补充核对要求。',reads)
