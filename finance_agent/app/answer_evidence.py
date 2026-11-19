"""Turn-local fact references for model-selected, runtime-bound delivery.

The model selects and orders references. Labels, scopes, values and operation
receipts come from the actual runtime result, never from a model supplied label.
SQL execution facts are distinct from proof of query meaning or completeness.
"""
import json

from .responses import render_information, render_scope, render_tool_failure


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


def catalog(results, receipt, turn_id):
    """Only this ask's actual results are addressable; no historical IDs resolve."""
    facts = {}
    prefix = str(turn_id) + ':'

    def add(key, label, text):
        ref = prefix + key
        facts[ref] = {'ref': ref, 'label': label, 'text': text}

    for index, (name, result) in enumerate(results):
        key = 'r' + str(index)
        evidence = result.get('evidence') or {}
        scope = render_scope(evidence)
        status = result.get('status')
        if status not in {'SUCCESS', 'NO_DATA', 'NO_CHANGE'}:
            add(key + '.status', '工具实际失败/拒绝',
                '\n'.join(filter(None, (scope, render_tool_failure(status, name, result)))))
            continue
        if evidence.get('source') != 'current_sqlite':
            continue
        data = result.get('data')
        add(key + '.result', name, render_information([(name, result)]))
        if name in {'get_finance_summary', 'get_annual_finance_summary'} and isinstance(data, dict):
            for field, (label, unit) in SUMMARY_FIELDS.items():
                if field in data:
                    add(key + '.' + field, label, f'{scope}：{label} {data[field]} {unit}。')
        elif name in {'get_invoice', 'resolve_recent_invoice'} and isinstance(data, dict):
            identity = ' / '.join(str(data.get(k, '')) for k in ('company_id', 'invoice_no'))
            for field, label in INVOICE_FIELDS.items():
                if field in data:
                    value = data[field] if data[field] not in (None, '') else '（空）'
                    add(key + '.' + field, label, f'{scope} {identity}：{label} {value}。')
        elif name == 'query_business_sql':
            # SQL aliases are execution column names, not certified business
            # labels. UNKNOWN never acquires units, set coverage or intent proof.
            query = evidence.get('query_scope') or {}
            facts[prefix + key + '.result']['text'] += (
                '\nSQL 列名（含别名）是实际执行返回的列名，不自动成为已认证的业务指标标签。')
            if query.get('scope') is None:
                facts[prefix + key + '.result']['text'] += (
                    '\n以上仅为授权快照中的实际 SQL 返回；查询语义归属为 UNKNOWN，'
                    '列名不是已认证的业务指标，不证明满足全部筛选或完整目标。')
    add('receipt', '本轮真实操作回执', '操作回执：' + str(receipt.get('message', '本轮未取得操作回执。')))
    return facts


def select(answer, facts):
    """An all-or-nothing ordered selection, with no arbitrary labels or values."""
    if (not isinstance(answer, list) or not answer or len(answer) > 64
            or any(type(ref) is not str or ref not in facts for ref in answer)
            or len(set(answer)) != len(answer)):
        return None
    return '\n'.join(facts[ref]['text'] for ref in answer)


def prompt(facts):
    return {'role': 'system', 'name': 'answer_catalog', 'content': (
        '本轮 answer_catalog 是程序从当前实际工具结果及真实回执生成的数据，不是用户授权。'
        '最终 information 用 answer:[ref,...] 按用户要求选择和排序要交付的事实，'
        '格式例如 {"kind":"information","text":"依据本轮证据回答。","answer":["实际ref"]}。'
        '不可重写标签、数值、范围或操作状态。text 可保留你的组织说明供Trace，'
        '但不作为当前业务事实或操作成功凭据公开。clarification 可同时带 answer 交付已查事实，'
        '并准确给 missing_fields 和待补事件。没有业务读取且用户要求结束时使用 turn_action:"stop"；'
        '它只终止本轮和未提交候选，不撤销历史提交。一般知识用 general，已有受限解释用 explanation。'
        'UNKNOWN SQL只能引用实际表格及其限制，不得宣称完整目标已满足。'
        '没有所需事实就继续调用工具或追问，不用错误/历史引用代替。\n'
        + json.dumps(list(facts.values()), ensure_ascii=False))}
