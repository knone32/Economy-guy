"""Trace business data origins, not natural-language clause relationships.

Field/relationship selection is model semantics, never write authorization.
Identity, explicit object scope, permissions, fresh facts and human approval
remain runtime responsibilities. No prose/quote scanner creates an action.
"""
from copy import deepcopy
from contextlib import closing
from hashlib import sha256

from .responses import request_scope
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

    scope_verified = False

    def fail(message, reason, status='SCOPE_MISMATCH'):
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
            state['change'] = {'field':[field]} if field else {}
            state['blocked_reason'] = reason
            state['superseded'] = {'change':old_change,
                                   'request_id':(previous or {}).get('request_id'),
                                   'provenance':deepcopy((previous or {}).get('provenance',{}))}
            state['missing_fields'] = tuple(k for k in ('field','new_value') if k not in state['change'])
            error = PendingRequestError(message + ' 上一次修改不会继续执行，请明确本次要求。',status)
            error.pending_state, error.state_updated = state, True
            error.reason = reason
            raise error
        raise PendingRequestError(message,status)

    current = request_scope(current_request,include_update_aliases=True)
    scope_patch = {}
    for key, arg in (('company_id','company_id'),('year','target_year'),('month','target_month'),('invoice_no','invoice_no')):
        if arg in args:
            available = current.get(key) or prior_scope.get(key,())
            if args[arg] not in available:
                fail('请明确本次要办理的企业、账期或发票，参数缺少可核对的来源。','object_source')
            if key == 'invoice_no' and current.get(key) and current[key] != [args[arg]]:
                fail('尚未唯一选定发票，请明确目标，不会从提及或读取的票据中代选。','object_ambiguity','AMBIGUOUS')
            scope_patch[key] = [args[arg]]
            state['provenance'][key] = (_origin(current_request,current_id,'current_identifier',str(args[arg]))
                if args[arg] in current.get(key,()) else
                {'kind':'verified_pending_scope','request_id':(previous or {}).get('request_id')})
        elif key != 'invoice_no' and len(current.get(key,())) == 1:
            scope_patch[key] = list(current[key])
            state['provenance'][key] = _origin(current_request,current_id,'current_scope')
        elif current.get(key) and len(current[key]) != 1:
            fail('当前提及多个企业、账期或发票，请明确本次办理目标。','object_ambiguity','AMBIGUOUS')
    if any(key in scope_patch and scope_patch[key] != prior_scope.get(key)
           for key in ('company_id','year','month')):
        state['scope'].pop('invoice_no',None)
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
    reference = args.get('value_ref','auto')
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
            fail('本次新内容缺少可核对的原文或有效待补来源，请明确填写内容。','new_value_source','AMBIGUOUS')
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
