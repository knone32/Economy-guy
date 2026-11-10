"""Run a fixed, human-approved invoice list through the existing single-item coordinator."""
from contextlib import closing
from dataclasses import asdict
from datetime import date
import re
import sqlite3

from .permissions import check_permission
from .queries import get_invoice, list_invoices
from .rules import missing_required_purpose, resolve_rule
from .tui_intent import excluded_invoice_ids, invoice_change_evidence
from .responses import explicit_scope
from .stage2_schema import open_existing
from .trace import redact
from .updates import prepare_invoice_update


MAX_BATCH_INVOICES = 20


def _preview(field_value):
    if field_value is None:
        return "（未填写）"
    if not field_value:
        return "（空字符串）"
    if not field_value.strip() or any(char in field_value for char in "\r\n\t"):
        return repr(field_value)
    return field_value


def _apply_target(agent, message, values, period, old, confirm, checkpoint):
    if not agent.workbook_available():
        return "ERROR", None
    coordinator = agent.coordinator
    coordinator.begin(message, allow_prepare=True, edit_scope={key: [val] for key, val in values.items()})
    try:
        prepared = prepare_invoice_update(agent.db_path, agent.update_session, **values)
        coordinator.record_preparation(prepared)
        agent.trace("invoice_batch.prepared", {"invoice_no": values["invoice_no"], "outcome": prepared})
        if prepared["status"] != "WAITING_CONFIRMATION":
            return prepared["status"], None
        draft, = agent.update_session.drafts.values()
        current_date = prepared["data"]["current_invoice"]["invoice_date"]
        if draft.old_value != old or current_date[:7] != period:
            return "CONFLICT", None
        if old == draft.new_value:
            return "NO_CHANGE", None
        fields = asdict(draft)
        if redact(fields) != fields:
            return "DENIED", None
        decision = confirm()
        if decision == "skip":
            return "SKIPPED", None
        if decision != "confirm":
            return "CANCELLED", None
        if not agent.workbook_available():
            return "ERROR", None
        fingerprint = draft.fingerprint()
        checkpoint(draft.request_id)
    except Exception:
        # This phase is read-only even if the dialog or checkpoint cannot be opened.
        return "ERROR", None

    try:
        receipt = agent.commit_update(draft.request_id, fingerprint)
    except Exception:
        # A checkpoint exists. The caller must inspect the audit before any retry.
        coordinator.receipt = coordinator._receipt("UNKNOWN_OUTCOME", {"request_id": draft.request_id})
        return "UNKNOWN_OUTCOME", draft.request_id
    return receipt["status"], draft.request_id


def _required_invoice_ids(db, actor, company, period, params, excluded):
    return {row["invoice_no"] for row in list_invoices(db, actor, company, *period)
            if row["invoice_no"] not in excluded and missing_required_purpose(params, row)}


_FILTER_FIELDS = {"销售方": "seller_name", "销方": "seller_name", "备注": "remark", "项目": "item_name"}
_LITERAL_FILTER = re.compile(
    rf"({'|'.join(_FILTER_FIELDS)})\s*(?:(不为空|为空)|(?:为|是|等于)\s*"
    r"(?:“([^”]+)”|‘([^’]+)’|\"([^\"]+)\"|'([^']+)'|([^，,。；;]+?)(?=的发票|且|，|,|。|；|;|$)))"
)


def _rule_subset_filters(text, new_value):
    """Only literal field constraints can justify a narrower rule selection."""
    start = text.rfind(new_value) if new_value else -1
    end = start + len(new_value)
    # The value being written is not evidence of a condition on the target.
    filters, edit_source = [], text
    for match in reversed(list(_LITERAL_FILTER.finditer(text))):
        if start >= 0 and match.start() < end and start < match.end():
            continue
        label, predicate, *values = match.groups()
        filters.append((_FILTER_FIELDS[label], predicate, next((value.strip() for value in values if value), None)))
        edit_source = edit_source[:match.start()] + " " + edit_source[match.end():]
    return tuple(filters), edit_source


def _matches_subset_filters(row, filters):
    for field, predicate, value in filters:
        current = (row[field] or "").strip()
        if predicate == "为空" and current or predicate == "不为空" and not current:
            return False
        if not predicate and current != value:
            return False
    return True


def plan_invoice_change(agent, source_request, proposal, selection, *, authorized_periods=(),
                        literal_periods=(), read_results=()):
    """Validate current-turn scope and literal edit constraints without preparing a draft."""
    if selection is None:
        return None, "AMBIGUOUS", "请先取得本轮可信发票集合。"
    keys, scope, source = selection
    companies = {company for company, _ in keys}
    if len(companies) != 1:
        return None, "SCOPE_MISMATCH", "一次只能确认一家企业，请分企业请求修改。"
    company, = companies
    rule_selection = source == "check_missing_purpose"
    collection = source == "query_business_sql" or rule_selection
    requested = explicit_scope(source_request, include_update_aliases=True)
    if (requested.get("company_id") and requested["company_id"] != [company]
            or source == "query_business_sql" and tuple(scope["company_ids"]) != (company,)):
        return None, "SCOPE_MISMATCH", "候选集合与用户明确的企业不一致。"
    excluded = excluded_invoice_ids(source_request)
    invoice_nos = {invoice for _, invoice in keys}
    if rule_selection:
        invoice_nos -= excluded
    if not invoice_nos:
        return None, "NO_DATA", "排除指定发票后没有可修改的记录。"
    named = set(requested.get("invoice_no", ())) - excluded
    if (excluded != {invoice.upper() for invoice in proposal["excluded_invoice_ids"]}
            or invoice_nos & excluded or (named and named != invoice_nos)):
        return None, "SCOPE_MISMATCH", "候选集合未准确遵守用户指定或排除的发票编号。"
    if not requested.get("company_id") and source != "resolve_recent_invoice" and source != "resolve_invoice_reference":
        return None, "AMBIGUOUS", "请明确修改对象所属企业。"
    if source == "get_invoice" and not named:
        return None, "AMBIGUOUS", "请明确发票编号或使用已核验的发票引用。"
    if len(invoice_nos) > MAX_BATCH_INVOICES:
        return None, "INVALID_ARGUMENTS", f"本次超过 {MAX_BATCH_INVOICES} 张的处理上限，请缩小范围。"

    target_period = (proposal["target_year"], proposal["target_month"]) if "target_year" in proposal else None
    rule_date = proposal.get("rule_business_date")
    if rule_selection:
        selected_period = (scope["year"], scope["month"])
        selected_date = scope["rule_business_date"]
        if ((target_period is not None and target_period != selected_period)
                or (rule_date is not None and rule_date != selected_date)):
            return None, "SCOPE_MISMATCH", "提案目标年月或参考日期与本轮规则选集不一致。"
        target_period, rule_date = selected_period, selected_date
    if len(authorized_periods) > 1 and (target_period is None or not rule_date):
        return None, "AMBIGUOUS", "请分别明确规则参考日期与唯一的发票目标年月。"
    if target_period is None and len(authorized_periods) == 1:
        target_period, = authorized_periods
    if target_period is not None and target_period not in authorized_periods:
        return None, "SCOPE_MISMATCH", "目标年月没有本轮用户字面量或账簿账期证据。"
    if collection and target_period is None:
        return None, "SCOPE_MISMATCH", "请明确要修改的发票目标年月。"

    rule = None
    cohort = False
    subset_filters = ()
    edit_source = source_request
    if rule_date:
        day = date.fromisoformat(rule_date)
        rule_period = (day.year, day.month)
        if rule_selection and len(authorized_periods) > 1 and (
                not scope["reference_rule_screening"] or rule_period == target_period):
            return None, "AMBIGUOUS", "跨月选集须分别使用可信参考日期和发票目标账期。"
        trusted_periods = authorized_periods if rule_selection else (literal_periods or authorized_periods)
        if rule_period not in trusted_periods or not collection:
            return None, "SCOPE_MISMATCH", "请使用本轮已核验的规则日期和目标发票清单。"
        matches = []
        for name, outcome in read_results:
            evidence = outcome.get("evidence", {})
            rule_scope = evidence.get("scope", {})
            if (outcome["status"] != "SUCCESS" or evidence.get("source") != "current_sqlite"
                    or rule_scope.get("company_id") != company):
                continue
            data = outcome["data"]
            if rule_selection:
                if (name != "check_missing_purpose" or data.get("selection_id") != proposal["selection_id"]
                        or (data["target_year"], data["target_month"]) != target_period
                        or data["rule_business_date"] != rule_date):
                    continue
                decision = data["rule"]
            else:
                if (name != "get_applicable_rules" or rule_scope.get("rule_type") != "purpose"
                        or rule_scope.get("business_date") != rule_date):
                    continue
                decision = data
            if decision == evidence.get("rule") and decision["rule_type"] == "purpose" and decision not in matches:
                matches.append(decision)
        if len(matches) != 1:
            return None, "SCOPE_MISMATCH", "当前轮没有唯一匹配的企业用途规则证据，请核对参考日期。"
        rule, = matches
        subset_filters, edit_source = _rule_subset_filters(source_request, proposal["new_value"])
        if rule_selection:
            criteria = source_request.replace(proposal["new_value"], "", 1) if proposal["new_value"] else source_request
            if named or subset_filters or any(label in criteria for label in ("销售方", "销方", "备注", "项目", "金额", "价税", "开票日期")):
                return None, "AMBIGUOUS", "规则全集工具不应用附加筛选，请使用含这些条件的 SQL 选集。"
        if len(subset_filters) > 1 and "或" in source_request:
            return None, "AMBIGUOUS", "附加筛选包含多个备选条件，请拆分或明确各条件的适用范围。"
        # The proposal flag describes intent. It cannot authorize an unexplained subset.
        cohort = rule_selection or not (named or subset_filters)

    if not invoice_change_evidence(edit_source, proposal["field"], proposal["new_value"],
                                   rule_field="purpose" if rule else None):
        return None, "AMBIGUOUS", "请明确允许修改的字段及来自用户原话的新值。"

    try:
        with closing(open_existing(agent.db_path, readonly=True)) as db:
            db.execute("BEGIN")
            if any(not check_permission(db, agent.user_id, company, operation).allowed
                   for operation in ("read", "modify")):
                return None, "DENIED", "当前账号没有该企业的发票读取和修改权限。"
            rows = [get_invoice(db, agent.user_id, company, invoice_no) for invoice_no in invoice_nos]
            if any(row is None for row in rows):
                return None, "CONFLICT", "清单中的发票已失效，请重新查询。"
            days = [date.fromisoformat(row["invoice_date"]) for row in rows]
            actual_periods = {(day.year, day.month) for day in days}
            if rule:
                current_rule = resolve_rule(db, agent.user_id, company, "purpose", rule_date)
                if (current_rule.rule_id, current_rule.version, current_rule.params) != (
                        rule["rule_id"], rule["version"], rule["params"]):
                    return None, "CONFLICT", "参考规则已变化，请重新核验。"
                if cohort:
                    expected = _required_invoice_ids(db, agent.user_id, company, target_period,
                                                     current_rule.params, excluded)
                    if len(expected) > MAX_BATCH_INVOICES:
                        return None, "INVALID_ARGUMENTS", f"规则缺项全集超过 {MAX_BATCH_INVOICES} 张，未创建确认清单。"
                    if invoice_nos != expected:
                        return None, "SCOPE_MISMATCH", (f"规则缺项全集有 {len(expected)} 张，候选清单有 {len(invoice_nos)} 张，"
                                                        "且无可核验的独立筛选依据。请重新查询或明确附加条件，未进入确认。")
                elif any(not missing_required_purpose(current_rule.params, row)
                         or not _matches_subset_filters(row, subset_filters) for row in rows):
                    return None, "SCOPE_MISMATCH", "清单含有不符合参考规则或原话附加条件的发票。"
    except (OSError, sqlite3.Error, ValueError):
        return None, "ERROR", "无法核验账簿、企业权限或发票实际日期。"

    if len(actual_periods) != 1 or target_period and actual_periods != {target_period}:
        return None, "SCOPE_MISMATCH", "所有发票必须属于同一个已确认的目标年月。"
    year, month = next(iter(actual_periods))
    if source == "query_business_sql":
        if (year, month) not in scope.get("periods", ()):
            return None, "SCOPE_MISMATCH", "发票实际年月与本轮 SQL 查询范围不一致。"
    elif (year, month) != (scope.get("year"), scope.get("month")):
        return None, "SCOPE_MISMATCH", "发票实际年月与本轮读取证据不一致。"
    if not rule and any(requested.get(key) and requested[key] != [value]
                        for key, value in (("year", year), ("month", month))):
        return None, "SCOPE_MISMATCH", "候选发票账期与用户要求不一致。"
    request = {key: proposal[key] for key in ("field", "new_value", "mode")}
    if rule:
        request["rule_reference"] = {"business_date": rule_date, "rule_id": rule["rule_id"],
                                     "version": rule["version"], "params": rule["params"], "cohort": cohort,
                                     "subset_filters": subset_filters,
                                     "screening": not rule_selection or scope["reference_rule_screening"]}
    return {**request, "company_id": company, "year": year, "month": month,
            "invoice_nos": tuple(sorted(invoice_nos)), "excluded": tuple(sorted(excluded)),
            "source_request": source_request, "actor": agent.user_id,
            "workbook": str(agent.db_path), "turn": agent.trace_id}, "WAITING_CONFIRMATION", None


def run_invoice_batch(agent, message, request, *, approve_batch, approve_item, checkpoint):
    company, year, month = (request[key] for key in ("company_id", "year", "month"))
    field, value, mode = (request[key] for key in ("field", "new_value", "mode"))
    period = f"{year:04d}-{month:02d}"
    invoice_nos = request["invoice_nos"]
    rule_reference = request.get("rule_reference")
    coordinator = agent.coordinator
    if (request["actor"], request["workbook"], request["turn"]) != (agent.user_id, str(agent.db_path), agent.trace_id):
        return "DENIED", "对话轮次、账簿或用户已变化，原清单失效。"
    if coordinator.receipt["status"] == "UNKNOWN_OUTCOME":
        return "UNKNOWN_OUTCOME", "上一次提交结果仍未知，请先核查审计。"

    if not invoice_nos or len(invoice_nos) > MAX_BATCH_INVOICES:
        return "INVALID_ARGUMENTS", f"可信清单必须包含 1 至 {MAX_BATCH_INVOICES} 张发票。"
    coordinator.begin(message)
    agent.trace("invoice_batch.started", {"company_id": company, "year": year, "month": month,
                                         "invoice_nos": invoice_nos, "field": field, "mode": mode})
    if not agent.workbook_available():
        return "ERROR", "工作账簿已变化，请重新打开。"
    try:
        with closing(open_existing(agent.db_path, readonly=True)) as db:
            db.execute("BEGIN")
            if any(not check_permission(db, agent.user_id, company, operation).allowed
                   for operation in ("read", "modify")):
                return "DENIED", "你没有该企业的读取和修改权限，未创建批量草稿。"
            rows = [get_invoice(db, agent.user_id, company, invoice_no) for invoice_no in invoice_nos]
            if any(not row or row["invoice_date"][:7] != period for row in rows):
                return "CONFLICT", "清单内发票已失效或账期已变更，未执行修改。"
            if rule_reference:
                if any(not missing_required_purpose(rule_reference["params"], row)
                       or not _matches_subset_filters(row, rule_reference["subset_filters"]) for row in rows):
                    return "CONFLICT", "发票已不符合参考规则或原话附加条件，未执行修改。"
                if rule_reference["cohort"] and set(invoice_nos) != _required_invoice_ids(
                        db, agent.user_id, company, (year, month), rule_reference["params"], request["excluded"]):
                    return "CONFLICT", "规则缺项全集已变化，请重新查询，未执行修改。"
            rows.sort(key=lambda row: (row["invoice_date"], row["invoice_no"]))
            targets = tuple((row["invoice_no"], row[field]) for row in rows)
    except (OSError, ValueError, sqlite3.Error):
        return "ERROR", "无法重新核验发票清单，请检查账簿。"

    field_label = "用途" if field == "purpose" else "备注"
    overwrites = sum(bool((old or "").strip()) and old != value for _, old in targets)
    scope = (f"企业　{company} · {period}\n字段　{field_label}\n"
             f"覆盖提示　将替换 {overwrites} 张发票已填写的{field_label}。")
    if rule_reference:
        label = "参考规则" if rule_reference["screening"] else "适用规则"
        scope += (f"\n{label}　{rule_reference['business_date']} · "
                  f"{rule_reference['rule_id']} v{rule_reference['version']}"
                  f"\n发票目标账期　{period}")
        if rule_reference["screening"]:
            scope += "\n按指定参考月份规则筛选目标月份发票，不代表目标月份正式合规认定。"
        if not rule_reference["cohort"]:
            scope += "\n仅确认以下 SQL 清单；程序未核验附加筛选条件的全集。"
    scope += "\n原始要求　" + message
    if request["excluded"]:
        scope += "\n明确排除　" + "、".join(request["excluded"])
    item_lines = [f"{invoice}\n原值　{_preview(old)}\n新值　{_preview(value)}" for invoice, old in targets]
    if redact(item_lines) != item_lines or redact(message) != message:
        return "DENIED", "预览含有需隐藏的内容，无法进行完整核对，未提交。"

    counts = {"committed": 0, "skipped": 0, "failed": 0, "unknown": 0}
    details = []
    status = "COMPLETED"
    full_preview = f"全部匹配 {len(targets)} 张\n\n" + "\n\n".join(item_lines)
    preview_pending = len(targets) > 1

    def confirm_item(body):
        nonlocal preview_pending
        if preview_pending:
            body += "\n\n" + full_preview
            preview_pending = False
        return approve_item(body)

    if mode != "item" and not approve_batch(f"{scope}\n确认后将连续处理。\n\n{full_preview}", mode):
        status = "CANCELLED"
    else:
        try:
            for index, (invoice, old) in enumerate(targets):
                values = {"company_id": company, "invoice_no": invoice, "field": field, "new_value": value}
                body = f"{scope}\n第 {index + 1} / {len(targets)} 张\n{item_lines[index]}"
                status, request_id = _apply_target(
                    agent, message, values, period, old,
                    lambda: confirm_item(body) if mode == "item" else "confirm", checkpoint,
                )
                if coordinator.receipt["status"] == "WAITING_CONFIRMATION":
                    outcome = "NOT_SUBMITTED" if status in {"SKIPPED", "NO_CHANGE"} else status
                    coordinator.receipt = coordinator._receipt(outcome)
                agent.trace("invoice_batch.item", {"invoice_no": invoice, "status": status, "request_id": request_id})
                if status == "COMMITTED":
                    counts["committed"] += 1
                    details.append(f"{invoice}：已保存并回读")
                elif status in {"NO_CHANGE", "SKIPPED"}:
                    counts["skipped"] += 1
                    details.append(f"{invoice}：" + ("当前值已相同" if status == "NO_CHANGE" else "已跳过"))
                elif status == "CANCELLED":
                    details.append(f"{invoice}：已终止，未提交")
                    break
                else:
                    if status == "UNKNOWN_OUTCOME":
                        counts["unknown"] += 1
                        details.append(f"{invoice}：结果未知，先查审计（请求编号 {request_id}）")
                    else:
                        counts["failed"] += 1
                        label = {"CONFLICT": "账期或原值变化", "DENIED": "权限或预览校验未通过",
                                 "NOT_FOUND": "找不到发票"}.get(status, "未能提交并核验")
                        details.append(f"{invoice}：{label}，已停止剩余处理")
                    break
            else:
                status = "COMPLETED"
        finally:
            agent.update_session.begin_turn("")
            coordinator.pending = None

    remaining = len(targets) - sum(counts.values())
    agent.trace("invoice_batch.finished", {"status": status, **counts, "unexecuted": remaining})
    summary = (f"{company} · {year:04d}-{month:02d} · 共 {len(targets)} 张\n"
               f"成功 {counts['committed']} · 跳过或无需变更 {counts['skipped']} · 失败 {counts['failed']} · "
               f"结果未知 {counts['unknown']} · 未执行 {remaining}")
    if counts["committed"] and status not in {"COMPLETED", "UNKNOWN_OUTCOME"}:
        status = "PARTIAL_RESULT"
    return status, "\n".join([summary, *details])
