"""Read-only menu views and atomic publication of newly initialized work databases."""
from contextlib import closing
from hashlib import sha256
import os
import sqlite3
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from zipfile import BadZipFile

from openpyxl.utils.exceptions import InvalidFileException

from .importer import initialize_database
from .permissions import check_permission
from .rules import SEED_RULES, import_rules
from .stage2_schema import STAGE2_DDL, open_existing
from .stage3_schema import STAGE3_DDL
from .references import REFERENCE_DDL


MIGRATED_TABLES = {"invoice_audit", "rules", "rule_management_audit", "tasks", "preferences", "reference_anchors"}


def missing_migrations(path):
    with closing(open_existing(path, readonly=True)) as db:
        return MIGRATED_TABLES - {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


BASE_COLUMNS = {
    "companies": "company_id,name,short_name",
    "users": "user_id,name",
    "permissions": "user_id,company_id,can_read,can_modify",
    "invoices": "company_id,invoice_no,invoice_date,seller_name,item_name,amount_cents,purpose,remark",
    "bank_transactions": "company_id,transaction_no,transaction_date,direction,amount_cents,counterparty_name,remark",
}


def _snapshot(db, tables):
    hashes = {}
    for table in sorted(tables):
        digest = sha256()
        for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
            digest.update(repr(tuple(row)).encode("utf-8") + b"\n")
        hashes[table] = digest.hexdigest()
    return hashes


def upgrade_workspace(path, *, backup=False):
    """Keep the original transaction intact until the backup and row checks succeed."""
    path = Path(path)
    workspace_users(path)
    ddl = STAGE2_DDL + STAGE3_DDL + REFERENCE_DDL
    with closing(open_existing(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        preserved = set(BASE_COLUMNS) | (MIGRATED_TABLES - missing_migrations(path))
        before = _snapshot(db, preserved)
        copy = None
        if backup:
            with NamedTemporaryFile(prefix=f"{path.stem}-backup-", suffix=".sqlite3", dir=path.parent,
                                    delete=False) as target:
                copy = Path(target.name)
            try:
                with closing(open_existing(path, readonly=True)) as source, closing(sqlite3.connect(copy)) as dest:
                    source.backup(dest)
                    if dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or _snapshot(dest, preserved) != before:
                        raise ValueError("无法验证备份，原账簿未升级。")
            except Exception:
                copy.unlink(missing_ok=True)
                raise
        for statement in ddl.split(";"):
            if statement.strip():
                db.execute(statement)
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if MIGRATED_TABLES - tables or _snapshot(db, preserved) != before:
            raise ValueError("升级验证未通过，原账簿已回滚。")
    return copy


def rules_available(path):
    with closing(open_existing(path, readonly=True)) as db:
        return bool(db.execute("SELECT 1 FROM rules WHERE status='ACTIVE' LIMIT 1").fetchone())


def workspace_users(path):
    """Validate the base schema without opening a write connection or creating a database."""
    with closing(open_existing(path, readonly=True)) as db:
        for table, columns in BASE_COLUMNS.items():
            db.execute(f"SELECT {columns} FROM {table} LIMIT 0")
        users = db.execute("SELECT user_id,name FROM users ORDER BY user_id").fetchall()
        if not users:
            raise ValueError("工作库没有模拟用户。请选择含有效企业与用户表的工作库。")
        return [dict(row) for row in users]


def company_access(path, user):
    with closing(open_existing(path, readonly=True)) as db:
        companies = []
        for row in db.execute("SELECT company_id,name FROM companies ORDER BY company_id"):
            read = check_permission(db, user, row["company_id"], "read").allowed
            modify = check_permission(db, user, row["company_id"], "modify").allowed
            if read or modify:
                companies.append(dict(row, read=read, modify=modify))
        return companies


def invoice_history(path, user):
    """Scope success history to its actor and recheck the current enterprise read ACL."""
    with closing(open_existing(path, readonly=True)) as db, db:
        db.execute("BEGIN")
        return [dict(row) for row in db.execute(
            """SELECT request_id,company_id,invoice_no,field,old_value,new_value,status,committed_at
               FROM invoice_audit WHERE actor=? AND status='COMMITTED'
               ORDER BY committed_at DESC, rowid DESC""", (user,))
            if check_permission(db, user, row["company_id"], "read").allowed][:20]


def rule_history(path, capabilities):
    if "rule.manage" not in capabilities:
        raise PermissionError("规则操作审计需要独立的模拟管理员入口。")
    with closing(open_existing(path, readonly=True)) as db:
        return [dict(row) for row in db.execute(
            """SELECT occurred_at,actor,operation,rule_id,version,old_status,new_status,result
               FROM rule_management_audit WHERE result='SUCCESS_CHANGED'
               ORDER BY occurred_at DESC, rowid DESC LIMIT 20""")]


def import_workspace(excel, target):
    """Validate in a private sibling directory, then atomically publish without replacing."""
    excel, target = Path(excel), Path(target)
    if not excel.is_file():
        raise ValueError("Excel 文件不存在。请核对路径后重试。")
    if excel.suffix.lower() != ".xlsx":
        raise ValueError("只支持官方或兼容结构的 .xlsx 文件。请使用官方模板核对工作表与字段。")
    if os.path.lexists(target):
        raise FileExistsError("目标工作库已存在。请选择一个新路径。")
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".finance-home-import-", dir=target.parent) as stage:
        candidate = Path(stage) / "workspace.db"
        try:
            counts = initialize_database(excel, candidate)
        except (BadZipFile, InvalidFileException, KeyError, StopIteration, IndexError) as error:
            raise ValueError("Excel 无法按官方结构读取。请核对文件、企业与用户权限表及必需字段。") from error
        upgrade_workspace(candidate)
        # The new private database needs official seed rules, not rights on an existing database.
        import_rules(candidate, SEED_RULES, {"rule.manage"}, actor="workspace_initializer", operation="seed")
        workspace_users(candidate)
        os.link(candidate, target)
    return counts
