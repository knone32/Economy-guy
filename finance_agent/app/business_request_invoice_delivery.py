"""Adapters for three finite, independently declared invoice views; no owner."""
from copy import deepcopy
from datetime import date
import json

ADAPTERS=frozenset({'rule_missing','directory','reference_details'})

def _error(message,status='TOOL_CAPABILITY_MISMATCH'):
    from .business_request_delivery import RequestDeliveryError
    raise RequestDeliveryError(message,status)

def _kind(target):
    return ('rule_missing' if target.purpose_check else 'directory' if target.directory else
            'reference_details' if target.reference else None)

def preflight(request,name,args,actor,book):
    from .business_request_delivery import _companies,_periods
    from .tool_contracts import TOOL_SPECS
    adapter=TOOL_SPECS[name].result_adapter;matched=[]
    for target in request.targets:
        if target.object!='invoices' or _kind(target)!=adapter:continue
        if adapter=='reference_details':
            ref=target.reference
            if name=='resolve_invoice_reference':
                if (ref.kind!='display_ordinal' or args.get('company_id')!=ref.company_id
                        or args.get('ordinal')!=ref.ordinal or args.get('anchor_id','') not in {'',ref.anchor_id}):continue
            elif args.get('source')!=ref.kind.removeprefix('recent_') or not ref.kind.startswith('recent_'):continue
        else:
            if (not _companies(args) or not _periods(args)
                    or not _companies(args)<=set(target.company_ids) or not _periods(args)<=set(target.periods)):continue
            if target.seller and target.seller.mode!='none' or target.filters:
                _error('此专用入口不能落实附加销售方或字段筛选。')
            if adapter=='rule_missing':
                expected=target.purpose_check.reference_business_date
                if args.get('rule_business_date')!=expected:
                    _error('参考规则日期与独立要求不一致；不能用参考日期替换目标月。','SCOPE_MISMATCH')
            else:
                view=target.directory
                if (args.get('sort_by','date')!=view.sort_by or args.get('sort_order','asc')!=view.sort_order
                        or view.coverage=='page' and args.get('page')!=view.page):
                    _error('目录页或排序不属于本轮独立要求。','SCOPE_MISMATCH')
        matched.append(target)
    if not matched:_error('工具不能以自身名称建立规则、目录或引用要求。')
    return matched

def _proof(target,scope,metric,**extra):
    return {'target_id':target.target_id,'operation':metric.operation,'field':metric.field,
            'scope':deepcopy(scope),'dimensions':{},'conditions':[],'all_groups':True,**extra}

def accept(request,name,result,actor,book):
    from .business_request_delivery import annotate,_targets
    from .tool_contracts import TOOL_SPECS
    data=result.get('data');evidence=result.get('evidence') or {};scope=evidence.get('scope') or {}
    adapter=TOOL_SPECS[name].result_adapter
    if evidence.get('source')!='current_sqlite':_error('专用结果缺少当前授权SQLite证据。','SQL_EVIDENCE_UNSUPPORTED')
    targets=[t for t in _targets(request,'invoices',scope) if _kind(t)==adapter]
    if not targets:_error('结果没有对应的本轮独立视图要求。','SCOPE_MISMATCH')
    proofs=[];scalar_facts=[];ids=[]
    for target in targets:
        if adapter=='rule_missing':
            from .rules import RuleDecision,missing_required_purpose,resolve_rule,RuleError
            from .stage2_schema import open_existing
            from contextlib import closing
            from dataclasses import asdict
            from .fact_arithmetic import cents
            if type(data) is not dict:_error('缺项检查结果结构不足。','SQL_EVIDENCE_UNSUPPORTED')
            rows=data.get('missing_invoices');rule=data.get('rule');count=data.get('count')
            try:decision=RuleDecision(**rule)
            except (TypeError,ValueError):_error('缺少实际RuleDecision。','SQL_EVIDENCE_UNSUPPORTED')
            if (not isinstance(decision.rule_id,str) or not decision.rule_id or not isinstance(decision.version,str)
                    or type(decision.params) is not dict or decision.params.get('mode') not in {'all','threshold'}
                    or decision.params.get('mode')=='threshold' and
                    (type(decision.params.get('threshold_cents')) is not int or decision.params['threshold_cents']<0)):
                _error('RuleDecision执行参数不可核实。','SQL_EVIDENCE_UNSUPPORTED')
            expected=target.purpose_check.reference_business_date
            default=date(scope['year'],scope['month'],1).isoformat()
            try:
                with closing(open_existing(book,readonly=True)) as db:
                    db.execute('BEGIN')
                    actual_rule=asdict(resolve_rule(db,actor,scope['company_id'],'purpose',expected or default))
            except RuleError:
                _error('当前适用用途RuleDecision无法重新核实。','SQL_EVIDENCE_UNSUPPORTED')
            if (rule!=evidence.get('rule') or decision.rule_type!='purpose'
                    or rule!=actual_rule
                    or decision.company_scope not in {'*',scope['company_id']}
                    or data.get('rule_business_date')!=(expected or default)
                    or data.get('reference_rule_screening')!=(expected is not None)
                    or evidence.get('reference_rule_screening')!=data.get('reference_rule_screening')
                    or data.get('target_year')!=scope['year'] or data.get('target_month')!=scope['month']):
                _error('实际规则版本、参考日期或目标期间不匹配。','SCOPE_MISMATCH')
            if (type(rows) is not list or type(count) is not int or count<0 or count!=len(rows)
                    or data.get('truncated') or len({(r.get('company_id'),r.get('invoice_no')) for r in rows})!=len(rows)):
                _error('缺项集合不完整或重复，不能交付统计。','SQL_EVIDENCE_UNSUPPORTED')
            for row in rows:
                if (row.get('company_id')!=scope['company_id'] or not str(row.get('invoice_date','')).startswith(f"{scope['year']:04d}-{scope['month']:02d}")
                        or cents(row.get('amount')) is None or not missing_required_purpose(decision.params,row)):
                    _error('缺项行不符合实际RuleDecision或目标范围。','SCOPE_MISMATCH')
            basis=json.dumps({'criterion':'required_missing','rule':rule,'rule_business_date':data['rule_business_date'],
                'reference_rule_screening':data['reference_rule_screening']},sort_keys=True,ensure_ascii=False)
            amount=None
            parents=[row['invoice_no'] for row in rows]
            for derived in evidence.get('derived',[]):
                if (derived.get('metric')=='missing_purpose_amount_total' and derived.get('coverage')=='complete_missing_set'
                        and derived.get('parent_invoice_nos')==parents and type(derived.get('amount_cents')) is int
                        and derived['amount_cents']==sum(cents(row['amount']) for row in rows)):
                    amount=derived['amount_cents']
            for metric in target.metrics:
                if metric.operation=='details':proofs.append(_proof(target,scope,metric,view='required_missing'))
                elif metric.operation=='count' and metric.field=='*':
                    proofs.append(_proof(target,scope,metric,basis=basis));scalar_facts.append({'operation':'count','field':'*','value':count,'unit':'count','basis':basis})
                elif metric.operation=='sum' and metric.field=='amount_cents' and amount is not None:
                    proofs.append(_proof(target,scope,metric,basis=basis));scalar_facts.append({'operation':'sum','field':'amount_cents','value':amount,'unit':'cents','basis':basis})
        elif adapter=='directory':
            if type(data) is not dict:_error('目录元数据缺失。','SQL_EVIDENCE_UNSUPPORTED')
            view=target.directory;rows=data.get('rows');total=data.get('total');page=data.get('page');size=data.get('page_size')
            if (any(type(v) is not int for v in (total,page,size)) or total<0 or page<1 or size<1
                    or type(rows) is not list or len(rows)>size or len(rows)!=max(0,min(size,total-(page-1)*size))
                    or data.get('sort_by')!=view.sort_by or data.get('sort_order')!=view.sort_order
                    or view.coverage=='page' and page!=view.page):
                _error('目录页、排序或计数证据不一致。','SCOPE_MISMATCH')
            keys=[]
            for row in rows:
                if (row.get('company_id')!=scope['company_id'] or type(row.get('invoice_no')) is not str
                        or type(row.get('invoice_date')) is not str or type(row.get('amount')) is not str
                        or type(row.get('has_purpose')) is not bool):_error('目录行结构无效。','SQL_EVIDENCE_UNSUPPORTED')
                day=date.fromisoformat(row['invoice_date'])
                if (day.year,day.month) not in target.periods:_error('目录行账期超出当前要求。','SCOPE_MISMATCH')
                keys.append((row['company_id'],row['invoice_no']))
            if len(set(keys))!=len(keys):_error('目录身份重复。','SQL_EVIDENCE_UNSUPPORTED')
            complete=view.coverage=='page' or page==1 and total<=size and len(rows)==total
            if complete:proofs.extend(_proof(target,scope,m,view='invoice_directory',page=page,total=total) for m in target.metrics)
        else:
            ref=target.reference
            if (type(data) is not dict or (data.get('company_id'),data.get('invoice_no'))!=(ref.company_id,ref.invoice_no)
                    or (scope.get('year'),scope.get('month'))!=(ref.year,ref.month)):
                _error('实际引用对象与原可信来源不一致。','SCOPE_MISMATCH')
            if ref.kind=='display_ordinal':
                actual=evidence.get('reference') or {}
                if any(actual.get(k)!=v for k,v in (('anchor_id',ref.anchor_id),('display_id',ref.display_id),('ordinal',ref.ordinal))):
                    _error('结果没有匹配的真实展示锚点。','SCOPE_MISMATCH')
            elif (evidence.get('reference_source')!=ref.kind.removeprefix('recent_')
                    or ref.kind=='recent_modified' and (evidence.get('historical_commit') or {}).get('request_id')!=ref.request_id):
                _error('近期来源或提交审计不匹配。','SCOPE_MISMATCH')
            from .seller_read_scope import _matching
            from .business_request_delivery import _proof_filter
            from .fact_arithmetic import cents
            if target.seller and target.seller.mode!='none' and data.get('seller_name') not in target.seller.names:
                _error('引用不满足当前销售方条件。','SCOPE_MISMATCH')
            for f in target.filters:
                value=cents(data.get('amount')) if f.field=='amount_cents' else data.get(f.field)
                if not _matching([value],[_proof_filter(f)]):
                    _error('引用不满足当前字段条件。','SCOPE_MISMATCH')
            proofs.extend(_proof(target,scope,m,view='trusted_reference') for m in target.metrics)
        ids.append(target.target_id)
    accepted=annotate(result,request,ids)
    accepted['evidence']['business_request'].update(measures=proofs,scalar_facts=scalar_facts,
        view_adapter=adapter,completeness=('partial' if not proofs else 'proved_metrics_only'))
    return accepted
