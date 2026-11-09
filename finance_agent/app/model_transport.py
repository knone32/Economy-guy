"""一个会话绑定一份解析后的连接；SDK调用与非敏感真实指标，不拥有业务状态。"""
import json
import time
from .model_config import QWEN_PREFLIGHT, is_official_qwen
from .thinking_protocol import ThinkingProtocol
from .trace import warn_trace_degraded


class ModelRequestError(RuntimeError):
    """SDK异常正文可能含凭据/业务输入，不向普通日志或CLI传播。"""


class ModelTransport:
    def __init__(self,connection,trace=None):
        self.connection,self.trace=connection,trace
        p=connection.profile
        self.protocol=ThinkingProtocol(p.base_url,p.model,thinking=p.protocol!='standard',bind_environment=False)
        self.protocol.check_binding()
        self.official_qwen = is_official_qwen(p)
        self.protocol_mode = ("deepseek-thinking" if self.protocol.enabled else
                              QWEN_PREFLIGHT if self.official_qwen and p.protocol == QWEN_PREFLIGHT else "standard")
        self.attempts=self.successes=self.failures=0

    def counts(self):
        return {'attempts':self.attempts,'successes':self.successes,'failures':self.failures}

    def emit(self,event,data):
        if self.trace:
            try: self.trace(event,{**self.connection.metadata(),'protocol_mode':self.protocol_mode,**data})
            except OSError: warn_trace_degraded()

    def __call__(self,messages,tools):
        from openai import OpenAI
        messages=self.protocol.wire(messages,bool(tools))
        json_mode=self.connection.profile.provider=='deepseek' and self.connection.profile.base_url.rstrip('/')=='https://api.deepseek.com'
        timeout=60 if self.connection.profile.provider=='deepseek' else 30
        self.attempts+=1
        self.emit('api.request',{'attempt':self.attempts,'message_chars':len(json.dumps(messages,ensure_ascii=False)),
            'tool_schema_chars':len(json.dumps(tools,ensure_ascii=False)),'usage_status':'UNKNOWN',
            'json_mode':json_mode,'timeout_seconds':timeout})
        started=time.perf_counter()
        try:
            client_options = {}
            if self.official_qwen:
                # A redirect is outside the verified endpoint, including a redirect with a retained POST body.
                from openai import DefaultHttpxClient
                client_options["http_client"] = DefaultHttpxClient(follow_redirects=False)
            with OpenAI(api_key=self.connection.api_key,base_url=self.connection.profile.base_url,
                        max_retries=0,timeout=timeout,**client_options) as client:
                kwargs={}
                if json_mode:
                    # 官方JSON模式只约束语法，不构成业务事实、身份或确认。
                    kwargs['response_format']={'type':'json_object'}
                if self.connection.profile.provider=='deepseek' and self.connection.profile.protocol=='standard':
                    # 仅显式standard配置关闭DeepSeek Thinking；auto默认协议不改变。
                    kwargs['extra_body']={'thinking':{'type':'disabled'}}
                completions = client.chat.completions
                if self.official_qwen:
                    thinking = self.protocol_mode == QWEN_PREFLIGHT
                    kwargs["extra_body"] = {"enable_thinking": thinking}
                    if thinking:
                        kwargs["extra_body"].update(reasoning_effort="low", preserve_thinking=False)
                    completions = completions.with_raw_response
                response = completions.create(model=self.connection.profile.model, messages=messages,
                                              tools=tools, tool_choice="auto", **kwargs)
                http_status = None
                if self.official_qwen:
                    http_status = response.status_code
                    response = response.parse()
                message = response.choices[0].message.model_dump(exclude_none=True)
                response_model = getattr(response, "model", None)
                if self.official_qwen:
                    message = self.protocol.normalize(message)
                    # A server echo of the bound credential cannot become visible text, tool input or Trace.
                    key = json.dumps(self.connection.api_key, ensure_ascii=False)[1:-1]
                    if key and key in json.dumps([message, response_model], ensure_ascii=False):
                        raise ModelRequestError("模型响应包含凭据，已停止")
                usage=getattr(response,'usage',None)
                raw=usage if type(usage) is dict else usage.model_dump() if usage is not None else {}
                raw=raw if type(raw) is dict else {}
                counts={k:raw.get(k) if type(raw.get(k)) is int and raw[k]>=0 else None for k in ('prompt_tokens','completion_tokens','total_tokens')}
            self.successes+=1
            self.emit('api.response',{'attempt':self.attempts,'success':True,'http_category':'SDK_SUCCESS','http_status':http_status,
                'response_model':response_model if type(response_model) is str else None,
                'usage':counts,'usage_status':'KNOWN' if all(v is not None for v in counts.values()) else 'UNKNOWN',
                'latency_ms':round((time.perf_counter()-started)*1000,3)})
            return message
        except Exception as error:
            self.failures+=1
            status=getattr(error,'status_code',None)
            status=status if type(status) is int else None
            category='HTTP_ERROR' if status else 'TIMEOUT' if 'Timeout' in type(error).__name__ else 'CONNECTION_ERROR' if 'Connection' in type(error).__name__ else 'SDK_OR_RESPONSE_ERROR'
            self.emit('api.response',{'attempt':self.attempts,'success':False,'http_category':category,'http_status':status,
                'usage':{'prompt_tokens':None,'completion_tokens':None,'total_tokens':None},'usage_status':'UNKNOWN',
                'latency_ms':round((time.perf_counter()-started)*1000,3)})
            raise ModelRequestError('模型请求失败，错误类别见安全Trace；未确认新的业务成功') from None
