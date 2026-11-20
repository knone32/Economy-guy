"""Finite seller identity/source checks for model-authored read SQL.

No language intent parser. A contains relationship remains a model
interpretation with a current user quote, never a program-proved intent.
"""
from contextlib import closing
import sqlite3
from time import monotonic

from .permissions import check_permission
from .stage2_schema import open_existing

MAX_SELLERS = 1000
MAX_CATALOG_BYTES = 256000
SELLER_SCHEMA = {'type': 'object', 'properties': {
    'mode': {'type': 'string', 'enum': ['single', 'contains']},
    'quote': {'type': 'string', 'minLength': 1, 'maxLength': 2000},
    'value': {'type': 'string', 'minLength': 1, 'maxLength': 2000}},
    'required': ['mode', 'quote', 'value'], 'additionalProperties': False}


class SellerReadError(ValueError):
    def __init__(self, message, status='AMBIGUOUS', *, evidence=None):
        super().__init__(message)
        self.status = status
        self.evidence = {'source': 'seller_request_scope', **(evidence or {})}


def validate_shape(binding):
    if (type(binding) is not dict or set(binding) != {'mode', 'quote', 'value'}
            or type(binding['mode']) is not str or binding['mode'] not in {'single', 'contains'}
            or any(type(binding[k]) is not str or not binding[k].strip() or len(binding[k]) > 2000
                   for k in ('quote', 'value'))):
        raise ValueError('卖方来源须提供single/contains及当前原话quote/value')


def validate_source(binding, request):
    validate_shape(binding)
    if (not isinstance(request, str) or binding['quote'] not in request
            or binding['value'] not in binding['quote']):
        raise SellerReadError('卖方条件缺少当前原话的连续来源。', 'SCOPE_MISMATCH')
    if binding['mode'] == 'contains' and binding['quote'].strip() == binding['value'].strip():
        raise SellerReadError('包含关系需要当前完整条件原话，不能只复制名称词。')


def catalog(path, actor, company_ids):
    """Complete all-period seller directory for current readable enterprises."""
    companies = tuple(company_ids)
    if not companies:
        raise SellerReadError('卖方目录缺少可信企业范围。')
    try:
        with closing(open_existing(path, readonly=True)) as db:
            db.execute('BEGIN')
            if any(not check_permission(db, actor, company, 'read').allowed for company in companies):
                raise SellerReadError('当前账号没有卖方目录的企业读取权限。', 'DENIED')
            deadline = monotonic() + 2
            db.set_progress_handler(lambda: monotonic() > deadline, 1000)
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_CATALOG_BYTES)
            marks = ','.join('?' for _ in companies)
            names = [row[0] for row in db.execute(
                f'SELECT DISTINCT seller_name FROM invoices WHERE company_id IN ({marks}) '
                'ORDER BY seller_name LIMIT ?', (*companies, MAX_SELLERS + 1))]
            size = sum(len(name.encode('utf-8')) if isinstance(name, str) else 4 for name in names)
            if (len(names) > MAX_SELLERS or size > MAX_CATALOG_BYTES
                    or any(isinstance(name, str) and len(name) > 2000 for name in names)):
                raise SellerReadError('完整卖方目录超过受控上限，请缩小企业范围。', 'SQL_SCOPE_LIMIT')
            return names
    except sqlite3.Error as error:
        status = 'SQL_SCOPE_LIMIT' if getattr(error, 'sqlite_errorcode', None) in {
            sqlite3.SQLITE_INTERRUPT, sqlite3.SQLITE_TOOBIG} else 'ERROR'
        raise SellerReadError('无法完整核实当前授权卖方目录。', status) from None


def full_mentions(request, names):
    from .business_object_sources import literal_spans
    found = [(name, span) for name in names if isinstance(name, str) and name
             for span in literal_spans(request or '', name)]
    return {name for name, span in found if not any(
        other[0] <= span[0] and other[1] >= span[1] and other != span
        for _, other in found)}


def _evidence(names, **extra):
    candidates = [name for name in names if isinstance(name, str) and name]
    return {'seller_scope': {'source': 'current_authorized_seller_catalog',
        'candidates': candidates[:20], 'candidate_total': len(candidates),
        'candidates_truncated': len(candidates) > 20, 'catalog_complete': True, **extra}}


def _matching(names, conditions):
    """Evaluate only existing proved predicates with SQLite's own semantics."""
    with closing(sqlite3.connect(':memory:')) as db:
        matched = set()
        for name in names:
            included = True
            for condition in conditions:
                target, values = '?', [name]
                transform = condition.get('transform')
                if transform == 'trim_ascii_space':
                    target = 'trim(?)'
                elif transform is not None:
                    raise SellerReadError('卖方转换形式尚无法核实。')
                operator, value = condition.get('operator'), condition.get('value')
                if operator == 'IN' and isinstance(value, list) and value:
                    expression = target + ' IN (' + ','.join('?' for _ in value) + ')'
                    values += value
                elif operator in {'=', '!=', '>', '>=', '<', '<=', 'LIKE'}:
                    expression = target + ' ' + operator + ' ?'
                    values.append(value)
                elif operator == 'is_blank' and type(value) is bool:
                    blank = name is None or not str(name).strip()
                    if blank != value:
                        included = False
                        break
                    continue
                else:
                    raise SellerReadError('卖方谓词尚无法核实。')
                if not db.execute('SELECT ' + expression, values).fetchone()[0]:
                    included = False
                    break
            if included:
                matched.add(name)
        return matched


def resolve(request, names, binding):
    full = full_mentions(request, names)
    if binding is not None:
        validate_source(binding, request)
        value = binding['value']
        chosen = {name for name in names if isinstance(name, str) and value in name}
        if binding['mode'] == 'single' and len(chosen) != 1:
            candidates = sorted(chosen)
            raise SellerReadError('卖方名称未唯一核实，请选择可区别的完整名称：' + '、'.join(candidates[:20]),
                                  evidence=_evidence(candidates))
        if full and chosen != full:
            raise SellerReadError('卖方候选不能覆盖当前原话中的完整登记身份。', 'SCOPE_MISMATCH',
                                  evidence=_evidence(sorted(full)))
        return full or chosen, {'mode': binding['mode'], 'quote': binding['quote'], 'value': value,
                                'interpretation': 'model_with_current_user_quote'}
    if full:
        return full, {'mode': 'single' if len(full) == 1 else 'registered_names',
                      'quote': sorted(full), 'interpretation': 'registered_full_name_source'}
    return None, None


def verify(path, actor, scope, request, binding, query, reads):
    """Check before returning any rows; bank-only queries are unaffected."""
    if 'invoices' not in reads or (request is None and binding is None):
        # Trusted direct Python callers report executed scope only. The Agent
        # always supplies current user text; this is not a production fallback.
        return None
    names = catalog(path, actor, scope['company_ids'])
    expected, source = resolve(request, names, binding)
    conditions = [c for c in query.get('conditions', ()) if c.get('field') == 'seller_name']
    if expected is None:
        if not conditions:
            return None
        candidates = [name for name in names if isinstance(name, str) and name]
        notice = '尚未核实本次销售方范围，请指定完整销售方，或明确名称包含条件。'
        if candidates:
            notice += '当前可读目录候选（不是已选目标）：' + '、'.join(candidates[:20]) + '。'
            if len(candidates) > 20:
                notice += '这里只显示前20个候选，目录仍有其他名称，请提供更具体的名称。'
        else:
            notice += '当前可读企业目录没有可核实的销售方名称。'
        raise SellerReadError(notice, evidence=_evidence(names))
    if query.get('status') != 'VERIFIED' or not conditions:
        raise SellerReadError('无法核实查询是否完整保留您指定的销售方，尚未交付统计。', 'SCOPE_MISMATCH',
                              evidence=_evidence(sorted(expected), **source))
    actual = _matching(names, conditions)
    if actual != expected:
        raise SellerReadError('实际查询的销售方范围与您当前指定的不一致，尚未交付统计。', 'SCOPE_MISMATCH',
                              evidence=_evidence(sorted(expected), **source))
    return {'source': 'current_authorized_seller_catalog', 'names': sorted(expected),
            'catalog_complete': True, 'authorization': False, **source}
