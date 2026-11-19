"""轻量连续修改意图、草稿协调与权威回执，不是持久任务。"""
import sqlite3
import re
from datetime import date
from uuid import uuid4
from .updates import UpdateSession, confirm_draft, commit_invoice_update, inspect_request, result as tool_result
from .trace import warn_trace_degraded
from .responses import request_scope as explicit_scope, scope_mismatch
from .tasks import task_progress
from .updates import current_target_matches

class WriteCoordinator:
    def __init__(self, user_id, db_path, trace):
        self.user_id, self.db_path, self.trace = user_id, db_path, trace
        self.session = UpdateSession(user_id)
        self.receipt = self._receipt("NOT_SUBMITTED")
        self.pending = None
        self.unverified_draft = None
        self.events = []

    def begin(self, text, allow_prepare=False, continue_edit=False, edit_scope=None, edit_correction=False):
        if self.unverified_draft is not None:
            self.session.begin_turn(text)
            return False
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
            "UNKNOWN_OUTCOME": "提交结果待核实，请输入 /inspect-update 核查原请求的审计和当前值。",
            "CURRENT_VALUE_CHANGED": "原请求的成功审计已核实，当前值已变化。",
            "NO_PENDING_VERIFICATION": "当前会话没有待核实的发票修改。",
            "INVALID_ARGUMENTS": "参数无效，未保存。",
            "SCOPE_MISMATCH": "范围不一致，未创建草稿或保存；请重新/edit明确更正目标。",
            "AMBIGUOUS": "请明确唯一企业和发票编号，未创建草稿或保存。",
        }
        return {"status": status, "message": messages.get(status, messages["ERROR"]),
                "readback_verified": readback_verified, "data": data}

    def assess_current_match(self, results, *, natural_scope=None):
        """只对可信编辑原句的明确字面目标及本轮真实读取做无需变更回执。"""
        if self.receipt["status"] != "NOT_SUBMITTED" or not (self.session.allow_prepare or natural_scope):
            return
        text=self.session.source_request
        scope = natural_scope or (self.session.expected_scope if self.session.explicit_edit_only else explicit_scope(
            text, include_update_aliases=True))
        if not scope or scope.get("_conflict"):
            return
        if any(len(scope.get(key,[]))!=1 for key in ('company_id','invoice_no')):return
        if natural_scope or self.session.explicit_edit_only:
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
        if value != "" and not value.strip():
            return
        company,invoice=scope['company_id'][0],scope['invoice_no'][0]
        if natural_scope and not any(
            name in {"get_invoice", "resolve_recent_invoice"} and outcome["status"] == "SUCCESS"
            and outcome["evidence"].get("source") == "current_sqlite"
            and (row := outcome["data"]).get("company_id") == company
            and row.get("invoice_no") == invoice and row.get(field) == value
            for name, outcome in results
        ):
            return
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
        if self.unverified_draft is not None:
            self._trace_update("update.cancelled_drafts",
                               {**data, "unverified_request_id": self.unverified_draft.request_id})
            return self.receipt
        if self.receipt["status"] in {"COMMITTED", "NO_CHANGE", "CURRENT_VALUE_CHANGED"}:
            return self.receipt
        self.receipt = self._receipt("CANCELLED", data)
        self.events.append({"event_id":uuid4().hex, "turn_id":self.session.turn_id, "request_id":None,
                            "source":"trusted_cli", "receipt":self.receipt})
        self._trace_update("update.result", self.receipt)
        return self.receipt

    def commit_update(self, request_id, fingerprint, commit_function=commit_invoice_update):
        """仅可信CLI调用；根据实际Commit及绑定回读证据生成回执。"""
        if self.unverified_draft is not None:
            return self.receipt
        draft = self.session.drafts.get(request_id)
        if not confirm_draft(self.session, request_id, fingerprint):
            outcome = tool_result("DENIED", error="没有本会话绑定草稿的最终确认")
        else:
            try:
                outcome = commit_function(self.db_path, self.session, request_id)
            except sqlite3.Error:
                outcome = tool_result("UNKNOWN_OUTCOME", {"request_id":request_id}, error="提交或回读异常，先查审计")
        status = outcome["status"]
        verified = status in {"COMMITTED", "NO_CHANGE"} and self._bound_readback(draft, outcome) is True
        if status == "UNKNOWN_OUTCOME" or (status in {"COMMITTED", "NO_CHANGE"} and not verified):
            return self.require_update_verification(draft, outcome)

        self.receipt = self._receipt(status, outcome, verified)
        if verified:
            # Commit/审计/回读已核实后再独立读取任务，不把进度查询失败改成提交失败。
            self.receipt["task_progress"] = self._post_commit_progress(outcome["data"]["current_invoice"])
        self.pending = None
        self._record_update(request_id)
        return self.receipt

    def require_update_verification(self, draft, outcome):
        """保留原草稿作为核查证据，并撤销本轮提交许可。"""
        self.unverified_draft = draft
        self.session.drafts.clear()
        self.session.confirmations.clear()
        self.session.allow_prepare = False
        self.pending = None
        self.receipt = self._verification_receipt("UNKNOWN_OUTCOME", draft, outcome)
        self._record_update(draft.request_id)
        return self.receipt

    def reconcile_update(self):
        """按可信身份核查原请求。整个过程只读。"""
        draft = self.unverified_draft
        if draft is None:
            return self._receipt("NO_PENDING_VERIFICATION")
        try:
            outcome = inspect_request(self.db_path, self.user_id, draft.request_id)
        except sqlite3.Error:
            outcome = tool_result("UNKNOWN_OUTCOME", {"request_id": draft.request_id}, error="审计或当前值暂时无法读取")

        matches = self._bound_readback(draft, outcome)
        status = "UNKNOWN_OUTCOME"
        if matches is not None:
            status = outcome["status"] if matches else "CURRENT_VALUE_CHANGED"
            self.unverified_draft = None
        self.receipt = self._verification_receipt(status, draft, outcome, matches is True)
        self.receipt["reconciled"] = True
        self._record_update(draft.request_id)
        return self.receipt

    def _verification_receipt(self, status, draft, outcome, verified=False):
        receipt = self._receipt(status, outcome, verified)
        receipt["request_id"] = draft.request_id
        receipt["message"] = f'{receipt["message"]} 请求编号 {draft.request_id}。'
        return receipt

    def _bound_readback(self, draft, outcome):
        """True/False 是绑定回读的匹配结果，None 表示证据不足。"""
        if draft is None or outcome["status"] not in {"COMMITTED", "NO_CHANGE"}:
            return None
        data = outcome.get("data") or {}
        audit = data.get("historical_commit") or {}
        current = data.get("current_invoice") or {}
        expected = {
            "request_id": draft.request_id, "fingerprint": draft.fingerprint(),
            "status": outcome["status"], "actor": self.user_id, "company_id": draft.company_id,
            "invoice_no": draft.invoice_no, "field": draft.field, "old_value": draft.old_value,
            "new_value": draft.new_value,
        }
        if (any(key not in audit or audit[key] != value for key, value in expected.items())
                or current.get("company_id") != draft.company_id or current.get("invoice_no") != draft.invoice_no
                or draft.field not in current):
            return None
        matches = current[draft.field] == draft.new_value
        return matches if data.get("current_matches") is matches else None

    def _record_update(self, request_id):
        self.events.append({"event_id": uuid4().hex, "turn_id": self.session.turn_id, "request_id": request_id,
                            "source": "trusted_cli", "receipt": self.receipt})
        self._trace_update("update.result", self.receipt)

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

    def _trace_update(self, event, data):
        """日志是可观测性副作用，不能遮蔽已经完成的业务结果。"""
        try:
            self.trace(event, data)
        except OSError:
            self.receipt["trace_degraded"] = True
            warn_trace_degraded()
