"""模型信息与权威操作状态分开；不尝试用关键词判断任意文本真假。"""
import json
import re
from decimal import Decimal, InvalidOperation

from .queries import INVOICE_FIELD_LABELS


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


def render_explanation_evidence(facts):
    if "annual_blank_purpose" in facts:
        data = facts["annual_blank_purpose"]
        when = "上一轮查询" if data["historical"] else "本轮查询"
        year, month = data["compliance_period"]
        text = (f"{when}已核验：{data['company_id']} {data['year']} 年用途为空的发票共 {data['total']} 张。\n"
                f"字段为空本身不足以认定违规。当前支持的用途合规检查账期为 {year} 年 {month} 月。")
        if data["rule"]:
            text += f"该企业在该账期的依据为 {data['rule']['id']} v{data['rule']['version']}。"
        return text
    if "bank_invoice_link" in facts:
        return ("已核验的银行收入不能单独证明本期发票已全部回款。"
                "当前账簿没有可靠的发票与银行流水逐笔关联，无法据此确认具体发票是否已付款。")
    return ""


def render_grounded_explanation(text, facts, user_text=""):
    """Check cited business literals and keep the verified evidence separate from model prose."""
    evidence = render_explanation_evidence(facts)
    if not evidence:
        return None
    token = r"\[\[([a-z_]+)\]\]"
    annual = facts.get("annual_blank_purpose")
    if annual:
        rule = annual["rule"]
        citation = f"{rule['id']} v{rule['version']}" if rule else "未取得唯一适用规则"
        slots = {"result": str(annual["total"]), "boundary": citation}
        if set(re.findall(token, text)) - slots.keys():
            return None
        prose = re.sub(token, "", text)
        year, month = annual["compliance_period"]
        allowed_years = {annual["year"], year}
        claimed_scope = explicit_scope(prose, include_update_aliases=True)
        if (set(claimed_scope.get("company_id", ())) - {annual["company_id"]}
                or set(claimed_scope.get("year", ())) - allowed_years
                or set(claimed_scope.get("month", ())) - {month}
                or set(claimed_scope.get("periods", ())) - {(year, month)}):
            return None
        if rule:
            prose = re.sub(rf"(?<![A-Za-z0-9]){re.escape(rule['id'])}\s*v?\s*{re.escape(rule['version'])}(?![\d.])",
                           "", prose, flags=re.IGNORECASE)
        verified_years = "|".join(str(value) for value in sorted(allowed_years))
        prose = re.sub(rf"(?<![A-Za-z0-9]){re.escape(annual['company_id'])}(?![A-Za-z0-9])|"
                       rf"(?<!\d)(?:{verified_years})\s*年|(?<!\d){month:02d}\s*月|(?<!\d){month}\s*月",
                       "", prose, flags=re.IGNORECASE)
        counts = r"(?<![\d.,])(\d{1,9})\s*张"
        quoted = {int(match) for match in re.findall(counts, user_text)}
        for match in re.finditer(counts, prose):
            count = int(match[1])
            if count == annual["total"]:
                continue
            lead = prose[:match.start()]
            tail = prose[match.end():]
            attributed = (re.search(r"(?:你|您)(?:所)?(?:说|提到|引用)(?:的)?\s*[“「]?$|(?:而非|并非|不是)\s*[“「]?$", lead)
                          or re.match(r"\s*[”」]?\s*(?:是|为)(?:你|您)(?:所)?(?:说|提到|引用)", tail))
            if count not in quoted or not attributed:
                return None
        prose = re.sub(counts, "", prose)
        rendered = re.sub(token, lambda match: slots[match[1]], text)
    else:
        # Interpret the explanation request without promoting the model's amounts or payment claims.
        markers = re.findall(token, text)
        if markers not in ([], ["boundary"]):
            return None
        prose = re.sub(token, "", text)
        if markers and not prose.strip(" 。！!，,；;\n\t"):
            return evidence
        if (not re.search(r"银行|流水|进账", prose)
                or not re.search(r"发票|回款|收款", prose)
                or not re.search(r"不能|无法|不足以|不意味|不代表|不等于|没有可靠|缺乏|缺少", prose)):
            return None
        return evidence
    if (not prose.strip() or re.search(
            r"[\d¥￥$\[\]]|[零〇一二两三四五六七八九十百千万亿]+\s*(?:张|条|元|分|年|月)|"
            r"金额|人民币|已(?:经)?(?:保存|提交|修改|付款|支付|确认|授权)|成功(?:保存|提交|修改)", prose)):
        return None
    return rendered + "\n\n" + evidence


def explicit_scope(text, include_update_aliases=False):
    """仅提取用户明确的编号与数字日期字面量，不做业务意图关键词路由。"""
    companies = sorted(set(re.findall(r"(?<![A-Za-z0-9])C\d+(?![A-Za-z0-9])",text,flags=re.IGNORECASE)))
    invoices = re.findall(r"(?<![A-Za-z0-9])F\d+(?![A-Za-z0-9])",text,flags=re.IGNORECASE)
    if include_update_aliases:
        # Only official company identifiers and their explicit aliases.
        companies += [company for alias, company in (("甲", "C001"), ("乙", "C002"))
                      if re.search(rf"{alias}(?:企业|公司)", text)]
        if re.search(r"甲\s*(?:[、和与及]\s*)?乙\s*(?:两家(?:公司|企业)?|两(?:公司|企业)|公司|企业)", text):
            companies.extend(("C001", "C002"))
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


QUERY_GOALS = {
    "finance": ("发票和银行收支汇总", {"get_finance_summary"}),
    "bank_income": ("银行收入", {"get_finance_summary", "list_bank_transactions"}),
    "directory": ("发票目录", {"list_invoice_directory"}),
    "purpose_rule": ("用途必填规则", {"get_applicable_rules"}),
}


def query_goal(text):
    """Recognize only the read goals for which composite coverage is verifiable."""
    if "用途" in text and re.search(r"必填|必须填写|规则|要求", text):
        return "purpose_rule"
    if "发票" in text and re.search(r"列出|目录|清单|全部|所有", text):
        return "directory"
    if "发票" in text and re.search(r"银行|收支", text):
        return "finance"
    if re.search(r"银行.{0,8}(?:收入|进账)|(?:银行进账|银行入账)", text):
        return "bank_income"
    if re.search(r"收支|综合金额|财务汇总", text):
        return "finance"
    return None


def verified_query_goal(goal, company, year, month, results):
    for name, outcome in results:
        evidence = outcome["evidence"]
        scope = evidence.get("scope", {})
        if (name not in QUERY_GOALS[goal][1] or outcome["status"] not in {"SUCCESS", "NO_DATA"}
                or evidence.get("source") != "current_sqlite"
                or (scope.get("company_id"), scope.get("year"), scope.get("month")) != (company, year, month)):
            continue
        if goal == "purpose_rule" and scope.get("rule_type") != "purpose":
            continue
        if goal == "directory" and outcome["data"]["page"] != 1:
            continue
        return True
    return False


def render_bank_income_comparison(results, goals):
    """Compare only two verified, independent, same-period SQLite bank totals."""
    targets = {(company, year, month) for goal, company, year, month in goals
               if goal == "bank_income"}
    if len(targets) != 2 or len({(year, month) for _, year, month in targets}) != 1:
        return "银行进账金额比较未完成：请明确两家企业的同一账期。", False
    amounts = {}
    for name, outcome in results:
        evidence = outcome.get("evidence", {})
        scope = evidence.get("scope", {})
        target = (scope.get("company_id"), scope.get("year"), scope.get("month"))
        if (target not in targets or outcome["status"] not in {"SUCCESS", "NO_DATA"}
                or evidence.get("source") != "current_sqlite"):
            continue
        summary = (outcome.get("data") if name == "get_finance_summary" else
                   evidence.get("finance_summary") if name == "list_bank_transactions" else None)
        if not isinstance(summary, dict):
            continue
        try:
            amount = Decimal(str(summary["bank_income_total"]))
            if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")):
                continue
        except (KeyError, InvalidOperation, TypeError, ValueError):
            continue
        amounts[target] = amount
    missing = sorted(target[0] for target in targets if target not in amounts)
    if missing:
        return "还无法比较银行收入。缺少 " + "、".join(missing) + " 同一账期的收入总额。", False
    (left, right) = sorted(targets)
    a, b = amounts[left], amounts[right]
    year, month = left[1:]
    first = f"{left[0]}：¥{a:,.2f}"
    second = f"{right[0]}：¥{b:,.2f}"
    if a == b:
        conclusion = "两家银行收入相同，差额 ¥0.00。"
    else:
        higher = left[0] if a > b else right[0]
        conclusion = f"{higher} 银行收入更多，相差 ¥{abs(a-b):,.2f}。"
    return f"{year} 年 {month} 月，{conclusion}{first}，{second}。", True


def render_hypothetical_purpose_rules(results, request, goals):
    """Answer only literal same-turn invoice-amount hypotheticals from rule params."""
    if not (re.search(r"发票|单据", request) and
            re.search(r"没填用途|未填用途|用途为空|用途还空|用途没填", request)):
        return ""
    company_pattern = r"甲(?:企业|公司)|乙(?:企业|公司)|(?<![A-Za-z0-9])C00[12](?![A-Za-z0-9])"
    amount_pattern = r"(?<![\d.,+\-])(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]{1,2})?"
    fragments = re.findall(rf"({company_pattern})(?:(?!(?:{company_pattern})).){{0,85}}?"
                           rf"({amount_pattern})\s*元", request, flags=re.I)
    if not fragments:
        return ""
    aliases = {"甲企业": "C001", "甲公司": "C001", "乙企业": "C002", "乙公司": "C002",
               "C001": "C001", "C002": "C002"}
    fragments = [(aliases[company.upper()], literal.replace(",", "")) for company, literal in fragments]
    targets = {(company, year, month) for goal, company, year, month in goals if goal == "purpose_rule"}
    if len({company for company, _ in fragments}) != len(fragments):
        return "假设金额不能唯一对应企业，请分别注明每家企业的金额。"
    if not targets or any((company, 2026, 9) not in targets for company, _ in fragments):
        return "无法判断这笔假设发票：请明确企业及 2026 年 9 月的适用规则范围。"
    rules = {}
    for name, outcome in results:
        scope = outcome.get("evidence", {}).get("scope", {})
        key = (scope.get("company_id"), scope.get("year"), scope.get("month"))
        if (name == "get_applicable_rules" and outcome["status"] == "SUCCESS"
                and outcome["evidence"].get("source") == "current_sqlite"
                and scope.get("rule_type") == "purpose" and key in targets):
            rules[key] = outcome["data"]
    statements = []
    for company, literal in fragments:
        alias = "甲" if company == "C001" else "乙"
        rule = rules.get((company, 2026, 9))
        if not rule:
            statements.append(f"{alias}企业的适用规则尚未核验，不能判断假设金额是否违反必填要求。")
            continue
        try:
            cents = Decimal(literal) * 100
            if cents != cents.to_integral_value() or cents < 0:
                return ""
            params = rule["params"]
            mode, threshold = params["mode"], params["threshold_cents"]
            if (mode not in {"all", "threshold"} or type(threshold) is not int or threshold < 0):
                raise ValueError("unsupported rule")
            required = mode == "all" or cents >= threshold
        except (KeyError, ValueError, InvalidOperation, TypeError):
            statements.append(f"{alias}企业的规则结构不足以判定该假设，请核对执行参数。")
            continue
        status = ("未填用途违反该企业必填规则" if required else
                  "此金额未触发该企业用途必填门槛，单就未填用途而言不违反该规则")
        statements.append(f"假设{alias}企业有一张金额 ¥{Decimal(literal):,.2f} 的发票且用途为空："
                          f"{status}（{rule['rule_id']} v{rule['version']}）。")
    return "以下仅判断假设情形，不表示数据库中存在这些发票：\n" + "\n".join(statements)


def render_goal_coverage(coverage, receipt):
    labels = {"VERIFIED": "查询已核验", "UNEXECUTED": "尚未执行", "DENIED": "读取被拒绝",
              "SCOPE_MISMATCH": "查询范围冲突", "FAILED": "未取得可信结果"}
    parts = [f"{company} · {QUERY_GOALS[goal][0]}：{labels[state]}。"
             for goal, company, state in coverage["reads"]]
    if coverage["deferred"]:
        parts.append("目录中的序数引用尚未执行。请在目录展示后下一轮提出。")
    if coverage["write"]:
        status = receipt["status"]
        if status == "NOT_SUBMITTED":
            parts.append("发票修改尚未执行。")
        elif status == "COMMITTED" and not receipt.get("readback_verified"):
            parts.append("发票修改的回读尚未核实。")
        else:
            parts.append(receipt["message"])
    if coverage["unknown"]:
        parts.append("本轮无法核定全部查询目标的覆盖情况。")
    if any(goal == "purpose_rule" and state == "VERIFIED" for goal, _, state in coverage["reads"]):
        parts.append("这里核验的是必填规则。缺项清单与全部必填对象的清单含义不同。")
    return "\n".join(parts)


def scope_mismatch(expected, actual):
    """只比较双方都有明确字段的范围，不猜测中文别名或跨轮指代。"""
    if "periods" in expected and "year" in actual and "month" in actual:
        if (actual["year"], actual["month"]) not in expected["periods"]:
            return True
    return any(key in actual and actual[key] not in values for key,values in expected.items())


def scope_key(evidence):
    scope = evidence.get("scope", {})
    if "company_ids" in scope:
        return (tuple(scope["company_ids"]), tuple(map(tuple, scope.get("periods", ()))),
                scope.get("year"), evidence.get("source"))
    rule = evidence.get("rule") or {}
    period = (scope["year"], scope.get("month")) if "year" in scope else scope.get("business_date")
    return (scope.get("company_id"), period, evidence.get("source"),
            rule.get("rule_id") or rule.get("id"), rule.get("version"), rule.get("name"), evidence.get("rule_status"),
            scope.get("rule_business_date"))


def render_scope(evidence, *, conversational=False):
    scope = evidence.get("scope",{})
    if "company_ids" in scope:
        companies = "、".join(scope["company_ids"])
        periods = ("、".join(f"{year:04d}-{month:02d}" for year, month in scope["periods"])
                   if "periods" in scope else f"{scope['year']} 年")
        return f"企业 {companies} · {periods}（当前账簿 SQL 快照）"
    company = scope.get("company_id","未限定")
    if "year" in scope and "month" in scope:
        period = f"{scope['year']:04d}-{scope['month']:02d}"
    elif "year" in scope:
        period = f"{scope['year']} 年"
    else:
        period = scope.get("business_date","未按年月限定")
    rule = evidence.get("rule")
    rule_text = f"{rule.get('rule_id',rule.get('id',''))} {rule['name']} v{rule['version']}" if rule else evidence.get("rule_status","不适用（无财税规则判定）")
    if evidence.get("reference_rule_screening"):
        return (f"企业 {company} · 目标账期 {period} · 参考日期 {scope['rule_business_date']} · {rule_text}。"
                "按参考规则重新筛选，不代表目标月份正式合规认定。")
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


def render_reference_error(status, evidence=None):
    if status == "OUT_OF_RANGE":
        reference = (evidence or {}).get("reference", {})
        ordinal, count = reference.get("ordinal"), reference.get("count")
        if type(ordinal) is int and type(count) is int and count > 0:
            choices = "第 1 张" if count == 1 else f"第 1～{count} 张"
            return f"刚才的列表共 {count} 张发票，不存在第 {ordinal} 张。请选择{choices}，或直接提供发票编号。"
        return "该序号超出刚才展示的范围。请从列表中选择，或直接提供发票编号。"
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
        elif name == "check_missing_purpose" and not evidence.get("reference_rule_screening"):
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
    return (any(name == "check_missing_purpose" and not outcome.get("evidence", {}).get("reference_rule_screening")
                for name, outcome in results)
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
    parts.append("用途待办仅支持2026年9月。本轮尚未创建待办。")
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


DIRECTORY_SORT_LABELS = {
    ("date", "asc"): "按日期从早到晚排序",
    ("date", "desc"): "按日期从晚到早排序",
    ("amount", "asc"): "按金额从低到高排序",
    ("amount", "desc"): "按金额从高到低排序",
}


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


def render_recent_commit(evidence):
    audit = evidence.get("historical_commit")
    if not audit:
        return ""
    field = {"purpose": "用途", "remark": "备注"}[audit["field"]]
    result = ("当前字段与当时提交值一致。" if audit["current_matches"] else "当前字段不再与当时提交值一致，或发票已不可读取。")
    return f"历史操作：{field}修改已提交，审计已重新核验（{audit['request_id']}）。{result}"


def render_invoice_comparison(previous, current):
    labels = {"invoice_date": "开票日期", "seller_name": "销售方", "item_name": "项目",
              "amount": "价税合计", "purpose": "用途", "remark": "备注"}
    first = f"{previous['company_id']}/{previous['invoice_no']}"
    second = f"{current['company_id']}/{current['invoice_no']}"
    differences = [f"{label}：{previous[key] or '（空）'} → {current[key] or '（空）'}"
                   for key, label in labels.items() if previous[key] != current[key]]
    return f"已重新读取 {first} 与 {second}。\n" + ("\n".join(differences) or "所列发票字段一致。")


def render_invoice_field_count(data):
    return f"{INVOICE_FIELD_LABELS[data['selector']]}的发票共 {data['count']} 张。"


def render_sql_evidence(data):
    columns = data["columns"]
    lines = ["SQL", data["sql"], "列 " + " · ".join(columns)]
    for row, derived in zip(data["rows"], data["derived"]):
        amount = [f"{columns[int(key)]} = ¥{value}" for key, value in derived.items() if key != "percentage"]
        if "percentage" in derived:
            amount.append(f"比例 = {derived['percentage']}" if derived["percentage"] is not None else "比例无法计算（分母为零）")
        suffix = ("　" + "；".join(amount)) if amount else ""
        lines.append(json.dumps(row, ensure_ascii=False) + suffix)
    if data["truncated"]:
        lines.append(f"仅显示前 {data['row_count']} 行，后续结果未展示。该行数不代表总数。")
    else:
        lines.append(f"返回 {data['row_count']} 行。")
    return "\n".join(lines)


def render_query_conclusion(results):
    """Summarize verified reads without copying the detail pane or guessing coverage."""
    lines = []
    for name, outcome in results:
        evidence = outcome["evidence"]
        if evidence.get("source") != "current_sqlite" or outcome["status"] not in {"SUCCESS", "NO_DATA"}:
            continue
        data, scope = outcome["data"], evidence.get("scope", {})
        companies = scope.get("company_ids") or ([scope["company_id"]] if scope.get("company_id") else [])
        periods = scope.get("periods")
        if periods:
            period = "、".join(f"{year:04d}-{month:02d}" for year, month in periods)
        elif scope.get("business_date"):
            period = scope["business_date"]
        elif scope.get("year"):
            period = (f"{scope['year']:04d}-{scope['month']:02d}" if scope.get("month") else f"{scope['year']} 年")
        else:
            period = ""
        heading = " ".join(filter(None, ("、".join(companies), period)))
        if name in {"get_finance_summary", "get_annual_finance_summary"}:
            rule = evidence.get("rule") or {}
            rule_id = rule.get("rule_id") or rule.get("id")
            basis = f"（{rule_id} v{rule['version']}）" if rule_id and rule.get("version") else ""
            detail = (f"发票价税合计 {data['invoice_total']} 元，银行收入 {data['bank_income_total']} 元，"
                      f"支出 {data['bank_expense_total']} 元{basis}。")
            if outcome["status"] == "NO_DATA":
                detail = "该账期没有发票或银行流水。" + detail
        elif name == "count_invoice_fields":
            detail = render_invoice_field_count(data)
            rule = evidence.get("rule")
            if rule:
                detail = f"按 {rule['rule_id']} v{rule['version']} 检查，" + detail
        elif name == "list_annual_blank_purpose":
            detail = f"查到 {data['total']} 张用途为空的发票。空值本身不足以判定违规。"
        elif name == "check_missing_purpose":
            rule = data["rule"]
            basis = f"{rule['rule_id']} v{rule['version']}"
            if data.get("reference_rule_screening"):
                detail = (f"按 {data['rule_business_date']} 的 {basis} 筛出 {data['count']} 张必填用途缺失的发票。"
                          "这是按参考规则筛选的结果。")
            else:
                detail = f"按 {basis} 检查，有 {data['count']} 张发票缺少必填用途。"
        elif name in {"get_invoice", "resolve_invoice_reference"} and data:
            purpose = data["purpose"] or "未填写"
            remark = data["remark"] or "无"
            detail = f"{data['invoice_no']} 的用途是{purpose}，备注为{remark}。"
        elif name == "get_applicable_rules":
            detail = f"适用 {data['rule_id']} v{data['version']}。{display_rule_amounts(data['content'])}"
        elif name == "query_business_sql":
            if outcome["status"] == "NO_DATA":
                detail = "本次筛选没有匹配的记录。"
            elif data["truncated"]:
                detail = f"本次筛选显示了 {data['row_count']} 行，总数尚未核实。"
            else:
                detail = f"本次筛选返回 {data['row_count']} 行，明细见业务记录。"
                columns = data["columns"]
                # Only summarize SQL cells when all dimensions and values fit in the reply.
                if 1 <= data["row_count"] <= 2 and all(
                    column.endswith("_cents") or column in {"company_id", "numerator", "denominator"}
                    for column in columns
                ):
                    values = []
                    for row, derived in zip(data["rows"], data["derived"]):
                        cells = [f"{column.removesuffix('_cents')} {derived[str(i)]} 元"
                                 if str(i) in derived else f"{column} {row[i]}"
                                 for i, column in enumerate(columns)]
                        if "percentage" in derived:
                            cells.append(f"比例 {derived['percentage']}" if derived["percentage"] is not None
                                         else "比例无法计算（分母为零）")
                        values.append("，".join(cells))
                    detail = "按本次筛选，" + "；".join(values) + "。"
        elif name == "list_invoice_directory":
            order = DIRECTORY_SORT_LABELS[(data.get("sort_by", "date"), data.get("sort_order", "asc"))]
            kind = "发票目录" if period else "全部账期的发票目录"
            detail = f"{kind}共 {data['total']} 张，{order}。"
        elif name in {"list_invoices", "list_bank_transactions", "list_tasks"}:
            item = {"list_invoices": "张发票", "list_bank_transactions": "条银行流水", "list_tasks": "项待办"}[name]
            detail = f"查到 {len(data)} {item}，明细见业务记录。"
        elif name == "list_annual_bank_income":
            detail = f"查到 {data['total']} 条银行收入流水，明细见业务记录。"
        else:
            detail = ("没有匹配的记录。" if outcome["status"] == "NO_DATA"
                      else "查询结果见业务记录。")
        line = f"{heading}：{detail}" if heading else detail
        if line not in lines:
            lines.append(line)
    return "\n".join(lines)


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
        elif name == "resolve_recent_invoice":
            history = render_recent_commit(outcome["evidence"])
            if history:
                parts.append(history)
            if data:
                parts.append("当前 SQLite 发票：" + json.dumps(data, ensure_ascii=False))
        elif name == "list_invoice_directory":
            order = (data.get("sort_by", "date"), data.get("sort_order", "asc"))
            parts.append(f"发票目录 · {DIRECTORY_SORT_LABELS[order]} · 共 {data['total']} 张 · "
                         f"第 {data['page']} 页 · 每页 {data['page_size']} 张。")
            parts.append(json.dumps(data["rows"], ensure_ascii=False))
        elif name == "query_business_sql":
            parts.append(render_sql_evidence(data))
        elif name == "count_invoice_fields":
            parts.append(render_invoice_field_count(data))
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
              if outcome['status'] in {'SUCCESS','NO_DATA','NO_CHANGE'} and name!='prepare_invoice_update'
              and outcome.get('evidence', {}).get('source') in {'current_sqlite', 'local_display_preference'}]
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
              "target_period":"要修改的发票目标年月，如引用其他月份规则请单独注明参考年月",
              "action":"具体管理动作", "task_id":"任务编号", "note":"待办的具体说明",
              "invoice_reference":"要看的发票来源（刚查过、已修改或目录序号）",
              "key":"偏好名称", "value":"偏好的具体内容"}
    fields = list(dict.fromkeys(value["missing_fields"]))
    if fields == ["business_object"]:
        return "请确认您想查银行收入流水还是发票？"
    labels["business_object"] = "查询对象（银行收入流水或发票）"
    # 追问信封不授予字段/写入权限；未知标签与任意模型text均不直接展示。
    questions=[labels[field] for field in fields if field in labels]
    if any(field not in labels for field in fields):
        questions.append("要处理的对象和具体要求")
    return "请补充" + "、".join(questions) + "。"


def render_tool_failure(status, tool=None, outcome=None):
    """User-facing guidance; diagnostic codes and provider details stay in Trace."""
    if tool == "query_business_sql" and status in {"SQL_SCOPE_LIMIT", "SQL_QUERY_LIMIT", "SQL_REJECTED", "SCOPE_MISMATCH"}:
        return outcome["error"] + "。"
    if status == "CONFLICT" and tool == "manage_task" and ((outcome or {}).get("data") or {}).get("existing_task_id"):
        return "该企业已有未完成待办，本次未创建。可打开待办列表查看或继续原待办。"
    if tool == "check_missing_purpose" and status in {"INVALID_ARGUMENTS", "NO_APPLICABLE_RULE", "RULE_CONFLICT"}:
        return {
            "INVALID_ARGUMENTS": "用途缺项查询参数不适用，请核对企业、目标年月和参考规则日期。",
            "NO_APPLICABLE_RULE": "指定日期没有适用的用途规则，无法判定缺项。",
            "RULE_CONFLICT": "指定日期无法确定唯一有效的用途规则，本轮未判定缺项。",
        }[status]
    return {
        "DENIED": "当前账号没有权限执行这项操作。",
        "SCOPE_MISMATCH": "查询范围与已确认的范围不一致，请核对企业和账期。",
        "INVALID_ARGUMENTS": "本次操作的参数不完整或不适用，已停止。请明确查询对象和范围；修改时还需说明字段和新内容。",
        "RULE_CONFLICT": "无法确定唯一有效的规则，暂不能按规则判定。",
        "NO_APPLICABLE_RULE": "指定日期没有适用规则。",
        "UNKNOWN_OUTCOME": "提交结果未知，请先检查本次操作的审计与当前记录，不要直接重复提交。",
        "SCHEDULE_MISMATCH": "本轮步骤与已确认的执行顺序不一致，已停止；尚未执行剩余步骤。",
        "CANCELLED": "已取消本次操作，没有保存本次候选内容。",
        "WAITING_CONFIRMATION": "请核对具体对象和内容，确认后才会保存。",
        "NOT_FOUND": "在当前权限和范围内未找到目标，请核对编号或重新查询列表。",
        "CONFLICT": "当前记录与本次操作冲突，请重新读取并核对后再操作。",
        "NO_PROGRESS": "没有新的查询进展，已停止。",
    }.get(status, "这项操作未能继续，具体原因可查看执行记录。")
