"""Pure strict JSON and attributed-measure checks; no request state owner."""
import hashlib
import json
from .seller_read_scope import SellerReadError


def load_review(content):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:
                raise ValueError('重复JSON字段')
            result[key]=value
        return result
    return json.loads(content,object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('非法JSON常量')))


def digest(value):
    payload = value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,sort_keys=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()



def verify_measure_sources(query, *, decision, directory, names):
    """Every attributed measure carries its own conditional cohort."""
    if query.get('status')!='VERIFIED':
        raise SellerReadError('当前查询形式暂不能提供可核实的统计依据。','SQL_EVIDENCE_UNSUPPORTED',
            evidence={'query_scope_status':query.get('status'),'query_scope_reason':query.get('reason')})
    base=[c for c in query.get('conditions',()) if c.get('field')=='seller_name']
    extras=[[c for c in meta.get('conditions',()) if c.get('field')=='seller_name']
            for meta in query.get('columns',())]
    if decision=='no_seller_requirement':
        if base or any(extras):
            raise SellerReadError('查询或条件统计增加了当前要求没有确认的销售方筛选。','SCOPE_MISMATCH')
    else:
        from .seller_read_scope import _matching
        for extra in extras:
            if extra and _matching(directory,[*base,*extra])!=set(names):
                raise SellerReadError('条件统计的销售方范围缩小或改变了当前要求。','SCOPE_MISMATCH')

