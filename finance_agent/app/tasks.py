"""当前SQLite中的单用户×企业待办任务；没有任务树或调度引擎。"""
import json
import sqlite3
from uuid import uuid4
from .permissions import check_permission
from .persistence import can_manage, can_propose, result, require_management_confirmation
from .queries import list_invoices
from .rules import check_missing_purpose, RuleError
from .stage2_schema import open_existing

UNFINISHED = {"ACTIVE","WAITING_USER","PAUSED"}
ACTIONS = {"create","show","update","correct","wait","pause","resume","complete","cancel"}


class TaskPolicy:
    """应用层提前给出冲突说明，SQLite索引是最终并发保护。"""
    @staticmethod
    def unfinished(connection, user_id, company_id):
        return connection.execute("""SELECT task_id FROM tasks WHERE user_id=? AND company_id=?
            AND status IN ('ACTIVE','WAITING_USER','PAUSED')""", (user_id,company_id)).fetchone()


def _task(row):
    data = dict(row)
    data["context"] = json.loads(data.pop("context_json"))
    return data


def _check(connection, user_id, company_id, year, month):
    """恢复和完成都用当前规则/发票，不用任务文本证明完成。"""
    if type(year) is not int or type(month) is not int or (year,month) != (2026,9):
        raise ValueError("初赛任务仅支持2026-09用途检查")
    evidence = check_missing_purpose(connection,user_id,company_id,year,month)
    evidence["invoice_count"] = len(list_invoices(connection,user_id,company_id,year,month))
    return evidence


def list_tasks(path, user_id, company_id):
    """按当前身份与企业重查权限；不返回他人的任务。"""
    connection = open_existing(path,readonly=True)
    try:
        connection.execute("BEGIN")
        if not check_permission(connection,user_id,company_id,"read").allowed:
            return result("DENIED",error="没有企业读取权限")
        rows = connection.execute("SELECT * FROM tasks WHERE user_id=? AND company_id=? ORDER BY created_at,task_id",(user_id,company_id)).fetchall()
        return result("SUCCESS" if rows else "NO_DATA",[_task(row) for row in rows],{"source":"current_sqlite","scope":{"company_id":company_id}})
    finally:
        connection.close()


def manage_task(path, user_id, company_id, action, task_id="", year=2026, month=9, note="", intent=None):
    """明确创建/补充/更正/转换状态；业务证据不足不能标完成。"""
    if type(action) is not str or action not in ACTIONS or any(type(v) is not str for v in (task_id,note)):
        return result("INVALID_ARGUMENTS",error="任务操作或参数无效")
    proposed={'company_id':company_id,'action':action,'task_id':task_id,'year':year,'month':month,'note':note}
    connection = open_existing(path)
    committing = False
    try:
        connection.execute("BEGIN IMMEDIATE" if action != "show" else "BEGIN")
        if not check_permission(connection,user_id,company_id,"read").allowed:
            return result("DENIED",error="没有企业读取权限")
        if action != "show" and not (can_manage(intent,user_id,"task",action) or can_propose(intent,user_id,"task",action)):
            return result("DENIED",error="本轮没有可信的明确任务管理意图")
        if action == "create":
            if task_id or not note.strip():
                return result("INVALID_ARGUMENTS",error="新建需空task_id及明确后续待办说明")
            old = TaskPolicy.unfinished(connection,user_id,company_id)
            if old:
                return result("CONFLICT",{"existing_task_id":old["task_id"]},error="已有未完成任务，请明确保留或取消后再创建")
            check = _check(connection,user_id,company_id,year,month)
            if check["count"] == 0:
                return result("NO_CHANGE",evidence=check,error="当前没有缺失用途，无需创建待办")
            pending=require_management_confirmation(intent,proposed,None)
            if pending:
                return pending
            task_id = uuid4().hex
            context = {"note":note,"explicit_request":intent.source_request}
            connection.execute("""INSERT INTO tasks (task_id,user_id,company_id,task_type,year,month,context_json,status)
                VALUES (?,?,?,'missing_purpose',?,?,?,'ACTIVE')""",(task_id,user_id,company_id,year,month,json.dumps(context,ensure_ascii=False)))
        else:
            row = connection.execute("SELECT * FROM tasks WHERE task_id=? AND user_id=? AND company_id=?",(task_id,user_id,company_id)).fetchone()
            if not row:
                return result("NOT_FOUND",error="当前用户企业范围内没有该任务")
            if action == "show":
                return result("SUCCESS",{"task":_task(row)},{"source":"current_sqlite"})
            if row["status"] not in UNFINISHED:
                return result("CONFLICT",error="终态任务不能恢复或修改；请明确新建任务")
            check = None
            status = row["status"]
            context = json.loads(row["context_json"])
            if action in {"update","correct"}:
                if not note.strip():
                    return result("INVALID_ARGUMENTS",error="补充或更正需明确说明")
                context = {"note":note,"explicit_request":intent.source_request}
            if action == "correct":
                check = _check(connection,user_id,company_id,year,month)
            else:
                year,month = row["year"],row["month"]
            if action in {"resume","complete"}:
                check = _check(connection,user_id,company_id,year,month)
            if action == "complete":
                if check["count"] or not check["invoice_count"]:
                    return result("CONFLICT",{"task":_task(row)},check,"当前用途检查证据不支持完成")
                status = "COMPLETED"
                context["historical_completion_evidence"] = {"missing_count":0,"invoice_count":check["invoice_count"],"rule":check["rule"]}
            elif action in {"wait","pause","resume","cancel"}:
                status = {"wait":"WAITING_USER","pause":"PAUSED","resume":"ACTIVE","cancel":"CANCELLED"}[action]
            pending=require_management_confirmation(intent,proposed,_task(row))
            if pending:
                return pending
            connection.execute("""UPDATE tasks SET year=?,month=?,context_json=?,status=?,updated_at=CURRENT_TIMESTAMP
                WHERE task_id=? AND user_id=? AND company_id=?""",(year,month,json.dumps(context,ensure_ascii=False),status,task_id,user_id,company_id))
        row = connection.execute("SELECT * FROM tasks WHERE task_id=? AND user_id=? AND company_id=?",(task_id,user_id,company_id)).fetchone()
        committing = True
        connection.commit()
        return result("SUCCESS",{"task":_task(row)}, {"source":"current_sqlite","scope":{"company_id":company_id,"year":year,"month":month},"check":check})
    except RuleError as error:
        connection.rollback()
        return result(str(error) if str(error) in {"NO_APPLICABLE_RULE","RULE_CONFLICT"} else "INVALID_ARGUMENTS",error=str(error))
    except ValueError as error:
        connection.rollback()
        return result("INVALID_ARGUMENTS",error=str(error))
    except sqlite3.IntegrityError:
        connection.rollback()
        return result("CONFLICT",error="未完成任务唯一约束冲突，没有替换原任务")
    except sqlite3.Error:
        connection.rollback()
        return result("UNKNOWN_OUTCOME" if committing else "ERROR",{"task_id":task_id},error="任务保存结果需查询核实" if committing else "任务数据库操作失败，未确认成功")
    finally:
        connection.close()
