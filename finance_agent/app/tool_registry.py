"""工具声明、严格参数校验与受控分发。"""
import json
import re
from uuid import uuid4
from pathlib import Path
import sqlite3
from dataclasses import asdict
from datetime import date
from . import finance, queries
from .permissions import check_permission
from .updates import inspect_request, prepare_invoice_update
from .stage2_schema import open_existing
from .rules import resolve_rule, check_missing_purpose, RuleError
from .responses import scope_mismatch, explicit_scope
from .tasks import list_tasks, manage_task
from .preferences import manage_preference
from .references import resolve_reference
from .persistence import can_manage, can_propose, confirm_management, ManagementIntent, ManagementCandidate, ManagementProposals, task_note_from_request
from contextlib import closing
from copy import deepcopy
from .provenance import ANNUAL, MONTHLY, ScopeProof, is_annual_query, validate_scope
from .business_sql import BusinessSQLError

YEAR = {"company_id": "string", "year": "integer"}
MONTH = {**YEAR, "month": "integer"}
DIRECTORY_SORT_FIELDS = {"sort_by": ("date", "amount"), "sort_order": ("asc", "desc")}
OPTIONAL_FIELDS = {"list_invoice_directory": DIRECTORY_SORT_FIELDS.keys()}
REGISTRY = {
    "query_business_sql": (None, {"sql": "string"}),
    "list_invoices": (queries.list_invoices, MONTH),
    "list_invoice_directory": (queries.invoice_directory, {**MONTH, "page": "integer", "sort_by": "string", "sort_order": "string"}),
    "get_invoice": (queries.get_invoice, {"company_id": "string", "invoice_no": "string"}),
    "list_bank_transactions": (queries.list_bank_transactions, MONTH),
    "invoice_total": (finance.invoice_total, MONTH),
    "bank_income_total": (finance.bank_income_total, MONTH),
    "bank_expense_total": (finance.bank_expense_total, MONTH),
    "summary": (None, MONTH),
    "get_finance_summary": (finance.get_finance_summary, MONTH),
    "check_missing_purpose": (check_missing_purpose, MONTH),
    "count_invoice_fields": (None, {**MONTH, "selector": "string"}),
    "get_annual_finance_summary": (finance.get_annual_finance_summary, YEAR),
    "list_annual_blank_purpose": (queries.list_annual_blank_purpose, {**YEAR, "page": "integer"}),
    "list_annual_bank_income": (queries.list_annual_bank_income, {**YEAR, "page": "integer"}),
    "get_applicable_rules": (None, {"company_id":"string", "rule_type":"string", "business_date":"string"}),
    "list_rule_versions": (None, {"company_id": "string", "rule_id": "string"}),
    "prepare_invoice_update": (None, {"company_id":"string", "invoice_no":"string", "field":"string", "new_value":"string"}),
    "propose_invoice_changes": (None, {"selection_id":"string", "field":"string", "new_value":"string",
                                       "mode":"string", "excluded_invoice_ids":"array"}),
    "add": (None, {"a": "integer", "b": "integer"}),
    "list_tasks": (None, {"company_id":"string"}),
    "manage_task": (None, {"company_id":"string","action":"string","task_id":"string","year":"integer","month":"integer","note":"string"}),
    "manage_display_preference": (None, {"action":"string","value":"string"}),
    "manage_preference": (None, {"company_id":"string","action":"string","key":"string","value":"string"}),
    "resolve_invoice_reference": (None, {"company_id":"string","ordinal":"integer","anchor_id":"string"}),
    "resolve_recent_invoice": (None, {"source": "string"}),
    "set_schedule": (None, {"goal":"string","steps":"array","stop_condition":"string"}),
}
TOOLS = [{"type": "function", "function": {"name": name,
          "description": ("仅准备草稿，不保存；需可信CLI最终确认：" if name == "prepare_invoice_update" else "查询当前数据库：") + name,
          "parameters": {"type": "object", "properties": {key: {"type": kind} for key, kind in fields.items()},
                         "required": [key for key in fields if key not in OPTIONAL_FIELDS.get(name, ())], "additionalProperties": False}}}
         for name, (_, fields) in REGISTRY.items()]
TEACHING_TOOLS = TOOLS
TOOLS = [tool for tool in TOOLS if tool["function"]["name"] in ANNUAL | {
    "query_business_sql", "get_finance_summary", "list_invoices", "list_invoice_directory", "get_invoice", "list_bank_transactions",
    "check_missing_purpose", "count_invoice_fields", "get_applicable_rules", "list_rule_versions", "prepare_invoice_update",
    "list_tasks", "manage_task", "manage_preference", "manage_display_preference", "resolve_invoice_reference", "resolve_recent_invoice", "propose_invoice_changes", "set_schedule"}]
DESCRIPTIONS = {
    "query_business_sql":"普通只读业务分析首选。在按可信企业和账期隔离的账簿快照上执行单条 SELECT 或只读 WITH。支持筛选、分组、JOIN 和子查询。金额原值是整数分；is_blank(value) 检查 NULL、空串与纯空白。规则判定仍用规则工具。",
    "get_annual_finance_summary":"仅用于可信的完整年度，分别汇总发票、银行收入和银行支出。",
    "list_annual_blank_purpose":"仅用于可信的完整年度，按页列出用途字段为空的发票；不判定必填或合规。",
    "list_annual_bank_income":"按可信完整年度分页查询银行收入流水明细，每页10条；不判断对应发票。",
    "get_finance_summary":"发票和银行收支综合查询首选：一次返回指定企业年月的价税合计/张数、收入/支出总额/分别条数和R001版本；补充月份后沿用原综合目标。无记录明确返回零，无需额外计划。",
    "list_invoices":"查询指定企业月份的发票明细；大列表优先使用分页目录。",
    "list_invoice_directory":"按企业和账期重新读取、排序并分页，每页10条。年度用year及month=0；全账簿用year=0、month=0；月度传完整年月。未指定方向时升序，未指定字段时按日期。",
    "get_invoice":"企业编号和发票号联合定位当前发票，不猜测模糊指代。",
    "list_bank_transactions":"查询指定企业年月的银行流水，只读，不推断发票已付款。",
    "count_invoice_fields":"按明确企业及月份统计发票数量。可统计有备注、空备注、空用途或按有效规则必填用途缺失。普通空值与规则缺项是不同条件。",
    "check_missing_purpose":"用户问哪些发票按规则必填用途但仍缺失时，使用本工具。采用可信只读账期或当前明确范围，按有效规则返回实际缺项和发票编号；不要改为财务汇总。备注不代替用途。",
    "get_applicable_rules":"按企业、业务日期和规则类型获取唯一启用依据。R001对应amount，R002/R003对应purpose，R004对应bank。查询旧版是否仍适用也使用其规则类型，不用金额汇总规则替代用途门槛规则；不提供管理权限。",
    "prepare_invoice_update":"只生成用途/备注草稿，展示旧值，不保存；必须等待可信CLI最终确认。",
    "propose_invoice_changes":"对本轮可信 selection_id 提出一个字段的发票修改候选。新值必须是用户原话。整批确认用 batch，逐张或未指定用 item。excluded_invoice_ids 保留用户指定的全部排除编号，SQL 选取时也要排除。候选必须经可信界面授权，不能提交。",
    "list_rule_versions":"读取企业可见的规则历史版本与启停状态。问 R002 v1.0、旧版或版本区别时使用，无需月份；停用版本不能用于当前合规判断。",
    "list_tasks":"列出当前用户指定企业的持久任务，不创建或修改待办。",
    "manage_task":"为普通自然语言后续待办提出创建/更正/取消等候选，或查询任务；候选无写入权限，需可信CLI展示具体对象和内容并确认。恢复重查规则与发票，完成必须有业务证据；不能修改发票。",
    "manage_display_preference":"仅当前模拟账号的个人回复详细度；明确要求以后简洁或详细时用set，value为简洁、详细或普通；get/delete时value为空。保存需要独立可信确认。与企业偏好、权限和财务事实无关。",
    "manage_preference":"用户企业隔离的偏好CRUD；普通自然语言可提出create/update/delete候选，get/list只读。删除需明确key、value为空。所有写候选须可信CLI展示旧值/新值并确认，不能自行声称保存。",
    "resolve_invoice_reference":"仅解析用户本轮明确的第几张发票线索；必须有真实展示锚点，重新鉴权查库，无唯一对象则追问。不能自由猜序号。",
    "resolve_recent_invoice":"只读解析用户本轮语义明确指向的近期发票来源，并重新鉴权读取当前值。modified 指已核验的实际提交，queried 指已核验的详情查询。来源不明先追问。",
    "set_schedule":"仅真正多步依赖时提出本轮粗计划；不是长期任务或授权。再次调用为一次显式重规划，不创造进展或预算。简单查询直接调用业务工具。",
}
PARAMETERS = {"sql":"单条 SELECT 或只读 WITH 查询。严格遵守运行时给出的企业、账期与投影字段。",
              "company_id":"企业编号，例如C001；不能凭空猜测。", "year":"明确的业务年份。",
              "month":"业务月份，1到12。", "page":"目录页码，从1开始。",
              "selector":"要统计的发票字段条件。",
              "sort_by":"date 按日期，amount 按金额。", "sort_order":"asc 升序，desc 降序。", "invoice_no":"与企业共同确定发票的精确编号。",
              "field":"只允许purpose或remark。", "new_value":"用户明确的新内容，空字符串表示清空。",
              "rule_id":"规则编号，如R002。", "rule_type":"amount、purpose或bank。", "business_date":"YYYY-MM-DD业务日期。",
              "action":"该管理工具支持的操作名称。", "task_id":"已有任务ID；create使用空字符串。",
              "note":"用户明确的简短后续待办说明，优先保留原话；不扩写发票清单、规则解释或步骤计划；具体内容仍需可信确认，不接受模型声称完成作为证据。",
              "key":"偏好名称；list时为空。", "value":"用户明确的偏好内容；查询/删除时为空。",
              "source":"近期发票的可信来源，不能自行填企业、发票号或审计编号。",
              "selection_id":"本轮真实查询结果返回的 selection_id，不能猜测或复用历史引用。",
              "mode":"item 逐张确认，batch 整批确认。",
              "excluded_invoice_ids":"用户原话明确要求排除的发票编号，若无则为空数组。",
              "ordinal":"用户明确的展示序号，从1开始。", "anchor_id":"已展示anchor编号；唯一列表时可为空，不能自行编造。",
              "goal":"本轮用户目标描述，不是执行证据。","steps":"必要工具步骤及依赖，不拆分SQL/事务等内部操作。",
              "stop_condition":"目标证据齐全或等待用户/确认/拒绝时停止的描述；不能扩大运行时硬限。"}
for tool in TOOLS:
    tool["function"]["description"] = DESCRIPTIONS[tool["function"]["name"]]
    for key, schema in tool["function"]["parameters"]["properties"].items():
        schema["description"] = PARAMETERS[key]
        if tool["function"]["name"] == "list_invoice_directory" and key in {"year", "month"}:
            schema["description"] += " 年度目录只将月份设为0；全账簿目录年份和月份都设为0。"
for tool in TOOLS:
    if tool["function"]["name"] == "count_invoice_fields":
        selector = tool["function"]["parameters"]["properties"]["selector"]
        selector["enum"] = list(queries.INVOICE_FIELD_LABELS)
        selector["description"] = "；".join(f"{key}：{label}" for key, label in queries.INVOICE_FIELD_LABELS.items())
    if tool["function"]["name"] == "resolve_recent_invoice":
        tool["function"]["parameters"]["properties"]["source"]["enum"] = ["modified", "queried"]
    if tool["function"]["name"] == "list_invoice_directory":
        for key, choices in DIRECTORY_SORT_FIELDS.items():
            tool["function"]["parameters"]["properties"][key]["enum"] = list(choices)
    if tool["function"]["name"] == "prepare_invoice_update":
        tool["function"]["parameters"]["properties"]["field"]["enum"] = ["purpose", "remark"]
    if tool["function"]["name"] == "propose_invoice_changes":
        fields = tool["function"]["parameters"]["properties"]
        fields["field"]["enum"] = ["purpose", "remark"]
        fields["mode"]["enum"] = ["item", "batch"]
        fields["excluded_invoice_ids"]["items"] = {"type": "string"}
    if tool["function"]["name"] == "manage_task":
        tool["function"]["parameters"]["properties"]["action"]["enum"] = ["create","show","update","correct","wait","pause","resume","complete","cancel"]
    if tool["function"]["name"] == "manage_display_preference":
        tool["function"]["parameters"]["properties"]["action"]["enum"] = ["get","set","delete"]
    if tool["function"]["name"] == "manage_preference":
        tool["function"]["parameters"]["properties"]["action"]["enum"] = ["create","get","list","update","delete"]
    if tool["function"]["name"] == "set_schedule":
        tool["function"]["parameters"]["properties"]["steps"].update(minItems=1,maxItems=12,items={
            "type":"object","properties":{"step_id":{"type":"string"},"action":{"type":"string"},
                "arguments":{"type":"object","description":"已知工具参数约束，可留待前序结果补全，但不得猜测身份/确认。"},
                "depends_on":{"type":"array","items":{"type":"string"}}},
            "required":["step_id","action","arguments","depends_on"],"additionalProperties":False})
ARGUMENT_SCHEMAS = {tool["function"]["name"]:tool["function"]["parameters"]["properties"] for tool in TEACHING_TOOLS}
def tool_result(status, data=None, evidence=None, error=None):
    """所有工具共用成功、无数据、拒绝和错误协议。"""
    return {"ok": status in {"SUCCESS", "NO_DATA"}, "status": status,
            "data": data, "evidence": evidence or {}, "error": error}


def validate_arguments(name, raw_arguments, partial=False, *, directory_sort=None):
    """实际调用与计划约束共用JSON字段/类型检查；partial只允许计划暂缺业务参数。"""
    def unique_object(pairs):
        result = {}
        for key,value in pairs:
            if key in result:
                raise ValueError("JSON字段重复")
            result[key] = value
        return result
    try:
        args = json.loads(raw_arguments,object_pairs_hook=unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("非法JSON常量")))
        json.dumps(args, ensure_ascii=False).encode("utf-8")
    except (RecursionError, UnicodeEncodeError):
        raise ValueError("JSON参数嵌套过深或包含无效Unicode") from None
    fields = REGISTRY[name][1]
    required = set(fields) - set(OPTIONAL_FIELDS.get(name, ()))
    if type(args) is not dict or not set(args) <= set(fields) or (not partial and not required <= set(args)):
        raise ValueError("缺失或多余参数")
    for key,value in args.items():
        kind = fields[key]
        if type(value) is not {"integer":int,"string":str,"array":list}[kind]:
            raise ValueError("参数类型错误："+key)
        if kind=="string" and key not in {"new_value","task_id","note","key","value","anchor_id"} and not value.strip():
            raise ValueError("参数不能为空："+key)
        choices=ARGUMENT_SCHEMAS[name][key].get("enum")
        if choices and value not in choices:
            raise ValueError("参数不在允许取值中："+key)
    if name == "propose_invoice_changes" and "excluded_invoice_ids" in args and any(
            type(invoice) is not str or not re.fullmatch(r"F\d+", invoice, re.I)
            for invoice in args["excluded_invoice_ids"]):
        raise ValueError("排除对象必须为发票编号")
    if name == "list_invoice_directory" and directory_sort and "sort_by" not in args:
        # Paging a verified directory with omitted sort parameters retains the previous order.
        args["sort_by"] = directory_sort[0]
        args.setdefault("sort_order", directory_sort[1])
    return args


def _management_context(intent, proposals, user_id, domain, action):
    """有显式动作约束时不回退；普通路径只形成无写权限候选。"""
    if intent is None and isinstance(proposals,ManagementProposals):
        return ManagementCandidate(user_id,domain,proposals.source_request,action,proposals)
    return intent


_TASK_NOTE_ACTIONS = {
    "create": r"新建|创建|新增|建立|建(?:个|一[个条])|记成|记为|记(?:个|一[个条]|一下)|列为|设为|加[个一条]|添加|保存为",
    "update": r"补充|追加|更新|修改|改成|改为|加上",
    "correct": r"更正|纠正|修正|改为|改成",
}


def _task_note_request_error(request, action, proof):
    explicit = explicit_scope(request, include_update_aliases=True)
    verb = _TASK_NOTE_ACTIONS[action]
    negated = re.search(r"(?:不要|不用|无需|别|暂不|不想|不)\s*(?:(?:先|直接|自动|帮我|替我|再)\s*)*"
                        r"(?:(?:改为|改成|改到|按|把|将|给)[^，,。；;\n]{0,30})?(?:" + verb + ")", request)
    bare_change = action != "create" and re.fullmatch(
        r"\s*(?:请|帮我)?\s*(?:" + verb + r")\s*(?:这个|这条|当前)?(?:待办|任务)[。！!？?\s]*", request)
    task_mentioned = bool(re.search(r"待办|任务|记一下", request))
    # A model may propose creation without a fixed CRUD verb, but not from a
    # read-only task question. A proposal remains unprivileged until confirmation.
    read_only_question = action == "create" and bool(re.search(
        r"(?:查|查看|查询|列出|展示|有哪些|有没有|是什么).{0,18}(?:待办|任务)|"
        r"(?:待办|任务).{0,12}(?:有哪些|多少|什么|状态|列表|清单|吗|[?？])", request))
    negated = negated or bool(action == "create" and re.search(
        r"(?:不要|别|不用|无需|不必|不想).{0,8}(?:待办|任务|留|记)", request))
    if (not task_mentioned or negated or bare_change
            or (action != "create" and not re.search(verb, request))
            or (read_only_question and not re.search(r"留|记|创建|新建|建立|添加", request))):
        fields = [] if negated else ["note" if bare_change else "action"]
        return tool_result("AMBIGUOUS", error="请明确待办操作及本轮要保存的说明",
                           evidence={"missing_fields": fields})
    if action in _TASK_NOTE_ACTIONS and task_note_from_request(request) is None:
        return tool_result("AMBIGUOUS", error="本轮指定的待办说明不唯一或为空",
                           evidence={"missing_fields": ["note"]})
    if len(explicit.get("company_id", ())) > 1:
        return tool_result("AMBIGUOUS", error="请明确单一企业后再管理待办")
    annual = bool((proof and proof.annual_year is not None) or re.search(r"全年|全年度|整年", request)
                  or (explicit.get("year") and not explicit.get("month")))
    periods = explicit.get("periods", ())
    if annual or re.search(r"季度|半年", request) or (len(periods) == 1 and periods[0] != (2026, 9)):
        return tool_result("SCOPE_MISMATCH", error="用途待办仅支持 2026-09 单月，请明确本次待办范围",
                           evidence={"scope_negotiation": {"reason": "purpose_task_period", "annual": annual},
                                     "requested_scope": explicit})
    if any(len(explicit.get(key, ())) > 1 for key in ("year", "month", "periods")):
        return tool_result("AMBIGUOUS", error="请明确单一账期后再管理待办")
    if action == "create":
        trusted = proof.values if proof else {}
        companies = explicit.get("company_id") or trusted.get("company_id", ())
        periods = explicit.get("periods") or trusted.get("periods", ())
        missing = (["company_id"] if len(companies) != 1 else []) + (["year", "month"] if len(periods) != 1 else [])
        if missing:
            return tool_result("AMBIGUOUS", error="请先明确唯一的待办企业和账期",
                               evidence={"missing_fields": missing})
    return None


def _set_schedule(args,user_id,db_path,execution,permitted,session,expected,intent,proposals=None,provenance=None):
    """验证模型粗计划的结构、已有范围和真实授权；不执行任何业务步骤。"""
    if execution is None:
        return tool_result("DENIED",error="缺少可信单轮运行上下文")
    steps = args["steps"]
    if not 1<=len(steps)<=min(12,execution.policy.max_tools):
        raise ValueError("计划步骤数无效")
    if any(isinstance(s,dict) and isinstance(s.get('action'),str) and s['action'] not in permitted for s in steps):
        return tool_result('DENIED',error='计划包含未授权工具')
    ids = set()
    validated = []
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri()+"?mode=ro",uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        for step in steps:
            if type(step) is not dict or set(step)!={"step_id","action","arguments","depends_on"}:
                raise ValueError("计划步骤字段无效，不能提供status/confirmed等字段")
            identifier,action,deps = step["step_id"],step["action"],step["depends_on"]
            if type(identifier) is not str or not identifier.strip() or identifier in ids:
                raise ValueError("计划step_id必须非空且唯一")
            if type(deps) is not list or any(type(dep) is not str or dep not in ids for dep in deps) or len(set(deps))!=len(deps):
                raise ValueError("依赖只能引用前面的唯一步骤，不允许环或未知步骤")
            if type(action) is not str or action not in permitted or action=="set_schedule":
                return tool_result("DENIED",error="计划包含未授权的业务工具")
            constraints = validate_arguments(action,json.dumps(step["arguments"]),partial=True)
            for key in ("company_id","invoice_no","year","month"):
                if key in REGISTRY[action][1] and key not in constraints and len((expected or {}).get(key,[]))==1:
                    constraints[key] = expected[key][0]
            if "company_id" not in constraints:
                return tool_result("AMBIGUOUS",error="计划缺少可信企业范围，请先明确企业")
            operation = "modify" if action=="prepare_invoice_update" else "read"
            if not check_permission(connection,user_id,constraints["company_id"],operation).allowed:
                return tool_result("DENIED",error="没有计划目标企业的所需权限")
            missing=validate_scope(provenance,user_id,action,constraints,partial=True)
            if missing:return tool_result(**missing)
            scope = dict(constraints)
            if action=="get_applicable_rules" and "business_date" in scope:
                day = date.fromisoformat(scope["business_date"])
                if day.isoformat()!=scope["business_date"]:
                    raise ValueError("business_date必须为严格YYYY-MM-DD日期")
                scope.update(year=day.year,month=day.month)
            if expected and scope_mismatch(expected,scope):
                return tool_result("SCOPE_MISMATCH",error="计划目标与用户明确范围冲突")
            if action=="prepare_invoice_update" and (session is None or session.user_id!=user_id or not session.allow_prepare):
                return tool_result("DENIED",error="计划不授予Prepare或最终确认权限")
            domain = {"manage_task":"task","manage_preference":"preference"}.get(action)
            if domain and constraints.get("action") not in ({"show"} if domain=="task" else {"get","list"}):
                context=_management_context(intent,proposals,user_id,domain,constraints.get('action'))
                if not (can_manage(context,user_id,domain,constraints.get("action")) or can_propose(context,user_id,domain,constraints.get('action'))):
                    return tool_result("DENIED",error="计划不能创造任务/偏好管理意图")
            if "year" in constraints and "month" in constraints:
                queries._check_month(constraints["year"],constraints["month"])
            validated.append({**step,"arguments":constraints})
            ids.add(identifier)
    if not any(s["depends_on"] for s in validated) and not any(s["action"]=="manage_task" and s["arguments"].get("action")=="resume" for s in validated):
        raise ValueError("简单独立查询使用Fast Path，无须粗计划")
    return execution.install(args["goal"],validated,args["stop_condition"])


def remaining_work_allowed(path,user_id,steps,session,intent,permitted=None,proposals=None):
    """软限处重查剩余目标权限；续期绝不成为授权缓存。"""
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True)) as connection:
            connection.row_factory=sqlite3.Row
            connection.execute("BEGIN")
            for step in steps:
                args,name=step["arguments"],step["action"]
                if permitted is not None and name not in permitted:
                    return False
                operation="modify" if name=="prepare_invoice_update" else "read"
                if not check_permission(connection,user_id,args["company_id"],operation).allowed:
                    return False
                if name=="prepare_invoice_update" and (session is None or session.user_id!=user_id or not session.allow_prepare):
                    return False
                domain={"manage_task":"task","manage_preference":"preference"}.get(name)
                if domain and args.get("action") not in ({"show"} if domain=="task" else {"get","list"}):
                    context=_management_context(intent,proposals,user_id,domain,args.get('action'))
                    if not (can_manage(context,user_id,domain,args.get('action')) or can_propose(context,user_id,domain,args.get('action'))):
                        return False
            return True
    except sqlite3.Error:
        return False


def _confirm_proposal(outcome, service, intent, user_id, action, confirm):
    if outcome["status"] != "WAITING_CONFIRMATION" or confirm is None:
        return outcome
    proposal = outcome["data"]
    try:
        accepted = confirm(deepcopy(proposal))
    except (EOFError, KeyboardInterrupt):
        accepted = False
    except Exception:
        return tool_result("ERROR", error="可信管理确认入口失败，未保存")
    if accepted is not True:
        return tool_result("CANCELLED", error="用户未确认该对象和内容，未持久化")
    if not (can_propose(intent,user_id,intent.domain,action) or can_manage(intent,user_id,intent.domain,action)):
        return tool_result("DENIED", error="确认上下文已失效，未保存")
    approved = confirm_management(intent, proposal)
    outcome = service(approved)
    outcome["evidence"]["management_confirmation"] = {"source":"trusted_cli","request_id":proposal["request_id"],
        "fingerprint":proposal["fingerprint"],"turn_id":approved.turn.turn_id}
    return outcome


def annual_amount_rule(connection, user_id, company_id, year):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rules'").fetchone():
        return {"id": "R001", "name": "金额统计说明", "version": "1.0"}
    prefix = queries._year_prefix(year)[:-1]
    decisions = [resolve_rule(connection, user_id, company_id, "amount", f"{period}-01")
                 for period, _, _ in queries.available_periods(connection, user_id, company_id)
                 if period.startswith(prefix)]
    if not decisions or any(decision != decisions[0] for decision in decisions[1:]):
        raise RuleError("RULE_CONFLICT")
    return asdict(decisions[0])


def register_invoice_selection(selections, keys, scope, source):
    selection_id = uuid4().hex
    selections[selection_id] = (tuple(keys), scope, source)
    return selection_id


def handle_tool(name, raw_arguments, user_id, db_path, update_session=None, allowed_tools=None, expected_scope=None, management_intent=None, reference_context=None, execution=None, management_confirmation=None, management_proposals=None,provenance=None,display_preference=None,recent_context=None,sql_workspace=None,invoice_selections=None):
    """严格按 Schema 校验，身份仅取可信 Session，并复用业务函数。"""
    try:
        if not isinstance(name, str) or name not in REGISTRY:
            raise ValueError("未知工具")
        # 默认正式能力；内部存在函数不等于当前调用方有执行权。
        permitted = {tool["function"]["name"] for tool in TOOLS} if allowed_tools is None else allowed_tools
        if name not in permitted:
            return tool_result("DENIED", error="工具未授权给当前运行上下文")
        directory_sort = provenance.directory_sort if isinstance(provenance, ScopeProof) and provenance.actor == user_id else None
        args = validate_arguments(name, raw_arguments, directory_sort=directory_sort)
        function = REGISTRY[name][0]
        if name == "query_business_sql":
            if (sql_workspace is None or sql_workspace.actor != user_id
                    or Path(sql_workspace.path).resolve() != Path(db_path).resolve()):
                return tool_result("DENIED", error="本轮没有可用的可信 SQL 工作区")
            if execution:
                rejection = execution.guard(name, args)
                if rejection:
                    return rejection
            try:
                scope, data, keys = sql_workspace.query(args["sql"])
            except BusinessSQLError as error:
                evidence = {"missing_fields": list(error.missing)} if error.missing else {}
                return tool_result(error.status, evidence=evidence, error=str(error))
            if keys and invoice_selections is not None:
                data["selection_id"] = register_invoice_selection(invoice_selections, keys, scope, name)
            status = "SUCCESS" if data["rows"] or data["truncated"] else "NO_DATA"
            return tool_result(status, data, {"scope": scope, "source": "current_sqlite"})
        if name == "resolve_recent_invoice":
            if execution:
                rejection = execution.guard(name, args)
                if rejection:
                    return rejection
            if (not recent_context or recent_context["actor"] != user_id
                    or Path(recent_context["workbook"]).resolve() != Path(db_path).resolve()):
                return tool_result("DENIED", error="近期对象不属于当前用户或账簿")
            candidate = recent_context["candidates"].get(args["source"])
            if not candidate:
                return tool_result("AMBIGUOUS", error="本对话没有该来源的唯一可信发票",
                                   evidence={"missing_fields": ["invoice_reference"]})
            key = {field: candidate[field] for field in ("company_id", "invoice_no")}
            explicit = recent_context["explicit"]
            if scope_mismatch(explicit, key):
                return tool_result("SCOPE_MISMATCH", error="近期对象与本轮明确目标冲突")
            trusted_key = {field: [value] for field, value in key.items()}
            proof = ScopeProof(user_id, trusted_key, dict.fromkeys(trusted_key, "trusted_reference"))
            rejection = validate_scope(proof, user_id, "get_invoice", key)
            if rejection:
                return tool_result(**rejection)
            with closing(open_existing(db_path, readonly=True)) as connection:
                connection.execute("BEGIN")
                if not check_permission(connection, user_id, key["company_id"], "read").allowed:
                    return tool_result("DENIED", error="没有读取该发票的权限")
                current = queries.get_invoice(connection, user_id, **key) if args["source"] == "queried" else None
            evidence = {"source": "current_sqlite", "scope": key, "reference_source": args["source"]}
            if args["source"] == "modified":
                checked = inspect_request(db_path, user_id, candidate["request_id"])
                if checked["status"] != "COMMITTED":
                    return tool_result(checked["status"], error="无法重新核实本用户的历史提交")
                audit = checked["data"]["historical_commit"]
                if any(audit.get(field) != value for field, value in key.items()):
                    return tool_result("SCOPE_MISMATCH", error="历史审计与可信发票目标不一致")
                current = checked["data"]["current_invoice"]
                evidence["historical_commit"] = {"request_id": candidate["request_id"], "field": audit["field"],
                                                  "current_matches": checked["data"]["current_matches"]}
            if current is not None:
                day = date.fromisoformat(current["invoice_date"])
                scope = {**key, "year": day.year, "month": day.month}
                if scope_mismatch(explicit, scope):
                    return tool_result("SCOPE_MISMATCH", error="当前发票不在本轮明确账期内")
                evidence["scope"] = scope
            return tool_result("SUCCESS" if current is not None else "NO_DATA", current, evidence)
        if name=="set_schedule":
            return _set_schedule(args,user_id,db_path,execution,permitted,update_session,expected_scope,management_intent,management_proposals,provenance)
        if name == "manage_display_preference":
            if display_preference is None or (execution and execution.schedule):
                return tool_result("DENIED",error="当前会话或计划不支持个人显示偏好操作")
            action = args["action"]
            intent = _management_context(None,management_proposals,user_id,"display_preference",action)
            service = lambda approval: display_preference(**args,intent=approval,actor=user_id)
            return _confirm_proposal(service(intent),service,intent,user_id,action,management_confirmation)
        if name == "add":
            return tool_result("SUCCESS", args["a"] + args["b"])
        if name == "propose_invoice_changes":
            # Direct registry calls cannot establish a trusted editing session.
            return tool_result("DENIED", error="修改候选只可由Harness核实，不授予Prepare权限")
        if name == "prepare_invoice_update":
            if update_session is None or update_session.user_id != user_id:
                return tool_result("DENIED", error="缺少可信更新Session")
            if update_session.explicit_edit_only:
                from .updates import edit_scope_error
                rejection = edit_scope_error(update_session.expected_scope or {}, **args)
                if rejection:
                    return rejection
            with closing(sqlite3.connect(Path(db_path).resolve().as_uri()+"?mode=ro",uri=True)) as c:
                c.row_factory=sqlite3.Row
                if not check_permission(c,user_id,args['company_id'],'modify').allowed:
                    return tool_result('DENIED',error='没有修改权限')
            if not update_session.explicit_edit_only:
                missing = validate_scope(provenance, user_id, name, args)
                if missing:
                    return tool_result(**missing)
            if execution and execution.schedule:
                with closing(sqlite3.connect(Path(db_path).resolve().as_uri()+"?mode=ro",uri=True)) as connection:
                    connection.row_factory=sqlite3.Row
                    if not check_permission(connection,user_id,args["company_id"],"modify").allowed:
                        return tool_result("DENIED",error="没有修改权限")
                rejection=execution.guard(name,args)
                if rejection:
                    return rejection
            target = update_session.expected_scope
            if target is None:
                target = explicit_scope(update_session.source_request, include_update_aliases=True)
            if expected_scope and not update_session.explicit_edit_only:
                target = dict(target)
                for key in ("company_id","invoice_no"):
                    if key in expected_scope:
                        if key in target and target[key] != expected_scope[key]:
                            target["_conflict"] = True
                        else:
                            target[key] = expected_scope[key]
            return prepare_invoice_update(db_path, update_session, **args, expected_scope=target)
        unfiltered = name == "list_invoice_directory" and (args["year"], args["month"]) == (0, 0)
        annual_directory = name == "list_invoice_directory" and is_annual_query(name, args)
        task_request_error = None
        if isinstance(management_proposals, ManagementProposals) and management_proposals.task_note_from_request:
            if name == "manage_task" and args["action"] in _TASK_NOTE_ACTIONS:
                task_request_error = _task_note_request_error(management_proposals.source_request, args["action"], provenance)
            elif name == "check_missing_purpose" and provenance and provenance.annual_year is not None:
                conflict = _task_note_request_error(management_proposals.source_request, "create", provenance)
                if conflict and conflict["status"] == "SCOPE_MISMATCH":
                    task_request_error = conflict
        negotiation = (task_request_error or {}).get("evidence", {}).get("scope_negotiation")
        if annual_directory:
            queries._year_prefix(args["year"])
        elif "month" in args and not unfiltered and not negotiation:
            queries._check_month(args["year"], args["month"])
        path = Path(db_path).resolve()
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN")
            permission = check_permission(connection, user_id, args["company_id"], "read")
            if not permission.allowed:
                return tool_result("DENIED", error="没有读取权限")
            actual_scope = args
            if negotiation:
                company = args["company_id"]
                if not check_permission(connection, user_id, company, "modify").allowed:
                    return tool_result("DENIED", error="处理用途待办需要该企业的发票修改权限")
                trusted_company = provenance and (
                    (provenance.read_workspace or {}).get("company_id") == [company]
                    or (provenance.values.get("company_id") == [company]
                        and not validate_scope(provenance, user_id, "list_tasks", {"company_id": company})))
                if args.get("action", "create") == "create" and trusted_company:
                    negotiation["alternative_scope"] = {"company_id": company, "year": 2026, "month": 9}
                return task_request_error
            if name in {'manage_task','manage_preference'} and management_intent is not None:
                if management_intent.domain!=('task' if name=='manage_task' else 'preference') or (management_intent.action is not None and management_intent.action!=args['action']):
                    return tool_result('DENIED',error='不能改变可信管理入口的动作')
            if name=='manage_task' and args['action'] not in {'create','correct'} and args['task_id']:
                row=connection.execute('SELECT year,month FROM tasks WHERE task_id=? AND user_id=? AND company_id=?',
                    (args['task_id'],user_id,args['company_id'])).fetchone()
                if row and ((args['year'],args['month'])!=(row['year'],row['month']) or
                    (expected_scope and scope_mismatch(expected_scope,{'company_id':args['company_id'],'year':row['year'],'month':row['month']}))):
                    return tool_result('SCOPE_MISMATCH',error='任务实际范围与本次参数/可信范围不一致')
            if name == "get_applicable_rules":
                business_date = date.fromisoformat(args["business_date"])
                if business_date.isoformat() != args["business_date"]:
                    raise ValueError("business_date必须为严格YYYY-MM-DD日期")
                actual_scope = {**args,"year":business_date.year,"month":business_date.month}
            if name == "list_invoice_directory":
                if unfiltered and expected_scope and {"year", "month", "periods"} & expected_scope.keys():
                    return tool_result("SCOPE_MISMATCH", error="请求限定了账期，不能查询全企业目录。")
                actual_scope = {"company_id": args["company_id"]}
                if not unfiltered:
                    actual_scope["year"] = args["year"]
                if not (unfiltered or annual_directory):
                    actual_scope["month"] = args["month"]
            if (name in MONTHLY or (name == "list_invoice_directory" and not (unfiltered or annual_directory))) and provenance and provenance.read_workspace:
                expected_scope = {**(expected_scope or {}), **provenance.read_workspace}
            if expected_scope and scope_mismatch(expected_scope, actual_scope):
                return tool_result("SCOPE_MISMATCH", evidence={"scope":actual_scope,"requested_scope":expected_scope,"source":"request_validation"},
                                   error="范围不一致：工具企业或年月与用户明确字面范围不同，请确认实际查询范围")
            if task_request_error:
                return task_request_error
            missing=validate_scope(provenance,user_id,name,actual_scope)
            if missing:return tool_result(**missing)
            if execution:
                rejection=execution.guard(name,args)
                if rejection:
                    return rejection
                if name=="manage_task" and args["action"]=="resume":
                    execution.restore_schedule(args)
            if name == "resolve_invoice_reference":
                if not reference_context or args["ordinal"] != reference_context["ordinal"] or args["anchor_id"] not in {"",reference_context["anchor_id"]}:
                    return tool_result("AMBIGUOUS",error="缺少匹配的本轮用户引用线索，不接受模型自行选取序号或列表")
                return resolve_reference(db_path,user_id,args["ordinal"],reference_context["scope"],reference_context["anchor_id"],
                                         display_ids=reference_context.get("display_ids"))
            if name in {"list_tasks","manage_task","manage_preference"}:
                writing=(name=='manage_task' and args['action']!='show') or (name=='manage_preference' and args['action'] not in {'get','list'})
                domain='task' if name=='manage_task' else 'preference'
                intent=_management_context(management_intent,management_proposals,user_id,domain,args.get('action')) if writing else management_intent
                if writing and not (can_propose(intent,user_id,domain,args['action']) or
                        (isinstance(intent,ManagementIntent) and intent.turn is not None)):
                    return tool_result('DENIED',error='模型管理写入缺少本轮内容确认上下文；直接CLI请使用可信业务入口')
                # 释放只读检查事务；业务服务用新事务重新鉴权并执行，避免自己阻塞写入。
                connection.rollback()
                if name == "list_tasks":
                    outcome = list_tasks(db_path,user_id,**args)
                elif name == "manage_task":
                    if (isinstance(intent, ManagementCandidate) and intent.turn.task_note_from_request
                            and args["action"] in _TASK_NOTE_ACTIONS):
                        # The preview and the transaction use the same trusted payload.
                        args = {**args, "note": task_note_from_request(intent.source_request)}
                    outcome = manage_task(db_path,user_id,**args,intent=intent)
                else:
                    outcome = manage_preference(db_path,user_id,**args,intent=intent)
                if writing:
                    service = manage_task if name == "manage_task" else manage_preference
                    outcome = _confirm_proposal(outcome, lambda approval: service(db_path,user_id,**args,intent=approval),
                                                intent,user_id,args["action"],management_confirmation)
                    if name == "manage_preference" and outcome["status"] == "SUCCESS":
                        try:
                            current = manage_preference(db_path,user_id,args["company_id"],"get",args["key"])
                            verified = current["status"] == "NOT_FOUND" if args["action"] == "delete" else (
                                current["status"] == "SUCCESS" and current["data"]["value"] == args["value"])
                        except sqlite3.Error:
                            verified = False
                        outcome["evidence"]["preference_readback_verified"] = verified
                if outcome["ok"] or (name=='manage_preference' and args['action']=='get' and outcome['status']=='NOT_FOUND'):
                    if name=='manage_preference':outcome['evidence']['operation']={'action':args['action'],'key':args['key']}
                    elif name == "manage_task":
                        outcome["evidence"]["operation"] = {"action": args["action"]}
                    outcome["evidence"].setdefault("scope",{"company_id":args["company_id"]})
                    outcome["evidence"].setdefault("source","current_sqlite")
                    check = outcome["evidence"].get("check")
                    if check:
                        outcome["evidence"]["rule"] = check["rule"]
                return outcome
            if name == "list_rule_versions":
                versions = [dict(row) for row in connection.execute("""
                    SELECT rule_id,version,name,effective_from,status,content FROM rules
                    WHERE rule_id=? AND company_scope IN (?, '*') ORDER BY effective_from,version
                """, (args["rule_id"], args["company_id"]))]
                return tool_result("SUCCESS" if versions else "NO_DATA", versions,
                                   {"scope": {"company_id": args["company_id"]}, "source": "current_sqlite"})
            if name == "get_applicable_rules":
                decision = resolve_rule(connection, user_id, **args)
                return tool_result("SUCCESS", asdict(decision), {"rule":asdict(decision),"scope":actual_scope,"source":"current_sqlite"})
            if name == "count_invoice_fields":
                selector = args["selector"]
                scope = {key: args[key] for key in MONTH}
                evidence = {"scope": scope, "source": "current_sqlite"}
                if selector == "required_purpose_missing":
                    checked = check_missing_purpose(connection, user_id, **scope)
                    count = checked["count"]
                    evidence["rule"] = checked["rule"]
                else:
                    count = queries.filter_monthly_invoices(connection, user_id, **args)
                return tool_result("SUCCESS", {"selector": selector, "count": count}, evidence)
            if name == "check_missing_purpose":
                data = check_missing_purpose(connection, user_id, **args)
                return tool_result("SUCCESS", data, {"rule":data["rule"], "source":"current_sqlite", "scope":args})
            if name in ANNUAL:
                data = function(connection, user_id, **args)
                evidence = {"source": "current_sqlite", "scope": {"company_id": args["company_id"], "year": args["year"]}}
                if name in {"list_annual_blank_purpose", "list_annual_bank_income"}:
                    return tool_result("SUCCESS" if data["rows"] else "NO_DATA", data, evidence)
                if not any(data[key] for key in ("invoice_count", "bank_income_count", "bank_expense_count")):
                    return tool_result("NO_DATA", data, evidence)
                evidence["rule"] = annual_amount_rule(connection, user_id, **args)
                return tool_result("SUCCESS", data, evidence)
            if name in {"summary", "get_finance_summary"}:
                data = finance.get_finance_summary(connection, user_id, **args)
                empty = not (data["invoice_count"] + data["bank_income_count"] + data["bank_expense_count"])
            else:
                data = function(connection, user_id, **args)
                empty = data is None or data == []
                if name.endswith("_total"):
                    rows = queries.list_invoices(connection, user_id, **args) if name == "invoice_total" else queries.list_bank_transactions(connection, user_id, **args)
                    if name != "invoice_total":
                        direction = "收入" if name == "bank_income_total" else "支出"
                        rows = [r for r in rows if r["direction"] == direction]
                    empty = not rows
            evidence = {"source": "current_sqlite", "scope": actual_scope}
            if name == "list_invoice_directory":
                return tool_result("SUCCESS" if data["rows"] else "NO_DATA", data, evidence)
            if name in {'list_invoices','list_bank_transactions'}:
                # 与明细同一已鉴权快照，复用现有金额服务；渲染按工具范围选取，不跨企业拼加。
                evidence['finance_summary']=finance.get_finance_summary(connection,user_id,**args)
            if name == "get_invoice" and data:
                evidence["scope"] = {**args,"year":int(data["invoice_date"][:4]),"month":int(data["invoice_date"][5:7])}
                if expected_scope and scope_mismatch(expected_scope,evidence["scope"]):
                    return tool_result("SCOPE_MISMATCH",evidence={**evidence,"requested_scope":expected_scope},error="范围不一致：当前发票日期与用户明确年月不同")
            if name == "list_bank_transactions":
                has_rules = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rules'").fetchone()
                if has_rules:
                    try:
                        evidence["rule"] = asdict(resolve_rule(connection,user_id,args["company_id"],"bank",f"{args['year']:04d}-{args['month']:02d}-01"))
                    except RuleError as error:
                        # R004是说明依据；缺失不赋予银行写权限，也不阻断原有只读数据查询。
                        evidence["rule_status"] = str(error)
                else:
                    evidence["rule"] = {"id":"R004","name":"银行资料说明","version":"1.0"}
            if name in {"summary", "get_finance_summary","list_invoices","list_bank_transactions"} or name.endswith("_total"):
                # 未迁移的Stage 1库继续提供原金额统计；Stage 2库一律解析当前规则。
                has_rules = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rules'").fetchone()
                if has_rules:
                    try:
                        amount_rule = asdict(resolve_rule(connection, user_id, args["company_id"], "amount", f"{args['year']:04d}-{args['month']:02d}-01"))
                    except RuleError as error:
                        if name not in {'list_invoices','list_bank_transactions'}:
                            raise
                        # 补充汇总无规则依据时不渲染金额；保留既有明细只读能力和错误证据。
                        evidence.pop('finance_summary',None)
                        evidence['summary_status']=str(error)
                        return tool_result('NO_DATA' if empty else 'SUCCESS',data,evidence)
                else:
                    amount_rule = {"id": "R001", "name": "金额统计说明", "version": "1.0"}
                if name=='list_bank_transactions':
                    evidence['amount_rule']=amount_rule
                else:
                    evidence['rule']=amount_rule
            return tool_result("NO_DATA" if empty else "SUCCESS", data, evidence)
        finally:
            connection.close()
    except RuleError as error:
        status = str(error) if str(error) in {"NO_APPLICABLE_RULE", "RULE_CONFLICT"} else "INVALID_ARGUMENTS"
        return tool_result(status, error=str(error))
    except (ValueError, TypeError, sqlite3.Error) as error:
        return tool_result("ERROR" if isinstance(error, sqlite3.Error) else "INVALID_ARGUMENTS",
                           error="数据库不可用" if isinstance(error, sqlite3.Error) else str(error))
