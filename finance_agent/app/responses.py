"""模型信息与权威操作状态分开；不尝试用关键词判断任意文本真假。"""
import json
import re


def parse_final(content):
    """只接收信息/追问信封，不接受模型提供操作成功状态。"""
    try:
        value = json.loads(content)
        json.dumps(value, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        return None
    if type(value) is not dict or type(value.get("kind")) is not str or value["kind"] not in {"general", "information", "clarification", "explanation"}:
        return None
    fields = {"kind", "text", "missing_fields"} if value["kind"] == "clarification" else {"kind", "text"}
    if set(value) != fields or type(value.get("text")) is not str or not value["text"].strip():
        return None
    if value["kind"] == "clarification":
        missing = value["missing_fields"]
        if not isinstance(missing, list) or not missing or any(type(v) is not str or not v.strip() for v in missing):
            return None
    return value


def render_grounded_explanation(text, facts):
    """Render a model-written explanation with values supplied by the Harness."""
    if "annual_blank_purpose" in facts:
        data = facts["annual_blank_purpose"]
        when = "上一轮查询" if data["historical"] else "本轮查询"
        year, month = data["compliance_period"]
        boundary = f"字段为空本身不足以认定违规。当前支持的用途合规检查账期为 {year} 年 {month} 月。"
        if data["rule"]:
            boundary += f"该企业在该账期的依据为 {data['rule']['id']} v{data['rule']['version']}。"
        slots = {"result": f"{when}中，{data['company_id']} {data['year']} 年用途为空的发票共 {data['total']} 张。",
                 "boundary": boundary}
    elif "bank_invoice_link" in facts:
        slots = {"boundary": "当前账簿没有可靠的发票与银行流水关联，无法据此判断具体发票是否已付款。"}
    else:
        return None
    token = r"\[\[([a-z_]+)\]\]"
    if sorted(re.findall(token, text)) != sorted(slots):
        return None
    prose = re.sub(token, "", text)
    if (not prose.strip() or re.search(
            r"[\d¥￥$\[\]]|[零〇一二两三四五六七八九十百千万亿]+\s*(?:张|条|元|分|年|月)|"
            r"金额|人民币|已(?:经)?(?:保存|提交|修改|付款|支付|确认|授权)|成功(?:保存|提交|修改)", prose)):
        return None
    return re.sub(token, lambda match: slots[match[1]], text)


def explicit_scope(text, include_update_aliases=False):
    """仅提取用户明确的编号与数字日期字面量，不做业务意图关键词路由。"""
    companies = sorted(set(re.findall(r"(?<![A-Za-z0-9])C\d+(?![A-Za-z0-9])",text,flags=re.IGNORECASE)))
    invoices = re.findall(r"(?<![A-Za-z0-9])F\d+(?![A-Za-z0-9])",text,flags=re.IGNORECASE)
    if include_update_aliases:
        # 官方初赛明确简称；仅写入目标使用，不泛化为自然语言指代解析。
        companies += [company for alias,company in (("甲企业","C001"),("乙企业","C002")) if alias in text]
    names = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,'十一':11,'十二':12}
    month_number = r"1[0-2]|0?[1-9]"
    month_literal = month_number + r"|十一|十二|[一二三四五六七八九十]"
    date_pattern = re.compile(
        rf"(?<!\d)(\d{{4}})\s*(?:年(?:\s*的)?\s*({month_literal})\s*月|[-/]\s*({month_number})(?!\d))"
    )
    periods = set()
    for year, chinese, numeric in date_pattern.findall(text):
        month = chinese or numeric
        periods.add((int(year), int(month) if month.isdigit() else names[month]))
    result = {}
    if companies:
        result["company_id"] = sorted({value.upper() for value in companies})
    if invoices:
        result["invoice_no"] = sorted({value.upper() for value in invoices})
    # 完整字面量保留配对，独立槽位只用于唯一补齐或追问。
    remaining = date_pattern.sub(" ", text)
    years = {int(y) for y in re.findall(r"(?<!\d)(\d{4})\s*年", remaining)}
    months = {int(m) if m.isdigit() else names[m]
              for m in re.findall(rf"(?<![\d一二三四五六七八九十])({month_literal})\s*月", remaining)}
    if not periods and len(years) == len(months) == 1:
        periods.add((next(iter(years)), next(iter(months))))
    if periods:
        result["periods"] = sorted(periods)
    years.update(year for year, month in periods)
    months.update(month for year, month in periods)
    if years:
        result["year"] = sorted(years)
    if months:
        result["month"] = sorted(months)
    return result


def scope_mismatch(expected, actual):
    """只比较双方都有明确字段的范围，不猜测中文别名或跨轮指代。"""
    if "periods" in expected and "year" in actual and "month" in actual:
        if (actual["year"], actual["month"]) not in expected["periods"]:
            return True
    return any(key in actual and actual[key] not in values for key,values in expected.items())


def scope_key(evidence):
    scope = evidence.get("scope", {})
    rule = evidence.get("rule") or {}
    period = (scope["year"], scope.get("month")) if "year" in scope else scope.get("business_date")
    return (scope.get("company_id"), period, evidence.get("source"),
            rule.get("rule_id") or rule.get("id"), rule.get("version"), rule.get("name"), evidence.get("rule_status"))


def render_scope(evidence, *, conversational=False):
    scope = evidence.get("scope",{})
    company = scope.get("company_id","未限定")
    if "year" in scope and "month" in scope:
        period = f"{scope['year']:04d}-{scope['month']:02d}"
    elif "year" in scope:
        period = f"{scope['year']} 年"
    else:
        period = scope.get("business_date","未按年月限定")
    rule = evidence.get("rule")
    rule_text = f"{rule.get('rule_id',rule.get('id',''))} {rule['name']} v{rule['version']}" if rule else evidence.get("rule_status","不适用（无财税规则判定）")
    if conversational:
        heading = f"企业 {company}" if "company_id" in scope else ""
        if "year" in scope and "month" in scope:
            heading += f" {scope['year']} 年 {scope['month']} 月"
        elif "year" in scope:
            heading += f" {scope['year']} 年"
        elif "business_date" in scope:
            heading += f" {scope['business_date']}"
        source = {"current_sqlite": "按工作账簿当前记录", "local_display_preference": "按本地显示设置"}.get(
            evidence.get("source"), "按本轮核验记录")
        basis = ""
        if rule:
            rule_id = rule.get("rule_id") or rule.get("id", "")
            basis = f"，依据 {rule_id} v{rule['version']} {rule['name']}"
        return f"{heading.strip()}（{source}{basis}）" if heading.strip() else source + basis
    return f"实际查询范围：企业 {company}；年月 {period}；来源 {evidence.get('source','未知')}；规则 {rule_text}。"


def render_reference_error(status):
    return {
        "DENIED": "当前账号没有读取权限，请切换到有权限的账簿账号。",
        "NOT_FOUND": "先前展示的发票已找不到，请刷新发票列表后再选。",
        "SCOPE_MISMATCH": "先前展示的发票已不在当前范围，请重新查询或明确企业和发票编号。",
        "ERROR": "当前无法读取工作账簿，请检查账簿后重试。",
    }.get(status, "我还不能确定你指的是哪张发票，请提供企业名称和发票编号，或者从发票列表中选择。")


def verified_task_progress(results):
    """仅合并本轮唯一匹配的已鉴权任务读取与用途检查。"""
    reads = []
    checks = []
    for name, outcome in results:
        evidence = outcome.get("evidence", {})
        if name == "manage_task" and evidence.get("management_confirmation"):
            return None
        if outcome["status"] != "SUCCESS" or evidence.get("source") != "current_sqlite":
            continue
        if name == "list_tasks":
            reads.extend((task, evidence["scope"]) for task in outcome["data"])
        elif name == "manage_task" and "task" in outcome["data"]:
            reads.append((outcome["data"]["task"], evidence["scope"]))
        elif name == "check_missing_purpose":
            checks.append(outcome)
    if len(checks) != 1:
        return None
    outcome = checks[0]
    check, evidence = outcome["data"], outcome["evidence"]
    scope = evidence["scope"]
    tasks = [task for task, read_scope in reads
             if task.get("task_id") and task.get("task_type") == "missing_purpose"
             and task.get("status") in {"ACTIVE", "WAITING_USER", "PAUSED"}
             and read_scope.get("company_id") == scope.get("company_id")
             and all(key in scope and task.get(key) == scope[key] for key in ("company_id", "year", "month"))]
    if len(tasks) != 1 or check["rule"] != evidence.get("rule") or check["count"] != len(check["missing_invoices"]):
        return None
    return {"status": "SUCCESS", "data": {"task": tasks[0], "check": check}, "evidence": evidence}


def render_task_closure(data):
    task, check = data["task"], data["check"]
    parts = [f"已重新核对待办与缺项。待办 {task['status']}，当前剩余 {check['count']} 张必填用途缺失。"]
    if data["filled"]:
        parts.append("当前值已填写：" + "、".join(data["filled"]) + "。")
    if data["audited"]:
        parts.append("有补齐成功记录且当前值一致：" + "、".join(data["audited"]) + "。审计未绑定待办。")
    if check["count"]:
        parts.append("下一步：逐张补齐缺项，保存前核对并确认。")
    elif task["status"] in {"ACTIVE", "WAITING_USER", "PAUSED"}:
        parts.append("下一步：打开待办，单独核对并确认完成。")
    return "\n".join(parts)


def needs_progress_evidence(results):
    return (any(name == "check_missing_purpose" for name, _ in results)
            and any(outcome["status"] in {"SUCCESS", "NO_DATA"} and
                    (name == "list_tasks" or (name == "manage_task" and
                     outcome.get("evidence", {}).get("operation", {}).get("action") in {None, "show"}))
                    for name, outcome in results)
            and not any(name == "manage_task" and outcome.get("evidence", {}).get("management_confirmation")
                        for name, outcome in results))


def render_task_scope_negotiation(stopped, results):
    if not stopped or stopped["status"] != "SCOPE_MISMATCH":
        return None
    guidance = stopped["evidence"].get("scope_negotiation", {})
    if guidance.get("reason") != "purpose_task_period":
        return None
    parts = []
    if guidance["annual"]:
        requested = stopped["evidence"].get("requested_scope", {})
        if any(name == "list_annual_blank_purpose" and outcome["status"] in {"SUCCESS", "NO_DATA"}
               and outcome["evidence"].get("source") == "current_sqlite"
               and not scope_mismatch(requested, outcome["evidence"].get("scope", {}))
               for name, outcome in results):
            parts.append("本轮年度用途空值查询已完成。")
        parts.append("全年空值只说明用途字段未填写，不能判定全年用途不合规。")
    parts.append("当前仅支持2026年9月用途合规检查。本轮尚未创建待办。")
    alternative = guidance.get("alternative_scope")
    if alternative:
        counts = {outcome["data"]["count"] for name, outcome in results
                  if name == "check_missing_purpose" and outcome["status"] == "SUCCESS"
                  and outcome["evidence"].get("source") == "current_sqlite"
                  and outcome["evidence"].get("scope") == alternative}
        if len(counts) == 1:
            parts.append(f"本轮已核验该月有 {next(iter(counts))} 张必填用途缺失。")
        parts.append("是否改为该月创建待办？请明确回复"
                     f"「按 {alternative['company_id']} 2026年9月创建待办」。")
    else:
        parts.append("请明确要处理的企业与单月待办操作。")
    return "\n".join(parts)


def directory_preview(pages):
    return min(pages, key=lambda page: page["page"])["rows"][:3]


def display_rule_amounts(content):
    def yuan(cents):
        whole, fraction = divmod(int(cents), 100)
        return f"¥{whole:,}.{fraction:02d}"

    content = re.sub(r"大于或等于\s*(\d+)\s*分", lambda m: f"达到{yuan(m[1])}（含）", content)
    return re.sub(r"(?<![\d.])(\d+)\s*分(?!钟)", lambda m: yuan(m[1]), content)


def render_rule_history(rows):
    return "\n".join(
        f"{row['rule_id']} v{row['version']} · {'已停用' if row['status'] == 'DISABLED' else '启用'}"
        f" · 生效日期 {row['effective_from']}：{display_rule_amounts(row['content'])}" for row in rows
    ) or "该企业范围内没有此规则的历史版本。"


def render_invoice_comparison(previous, current):
    labels = {"invoice_date": "开票日期", "seller_name": "销售方", "item_name": "项目",
              "amount": "价税合计", "purpose": "用途", "remark": "备注"}
    first = f"{previous['company_id']}/{previous['invoice_no']}"
    second = f"{current['company_id']}/{current['invoice_no']}"
    differences = [f"{label}：{previous[key] or '（空）'} → {current[key] or '（空）'}"
                   for key, label in labels.items() if previous[key] != current[key]]
    return f"已重新读取 {first} 与 {second}。\n" + ("\n".join(differences) or "所列发票字段一致。")


def render_information(results):
    """保留执行摘要，从本轮真实证据按结构化范围合并说明。"""
    parts = []
    scopes = set()

    def add_scope(evidence):
        key = scope_key(evidence)
        if key not in scopes:
            scopes.add(key)
            parts.append(render_scope(evidence))

    for name, outcome in results:
        if name=='manage_preference' and outcome['status']=='NOT_FOUND':
            add_scope(outcome.get('evidence', {}))
            parts.append('当前用户企业范围内没有该偏好（NOT_FOUND）；此查询未保存或修改任何内容。')
            continue
        if outcome["status"] not in {"SUCCESS", "NO_DATA", "NO_CHANGE"}:
            continue
        data = outcome["data"]
        add_scope(outcome.get("evidence", {}))
        if name in {"get_finance_summary", "get_annual_finance_summary"}:
            parts.append(f"本轮查询：发票价税合计 {data['invoice_total']} 元（{data['invoice_count']}张）；"
                         f"银行收入 {data['bank_income_total']} 元（{data['bank_income_count']}条）；"
                         f"银行支出 {data['bank_expense_total']} 元（{data['bank_expense_count']}条）。")
        elif name == "get_applicable_rules":
            parts.append(f"当前适用规则 {data['rule_id']} v{data['version']}：" + display_rule_amounts(data["content"]))
        elif name == "list_rule_versions":
            parts.append(render_rule_history(data))
        elif name == "list_annual_blank_purpose":
            parts.append(f"全年用途字段为空的发票共 {data['total']} 张（仅检查字段值）。"
                         + f"第 {data['page']} 页：" + "、".join(row["invoice_no"] for row in data["rows"]))
        elif name == "check_missing_purpose":
            parts.append(f"本轮检查：{data['count']}张必填用途缺失。依据{data['rule']['name']} {data['rule']['version']}版。")
            parts.append(display_rule_amounts(data["rule"]["content"]))
            parts.append("缺失明细（业务数据）：" + json.dumps(data["missing_invoices"], ensure_ascii=False))
        elif name in {"manage_task","manage_preference","manage_display_preference"}:
            parts.append("持久化管理结果 "+outcome['status']+"（不授予发票修改许可）：" + json.dumps(data,ensure_ascii=False))
        elif name != "prepare_invoice_update":
            parts.append("本轮查询结果（业务数据，不是操作回执）：" + json.dumps(data, ensure_ascii=False))
            totals=outcome.get('evidence',{}).get('finance_summary')
            if totals and name=='list_invoices':
                parts.append(f"本轮发票价税合计 {totals['invoice_total']} 元（{totals['invoice_count']}张）。")
            if totals and name=='list_bank_transactions' and 'amount_rule' in outcome['evidence']:
                parts.append(f"本轮银行收入 {totals['bank_income_total']} 元（{totals['bank_income_count']}条）；"
                             f"银行支出 {totals['bank_expense_total']} 元（{totals['bank_expense_count']}条）。")
                add_scope({**outcome['evidence'], 'rule': outcome['evidence']['amount_rule']})
        if outcome["status"] == "NO_DATA":
            parts.append("没有匹配记录；这不是权限拒绝。")
        if outcome["status"] == "NO_CHANGE":
            parts.append("未发生更改：" + (outcome.get("error") or "当前状态无需改变"))
    progress = verified_task_progress(results)
    if progress:
        add_scope(progress["evidence"])
        parts.append(render_task_progress(progress, include_scope=False))
    elif needs_progress_evidence(results):
        parts.append("本轮无法核实同一任务与缺失用途的完整进度，请明确待办范围后核对。")
    receipt=preference_receipt(results)
    if receipt:parts.append(receipt)
    return "\n".join(parts) if parts else "该模型信息尚未核实；没有本轮可核验查询证据，也没有提交成功依据。"


def preference_receipt(results):
    """本轮具体确认写入与后续真实get/list核对分开，不采信模型完成声明。"""
    writes={}
    for name,outcome in results:
        if name!='manage_preference':continue
        evidence=outcome.get('evidence',{});operation=evidence.get('operation',{})
        data=outcome.get('data');action=operation.get('action')
        if outcome['status']=='SUCCESS' and evidence.get('management_confirmation') and action in {'create','update'} and isinstance(data,dict):
            key=(data.get('user_id'),data.get('company_id'),data.get('preference_key'))
            writes[key]={'value':data.get('value'),'verified':False}
        elif outcome['status']=='SUCCESS' and action in {'get','list'}:
            rows=data if isinstance(data,list) else [data]
            for row in rows:
                if not isinstance(row,dict):continue
                key=(row.get('user_id'),row.get('company_id'),row.get('preference_key'))
                if key in writes:writes[key]['verified']=row.get('value')==writes[key]['value']
    if not writes:return ''
    if all(value['verified'] for value in writes.values()):
        return '可信管理回执：具体确认后的偏好保存及后续读取核对完成；仅复用本轮真实执行证据，不代表新增查询或发票Commit。'
    return '可信管理回执：偏好已按具体确认保存；尚未取得所有保存目标的后续独立读取核对证据，不能声称核对完成。'


def render_stopped(results, stop_reason):
    """失败不能回滚此前真实结果；也不展示拒绝项的业务data。"""
    verified=[(name,outcome) for name,outcome in results
              if outcome['status'] in {'SUCCESS','NO_DATA','NO_CHANGE'} and name!='prepare_invoice_update']
    if not verified:
        return None
    failures=[]
    for index,(name,outcome) in enumerate(results):
        if outcome['status'] in {'SUCCESS','NO_DATA','NO_CHANGE'}:continue
        key=outcome.get('evidence',{}).get('operation',{}).get('key')
        company=outcome.get('evidence',{}).get('scope',{}).get('company_id')
        resolved=(name=='manage_preference' and outcome['status']=='NOT_FOUND' and key and any(
            n=='manage_preference' and r['status']=='SUCCESS' and r.get('evidence',{}).get('management_confirmation')
            and r.get('evidence',{}).get('scope',{}).get('company_id')==company
            and r.get('evidence',{}).get('operation',{}).get('key')==key for n,r in results[index+1:]))
        if not resolved:failures.append({'tool':name,'status':outcome['status']})
    reason={'MODEL_LIMIT':'模型请求上限','TOOL_LIMIT':'实际工具调用上限','CONTEXT_LIMIT':'上下文上限',
            'WAITING_CONFIRMATION':'等待可信确认，尚未保存'}.get(stop_reason,'按真实执行状态停止')
    return ('本轮已核实结果（仅代表各项实际执行时的事实）：\n'+render_information(verified)
            +'\n本轮停止原因：'+stop_reason+'（'+reason+'）。后续调用或模型答复已停止；这不撤销以上已完成结果，目标核对情况以可信回执为准。'
            +'\n未完成/拒绝项：'+json.dumps(failures,ensure_ascii=False))


def render_task_progress(outcome, *, include_scope=True):
    """从当前任务检查证据展示剩余事项，不宣告任务完成或写入新值。"""
    if outcome['status']!='SUCCESS':
        return '当前任务进度：'+outcome['status']+'；'+(outcome.get('error') or '无法核实剩余事项')
    task,check=outcome['data']['task'],outcome['data']['check']
    scope = render_scope(outcome["evidence"]) + "\n" if include_scope else ""
    return (scope+f"任务 {task['task_id']} 状态仍为 {task['status']}；当前剩余 {check['count']} 张必填用途缺失。"
            +'\n当前剩余对象：'+json.dumps(check['missing_invoices'],ensure_ascii=False)
            +'\n下一步：核对剩余对象并明确提供用途，经Prepare、可信确认和Commit逐张保存；全部补齐后仍须单独核对并确认任务完成。')


def render_clarification(value):
    """保留模型选择的缺失信息，自然提问；不展示任意状态性自由文本。"""
    labels = {"company_id":"企业", "invoice_no":"发票编号", "field":"要修改的字段（用途或备注）",
              "new_value":"修改后的具体内容", "year":"年份", "month":"月份",
              "action":"具体管理动作", "task_id":"任务编号", "note":"待办的具体说明",
              "key":"偏好名称", "value":"偏好的具体内容"}
    fields = list(dict.fromkeys(value["missing_fields"]))
    if fields == ["business_object"]:
        return "请确认您想查银行收入流水还是发票？"
    labels["business_object"] = "查询对象（银行收入流水或发票）"
    # 追问信封不授予字段/写入权限；未知标签与任意模型text均不直接展示。
    questions=[labels[field] for field in fields if field in labels]
    if any(field not in labels for field in fields):
        questions.append("本次请求的具体对象、操作和内容（无法确定所缺信息）")
    return "请提供" + "和".join(questions)


def render_tool_failure(status, tool=None, outcome=None):
    """User-facing guidance; diagnostic codes and provider details stay in Trace."""
    if status == "CONFLICT" and tool == "manage_task" and ((outcome or {}).get("data") or {}).get("existing_task_id"):
        return "该企业已有未完成待办，本次未创建。可打开待办列表查看或继续原待办。"
    if status == "INVALID_ARGUMENTS" and tool == "check_missing_purpose":
        return "当前用途合规检查仅支持2026年9月。本轮未完成检查；请明确企业并选择该月，或改查指定年度的用途字段空值。空值查询不代表合规判断。"
    return {
        "DENIED": "当前账号没有执行这项操作的权限，已停止。请使用有相应权限的账号。",
        "SCOPE_MISMATCH": "查询参数与您确认的范围不一致，已停止。请明确企业、年份和月份，或明确完整年度后重试。",
        "INVALID_ARGUMENTS": "本次操作的参数不完整或不适用，已停止。请明确查询对象和范围；修改时还需说明字段和新内容。",
        "UNKNOWN_OUTCOME": "提交结果未知，请先检查本次操作的审计与当前记录，不要直接重复提交。",
        "SCHEDULE_MISMATCH": "本轮步骤与已确认的执行顺序不一致，已停止；尚未执行剩余步骤。",
        "CANCELLED": "已取消本次操作，没有保存本次候选内容。",
        "WAITING_CONFIRMATION": "请核对具体对象和内容，确认后才会保存。",
        "NOT_FOUND": "在当前权限和范围内未找到目标，请核对编号或重新查询列表。",
        "CONFLICT": "当前记录与本次操作冲突，请重新读取并核对后再操作。",
        "NO_PROGRESS": "本轮没有取得新的结果，已停止重复操作。请补充或更正查询条件。",
    }.get(status, "本轮操作未能继续，请核对查询对象和范围后重试；已核验结果仍按实际执行情况保留。")
