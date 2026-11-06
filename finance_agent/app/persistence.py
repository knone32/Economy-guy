"""持久化管理的可信本轮意图和通用结果；不依赖LLM消息协议。"""
from dataclasses import dataclass, field, replace
from copy import deepcopy
import hashlib
import json
from uuid import uuid4


@dataclass
class ManagementProposals:
    """本轮候选预览的生命周期，没有管理/写入权限。"""
    actor: str
    source_request: str
    turn_id: str = field(default_factory=lambda:uuid4().hex)
    active: bool = True


@dataclass(frozen=True)
class ManagementCandidate:
    """模型参数只能成为候选；即使有此对象也必须先返回预览。"""
    actor: str
    domain: str
    source_request: str
    action: str
    turn: ManagementProposals


@dataclass
class ManagementTurn:
    """可信运行层拥有的本轮许可生命周期；不持久化，不从模型恢复。"""
    actor: str
    turn_id: str = field(default_factory=lambda:uuid4().hex)
    active: bool = True
    # 自然语言提案确认后创建授权；下一轮/身份变化同时撤销其来源。
    proposals: ManagementProposals | None = None


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
            and (intent.turn is None or (intent.turn.active and intent.turn.actor==user_id
                 and (intent.turn.proposals is None or
                      (intent.turn.proposals.active and intent.turn.proposals.actor==user_id)))))


def can_propose(candidate, user_id, domain, action):
    """只允许预览；绝不能把候选当作can_manage的授权结果。"""
    return (isinstance(candidate,ManagementCandidate) and candidate.actor==user_id
            and candidate.domain==domain and candidate.action==action
            and bool(candidate.source_request.strip())
            and candidate.turn.active and candidate.turn.actor==user_id
            and candidate.source_request==candidate.turn.source_request)


def _fingerprint(intent,request_id,payload,current):
    data=[intent.actor,intent.domain,intent.action,intent.source_request,
          intent.turn.turn_id,request_id,payload,current]
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()


def confirm_management(intent,proposal):
    """仅可信CLI在用户确认具体提案后调用；该函数不是LLM工具。"""
    candidate=can_propose(intent,intent.actor,intent.domain,intent.action)
    if not intent.turn or not (candidate or can_manage(intent,intent.actor,intent.domain,intent.action)):
        raise ValueError("本轮管理确认已失效")
    expected=_fingerprint(intent,proposal['request_id'],proposal['proposal'],proposal['current'])
    if proposal['fingerprint']!=expected:
        raise ValueError("管理提案指纹不一致")
    if candidate:
        # 仅在可信入口确认具体内容后建立受限授权，不由模型选工具时建立。
        intent=ManagementIntent(intent.actor,intent.domain,intent.source_request,intent.action,
            turn=ManagementTurn(intent.actor,turn_id=intent.turn.turn_id,proposals=intent.turn))
    return replace(intent,approval=ManagementApproval(proposal['request_id'],expected,deepcopy(proposal['current'])))


def require_management_confirmation(intent,payload,current):
    """在业务写事务内绑定对象/全部参数/旧值；旧许可不能重复使用。"""
    candidate=isinstance(intent,ManagementCandidate)
    if not candidate and intent.turn is None:
        # 直接CLI参数来自用户，未经过模型；保留可信内部Python接口。
        return None
    approval=None if candidate else intent.approval
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
