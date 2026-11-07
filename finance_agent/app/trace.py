"""JSONL事件记录与脱敏，不决定业务状态。"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode

PRIVATE_FIELDS={'reasoning_content','reasoning','thinking','analysis','chain_of_thought','reasoning_details'}
SECRET_FIELDS={'key','api_key','apikey','password','passwd','secret','token','authorization','proxy_authorization',
               'cookie','set_cookie','credentials','credential','client_secret','x_api_key','api_key_value'}


def _name(key):
    return re.sub(r'(?<=[a-z])(?=[A-Z])','_',str(key)).lower().replace('-','_').strip('_')


def _secret(key):
    key=_name(key)
    return key in SECRET_FIELDS or key.endswith(('_password','_secret','_api_key','_auth_token','_access_token','_refresh_token','_session_token','_secret_access_key'))


def _url(match):
    value=match[0]
    try:
        p=urlsplit(value)
        query=parse_qsl(p.query,keep_blank_values=True)
        if not p.username and not p.password and not any(_secret(k) for k,_ in query): return value
        netloc=('[REDACTED]@' if p.username or p.password else '')+p.netloc.rsplit('@',1)[-1]
        return urlunsplit((p.scheme,netloc,p.path,urlencode([(k,'[REDACTED]' if _secret(k) else v) for k,v in query]),p.fragment))
    except ValueError:
        return '[REDACTED_URL]'

def redact(value):
    """按字段语义遮蔽凭据/私有推理；保留业务键名及真实Token计数。"""
    if isinstance(value, dict):
        output={}
        for k,v in value.items():
            preference_key=(_name(k)=='key' and type(value.get('action')) is str and value['action'] in {'create','get','list','update','delete'} and 'company_id' in value)
            schema_key=(_name(k)=='key' and type(v) is dict and v.get('type')=='string' and set(v)<={'type','description','enum'})
            output[k]='[PRIVATE_PROTOCOL_HIDDEN]' if _name(k) in PRIVATE_FIELDS else '[REDACTED]' if _secret(k) and not (preference_key or schema_key) else redact(v)
        return output
    if isinstance(value, (list,tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        try:
            parsed=json.loads(value)
            if type(parsed) in (dict,list):
                cleaned=redact(parsed)
                return value if cleaned==parsed else json.dumps(cleaned,ensure_ascii=False)
        except RecursionError:
            return '[REDACTED_UNPARSEABLE_JSON]'
        except (ValueError,TypeError):
            pass
        value=re.sub(r'(?i)(\b(?:set-cookie|cookie)[ \t]*:)[^\r\n]*',r'\1 [REDACTED]',value)
        value=re.sub(r'https?://[^\s\"\'<>]+',_url,value)
        value=re.sub(r'(?i)\b(?:authorization|proxy-authorization)\s*[:=]\s*[^\r\n,;]+','Authorization: [REDACTED]',value)
        value=re.sub(r'(?i)\b(?:reasoning_content|reasoning|thinking|chain_of_thought)\s*[:=]\s*("(?:\\.|[^"\\])*"|\'[^\']*\'|[^\r\n;]+)','reasoning_content=[PRIVATE_PROTOCOL_HIDDEN]',value)
        value = re.sub(r"(?i)(bearer\s+|sk-)[A-Za-z0-9_.-]+", "[REDACTED]", value)
        value=re.sub(r'(?i)\bbasic\s+[A-Za-z0-9+/=_-]+','[REDACTED]',value)
        return re.sub(r'(?i)(\b(?:api[_ -]?key|password|access_token|refresh_token|token|secret|密钥|口令)\s*["\']?\s*[:=：]\s*)("(?:\\.|[^"\\])*"|\'[^\']*\'|[^\s,;}]+)',r'\1[REDACTED]',value)
    return value


def write_trace(path, mode, trace_id, event, data,metadata=None):
    """底层写入可抛OSError；调用层须标记降级，不改变业务事实。"""
    if path:
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(redact({**(metadata or {}),"trace_id":trace_id, "mode":mode, "event":event, "data":data}), ensure_ascii=False) + "\n")


def warn_trace_degraded():
    """不暴露异常文本/路径/凭据，stderr本身故障时由降级标志提供证据。"""
    try:
        print("警告：Trace记录不可用；可观测性降级，请以SQLite业务审计与回读为准。", file=sys.stderr)
    except OSError:
        # 接收方关闭stderr不能影响已提交事实；调用方仍返回trace_degraded。
        pass
