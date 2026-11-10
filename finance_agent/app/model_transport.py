"""一个会话绑定一份解析后的连接；SDK调用与非敏感真实指标，不拥有业务状态。"""
from collections import Counter
import json
import re
import time
from urllib.parse import urlsplit

from .model_config import QWEN_PREFLIGHT, is_official_qwen
from .thinking_protocol import ThinkingProtocol, is_official_deepseek_endpoint
from .trace import redact, warn_trace_degraded


class ModelRequestError(RuntimeError):
    """SDK异常正文可能含凭据/业务输入，不向普通日志或CLI传播。"""


_ERROR_CODES = {
    "invalid_request_error", "invalid_parameter", "invalid_value", "unsupported_parameter", "unknown_parameter",
    "invalid_model", "model_not_found", "invalid_api_key", "permission_denied", "rate_limit_exceeded",
    "insufficient_quota", "context_length_exceeded", "server_error", "invalid_request", "model_not_supported",
    "invalid_tool", "tool_not_supported", "InvalidParameter", "InvalidApiKey", "ModelNotFound", "AccessDenied",
    "20012", "50505",
}
_PARAMETER = re.compile(
    r"(?:model|messages|tools|tool_choice|response_format|max_tokens|max_completion_tokens|temperature|top_p|"
    r"enable_thinking|thinking|reasoning_effort|preserve_thinking|stream)"
    r"(?:\[[0-9]{1,4}\]|\.[0-9]{1,4}|\.(?:role|name|content|tool_call_id|tool_calls|function|arguments|"
    r"parameters|type|properties|required|additionalProperties|strict|items|enum|description|minItems|maxItems|"
    r"steps|depends_on|selection_id|excluded_invoice_ids|rule_business_date|rule_cohort|target_year|target_month)){0,16}"
)
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,199}")
_STATUS_CATEGORIES = {400: "INVALID_REQUEST", 401: "AUTHENTICATION", 403: "FORBIDDEN",
                      404: "NOT_FOUND", 422: "INVALID_REQUEST", 429: "RATE_LIMIT"}
_CATEGORY_LABELS = {
    "INVALID_REQUEST": "服务商拒绝了请求，可能涉及参数或模型兼容性",
    "AUTHENTICATION": "密钥鉴权失败", "FORBIDDEN": "服务访问被拒绝",
    "NOT_FOUND": "服务地址或模型资源不存在", "MODEL_NOT_FOUND": "服务商报告模型不存在",
    "RATE_LIMIT": "服务限流",
    "SERVER_ERROR": "服务端错误", "TIMEOUT": "请求超时",
    "CONNECTION_ERROR": "无法连接服务，请核对地址和网络",
    "RESPONSE_PROTOCOL": "HTTP 成功，但回复格式不符合 Chat Completions 协议",
    "HTTP_ERROR": "服务商拒绝了请求", "SDK_OR_RESPONSE_ERROR": "SDK 请求或响应处理失败",
}
_PHASE_LABELS = {"agent": "对话请求", "connection": "基础连接", "function_calling": "工具检测"}


def describe_failure(data):
    status = data.get("http_status")
    category = data.get("error_category")
    code, param = data.get("provider_error_code"), data.get("error_param")
    label = _CATEGORY_LABELS.get(category, _CATEGORY_LABELS["SDK_OR_RESPONSE_ERROR"])
    if category == "INVALID_REQUEST" and not param:
        label += "，具体错误字段未知"
    details = [label, f"HTTP {status}" if status else "", f"错误码 {code}" if code else "",
               f"参数 {param}" if param else "", _PHASE_LABELS.get(data.get("stage"), ""),
               "含工具" if data.get("has_tools") else "无工具", data.get("model") or "",
               data.get("protocol_mode") or ""]
    return " · ".join(filter(None, details))


def _safe_error_fields(error, credential):
    body = getattr(error, "body", None)
    if type(body) is not dict:
        return None, None
    nested = body.get("error")
    fields = nested if type(nested) is dict else body
    code, param = fields.get("code"), fields.get("param")
    code = str(code) if type(code) is int and code in {20012, 50505} else code
    code = code if type(code) is str and code in _ERROR_CODES and (not credential or credential not in code) else None
    param = param if (type(param) is str and len(param) <= 128 and _PARAMETER.fullmatch(param)
                      and (not credential or credential not in param)) else None
    return code, param


def _schema_issues(schema):
    """Small structural check for the JSON Schema forms used by the tool registry."""
    if not isinstance(schema, dict):
        return {"invalid_schema"}
    kind = schema.get("type")
    if kind == "array":
        return _schema_issues(schema["items"]) if "items" in schema else {"missing_array_items"}
    if kind == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict):
            return {"invalid_properties"}
        issues = set()
        if (not isinstance(required, list) or any(not isinstance(name, str) for name in required)
                or len(set(required)) != len(required) or not set(required) <= properties.keys()):
            issues.add("invalid_required")
        for child in properties.values():
            issues.update(_schema_issues(child))
        if type(schema.get("additionalProperties", True)) is not bool:
            issues.update(_schema_issues(schema["additionalProperties"]))
        return issues
    return set() if kind in ("string", "integer", "number", "boolean", "null") else {"invalid_type"}


def tool_schema_summary(tool):
    function = tool.get("function") or {}
    name = function.get("name")
    schema = function.get("parameters")
    valid_name = isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name)
    issues = _schema_issues(schema)
    if not isinstance(schema, dict) or schema.get("type") != "object":
        issues.add("parameters_not_object")
    if tool.get("type") != "function" or not valid_name:
        issues.add("invalid_function")
    return {"name": name if valid_name else None, "schema_present": schema is not None,
            "schema_issues": sorted(issues)}


def _request_shape(messages, tools, kwargs):
    roles, named, contents = [], Counter(), Counter()
    pending = set()
    unpaired = orphaned = duplicate_or_missing_ids = 0
    for message in messages:
        role = message.get("role")
        role = role if role in ("system", "user", "assistant", "tool", "developer") else "other"
        roles.append(role)
        if "name" in message:
            named[role] += 1
        content = message.get("content")
        kind = {str: "text", list: "parts", type(None): "null"}.get(type(content), "other")
        contents[kind if "content" in message else "absent"] += 1
        if role == "tool":
            identifier = message.get("tool_call_id")
            if isinstance(identifier, str) and identifier in pending:
                pending.remove(identifier)
            else:
                orphaned += 1
        else:
            unpaired += len(pending)
            pending.clear()
            if role == "assistant":
                for call in message.get("tool_calls") or ():
                    identifier = call.get("id")
                    if not isinstance(identifier, str) or not identifier or identifier in pending:
                        duplicate_or_missing_ids += 1
                    else:
                        pending.add(identifier)
    return {
        "message_roles": roles, "role_counts": dict(Counter(roles)), "named_by_role": dict(named),
        "content_types": dict(contents), "private_reasoning_count": sum("reasoning_content" in m for m in messages),
        "tool_pairing": {"missing_results": unpaired + len(pending), "orphan_results": orphaned,
                         "duplicate_or_missing_call_ids": duplicate_or_missing_ids},
        "tool_count": len(tools), "tools": [tool_schema_summary(tool) for tool in tools],
        "tool_choice": kwargs.get("tool_choice"), "response_format_present": "response_format" in kwargs,
        "extra_body_fields": sorted(kwargs.get("extra_body", {})),
        "request_body_bytes": None, "sdk_route_matches": None,
    }


class ModelTransport:
    def __init__(self,connection,trace=None):
        self.connection,self.trace=connection,trace
        p=connection.profile
        self.official_deepseek = is_official_deepseek_endpoint(p.base_url)
        self.protocol=ThinkingProtocol(p.base_url,p.model,thinking=self.official_deepseek and p.protocol!='standard',
                                       bind_environment=False)
        self.protocol.check_binding()
        self.official_qwen = is_official_qwen(p)
        self.protocol_mode = ("deepseek-thinking" if self.protocol.enabled else
                              QWEN_PREFLIGHT if self.official_qwen and p.protocol == QWEN_PREFLIGHT else "standard")
        self.attempts=self.successes=self.failures=0
        self.last_response = None
        self.diagnose_next_request = False

    def counts(self):
        return {'attempts':self.attempts,'successes':self.successes,'failures':self.failures}

    def emit(self,event,data):
        if self.trace:
            try:
                key = self.connection.api_key
                metadata = {} if event == "api.request_diagnostic" else {
                    name: value.replace(key, "[REDACTED]") if key and isinstance(value, str) else value
                    for name, value in self.connection.metadata().items()
                }
                self.trace(event, {**metadata, "protocol_mode": self.protocol_mode, **data})
            except OSError: warn_trace_degraded()

    def __call__(self, messages, tools, *, stage="agent"):
        diagnose = stage == "agent" and self.diagnose_next_request
        if diagnose:
            self.diagnose_next_request = False
        messages=self.protocol.wire(messages,bool(tools))
        profile = self.connection.profile
        if (profile.provider == "openai-compatible" and self.protocol_mode == "standard"
                and not (self.official_qwen or self.official_deepseek)):
            system = [message for message in messages if message["role"] == "system"]
            if (system and (len(system) > 1 or messages[0] is not system[0])
                    and all(set(message) == {"role", "content"} and isinstance(message["content"], str)
                            for message in system)):
                # Some chat templates accept a system message only in position zero.
                leading = {"role": "system", "content": "\n\n".join(message["content"] for message in system)}
                messages = [leading, *(message for message in messages if message["role"] != "system")]
        json_mode = stage != "connection" and (
            (profile.provider == "deepseek" and profile.base_url.rstrip("/") == "https://api.deepseek.com")
            or (self.official_qwen and profile.protocol == "standard"))
        key = self.connection.api_key
        model = profile.model if _MODEL_ID.fullmatch(profile.model) and (not key or key not in profile.model) else None
        request = {"stage": stage, "has_tools": bool(tools), "model": model, "protocol_mode": self.protocol_mode}
        timeout=60 if self.connection.profile.provider=='deepseek' else 30
        self.attempts+=1
        self.last_response = None
        self.emit('api.request',{'attempt':self.attempts,'message_chars':len(json.dumps(messages,ensure_ascii=False)),
            'tool_schema_chars':len(json.dumps(tools,ensure_ascii=False)),'usage_status':'UNKNOWN',
            'json_mode':json_mode,'timeout_seconds':timeout,**request})
        started=time.perf_counter()
        http_status = None
        response_received = False
        shape = None
        base_url = profile.base_url
        suffix = "/chat/completions"
        if base_url.lower().endswith(suffix):
            # A legacy profile keeps its saved endpoint and vault identity.
            base_url = base_url[:-len(suffix)]

        def observe_wire(http_request):
            if shape["request_body_bytes"] is not None:
                return
            # Do not decode or store the serialized body, URL, or headers.
            shape["request_body_bytes"] = len(http_request.content)
            endpoint = urlsplit(base_url)
            url = http_request.url
            shape["sdk_route_matches"] = ((url.scheme, url.host, url.port or 443)
                == (endpoint.scheme, endpoint.hostname, endpoint.port or 443)
                and url.path == endpoint.path.rstrip("/") + suffix)

        def observe_status(http_response):
            nonlocal http_status
            http_status = http_response.status_code

        try:
            from openai import OpenAI
            client_options = {}
            if self.official_qwen or stage != "agent" or diagnose:
                from openai import DefaultHttpxClient
                options = {}
                if self.official_qwen or stage != "agent":
                    # Probes and verified Qwen endpoints reject redirects that retain the POST.
                    options["follow_redirects"] = False
                if diagnose:
                    options["event_hooks"] = {"request": [observe_wire], "response": [observe_status]}
                client_options["http_client"] = DefaultHttpxClient(**options)
            with OpenAI(api_key=key, base_url=base_url, max_retries=0, timeout=timeout, **client_options) as client:
                kwargs={}
                if json_mode:
                    # 官方JSON模式只约束语法，不构成业务事实、身份或确认。
                    kwargs['response_format']={'type':'json_object'}
                if self.official_deepseek and profile.provider == "deepseek" and profile.protocol == "standard":
                    # 仅显式standard配置关闭DeepSeek Thinking；auto默认协议不改变。
                    kwargs['extra_body']={'thinking':{'type':'disabled'}}
                completions = client.chat.completions
                if self.official_qwen:
                    thinking = self.protocol_mode == QWEN_PREFLIGHT
                    kwargs["extra_body"] = {"enable_thinking": thinking}
                    if thinking:
                        kwargs["extra_body"].update(reasoning_effort="low", preserve_thinking=False)
                if tools:
                    kwargs.update(tools=tools, tool_choice="auto")
                raw_response = self.official_qwen or stage != "agent"
                if raw_response:
                    completions = completions.with_raw_response
                if diagnose:
                    shape = _request_shape(messages, tools, kwargs)
                response = completions.create(model=profile.model, messages=messages, **kwargs)
                response_received = True
                if raw_response:
                    http_status = response.status_code
                    response = response.parse()
                message = response.choices[0].message.model_dump(exclude_none=True)
                response_model = getattr(response, "model", None)
                if not self.protocol.enabled:
                    message = self.protocol.normalize(message)
                # An echo of the bound credential must never reach the Agent, a probe or Trace.
                encoded_key = json.dumps(key, ensure_ascii=False)[1:-1]
                if encoded_key and encoded_key in json.dumps([message, response_model], ensure_ascii=False):
                    raise ValueError("Unsafe response")
                if message.get("role") != "assistant" or (
                    not isinstance(message.get("content"), str) and not message.get("tool_calls")
                ):
                    raise ValueError("Invalid assistant message")
                usage=getattr(response,'usage',None)
                raw=usage if type(usage) is dict else usage.model_dump() if usage is not None else {}
                raw=raw if type(raw) is dict else {}
                counts={k:raw.get(k) if type(raw.get(k)) is int and raw[k]>=0 else None for k in ('prompt_tokens','completion_tokens','total_tokens')}
            self.successes+=1
            self.last_response = {**request, 'attempt':self.attempts,'success':True,
                'http_category':'SDK_SUCCESS','http_status':http_status,
                'response_model':response_model if type(response_model) is str and _MODEL_ID.fullmatch(response_model)
                and redact(response_model) == response_model else None,
                'usage':counts,'usage_status':'KNOWN' if all(v is not None for v in counts.values()) else 'UNKNOWN',
                'latency_ms':round((time.perf_counter()-started)*1000,3)}
            self.emit("api.response", self.last_response)
            return message
        except Exception as error:
            self.failures+=1
            status = getattr(error, "status_code", None)
            status = status if type(status) is int and 100 <= status <= 599 else http_status
            http_error = status is not None and not 200 <= status < 300
            error_type = type(error).__name__
            if http_error:
                category = "HTTP_ERROR"
                detail = _STATUS_CATEGORIES.get(status, "SERVER_ERROR" if status >= 500 else category)
            elif "Timeout" in error_type:
                category = detail = "TIMEOUT"
            elif "Connection" in error_type:
                category = detail = "CONNECTION_ERROR"
            else:
                category = "SDK_OR_RESPONSE_ERROR"
                detail = "RESPONSE_PROTOCOL" if status is not None or response_received else category
            code, param = _safe_error_fields(error, key) if http_error else (None, None)
            siliconflow_model_missing = (code == "20012"
                and urlsplit(profile.base_url).hostname in {"api.siliconflow.cn", "api.siliconflow.com"})
            if status in {400, 404} and (code in {"model_not_found", "ModelNotFound"} or siliconflow_model_missing):
                detail = "MODEL_NOT_FOUND"
            self.last_response = {**request,'attempt':self.attempts,'success':False,'http_category':category,
                'http_status':status,'error_category':detail,'provider_error_code':code,'error_param':param,
                'usage':{'prompt_tokens':None,'completion_tokens':None,'total_tokens':None},'usage_status':'UNKNOWN',
                'latency_ms':round((time.perf_counter()-started)*1000,3)}
            self.emit("api.response", self.last_response)
            raise ModelRequestError(describe_failure(self.last_response)) from None
        finally:
            if diagnose and shape is not None:
                outcome = {key: (self.last_response or {}).get(key) for key in
                           ("success", "http_status", "error_category", "provider_error_code", "error_param")}
                self.emit("api.request_diagnostic", {**request, **shape, **outcome, "attempt": self.attempts})

    def probe(self, can_continue):
        """At most two synthetic requests. Nothing invokes or registers the dummy function."""
        try:
            reply = self([{"role": "user", "content": "Reply OK."}], [], stage="connection")
        except ModelRequestError as error:
            return f"基础连接失败。{error}\n工具调用未检测。当前配置暂不适合启用 Agent。"
        content = reply.get("content")
        if not isinstance(content, str) or not content.strip() or reply.get("tool_calls"):
            self.emit("api.probe_result", {"stage": "connection", "has_tools": False, "success": False,
                                          "error_category": "RESPONSE_PROTOCOL", "http_status": self.last_response["http_status"]})
            failure = describe_failure({**self.last_response, "error_category": "RESPONSE_PROTOCOL"})
            return f"基础连接失败。{failure}\n工具调用未检测。当前配置暂不适合启用 Agent。"
        status = self.last_response["http_status"]
        basic = f"基础连接成功（HTTP {status}）。" if status else "基础连接成功。"
        if not can_continue():
            return basic + "\n工具调用未检测。"
        name = "economy_connection_probe"
        tools = [{"type": "function", "function": {"name": name, "description": "Return an empty test call.",
                  "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}}]
        try:
            reply = self([{"role": "user", "content": f"Call {name} with {{}} now. Otherwise reply in JSON."}],
                         tools, stage="function_calling")
        except ModelRequestError as error:
            return f"{basic}\n工具调用检测失败。{error}\n当前配置暂不适合启用 Agent。"
        calls = reply.get("tool_calls")
        call = calls[0] if isinstance(calls, list) and len(calls) == 1 else None
        function = call.get("function") if isinstance(call, dict) else None
        valid = (isinstance(function, dict) and call.get("type") == "function"
                 and isinstance(call.get("id"), str) and bool(call["id"].strip())
                 and function.get("name") == name and isinstance(function.get("arguments"), str)
                 and re.fullmatch(r"\s*\{\s*\}\s*", function["arguments"]) is not None)
        status = self.last_response["http_status"]
        self.emit("api.probe_result", {"stage": "function_calling", "has_tools": True, "success": valid,
                                      "error_category": None if valid else "RESPONSE_PROTOCOL", "http_status": status})
        if not valid:
            http = f"（HTTP {status}）" if status else ""
            return f"{basic}\n已收到回复{http}，但本次未返回有效工具调用，暂不适合启用 Agent。"
        return f"{basic}\n工具调用检测成功。可继续试用 Agent，实际业务兼容性尚未验证。"
