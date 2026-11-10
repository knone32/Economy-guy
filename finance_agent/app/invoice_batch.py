"""Run a fixed, human-approved invoice list through the existing single-item coordinator."""
from contextlib import closing
from dataclasses import asdict
import sqlite3
from uuid import uuid4

from .permissions import check_permission
from .queries import INVOICE_FIELD_LABELS, filter_monthly_invoices
from .rules import RuleError, check_missing_purpose
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


def run_invoice_batch(agent, message, request, *, approve_batch, approve_item, checkpoint):
    company, year, month = (request[key] for key in ("company_id", "year", "month"))
    selector, field, value, mode = (request[key] for key in ("selector", "field", "new_value", "mode"))
    coordinator = agent.coordinator
    if coordinator.receipt["status"] == "UNKNOWN_OUTCOME":
        return "UNKNOWN_OUTCOME", "上一次提交结果仍未知，请先核查审计。"

    agent.trace_id = uuid4().hex
    coordinator.begin(message)
    agent.trace("invoice_batch.started", {"company_id": company, "year": year, "month": month,
                                         "selector": selector, "field": field, "mode": mode})
    if not agent.workbook_available():
        return "ERROR", "工作账簿已变化，请重新打开。"
    try:
        with closing(open_existing(agent.db_path, readonly=True)) as db:
            db.execute("BEGIN")
            if any(not check_permission(db, agent.user_id, company, operation).allowed
                   for operation in ("read", "modify")):
                return "DENIED", "你没有该企业的读取和修改权限，未创建批量草稿。"
            if selector == "required_purpose_missing":
                rows = check_missing_purpose(db, agent.user_id, company, year, month)["missing_invoices"]
            else:
                rows = filter_monthly_invoices(db, agent.user_id, company, year, month, selector,
                                               limit=MAX_BATCH_INVOICES + 1)
            targets = tuple((row["invoice_no"], row[field]) for row in rows)
    except (OSError, ValueError, sqlite3.Error) as error:
        detail = str(error) if isinstance(error, RuleError) else "无法读取或核验本次筛选，请检查账簿及年月。"
        return "ERROR", detail
    if not targets:
        return "NO_DATA", "没有符合筛选条件的发票，未执行修改。"
    if len(targets) > MAX_BATCH_INVOICES:
        return "INVALID_ARGUMENTS", f"本次超过 {MAX_BATCH_INVOICES} 张的处理上限，请缩小范围。"

    field_label = "用途" if field == "purpose" else "备注"
    scope = f"企业　{company} · {year:04d}-{month:02d}\n筛选　{INVOICE_FIELD_LABELS[selector]}\n字段　{field_label}"
    item_lines = [f"{invoice}\n原值　{_preview(old)}\n新值　{_preview(value)}" for invoice, old in targets]
    if redact(item_lines) != item_lines:
        return "DENIED", "预览含有需隐藏的内容，无法进行完整核对，未提交。"

    counts = {"committed": 0, "skipped": 0, "failed": 0, "unknown": 0}
    details = []
    status = "COMPLETED"
    if mode != "item" and not approve_batch(scope + f"\n共 {len(targets)} 张，确认后将连续处理。\n\n"
                                            + "\n\n".join(item_lines), mode):
        status = "CANCELLED"
    else:
        try:
            for index, (invoice, old) in enumerate(targets):
                values = {"company_id": company, "invoice_no": invoice, "field": field, "new_value": value}
                body = f"{scope}\n第 {index + 1} / {len(targets)} 张\n{item_lines[index]}"
                status, request_id = _apply_target(
                    agent, message, values, f"{year:04d}-{month:02d}", old,
                    lambda: approve_item(body) if mode == "item" else "confirm", checkpoint,
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
