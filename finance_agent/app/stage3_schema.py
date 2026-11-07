"""Stage 3A仅新增任务、偏好和未完成任务唯一索引。"""
from .stage2_schema import open_existing


STAGE3_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, company_id TEXT NOT NULL,
  task_type TEXT NOT NULL CHECK(task_type='missing_purpose'),
  year INTEGER NOT NULL, month INTEGER NOT NULL CHECK(month BETWEEN 1 AND 12),
  context_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('ACTIVE','WAITING_USER','PAUSED','COMPLETED','CANCELLED')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES users(user_id),
  FOREIGN KEY(company_id) REFERENCES companies(company_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_unfinished_task_per_user_company
  ON tasks(user_id,company_id) WHERE status IN ('ACTIVE','WAITING_USER','PAUSED');
CREATE TABLE IF NOT EXISTS preferences (
  user_id TEXT NOT NULL, company_id TEXT NOT NULL, preference_key TEXT NOT NULL,
  value TEXT NOT NULL, explicit_request TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(user_id,company_id,preference_key),
  FOREIGN KEY(user_id) REFERENCES users(user_id),
  FOREIGN KEY(company_id) REFERENCES companies(company_id)
);
"""


def migrate(path):
    """加法迁移，可重复执行，不覆盖既有业务库。"""
    connection = open_existing(path)
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + STAGE3_DDL + "COMMIT;")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
