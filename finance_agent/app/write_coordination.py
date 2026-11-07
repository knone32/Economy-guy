"""轻量连续修改意图、草稿协调与权威回执，不是持久任务。"""
import sqlite3
import re
from datetime import date
from uuid import uuid4
from .updates import UpdateSession, confirm_draft, commit_invoice_update, result as tool_result
from .trace import warn_trace_degraded
from .responses import explicit_scope, scope_mismatch
from .tasks import task_progress
from .updates import current_target_matches

class WriteCoordinator:
    def __init__(self, user_id, db_path, trace):
        self.user_id, self.db_path, self.trace = user_id, db_path, trace
        self.session = UpdateSession(user_id)
        self.receipt = self._receipt("NOT_SUBMITTED")
        self.pending = None
        self.events = []

    def begin(self, text, allow_prepare=False, continue_edit=False, edit_scope=None, edit_correction=False):
        original = self.pending if continue_edit and self.pending and self.pending["user_id"] == self.user_id else None
        enabled = bool(allow_prepare or original)
        if allow_prepare:
            original = {"intent_id":uuid4().hex, "user_id":self.user_id, "inputs":[], "scope":{}, "explicit_edit_only":edit_scope is not None}
        self.pending = original if enabled else None
        if self.pending:
            self.pending["inputs"].append(text)
            incoming = edit_scope if edit_scope is not None else explicit_scope(text, include_update_aliases=True)
            scope = self.pending["scope"]
            for key in ("company_id", "invoice_no", "field", "new_value"):
                if key not in incoming:
                    continue
                if key in scope and scope[key] != incoming[key] and not edit_correction:
                    # 不能把C001/C002或F002/F003并为多个允许的写目标。
                    scope["_conflict"] = True
                else:
                    scope[key] = incoming[key]
        source = "\n".join(self.pending["inputs"]) if self.pending else text
        self.session.begin_turn(source, enabled, expected_scope=self.pending["scope"] if self.pending else None,
                                explicit_edit_only=bool(self.pending and self.pending["explicit_edit_only"]))
        self.receipt = self._receipt("NOT_SUBMITTED")
        return enabled

    def record_preparation(self, outcome):
        """只接收Handler的实际结果；草稿与待补充意图不同时存活。"""
        self.receipt = self._receipt(outcome["status"], outcome.get("data"))
        if not (self.session.explicit_edit_only and outcome["status"] == "AMBIGUOUS"):
            self.pending = None

    @staticmethod
    def _receipt(status, data=None, readback_verified=False):
        """操作提示由程序生成，不接收模型提供的成功文本。"""
        messages = {
            "NOT_SUBMITTED": "尚未保存：本轮没有提交操作；请明确目标、字段和新值后准备草稿。",
            "WAITING_CONFIRMATION": "草稿已准备，尚未保存；请在可信CLI核对并确认。",
            "CANCELLED": "已取消，未提交。",
            "COMMITTED": "保存成功：提交审计和新连接回读已核实。",
            "NO_CHANGE": "无需修改：原值与新值相同，已核实当前值；没有执行字段更新。",
            "CURRENT_VALUE_MATCHES": "无需再次修改：当前数据库值已符合本次明确目标；本轮没有Commit，也没有新增审计。",
            "DENIED": "操作被拒绝，不能报告保存成功。",
            "CONFLICT": "当前值或请求内容冲突，未执行本次更新；请重新核对。",
            "NOT_FOUND": "未找到目标记录，未保存。",
            "ERROR": "操作失败，未核实保存成功；请查看业务错误。",
            "UNKNOWN_OUTCOME": "提交或回读结果未知，尚未核实最终状态；请先按request_id核查审计。",
            "INVALID_ARGUMENTS": "参数无效，未保存。",
            "SCOPE_MISMATCH": "范围不一致，未创建草稿或保存；请重新/edit明确更正目标。",
            "AMBIGUOUS": "请明确唯一企业和发票编号，未创建草稿或保存。",
        }
        return {"status": status, "message": messages.get(status, messages["ERROR"]),
                "readback_verified": readback_verified, "data": data}

    def assess_current_match(self,results):
        """只对可信编辑原句的明确字面目标及本轮真实读取做无需变更回执。"""
        if self.receipt['status']!='NOT_SUBMITTED' or not self.session.allow_prepare:return
        text=self.session.source_request
        scope = self.session.expected_scope if self.session.explicit_edit_only else explicit_scope(
            text, include_update_aliases=True)
        if not scope or scope.get("_conflict"):
            return
        if any(len(scope.get(key,[]))!=1 for key in ('company_id','invoice_no')):return
        if self.session.explicit_edit_only:
            if any(len(scope.get(key, [])) != 1 for key in ("field", "new_value")):
                return
            field, value = scope["field"][0], scope["new_value"][0]
        else:
            matches = list(re.finditer(r'(用途|purpose|备注|remark)\s*(?:修改为|改为|改成|设置为|设为)', text))
            if len(matches) != 1:
                return
            match = matches[0]
            field = 'purpose' if match[1] in {'用途', 'purpose'} else 'remark'
            value = re.split(r'[。\n]', text[match.end():], maxsplit=1)[0].strip()
            if value.startswith(('“','"')):
                closing='”' if value[0]=='“' else '"'
                if not value.endswith(closing):return
                value=value[1:-1]
        if not value.strip():
            return
        company,invoice=scope['company_id'][0],scope['invoice_no'][0]
        # 模型可能只引用历史值；可信编辑入口的明确目标仍须独立新连接核对。
        # 此次核对不是模型Tool Call，亦不产生Prepare/Commit/成功审计。
        try:
            current = current_target_matches(self.db_path, self.user_id, company, invoice, field, value)
            if current:
                day = date.fromisoformat(current['current_invoice']['invoice_date'])
                if scope_mismatch(scope, {'year': day.year, 'month': day.month}):
                    current = None
        except (sqlite3.Error, ValueError, PermissionError):
            return
        if current:
            current['checked_by']='harness_readonly_reconciliation'
            self.receipt=self._receipt('CURRENT_VALUE_MATCHES',current)
        try:
            self.trace('update.target_checked',{'company_id':company,'invoice_no':invoice,'field':field,
                'source':'current_sqlite','matched':bool(current),'committed_this_turn':False})
        except OSError:
            self.receipt['trace_degraded']=True;warn_trace_degraded()

    def cancel_update(self):
        """可信CLI取消后撤销本轮全部草稿与确认。"""
        data = {"request_ids":list(self.session.drafts), "intent_id":self.pending["intent_id"] if self.pending else None}
        self.session.confirmations.clear()
        self.session.drafts.clear()
        self.pending = None
        self.receipt = self._receipt("CANCELLED", data)
        self.events.append({"event_id":uuid4().hex, "turn_id":self.session.turn_id, "request_id":None,
                            "source":"trusted_cli", "receipt":self.receipt})
        self._trace_receipt()
        return self.receipt

    def commit_update(self, request_id, fingerprint, commit_function=commit_invoice_update):
        """仅可信CLI调用；根据实际Commit及绑定回读证据生成回执。"""
        draft = self.session.drafts.get(request_id)
        if not confirm_draft(self.session, request_id, fingerprint):
            outcome = tool_result("DENIED", error="没有本会话绑定草稿的最终确认")
        else:
            try:
                outcome = commit_function(self.db_path, self.session, request_id)
            except sqlite3.Error:
                outcome = tool_result("UNKNOWN_OUTCOME", {"request_id":request_id}, error="提交或回读异常，先查审计")
        status = outcome["status"]
        verified = False
        if status in {"COMMITTED", "NO_CHANGE"}:
            data = outcome.get("data") or {}
            audit = data.get("historical_commit") or {}
            current = data.get("current_invoice") or {}
            verified = bool(draft and audit.get("request_id") == request_id
                            and audit.get("fingerprint") == draft.fingerprint()
                            and audit.get("status") == status and audit.get("actor") == self.user_id
                            and audit.get("company_id") == draft.company_id
                            and audit.get("invoice_no") == draft.invoice_no
                            and audit.get("field") == draft.field
                            and audit.get("old_value") == draft.old_value
                            and audit.get("new_value") == draft.new_value
                            and current.get("company_id") == draft.company_id
                            and current.get("invoice_no") == draft.invoice_no
                            and current.get(draft.field) == draft.new_value
                            and data.get("current_matches") is True)
            if not verified:
                status = "UNKNOWN_OUTCOME"
        self.receipt = self._receipt(status, outcome, verified)
        if verified:
            # Commit/审计/回读已核实后再独立读取任务，不把进度查询失败改成提交失败。
            self.receipt['task_progress']=self._post_commit_progress(current)
        self.events.append({"event_id":uuid4().hex, "turn_id":self.session.turn_id, "request_id":request_id, "source":"trusted_cli", "receipt":self.receipt})
        self.pending = None
        self._trace_receipt()
        return self.receipt

    def _post_commit_progress(self,current):
        """仅隔离已经核实提交后的可选进度；绝不捕获Commit/审计/回读事务异常。"""
        try:
            raw=current['invoice_date']
            if type(raw) is not str: raise ValueError('invalid date')
            day=date.fromisoformat(raw)
            if day.isoformat()!=raw: raise ValueError('invalid format')
            progress=task_progress(self.db_path,self.user_id,current['company_id'],day.year,day.month)
            if type(progress) is not dict or type(progress.get('status')) is not str:
                raise ValueError('invalid progress response')
            return progress
        except Exception:
            # 此作用域只有附加只读操作；显式返回ERROR，不影响已生成的权威成功回执。
            return tool_result('ERROR',error='已核实的提交状态不变；附加任务进度不可用，请重新查询')

    def _trace_receipt(self):
        """日志是可观测性副作用，不能遮蔽已经完成的业务结果。"""
        try:
            self.trace("update.result", self.receipt)
        except OSError:
            self.receipt["trace_degraded"] = True
            warn_trace_degraded()
