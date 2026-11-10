"""一个会话绑定一份解析后的连接；SDK调用与非敏感真实指标，不拥有业务状态。"""
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
    r"parameters|type|properties|required|additionalProperties|strict)){0,10}"
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

    def counts(self):
        return {'attempts':self.attempts,'successes':self.successes,'failures':self.failures}

    def emit(self,event,data):
        if self.trace:
            try:
                key = self.connection.api_key
                metadata = {name: value.replace(key, "[REDACTED]") if key and isinstance(value, str) else value
                            for name, value in self.connection.metadata().items()}
                self.trace(event, {**metadata, "protocol_mode": self.protocol_mode, **data})
            except OSError: warn_trace_degraded()

    def __call__(self, messages, tools, *, stage="agent"):
        messages=self.protocol.wire(messages,bool(tools))
        profile = self.connection.profile
        json_mode = stage != "connection" and (
            (profile.provider == "deepseek" and profile.base_url.rstrip("/") == "https://api.deepseek.com")
            or (self.official_qwen and profile.protocol == "standard"))
        key = self.connection.api_key
        model = profile.model if _MODEL_ID.fullmatch(profile.model) and (not key or key not in profile.model) else None
        request = {"stage": stage, "has_tools": bool(tools), "model": model, "protocol_mode": self.protocol_mode}
        timeout=60 if self.connection.profile.provider=='deepseek' else 30
        self.attempts+=1
        self.emit('api.request',{'attempt':self.attempts,'message_chars':len(json.dumps(messages,ensure_ascii=False)),
            'tool_schema_chars':len(json.dumps(tools,ensure_ascii=False)),'usage_status':'UNKNOWN',
            'json_mode':json_mode,'timeout_seconds':timeout,**request})
        started=time.perf_counter()
        http_status = None
        response_received = False
        try:
            from openai import OpenAI
            client_options = {}
            if self.official_qwen or stage != "agent":
                # Probes stay on the explicitly selected address, including for redirects that retain a POST body.
                from openai import DefaultHttpxClient
                client_options["http_client"] = DefaultHttpxClient(follow_redirects=False)
            base_url = profile.base_url
            suffix = "/chat/completions"
            if base_url.lower().endswith(suffix):
                # A legacy profile keeps its saved endpoint and vault identity.
                base_url = base_url[:-len(suffix)]
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
