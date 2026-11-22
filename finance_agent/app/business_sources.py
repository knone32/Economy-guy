"""Trace business data origins, not natural-language clause relationships.

Field/relationship selection is model semantics, never write authorization.
Identity, explicit object scope, permissions, fresh facts and human approval
remain runtime responsibilities. No prose/quote scanner creates an action.
"""
from copy import deepcopy
from contextlib import closing
from hashlib import sha256

from .business_object_sources import amendment_sources, unreadable_company_mentions
from .permissions import check_permission
from .stage2_schema import open_existing
from .pending_transition import PendingRequestError


def _one(mapping, key):
    values = mapping.get(key, ())
    return values[0] if len(values) == 1 else None


def _origin(message, message_id, kind, value=None):
    result = {'kind':kind, 'message_id':message_id,
              'message_sha256':sha256(message.encode('utf-8')).hexdigest()}
    if value:
        start = message.find(value)
        if start >= 0:
            result['span'] = [start, start + len(value)]
    return result


def checked_change(change, request):
    """A typed current-message candidate, never text extracted from an answer."""
    if (type(change) is not dict or set(change)!={'field','new_value','source'}
            or type(change['field']) is not str or change['field'] not in {'purpose','remark'}
            or type(change['new_value']) is not str):
        raise PendingRequestError('新值须带完整的结构化字段和当前来源。','DENIED')
    source=change['source']
    if (type(source) is not dict or set(source)!={'kind','quote'} or source.get('kind')!='current'
            or type(source.get('quote')) is not str or not source['quote'].strip()
            or source['quote'] not in request or change['new_value'] not in source['quote']):
        raise PendingRequestError('新值候选没有一致的当前原话来源。','DENIED')
    return {'field':change['field'],'new_value':change['new_value']}


def checked_revision(origin, *, actor, book, current_id, current_request):
    from .intent_contract import BoundIntent
    if origin is None:return {}
    if (not isinstance(origin,BoundIntent) or origin.action!='amend'
            or (origin.actor,origin.workbook,origin.turn_id,origin.request)!=(actor,str(book),current_id,current_request)
            or origin.sources.get('source')!='independent_business_entry' or type(origin.target) is not dict):
        raise PendingRequestError('修订关系缺少本轮独立业务来源。','DENIED')
    choices={'field':{'purpose','remark'},'value_relation':{'keep','replace','clear','withdraw','unclear'},
             'matter_relation':{'continue','new','unclear'},'reference_relation':{'displayed','none','unclear'}}
    for key,allowed in choices.items():
        value=origin.target.get(key)
        if value is not None:
            quote=origin.sources.get({'field':'field_quote','value_relation':'value_quote','matter_relation':'matter_quote','reference_relation':'reference_quote'}[key])
            if type(value) is not str or value not in allowed or type(quote) is not str or not quote.strip() or quote not in current_request:
                raise PendingRequestError('修订关系的原话来源不属于本轮。','DENIED')
    if origin.target.get('pending_change') is not None:
        change=checked_change(origin.target['pending_change'],current_request)
        if origin.target.get('field',change['field']) not in (None,change['field']):
            raise PendingRequestError('独立候选字段与本轮字段关系冲突。','DENIED')
        relation=origin.target.get('value_relation')
        if relation in {'withdraw','unclear'} or relation=='clear' and change['new_value']!='':
            raise PendingRequestError('撤回或未决关系不能同时携带确定新值；撤旧并换新须表达为replace。','AMBIGUOUS')
    return origin.target


def recover_candidate(pending, *, actor, book):
    """Recheck saved runtime business data; never restore approval or a draft.

    The caller supplies SessionStore-owned metadata, not transcript/model text.
    Every continuation still goes through bind_request and fresh invoice reads.
    """
    if (type(pending) is not dict or pending.get('business_action') != 'single_invoice'
            or pending.get('model_managed') is not True
            or (pending.get('actor'), pending.get('workbook')) != (actor, str(book))):
        raise ValueError('单票候选的账号或账簿不匹配，请重新发起。')
    allowed = {'request_id','actor','workbook','request','source_request','scope','change',
               'model_managed','business_action','provenance','missing_fields','superseded',
               'on_hold','blocked_reason','reference_collection'}
    if (set(pending) - allowed or any(type(pending.get(key)) is not str or not pending[key]
            for key in ('request_id','request','source_request'))
            or pending['request'] != pending['source_request']
            or type(pending.get('provenance')) is not dict
            or type(pending.get('missing_fields')) not in (list,tuple)
            or not all(type(key) is str for key in pending['missing_fields'])):
        raise ValueError('未提交的单票候选来源不完整，请重新发起。')
    for name, keys in (('scope', {'company_id','invoice_no','year','month','periods'}),
                       ('change', {'field','new_value'})):
        values = pending.get(name)
        if type(values) is not dict or set(values) - keys:
            raise ValueError('单票候选范围无效，请重新发起。')
        for key, items in values.items():
            if type(items) not in (list,tuple) or len(items) > 1:
                raise ValueError('单票候选不唯一，请重新明确。')
            if key == 'periods':
                if any(type(pair) not in (list,tuple) or len(pair) != 2
                       or any(type(value) is not int for value in pair) for pair in items):
                    raise ValueError('单票候选账期无效。')
            elif any(type(value) is not (int if key in {'year','month'} else str) for value in items):
                raise ValueError('单票候选参数无效。')
    field = _one(pending['change'],'field')
    if field is not None and field not in {'purpose','remark'}:
        raise ValueError('单票候选字段无效。')
    with closing(open_existing(book,readonly=True)) as db:
        if not db.execute('SELECT 1 FROM users WHERE user_id=?',(actor,)).fetchone():
            raise PermissionError('当前账号不存在，未恢复单票候选。')
        for company in pending['scope'].get('company_id',()):
            if not all(check_permission(db,actor,company,operation).allowed for operation in ('read','modify')):
                raise PermissionError('当前账号缺少企业读改权限，未恢复单票候选。')
    state = deepcopy(pending)
    if state.get('reference_collection'):
        from .references import validate_collection_origin
        validate_collection_origin(book,actor,state['reference_collection'])
    state['missing_fields'] = tuple(state['missing_fields'])
    return state


def suspend(previous, request, current_id, *, actor, book, reason):
    """Keep the old record for clarification; never execute it by default."""
    if not previous or (previous.get('actor'),previous.get('workbook')) != (actor,str(book)):
        return previous
    state = deepcopy(previous)
    state['on_hold'] = (deepcopy(previous['on_hold']) if not previous.get('change') and previous.get('on_hold') else
        {'change':deepcopy(previous.get('change',{})), 'request_id':previous.get('request_id'),
         'provenance':deepcopy(previous.get('provenance',{}))})
    state['change'] = {}
    state.setdefault('provenance',{}).pop('field',None)
    state['provenance'].pop('new_value',None)
    state['blocked_reason'] = reason
    state['missing_fields'] = ('field','new_value')
    state['request_id'] = current_id
    state['source_request'] = state.get('source_request',state['request']) + '\n' + request
    state['request'] = state['source_request']
    return state


def bind_request(args, previous, *, actor, book, current_id, current_request, target_origin=None, revision_origin=None):
    from .intent_contract import BoundIntent
    reference_scope = {}
    if target_origin is not None:
        if (not isinstance(target_origin, BoundIntent) or target_origin.action != 'read'
                or (target_origin.actor, target_origin.workbook, target_origin.turn_id, target_origin.request)
                   != (actor, str(book), current_id, current_request)
                or target_origin.sources.get('source') != 'runtime_display_reference'):
            raise PendingRequestError('展示对象来源不属于本轮可信会话。', 'DENIED')
        reference_scope = {key: [target_origin.target[key]]
                           for key in ('company_id', 'invoice_no', 'year', 'month') if key in target_origin.target}
        if 'year' in target_origin.target and 'month' in target_origin.target:
            reference_scope['periods'] = [(target_origin.target['year'], target_origin.target['month'])]
    if previous and (previous.get('actor'),previous.get('workbook')) != (actor,str(book)):
        raise PendingRequestError('当前办理不属于这个账号或账簿，请重新发起。','DENIED')
    # A read clarification or arbitrary model pending is not a change source.
    if previous and previous.get('business_action') != 'single_invoice':
        previous = None
    revision=checked_revision(revision_origin,actor=actor,book=book,current_id=current_id,current_request=current_request)
    value_relation=revision.get('value_relation')
    prior_scope = deepcopy((previous or {}).get('scope',{}))
    old_change = deepcopy((previous or {}).get('change',{}))
    relation = args.get('relation','update')
    field = revision.get('field') or (_one(old_change,'field') if previous else args.get('field'))
    old_value = _one(old_change,'new_value')
    replacement = bool(previous and (value_relation in {'replace','clear','withdraw'}
        or revision.get('field') is not None and revision['field'] != _one(old_change,'field')))
    source = ((previous or {}).get('source_request') or (previous or {}).get('request') or '')
    source = '\n'.join(x for x in (source,current_request) if x)
    state = {'request_id':current_id,'actor':actor,'workbook':str(book),'request':source,
        'source_request':source,'scope':deepcopy(prior_scope),'change':{},'model_managed':True,
        'business_action':'single_invoice','provenance':deepcopy((previous or {}).get('provenance',{}))}
    state['provenance'].pop('new_value',None)
    if field:
        state['change']['field'] = [field]
        state['provenance']['field'] = (_origin(current_request,current_id,'independent_business_field_intent')
            if revision.get('field') is not None else _origin(current_request,current_id,'business_field_intent')
            if 'field' in args else state['provenance'].get('field',{'kind':'verified_pending'}))
    if replacement:
        state['superseded'] = {'change':old_change,'request_id':previous.get('request_id'),
                               'provenance':deepcopy(previous.get('provenance',{}))}
    elif previous and previous.get('superseded'):
        state['superseded'] = deepcopy(previous['superseded'])

    # Identify a contradicted invoice independently of the model patch, so an
    # early rejection cannot reactivate the old target in a later turn.
    reference = args.get('value_ref','auto')
    literal = args.get('new_value') if reference == 'auto' else None
    object_origins = {}
    current, value_scope, ambiguous_literal = amendment_sources(current_request, literal,
        actor=actor, book=book, invoice_candidates=[args.get('invoice_no'), *prior_scope.get('invoice_no', ())],
        metadata=object_origins)
    if reference_scope:
        source_text = current_request
        if literal and source_text.count(literal) == 1:
            start = source_text.index(literal)
            source_text = source_text[:start] + ' ' * len(literal) + source_text[start + len(literal):]
        if (unreadable_company_mentions(source_text, actor=actor, book=book)
                or any(key in reference_scope and current.get(key) and list(current[key]) != reference_scope[key]
                       for key in ('company_id', 'invoice_no', 'year', 'month', 'periods'))):
            reference_scope = {}
    old_target = prior_scope.get('invoice_no')
    mentioned_invoices = current.get('invoice_no', ())
    # A unique literal may refer to another invoice or frame as data. When
    # it could also be a newly supplied target, omitting the target isn't an
    # affirmative choice to continue the old one.
    needs_target_choice = bool(old_target and not mentioned_invoices and
        ('invoice_no' not in args or args['invoice_no'] not in old_target) and
        any(value_scope.get(k) and value_scope[k] != prior_scope.get(k)
            for k in ('invoice_no','company_id','year','month')))
    old_target_conflicts = bool(old_target and (ambiguous_literal or needs_target_choice or
        (mentioned_invoices and list(mentioned_invoices) != old_target)
        or any(current.get(k) and current[k] != prior_scope.get(k)
               for k in ('company_id','year','month'))))

    def retire_invoice():
        state['scope'].pop('invoice_no',None)
        state['provenance'].pop('invoice_no',None)

    scope_verified = False

    def fail(message, reason, status='SCOPE_MISMATCH', *, repairable_reference=False):
        # Only an independently checked user revision can retire old content.
        # An invalid execution proposal cannot acquire cancellation authority.
        if previous and not replacement:
            error=PendingRequestError(message+' 原有效待补保持不变，尚未保存。',status)
            error.pending_state,error.state_updated=deepcopy(previous),False
            error.reason,error.repairable_reference=reason,repairable_reference
            raise error
        if previous or relation == 'clarify':
            if not scope_verified:
                state['scope'] = deepcopy(prior_scope)
                for key in ('company_id','invoice_no','year','month'):
                    origin = (previous or {}).get('provenance',{}).get(key)
                    if origin:
                        state['provenance'][key] = deepcopy(origin)
                    else:
                        state['provenance'].pop(key,None)
                if old_target_conflicts:
                    retire_invoice()
            verified=({'field':[field]} if field else {})
            if value_relation=='clear':
                verified['new_value']=['']
                state['provenance']['new_value']=_origin(current_request,current_id,'independent_clear_business_intent')
            elif replacement and type(args.get('new_value')) is str and args['new_value'] and args['new_value'] in current_request and not ambiguous_literal and value_relation!='withdraw':
                verified['new_value']=[args['new_value']]
                state['provenance']['new_value']=_origin(current_request,current_id,'current_literal',args['new_value'])
            state['change'] = verified
            state['blocked_reason'] = reason
            state['superseded'] = {'change':old_change,
                                   'request_id':(previous or {}).get('request_id'),
                                   'provenance':deepcopy((previous or {}).get('provenance',{}))}
            state['missing_fields'] = tuple(
                [k for k in ('company_id','invoice_no','year','month') if len(state['scope'].get(k,())) != 1]
                + [k for k in ('field','new_value') if k not in state['change']])
            error = PendingRequestError(message + ' 上一次修改不会继续执行，请明确本次要求。',status)
            error.pending_state, error.state_updated = state, True
            error.reason = reason
            error.repairable_reference = repairable_reference
            raise error
        raise PendingRequestError(message,status)

    if ambiguous_literal:
        fail('同样的未引用内容也出现在办理范围中。请分别说明发票目标和填写文字。',
             'value_scope_overlap','AMBIGUOUS')
    scope_patch = {}
    scope_origins = {}
    conflicts=[arg for key,arg in (('company_id','company_id'),('year','target_year'),('month','target_month'),('invoice_no','invoice_no'))
               if arg in args and args[arg] not in (current.get(key) or prior_scope.get(key,()) or reference_scope.get(key,()))]
    if conflicts:
        # The original proposal remains rejected. Independently bind only its
        # other source-checked slots into the same unapproved pending owner.
        # Explicit user date restrictions are inferred by that binding, never
        # discarded merely because a generated date conflicted with them.
        corrected={key:value for key,value in args.items() if key not in conflicts}
        try:
            partial=bind_request(corrected,previous,actor=actor,book=book,current_id=current_id,
                current_request=current_request,target_origin=target_origin,revision_origin=revision_origin)
        except PendingRequestError as inner:
            partial=getattr(inner,'pending_state',None)
            if partial is None:raise
        partial['blocked_reason']='source_conflict'
        error=PendingRequestError('部分候选参数没有本轮来源，请补正这些槽位；其余已核实内容保留，未生成预览。','SCOPE_MISMATCH')
        error.pending_state,error.state_updated=partial,True
        error.reason='object_source'
        error.conflicting_slots=conflicts
        raise error
    if previous:
        if args.get('field',field)!=field:
            fail('候选字段与已核实的本轮字段要求不一致。','field_revision','AMBIGUOUS')
        if relation=='clarify' and value_relation!='unclear':
            fail('候选澄清关系尚未由当前原话独立核实。','unverified_revision','AMBIGUOUS')
        # A bare, sourced choice from the owner's pending collection supplies
        # identity only. It cannot revise a value, and needs no new value
        # relation merely to retain the existing verified pending content.
        identity_supplement = (not prior_scope.get('invoice_no')
            and previous.get('reference_collection') and not previous.get('on_hold')
            and not previous.get('blocked_reason') and target_origin is not None
            and revision.get('matter_relation')=='continue'
            and revision.get('field') is None and revision.get('pending_change') is None
            and set(args)=={'invoice_no'} and current_request.strip()==args['invoice_no']
            and target_origin.target.get('invoice_no')==args['invoice_no'])
        if old_value is not None and value_relation is None and not identity_supplement:
            fail('请核实本轮是保留、替换还是撤回旧内容。','unverified_revision','AMBIGUOUS',repairable_reference=True)
        if relation=='replace' and not replacement:
            fail('替换提案没有独立的本轮替换依据。','unverified_revision','AMBIGUOUS',repairable_reference=True)
        if value_relation=='keep' and ('new_value' in args and args['new_value']!=old_value or args.get('value_ref')=='clear'):
            fail('执行提案改变了本轮明确保留的内容。','value_revision','AMBIGUOUS')
    for key, arg in (('company_id','company_id'),('year','target_year'),('month','target_month'),('invoice_no','invoice_no')):
        if arg in args:
            available = current.get(key) or prior_scope.get(key,()) or reference_scope.get(key, ())
            if args[arg] not in available:
                fail('请明确本次要办理的企业、账期或发票，参数缺少可核对的来源。','object_source')
            if key in {'company_id', 'invoice_no'} and current.get(key) and current[key] != [args[arg]]:
                fail('尚未唯一选定发票，请明确目标，不会从提及或读取的票据中代选。','object_ambiguity','AMBIGUOUS')
            scope_patch[key] = [args[arg]]
            scope_origins[key] = (_origin(current_request,current_id,'current_identifier',str(args[arg]))
                if args[arg] in current.get(key,()) else
                {'kind':'verified_pending_scope','request_id':previous['request_id']} if previous and args[arg] in prior_scope.get(key,()) else
                {'kind':'trusted_reference','reference':deepcopy(target_origin.sources['reference'])})
            if key == 'company_id' and args[arg] in current.get(key, ()):
                origins = [item for item in object_origins['company_mentions'] if item['company_id'] == args[arg]]
                scope_origins[key].update(kind='current_authorized_catalog', literals=origins)
        elif key != 'invoice_no' and len(current.get(key,())) == 1:
            scope_patch[key] = list(current[key])
            scope_origins[key] = _origin(current_request,current_id,'current_scope')
        elif current.get(key) and len(current[key]) != 1:
            fail('当前提及多个企业、账期或发票，请明确本次办理目标。','object_ambiguity','AMBIGUOUS')
        elif not prior_scope.get(key) and reference_scope.get(key):
            scope_patch[key] = list(reference_scope[key])
            scope_origins[key] = {'kind': 'trusted_reference',
                                       'reference': deepcopy(target_origin.sources['reference'])}
    if 'invoice_no' not in scope_patch and old_target_conflicts:
        # A different mention is not authorization to select the new key;
        # neither is the omission permission to resurrect the old key.
        retire_invoice()
    if any(key in scope_patch and scope_patch[key] != prior_scope.get(key)
           for key in ('company_id','year','month')):
        retire_invoice()
        if ('invoice_no' in args and current.get('invoice_no') != [args['invoice_no']]
                and reference_scope.get('invoice_no') != [args['invoice_no']]):
            fail('企业或账期改变后，请重新明确目标发票。','object_frame')
    state['scope'].update(scope_patch)
    state['provenance'].update(scope_origins)
    if _one(state['scope'],'year') and _one(state['scope'],'month'):
        pair = (_one(state['scope'],'year'),_one(state['scope'],'month'))
        allowed = {tuple(p) for p in current.get('periods',())}
        if not current.get('periods'):
            allowed.update(tuple(p) for p in prior_scope.get('periods',()))
            if not prior_scope.get('periods'):
                allowed.update(reference_scope.get('periods', ()))
                # A cross-month display can prove one shared year without
                # prescribing a month. Combine only that unique source slot
                # with the user's unique current month (and conversely).
                if len(current.get('month',()))==1 and not current.get('year') and len(reference_scope.get('year',()))==1:
                    allowed.add((reference_scope['year'][0],current['month'][0]))
                if len(current.get('year',()))==1 and not current.get('month') and len(reference_scope.get('month',()))==1:
                    allowed.add((current['year'][0],reference_scope['month'][0]))
            if len(prior_scope.get('periods',())) == 1:
                prior_year, prior_month = prior_scope['periods'][0]
                if len(current.get('year',())) == 1 and not current.get('month'):
                    allowed.add((current['year'][0],prior_month))
                if len(current.get('month',())) == 1 and not current.get('year'):
                    allowed.add((prior_year,current['month'][0]))
        if pair not in allowed:
            fail('企业账期没有唯一对应来源，请明确完整年月。','period_pair','AMBIGUOUS')
        state['scope']['periods'] = [pair]
    with closing(open_existing(book,readonly=True)) as db:
        if not db.execute('SELECT 1 FROM users WHERE user_id=?',(actor,)).fetchone():
            raise PendingRequestError('当前账号无法办理，请重新登录。','DENIED')
        for company in state['scope'].get('company_id',()):
            if not all(check_permission(db,actor,company,operation).allowed for operation in ('read','modify')):
                fail('当前账号没有该企业发票的办理权限。','permission','DENIED')
    scope_verified = True
    if value_relation=='withdraw':
        state['change']={'field':[field]} if field else {}
        state['missing_fields']=('new_value',)
        return state
    if value_relation=='unclear':
        state['change']=deepcopy(old_change)
        state['on_hold'] = {'change':old_change,'request_id':(previous or {}).get('request_id')}
        state['missing_fields'] = ('change_choice',)
        state['blocked_reason'] = 'ambiguous_business_choice'
        return state
    if reference=='clear' and value_relation!='clear':
        fail('清空提案尚未由本轮独立业务要求核实。','unverified_clear','AMBIGUOUS')
    if value_relation=='clear':
        if args.get('new_value','') != '' or not current_request.strip():
            fail('清空与填写内容不能同时指定，请明确本次内容。','value_ambiguity','AMBIGUOUS')
        value = ''
        origin = _origin(current_request,current_id,'independent_clear_business_intent')
    elif reference == 'previous':
        if value_relation!='keep' or old_value is None or ('new_value' in args and args['new_value'] != old_value):
            fail('没有唯一有效的上一项填写内容可引用，请明确新内容。','value_reference','AMBIGUOUS')
        value = old_value
        origin = {'kind':'explicit_previous_value','request_id':previous['request_id'],
                  'origin':deepcopy((previous or {}).get('provenance',{}).get('new_value',{}))}
    elif 'new_value' in args:
        value = args['new_value']
        if value and value in current_request:
            origin = _origin(current_request,current_id,'current_literal',value)
        else:
            # A model may have echoed a server-owned value while making a
            # valid patch. Never accept the echo itself as evidence. Only this
            # exact, same-field case can request a fresh semantic decision.
            repairable = (reference == 'auto' and not replacement and value == old_value and field is not None)
            fail('本次新内容缺少可核对的原文或有效待补来源，请明确填写内容。',
                 'new_value_source','AMBIGUOUS',repairable_reference=repairable)
    elif not replacement and field == _one(old_change,'field') and old_value is not None:
        value = old_value
        origin = {'kind':'verified_pending','request_id':previous['request_id'],
                  'origin':deepcopy((previous or {}).get('provenance',{}).get('new_value',{}))}
    else:
        value, origin = None, None
    if value is not None:
        state['change']['new_value'] = [value]
        state['provenance']['new_value'] = origin
    missing = [key for key in ('company_id','invoice_no','year','month') if len(state['scope'].get(key,())) != 1]
    missing += [key for key in ('field','new_value') if len(state['change'].get(key,())) != 1]
    state['missing_fields'] = tuple(missing or ['invoice_selection'])
    return state
