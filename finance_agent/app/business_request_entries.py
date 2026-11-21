"""Finite invoice-view requirements and original-owner reference witnesses.

No candidate, display, approval or execution state is owned here.
"""
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class PurposeCheck:
    criterion: str
    reference_business_date: str | None
    source: object


@dataclass(frozen=True)
class DirectoryRequirement:
    coverage: str
    page: int | None
    sort_by: str
    sort_order: str
    source: object


@dataclass(frozen=True)
class ReferenceRequirement:
    kind: str
    company_id: str
    year: int
    month: int
    invoice_no: str
    ordinal: int | None
    anchor_id: str
    display_id: str
    request_id: str
    source: object


@dataclass(frozen=True)
class ReferenceCandidate:
    kind: str
    company_id: str
    year: int
    month: int
    invoice_no: str
    ordinal: int | None = None
    anchor_id: str = ''
    display_id: str = ''
    request_id: str = ''


@dataclass(frozen=True)
class TrustedReferences:
    actor: str
    workbook: str
    entries: tuple

    def public(self):
        # The model chooses a source, never supplies its target invoice key.
        return [{'kind':r.kind,'ordinal':r.ordinal,'company_id':r.company_id,
                 'periods':[[r.year,r.month]]} for r in self.entries]


def trusted_reference_catalog(*, actor, book, reference_context=None, recent_context=None):
    """Project only existing original reference/recent owners after fresh checks.

    Inputs are runtime-only contexts, never a model argument or transcript JSON.
    The original resolvers remain responsible for target and ACL validation.
    """
    from .references import resolve_reference
    from .queries import get_invoice
    from .stage2_schema import open_existing
    from .updates import inspect_request
    book=Path(book).resolve();entries=[]
    if isinstance(reference_context,dict):
        ordinal=reference_context.get('ordinal');displays=reference_context.get('display_ids')
        if type(ordinal) is int and ordinal>0 and isinstance(displays,(tuple,list)) and displays:
            result=resolve_reference(book,actor,ordinal,reference_context.get('scope'),
                reference_context.get('anchor_id',''),display_ids=displays)
            if result.get('status')=='SUCCESS':
                scope=result['evidence']['scope'];ref=result['evidence']['reference']
                entries.append(ReferenceCandidate('display_ordinal',scope['company_id'],scope['year'],scope['month'],
                    scope['invoice_no'],ordinal,ref['anchor_id'],ref['display_id']))
    if (isinstance(recent_context,dict) and recent_context.get('actor')==actor
            and Path(recent_context.get('workbook','')).resolve()==book):
        for source in ('queried','modified'):
            candidate=recent_context.get('candidates',{}).get(source)
            if not isinstance(candidate,dict):continue
            company,number=candidate.get('company_id'),candidate.get('invoice_no')
            if not isinstance(company,str) or not isinstance(number,str):continue
            request_id=''
            if source=='modified':
                request_id=candidate.get('request_id','')
                if not request_id:continue
                checked=inspect_request(book,actor,request_id)
                if checked.get('status')!='COMMITTED':continue
                audit=checked['data']['historical_commit']
                if (audit.get('company_id'),audit.get('invoice_no'))!=(company,number):continue
                current=checked['data']['current_invoice']
            else:
                with closing(open_existing(book,readonly=True)) as db:
                    db.execute('BEGIN');current=get_invoice(db,actor,company,number)
            if current is None:continue
            day=date.fromisoformat(current['invoice_date'])
            entries.append(ReferenceCandidate('recent_'+source,company,day.year,day.month,number,request_id=request_id))
    return TrustedReferences(actor,str(book),tuple(entries))


def bind_reference(body, *, actor, book, catalog, source):
    from .business_request import BusinessRequestError
    if body is None:return None
    if (type(body) is not dict or set(body)-{'kind','ordinal','quote'}
            or body.get('kind') not in {'display_ordinal','recent_queried','recent_modified'}):
        raise BusinessRequestError('引用要求只能选择既有展示或近期来源，不接受模型提供票号。','INVALID_ARGUMENTS')
    origin=source(body.get('quote'),'reference')
    if (not isinstance(catalog,TrustedReferences) or catalog.actor!=actor
            or catalog.workbook!=str(Path(book).resolve())):
        raise BusinessRequestError('没有同账号同账簿的可信引用来源。','AMBIGUOUS')
    ordinal=body.get('ordinal')
    if body['kind']=='display_ordinal':
        if type(ordinal) is not int or ordinal<1:raise BusinessRequestError('展示序号无效。','INVALID_ARGUMENTS')
    elif ordinal is not None:raise BusinessRequestError('近期引用不接受展示序号。','INVALID_ARGUMENTS')
    entries=[r for r in catalog.entries if r.kind==body['kind'] and r.ordinal==ordinal]
    if len(entries)!=1:raise BusinessRequestError('引用来源尚未唯一或与本轮实际线索不一致。','AMBIGUOUS')
    r=entries[0]
    return ReferenceRequirement(r.kind,r.company_id,r.year,r.month,r.invoice_no,r.ordinal,
        r.anchor_id,r.display_id,r.request_id,origin)


def bind_views(item, *, source):
    from .business_request import BusinessRequestError
    purpose=directory=None
    body=item.get('purpose_check')
    if body is not None:
        if (type(body) is not dict or set(body)-{'criterion','rule_type','reference_business_date','quote'}
                or body.get('criterion')!='required_missing' or body.get('rule_type')!='purpose'):
            raise BusinessRequestError('用途规则检查要求结构无效。','INVALID_ARGUMENTS')
        origin=source(body.get('quote'),'purpose_check');reference=body.get('reference_business_date')
        if reference is not None:
            try:
                day=date.fromisoformat(reference)
                valid=day.isoformat()==reference and (reference in origin.quote
                    or f'{day.year}年{day.month}月{day.day}日' in origin.quote)
            except (TypeError,ValueError):valid=False
            if not valid:raise BusinessRequestError('参考规则日期缺少独立原话来源。','SCOPE_MISMATCH')
        purpose=PurposeCheck('required_missing',reference,origin)
    body=item.get('directory')
    if body is not None:
        if (type(body) is not dict or set(body)-{'coverage','page','sort_by','sort_order','quote'}
                or body.get('coverage') not in {'page','all'} or body.get('sort_by','date') not in {'date','amount','invoice_no'}
                or body.get('sort_order','asc') not in {'asc','desc'}):
            raise BusinessRequestError('发票目录要求结构无效。','INVALID_ARGUMENTS')
        page=body.get('page')
        if ((body['coverage']=='page' and (type(page) is not int or page<1))
                or body['coverage']=='all' and page is not None):
            raise BusinessRequestError('目录须区分指定页与完整目录。','INVALID_ARGUMENTS')
        directory=DirectoryRequirement(body['coverage'],page,body.get('sort_by','date'),body.get('sort_order','asc'),
            source(body.get('quote'),'directory'))
    return purpose,directory
