"""Run a fixed, human-approved invoice list through the existing single-item coordinator."""
from contextlib import closing
from dataclasses import asdict
from datetime import date
import sqlite3

from .permissions import check_permission
from .queries import get_invoice
from .rules import missing_required_purpose
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


def plan_invoice_change(agent, source_request, proposal, selection, *, target_period=None,
                        rule_period=None, rule_outcome=None):
    """Validate current-turn scope and literal edit constraints without preparing a draft."""
    if selection is None:
        return None, "AMBIGUOUS", "请先取得本轮可信发票集合。"
    keys, scope, source = selection
    companies = {company for company, _ in keys}
    if len(companies) != 1:
        return None, "SCOPE_MISMATCH", "一次只能确认一家企业，请分企业请求修改。"
    company, = companies
    collection = source in {"query_business_sql", "check_missing_purpose"}
    requested = explicit_scope(source_request, include_update_aliases=True)
    if (requested.get("company_id") and requested["company_id"] != [company]
            or source == "query_business_sql" and tuple(scope["company_ids"]) != (company,)):
        return None, "SCOPE_MISMATCH", "候选集合与用户明确的企业不一致。"
    excluded = excluded_invoice_ids(source_request)
    invoice_nos = {invoice for _, invoice in keys}
    if source == "check_missing_purpose":
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
    if not invoice_change_evidence(source_request, proposal["field"], proposal["new_value"]):
        return None, "AMBIGUOUS", "请明确只改用途或备注，并提供该字段的具体新值。"
    if len(invoice_nos) > MAX_BATCH_INVOICES:
        return None, "INVALID_ARGUMENTS", f"本次超过 {MAX_BATCH_INVOICES} 张的处理上限，请缩小范围。"

    if collection and target_period is None:
        return None, "SCOPE_MISMATCH", "请明确要修改的发票目标年月。"
    rule = None
    if rule_period is not None:
        if (rule_outcome is None or rule_outcome["evidence"]["scope"]["company_id"] != company
                or source != "query_business_sql"):
            return None, "SCOPE_MISMATCH", "请先核验该企业参考月用途规则，再按它筛选目标月发票。"
        rule = rule_outcome["data"]

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
            if rule and any(not missing_required_purpose(rule["params"], row) for row in rows):
                return None, "SCOPE_MISMATCH", "清单含有不符合参考规则筛选条件的发票。"
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
        request["rule_reference"] = {"period": rule_period, "rule_id": rule["rule_id"],
                                     "version": rule["version"], "params": rule["params"]}
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
            if rule_reference and any(not missing_required_purpose(rule_reference["params"], row) for row in rows):
                return "CONFLICT", "发票已不符合参考规则筛选条件，未执行修改。"
            rows.sort(key=lambda row: (row["invoice_date"], row["invoice_no"]))
            targets = tuple((row["invoice_no"], row[field]) for row in rows)
    except (OSError, ValueError, sqlite3.Error):
        return "ERROR", "无法重新核验发票清单，请检查账簿。"

    field_label = "用途" if field == "purpose" else "备注"
    overwrites = sum(bool((old or "").strip()) and old != value for _, old in targets)
    scope = (f"企业　{company} · {period}\n字段　{field_label}\n"
             f"覆盖提示　将替换 {overwrites} 张发票已填写的{field_label}。")
    if rule_reference:
        rule_year, rule_month = rule_reference["period"]
        scope += (f"\n参考规则　{rule_year:04d}-{rule_month:02d} · "
                  f"{rule_reference['rule_id']} v{rule_reference['version']}"
                  f"\n发票目标账期　{period}"
                  "\n依据指定规则重新筛选，结果不代表目标账期的正式合规认定。")
    if request["excluded"]:
        scope += "\n明确排除　" + "、".join(request["excluded"])
    item_lines = [f"{invoice}\n原值　{_preview(old)}\n新值　{_preview(value)}" for invoice, old in targets]
    if redact(item_lines) != item_lines:
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
