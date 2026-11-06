"""企业范围内用户明确要求的偏好CRUD；偏好永远不是操作授权。"""
import sqlite3
from .permissions import check_permission
from .persistence import can_manage, result, require_management_confirmation
from .stage2_schema import open_existing


def manage_preference(path, user_id, company_id, action, key="", value="", intent=None):
    """每次鉴权，不自动从对话提取或保存偏好。"""
    if type(action) is not str or action not in {"create","get","list","update","delete"} or type(key) is not str or type(value) is not str:
        return result("INVALID_ARGUMENTS",error="偏好操作或参数无效")
    connection = open_existing(path)
    committing = False
    try:
        writing = action in {"create","update","delete"}
        connection.execute("BEGIN IMMEDIATE" if writing else "BEGIN")
        if not check_permission(connection,user_id,company_id,"read").allowed:
            return result("DENIED",error="没有企业读取权限")
        if writing and not can_manage(intent,user_id,"preference",action):
            return result("DENIED",error="本轮没有可信的明确偏好管理意图")
        if action == "list":
            rows = connection.execute("SELECT * FROM preferences WHERE user_id=? AND company_id=? ORDER BY preference_key",(user_id,company_id)).fetchall()
            return result("SUCCESS" if rows else "NO_DATA",[dict(row) for row in rows])
        if not key.strip() or (action in {"create","update"} and not value.strip()):
            return result("INVALID_ARGUMENTS",error="偏好名称和保存内容须明确")
        row = connection.execute("SELECT * FROM preferences WHERE user_id=? AND company_id=? AND preference_key=?",(user_id,company_id,key)).fetchone()
        if action == "create" and row:
            return result("CONFLICT",error="偏好已存在，需明确更新")
        if action != "create" and not row:
            return result("NOT_FOUND",error="当前用户企业范围内没有该偏好")
        if action == "get":
            return result("SUCCESS",dict(row))
        pending=require_management_confirmation(intent,{'company_id':company_id,'action':action,'key':key,'value':value},dict(row) if row else None)
        if pending:
            return pending
        if action == "create":
            connection.execute("INSERT INTO preferences (user_id,company_id,preference_key,value,explicit_request) VALUES (?,?,?,?,?)",(user_id,company_id,key,value,intent.source_request))
        elif action == "update":
            connection.execute("UPDATE preferences SET value=?,explicit_request=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=? AND company_id=? AND preference_key=?",(value,intent.source_request,user_id,company_id,key))
        else:
            connection.execute("DELETE FROM preferences WHERE user_id=? AND company_id=? AND preference_key=?",(user_id,company_id,key))
        row = connection.execute("SELECT * FROM preferences WHERE user_id=? AND company_id=? AND preference_key=?",(user_id,company_id,key)).fetchone()
        committing = True
        connection.commit()
        return result("SUCCESS",dict(row) if row else {"deleted_key":key},{"source":"current_sqlite","scope":{"company_id":company_id}})
    except sqlite3.Error:
        connection.rollback()
        return result("UNKNOWN_OUTCOME" if committing else "ERROR",{"key":key},error="偏好保存结果需查询核实" if committing else "偏好数据库操作失败，未确认成功")
    finally:
        connection.close()
