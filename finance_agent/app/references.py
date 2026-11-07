"""展示锚点的单一存储及当前发票重查；不保存业务字段或写入授权。"""
import json
import sqlite3
from uuid import uuid4
from .stage2_schema import open_existing
from .permissions import check_permission
from .queries import get_invoice
from .persistence import result


def migrate(path):
    """显式加法迁移；旧库不自动建表，不覆盖业务记录。"""
    connection = open_existing(path)
    try:
        with connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS reference_anchors (
                anchor_id TEXT PRIMARY KEY, display_id TEXT NOT NULL,
                user_id TEXT NOT NULL, company_id TEXT NOT NULL,
                year INTEGER, month INTEGER, source TEXT NOT NULL, keys_json TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(company_id) REFERENCES companies(company_id))""")
            connection.execute("CREATE INDEX IF NOT EXISTS reference_owner ON reference_anchors(user_id,active)")
    finally:
        connection.close()


def _available(connection):
    return bool(connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reference_anchors'").fetchone())


def record_display(path, user_id, display_id, groups):
    """仅由真实展示路径调用；按展示顺序保存联合键，不持久化用途、金额等旧值。"""
    connection = open_existing(path)
    try:
        with connection:
            if not _available(connection):
                return []
            anchors = []
            for group in groups:
                scope, keys = group["scope"], group["keys"]
                company = scope["company_id"]
                if not check_permission(connection,user_id,company,"read").allowed:
                    continue
                if not keys or any(key["company_id"] != company for key in keys):
                    raise ValueError("展示锚点必须使用同企业联合键")
                anchor_id = uuid4().hex
                connection.execute("""INSERT INTO reference_anchors
                    (anchor_id,display_id,user_id,company_id,year,month,source,keys_json)
                    VALUES (?,?,?,?,?,?,?,?)""", (anchor_id,display_id,user_id,company,
                    scope.get("year"),scope.get("month"),group["source"],json.dumps(keys)))
                anchors.append({"anchor_id":anchor_id,"scope":scope,"source":group["source"],"count":len(keys)})
            return anchors
    finally:
        connection.close()


def invalidate_references(path, user_id):
    """焦点更正/取消时使旧引用失效；不更改任务或已提交业务事实。"""
    connection = open_existing(path)
    try:
        with connection:
            if _available(connection):
                connection.execute("UPDATE reference_anchors SET active=0 WHERE user_id=? AND active=1",(user_id,))
    finally:
        connection.close()


def _candidates(connection, user_id, scope=None, anchor_id="",authorized_only=True):
    if not _available(connection):
        return []
    if anchor_id:
        rows = connection.execute("SELECT * FROM reference_anchors WHERE user_id=? AND active=1 AND anchor_id=?",(user_id,anchor_id)).fetchall()
    else:
        latest = connection.execute("SELECT display_id FROM reference_anchors WHERE user_id=? AND active=1 ORDER BY rowid DESC LIMIT 1",(user_id,)).fetchone()
        # 同一次展示有多个列表时不擅自挑选其中一个。
        rows = connection.execute("SELECT * FROM reference_anchors WHERE user_id=? AND active=1 AND display_id=? ORDER BY rowid",(user_id,latest["display_id"])).fetchall() if latest else []
    scope = scope or {}
    return [row for row in rows if all(key not in scope or row[key] in scope[key]
            for key in ("company_id","year","month")) and
            ("periods" not in scope or (row["year"], row["month"]) in scope["periods"]) and
            (not authorized_only or check_permission(connection,user_id,row["company_id"],"read").allowed)]


def reference_catalog(path, user_id, scope=None):
    """提供自己的可访问展示来源；元数据不是当前业务值。"""
    connection = open_existing(path,readonly=True)
    try:
        connection.execute("BEGIN")
        return [{"anchor_id":row["anchor_id"],"display_id":row["display_id"],
                 "scope":{key:row[key] for key in ("company_id","year","month") if row[key] is not None},
                 "source":row["source"],"count":len(json.loads(row["keys_json"]))}
                for row in _candidates(connection,user_id,scope)]
    finally:
        connection.close()


def resolve_reference(path, user_id, ordinal, scope=None, anchor_id=""):
    """先找用户实际展示锚点，再鉴权并重读SQLite；不足以唯一定位则追问。"""
    try:
        connection = open_existing(path,readonly=True)
    except sqlite3.Error:
        return result("ERROR",error="引用数据库不可用；未确认业务成功")
    try:
        connection.execute("BEGIN")
        scope = scope or {}
        for company in scope.get("company_id",[]):
            if not check_permission(connection,user_id,company,"read").allowed:
                return result("DENIED",error="没有企业读取权限")
        rows = _candidates(connection,user_id,scope,anchor_id,authorized_only=False)
        if len(rows) != 1:
            return result("AMBIGUOUS",error="没有唯一可信展示列表，请提供企业、年月或已展示的anchor编号")
        row = rows[0]
        if not check_permission(connection,user_id,row["company_id"],"read").allowed:
            return result("DENIED",error="没有企业读取权限")
        keys = json.loads(row["keys_json"])
        # “那张”仅能用于单对象展示；不根据模型猜测序号。
        if ordinal is None and len(keys) == 1:
            ordinal = 1
        if type(ordinal) is not int or not 1 <= ordinal <= len(keys):
            return result("AMBIGUOUS",error="引用序号不存在或对象不唯一，请明确发票")
        key = keys[ordinal-1]
        if not check_permission(connection,user_id,key["company_id"],"read").allowed:
            return result("DENIED",error="没有企业读取权限")
        current = get_invoice(connection,user_id,**key)
        evidence = {"source":"current_sqlite","reference":{"anchor_id":row["anchor_id"],
                    "display_id":row["display_id"],"source":row["source"],"ordinal":ordinal},"scope":dict(key)}
        if current is None:
            return result("NOT_FOUND",evidence=evidence,error="已展示对象当前不存在，请重新列出")
        evidence["scope"].update(year=int(current["invoice_date"][:4]),month=int(current["invoice_date"][5:7]))
        # 日期发生变化也不把旧列表月份冒充当前月份。
        current_scope = evidence["scope"]
        current_period = (current_scope["year"], current_scope["month"])
        anchor_changed = any(row[key] is not None and current_scope[key] != row[key]
                             for key in ("year", "month"))
        scope_changed = any(key in scope and value not in scope[key]
                            for key, value in current_scope.items())
        if anchor_changed or scope_changed or ("periods" in scope and current_period not in scope["periods"]):
            return result("SCOPE_MISMATCH",evidence=evidence,error="当前对象已不在引用范围，请重新列出")
        return result("SUCCESS",current,evidence)
    except sqlite3.Error:
        return result("ERROR",error="引用数据库不可用；未确认业务成功")
    finally:
        connection.close()
