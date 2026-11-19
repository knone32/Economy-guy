"""Two finite operations on runtime-bound scalar parents; not a general DSL."""
from decimal import Decimal, InvalidOperation
import json

from .queries import _money


def cents(value):
    try:
        result = Decimal(str(value)) * 100
        return int(result) if result.is_finite() and result == result.to_integral_value() else None
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return None


def basis(query, extra=()):
    if query.get('status') != 'VERIFIED' or query.get('scope') is None:
        return None
    items = [c for c in [*query.get('conditions', ()), *extra]
             if c.get('field') not in {'company_id', query.get('date_field')}]
    return json.dumps(sorted({json.dumps(c, ensure_ascii=False, sort_keys=True) for c in items}), ensure_ascii=False)


def scalar(value, *, unit, metric, cohort, subject, scope, scope_text, parent_ref, dimensions=None):
    if type(value) is not int or unit not in {'cents', 'count'}:
        return {}
    return {'type': 'scalar', 'value': value, 'unit': unit, 'metric': tuple(metric), 'basis': cohort,
            'subject': subject, 'scope': dict(scope), 'scope_text': scope_text, 'parent_ref': parent_ref,
            'dimensions': dict(dimensions or {})}


def sql_scalars(result, parent_ref, scope_text):
    """Use existing expression attribution; arbitrary aliases never define metrics."""
    evidence, data = result.get('evidence') or {}, result.get('data') or {}
    query = evidence.get('query_scope') or {}
    if (query.get('status') != 'VERIFIED' or query.get('scope') is None
            or data.get('truncated') is not False or query.get('limited') is not False):
        return {}
    table, columns = query.get('table'), query.get('columns', ())
    if table not in {'invoices', 'bank_transactions'} or len(columns) != len(data.get('columns', ())):
        return {}
    table_label = {'invoices': '发票', 'bank_transactions': '银行流水'}[table]
    operations = {'sum': '金额合计', 'count_rows': '数量', 'count_nonnull': '非空数量',
                  'min': '最小值', 'max': '最大值', 'conditional_sum': '条件金额合计', 'conditional_count': '条件数量'}
    output = {}
    for row_index, row in enumerate(data.get('rows', ())):
        if len(row) != len(columns):
            continue
        dimensions = {m['field']: v for m, v in zip(columns, row)
                      if m.get('kind') == 'column' and m.get('unit') == 'text' and m.get('field')}
        identity = ' / '.join(f'{k}={v}' for k,v in dimensions.items())
        for column_index, (meta, value) in enumerate(zip(columns, row)):
            kind = meta.get('kind')
            if kind not in operations or type(value) is not int:
                continue
            normal_kind = {'conditional_sum': 'sum', 'conditional_count': 'count_rows'}.get(kind, kind)
            metric = (table, normal_kind, meta.get('field'))
            cohort = basis(query, meta.get('conditions', ()))
            label = table_label + operations[kind]
            if meta.get('field') and meta['field'] != 'amount_cents':
                label += '（' + meta['field'] + '）'
            if meta.get('conditions'):
                label += '（' + json.dumps(meta['conditions'], ensure_ascii=False) + '）'
            subject = (identity + ' · ' if identity else '') + label
            info = scalar(value, unit=meta.get('unit'), metric=metric, cohort=cohort, subject=subject,
                          scope=query['scope'], scope_text=scope_text, parent_ref=parent_ref, dimensions=dimensions)
            if info:
                output[f'cell.{row_index}.{column_index}'] = (label, info)
    return output


def _scope_identity(fact):
    scope = fact['scope']
    companies = fact.get('dimensions', {}).get('company_id')
    companies = (companies,) if companies else tuple(scope.get('company_ids') or (scope.get('company_id'),))
    periods = scope.get('periods')
    if periods is None:
        year, month = scope.get('year'), scope.get('month')
        periods = ((year, month),) if month else tuple((year, m) for m in range(1, 13))
    return tuple(sorted(companies)), tuple(sorted(map(tuple, periods)))


def display(value, unit, metric=()):
    count_unit = {'invoices': '张', 'bank_transactions': '笔'}.get(metric[0] if metric else None, '项')
    return _money(value) + ' 元' if unit == 'cents' else str(value) + ' ' + count_unit


def derive(item, facts):
    left, right = facts.get(item['left']), facts.get(item['right'])
    if (not left or not right or left.get('type') != 'scalar' or right.get('type') != 'scalar'
            or left.get('unit') != right.get('unit') or type(left.get('value')) is not int
            or type(right.get('value')) is not int):
        return None
    same_measure = left.get('metric') == right.get('metric') and left.get('basis') == right.get('basis')
    left_scope, right_scope = _scope_identity(left), _scope_identity(right)
    for companies, periods in (left_scope, right_scope):
        if (not companies or any(type(c) is not str or not c for c in companies)
                or not periods or any(type(y) is not int or type(m) is not int or not 1 <= m <= 12
                                     for y,m in periods)):
            return None
    if tuple(map(len, left_scope)) != tuple(map(len, right_scope)):
        return None
    # Cross-metric monetary subtraction remains an explicitly labelled arithmetic
    # fact (e.g. income minus invoice total), never a profit/payment assertion.
    if not same_measure and not (item['op'] == 'subtract' and left['unit'] == 'cents'
                                and left_scope == right_scope):
        return None
    a, b, unit = left['value'], right['value'], left['unit']
    scope = left['scope_text'] if left['scope_text'] == right['scope_text'] else (
        '左侧范围：' + left['scope_text'] + '\n右侧范围：' + right['scope_text'])
    if item['op'] == 'subtract':
        conclusion = f"左侧 {left['subject']} − 右侧 {right['subject']} = {display(a-b, unit, left['metric'])}"
    elif a == b:
        conclusion = f"左侧 {left['subject']}与右侧 {right['subject']}相同，差额 {display(0, unit, left['metric'])}"
    else:
        high, low = ('左侧 ' + left['subject'], '右侧 ' + right['subject']) if a > b else (
            '右侧 ' + right['subject'], '左侧 ' + left['subject'])
        conclusion = f"{high}高于{low}，差额 {display(abs(a-b), unit, left['metric'])}"
    return scope + '\n' + conclusion + '（依据本轮两个父事实计算，不扩展为其他业务结论）。'
