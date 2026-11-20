"""Validate a model's read-only canonicalization against the current catalog.

No fuzzy names, default centuries, semantic routing, history, or write sources.
The model supplies the relationship; runtime verifies quotes and uniqueness.
"""
from contextlib import closing
import re

from .permissions import check_permission
from .queries import available_periods
from .responses import request_scope
from .stage2_schema import open_existing
from .seller_read_scope import SELLER_SCHEMA, validate_shape as validate_seller_shape


PERIOD_SCHEMA = {'type':'object','properties':{
    'year':{'type':'integer','minimum':1,'maximum':9999},
    'month':{'type':'integer','minimum':1,'maximum':12}},
    'required':['year','month'],'additionalProperties':False}
READ_SCOPE_SCHEMA = {'type':'object','properties':{
    'company_id':{'type':'string','minLength':1,'maxLength':2000},
    'periods':{'type':'array','items':PERIOD_SCHEMA,'minItems':1,'maxItems':24,'uniqueItems':True},
    'company_quote':{'type':'string','minLength':1,'maxLength':2000},
    'period_quote':{'type':'string','minLength':1,'maxLength':2000},
    'seller': SELLER_SCHEMA},
    'required':['company_id','periods','company_quote','period_quote'],'additionalProperties':False}


class ReadBindingError(ValueError):
    def __init__(self,message,status='AMBIGUOUS'):
        super().__init__(message)
        self.status = status


def validate_shape(binding):
    if (type(binding) is not dict or not set(READ_SCOPE_SCHEMA['required']) <= set(binding)
            or set(binding) - set(READ_SCOPE_SCHEMA['properties'])):
        raise ValueError('只读范围候选字段不完整或含多余参数')
    if any(type(binding[key]) is not str or not binding[key].strip() or len(binding[key])>2000
           for key in ('company_id','company_quote','period_quote')):
        raise ValueError('只读范围候选必须提供当前原话和企业编号')
    if 'seller' in binding:
        validate_seller_shape(binding['seller'])
    periods = binding['periods']
    if type(periods) is not list or not 1<=len(periods)<=24:
        raise ValueError('只读范围候选须提供1至24个完整年月')
    for pair in periods:
        if (type(pair) is not dict or set(pair)!={'year','month'}
                or type(pair['year']) is not int or not 1<=pair['year']<=9999
                or type(pair['month']) is not int or not 1<=pair['month']<=12):
            raise ValueError('只读范围候选年月无效')
    if len({(p['year'],p['month']) for p in periods}) != len(periods):
        raise ValueError('只读范围候选年月重复')


def catalog(path,actor):
    """Only current readable entities and periods; no amount or write grant."""
    companies = []
    with closing(open_existing(path,readonly=True)) as db:
        db.execute('BEGIN')
        for row in db.execute('SELECT company_id,name,short_name FROM companies ORDER BY company_id'):
            if check_permission(db,actor,row['company_id'],'read').allowed:
                companies.append({'company_id':row['company_id'],'name':row['name'],'short_name':row['short_name'],
                    'periods':[period for period,_,_ in available_periods(db,actor,row['company_id'])]})
    return {'source':'current_authorized_workbook','read_only':True,'companies':companies,
            'usage':'名称仅可与已登记编号、全称或简称精确绑定；未登记缩写或多个候选须追问。账期用于核验只读归一化，不授予修改许可。'}


def bind(binding,request,current_catalog,*,trusted_scope=None):
    validate_shape(binding)
    if (type(request) is not str or not request
            or any(binding[key] not in request for key in ('company_quote','period_quote'))):
        raise ReadBindingError('只读范围缺少本轮原话来源，请明确企业和完整年月。')
    quote = binding['company_quote']
    matches = [row for row in current_catalog['companies']
               if quote in {row['company_id'],row['name'],row['short_name']}]
    if len(matches)!=1:
        raise ReadBindingError('企业简称未登记或对应多个可读企业，请提供企业编号或可区别的完整名称。')
    company = matches[0]
    if quote == company['company_id'] and re.fullmatch(r'[A-Za-z0-9_-]+',quote) and not re.search(
            r'(?<![A-Za-z0-9_-])'+re.escape(quote)+r'(?![A-Za-z0-9_-])',request):
        raise ReadBindingError('企业编号不是本轮独立的完整标识符，请明确企业。')
    if company['company_id'] != binding['company_id']:
        raise ReadBindingError('企业编号与当前已登记名称不一致。','SCOPE_MISMATCH')
    parsed = request_scope(binding['period_quote'])
    months = set(parsed.get('month',()))
    years = set(parsed.get('year',()))
    short_years = set(map(int,re.findall(r'(?<!\d)(\d{2})\s*年',binding['period_quote'])))
    available = {tuple(map(int,period.split('-'))) for period in company['periods']}
    if short_years:
        if years or len(short_years)!=1 or not months:
            raise ReadBindingError('日期缩写不能唯一对应完整账期，请明确完整年月。')
        suffix = next(iter(short_years))
        years = {year for year,_ in available if year%100==suffix
                 and all((year,month) in available for month in months)}
        if len(years)!=1:
            raise ReadBindingError('两位年份不能在当前账簿中唯一核实，请提供四位年份。')
    elif not years and months and trusted_scope:
        # A redundant optional sidecar must not discard the already validated
        # current year. The catalog alone never supplies this missing year.
        if tuple(trusted_scope.get('company_ids', ())) == (company['company_id'],):
            prior = {tuple(p) for p in trusted_scope.get('periods', ()) if p[1] in months}
            prior_years = {y for y, _ in prior}
            if len(prior_years) == 1 and {m for _, m in prior} == months:
                years = prior_years
    if not years or not months:
        raise ReadBindingError('只读范围尚缺可核对的完整年份或月份。')
    pairs = set(parsed.get('periods',())) if not short_years else set()
    if not pairs:
        if len(years)!=1:
            raise ReadBindingError('多个年份和月份未唯一配对，请明确各账期。')
        pairs = {(next(iter(years)),month) for month in months}
    target = {(p['year'],p['month']) for p in binding['periods']}
    if pairs!=target or not target<=available:
        raise ReadBindingError('候选账期与原话或当前企业账期目录不一致。','SCOPE_MISMATCH')
    values = {'company_id':[company['company_id']], 'periods':sorted(target),
              'year':sorted({y for y,_ in target}), 'month':sorted({m for _,m in target})}
    return values
