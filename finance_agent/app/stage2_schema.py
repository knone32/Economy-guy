"""Stage 2 加法迁移：只新增表，不删除或重导业务数据。"""
from pathlib import Path
import sqlite3


def open_existing(path, readonly=False):
    """已有库连接，路径不存在时不创建空库。"""
    mode = "ro" if readonly else "rw"
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=" + mode, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


STAGE2_DDL = """
CREATE TABLE IF NOT EXISTS invoice_audit (
  request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
  actor TEXT NOT NULL, company_id TEXT NOT NULL, invoice_no TEXT NOT NULL,
  field TEXT NOT NULL CHECK(field IN ('purpose','remark')),
  old_value TEXT, new_value TEXT NOT NULL, status TEXT NOT NULL,
  committed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS rules (
  rule_id TEXT NOT NULL, version TEXT NOT NULL, name TEXT NOT NULL,
  company_scope TEXT NOT NULL, effective_from TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('ACTIVE','DISABLED')),
  rule_type TEXT NOT NULL, params_json TEXT NOT NULL, content TEXT NOT NULL,
  PRIMARY KEY(rule_id,version)
);
CREATE TABLE IF NOT EXISTS rule_management_audit (
  event_id TEXT PRIMARY KEY, actor TEXT NOT NULL,
  operation TEXT NOT NULL CHECK(operation IN ('seed','import','disable')),
  rule_id TEXT NOT NULL, version TEXT NOT NULL,
  old_status TEXT CHECK(old_status IN ('ACTIVE','DISABLED')),
  new_status TEXT NOT NULL CHECK(new_status IN ('ACTIVE','DISABLED')),
  result TEXT NOT NULL CHECK(result = 'SUCCESS_CHANGED'),
  occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def migrate(path):
    """显式、可重复的加法迁移，不修改已有发票或银行记录。"""
    connection = open_existing(path)
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + STAGE2_DDL + "COMMIT;")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
