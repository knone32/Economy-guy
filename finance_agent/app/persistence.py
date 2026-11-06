"""持久化管理的可信本轮意图和通用结果；不依赖LLM消息协议。"""
from dataclasses import dataclass, field, replace
from copy import deepcopy
import hashlib
import json
from uuid import uuid4


@dataclass
class ManagementTurn:
    """可信运行层拥有的本轮许可生命周期；不持久化，不从模型恢复。"""
    actor: str
    turn_id: str = field(default_factory=lambda:uuid4().hex)
    active: bool = True


@dataclass
class ManagementApproval:
    """绑定内容指纹及旧对象的一次性许可，只能由可信确认入口创建。"""
    request_id: str
    fingerprint: str
    current: object
    used: bool = False


@dataclass(frozen=True)
class ManagementIntent:
    actor: str
    domain: str
    source_request: str
    action: str | None = None
    # None只用于直接可信Python/argparse入口；模型分发必须设置本轮对象。
    turn: ManagementTurn | None = None
    approval: ManagementApproval | None = None


def can_manage(intent, user_id, domain, action):
    """只接受可信Python/CLI创建的本轮意图，不由工具参数自报授权。"""
    return (isinstance(intent, ManagementIntent) and intent.actor == user_id
            and intent.domain == domain and bool(intent.source_request.strip())
            and (intent.action is None or intent.action == action)
            and (intent.turn is None or (intent.turn.active and intent.turn.actor==user_id)))


def _fingerprint(intent,request_id,payload,current):
    data=[intent.actor,intent.domain,intent.action,intent.source_request,
          intent.turn.turn_id,request_id,payload,current]
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()


def confirm_management(intent,proposal):
    """仅可信CLI在用户确认具体提案后调用；该函数不是LLM工具。"""
    if not intent.turn or not can_manage(intent,intent.actor,intent.domain,intent.action):
        raise ValueError("本轮管理确认已失效")
    expected=_fingerprint(intent,proposal['request_id'],proposal['proposal'],proposal['current'])
    if proposal['fingerprint']!=expected:
        raise ValueError("管理提案指纹不一致")
    return replace(intent,approval=ManagementApproval(proposal['request_id'],expected,deepcopy(proposal['current'])))


def require_management_confirmation(intent,payload,current):
    """在业务写事务内绑定对象/全部参数/旧值；旧许可不能重复使用。"""
    if intent.turn is None:
        # 直接CLI参数来自用户，未经过模型；保留可信内部Python接口。
        return None
    approval=intent.approval
    if approval is None:
        request_id=uuid4().hex
        proposal={'request_id':request_id,'domain':intent.domain,'original_request':intent.source_request,
                  'proposal':deepcopy(payload),'current':deepcopy(current)}
        proposal['fingerprint']=_fingerprint(intent,request_id,payload,current)
        return result('WAITING_CONFIRMATION',proposal,error='请通过可信CLI核对原始要求、具体对象和内容并确认；尚未持久化')
    expected=_fingerprint(intent,approval.request_id,payload,approval.current)
    if approval.used or expected!=approval.fingerprint:
        return result('DENIED',error='管理确认已使用或对象/内容与确认不一致，未保存')
    if current!=approval.current:
        return result('CONFLICT',error='确认期间目标状态发生变化，请重新核对确认，未保存')
    approval.used=True
    return None


def result(status, data=None, evidence=None, error=None):
    return {"ok":status in {"SUCCESS","NO_DATA","NO_CHANGE"}, "status":status,
            "data":data, "evidence":evidence or {}, "error":error}
