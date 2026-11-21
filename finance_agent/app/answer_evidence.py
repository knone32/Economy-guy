"""Turn-local fact references for model-selected, runtime-bound delivery.

The model selects and orders references. Labels, scopes, values and operation
receipts come from the actual runtime result, never from a model supplied label.
SQL execution facts are distinct from proof of query meaning or completeness.
"""
import json
from hashlib import sha256

from .responses import render_information, render_scope, render_summary_basis, render_tool_failure, valid_answer_item
from .fact_arithmetic import basis as measure_basis, cents, derive, display, scalar, sql_scalars


SUMMARY_FIELDS = {
    'invoice_count': ('发票张数', '张'),
    'invoice_total': ('发票价税合计', '元'),
    'bank_income_count': ('银行收入笔数', '笔'),
    'bank_income_total': ('银行收入合计', '元'),
    'bank_expense_count': ('银行支出笔数', '笔'),
    'bank_expense_total': ('银行支出合计', '元'),
}
INVOICE_FIELDS = {
    'invoice_no': '发票编号', 'invoice_date': '开票日期', 'seller_name': '销售方',
    'item_name': '项目', 'amount': '发票价税合计（元）', 'purpose': '用途', 'remark': '备注',
}


def returned_invoice_counts(result):
    """Count an actual complete returned identity set, not a natural-language goal.

    The projection/coverage metadata is produced by BusinessSQL from the same
    authorized snapshot. Aliases, arbitrary row_count and duplicate rows cannot
    supply invoice identity. Whole-snapshot coverage is deliberately not needed.
    """
    data = result.get('data') or {}
    projection = data.get('invoice_projection') or {}
    coverage = data.get('invoice_coverage') or {}
    if (data.get('truncated') is not False or coverage.get('sql_paginated') is not False
            or coverage.get('display_truncated') is not False
            or not {'company_id', 'invoice_no'} <= projection.keys()):
        return None
    companies = (result.get('evidence') or {}).get('scope', {}).get('company_ids', ())
    if not companies or any(type(c) is not str or not c for c in companies):
        return None
    counts = dict.fromkeys(sorted(set(companies)), 0)
    company_index, invoice_index = projection['company_id'], projection['invoice_no']
    if any(type(i) is not int or i < 0 for i in (company_index, invoice_index)):
        return None
    seen = set()
    for row in data.get('rows', ()):
        if max(company_index, invoice_index) >= len(row):
            return None
        company, number = row[company_index], row[invoice_index]
        if (company not in counts or type(number) is not str or not number
                or (company, number) in seen):
            return None
        seen.add((company, number))
        counts[company] += 1
    return counts


def catalog(results, receipt, turn_id):
    """Only this ask's actual results are addressable; no historical IDs resolve."""
    facts = {}
    prefix = str(turn_id) + ':'

    def add(key, label, text, **metadata):
        ref = prefix + key
        facts[ref] = {'ref': ref, 'label': label, 'text': text, **metadata}

    for index, (name, result) in enumerate(results):
        key = 'r' + str(index)
        evidence = result.get('evidence') or {}
        scope = render_scope(evidence)
        status = result.get('status')
        if status not in {'SUCCESS', 'NO_DATA', 'NO_CHANGE'}:
            add(key + '.status', '工具实际失败/拒绝',
                '\n'.join(filter(None, (scope, render_tool_failure(status, name, result)))), type='status', value=status)
            continue
        if evidence.get('source') != 'current_sqlite':
            continue
        data = result.get('data')
        parent = prefix + key + '.result'
        add(key + '.result', name, render_information([(name, result)]), type='result', scope=evidence.get('scope', {}))
        if name=='check_missing_purpose' and (evidence.get('business_request') or {}).get('view_adapter')=='rule_missing':
            for number, item in enumerate(evidence['business_request'].get('scalar_facts',())):
                if item.get('operation') not in {'count','sum'}:continue
                amount=item.get('value');unit=item.get('unit')
                operation='count_rows' if item['operation']=='count' else 'sum'
                info=scalar(amount,unit=unit,metric=('invoices',operation,item['field']),
                    cohort=item['basis'],subject='实际用途规则下的完整缺项集合',scope=evidence.get('scope',{}),
                    scope_text=scope,parent_ref=parent)
                if info:
                    text=(f'{scope}：按实际用途规则缺项 {amount} 张。' if unit=='count' else
                          f'{scope}：实际用途规则缺项金额 {display(amount,"cents")}。')
                    add(key+'.required_missing.'+str(number),'规则缺项指标',text,**info)
        if name in {'get_finance_summary', 'get_annual_finance_summary'} and isinstance(data, dict):
            basis_text = render_summary_basis(evidence.get('rule'))
            basis_ref = prefix + key + '.basis' if basis_text else None
            if basis_ref:
                add(key + '.basis', '统计口径与规则来源', scope + '\n' + basis_text, type='basis', parent_ref=parent)
            for field, (label, unit) in SUMMARY_FIELDS.items():
                if field in data:
                    add(key + '.' + field, label, f'{scope}：{label} {data[field]} {unit}。')
                    if basis_ref:
                        facts[prefix + key + '.' + field]['basis_ref'] = basis_ref
                    table = 'invoices' if field.startswith('invoice_') else 'bank_transactions'
                    operation = 'count_rows' if field.endswith('_count') else 'sum'
                    conditions = [] if table == 'invoices' else [{'field': 'direction', 'operator': '=',
                        'value': '收入' if field.startswith('bank_income') else '支出'}]
                    amount = data[field] if operation == 'count_rows' else cents(data[field])
                    subject = ' / '.join(str(evidence.get('scope', {}).get(k, '')) for k in ('company_id',)) + ' · ' + label
                    cohort = measure_basis({'status': 'VERIFIED', 'scope': evidence.get('scope', {}), 'conditions': conditions})
                    facts[prefix + key + '.' + field].update(scalar(amount, unit='count' if operation == 'count_rows' else 'cents',
                        metric=(table, operation, None if operation == 'count_rows' else 'amount_cents'), cohort=cohort,
                        subject=subject, scope=evidence.get('scope', {}), scope_text=scope, parent_ref=parent))
        elif name in {'get_invoice', 'resolve_recent_invoice'} and isinstance(data, dict):
            identity = ' / '.join(str(data.get(k, '')) for k in ('company_id', 'invoice_no'))
            for field, label in INVOICE_FIELDS.items():
                if field in data:
                    value = data[field] if data[field] not in (None, '') else '（空）'
                    add(key + '.' + field, label, f'{scope} {identity}：{label} {value}。',
                        type='text', value=value, parent_ref=parent)
                    if field == 'amount':
                        facts[prefix + key + '.' + field].update(scalar(cents(data[field]), unit='cents',
                            metric=('invoices', 'column', 'amount_cents'), cohort='[]', subject=identity + ' · ' + label,
                            scope=evidence.get('scope', {}), scope_text=scope, parent_ref=parent))
        elif name == 'query_business_sql':
            # SQL aliases are execution column names, not certified business
            # labels. UNKNOWN never acquires units, set coverage or intent proof.
            query = evidence.get('query_scope') or {}
            if not (query.get('status') == 'VERIFIED'
                    and data.get('request_projection', {}).get('detail_columns_only')):
                facts[prefix + key + '.result']['text'] += (
                    '\nSQL 列名（含别名）是实际执行返回的列名，不自动成为已认证的业务指标标签。')
            if query.get('scope') is None:
                facts[prefix + key + '.result']['text'] += (
                    '\n以上仅为授权快照中的实际 SQL 返回；查询语义归属为 UNKNOWN，'
                    '列名不是已认证的业务指标，不证明满足全部筛选或完整目标。')
            counts = returned_invoice_counts(result)
            if counts is not None:
                cohort = measure_basis(query) or ('returned_set:' + parent)
                for company, count in counts.items():
                    field = key + '.returned_invoice_count.' + company
                    add(field, '本次返回明细的企业发票数',
                        f'{scope}：本次返回明细中 {company} 发票 {count} 张（按企业与票号联合键计数，不代表授权账簿全集）。')
                    facts[prefix + field]['parent_ref'] = prefix + key + '.result'
                    facts[prefix + field].update(scalar(count, unit='count', metric=('invoices', 'count_rows', None),
                        cohort=cohort, subject=company + ' · 本次返回明细发票数', scope=evidence.get('scope', {}),
                        scope_text=scope, parent_ref=parent, dimensions={'company_id': company}))
                projection = data.get('invoice_projection') or {}
                amount_index, company_index = projection.get('amount_cents'), projection.get('company_id')
                if (type(amount_index) is int and amount_index >= 0 and type(company_index) is int
                        and all(len(row) > amount_index and type(row[amount_index]) is int for row in data['rows'])):
                    totals = dict.fromkeys(counts, 0)
                    for row in data['rows']:
                        totals[row[company_index]] += row[amount_index]
                    for company, total in totals.items():
                        field = key + '.returned_invoice_total.' + company
                        label = '本次返回明细发票价税合计'
                        info = scalar(total, unit='cents', metric=('invoices', 'sum', 'amount_cents'), cohort=cohort,
                            subject=company + ' · ' + label, scope=evidence.get('scope', {}), scope_text=scope,
                            parent_ref=parent, dimensions={'company_id': company})
                        add(field, label, f'{scope}：本次返回明细中 {company} 发票价税合计 {display(total, "cents")}。', **info)
                if len(counts) == 2:
                    first, second = counts
                    difference = counts[first] - counts[second]
                    comparison = (f'{first} 与 {second} 的发票张数相同，差额 0 张' if difference == 0
                                  else f'{first} 比 {second} 多 {difference} 张' if difference > 0
                                  else f'{second} 比 {first} 多 {-difference} 张')
                    field = key + '.returned_invoice_difference.' + first + '.' + second
                    add(field, '本次返回明细的企业发票数比较', f'{scope}：本次返回明细中 {comparison}。')
                    facts[prefix + field]['parent_ref'] = prefix + key + '.result'
            for suffix, (label, info) in sql_scalars(result, parent, scope).items():
                add(key + '.' + suffix, label, f'{scope}：{info["subject"]} {display(info["value"], info["unit"], info["metric"])}。', **info)
    add('receipt', '本轮真实操作回执', '操作回执：' + str(receipt.get('message', '本轮未取得操作回执。')),
        type='receipt', value=receipt.get('status', 'UNKNOWN'))
    return facts


def select(answer, facts):
    """An all-or-nothing ordered selection, with no arbitrary labels or values."""
    if (not isinstance(answer, list) or not answer or len(answer) > 64
            or any(not valid_answer_item(ref) for ref in answer)
            or len({json.dumps(ref, sort_keys=True) for ref in answer}) != len(answer)):
        return None
    rendered = []
    dependencies = []
    for item in answer:
        text = facts.get(item, {}).get('text') if type(item) is str else derive(item, facts)
        if text is None:
            return None
        rendered.append(text)
        # Provenance is a dependency of the chosen fact, including arithmetic
        # parents. This never determines which metric the user intended.
        parents = (item,) if type(item) is str else (item['left'], item['right'])
        for parent in parents:
            ref = facts.get(parent, {}).get('basis_ref')
            if ref and ref not in dependencies and ref not in answer:
                dependencies.append(ref)
    for ref in dependencies:
        if ref not in facts:
            return None
        rendered.append(facts[ref]['text'])
    return '\n'.join(rendered)


def selection_diagnostic(answer, facts):
    """Explain a failed selection without choosing replacements or changing facts."""
    if not isinstance(answer, list) or any(not valid_answer_item(item) for item in answer):
        return {'issues': [{'reason': 'invalid_answer_structure'}]}
    issues = []
    for index, item in enumerate(answer):
        references = (('ref', item),) if type(item) is str else (
            ('left', item['left']), ('right', item['right']))
        for side, ref in references:
            fact = facts.get(ref)
            if fact is None:
                issues.append({'answer_index': index, 'side': side, 'ref': ref[:200],
                               'reason': 'missing_reference'})
            elif type(item) is dict and fact.get('type') != 'scalar':
                issues.append({'answer_index': index, 'side': side, 'ref': ref[:200],
                               'reason': 'parent_type_mismatch', 'expected_type': 'scalar',
                               'actual_type': fact.get('type'), 'op': item['op']})
        if len(issues) >= 8:
            break
    return {'issues': issues[:8] or [{'reason': 'incompatible_current_fact_selection'}]}


def prompt(facts):
    view = []
    for fact in facts.values():
        item = {key: fact[key] for key in ('ref', 'label', 'type', 'value', 'unit', 'metric', 'parent_ref', 'dimensions', 'basis_ref') if key in fact}
        if fact.get('type') == 'result':
            item['scope'] = fact.get('scope', {})
        if fact.get('type') == 'text':
            item.pop('value', None)  # The complete value remains in its original tool message.
        if 'basis' in fact:
            item['basis_id'] = sha256(str(fact['basis']).encode()).hexdigest()[:16]
        view.append(item)
    return {'role': 'system', 'name': 'answer_catalog', 'content': (
        '本轮 answer_catalog 是程序从当前实际工具结果及真实回执生成的数据，不是用户授权。'
        '最终 information 用 answer:[ref,...] 按用户要求选择和排序要交付的事实，'
        '格式例如 {"kind":"information","text":"依据本轮证据回答。","answer":["实际ref"]}。'
        '要比较/求差，可在answer使用{"op":"compare","left":"父ref","right":"父ref"}，op也可为subtract；'
        '只允许本轮scalar父事实，程序验证指标/单位/口径并算术，不接收自定义label、值或嵌套运算。'
        'compare用于相同指标口径；subtract也可对同范围不同金额指标作明确标注的差，不推断利润或回款。'
        '不可重写标签、数值、范围或操作状态。text 可保留你的组织说明供Trace，'
        '但不作为当前业务事实或操作成功凭据公开。clarification 可同时带 answer 交付已查事实，'
        '并准确给 missing_fields 和待补事件。没有业务读取且用户要求结束时使用 turn_action:"stop"；'
        '它只终止本轮和未提交候选，不撤销历史提交。一般知识用 general，已有受限解释用 explanation。'
        'UNKNOWN SQL只能引用实际表格及其限制，不得宣称完整目标已满足。'
        '用户需要的统计或比较须用相应事实ref或工具计算覆盖；不要只在text中补充未引用的数值。'
        '已有所需当前父事实就直接引用或运算收尾，不为重复得到同一事实再次查询。'
        '没有所需事实就继续调用工具或追问，不用错误/历史引用代替。\n'
        'catalog仅列紧凑引用元数据；完整行/SQL和来源在原工具消息，执行侧保留完整事实文本。\n'
        + json.dumps(view, ensure_ascii=False))}
