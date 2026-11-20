"""Trace business data origins, not natural-language clause relationships.

Field/relationship selection is model semantics, never write authorization.
Identity, explicit object scope, permissions, fresh facts and human approval
remain runtime responsibilities. No prose/quote scanner creates an action.
"""
from copy import deepcopy
from contextlib import closing
from hashlib import sha256

from .business_object_sources import amendment_sources
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
               'on_hold','blocked_reason'}
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
    state['missing_fields'] = tuple(state['missing_fields'])
    return state


def suspend(previous, request, current_id, *, actor, book, reason):
    """Keep the old record for clarification; never execute it by default."""
    if not previous or (previous.get('actor'),previous.get('workbook')) != (actor,str(book)):
        return previous
    state = deepcopy(previous)
    state['on_hold'] = {'change':deepcopy(previous.get('change',{})),
                        'request_id':previous.get('request_id'),
                        'provenance':deepcopy(previous.get('provenance',{}))}
    state['change'] = {}
    state.setdefault('provenance',{}).pop('field',None)
    state['provenance'].pop('new_value',None)
    state['blocked_reason'] = reason
    state['missing_fields'] = ('field','new_value')
    state['request_id'] = current_id
    state['source_request'] = state.get('source_request',state['request']) + '\n' + request
    state['request'] = state['source_request']
    return state


def bind_request(args, previous, *, actor, book, current_id, current_request):
    if previous and (previous.get('actor'),previous.get('workbook')) != (actor,str(book)):
        raise PendingRequestError('当前办理不属于这个账号或账簿，请重新发起。','DENIED')
    # A read clarification or arbitrary model pending is not a change source.
    if previous and previous.get('business_action') != 'single_invoice':
        previous = None
    prior_scope = deepcopy((previous or {}).get('scope',{}))
    old_change = deepcopy((previous or {}).get('change',{}))
    relation = args.get('relation','update')
    field = args.get('field', None if relation == 'replace' else _one(old_change,'field'))
    old_value = _one(old_change,'new_value')
    replacement = bool(previous and (relation == 'replace'
        or ('field' in args and args['field'] != _one(old_change,'field'))
        or ('new_value' in args and args['new_value'] != old_value)
        or args.get('value_ref') == 'clear'))
    source = ((previous or {}).get('source_request') or (previous or {}).get('request') or '')
    source = '\n'.join(x for x in (source,current_request) if x)
    state = {'request_id':current_id,'actor':actor,'workbook':str(book),'request':source,
        'source_request':source,'scope':deepcopy(prior_scope),'change':{},'model_managed':True,
        'business_action':'single_invoice','provenance':deepcopy((previous or {}).get('provenance',{}))}
    state['provenance'].pop('new_value',None)
    if field:
        state['change']['field'] = [field]
        state['provenance']['field'] = (_origin(current_request,current_id,'business_field_intent')
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
        # A rejected replacement cannot resurrect the superseded field/value.
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
            state['change'] = {'field':[field]} if field else {}
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
    for key, arg in (('company_id','company_id'),('year','target_year'),('month','target_month'),('invoice_no','invoice_no')):
        if arg in args:
            available = current.get(key) or prior_scope.get(key,())
            if args[arg] not in available:
                fail('请明确本次要办理的企业、账期或发票，参数缺少可核对的来源。','object_source')
            if key in {'company_id', 'invoice_no'} and current.get(key) and current[key] != [args[arg]]:
                fail('尚未唯一选定发票，请明确目标，不会从提及或读取的票据中代选。','object_ambiguity','AMBIGUOUS')
            scope_patch[key] = [args[arg]]
            state['provenance'][key] = (_origin(current_request,current_id,'current_identifier',str(args[arg]))
                if args[arg] in current.get(key,()) else
                {'kind':'verified_pending_scope','request_id':(previous or {}).get('request_id')})
            if key == 'company_id' and args[arg] in current.get(key, ()):
                origins = [item for item in object_origins['company_mentions'] if item['company_id'] == args[arg]]
                state['provenance'][key].update(kind='current_authorized_catalog', literals=origins)
        elif key != 'invoice_no' and len(current.get(key,())) == 1:
            scope_patch[key] = list(current[key])
            state['provenance'][key] = _origin(current_request,current_id,'current_scope')
        elif current.get(key) and len(current[key]) != 1:
            fail('当前提及多个企业、账期或发票，请明确本次办理目标。','object_ambiguity','AMBIGUOUS')
    if 'invoice_no' not in scope_patch and old_target_conflicts:
        # A different mention is not authorization to select the new key;
        # neither is the omission permission to resurrect the old key.
        retire_invoice()
    if any(key in scope_patch and scope_patch[key] != prior_scope.get(key)
           for key in ('company_id','year','month')):
        retire_invoice()
        if 'invoice_no' in args and current.get('invoice_no') != [args['invoice_no']]:
            fail('企业或账期改变后，请重新明确目标发票。','object_frame')
    state['scope'].update(scope_patch)
    if _one(state['scope'],'year') and _one(state['scope'],'month'):
        pair = (_one(state['scope'],'year'),_one(state['scope'],'month'))
        allowed = {tuple(p) for p in current.get('periods',())}
        if not current.get('periods'):
            allowed.update(tuple(p) for p in prior_scope.get('periods',()))
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
    if relation == 'clarify':
        state['on_hold'] = {'change':old_change,'request_id':(previous or {}).get('request_id')}
        state['missing_fields'] = ('change_choice',)
        state['blocked_reason'] = 'ambiguous_business_choice'
        return state
    if reference == 'clear':
        if args.get('new_value','') != '' or not current_request.strip():
            fail('清空与填写内容不能同时指定，请明确本次内容。','value_ambiguity','AMBIGUOUS')
        value = ''
        origin = _origin(current_request,current_id,'clear_business_intent')
    elif reference == 'previous':
        if old_value is None or ('new_value' in args and args['new_value'] != old_value):
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
            repairable = (reference == 'auto' and not replacement and value == old_value
                          and field is not None and relation == 'update')
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
