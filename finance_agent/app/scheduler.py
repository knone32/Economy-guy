"""单轮粗计划与分块预算；不持久化任务，不执行业务，不授予权限。"""
from copy import deepcopy
from dataclasses import dataclass
import json


@dataclass(frozen=True)
class BudgetPolicy:
    """固定块长与硬限；不估算token或让模型自行续费。"""
    block_requests: int = 3
    max_requests: int = 9
    max_tools: int = 12
    max_extensions: int = 2
    max_replans: int = 1

    def __post_init__(self):
        for key in ("block_requests","max_requests","max_tools","max_extensions","max_replans"):
            value = getattr(self,key)
            if type(value) is not int or value < (0 if key in {"max_extensions","max_replans"} else 1):
                raise ValueError("预算参数必须是合法整数："+key)
        if self.max_requests>9 or self.max_tools>12 or self.max_extensions>2 or self.max_replans>1:
            raise ValueError("不能超过9次模型/12次工具/2次续期/1次重规划硬限")


def matches(step,name,args):
    """计划仅约束实际工具名和已知参数，不把计划文字当业务证据。"""
    return step["action"]==name and all(key in args and args[key]==value for key,value in step["arguments"].items())


class TurnExecution:
    """一个用户消息一个实例；只持有本轮计数、计划和已观测证据索引。"""
    def __init__(self,policy,emit=lambda event,data:None,can_continue=lambda steps:True):
        self.policy,self.emit = policy,emit
        self.can_continue = can_continue
        self.model_requests = self.actual_tools = self.requested_tools = 0
        self.extensions = self.replans = self.progress = self.block_progress = 0
        self.block_limit = min(policy.block_requests,policy.max_requests)
        self.schedule = None
        self.stop_reason = None
        self.seen = set()
        self.observed = []

    def snapshot(self):
        """仅供展示/Trace的快照；不是持久业务状态。"""
        return deepcopy({"model_requests":self.model_requests,"actual_tool_calls":self.actual_tools,
            "requested_tool_calls":self.requested_tools,"extensions":self.extensions,"replans":self.replans,
            "block_limit":self.block_limit,"max_requests":self.policy.max_requests,"max_tools":self.policy.max_tools,
            "progress_count":self.progress,"stop_reason":self.stop_reason,"schedule":self.schedule})

    def stop(self,reason):
        """第一停止原因优先；后续跳过的工具不能掩盖DENIED等真实原因。"""
        if self.stop_reason is None:
            self.stop_reason = reason
            if self.schedule:
                self.schedule["status"] = ("COMPLETED" if reason=="COMPLETED" else
                    "WAITING_USER" if reason in {"WAITING_USER","WAITING_CONFIRMATION"} else "STOPPED")
            self.emit("execution.stopped",self.snapshot())

    def ready(self):
        """只允许依赖已由真实工具完成的必要剩余步骤。"""
        if not self.schedule:
            return []
        done = {s["step_id"] for s in self.schedule["steps"] if s["status"]=="DONE"}
        return [s for s in self.schedule["steps"] if s["status"]=="PENDING" and set(s["depends_on"])<=done]

    def start_request(self):
        """在实际模型调用前记数；达到软限时用真实进展决定是否续一块。"""
        if self.stop_reason:
            return False
        if self.model_requests>=self.policy.max_requests:
            self.stop("MODEL_LIMIT")
            return False
        if self.actual_tools>=self.policy.max_tools:
            self.stop("TOOL_LIMIT")
            return False
        if self.model_requests>=self.block_limit:
            if self.progress<=self.block_progress:
                self.stop("NO_PROGRESS")
                return False
            if not self.ready() or not self.can_continue(self.ready()):
                self.stop("NO_LEGAL_WORK")
                return False
            if self.extensions>=self.policy.max_extensions:
                self.stop("EXTENSION_LIMIT")
                return False
            self.extensions += 1
            self.block_progress = self.progress
            self.block_limit = min(self.block_limit+self.policy.block_requests,self.policy.max_requests)
            self.emit("budget.extended",{"reason":"本块有新工具证据且仍有合法就绪步骤",**self.snapshot()})
        self.model_requests += 1
        self.emit("budget",self.snapshot())
        return True

    def dispatch(self,name,raw_arguments):
        """计数实际进入Handler的调用；重复参数不再执行，跳过项不计实际工具数。"""
        try:
            signature = json.dumps([name,json.loads(raw_arguments)],sort_keys=True,ensure_ascii=False)
        except (ValueError,TypeError):
            signature = repr((name,raw_arguments))
        if signature in self.seen:
            self.stop("NO_PROGRESS")
            return "NO_PROGRESS"
        if self.actual_tools>=self.policy.max_tools:
            self.stop("TOOL_LIMIT")
            return "TOOL_LIMIT"
        self.seen.add(signature)
        self.actual_tools += 1
        return None

    def install(self,goal,steps,stop_condition):
        """Registry校验工具/身份/范围后接收计划；模型不能传status或完成证据。"""
        if self.schedule and self.replans>=self.policy.max_replans:
            return {"ok":False,"status":"REPLAN_LIMIT","data":None,"evidence":{},"error":"本轮重规划次数已达上限"}
        if self.schedule:
            self.replans += 1
        prepared = []
        for step in steps:
            done = any(matches(step,entry["action"],entry["arguments"]) for entry in self.observed)
            prepared.append({**deepcopy(step),"status":"DONE" if done else "PENDING"})
        self.schedule = {"goal":goal,"steps":prepared,"stop_condition":stop_condition,
                         "status":"ACTIVE","revision":self.replans}
        self.emit("schedule.replanned" if self.replans else "schedule.created",self.snapshot())
        return {"ok":True,"status":"SUCCESS","data":deepcopy(self.schedule),
                "evidence":{"source":"harness_schedule","business_authorization":False},"error":None}

    def guard(self,name,args):
        """约束调用必须匹配就绪步骤；执行时的业务鉴权依然独立。"""
        if self.schedule and not any(matches(s,name,args) for s in self.ready()):
            return {"ok":False,"status":"SCHEDULE_MISMATCH","data":None,"evidence":{},
                    "error":"工具不匹配计划就绪步骤或依赖未完成；需明确重规划"}
        return None

    def restore_schedule(self,args):
        """真实resume工具触发一个恢复步骤，不拆开其内部规则/SQL检查。"""
        if self.schedule is None:
            self.install("恢复当前用户的持久任务",[{"step_id":"restore","action":"manage_task",
                "arguments":deepcopy(args),"depends_on":[]}],"返回实际恢复结果或遇到用户等待/拒绝即停止")

    def observe(self,name,args,outcome):
        """只接受执行层结果；计划完成仅指所列工具步骤，绝不代表发票已提交。"""
        status = outcome["status"]
        if status=="WAITING_CONFIRMATION":
            for step in self.ready():
                if matches(step,name,args):
                    step["status"]="WAITING_USER"
                    step["evidence"]={"status":status}
                    break
            self.stop("WAITING_CONFIRMATION")
            return
        if not outcome["ok"]:
            self.stop(status)
            return
        if name=="set_schedule":
            if self.schedule and all(s["status"]=="DONE" for s in self.schedule["steps"]):
                self.stop("COMPLETED")
            return
        if status=="NO_CHANGE":
            self.stop("NO_PROGRESS")
            return
        if status not in {"SUCCESS","NO_DATA"}:
            self.stop("UNVERIFIED_RESULT")
            return
        self.progress += 1
        self.observed.append({"action":name,"arguments":deepcopy(args),"status":status,
                              "source":outcome.get("evidence",{}).get("source")})
        for step in self.ready():
            if matches(step,name,args):
                step["status"] = "DONE"
                step["evidence"] = {"status":status,"source":outcome.get("evidence",{}).get("source")}
                break
        self.emit("schedule.progress",self.snapshot())
        task = (outcome.get("data") or {}).get("task") if name=="manage_task" else None
        if task and task["status"] in {"WAITING_USER","PAUSED"}:
            self.stop("WAITING_USER")
        elif self.schedule and all(s["status"]=="DONE" for s in self.schedule["steps"]):
            self.stop("COMPLETED")
        elif task and task["status"] in {"COMPLETED","CANCELLED"}:
            self.stop("TASK_FINISHED")
