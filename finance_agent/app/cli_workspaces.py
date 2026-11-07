"""Read-only menu views and atomic publication of newly initialized work databases."""
from contextlib import closing
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile

from openpyxl.utils.exceptions import InvalidFileException

from .importer import initialize_database
from .permissions import check_permission
from .rules import SEED_RULES, import_rules
from .stage2_schema import migrate as migrate_rules, open_existing
from .stage3_schema import migrate as migrate_state
from .references import migrate as migrate_references


MIGRATED_TABLES = {"invoice_audit", "rules", "rule_management_audit", "tasks", "preferences", "reference_anchors"}


def missing_migrations(path):
    with closing(open_existing(path, readonly=True)) as db:
        return MIGRATED_TABLES - {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def upgrade_workspace(path):
    """Apply only the existing additive migrations to an explicitly selected database."""
    migrate_rules(path)
    migrate_state(path)
    migrate_references(path)


def workspace_users(path):
    """Validate the base schema without opening a write connection or creating a database."""
    with closing(open_existing(path, readonly=True)) as db:
        for table in ("companies", "permissions", "invoices", "bank_transactions"):
            db.execute(f"SELECT * FROM {table} LIMIT 0")
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
