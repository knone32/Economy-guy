"""工具声明、严格参数校验与受控分发。"""
import json
from pathlib import Path
import sqlite3
from dataclasses import asdict
from datetime import date
from . import finance, queries
from .permissions import check_permission
from .updates import prepare_invoice_update
from .rules import resolve_rule, check_missing_purpose, RuleError
from .responses import scope_mismatch, explicit_scope
from .tasks import list_tasks, manage_task
from .preferences import manage_preference
from .references import resolve_reference
from .persistence import can_manage, can_propose, confirm_management, ManagementIntent, ManagementCandidate, ManagementProposals
from contextlib import closing
from copy import deepcopy
from .provenance import MONTHLY, validate_scope

MONTH = {"company_id": "string", "year": "integer", "month": "integer"}
REGISTRY = {
    "list_invoices": (queries.list_invoices, MONTH),
    "list_invoice_directory": (queries.invoice_directory, {**MONTH, "page": "integer"}),
    "get_invoice": (queries.get_invoice, {"company_id": "string", "invoice_no": "string"}),
    "list_bank_transactions": (queries.list_bank_transactions, MONTH),
    "invoice_total": (finance.invoice_total, MONTH),
    "bank_income_total": (finance.bank_income_total, MONTH),
    "bank_expense_total": (finance.bank_expense_total, MONTH),
    "summary": (None, MONTH),
    "get_finance_summary": (finance.get_finance_summary, MONTH),
    "check_missing_purpose": (check_missing_purpose, MONTH),
    "get_applicable_rules": (None, {"company_id":"string", "rule_type":"string", "business_date":"string"}),
    "prepare_invoice_update": (None, {"company_id":"string", "invoice_no":"string", "field":"string", "new_value":"string"}),
    "add": (None, {"a": "integer", "b": "integer"}),
    "list_tasks": (None, {"company_id":"string"}),
    "manage_task": (None, {"company_id":"string","action":"string","task_id":"string","year":"integer","month":"integer","note":"string"}),
    "manage_preference": (None, {"company_id":"string","action":"string","key":"string","value":"string"}),
    "resolve_invoice_reference": (None, {"company_id":"string","ordinal":"integer","anchor_id":"string"}),
    "set_schedule": (None, {"goal":"string","steps":"array","stop_condition":"string"}),
}
TOOLS = [{"type": "function", "function": {"name": name,
          "description": ("仅准备草稿，不保存；需可信CLI最终确认：" if name == "prepare_invoice_update" else "查询当前数据库：") + name,
          "parameters": {"type": "object", "properties": {key: {"type": kind} for key, kind in fields.items()},
                         "required": list(fields), "additionalProperties": False}}}
         for name, (_, fields) in REGISTRY.items()]
TEACHING_TOOLS = TOOLS
TOOLS = [tool for tool in TOOLS if tool["function"]["name"] in {
    "get_finance_summary", "list_invoices", "list_invoice_directory", "get_invoice", "list_bank_transactions",
    "check_missing_purpose", "get_applicable_rules", "prepare_invoice_update",
    "list_tasks", "manage_task", "manage_preference", "resolve_invoice_reference", "set_schedule"}]
DESCRIPTIONS = {
    "get_finance_summary":"发票和银行收支综合查询首选：一次返回指定企业年月的价税合计/张数、收入/支出总额/分别条数和R001版本；补充月份后沿用原综合目标。无记录明确返回零，无需额外计划。",
    "list_invoices":"查询指定企业月份的发票明细；大列表优先使用分页目录。",
    "list_invoice_directory":"分页列出企业发票目录，返回真实总数；每页10条，page从1开始。全企业目录使用year=0、month=0，无需追问月份。用户明确选择年月时提供完整配对。",
    "get_invoice":"企业编号和发票号联合定位当前发票，不猜测模糊指代。",
    "list_bank_transactions":"查询指定企业年月的银行流水，只读，不推断发票已付款。",
    "check_missing_purpose":"按唯一有效RuleDecision检查2026年9月必填用途缺失；备注不代替用途。",
    "get_applicable_rules":"按企业、业务日期和规则类型获取唯一启用依据；不提供管理权限。",
    "prepare_invoice_update":"只生成用途/备注草稿，展示旧值，不保存；必须等待可信CLI最终确认。",
    "list_tasks":"列出当前用户指定企业的持久任务，不创建或修改待办。",
    "manage_task":"为普通自然语言后续待办提出创建/更正/取消等候选，或查询任务；候选无写入权限，需可信CLI展示具体对象和内容并确认。恢复重查规则与发票，完成必须有业务证据；不能修改发票。",
    "manage_preference":"用户企业隔离的偏好CRUD；普通自然语言可提出create/update/delete候选，get/list只读。删除需明确key、value为空。所有写候选须可信CLI展示旧值/新值并确认，不能自行声称保存。",
    "resolve_invoice_reference":"仅解析用户本轮明确的第几张发票线索；必须有真实展示锚点，重新鉴权查库，无唯一对象则追问。不能自由猜序号。",
    "set_schedule":"仅真正多步依赖时提出本轮粗计划；不是长期任务或授权。再次调用为一次显式重规划，不创造进展或预算。简单查询直接调用业务工具。",
}
PARAMETERS = {"company_id":"企业编号，例如C001；不能凭空猜测。", "year":"明确的业务年份。",
              "month":"业务月份，1到12。", "page":"目录页码，从1开始。", "invoice_no":"与企业共同确定发票的精确编号。",
              "field":"只允许purpose或remark。", "new_value":"用户明确的新内容，空字符串表示清空。",
              "rule_type":"amount、purpose或bank。", "business_date":"YYYY-MM-DD业务日期。",
              "action":"该管理工具支持的操作名称。", "task_id":"已有任务ID；create使用空字符串。",
              "note":"用户明确的简短后续待办说明，优先保留原话；不扩写发票清单、规则解释或步骤计划；具体内容仍需可信确认，不接受模型声称完成作为证据。",
              "key":"偏好名称；list时为空。", "value":"用户明确的偏好内容；查询/删除时为空。",
              "ordinal":"用户明确的展示序号，从1开始。", "anchor_id":"已展示anchor编号；唯一列表时可为空，不能自行编造。",
              "goal":"本轮用户目标描述，不是执行证据。","steps":"必要工具步骤及依赖，不拆分SQL/事务等内部操作。",
              "stop_condition":"目标证据齐全或等待用户/确认/拒绝时停止的描述；不能扩大运行时硬限。"}
for tool in TOOLS:
    tool["function"]["description"] = DESCRIPTIONS[tool["function"]["name"]]
    for key, schema in tool["function"]["parameters"]["properties"].items():
        schema["description"] = PARAMETERS[key]
        if tool["function"]["name"] == "list_invoice_directory" and key in {"year", "month"}:
            schema["description"] += " 不筛选账期时，年份和月份都传0。"
for tool in TOOLS:
    if tool["function"]["name"] == "prepare_invoice_update":
        tool["function"]["parameters"]["properties"]["field"]["enum"] = ["purpose", "remark"]
    if tool["function"]["name"] == "manage_task":
        tool["function"]["parameters"]["properties"]["action"]["enum"] = ["create","show","update","correct","wait","pause","resume","complete","cancel"]
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


def validate_arguments(name, raw_arguments, partial=False):
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
    if type(args) is not dict or not set(args)<=set(fields) or (not partial and set(args)!=set(fields)):
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
    return args


def _management_context(intent, proposals, user_id, domain, action):
    """有显式动作约束时不回退；普通路径只形成无写权限候选。"""
    if intent is None and isinstance(proposals,ManagementProposals):
        return ManagementCandidate(user_id,domain,proposals.source_request,action,proposals)
    return intent


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


def handle_tool(name, raw_arguments, user_id, db_path, update_session=None, allowed_tools=None, expected_scope=None, management_intent=None, reference_context=None, execution=None, management_confirmation=None, management_proposals=None,provenance=None):
    """严格按 Schema 校验，身份仅取可信 Session，并复用业务函数。"""
    try:
        if not isinstance(name, str) or name not in REGISTRY:
            raise ValueError("未知工具")
        # 默认正式能力；内部存在函数不等于当前调用方有执行权。
        permitted = {tool["function"]["name"] for tool in TOOLS} if allowed_tools is None else allowed_tools
        if name not in permitted:
            return tool_result("DENIED", error="工具未授权给当前运行上下文")
        args = validate_arguments(name,raw_arguments)
        function = REGISTRY[name][0]
        if name=="set_schedule":
            return _set_schedule(args,user_id,db_path,execution,permitted,update_session,expected_scope,management_intent,management_proposals,provenance)
        if name == "add":
            return tool_result("SUCCESS", args["a"] + args["b"])
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
        if "month" in args and not unfiltered:
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
                    actual_scope.update(year=args["year"], month=args["month"])
            if (name in MONTHLY or (name == "list_invoice_directory" and not unfiltered)) and provenance and provenance.read_workspace:
                expected_scope = {**(expected_scope or {}), **provenance.read_workspace}
            if expected_scope and scope_mismatch(expected_scope, actual_scope):
                return tool_result("SCOPE_MISMATCH", evidence={"scope":actual_scope,"requested_scope":expected_scope,"source":"request_validation"},
                                   error="范围不一致：工具企业或年月与用户明确字面范围不同，请确认实际查询范围")
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
                return resolve_reference(db_path,user_id,args["ordinal"],reference_context["scope"],reference_context["anchor_id"])
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
                    outcome = manage_task(db_path,user_id,**args,intent=intent)
                else:
                    outcome = manage_preference(db_path,user_id,**args,intent=intent)
                if outcome['status']=='WAITING_CONFIRMATION' and management_confirmation is not None:
                    # 预览事务已经关闭；不在持有SQLite锁时等待用户输入。
                    proposal=outcome['data']
                    try:
                        accepted=management_confirmation(deepcopy(proposal))
                    except (EOFError,KeyboardInterrupt):
                        accepted=False
                    except Exception:
                        return tool_result('ERROR',error='可信管理确认入口失败，未保存')
                    if accepted is not True:
                        return tool_result('CANCELLED',error='用户未确认该对象和内容，未持久化')
                    if not (can_propose(intent,user_id,intent.domain,args['action']) or can_manage(intent,user_id,intent.domain,args['action'])):
                        return tool_result('DENIED',error='确认上下文已失效，未保存')
                    approved=confirm_management(intent,proposal)
                    service=manage_task if name=='manage_task' else manage_preference
                    outcome=service(db_path,user_id,**args,intent=approved)
                    outcome['evidence']['management_confirmation']={'source':'trusted_cli','request_id':proposal['request_id'],
                        'fingerprint':proposal['fingerprint'],'turn_id':approved.turn.turn_id}
                if outcome["ok"] or (name=='manage_preference' and args['action']=='get' and outcome['status']=='NOT_FOUND'):
                    if name=='manage_preference':outcome['evidence']['operation']={'action':args['action'],'key':args['key']}
                    outcome["evidence"].setdefault("scope",{"company_id":args["company_id"]})
                    outcome["evidence"].setdefault("source","current_sqlite")
                    check = outcome["evidence"].get("check")
                    if check:
                        outcome["evidence"]["rule"] = check["rule"]
                return outcome
            if name == "get_applicable_rules":
                decision = resolve_rule(connection, user_id, **args)
                return tool_result("SUCCESS", asdict(decision), {"rule":asdict(decision),"scope":actual_scope,"source":"current_sqlite"})
            if name == "check_missing_purpose":
                data = check_missing_purpose(connection, user_id, **args)
                return tool_result("SUCCESS", data, {"rule":data["rule"], "source":"current_sqlite", "scope":args})
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
