"""版本规则存储和唯一适用规则解析；不解释任意规则代码。"""
from dataclasses import dataclass, asdict
from datetime import date
import json
from decimal import Decimal
from uuid import uuid4
from .permissions import check_permission
from .queries import get_invoice, list_invoices
from .stage2_schema import open_existing


class RuleError(ValueError):
    """无规则、冲突或非法规则时明确拒绝。"""


def canonical_content(rule_type, params):
    """有限类型的正文由执行参数生成，禁止正文和执行门槛分离。"""
    if rule_type == "amount" and params == {"unit": "cents", "separate_bank": True} and params["separate_bank"] is True:
        return "发票按价税合计；银行收入、支出分别统计，不抵销；整数分计算，元保留两位。"
    if rule_type == "bank" and params == {"readonly": True} and params["readonly"] is True:
        return "银行资料全部只读，企业编号与流水编号共同定位，不与发票逐条匹配。"
    if rule_type == "purpose" and set(params) == {"mode", "threshold_cents"}:
        threshold = params["threshold_cents"]
        if type(threshold) is not int or threshold < 0:
            raise RuleError("用途门槛必须是非负整数分")
        if params["mode"] == "all" and threshold == 0:
            return "每张发票用途必填；空白字符视为未填，备注不能代替用途。"
        if params["mode"] == "threshold":
            return f"金额大于或等于{threshold}分的发票用途必填；空白字符视为未填，备注不能代替用途。"
    raise RuleError("规则类型或执行参数不受支持")


def make_rule(rule_id, version, name, scope, effective, status, rule_type, params):
    return {"rule_id": rule_id, "version": version, "name": name, "company_scope": scope,
            "effective_from": effective, "status": status, "rule_type": rule_type,
            "params": params, "content": canonical_content(rule_type, params)}


SEED_RULES = [
    make_rule("R001", "1.0", "金额统计说明", "*", "2026-01-01", "ACTIVE", "amount", {"unit":"cents", "separate_bank":True}),
    make_rule("R002", "1.0", "甲企业发票用途规则", "C001", "2026-08-01", "DISABLED", "purpose", {"mode":"threshold", "threshold_cents":100000}),
    make_rule("R002", "2.0", "甲企业发票用途规则", "C001", "2026-09-01", "ACTIVE", "purpose", {"mode":"all", "threshold_cents":0}),
    make_rule("R003", "1.0", "乙企业发票用途规则", "C002", "2026-08-01", "ACTIVE", "purpose", {"mode":"threshold", "threshold_cents":100000}),
    make_rule("R004", "1.0", "银行资料说明", "*", "2026-01-01", "ACTIVE", "bank", {"readonly":True}),
]


def _validated(rule):
    if type(rule) is not dict or set(rule) != set(SEED_RULES[0]):
        raise RuleError("规则字段不完整或含未知字段")
    for key in set(rule) - {"params"}:
        if type(rule[key]) is not str or not rule[key].strip():
            raise RuleError("规则文本字段无效")
    date.fromisoformat(rule["effective_from"])
    if rule["status"] not in {"ACTIVE", "DISABLED"} or type(rule["params"]) is not dict:
        raise RuleError("规则状态或参数无效")
    if rule["content"] != canonical_content(rule["rule_type"], rule["params"]):
        raise RuleError("正文与执行参数不一致")
    return tuple(rule[k] for k in ("rule_id", "version", "name", "company_scope", "effective_from", "status", "rule_type")) + (json.dumps(rule["params"], sort_keys=True, ensure_ascii=False), rule["content"])


def _require_rule_audit(connection):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rule_management_audit'").fetchone():
        raise RuleError("规则审计表缺失，请先执行 migrate-stage2")


def _audit_rule_change(connection, actor, operation, rule_id, version, old_status, new_status):
    row = connection.execute("""INSERT INTO rule_management_audit
        (event_id,actor,operation,rule_id,version,old_status,new_status,result)
        VALUES (?,?,?,?,?,?,?,'SUCCESS_CHANGED')""",
        (uuid4().hex, actor, operation, rule_id, version, old_status, new_status))
    if row.rowcount != 1:
        raise RuleError("数据库未写入规则审计，已撤销本次变更")


def _change_result(changed, unchanged):
    return {"status": "SUCCESS_CHANGED" if changed else "NO_CHANGE", "changed": changed, "unchanged": unchanged}


def import_rules(path, rules, capabilities=frozenset(), *, actor="trusted_python_rule_manager", operation="import",
                 source_ref=None, supersedes=None):
    """独立 rule.manage 授权，整批规则与成功审计原子提交。"""
    if "rule.manage" not in capabilities:
        raise PermissionError("缺少独立 rule.manage 权限")
    if operation not in {"seed", "import"}:
        raise RuleError("规则导入操作无效")
    records = [_validated(rule) for rule in rules]
    if source_ref is not None and len(records) != 1:
        raise RuleError("一次资料发布必须恰好一条规则")
    if supersedes is not None and source_ref is None:
        raise RuleError("截止旧版必须绑定发布资料")
    changed = 0
    connection = open_existing(path)
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_rule_audit(connection)
            if source_ref is not None:
                from .materials import get_paragraph
                if type(source_ref) is not dict or set(source_ref) != {"material_id", "version", "paragraph_id"}:
                    raise RuleError("资料引用必须精确指定版本原段")
                paragraph = get_paragraph(connection, actor, **source_ref)
                if paragraph["company_id"] != records[0][3] or records[0][5] != "ACTIVE":
                    raise RuleError("发布规则必须启用且与资料企业一致")
                if not paragraph["text"].strip():
                    raise RuleError("不能发布空白原段")
                # Publishing establishes an explicit human-managed association; no LLM inference.
                existing_source = connection.execute("SELECT material_id,version,paragraph_id FROM rule_material_sources WHERE rule_id=? AND rule_version=?", records[0][:2]).fetchone()
                if existing_source and dict(existing_source) != source_ref:
                    raise RuleError("同号同版资料引用冲突")
                if supersedes is not None:
                    old_rule = connection.execute("SELECT r.*,s.effective_to FROM rules r JOIN rule_material_sources s ON r.rule_id=s.rule_id AND r.version=s.rule_version WHERE r.rule_id=? AND r.version=?", tuple(supersedes)).fetchone()
                    new = records[0]
                    if (old_rule is None or old_rule["rule_id"] != new[0] or old_rule["version"] == new[1]
                            or old_rule["company_scope"] != new[3] or old_rule["rule_type"] != new[6]
                            or old_rule["effective_from"] >= new[4]
                            or old_rule["effective_to"] not in (None, new[4])):
                        raise RuleError("旧版截止关系无效或冲突")
                    if existing_source is not None and old_rule["effective_to"] is None:
                        raise RuleError("既有发布不可事后更改旧版有效区间")
                    connection.execute("UPDATE rule_material_sources SET effective_to=? WHERE rule_id=? AND rule_version=?", (new[4], *supersedes))
            for record in records:
                if record[3] != "*" and not connection.execute("SELECT 1 FROM companies WHERE company_id=?", (record[3],)).fetchone():
                    raise RuleError("规则企业不存在")
                old = connection.execute("SELECT * FROM rules WHERE rule_id=? AND version=?", record[:2]).fetchone()
                if old:
                    if tuple(old) != record:
                        raise RuleError("同号同版规则冲突，不覆盖旧版")
                    continue
                row = connection.execute("""INSERT INTO rules (rule_id,version,name,company_scope,effective_from,status,rule_type,params_json,content)
                    VALUES (?,?,?,?,?,?,?,?,?)""", record)
                if row.rowcount != 1:
                    raise RuleError("数据库未写入规则，已撤销本次变更")
                _audit_rule_change(connection, actor, operation, record[0], record[1], None, record[5])
                changed += 1
            if source_ref is not None and existing_source is None:
                if not changed:
                    raise RuleError("不能为既有规则事后替换来源；请发布新版本")
                connection.execute("INSERT INTO rule_material_sources (rule_id,rule_version,material_id,version,paragraph_id) VALUES (?,?,?,?,?)",
                                   (*records[0][:2], source_ref["material_id"], source_ref["version"], source_ref["paragraph_id"]))
    finally:
        connection.close()
    return _change_result(changed, len(records) - changed)


def publish_material_rule(path, rule, source_ref, capabilities=frozenset(), *, actor, supersedes=None):
    """Trusted explicit management entry; upload alone cannot activate a rule.

    supersedes names an older published version and closes its interval at the
    new effective_from (exclusive). Without it overlapping ACTIVE rules conflict.
    """
    return import_rules(path, [rule], capabilities, actor=actor, source_ref=source_ref, supersedes=supersedes)


def disable_rule(path, rule_id, version, capabilities=frozenset(), *, actor="trusted_python_rule_manager"):
    if "rule.manage" not in capabilities:
        raise PermissionError("缺少独立 rule.manage 权限")
    connection = open_existing(path)
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_rule_audit(connection)
            key = (rule_id, version)
            old = connection.execute("SELECT status FROM rules WHERE rule_id=? AND version=?", key).fetchone()
            if old is None:
                raise RuleError("规则不存在")
            if old["status"] == "DISABLED":
                return _change_result(0, 1)
            row = connection.execute("UPDATE rules SET status='DISABLED' WHERE rule_id=? AND version=?", key)
            if row.rowcount != 1:
                raise RuleError("数据库未更新规则，已撤销本次变更")
            _audit_rule_change(connection, actor, "disable", rule_id, version, old["status"], "DISABLED")
    finally:
        connection.close()
    return _change_result(1, 0)


def find_rules(path, capabilities=frozenset()):
    if "rule.manage" not in capabilities:
        raise PermissionError("缺少独立 rule.manage 权限")
    connection = open_existing(path, readonly=True)
    try:
        return [dict(row) for row in connection.execute("SELECT * FROM rules ORDER BY rule_id,version")]
    finally:
        connection.close()


@dataclass(frozen=True)
class RuleDecision:
    rule_id: str
    version: str
    name: str
    company_scope: str
    effective_from: str
    rule_type: str
    params: dict
    content: str
    # 兼容补充官方限制，不覆盖持久化同号同版正文或执行参数。
    explanation: tuple[str, ...] = ()
    source: dict | None = None


OFFICIAL_NOTES = {
    "amount": (
        "来源：官方业务规则1.1.0 R001 v1.0；按发票日期或银行交易日期确定年月，月份不明先追问。",
        "是否填写用途不影响发票金额；不拆税额；发票、银行收入与支出分别统计，不要求相等。",
        "成功无记录才为0.00；无权限或异常不是零；当前SQLite为事实来源。",
        "不根据金额、日期、交易方认定某张发票已经付款。",
    ),
    "purpose": (
        "来源：官方业务规则1.1.0；待办账期为2026-09，已停用的历史用途规则不恢复。",
        "以本RuleDecision的mode/threshold_cents执行，等于门槛也必填；空白字符为未填，备注不能替代。",
        "不从销售方或票面项目推测用途。修改仅限用户明确要求的用途/备注，须授权、确认、提交后回读。",
        "已停用版本不作当前依据；不同企业不能混用规则。",
    ),
    "bank": (
        "来源：官方业务规则1.1.0 R004 v1.0；企业与流水号共同定位，交易日期决定年月。",
        "收入、支出金额均为正数，分开统计，支出不再加负号；全部银行字段只读。",
        "对方名称和备注不能证明发票已付款，流水与发票不逐条对应；必须鉴权。",
    ),
}


def resolve_rule(connection, user_id, company_id, rule_type, business_date):
    """按企业、日期、启用状态筛出唯一依据，不擅自选择最高版本。"""
    if not check_permission(connection, user_id, company_id, "read").allowed:
        raise PermissionError("没有读取权限")
    if type(business_date) is not str or date.fromisoformat(business_date).isoformat() != business_date:
        raise RuleError("business_date必须为严格YYYY-MM-DD日期")
    rows = connection.execute("""SELECT * FROM rules WHERE (company_scope=? OR company_scope='*')
        AND rule_type=? AND status='ACTIVE' AND effective_from<=?""", (company_id, rule_type, business_date)).fetchall()
    sources = {}
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='rule_material_sources' AND type='table'").fetchone():
        sources = {(r["rule_id"], r["rule_version"]): dict(r) for r in connection.execute("SELECT * FROM rule_material_sources")}
        rows = [row for row in rows if not sources.get((row["rule_id"], row["version"]), {}).get("effective_to")
                or business_date < sources[(row["rule_id"], row["version"])]["effective_to"]]
    if not rows:
        raise RuleError("NO_APPLICABLE_RULE")
    if len(rows) != 1:
        raise RuleError("RULE_CONFLICT")
    row = dict(rows[0])
    params = json.loads(row.pop("params_json"))
    if row.pop("status") != "ACTIVE" or row["content"] != canonical_content(rule_type, params):
        raise RuleError("RULE_CONFLICT")
    source = sources.get((row["rule_id"], row["version"]))
    if source:
        source = {key: source[key] for key in ("material_id", "version", "paragraph_id")}
        # Executable rules use enterprise read ACL; opening private originals
        # independently rechecks ownership in materials.get_paragraph.
    return RuleDecision(**row, params=params, explanation=OFFICIAL_NOTES[rule_type], source=source)


def missing_required_purpose(params, invoice):
    required = params["mode"] == "all" or int(Decimal(invoice["amount"]) * 100) >= params["threshold_cents"]
    return required and not (invoice["purpose"] or "").strip()


def check_missing_purpose(connection, user_id, company_id, year, month, rule_business_date=None):
    """Read the full target month and apply the rule effective on the chosen date."""
    target_start = date(year, month, 1).isoformat()
    reference_date = rule_business_date if rule_business_date is not None else target_start
    decision = resolve_rule(connection, user_id, company_id, "purpose", reference_date)
    invoices = list_invoices(connection, user_id, company_id, year, month)
    missing = [invoice for invoice in invoices if missing_required_purpose(decision.params, invoice)]
    return {"missing_invoices": missing, "count": len(missing), "rule": asdict(decision),
            "rule_business_date": reference_date, "target_year": year, "target_month": month,
            "reference_rule_screening": rule_business_date is not None}


def check_displayed_purpose(connection, user_id, company_id, periods, keys, rule_business_date):
    """Recheck the displayed invoice identities in the current authorized transaction."""
    decision = resolve_rule(connection, user_id, company_id, "purpose", rule_business_date)
    missing = []
    for company, number in keys:
        if company != company_id:
            raise RuleError("SCOPE_MISMATCH")
        invoice = get_invoice(connection, user_id, company, number)
        if invoice is None or tuple(map(int, invoice["invoice_date"][:7].split("-"))) not in periods:
            raise RuleError("STALE_REFERENCE")
        if missing_required_purpose(decision.params, invoice):
            missing.append(invoice)
    return {"missing_invoices": missing, "count": len(missing), "rule": asdict(decision),
            "rule_business_date": rule_business_date, "reference_rule_screening": True,
            "checked_count": len(keys)}
