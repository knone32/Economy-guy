"""Bound a model's small read/amend candidate to this request and real sources.

This is neither authorization nor a second semantic controller. The model picks
meaning; runtime checks exact source spans, existing slots and fresh selections.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from contextlib import closing

from .permissions import check_permission
from .provenance import ScopeProof, SOURCES, READ_SOURCES, READ_ONLY_TOOLS
from .responses import request_scope, explicit_scope, _QUOTED_DATA
from .stage2_schema import open_existing
from .controlled_read_scope import catalog as read_catalog
from .business_object_sources import amendment_sources, registered_company_mentions

SCOPE_KEYS = ('company_id','invoice_no','year','month')
WRITE_KEYS = (*SCOPE_KEYS, 'field','new_value')
FIELD_LABELS = {'purpose': ('purpose','用途'), 'remark': ('remark','备注')}
READ_TOOLS = READ_ONLY_TOOLS


def _field_origins(plain):
    """Conservative controlled-slot conflict gate, not an action classifier."""
    return {field for field, labels in FIELD_LABELS.items() if any(label in plain for label in labels)}


class IntentContractError(ValueError):
    def __init__(self, message, *, status='AMBIGUOUS', slot=None):
        super().__init__(message)
        self.status, self.slot = status, slot


@dataclass(frozen=True)
class BoundIntent:
    action: str
    actor: str
    workbook: str
    turn_id: str
    request: str
    target: dict
    sources: dict
    pending_request_id: str | None = None

    def metadata(self):
        return {'action':self.action,'target':deepcopy(self.target),'sources':deepcopy(self.sources),
                'pending_request_id':self.pending_request_id,'turn_id':self.turn_id,
                'request_sha256':hashlib.sha256(self.request.encode()).hexdigest(),
                'authorization':False}


def sidecar(content):
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        value = json.loads(content)
    except (ValueError, TypeError, RecursionError):
        return None
    if not isinstance(value, dict) or 'intent' not in value:
        return None
    if not isinstance(value['intent'], dict):
        raise IntentContractError('意图候选结构无效。', status='INVALID_ARGUMENTS')
    return value['intent']


def _pending_value(pending, slot):
    values = (pending or {}).get('change' if slot in ('field','new_value') else 'scope', {}).get(slot, ())
    return values


def _valid_target(target, write):
    required = set(WRITE_KEYS if write else ('company_id','year','month'))
    allowed = required if write else required | {'invoice_no'}
    if type(target) is not dict or not required <= target.keys() or set(target) - allowed:
        raise IntentContractError('意图候选缺少唯一对象或内容。', status='INVALID_ARGUMENTS')
    if (type(target['company_id']) is not str or not target['company_id']
            or type(target['year']) is not int or type(target['month']) is not int):
        raise IntentContractError('意图候选的企业或日期无效。', status='INVALID_ARGUMENTS')
    try:
        date(target['year'], target['month'], 1)
    except (ValueError, OverflowError):
        raise IntentContractError('意图候选的日期无效。', status='INVALID_ARGUMENTS') from None
    if 'invoice_no' in target and (type(target['invoice_no']) is not str or not target['invoice_no']):
        raise IntentContractError('意图候选没有唯一票号。', status='INVALID_ARGUMENTS')
    if write and (type(target['field']) is not str or target['field'] not in FIELD_LABELS or type(target['new_value']) is not str):
        raise IntentContractError('意图候选字段或新值无效。', status='INVALID_ARGUMENTS')


def _period_quote_has_external_carrier(quote, value, slot, request, masked, spans):
    """An identifier's internal digits cannot become a business period.

    A broad quote wrapping that identifier must retain the same recognized date
    outside it. Existing nonnumeric language/anchor contracts are not reparsed
    into a new vocabulary; only known literal date carriers are removed here.
    """
    parsed = explicit_scope(quote, include_update_aliases=True)
    start = request.find(quote)
    while start >= 0:
        end = start + len(quote)
        if not any(left <= start and end <= right for left, right in spans):
            outside = explicit_scope(masked[start:end], include_update_aliases=True)
            if value not in parsed.get(slot, ()) or value in outside.get(slot, ()):
                return True
        start = request.find(quote, start + 1)
    return False


def validate(raw, *, actor, book, request, turn_id, pending=None, anchor=None):
    if type(raw) is not dict or set(raw) - {'action','pending_request_id','target','sources'}:
        raise IntentContractError('意图候选不得声明身份、授权、确认或提交。', status='INVALID_ARGUMENTS')
    action = raw.get('action')
    if type(action) is not str or action not in {'read','amend','cancel'}:
        raise IntentContractError('不支持的意图候选动作。', status='INVALID_ARGUMENTS')
    pending_id = raw.get('pending_request_id')
    if action != 'read':
        if (not pending or pending_id != pending.get('request_id')
                or pending.get('actor') != actor or pending.get('workbook') != str(book)):
            raise IntentContractError('待补引用已失效或不属于当前会话。')
    elif pending_id is not None:
        raise IntentContractError('只读候选不能继承修改待补许可。', status='INVALID_ARGUMENTS')
    if action == 'cancel':
        if set(raw) != {'action','pending_request_id'}:
            raise IntentContractError('取消候选不能同时更改对象或内容。', status='INVALID_ARGUMENTS')
        return BoundIntent(action, actor, str(book), turn_id, request, {}, {}, pending_id)
    target, sources = raw.get('target'), raw.get('sources')
    _valid_target(target, action == 'amend')
    if type(sources) is not dict or set(sources) != set(target):
        raise IntentContractError('意图候选每个参数必须有对应来源。', status='INVALID_ARGUMENTS')
    named = request_scope(request, include_update_aliases=True)
    read_companies = None
    object_spans, masked_request = (), request
    if action == 'read':
        read_companies = read_catalog(book, actor)['companies']
        if target['company_id'] not in {row['company_id'] for row in read_companies}:
            raise IntentContractError('当前账号没有该企业的读取权限。', status='DENIED')
        metadata = {}
        invoices = (target['invoice_no'],) if 'invoice_no' in target else ()
        named, _, _ = amendment_sources(request, None, actor=actor, book=book,
                                        invoice_candidates=invoices, metadata=metadata)
        # Quotes can legally identify read objects. Their content stays absent
        # from automatic target scope, but still masks identifier-internal dates.
        scan = _QUOTED_DATA.sub(lambda match: ' ' + match[0][1:-1] + ' ', request)
        if scan != request:
            metadata = {}
            amendment_sources(scan, None, actor=actor, book=book,
                              invoice_candidates=invoices, metadata=metadata)
        object_spans = [item['span'] for item in metadata.get('company_mentions', ())]
        object_spans.extend(span for occurrences in metadata.get('invoice_mentions', {}).values() for span in occurrences)
        masked = list(request)
        for start, end in object_spans:
            masked[start:end] = ' ' * (end - start)
        masked_request = ''.join(masked)
    plain = _QUOTED_DATA.sub(' ', request)
    current_fields = _field_origins(plain)
    for slot, value in target.items():
        source = sources[slot]
        if (type(source) is not dict or type(source.get('kind')) is not str
                or source.get('kind') not in {'current','pending','anchor','period_offset'}):
            raise IntentContractError('意图候选来源无效。', slot=slot)
        kind = source['kind']
        if (action == 'read' and slot in {'year', 'month'} and kind in {'current', 'period_offset'}
                and type(source.get('text')) is str and source['text']
                and not _period_quote_has_external_carrier(source['text'], value, slot,
                                                           request, masked_request, object_spans)):
            raise IntentContractError('账期原话只落在业务对象标识符内，请提供独立账期来源。', slot=slot)
        if kind == 'current':
            if set(source) != {'kind','text'} or type(source['text']) is not str or not source['text'] or source['text'] not in request:
                raise IntentContractError('意图候选没有当前原文来源。', slot=slot)
            quote = source['text']
            parsed_quote = explicit_scope(quote, include_update_aliases=True)
            if action == 'read' and slot == 'company_id':
                companies = {item['company_id'] for item in registered_company_mentions(quote, read_companies)}
                if len(companies) != 1:
                    raise IntentContractError('企业原话未登记或对应多个可读企业，请明确企业。', slot=slot)
                if value not in companies:
                    raise IntentContractError('企业原话与实际登记对象不一致。', status='SCOPE_MISMATCH', slot=slot)
                parsed_quote = {**parsed_quote, 'company_id': list(companies)}
            elif action == 'read' and slot == 'invoice_no':
                quoted, _, _ = amendment_sources(quote, None, actor=actor, book=book,
                                                  invoice_candidates=(value,))
                parsed_quote = {**parsed_quote, 'invoice_no': quoted.get('invoice_no', ())}
            if slot in SCOPE_KEYS:
                if (named.get(slot) and value not in named[slot]) or (parsed_quote.get(slot) and value not in parsed_quote[slot]):
                    raise IntentContractError('意图候选与当前明确对象或日期冲突。', status='SCOPE_MISMATCH', slot=slot)
                if (action == 'read' and isinstance(anchor, ScopeProof) and anchor.actor == actor
                        and anchor.sources.get(slot) == 'trusted_reference'
                        and value not in anchor.values.get(slot, ())):
                    raise IntentContractError('只读候选与当前可信对象引用冲突。', status='SCOPE_MISMATCH', slot=slot)
                if action == 'amend' and value not in named.get(slot, ()):
                    raise IntentContractError('修改对象必须有本轮明确原文、待补或可信锚点来源。', slot=slot)
                if action == 'read' and slot == 'invoice_no' and value not in parsed_quote.get(slot, ()):
                    raise IntentContractError('关键票号必须由当前明确标识符或可信对象锚点给出。', slot=slot)
            elif slot == 'field':
                if quote not in FIELD_LABELS[value] or quote not in plain:
                    raise IntentContractError('修改字段与当前原文不一致。', slot=slot)
            elif not ((quote == value and value) or (value == '' and quote in ('""','“”','「」','『』','‘’'))):
                raise IntentContractError('修改新值与当前原文不一致。', slot=slot)
        elif kind == 'pending':
            if set(source) != {'kind'} or action != 'amend' or value not in _pending_value(pending, slot):
                raise IntentContractError('候选参数不是已知待补内容。', slot=slot)
            if slot in SCOPE_KEYS and named.get(slot) and value not in named[slot]:
                raise IntentContractError('待补内容与本轮更正冲突。', status='SCOPE_MISMATCH', slot=slot)
            if slot == 'field' and current_fields and current_fields != {value}:
                raise IntentContractError('本轮字段来源不唯一或与旧字段不同，不能借旧字段绑定当前新值。',
                                          status='SCOPE_MISMATCH', slot=slot)
        elif kind == 'anchor':
            if (set(source) != {'kind'} or slot not in SCOPE_KEYS or not isinstance(anchor, ScopeProof)
                    or anchor.actor != actor or anchor.sources.get(slot) not in (READ_SOURCES if action == 'read' else SOURCES)
                    or value not in anchor.values.get(slot, ())):
                raise IntentContractError('候选缺少实际可信对象锚点。', slot=slot)
            if named.get(slot) and value not in named[slot]:
                raise IntentContractError('对象锚点与当前明确范围冲突。', status='SCOPE_MISMATCH', slot=slot)
        else:
            if (action != 'read' or slot not in {'year','month'} or set(source) != {'kind','text','months'}
                    or type(source['text']) is not str or not source['text'] or source['text'] not in request
                    or type(source['months']) is not int or not -24 <= source['months'] <= 24
                    or not isinstance(anchor, ScopeProof) or anchor.actor != actor
                    or anchor.sources.get('periods') not in SOURCES or len(anchor.values.get('periods', ())) != 1):
                raise IntentContractError('相对日期缺少唯一可信锚点或有界偏移。', slot=slot)
            y, m = anchor.values['periods'][0]
            shifted = y * 12 + m - 1 + source['months']
            expected = (shifted // 12, shifted % 12 + 1)
            if target['year'] != expected[0] or target['month'] != expected[1]:
                raise IntentContractError('候选日期与锚点偏移不一致。', status='SCOPE_MISMATCH', slot=slot)
    if action == 'read':
        with closing(open_existing(book, readonly=True)) as db:
            if not check_permission(db, actor, target['company_id'], 'read').allowed:
                raise IntentContractError('当前账号没有该企业的读取权限。', status='DENIED')
    return BoundIntent(action, actor, str(book), turn_id, request, deepcopy(target), deepcopy(sources), pending_id)


def infer_proposal(proposal, selection, *, pending, actor, book, request, turn_id, anchor):
    """Existing canonical tool arguments can supply the same explicit candidate."""
    if (not pending or proposal.get('pending_request_id') != pending.get('request_id')
            or not selection or len(selection[0]) != 1 or proposal.get('mode') != 'item'
            or selection[2] not in {'get_invoice','resolve_recent_invoice','resolve_invoice_reference'}
            or proposal.get('rule_business_date') or proposal.get('rule_cohort')
            or proposal.get('new_value') == ''):
        return None
    if (proposal['new_value'] not in request
            and proposal['new_value'] in _pending_value(pending, 'new_value')):
        # Unchanged-value/batch/rule legacy paths retain their existing contract.
        return None
    company, number = selection[0][0]
    scope = selection[1]
    target = {'company_id':company,'invoice_no':number,'year':scope['year'],'month':scope['month'],
              'field':proposal['field'],'new_value':proposal['new_value']}
    named = request_scope(request, include_update_aliases=True)
    plain = _QUOTED_DATA.sub(' ', request)
    current_fields = _field_origins(plain)
    if current_fields and current_fields != {proposal['field']}:
        # The optional compatibility bridge cannot assign a new current value
        # to an old field when this request names another/ambiguous field.
        # Keep the original validator (or require an explicit source candidate)
        # rather than fabricate a cross-turn field/value bundle.
        return None
    sources = {}
    for slot, value in target.items():
        if slot in SCOPE_KEYS and value in named.get(slot, ()):
            sources[slot] = {'kind':'current','text':request}
        elif slot == 'field' and any(label in plain for label in FIELD_LABELS.get(value, ())):
            sources[slot] = {'kind':'current','text':next(label for label in FIELD_LABELS[value] if label in plain)}
        elif slot == 'new_value' and value and value in request:
            sources[slot] = {'kind':'current','text':value}
        elif value in _pending_value(pending, slot):
            sources[slot] = {'kind':'pending'}
        elif (slot in SCOPE_KEYS and isinstance(anchor, ScopeProof) and anchor.sources.get(slot) in SOURCES
              and value in anchor.values.get(slot, ())):
            sources[slot] = {'kind':'anchor'}
        else:
            raise IntentContractError('提案参数缺少当前原文或可继承来源。', slot=slot)
    return validate({'action':'amend','pending_request_id':pending['request_id'],'target':target,'sources':sources},
        actor=actor,book=book,request=request,turn_id=turn_id,pending=pending,anchor=anchor)


def apply_pending(candidate, previous):
    """Atomic in-memory slot amendment; never a draft, approval or DB change."""
    if candidate.action != 'amend' or previous.get('request_id') != candidate.pending_request_id:
        raise IntentContractError('更正候选与待补引用不一致。')
    target = candidate.target
    revised = deepcopy(previous)
    revised['scope'] = {k:[target[k]] for k in SCOPE_KEYS}
    revised['scope']['periods'] = [(target['year'],target['month'])]
    revised['change'] = {k:[target[k]] for k in ('field','new_value')}
    revised['missing_fields'] = ()
    prior_source = previous.get('source_request', previous['request'])
    previous_candidate = previous.get('intent_candidate') or {}
    same_request = (previous_candidate.get('turn_id') == candidate.turn_id
                    and previous_candidate.get('request_sha256') == candidate.metadata()['request_sha256'])
    revised['source_request'] = prior_source if same_request else prior_source + '\n' + candidate.request
    revised['request'] = revised['source_request']
    revised['intent_candidate'] = candidate.metadata()
    return revised


def proposal_edit(candidate, proposal, selection, *, actor, book, turn_id, request):
    if (not isinstance(candidate, BoundIntent) or candidate.action != 'amend'
            or (candidate.actor,candidate.workbook,candidate.turn_id,candidate.request) != (actor,str(book),turn_id,request)
            or proposal.get('pending_request_id') != candidate.pending_request_id):
        raise IntentContractError('更正候选不属于当前执行轮。')
    t = candidate.target
    write_scope = {'company_id':t['company_id'],'year':t['year'],'month':t['month'],'invoice_nos':[t['invoice_no']]}
    if (not selection or selection[0] != ((t['company_id'],t['invoice_no']),)
            or selection[2] not in {'get_invoice','resolve_recent_invoice','resolve_invoice_reference'}
            or any(selection[1].get(k) != t[k] for k in ('company_id','year','month'))
            or proposal['field'] != t['field'] or proposal['new_value'] != t['new_value']
            or proposal['mode'] != 'item' or proposal['excluded_invoice_ids']
            or proposal.get('rule_business_date') or proposal.get('rule_cohort')
            or ('write_scope' in proposal and proposal['write_scope'] != write_scope)
            or ('target_year' in proposal and proposal['target_year'] != t['year'])
            or ('target_month' in proposal and proposal['target_month'] != t['month'])):
        raise IntentContractError('提案与本轮新读取、更正对象或内容不一致。', status='SCOPE_MISMATCH')
    scope = {k:[t[k]] for k in SCOPE_KEYS}; scope['periods'] = [(t['year'],t['month'])]
    return {'write':request,'excluded':set(),'write_scope':scope,
            'field_evidence':{k:[t[k]] for k in ('field','new_value')},
            'intent_candidate':candidate.metadata(),'bound_intent':candidate}


def read_proof(candidate, proof, expected, *, actor, book, turn_id, request):
    if (not isinstance(proof, ScopeProof) or proof.actor != actor or candidate.action != 'read'
            or (candidate.actor,candidate.workbook,candidate.turn_id,candidate.request)
            != (actor,str(book),turn_id,request)):
        raise IntentContractError('只读候选不属于当前请求。')
    values, sources, scope = deepcopy(proof.values), dict(proof.sources), deepcopy(expected)
    for slot, value in candidate.target.items():
        values[slot] = scope[slot] = [value]
        sources[slot] = 'model_read_candidate'
    pair = (candidate.target['year'],candidate.target['month'])
    values['periods'] = scope['periods'] = [pair]
    sources['periods'] = 'model_read_candidate'
    # Candidate scope is turn-local and never changes UI workspace or write proof.
    return ScopeProof(actor,values,sources,annual_year=None), scope
