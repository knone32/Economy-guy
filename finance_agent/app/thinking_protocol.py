"""仅DeepSeek已验证端点的私有消息传输；不保存业务事实或授权。"""
import json
import os
from urllib.parse import urlsplit


class ProtocolError(ValueError):
    """协议不明确/字段不合法时停止，不猜测推理内容。"""


class PrivateAssistant(dict):
    """普通dict只含业务消息；私有字段不参与repr/JSON/工具参数。"""
    __slots__=('reasoning',)

    def __init__(self,message,reasoning):
        super().__init__(message)
        self.reasoning=reasoning


def settings():
    """仅公共传输标识，不读取或保存密钥。"""
    return (os.getenv('OPENAI_BASE_URL') or os.getenv('BASE_URL') or '',
            os.getenv('OPENAI_MODEL') or os.getenv('MODEL') or '')


class ThinkingProtocol:
    """协议状态随消息对象存活；只在构造API输入时还原。"""
    def __init__(self,base_url=None,model=None,thinking=True):
        self.binding=settings() if base_url is None else (base_url,model)
        url,name=self.binding
        parsed=urlsplit(url)
        official=(parsed.scheme=='https' and parsed.hostname=='api.deepseek.com'
                  and parsed.port in (None,443) and not parsed.username and not parsed.password
                  and parsed.path.rstrip('/') in ('','/v1') and not parsed.query and not parsed.fragment)
        known=name in {'deepseek-flash','deepseek-v4-pro'}
        self.ambiguous=known and not official
        self.enabled=bool(official and known and thinking)

    def check_binding(self):
        if settings()!=self.binding:
            raise ProtocolError('服务配置已变化，请退出并新建会话；不跨服务传递旧协议历史')
        if self.ambiguous:
            raise ProtocolError('自定义DeepSeek代理协议未明确配置，停止猜测；请使用已验证官方端点')

    def normalize(self,reply,tools=True):
        """实际模型缺字段/None不补造；真实空字符串按原样保留。"""
        message={key:reply[key] for key in ('role','content','tool_calls') if key in reply}
        if self.enabled and tools:
            if type(reply.get('reasoning_content')) is not str:
                raise ProtocolError('Thinking响应缺少合法私有协议字段')
            return PrivateAssistant(message,reply['reasoning_content'])
        return message

    def wire(self,messages,tools=True):
        """传输副本保留原顺序；脱敏标记从不回流到服务商。"""
        output=[]
        for message in messages:
            value={k:v for k,v in message.items() if k!='reasoning_content'}
            if self.enabled and tools and message.get('role')=='assistant':
                if isinstance(message,PrivateAssistant):
                    reasoning=message.reasoning
                elif 'reasoning_content' in message:
                    reasoning=message['reasoning_content']
                elif message.get('name') in {'context_data','harness_history','harness_schedule','reference_data','harness_output'}:
                    # 明确标记来源的本地数据没有经过模型推理；空协议槽不是补造模型返回值。
                    reasoning=''
                else:
                    raise ProtocolError('缺少与assistant消息绑定的实际协议字段')
                if type(reasoning) is not str:
                    raise ProtocolError('私有协议字段类型无效')
                value['reasoning_content']=reasoning
            output.append(value)
        return output

    def size(self,messages):
        """Context仍按字符计数，但必须包含实际待发送的完整私有字段。"""
        return len(json.dumps(self.wire(messages),ensure_ascii=False))

    def metadata(self,messages):
        fields=[m['reasoning_content'] for m in messages if 'reasoning_content' in m]
        return {'enabled':self.enabled,'private_fields':len(fields),'private_chars':sum(map(len,fields)),
                'usage':'仅私有协议传输，不是业务事实/授权；Trace隐藏字段正文'}
