"""模型信息与权威操作状态分开；不尝试用关键词判断任意文本真假。"""
import json
import re


def parse_final(content):
    """只接收信息/追问信封，不接受模型提供操作成功状态。"""
    try:
        value = json.loads(content)
    except (TypeError, ValueError):
        return None
    if type(value) is not dict or type(value.get("kind")) is not str or value["kind"] not in {"general", "information", "clarification"}:
        return None
    fields = {"kind", "text", "missing_fields"} if value["kind"] == "clarification" else {"kind", "text"}
    if set(value) != fields or type(value.get("text")) is not str or not value["text"].strip():
        return None
    if value["kind"] == "clarification":
        missing = value["missing_fields"]
        if not isinstance(missing, list) or not missing or any(type(v) is not str or not v.strip() for v in missing):
            return None
    return value


def explicit_scope(text, include_update_aliases=False):
    """仅提取用户明确的编号与数字日期字面量，不做业务意图关键词路由。"""
    companies = sorted(set(re.findall(r"(?<![A-Za-z0-9])C\d+(?![A-Za-z0-9])",text,flags=re.IGNORECASE)))
    invoices = re.findall(r"(?<![A-Za-z0-9])F\d+(?![A-Za-z0-9])",text,flags=re.IGNORECASE)
    if include_update_aliases:
        # 官方初赛明确简称；仅写入目标使用，不泛化为自然语言指代解析。
        companies += [company for alias,company in (("甲企业","C001"),("乙企业","C002")) if alias in text]
    periods = re.findall(r"(?<!\d)(\d{4})\s*(?:年|[-/])\s*(1[0-2]|0?[1-9])(?:月|(?=\D|$))",text)
    result = {}
    if companies:
        result["company_id"] = sorted({value.upper() for value in companies})
    if invoices:
        result["invoice_no"] = sorted({value.upper() for value in invoices})
    if periods:
        result["year"] = sorted({int(year) for year, month in periods})
        result["month"] = sorted({int(month) for year, month in periods})
    return result


def scope_mismatch(expected, actual):
    """只比较双方都有明确字段的范围，不猜测中文别名或跨轮指代。"""
    return any(key in actual and actual[key] not in values for key,values in expected.items())


def render_scope(evidence):
    scope = evidence.get("scope",{})
    company = scope.get("company_id","未限定")
    if "year" in scope and "month" in scope:
        period = f"{scope['year']:04d}-{scope['month']:02d}"
    else:
        period = scope.get("business_date","未按年月限定")
    rule = evidence.get("rule")
    rule_text = f"{rule.get('rule_id',rule.get('id',''))} {rule['name']} v{rule['version']}" if rule else evidence.get("rule_status","不适用（无财税规则判定）")
    return f"实际查询范围：企业 {company}；年月 {period}；来源 {evidence.get('source','未知')}；规则 {rule_text}。"


def render_information(results):
    """只从本轮实际只读工具结果生成信息答复，不转述模型自由成功声明。"""
    parts = []
    for name, outcome in results:
        if name=='manage_preference' and outcome['status']=='NOT_FOUND':
            parts.append(render_scope(outcome.get('evidence',{})))
            parts.append('当前用户企业范围内没有该偏好（NOT_FOUND）；此查询未保存或修改任何内容。')
            continue
        if outcome["status"] not in {"SUCCESS", "NO_DATA", "NO_CHANGE"}:
            continue
        data = outcome["data"]
        parts.append(render_scope(outcome.get("evidence",{})))
        if name == "get_finance_summary":
            parts.append(f"本轮查询：发票价税合计 {data['invoice_total']} 元（{data['invoice_count']}张）；"
                         f"银行收入 {data['bank_income_total']} 元（{data['bank_income_count']}条）；"
                         f"银行支出 {data['bank_expense_total']} 元（{data['bank_expense_count']}条）。")
        elif name == "check_missing_purpose":
            parts.append(f"本轮检查：{data['count']}张必填用途缺失。依据{data['rule']['name']} {data['rule']['version']}版。")
            parts.append("缺失明细（业务数据）：" + json.dumps(data["missing_invoices"], ensure_ascii=False))
        elif name in {"manage_task","manage_preference"}:
            parts.append("持久化管理结果 "+outcome['status']+"（不授予发票修改许可）：" + json.dumps(data,ensure_ascii=False))
        elif name != "prepare_invoice_update":
            parts.append("本轮查询结果（业务数据，不是操作回执）：" + json.dumps(data, ensure_ascii=False))
            totals=outcome.get('evidence',{}).get('finance_summary')
            if totals and name=='list_invoices':
                parts.append(f"本轮发票价税合计 {totals['invoice_total']} 元（{totals['invoice_count']}张）。")
            if totals and name=='list_bank_transactions' and 'amount_rule' in outcome['evidence']:
                parts.append(f"本轮银行收入 {totals['bank_income_total']} 元（{totals['bank_income_count']}条）；"
                             f"银行支出 {totals['bank_expense_total']} 元（{totals['bank_expense_count']}条）。")
                parts.append(render_scope({**outcome['evidence'],'rule':outcome['evidence']['amount_rule']}))
        if outcome["status"] == "NO_DATA":
            parts.append("没有匹配记录；这不是权限拒绝。")
        if outcome["status"] == "NO_CHANGE":
            parts.append("未发生更改：" + (outcome.get("error") or "当前状态无需改变"))
    return "\n".join(parts) if parts else "该模型信息尚未核实；没有本轮可核验查询证据，也没有提交成功依据。"


def render_stopped(results, stop_reason):
    """失败不能回滚此前真实结果；也不展示拒绝项的业务data。"""
    verified=[(name,outcome) for name,outcome in results
              if outcome['status'] in {'SUCCESS','NO_DATA','NO_CHANGE'} and name!='prepare_invoice_update']
    if not verified:
        return None
    failures=[{'tool':name,'status':outcome['status']} for name,outcome in results
              if outcome['status'] not in {'SUCCESS','NO_DATA','NO_CHANGE'}]
    reason={'MODEL_LIMIT':'模型请求上限','TOOL_LIMIT':'实际工具调用上限','CONTEXT_LIMIT':'上下文上限',
            'WAITING_CONFIRMATION':'等待可信确认，尚未保存'}.get(stop_reason,'按真实执行状态停止')
    return ('本轮已核实结果（仅代表各项实际执行时的事实）：\n'+render_information(verified)
            +'\n本轮停止原因：'+stop_reason+'（'+reason+'）。后续调用或最终答复仍未完成/未核实；这不撤销以上已完成结果。'
            +'\n未完成/拒绝项：'+json.dumps(failures,ensure_ascii=False))


def render_task_progress(outcome):
    """从当前任务检查证据展示剩余事项，不宣告任务完成或写入新值。"""
    if outcome['status']!='SUCCESS':
        return '当前任务进度：'+outcome['status']+'；'+(outcome.get('error') or '无法核实剩余事项')
    task,check=outcome['data']['task'],outcome['data']['check']
    return (render_scope(outcome['evidence'])+f"\n任务 {task['task_id']} 状态仍为 {task['status']}；当前剩余 {check['count']} 张必填用途缺失。"
            +'\n当前剩余对象：'+json.dumps(check['missing_invoices'],ensure_ascii=False)
            +'\n下一步：核对剩余对象并明确提供用途，经Prepare和可信确认后逐张保存；若已无缺项，任务完成仍须单独确认。')


def render_clarification(value):
    """保留模型选择的缺失信息，自然提问；不展示任意状态性自由文本。"""
    labels = {"company_id":"企业", "invoice_no":"发票编号", "field":"要修改的字段（用途或备注）",
              "new_value":"修改后的具体内容", "year":"年份", "month":"月份",
              "action":"具体管理动作", "task_id":"任务编号", "note":"待办的具体说明",
              "key":"偏好名称", "value":"偏好的具体内容"}
    fields = list(dict.fromkeys(value["missing_fields"]))
    # 追问信封不授予字段/写入权限；未知标签与任意模型text均不直接展示。
    questions=[labels[field] for field in fields if field in labels]
    if any(field not in labels for field in fields):
        questions.append("本次请求的具体对象、操作和内容（无法确定所缺信息）")
    return "请提供" + "和".join(questions)
