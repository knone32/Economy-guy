"""可信本地模型Profile与凭据引用；不读写业务SQLite，不提供LLM工具。"""
from collections import Counter
from dataclasses import dataclass,field,asdict
from hashlib import sha256
import ipaddress
import json
import os
from pathlib import Path
import re
import tempfile
import tomllib
from urllib.parse import urlsplit

CONFIG=Path(__file__).resolve().parents[1]/'config'
DEFAULT_TEMPLATE=CONFIG/'model_profiles.toml'
DEFAULT_LOCAL=CONFIG/'model_profiles.local.json'
QWEN_SNAPSHOT = "qwen3.8-max-0902"
QWEN_MODELS = frozenset({"qwen3.8-max", QWEN_SNAPSHOT, "qwen3.8-flash"})
QWEN_PREFLIGHT = "qwen-thinking-preflight"
PROFILE_PROTOCOLS = ("auto", "standard", "deepseek-thinking", QWEN_PREFLIGHT)


class ProfileError(ValueError):
    """不在错误信息中复述密钥或不安全配置值。"""


def safe_url(value):
    """只接受显式HTTPS服务地址，拒绝凭据/查询串/本机及私网字面量。"""
    try:
        p = urlsplit(value)
        host = p.hostname
        if (p.scheme != 'https' or not host or p.username is not None or p.password is not None
            or '?' in value or '#' in value or '\\' in value or '%' in host
            or any(c.isspace() or ord(c) < 32 for c in value) or p.port not in (None, 443)):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            domain = host.encode('idna').decode('ascii').lower().removesuffix('.')
            if domain == 'localhost' or domain.endswith('.localhost') or p.netloc.startswith('['):
                raise ValueError()
            # Legacy IPv4 parsers accept short, octal, hex and single-integer forms.
            component = r'(?:[0-9]+|0x[0-9a-f]*)'
            if re.fullmatch(rf'{component}(?:\.{component})*', domain):
                raise ValueError()
            label = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
            if len(domain) > 253 or not re.fullmatch(rf'{label}(?:\.{label})*', domain):
                raise ValueError()
        else:
            if not address.is_global or address.is_multicast:
                raise ValueError()
        return value.rstrip('/')
    except (ValueError,TypeError):
        raise ProfileError('模型URL不安全或格式无效，未连接') from None


@dataclass(frozen=True)
class Profile:
    profile_name: str
    scope: str
    owner_user_id: str | None
    provider: str
    service_account_ref: str
    model: str
    base_url: str
    api_key_env: str
    protocol: str='auto'

    @property
    def identity(self):
        return self.scope, self.owner_user_id, self.profile_name


def _name_conflict(profiles, candidate):
    # Global names remain reserved to keep CLI and saved unqualified choices unambiguous.
    return any(p.identity == candidate.identity or
               (p.profile_name == candidate.profile_name and "global" in (p.scope, candidate.scope))
               for p in profiles)


def is_official_qwen(profile):
    """Recognize exact Qwen 3.8 IDs on documented Bailian Chat Completions endpoints."""
    if (profile.provider != "openai-compatible" or profile.model not in QWEN_MODELS
            or profile.protocol not in {"auto", "standard", QWEN_PREFLIGHT}):
        return False
    endpoint = urlsplit(safe_url(profile.base_url))
    if endpoint.path != "/compatible-mode/v1":
        return False
    host = endpoint.hostname
    return host in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com",
                    "cn-hongkong.dashscope.aliyuncs.com"} or bool(re.fullmatch(
        r"[a-z0-9][a-z0-9-]*\.(?:cn-beijing|ap-southeast-1|us-east-1|eu-central-1|"
        r"ap-northeast-1|cn-hongkong)\.maas\.aliyuncs\.com", host))


def validate_profile(data, *, new=False):
    """所有存储来源使用同一白名单；只保存环境变量名称。"""
    fields = set(Profile.__dataclass_fields__)
    optional = {"protocol", "owner_user_id"} | ({"service_account_ref"} if new else set())
    if type(data) is not dict or set(data)-fields or fields-optional-set(data):
        raise ProfileError('Profile字段缺失或含不支持字段；不接受明文凭据')
    values={**data,'owner_user_id':data.get('owner_user_id'),'protocol':data.get('protocol','auto')}
    for key in ('profile_name','provider','model','api_key_env','base_url','protocol','scope'):
        if type(values[key]) is not str or not values[key].strip():
            raise ProfileError('Profile必要字段必须明确')
    name = values["profile_name"]
    if (len(name) > 64 or name != name.strip()
            or not all(char.isalnum() or char in " ._-" for char in name)):
        raise ProfileError("配置名称须为 1–64 个字符，可用中文、字母、数字、内部空格、点、下划线或短横线。")
    if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}',values['api_key_env']):
        raise ProfileError('api_key_env必须是环境变量名称，不是实际Key')
    if values['provider'] not in {'deepseek','openai','openai-compatible'} or values['protocol'] not in PROFILE_PROTOCOLS:
        raise ProfileError('不支持该Provider或协议配置')
    if values['scope'] not in {'global','user'} or (values['scope']=='global' and values['owner_user_id'] is not None):
        raise ProfileError('Profile范围或归属不合法')
    if values['scope']=='user' and (type(values['owner_user_id']) is not str or not re.fullmatch(r'U\d{3,}',values['owner_user_id'])):
        raise ProfileError('User Profile必须绑定可信模拟用户')
    values['base_url']=safe_url(values['base_url'])
    if new and values["base_url"].lower().endswith("/chat/completions"):
        raise ProfileError("请填写 SDK Base URL，去掉末尾的 /chat/completions。")
    ref = values.get("service_account_ref")
    if new and ref in (None, ""):
        identity = json.dumps([values["scope"], values["owner_user_id"], name, values["base_url"]], ensure_ascii=False)
        ref = "acct_" + sha256(identity.encode("utf-8")).hexdigest()[:24]
    if type(ref) is not str or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", ref):
        raise ProfileError("服务账户逻辑引用须使用 ASCII 字母、数字、点、下划线或短横线。")
    p = Profile(**{**values, "service_account_ref": ref})
    if p.protocol == QWEN_PREFLIGHT and (p.model != QWEN_SNAPSHOT or not is_official_qwen(p)):
        raise ProfileError("Qwen 思考预检仅支持指定快照和百炼官方端点")
    # 兼容代理在 auto 下走标准协议。只有显式选择 Thinking 才校验该专用能力。
    from .thinking_protocol import ThinkingProtocol
    if p.protocol == "deepseek-thinking" and not ThinkingProtocol(
        p.base_url, p.model, bind_environment=False
    ).enabled:
        raise ProfileError('该端点/模型尚无已验证Thinking协议配置')
    return p


def load_profiles(template=DEFAULT_TEMPLATE,local=DEFAULT_LOCAL):
    """合并静态模板与本地新增，不静默覆盖同名或冲突默认项。"""
    profiles={};defaults=[]
    for path,kind in ((Path(template),'toml'),(Path(local),'json')):
        if not path.exists():
            if kind=='toml': raise ProfileError('缺少模型配置模板')
            continue
        try:
            raw=tomllib.loads(path.read_text(encoding='utf-8')) if kind=='toml' else json.loads(path.read_text(encoding='utf-8'))
            if type(raw) is not dict or set(raw)-{'profiles','settings','version'} or type(raw.get('profiles',[])) is not list:
                raise ValueError()
            if type(raw.get('version',1)) is not int or raw.get('version',1)!=1:
                raise ValueError()
            setting=raw.get('settings',{})
            if type(setting) is not dict or set(setting)-{'default_profile'}:
                raise ValueError()
            default=setting.get('default_profile','')
            if type(default) is not str: raise ValueError()
            if default: defaults.append(default)
            for item in raw.get('profiles',[]):
                p=validate_profile(item)
                if _name_conflict(profiles.values(), p):
                    raise ProfileError('Profile同名或来源冲突；全局名称不得与个人配置共用')
                if p.scope == "user" and any(
                    other.profile_name == p.profile_name and other.api_key_env == p.api_key_env
                    for other in profiles.values()
                ):
                    raise ProfileError("不同账号的同名配置必须使用独立凭据环境变量")
                profiles[p.identity]=p
        except ProfileError:
            raise
        except (OSError,ValueError,TypeError):
            raise ProfileError('模型配置文件异常，未修改原文件') from None
    if len(set(defaults))>1: raise ProfileError('默认Profile来源冲突')
    names = Counter(p.profile_name for p in profiles.values())
    # Preserve existing plain-name reads for unambiguous catalogs.
    catalog = {p.profile_name if names[p.profile_name] == 1 else p.identity: p for p in profiles.values()}
    return catalog, defaults[0] if defaults else None


def visible_profiles(user_id,template=DEFAULT_TEMPLATE,local=DEFAULT_LOCAL):
    profiles,_=load_profiles(template,local)
    return [asdict(p) for p in profiles.values() if p.scope=='global' or p.owner_user_id==user_id]


def add_profile(data,user_id=None,simulate_manager=False,template=DEFAULT_TEMPLATE,local=DEFAULT_LOCAL, *,
                isolated_credentials=False):
    """仅可信CLI添加；锁内校验、fsync后原子替换，不覆盖同名配置。"""
    p = validate_profile(data, new=True)
    if p.scope=='global' and not simulate_manager:
        raise ProfileError('Global新增需要显式模拟profile.manage管理入口；不是U001默认权限')
    if p.scope=='user' and p.owner_user_id!=user_id:
        raise ProfileError('User新增只能绑定可信CLI当前模拟用户')
    return _store_profile(p, template, local, isolated_credentials=isolated_credentials)


def update_user_profile(previous, data, user_id, *, template=DEFAULT_TEMPLATE, local=DEFAULT_LOCAL):
    """Replace exactly the local personal record the user opened for editing."""
    candidate = validate_profile(data)
    if (previous.scope != "user" or previous.owner_user_id != user_id
            or (candidate.scope, candidate.owner_user_id, candidate.profile_name)
            != (previous.scope, previous.owner_user_id, previous.profile_name)):
        raise ProfileError("只能编辑本人本地个人配置，名称及归属保持固定")
    if candidate.base_url != previous.base_url and candidate.api_key_env == previous.api_key_env:
        raise ProfileError("更换端点时请使用新的凭据环境变量引用，避免沿用旧端点密钥")
    return _store_profile(candidate, template, local, previous=previous, isolated_credentials=True)


def _store_profile(profile, template, local, *, previous=None, isolated_credentials=False):
    path = Path(local)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise ProfileError("模型配置目录不可写，未修改") from None
    lock=path.with_name(path.name+'.lock');temp=None
    try:
        fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except OSError:
        raise ProfileError('模型配置正在编辑或不可写，未修改') from None
    try:
        os.close(fd)
        profiles,_=load_profiles(template,path)
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1, "profiles": []}
        rows = raw.setdefault("profiles", [])
        if previous is None:
            if _name_conflict(profiles.values(), profile):
                raise ProfileError("Profile同名或归属冲突；全局名称不得与个人配置共用")
            index = len(rows)
        else:
            current = next((p for p in profiles.values() if p.identity == previous.identity), None)
            if current != previous:
                raise ProfileError("配置已变更，请重新打开详情后编辑，未覆盖")
            index = next((i for i, row in enumerate(rows)
                          if (row["scope"], row.get("owner_user_id"), row["profile_name"]) == previous.identity), None)
            if index is None:
                raise ProfileError("此配置由模板提供，仅可查看和使用")
        if any(
            other.identity != profile.identity and other.api_key_env == profile.api_key_env
            and ((other.scope == profile.scope == "user" and other.owner_user_id != profile.owner_user_id)
                 or (isolated_credentials and (other.base_url != profile.base_url
                                               or other.owner_user_id != profile.owner_user_id)))
            for other in profiles.values()
        ):
            raise ProfileError("不同账号或端点请使用独立的凭据环境变量引用")
        rows[index:index + 1] = [asdict(profile)]
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,suffix='.tmp',delete=False) as stream:
            temp=Path(stream.name)
            json.dump(raw,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path);temp=None
    except ProfileError:
        raise
    except (OSError,ValueError):
        raise ProfileError('模型配置保存失败，未确认更新；请检查原配置') from None
    finally:
        if temp is not None: temp.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)
    return asdict(profile)


@dataclass(frozen=True)
class ModelConnection:
    """创建时冻结私有凭据；不对Key做可追踪指纹，不逐轮读取环境变量。"""
    profile: Profile
    _api_key: str=field(repr=False,compare=False)

    @property
    def api_key(self): return self._api_key

    def authorize(self,user_id):
        if self.profile.scope=='user' and self.profile.owner_user_id!=user_id:
            raise ProfileError('当前用户无权选择此Profile，未回退')

    def metadata(self):
        p=self.profile
        return {**{k:getattr(p,k) for k in ('profile_name','provider','model','service_account_ref','protocol')},'profile_scope':p.scope}


def resolve_connection(user_id,profile=None,*,template=DEFAULT_TEMPLATE,local=DEFAULT_LOCAL,require_key=True):
    """CLI→环境Profile→文件默认→完整旧环境组；不拼接不完整组或自动回退。"""
    profiles,default=load_profiles(template,local)
    name=profile or os.getenv('FINANCE_MODEL_PROFILE') or default
    if name:
        p = next((item for item in profiles.values() if item.profile_name == name
                  and (item.scope == 'global' or item.owner_user_id == user_id)), None)
        if p is None:
            if any(item.profile_name == name for item in profiles.values()):
                raise ProfileError('当前用户无权选择此Profile，未回退')
            raise ProfileError('指定Profile不存在，未回退')
        key=os.getenv(p.api_key_env,'') if require_key else ''
    else:
        modern=[os.getenv('OPENAI_'+suffix) for suffix in ('API_KEY','BASE_URL','MODEL')]
        if any(modern):
            if not all(modern): raise ProfileError('OPENAI配置组不完整，禁止混入旧组')
            key,url,model=modern
            key_env='OPENAI_API_KEY'
        else:
            key=os.getenv('KEY') or os.getenv('API_KEY');url=os.getenv('BASE_URL');model=os.getenv('MODEL')
            if not all((key,url,model)): raise ProfileError('需要完整KEY/BASE_URL/MODEL或OPENAI配置组')
            key_env='KEY' if os.getenv('KEY') else 'API_KEY'
        p=validate_profile(profile_data_legacy(url,model,key_env))
        if not require_key: key=''
    if require_key and not key.strip(): raise ProfileError('当前Profile缺少其引用的API凭据，未回退')
    return ModelConnection(p,key)


def profile_data_legacy(url,model,key_env='OPENAI_API_KEY'):
    return {'profile_name':'legacy-env','scope':'global','owner_user_id':None,
        'provider':'deepseek' if urlsplit(url).hostname=='api.deepseek.com' else 'openai-compatible',
        'service_account_ref':'legacy-unverified','model':model,'base_url':url,'api_key_env':key_env,'protocol':'auto'}
