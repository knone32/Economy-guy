"""不依赖语言模型的企业权限校验。"""
from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True)
class PermissionResult:
    allowed: bool
    reason: str


def check_permission(connection: sqlite3.Connection, user_id: str, company_id: str, operation: str) -> PermissionResult:
    """检查 read 或 modify 权限；未知对象和未知操作一律拒绝。"""
    if operation not in {"read", "modify"}:
        return PermissionResult(False, "不支持的操作类型")
    if not connection.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone():
        return PermissionResult(False, "未知用户")
    if not connection.execute("SELECT 1 FROM companies WHERE company_id = ?", (company_id,)).fetchone():
        return PermissionResult(False, "未知企业")
    row = connection.execute(
        "SELECT can_read, can_modify FROM permissions WHERE user_id = ? AND company_id = ?",
        (user_id, company_id),
    ).fetchone()
    if not row:
        return PermissionResult(False, "用户没有该企业权限")
    allowed = bool(row["can_read"] if operation == "read" else row["can_modify"])
    return PermissionResult(allowed, "允许" if allowed else "用户没有该操作权限")
