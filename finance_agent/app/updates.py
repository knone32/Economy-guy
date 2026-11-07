"""受控发票更新：Prepare -> CLI确认 -> Commit与审计 -> 新连接回读。"""
from dataclasses import dataclass, field as dataclass_field, asdict
import hashlib
import json
import sqlite3
from uuid import uuid4
from .permissions import check_permission
from .queries import get_invoice
from .stage2_schema import open_existing

FIELDS = {"purpose", "remark"}

def current_target_matches(path,user_id,company_id,invoice_no,field,new_value):
    """仅核对当前值和修改权限，不执行Prepare/Commit或新增审计。"""
    connection=open_existing(path,readonly=True)
    try:
        if field not in FIELDS or not check_permission(connection,user_id,company_id,'modify').allowed:return None
        current=get_invoice(connection,user_id,company_id,invoice_no)
        if current and current[field]==new_value:
            return {'current_invoice':current,'field':field,'target_value':new_value,'source':'current_sqlite','committed_this_turn':False}
        return None
    finally:connection.close()


def result(status, data=None, error=None):
    """业务结果不依赖 LLM 消息格式。"""
    return {"ok": status in {"WAITING_CONFIRMATION", "COMMITTED", "NO_CHANGE", "SUCCESS"},
            "status": status, "data": data, "evidence": {}, "error": error}


@dataclass(frozen=True)
class Draft:
    request_id: str
    session_id: str
    turn_id: str
    actor: str
    company_id: str
    invoice_no: str
    field: str
    old_value: str | None
    new_value: str
    source_request: str

    def fingerprint(self):
        """内容指纹绑定身份、目标、旧值、新值及本轮来源。"""
        payload = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class UpdateSession:
    """由可信 CLI 创建；确认不持久化，不从模型消息读取。"""
    user_id: str
    session_id: str = dataclass_field(default_factory=lambda: uuid4().hex)
    turn_id: str = ""
    source_request: str = ""
    # 用户通过CLI明确允许本轮提出草稿；这不是最终写入确认。
    allow_prepare: bool = False
    drafts: dict = dataclass_field(default_factory=dict)
    confirmations: dict = dataclass_field(default_factory=dict)
    expected_scope: dict | None = None
    explicit_edit_only: bool = False

    def begin_turn(self, request, allow_prepare=False, expected_scope=None, explicit_edit_only=False):
        self.turn_id = uuid4().hex
        self.source_request = request
        self.allow_prepare = allow_prepare
        self.expected_scope = expected_scope
        self.explicit_edit_only = explicit_edit_only
        self.drafts.clear()
        self.confirmations.clear()


def prepare_invoice_update(path, session, company_id, invoice_no, field, new_value, expected_scope=None):
    """精确定位并展示旧值，只创建本会话草稿，不写发票。"""
    if not session or not session.allow_prepare or not session.source_request.strip():
        return result("DENIED", error="本轮未在可信CLI声明修改意图")
    if field not in FIELDS or type(new_value) is not str:
        return result("INVALID_ARGUMENTS", error="只允许purpose/remark文本")
    connection = open_existing(path, readonly=True)
    try:
        if not check_permission(connection, session.user_id, company_id, "modify").allowed:
            return result("DENIED", error="没有修改权限")
        scopes = [scope for scope in (session.expected_scope,expected_scope) if scope is not None]
        if scopes:
            scope = {}
            for constraint in scopes:
                if constraint.get("_conflict"):
                    scope["_conflict"] = True
                for key in ("company_id","invoice_no"):
                    if key in constraint:
                        if key in scope and scope[key] != constraint[key]:
                            scope["_conflict"] = True
                        else:
                            scope[key] = constraint[key]
            mismatch = scope.get("_conflict") or any(key in scope and actual not in scope[key] for key,actual in (("company_id",company_id),("invoice_no",invoice_no)))
            if mismatch:
                return result("SCOPE_MISMATCH", error="范围不一致：目标与可信修改意图不同，请重新明确更正")
            if any(len(scope.get(key,[])) != 1 for key in ("company_id","invoice_no")):
                return result("AMBIGUOUS", error="请明确唯一企业与发票编号，不允许模型猜测目标")
        invoice = get_invoice(connection, session.user_id, company_id, invoice_no)
        if not invoice:
            return result("NOT_FOUND", error="指定企业中没有该发票")
        draft = Draft(uuid4().hex, session.session_id, session.turn_id, session.user_id,
                      company_id, invoice_no, field, invoice[field], new_value, session.source_request)
        session.drafts[draft.request_id] = draft
        return result("WAITING_CONFIRMATION", {**asdict(draft), "fingerprint": draft.fingerprint(), "current_invoice": invoice})
    finally:
        connection.close()


def confirm_draft(session, request_id, fingerprint):
    """仅由可信 CLI 在展示完整草稿后调用，不注册为模型工具。"""
    draft = session.drafts.get(request_id)
    if not draft or draft.session_id != session.session_id or draft.turn_id != session.turn_id or draft.fingerprint() != fingerprint:
        return False
    session.confirmations[request_id] = fingerprint
    return True


def _readback(path, user_id, audit):
    connection = open_existing(path, readonly=True)
    try:
        if not check_permission(connection, user_id, audit["company_id"], "modify").allowed:
            return result("DENIED", error="回读时权限已失效")
        invoice = get_invoice(connection, user_id, audit["company_id"], audit["invoice_no"])
        return result(audit["status"], {"request_id": audit["request_id"], "historical_commit": dict(audit),
                     "current_invoice": invoice,
                     "current_matches": invoice is not None and invoice[audit["field"]] == audit["new_value"]})
    finally:
        connection.close()


def inspect_request(path, user_id, request_id):
    """未知结果或重启后先查审计，再以新连接回读；绝不重写。"""
    connection = open_existing(path, readonly=True)
    try:
        audit = connection.execute("SELECT * FROM invoice_audit WHERE request_id=? AND actor=?", (request_id, user_id)).fetchone()
        if not audit:
            return result("NOT_FOUND", error="没有本用户的成功审计；不得据此自动重写")
    finally:
        connection.close()
    return _readback(path, user_id, audit)


def commit_invoice_update(path, session, request_id):
    """事务内鉴权、核对指纹/旧值，UPDATE与成功审计同事务。"""
    draft = session.drafts.get(request_id)
    if (not draft or draft.actor != session.user_id or draft.session_id != session.session_id
            or draft.turn_id != session.turn_id or draft.field not in FIELDS
            or session.confirmations.get(request_id) != draft.fingerprint()):
        return result("DENIED", error="没有绑定本会话草稿的最终确认")
    connection = open_existing(path)
    commit_started = False
    try:
        connection.execute("BEGIN IMMEDIATE")
        if not check_permission(connection, session.user_id, draft.company_id, "modify").allowed:
            return result("DENIED", error="提交时没有修改权限")
        audit = connection.execute("SELECT * FROM invoice_audit WHERE request_id=?", (request_id,)).fetchone()
        if audit:
            if audit["fingerprint"] != draft.fingerprint() or audit["actor"] != session.user_id:
                return result("CONFLICT", error="request_id与内容指纹冲突")
            connection.rollback()
            return _readback(path, session.user_id, audit)
        invoice = get_invoice(connection, session.user_id, draft.company_id, draft.invoice_no)
        if not invoice:
            return result("NOT_FOUND", error="发票不存在")
        if invoice[draft.field] != draft.old_value:
            return result("CONFLICT", error="当前值与已展示旧值不同，请重新准备并确认")
        status = "NO_CHANGE" if draft.old_value == draft.new_value else "COMMITTED"
        if status == "COMMITTED":
            # field只能来自内部白名单；所有值均参数化。
            connection.execute(f"UPDATE invoices SET {draft.field}=? WHERE company_id=? AND invoice_no=?",
                               (draft.new_value, draft.company_id, draft.invoice_no))
        connection.execute("""INSERT INTO invoice_audit
            (request_id,fingerprint,actor,company_id,invoice_no,field,old_value,new_value,status)
            VALUES (?,?,?,?,?,?,?,?,?)""", (request_id, draft.fingerprint(), session.user_id, draft.company_id,
            draft.invoice_no, draft.field, draft.old_value, draft.new_value, status))
        commit_started = True
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        if not commit_started:
            return result("ERROR", error="更新或审计失败，事务已回滚")
        # COMMIT结果不明，仅核查历史，不执行第二次UPDATE。
        try:
            checked = inspect_request(path, session.user_id, request_id)
            if checked["status"] in {"COMMITTED", "NO_CHANGE"}:
                return checked
        except sqlite3.Error:
            pass
        return result("UNKNOWN_OUTCOME", {"request_id": request_id}, "提交结果未知，请先查审计")
    finally:
        connection.close()
    try:
        return inspect_request(path, session.user_id, request_id)
    except sqlite3.Error:
        return result("UNKNOWN_OUTCOME", {"request_id": request_id}, "已尝试提交，回读失败；先查审计")
