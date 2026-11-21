"""轻量连续修改意图、草稿协调与权威回执，不是持久任务。"""
import sqlite3
import re
import hashlib
from pathlib import Path
from datetime import date
from uuid import uuid4
from .updates import UpdateSession, confirm_draft, commit_invoice_update, inspect_request, result as tool_result
from .trace import warn_trace_degraded
from .responses import request_scope as explicit_scope, scope_mismatch
from .tasks import task_progress
from .updates import current_target_matches, Draft

class WriteCoordinator:
    def __init__(self, user_id, db_path, trace):
        self.user_id, self.db_path, self.trace = user_id, db_path, trace
        self.session = UpdateSession(user_id)
        self.receipt = self._receipt("NOT_SUBMITTED")
        self.pending = None
        self.unverified_draft = None
        self.unverified_request_ids = ()
        self.events = []

    @property
    def has_unverified_update(self):
        return self.unverified_draft is not None or bool(self.unverified_request_ids)

    def restore_verification_requests(self, request_ids, *, actor, book):
        """Trusted SessionStore adapter: restore lookup references, never drafts."""
        if (actor != self.user_id or Path(book).resolve() != Path(self.db_path).resolve()
                or not isinstance(request_ids, (list,tuple))
                or any(type(ref) is not str or not ref or len(ref)>128 for ref in request_ids)):
            raise ValueError('待核查请求不属于当前账号或账簿。')
        refs = tuple(dict.fromkeys((*self.unverified_request_ids,*request_ids)))
        if self.unverified_draft is not None:
            refs = tuple(ref for ref in refs if ref != self.unverified_draft.request_id)
        self.unverified_request_ids = refs
        if refs:
            self.pending = None
            self.session.drafts.clear()
            self.session.confirmations.clear()
            self.session.allow_prepare = False
            self.receipt = self._receipt('UNKNOWN_OUTCOME')
            self.receipt['request_id'] = refs[0]
            self.receipt['pending_request_ids'] = list(refs)

    def _inspect_restored_request(self):
        ref = self.unverified_request_ids[0]
        try:
            outcome = inspect_request(self.db_path,self.user_id,ref)
        except (OSError,sqlite3.Error):
            outcome = tool_result('UNKNOWN_OUTCOME',{'request_id':ref},error='审计或当前值暂时无法读取')
        data = outcome.get('data') or {}
        audit,current = data.get('historical_commit') or {},data.get('current_invoice') or {}
        field = audit.get('field')
        valid = (outcome['status'] in {'COMMITTED','NO_CHANGE'}
            and audit.get('request_id') == ref and audit.get('actor') == self.user_id
            and audit.get('status') == outcome['status'] and field in {'purpose','remark'}
            and all(audit.get(key) and current.get(key) == audit[key] for key in ('company_id','invoice_no'))
            and field in current and type(data.get('current_matches')) is bool
            and data['current_matches'] is (current.get(field) == audit.get('new_value')))
        status = 'UNKNOWN_OUTCOME'
        if valid:
            self.unverified_request_ids = self.unverified_request_ids[1:]
            status = outcome['status'] if data['current_matches'] else 'CURRENT_VALUE_CHANGED'
        if self.unverified_request_ids:
            status = 'UNKNOWN_OUTCOME'
        self.receipt = self._receipt(status,outcome,valid and data['current_matches'] and not self.unverified_request_ids)
        self.receipt.update(request_id=ref,pending_request_ids=list(self.unverified_request_ids),
                            reconciled=True,committed_this_turn=False)
        if status in {'COMMITTED','NO_CHANGE'}:
            self.receipt['message']='已核实原请求的历史提交，当前值与审计一致；本次仅核查，没有再次提交。'
        elif status == 'CURRENT_VALUE_CHANGED':
            self.receipt['message']='已核实原请求的历史提交，但当前值已变化；本次仅核查，没有再次提交。'
        self._record_update(ref)
        return self.receipt

    def read_basis(self, name, arguments, *, actor, book):
        """A current explicit single-invoice edit may read only that invoice.

        This is evidence from the existing owner, not a model route or a new
        approval. Statistics and arbitrary discovery never inherit this basis.
        """
        session = self.session
        scope = session.expected_scope or {}
        if (name != 'get_invoice' or actor != self.user_id or session.user_id != actor
                or Path(book).resolve() != Path(self.db_path).resolve()
                or not session.allow_prepare or not session.explicit_edit_only
                or not session.turn_id or not session.source_request or scope.get('_conflict')
                or self.has_unverified_update):
            return None
        for field in ('company_id', 'invoice_no'):
            values = scope.get(field)
            if not isinstance(values, (list, tuple)) or len(values) != 1 or arguments.get(field) != values[0]:
                return None
        # A stale allow_prepare flag is not an active edit lifecycle.
        pending=self.pending
        pending_live=(self.receipt.get('status') in {'NOT_SUBMITTED','AMBIGUOUS'}
            and isinstance(pending,dict) and pending.get('user_id')==actor
            and pending.get('explicit_edit_only') is True and pending.get('scope')==scope
            and isinstance(pending.get('inputs'),list) and bool(pending['inputs'])
            and all(type(text) is str for text in pending['inputs'])
            and '\n'.join(pending['inputs'])==session.source_request)
        draft_live=False
        if self.receipt.get('status')=='WAITING_CONFIRMATION':
            data=self.receipt.get('data') or {}
            request_id=data.get('request_id') if isinstance(data,dict) else None
            draft=session.drafts.get(request_id) if isinstance(request_id,str) else None
            draft_live=(isinstance(draft,Draft) and draft.request_id==request_id
                and draft.session_id==session.session_id and draft.turn_id==session.turn_id
                and draft.actor==actor and draft.source_request==session.source_request
                and draft.company_id==scope['company_id'][0] and draft.invoice_no==scope['invoice_no'][0]
                and scope.get('field') in ([draft.field],(draft.field,))
                and scope.get('new_value') in ([draft.new_value],(draft.new_value,))
                and data.get('fingerprint')==draft.fingerprint())
        if not (pending_live or draft_live):return None
        return {'kind':'invoice_update_session', 'actor':actor,
                'session_id':session.session_id, 'turn_id':session.turn_id,
                'company_id':scope['company_id'][0], 'invoice_no':scope['invoice_no'][0],
                'source_hash':hashlib.sha256(session.source_request.encode('utf-8')).hexdigest(),
                'authorization':False}

    def begin(self, text, allow_prepare=False, continue_edit=False, edit_scope=None, edit_correction=False):
        if self.has_unverified_update:
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
        if self.has_unverified_update:
            self._trace_update("update.cancelled_drafts",
                               {**data, "unverified_request_id": self.unverified_draft.request_id
                                if self.unverified_draft else self.unverified_request_ids[0]})
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
        if self.has_unverified_update:
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
            if self.unverified_request_ids:
                return self._inspect_restored_request()
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
        if self.unverified_request_ids:
            status = 'UNKNOWN_OUTCOME'
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
