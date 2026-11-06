"""JSONL事件记录与脱敏，不决定业务状态。"""
import json
import re
import sys
from pathlib import Path

def redact(value):
    """脱敏 Trace；不保存凭据字段或常见令牌。"""
    if isinstance(value, dict):
        return {k: "[PRIVATE_PROTOCOL_HIDDEN]" if k.lower() in {'reasoning_content','reasoning','thinking'}
                else "[REDACTED]" if any(s in k.lower() for s in ("key", "password", "token", "secret")) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)(bearer\s+|sk-)[A-Za-z0-9_.-]+", "[REDACTED]", value)
        return re.sub(r"(?i)((?:api[_ -]?key|password|token|secret|密钥|口令)\s*[:=：]\s*)\S+", r"\1[REDACTED]", value)
    return value


def write_trace(path, mode, trace_id, event, data):
    """底层写入可抛OSError；调用层须标记降级，不改变业务事实。"""
    if path:
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(redact({"trace_id":trace_id, "mode":mode, "event":event, "data":data}), ensure_ascii=False) + "\n")


def warn_trace_degraded():
    """不暴露异常文本/路径/凭据，stderr本身故障时由降级标志提供证据。"""
    try:
        print("警告：Trace记录不可用；可观测性降级，请以SQLite业务审计与回读为准。", file=sys.stderr)
    except OSError:
        # 接收方关闭stderr不能影响已提交事实；调用方仍返回trace_degraded。
        pass
