"""Immutable, current-user read requirements, fixed before tool generation.

The model interprets language. Runtime verifies sources, registered identities,
permissions and finite structure; this never asserts a formal proof of intent.
"""
from dataclasses import dataclass, asdict, is_dataclass
from datetime import date
from pathlib import Path
from contextlib import closing
import sqlite3

from .seller_semantic_review import load_review, digest
from .seller_read_scope import catalog as seller_catalog, full_mentions, SellerReadError, validate_source
from .controlled_read_scope import catalog as company_catalog, bind as bind_read_scope, ReadBindingError
from .business_object_sources import registered_company_mentions, amendment_sources
from .provenance import READ_SOURCES, ScopeProof
from .intent_contract import validate as validate_read_intent, IntentContractError
from .responses import request_scope
from .stage2_schema import open_existing
from .permissions import check_permission


class BusinessRequestError(ValueError):
    def __init__(self,message,status='AMBIGUOUS',*,candidates=(),slot=None):
        super().__init__(message)
        self.status,self.candidates,self.slot=status,tuple(candidates),slot


def _immutable(value):
    if type(value) in (str,int,bool,type(None)) or is_dataclass(value):return value
    if isinstance(value,(tuple,list)):return tuple(_immutable(v) for v in value)
    raise TypeError('要求不能持有可变或未知结构')


def _freeze_fields(owner,*fields):
    for name in fields:object.__setattr__(owner,name,_immutable(getattr(owner,name)))


@dataclass(frozen=True)
class Source:
    kind: str
    quote: str
    key: str | None = None

    def __post_init__(self):
        if type(self.kind) is not str or type(self.quote) is not str or self.key is not None and type(self.key) is not str:
            raise TypeError('来源必须是不可变文字字段')


@dataclass(frozen=True)
class SellerRequirement:
    mode: str
    names: tuple
    value: str
    source: Source

    def __post_init__(self):_freeze_fields(self,'names')


@dataclass(frozen=True)
class ReadFilter:
    field: str
    operator: str
    value: str | int | bool | tuple
    source: Source

    def __post_init__(self):_freeze_fields(self,'value')


@dataclass(frozen=True)
class ReadMetric:
    operation: str
    field: str
    source: Source


@dataclass(frozen=True)
class ReadComparison:
    operation: str
    metric_operation: str
    metric_field: str
    left_period: tuple
    right_period: tuple
    source: Source

    def __post_init__(self):_freeze_fields(self,'left_period','right_period')


@dataclass(frozen=True)
class ReadRequirement:
    target_id: str
    object: str
    company_ids: tuple
    periods: tuple
    seller: SellerRequirement | None = None
    filters: tuple = ()
    metrics: tuple = ()
    group_by: tuple = ()
    comparisons: tuple = ()
    company_source: Source | None = None
    period_source: Source | None = None
    relation: str = 'update'
    relation_source: Source | None = None
    previous_target_id: str | None = None

    def __post_init__(self):
        _freeze_fields(self,'company_ids','periods','filters','metrics','group_by','comparisons')


@dataclass(frozen=True)
class BusinessRequest:
    actor: str
    workbook: str
    turn_id: str
    revision: int
    current_source: Source
    request_hash: str
    catalog_hash: str
    targets: tuple
    unresolved: tuple = ()
    context_transition: str = 'continue'
    previous_request_revision: int | None = None
    previous_request_hash: str | None = None

    def __post_init__(self):
        _freeze_fields(self,'targets','unresolved')
        if not isinstance(self.current_source,Source) or any(not isinstance(t,ReadRequirement) for t in self.targets):
            raise TypeError('要求必须持有受控的不可变来源和目标')
        if type(self.revision) is not int or self.revision<1:
            raise TypeError('要求修订号无效')
        if (type(self.context_transition) is not str or self.context_transition not in {'continue','pending_to_read'}
                or self.previous_request_revision is not None and type(self.previous_request_revision) is not int
                or self.previous_request_hash is not None and type(self.previous_request_hash) is not str):
            raise TypeError('读取过渡只可保存不可变类型的来源引用')

    def metadata(self):
        return {**asdict(self),'interpretation':'model_with_current_user_sources',
                'formal_semantic_proof':False,'authorization':False}

    def require_context(self,actor,book,turn_id=None):
        """Check effective prior requirements before exposing them to a model."""
        if (actor!=self.actor or str(Path(book).resolve())!=self.workbook
                or turn_id is not None and turn_id!=self.turn_id
                or self.current_source.kind!='current'
                or digest(self.current_source.quote)!=self.request_hash):
            raise BusinessRequestError('本次读取要求不属于当前身份、账簿或轮次。','DENIED')
        ids=tuple(sorted({company for target in self.targets for company in target.company_ids}))
        current=read_catalog(book,actor,company_ids=ids)
        if digest(current)!=self.catalog_hash:
            raise BusinessRequestError('企业、账期或销售方目录已变化，请重新明确本次要求。','SCOPE_MISMATCH')
        return self

    def require_current(self,actor,book,turn_id=None):
        self.require_context(actor,book,turn_id)
        if self.unresolved:
            raise BusinessRequestError('本次读取要求仍有待澄清项，请先明确对象与条件。')
        return self


def read_catalog(book,actor,*,company_ids=None):
    current=company_catalog(book,actor)
    rows=current['companies']
    if company_ids is not None:
        if not set(company_ids)<={r['company_id'] for r in rows}:
            raise BusinessRequestError('当前账号没有目标企业读取权限。','DENIED')
        rows=[r for r in rows if r['company_id'] in company_ids]
    companies=[]
    for row in rows:
        item={**row}
        try:
            item['seller_names']=seller_catalog(book,actor,(row['company_id'],))
            item['seller_catalog_complete']=True
        except SellerReadError as error:
            # A large invoice directory must not block an unrelated bank target.
            item['seller_names']=[];item['seller_catalog_complete']=False
            item['seller_catalog_status']=error.status
        companies.append(item)
    return {'source':'current_authorized_workbook','companies':companies,'read_only':True}


# Actual business columns, not a generated SQL proposal or language router.
BUSINESS_FIELDS = {
 'invoices':{'company_id':'企业编号','invoice_no':'发票号码（与企业编号组成联合键）',
   'invoice_date':'开票日期（YYYY-MM-DD）','seller_name':'销售方名称','item_name':'项目',
   'amount_cents':'发票价税合计，整数分','purpose':'用途','remark':'备注'},
 'bank_transactions':{'company_id':'企业编号','transaction_no':'银行交易编号',
   'transaction_date':'交易日期（YYYY-MM-DD）','direction':'方向（收入/支出）',
   'amount_cents':'银行金额，整数分；收入与支出分算','counterparty_name':'交易对方','remark':'备注'}}
GROUP_FIELDS = {obj:frozenset(fields)|{'period'} for obj,fields in BUSINESS_FIELDS.items()}


DEFINITION = {
 'objects':{'invoices':'发票价税合计金额、张数、明细；销售方属于发票对象',
            'bank_transactions':'银行收入/支出分别统计，不能抵销；交易方不等于发票销售方'},
 'money':'源账金额是整数分；业务金额元。金额与张数不可替换。',
 'identity':'简称多家先ambiguous；全部发票不等于所有名称包含词的销售方；不凭目录代选。',
 'fields':BUSINESS_FIELDS,
 'groups':{obj:sorted(fields) for obj,fields in GROUP_FIELDS.items()},
 'period':'账期为YYYY-MM；明确完整年月可以无记录，不从记录目录默认补日期。',
 'units':{'amount_cents':'整数分','sum(amount_cents)':'整数分，显示元时除100','count(*)':'条/张'},
 'protocol':{
   'read_top_level':{'allowed_keys':['kind','targets','unresolved'],'kind':'read',
      'additional_keys':False,'targets':'1至12个对象target的JSON列表',
      'unresolved':'JSON字符串列表list[str]，无未决项用[]；不能放对象、字段描述字典或布尔值'},
   'company_source':{'allowed':['current','context'],'default':'current',
      'current':'company_quote为当前原话连续片段，登记对象须与company_ids一致',
      'context':'仅可引用trusted_scope中唯一企业；company_quote可为空'},
   'period_source':{'allowed':['current','context'],'default':'current',
      'current':'period_quote为当前原话连续片段，periods须逐对对应；完整年月允许无记录',
      'context':'periods须等于当前trusted_scope.periods；period_quote可为空',
      'annual':'Agent已将可信完整年度规范为12个月时，使用period_source=context并逐对列出这12个月；不从目录补年'},
   'seller':{'required_for':'invoices；bank_transactions省略或null',
      'modes':['single','set','ambiguous','none'],
      'quote':'所有mode均须非空、当前原话中的目标自身连续片段；有效context来源除外',
      'none':'value必须为空串；quote引用本目标统计或明细要求本身，不虚构“无筛选”原话，不混入其他对象条件',
      'single':'一家登记销售方，不能从共享简称代选',
      'set':'用户明确名称包含范围，value为当前quote中的包含词；quote不可仅等于value',
      'ambiguous':'value仍是当前quote中的原话简称字符串，不能放候选名称列表；实际候选由Runtime目录产生；不能改成set'},
   'filter_operators':{
      '=':{'value':'单一字符串、整数或布尔值'},'!=':{'value':'单一字符串、整数或布尔值'},
      '>':{'value':'单一字符串或整数'},'>=':{'value':'单一字符串或整数'},
      '<':{'value':'单一字符串或整数'},'<=':{'value':'单一字符串或整数'},
      'IN':{'value':'非空JSON列表；每个任意文本值均须有quote中的字面来源'},
      'LIKE':{'value':'SQL模式字符串；去掉%/_后的非空文本片段均须出现在quote'},
      'is_blank':{'value':'','meaning':'空值条件使用空字符串，不用null；仍须真实非空quote'}},
   'filter_source':'每个filter须field/operator/value/quote；quote为当前条件连续原话。金额值按整数分归一，关系解释来自模型而非程序语义证明',
   'bank_direction':{'operators':['=','IN'],'values':['收入','支出'],
      'source':'必须有真实当前quote，允许模型将用户表达归一到有限枚举；不是关键词匹配证明',
      'sum':'单方向过滤，或group_by包含direction；IN同时含收入和支出时仍须按direction分组'},
   'metric_operations':['sum','count','details','min','max'],
   'metric_fields':{'invoices':['invoice_no','invoice_date','item_name','purpose','remark','amount_cents','*'],
      'bank_transactions':['transaction_no','transaction_date','direction','counterparty_name','remark','amount_cents','*']},
   'metrics':'每项operation/field/quote；field限metric_fields中的本对象字段；张数用count(*)，明细用details(*)；金额sum(amount_cents)',
   'group_by':'只用groups中本对象实际字段或period，不传SQL表达式',
   'comparisons':'每项operation=subtract或compare，metric_operation/metric_field须已在同target.metrics中；left_period/right_period均在该target.periods内，quote须当前原话',
   'revision_relation':{'allowed':['update','replace','clarify'],'default':'update',
      'source':'显式relation须有relation_quote当前连续原话',
      'replace':'必须提供previous_target_id，引用previous_requirement中实际旧目标；新目标仍须当前来源和权限核实；允许明确新查询不保留旧seller/filter',
      'update':'默认保持旧条件；不能静默删除旧seller/filter；clarify保留未决、不执行'},
   'context_source':{'kind':'context','key':'target_id.seller 或 target_id.filters.索引 或 target_id.metrics.索引'},
   'context_source_rule':'seller/filter/metric继承时字段、关系和值必须与previous_requirement相同；quote可空，程序重取原来源；company_source/period_source使用上面的字符串字段'},
 'output':{'kind':'read','targets':[{'target_id':'i1','object':'invoices',
 'company_ids':['当前登记ID'],'company_quote':'当前原话或context来源',
 'periods':[[2026,9]],'period_quote':'当前账期原话',
 'seller':{'mode':'single|set|ambiguous|none','quote':'当前完整条件原话','value':'名称/包含词，none空串'},
 'filters':[{'field':'purpose','operator':'=','value':'原话值','quote':'原话条件'}],
 'metrics':[{'operation':'sum|count|details|min|max','field':'实际业务字段|*','quote':'原话目标'}],
 'group_by':['period'],'comparisons':[{'operation':'subtract|compare','metric_operation':'sum',
 'metric_field':'amount_cents','left_period':[2026,10],'right_period':[2026,9],'quote':'当前比较要求'}]}],
 'unresolved':[]}}


def _validate_context_transition(value):
    if type(value) is not str or value not in {'continue','pending_to_read'}:
        raise BusinessRequestError('读取上下文过渡参数无效。','INVALID_ARGUMENTS')



def native_pending_context(pending, *, actor=None, book=None):
    """Read-only, source-only view of an existing runtime native candidate.

    This is not a bound read source, a restored draft, or another state owner.
    Invalid old state contributes no business values to the semantic input.
    """
    if pending is None or type(actor) is not str or not actor or book is None:
        return None
    try:
        from .business_sources import recover_candidate
        from .invoice_action import public_state
        state=recover_candidate(pending,actor=actor,book=Path(book).resolve())
        public=public_state(state)
        return {'status':'unsubmitted_business_context',
                'source':{'kind':'native_user_request','quote':state['source_request']},
                'known':public['known'],'missing_fields':public['missing_fields']}
    except (ValueError,TypeError,PermissionError,OSError,sqlite3.Error):
        return None

def messages(request,current_catalog,*,trusted_scope=None,previous_request=None,context_transition='continue',
             native_pending=None,actor=None,book=None):
    _validate_context_transition(context_transition)
    scope=trusted_scope or {}
    native=None
    if native_pending is not None:
        native=native_pending_context(native_pending,actor=actor,book=book)
        # The reserved view is derived here, never accepted from an old payload.
        scope={k:v for k,v in scope.items() if k!='native_invoice_candidate'}
        if native is not None:scope['native_invoice_candidate']=native
    output = [{'role':'system','content':
        '先独立解释当前要求，不生成SQL、不调用工具，不看拟执行方案。仅JSON。'
        'read顶层仅kind、targets、unresolved，禁止额外type等标签；unresolved仅字符串列表，无未决项用[]，不能用对象列表。'
        'seller.value在ambiguous时也必须是当前原话简称字符串，不传候选列表；候选由Runtime目录生成。'
        '按业务对象分别列target，发票销售方/用途不能移到银行。公司和账期不可从目录默认补。'
        '先保留用户全部筛选、指标、分组、比较和未决项。共享简称不明则seller.mode=ambiguous；'
        '只有明确名称包含范围才set，单家用single；未要销售方筛选用none，银行不传seller。'
        'none也须非空target-local原话quote，可引用本目标统计/明细要求，value为空串；不可造出用户没说的“无筛选”。'
        '银行金额收入与支出分算；sum(amount_cents)须单方向过滤或按direction分组，不能混为总额。'
        '每个quote必须是当前原话连续片段，数值和关系由你解释但不是程序已证明。'
        '完整字段约定见business_definition.protocol；IN用列表，LIKE文本片段须有原话，is_blank的value用空串而非null。'
        'company_source/period_source可明确context，只有已给唯一可信scope才允许继承。'
        '若可信全年已规范trusted_scope.periods为12个月，列出这12个月并用period_source=context，不将全年原话冒作逐月字面。'
        '有效前文是不可变读取要求，不是历史金额；延续问题时不可删掉前文销售方、用途等筛选。'
        'seller/filter/metric可加source={kind:context,key:前目标ID.seller或前目标ID.filters.0或前目标ID.metrics.0}，'
        '字段和值须与有效前文一致；quote可以留空，由程序取原来源。目标可传previous_target_id。'
        '默认relation=update保留旧筛选；用户明确新查询或替换要求时可relation=replace，但须relation_quote当前原话并指明previous_target_id；不清则clarify。'
        '问候或一般知识可直接{"kind":"general","text":"回答"}；修改/管理走{"kind":"legacy"}，'
        '该route不授予业务读取或写入许可。业务对象或目标不清时用read+unresolved，不能擅自删目标。'},
        {'role':'user','content':__import__('json').dumps({'request':request,'read_catalog':current_catalog,
            'trusted_scope':scope,'previous_requirement':previous_request.metadata() if previous_request else None,
            'business_definition':DEFINITION},ensure_ascii=False)}]
    if native_pending is not None:
        if native is None:
            output[0]['content']+=('旧办理上下文不可核实，不据其补范围，续办需重新明确。'
                '当前新读取仍按当前原话与授权目录判断，不因无效旧状态伪造来源。')
        else:
            output[0]['content']+=('当前有原运行时持有的尚未提交单票业务上下文，见trusted_scope.native_invoice_candidate。'
                '其中source是原用户来源、known是已给业务槽、missing_fields是待补项，不是当前读取范围或权限。'
                '仅帮助判断当前要求：新查询输出read，按当前原话和有效读取来源独立建立要求，'
                '旧票号和旧填写内容不得自动变成新查询的目标或筛选；'
                '继续或更正原事项输出legacy，回到原协调器重核来源与实际对象；一般对话仍可general。'
                '此输入本身不暂停、不提交、不批准事项，不创建草稿；不要新增输出字段或另一套intent，仍仅用原route协议。')
    if context_transition=='pending_to_read':
        output[0]['content']+=('当前由运行时从暂停办理转入新的独立读取要求。'
            '有效前文仅供用户明确指代时按来源引用；旧单张发票范围、销售方及用途等筛选不能自动保留。'
            '仅根据当前原话和明确有效引用重新解释全部读取对象、范围、条件与指标；缺来源时保留未决。'
            '不要从旧intent目标、失败回复、SQL或工具提案补出要求。'
            '这是运行时边界；输出JSON不得添加context_transition或其他协议外字段。')
    return output



_SCHEMA_ERROR_GUIDANCE = {
    'invalid_structure':'独立要求JSON未满足有限字段或类型约定。',
    'top_level':'read顶层字段不符合约定。',
    'unresolved':'unresolved类型不符合约定。',
    'seller_value':'seller.value类型不符合约定。',
}


def schema_restatement_messages(original_context, *, error_code='invalid_structure'):
    """Pure prompt construction; scheduler/one-attempt allowance stay with Agent.

    Accept only the original independent input and a finite static error code.
    There is no failed-reply, SQL, tool-proposal or execution-result parameter.
    """
    if type(error_code) is not str or error_code not in _SCHEMA_ERROR_GUIDANCE:
        raise ValueError('结构重述只能使用静态错误码')
    if (type(original_context) not in (list,tuple) or len(original_context)!=2
            or any(type(m) is not dict or set(m)!={'role','content'}
                   or type(m['content']) is not str for m in original_context)
            or [m['role'] for m in original_context]!=['system','user']):
        raise ValueError('结构重述仅接收原独立要求的两条输入消息')
    payload=load_review(original_context[1]['content'])
    if (type(payload) is not dict or set(payload)!={'request','read_catalog','trusted_scope',
                                                  'previous_requirement','business_definition'}):
        raise ValueError('结构重述输入不是原独立要求上下文')
    return [dict(m) for m in original_context]+[{'role':'system','content':
        '仅做一次独立要求的结构重述，不调用工具、不生成SQL、不输出业务结果。'
        +_SCHEMA_ERROR_GUIDANCE[error_code]+
        '只根据前述原用户要求、有效前文和授权目录重新输出JSON；不引用失败回复或工具提案。'
        '若kind为read，顶层仅kind/targets/unresolved，禁止type等额外键；targets为对象列表。'
        'unresolved必须为字符串列表list[str]，无未决项用[]，不能用list[dict]。'
        'seller.value必须是字符串；ambiguous也使用当前quote中的原话简称，不填候选列表。'
        '保留所有条件及未决项；语义不明时保留unresolved，不能为结构合法擅自补出来源或猜单家。'
        '其他字段、当前quote、权限和有限协议仍完全遵循原business_definition.protocol。'}]

def _source(quote,request,slot):
    if type(quote) is not str or not quote or len(quote)>4000 or quote not in request:
        raise BusinessRequestError('当前要求缺少可核对原话，请重新明确。',slot=slot)
    return Source('current',quote)


def _pair(value):
    if (type(value) is not list or len(value)!=2 or any(type(v) is not int for v in value)):
        raise BusinessRequestError('账期必须为完整年月。')
    try:date(value[0],value[1],1)
    except ValueError:raise BusinessRequestError('账期不合法。') from None
    return tuple(value)


def _scalar(value):
    if type(value) in (str,int,bool):return value
    if type(value) is list and 1<=len(value)<=100 and all(type(v) in (str,int,bool) for v in value):
        return tuple(value)
    raise BusinessRequestError('筛选值不是受控有限字面值。')


def bind(content,*,actor,book,turn_id,request,revision=1,trusted_scope=None,previous_request=None,
         context_transition='continue'):
    _validate_context_transition(context_transition)
    try:raw=load_review(content) if isinstance(content,str) else content
    except (ValueError,TypeError,RecursionError):
        raise BusinessRequestError('读取要求JSON结构无效或字段重复。','INVALID_ARGUMENTS') from None
    if type(raw) is not dict or raw.get('kind')!='read' or set(raw)-{'kind','targets','unresolved'}:
        raise BusinessRequestError('当前读取要求结构不完整。','INVALID_ARGUMENTS')
    entries=raw.get('targets');unresolved=raw.get('unresolved',[])
    if (type(entries) is not list or not 1<=len(entries)<=12 or type(unresolved) is not list
            or len(unresolved)>24 or any(type(s) is not str or not s or len(s)>200 for s in unresolved)):
        raise BusinessRequestError('须明确有限的业务对象和未决项。','INVALID_ARGUMENTS')
    frame=read_catalog(book,actor);byid={r['company_id']:r for r in frame['companies']}
    previous=previous_request
    if previous is not None:
        if (not isinstance(previous,BusinessRequest) or previous.actor!=actor
                or previous.workbook!=str(Path(book).resolve())
                or digest(previous.current_source.quote)!=previous.request_hash):
            raise BusinessRequestError('有效前文不属于当前身份或账簿。','DENIED')
        previous_ids=tuple(sorted({c for t in previous.targets for c in t.company_ids}))
        if digest(read_catalog(book,actor,company_ids=previous_ids))!=previous.catalog_hash:
            raise BusinessRequestError('前文目录来源已经变化，请重新明确。','SCOPE_MISMATCH')
    def inherited(body, expected_type):
        source=body.get('source')
        if source is None:return None
        if type(source) is not dict or set(source)!={'kind','key'} or source['kind']!='context' or previous is None:
            raise BusinessRequestError('没有可继承的可信读取要求。')
        key=source['key']
        if type(key) is not str:raise BusinessRequestError('前文来源引用无效。')
        parts=key.split('.')
        target=next((t for t in previous.targets if t.target_id==parts[0]),None)
        if target is None:raise BusinessRequestError('前文目标不存在。')
        value=None
        if len(parts)==2 and parts[1]=='seller':value=target.seller
        elif len(parts)==3 and parts[1] in {'filters','metrics'} and parts[2].isdigit():
            values=getattr(target,parts[1]);index=int(parts[2])
            if index<len(values):value=values[index]
        if not isinstance(value,expected_type):raise BusinessRequestError('前文引用类型或位置不一致。')
        return value,Source('context',value.source.quote,f'{previous.revision}/{previous.request_hash}/{key}')
    trusted=trusted_scope or {};targets=[]
    for item in entries:
        allowed={'target_id','object','company_ids','company_quote','company_source','periods','period_quote','period_source',
                 'seller','filters','metrics','group_by','comparisons','previous_target_id','relation','relation_quote'}
        if type(item) is not dict or set(item)-allowed:
            raise BusinessRequestError('读取目标含未知字段。','INVALID_ARGUMENTS')
        target_id,obj=item.get('target_id'),item.get('object')
        if type(target_id) is not str or not target_id or len(target_id)>100 or obj not in {'invoices','bank_transactions'}:
            raise BusinessRequestError('读取目标标识或业务对象无效。','INVALID_ARGUMENTS')
        relation=item.get('relation','update')
        if type(relation) is not str or relation not in {'update','replace','clarify'}:
            raise BusinessRequestError('读取要求修订关系无效。','INVALID_ARGUMENTS')
        relation_source=None
        if 'relation' in item or 'relation_quote' in item:
            relation_source=_source(item.get('relation_quote'),request,'relation')
        previous_id=item.get('previous_target_id')
        if previous_id is not None and (type(previous_id) is not str or not previous_id):
            raise BusinessRequestError('被修订读取目标无效。','INVALID_ARGUMENTS')
        if relation=='replace':
            if previous is None or previous_id is None or not any(t.target_id==previous_id for t in previous.targets):
                raise BusinessRequestError('替换必须引用当前有效前文中的实际读取目标。','SCOPE_MISMATCH')
            relation_source=Source('current',relation_source.quote,
                f'{previous.revision}/{previous.request_hash}/{previous_id}')
        if relation=='clarify':unresolved.append(target_id+'.relation')
        ids=item.get('company_ids',[])
        if type(ids) is not list or len(ids)>8 or any(type(c) is not str for c in ids):
            raise BusinessRequestError('目标企业结构无效。','INVALID_ARGUMENTS')
        if any(c not in byid for c in ids):raise BusinessRequestError('当前账号没有目标企业读取权限。','DENIED')
        if not ids:unresolved.append(target_id+'.company_id')
        if len(set(ids))!=len(ids):raise BusinessRequestError('企业目标重复。','INVALID_ARGUMENTS')
        company_context=item.get('company_source','current')=='context'
        company_source=(Source('unresolved','','company_id') if not ids else
            Source('context','', 'scope.company_id') if company_context else _source(item.get('company_quote'),request,'company_id'))
        if not ids:pass
        elif company_context:
            if len(trusted.get('company_id',()))!=1 or tuple(ids)!=tuple(trusted['company_id']):
                raise BusinessRequestError('没有唯一可信企业上下文。')
        else:
            quote=_source(item.get('company_quote'),request,'company_id').quote
            found={m['company_id'] for m in registered_company_mentions(quote,frame['companies'])}
            if found!=set(ids):raise BusinessRequestError('企业名称与当前登记对象不一致。','SCOPE_MISMATCH')
        pairs_raw=item.get('periods',[])
        if type(pairs_raw) is not list or len(pairs_raw)>24:
            raise BusinessRequestError('账期结构无效。','INVALID_ARGUMENTS')
        if not pairs_raw:unresolved.append(target_id+'.periods')
        pairs=tuple(_pair(v) for v in pairs_raw)
        if len(set(pairs))!=len(pairs):raise BusinessRequestError('目标账期重复。','INVALID_ARGUMENTS')
        period_context=item.get('period_source','current')=='context'
        period_source=(Source('unresolved','','periods') if not pairs else
            Source('context','', 'scope.periods') if period_context else _source(item.get('period_quote'),request,'periods'))
        if not pairs:pass
        elif period_context:
            if set(pairs)!=set(map(tuple,trusted.get('periods',()))):
                raise BusinessRequestError('账期不能由目录或历史数值自行补出。')
        else:
            period_quote=_source(item.get('period_quote'),request,'periods').quote
            literal_period=request_scope(period_quote)
            inherited_years=set(trusted.get('year',())) or {y for y,m in trusted.get('periods',())}
            if (not literal_period.get('year') and literal_period.get('month') and len(inherited_years)==1):
                wanted={(next(iter(inherited_years)),m) for m in literal_period['month']}
                if wanted!=set(pairs):raise BusinessRequestError('本月更正与唯一可信年份不一致。','SCOPE_MISMATCH')
                period_source=Source('context',period_quote,'scope.year+current.month')
            elif literal_period.get('year'):
                # Fully stated years/months are source facts, not existence claims.
                # Mask registered object identifiers using the shared source helper.
                literal,_,_=amendment_sources(period_quote,None,actor=actor,book=book)
                wanted=set(map(tuple,literal.get('periods',())))
                if not wanted and len(literal.get('year',()))==1:
                    wanted={(literal['year'][0],m) for m in literal.get('month',())}
                if wanted!=set(pairs):
                    raise BusinessRequestError('当前完整年月与原话来源不一致。','SCOPE_MISMATCH')
            # Only abbreviated centuries still need unique catalog validation.
            elif not company_context and len(ids)==1:
                mention=next(m for m in registered_company_mentions(item['company_quote'],frame['companies']) if m['company_id']==ids[0])
                try:
                    bind_read_scope({'company_id':ids[0],'company_quote':mention['quote'],'period_quote':period_quote,
                        'periods':[{'year':y,'month':m} for y,m in pairs]},request,frame,
                        trusted_scope={'company_ids':tuple(ids),'periods':tuple(map(tuple,trusted.get('periods',())))})
                except (ValueError,ReadBindingError) as error:raise BusinessRequestError(str(error),getattr(error,'status','AMBIGUOUS')) from None
            else:
                literal,_,_=amendment_sources(period_quote,None,actor=actor,book=book)
                wanted=set(map(tuple,literal.get('periods',())))
                if not wanted and len(literal.get('year',()))==1:
                    wanted={(literal['year'][0],m) for m in literal.get('month',())}
                if wanted!=set(pairs):raise BusinessRequestError('当前日期来源尚不能唯一核实，请明确年月。')
        anchor_values={key:list(values) for key,values in trusted.items() if isinstance(values,(tuple,list))}
        if anchor_values.get('periods'):
            anchor_values.setdefault('year',sorted({y for y,m in anchor_values['periods']}))
            anchor_values.setdefault('month',sorted({m for y,m in anchor_values['periods']}))
        anchor=ScopeProof(actor,anchor_values,dict.fromkeys(anchor_values,'controlled_read_scope'))
        for company in ids:
            company_origin=({'kind':'anchor'} if company_context else {'kind':'current','text':next(
                mention['quote'] for mention in registered_company_mentions(item['company_quote'],frame['companies'])
                if mention['company_id']==company)})
            period_origin={'kind':'anchor'} if period_context else {'kind':'current','text':period_source.quote}
            for year,month in pairs:
                try:
                    validate_read_intent({'action':'read','target':{'company_id':company,'year':year,'month':month},
                        'sources':{'company_id':company_origin,'year':period_origin,'month':period_origin}},
                        actor=actor,book=book,request=request,turn_id=turn_id,anchor=anchor)
                except IntentContractError as error:
                    raise BusinessRequestError(str(error),error.status,slot=error.slot) from None
        for key in ('filters','metrics','comparisons'):
            if type(item.get(key,[])) is not list or len(item.get(key,[]))>64:
                raise BusinessRequestError('读取条件或目标过多，请缩小范围。','INVALID_ARGUMENTS')
        seller=None
        if obj=='bank_transactions' and item.get('seller') is not None:
            raise BusinessRequestError('发票销售方条件不能用于银行流水。','SCOPE_MISMATCH')
        if obj=='invoices':
            body=item.get('seller')
            if (type(body) is not dict or not {'mode','quote','value'}<=set(body)
                    or set(body)-{'mode','quote','value','source'} or body.get('mode') not in {'single','set','ambiguous','none'}):
                raise BusinessRequestError('须独立明确销售方关系，包括无销售方筛选。')
            inherited_seller=inherited(body,SellerRequirement)
            source=inherited_seller[1] if inherited_seller else _source(body['quote'],request,'seller')
            value=body['value'];mode=body['mode']
            if inherited_seller and (mode,value)!=(inherited_seller[0].mode,inherited_seller[0].value):
                raise BusinessRequestError('继承销售方不得同时改写其关系或值。','SCOPE_MISMATCH')
            if type(value) is not str or len(value)>2000:raise BusinessRequestError('销售方值无效。','INVALID_ARGUMENTS')
            names=tuple(sorted({n for c in ids for n in byid[c]['seller_names'] if isinstance(n,str) and n}))
            if mode!='none' and any(not byid[c]['seller_catalog_complete'] for c in ids):
                raise BusinessRequestError('完整销售方目录超过能力边界，不能猜测唯一对象。','SQL_SCOPE_LIMIT')
            full=full_mentions(source.quote,names)
            if mode=='none':
                if value or full:raise BusinessRequestError('不能丢弃当前明确销售方。','SCOPE_MISMATCH')
                chosen=()
            else:
                if not value or value not in source.quote:raise BusinessRequestError('销售方值缺少当前原话来源。')
                chosen=tuple(n for n in names if value in n)
                if mode=='single' and len(full)==1 and value in next(iter(full)):
                    chosen=tuple(sorted(full))
                elif full and set(chosen)!=full:
                    mode='ambiguous'
                if mode=='single' and len(chosen)!=1:mode='ambiguous'
                if mode=='set' and source.quote.strip()==value.strip():mode='ambiguous'
                if not chosen:mode='ambiguous'
                if mode=='ambiguous':unresolved.append(target_id+'.seller')
            seller=SellerRequirement(mode,chosen,value,source)
        fields=({'invoice_no','invoice_date','item_name','purpose','remark','amount_cents'} if obj=='invoices'
                else {'transaction_no','transaction_date','direction','counterparty_name','remark','amount_cents'})
        filters=[]
        for f in item.get('filters',[]):
            if (type(f) is not dict or not {'field','operator','value','quote'}<=set(f)
                    or set(f)-{'field','operator','value','quote','source'} or f['field'] not in fields
                    or f['operator'] not in {'=','!=','>','>=','<','<=','LIKE','IN','is_blank'}):
                raise BusinessRequestError('筛选条件超出受控结构。','INVALID_ARGUMENTS')
            inherited_filter=inherited(f,ReadFilter)
            source=inherited_filter[1] if inherited_filter else _source(f['quote'],request,'filter');value=_scalar(f['value'])
            if inherited_filter and (f['field'],f['operator'],value)!=(inherited_filter[0].field,inherited_filter[0].operator,inherited_filter[0].value):
                raise BusinessRequestError('继承筛选不得更改其字段、关系或值。','SCOPE_MISMATCH')
            if obj=='bank_transactions' and f['field']=='direction':
                directions=value if isinstance(value,tuple) else (value,)
                if (f['operator'] not in {'=','IN'} or any(v not in {'收入','支出'} for v in directions)
                        or f['operator']=='=' and isinstance(value,tuple)
                        or f['operator']=='IN' and not isinstance(value,tuple)):
                    raise BusinessRequestError('银行方向须归一为收入/支出有限枚举。','INVALID_ARGUMENTS')
                if not inherited_filter:
                    source=Source('current',source.quote,'model_interpretation:bank_direction')
            else:
                literals=value if isinstance(value,tuple) else (value,)
                for literal in literals:
                    if type(literal) is not str or literal in source.quote:continue
                    if f['operator']=='LIKE':
                        pieces=[part for part in literal.replace('%','\0').replace('_','\0').split('\0') if part]
                        if pieces and all(part in source.quote for part in pieces):continue
                    raise BusinessRequestError('筛选文字缺少当前原话。','SCOPE_MISMATCH')
            filters.append(ReadFilter(f['field'],f['operator'],value,source))
        metrics=[]
        for m in item.get('metrics',[]):
            if (type(m) is not dict or not {'operation','field','quote'}<=set(m)
                    or set(m)-{'operation','field','quote','source'} or m['operation'] not in {'sum','count','details','min','max'}
                    or m['field'] not in ({'amount_cents','*'}|fields)):
                raise BusinessRequestError('查询指标超出受控结构。','INVALID_ARGUMENTS')
            inherited_metric=inherited(m,ReadMetric)
            if inherited_metric and (m['operation'],m['field'])!=(inherited_metric[0].operation,inherited_metric[0].field):
                raise BusinessRequestError('继承指标不得更改含义。','SCOPE_MISMATCH')
            metrics.append(ReadMetric(m['operation'],m['field'],inherited_metric[1] if inherited_metric else _source(m['quote'],request,'metric')))
        if not metrics:unresolved.append(target_id+'.metrics')
        group=item.get('group_by',[])
        if type(group) is not list or any(type(g) is not str for g in group) or len(set(group))!=len(group):
            raise BusinessRequestError('分组目标无效。','INVALID_ARGUMENTS')
        if any(g not in GROUP_FIELDS[obj] for g in group):
            raise BusinessRequestError('分组字段不属于当前业务对象或不是实际字段。','SCOPE_MISMATCH')
        if obj=='bank_transactions' and any(m.operation=='sum' and m.field=='amount_cents' for m in metrics):
            single_direction=any(f.field=='direction' and f.operator in {'=','IN'}
                and len(set(f.value if isinstance(f.value,tuple) else (f.value,)))==1 for f in filters)
            if not single_direction and 'direction' not in group:
                unresolved.append(target_id+'.bank_direction')
        comparisons=[]
        for c in item.get('comparisons',[]):
            if (type(c) is not dict or set(c)!={'operation','metric_operation','metric_field','left_period','right_period','quote'}
                    or c['operation'] not in {'subtract','compare'}
                    or (c['metric_operation'],c['metric_field']) not in {(m.operation,m.field) for m in metrics}):
                raise BusinessRequestError('比较目标须对应实际查询指标。')
            left,right=_pair(c['left_period']),_pair(c['right_period'])
            if left not in pairs or right not in pairs:raise BusinessRequestError('比较账期超出当前读取目标。','SCOPE_MISMATCH')
            comparisons.append(ReadComparison(c['operation'],c['metric_operation'],c['metric_field'],left,right,
                                              _source(c['quote'],request,'comparison')))
        old=None
        if previous:
            old_id=item.get('previous_target_id')
            candidates=[t for t in previous.targets if
                        (relation=='replace' and t.target_id==old_id) or
                        (relation!='replace' and t.object==obj and t.company_ids==tuple(ids)
                         and (old_id is None or t.target_id==old_id))]
            if len(candidates)==1:old=candidates[0]
            elif old_id is not None:raise BusinessRequestError('前文对象或企业不一致。','SCOPE_MISMATCH')
        if old and relation!='replace' and context_transition!='pending_to_read':
            if old.seller and old.seller.mode!='none' and seller and seller.mode=='none':
                unresolved.append(target_id+'.previous_seller_not_replaced')
            old_filters={(f.field,f.operator,f.value) for f in old.filters}
            new_filters={(f.field,f.operator,f.value) for f in filters}
            if old_filters-new_filters:
                unresolved.append(target_id+'.previous_filters_not_replaced')
        targets.append(ReadRequirement(target_id,obj,tuple(ids),pairs,seller,tuple(filters),tuple(metrics),
            tuple(group),tuple(comparisons),company_source,period_source,relation,relation_source,previous_id))
    if len({t.target_id for t in targets})!=len(targets):raise BusinessRequestError('读取目标标识重复。','INVALID_ARGUMENTS')
    selected=tuple(sorted({c for t in targets for c in t.company_ids}))
    req=BusinessRequest(actor,str(Path(book).resolve()),turn_id,revision,Source('current',request),digest(request),
                        digest(read_catalog(book,actor,company_ids=selected)),tuple(targets),tuple(dict.fromkeys(unresolved)),
                        context_transition,previous.revision if previous else None,previous.request_hash if previous else None)
    return req
