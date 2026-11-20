"""Read-result adapters for a runtime-owned request; never an intent parser.

This module owns neither the current request nor draft state. It compares
registered tool evidence to a request bound before execution was proposed.
"""
from copy import deepcopy
from calendar import monthrange
from datetime import date
import json


from .tool_contracts import TOOL_SPECS, CAPABILITIES, SUPPORT_TOOLS


class RequestDeliveryError(ValueError):
    def __init__(self, message, status='SCOPE_MISMATCH', **details):
        super().__init__(message)
        self.status = status
        self.details = details


def _frame(request, actor, book):
    from .business_request import BusinessRequest, BusinessRequestError
    if not isinstance(request, BusinessRequest):
        raise RequestDeliveryError('本轮尚未建立可核对的业务要求。', 'REQUEST_UNRESOLVED')
    try:
        request.require_current(actor, book)
    except BusinessRequestError as error:
        raise RequestDeliveryError(str(error), error.status) from None
    if request.unresolved:
        raise RequestDeliveryError('当前业务要求仍有未决项，请先明确查询对象。', 'REQUEST_UNRESOLVED')


def _periods(scope):
    if scope.get('periods'):
        return {tuple(pair) for pair in scope['periods']}
    if scope.get('year') and scope.get('month'):
        return {(scope['year'], scope['month'])}
    if scope.get('year'):
        return {(scope['year'], month) for month in range(1, 13)}
    return set()


def _companies(scope):
    return set(scope.get('company_ids') or ([scope['company_id']] if scope.get('company_id') else []))


def _targets(request, object_name, scope):
    companies, periods = _companies(scope), _periods(scope)
    if not companies or not periods:
        raise RequestDeliveryError('返回证据缺少完整企业或账期，尚未交付统计。', 'SQL_EVIDENCE_UNSUPPORTED')
    matches = [target for target in request.targets if target.object == object_name
               and companies <= set(target.company_ids) and periods <= set(target.periods)]
    if not matches:
        raise RequestDeliveryError('实际查询对象或账期超出本轮业务要求，未交付该结果。')
    return matches


def _directions(condition):
    if condition.field != 'direction':
        return set()
    values = ({condition.value} if condition.operator == '=' else set(condition.value)
              if condition.operator == 'IN' and isinstance(condition.value, tuple) else set())
    return values if values and values <= {'收入', '支出'} else set()


def preflight(request, name, args, actor, book):
    """Reject unsupported dedicated-tool filters before any data is read."""
    _frame(request, actor, book)
    if name not in CAPABILITIES:
        if name in SUPPORT_TOOLS:
            return
        raise RequestDeliveryError('该工具尚未登记本轮业务要求的结果契约，未执行。',
                                   'TOOL_CAPABILITY_MISMATCH')
    if TOOL_SPECS[name].result_adapter == 'sql':
        scope = args.get('read_scope')
        if scope:
            actual = {'company_id': scope['company_id'],
                      'periods': [(p['year'], p['month']) for p in scope['periods']]}
            if not any(_companies(actual) <= set(t.company_ids)
                       and _periods(actual) <= set(t.periods) for t in request.targets):
                raise RequestDeliveryError('查询候选的企业或账期不属于当前要求。')
        return
    companies, periods = _companies(args), _periods(args)
    applicable = [t for t in request.targets if t.object in CAPABILITIES[name]
                  and companies and companies <= set(t.company_ids)
                  and (TOOL_SPECS[name].read_mode == 'invoice' or periods and periods <= set(t.periods))]
    if not applicable:
        raise RequestDeliveryError('该工具返回的业务对象不属于当前要求。')
    for target in applicable:
        if TOOL_SPECS[name].result_adapter == 'summary':
            supported_groups = {'period', 'company_id'}
            if target.object == 'bank_transactions':
                supported_groups.add('direction')
            if set(target.group_by) - supported_groups:
                raise RequestDeliveryError('此汇总工具不能提供本轮要求的分组，未执行该统计。',
                                           'TOOL_CAPABILITY_MISMATCH', target_id=target.target_id)
        seller = target.seller
        if TOOL_SPECS[name].condition_mode != 'row' and (seller is not None and seller.mode != 'none' or target.filters):
            # Whole-month tools cannot acquire filter support merely because
            # the generator picked them instead of SQL.
            allowed = (seller is None and target.filters
                       and all(_directions(f)
                               and (TOOL_SPECS[name].condition_mode == 'direction'
                                    or TOOL_SPECS[name].condition_mode == 'direction_arg' and _directions(f) == {args.get('direction')})
                               for f in target.filters))
            if not allowed:
                raise RequestDeliveryError('此工具不能落实本轮附加筛选，请使用支持该条件的查询。',
                                           'TOOL_CAPABILITY_MISMATCH', target_id=target.target_id)


def _condition_key(condition):
    return json.dumps(condition, ensure_ascii=False, sort_keys=True)


def _proof_filter(condition):
    value=list(condition.value) if isinstance(condition.value,tuple) else condition.value
    # Empty-string spells positive blank. False must remain False.
    if condition.operator=='is_blank' and type(value) is str and value=='':value=True
    return {'field':condition.field,'operator':condition.operator,'value':value}


def _expected_filters(target):
    return [_proof_filter(f) for f in target.filters]


def canonical_sql_result(result):
    # Canonicalize consumer metadata from same-transaction constraints only.
    # Original attribution, SQL/hash and rows are retained; no new reads occur.
    from hashlib import sha256
    data=result.get('data') or {};query=(result.get('evidence') or {}).get('query_scope') or {}
    version=data.get('read_version') or {};constraints=version.get('schema_constraints') or {}
    columns=constraints.get('not_null_columns');sql=data.get('sql')
    if (query.get('status')!='VERIFIED' or version.get('consistency')!='one_sqlite_read_transaction'
            or constraints.get('source')!='same_sqlite_read_transaction' or type(columns) is not dict
            or not version.get('scope_snapshot_sha256') or type(sql) is not str
            or query.get('sql_sha256')!=sha256(sql.encode('utf-8')).hexdigest()
            or constraints.get('sha256')!=sha256(json.dumps(columns,sort_keys=True,
                separators=(',', ':')).encode()).hexdigest()):
        return result
    declared=columns.get(query.get('table'),())
    if type(declared) not in (list,tuple) or any(type(name) is not str for name in declared):return result
    changes=[i for i,column in enumerate(query.get('columns',()))
             if column.get('kind')=='count_nonnull' and column.get('field') in declared]
    if not changes:return result
    accepted=deepcopy(result);evidence=accepted['evidence'];current=evidence['query_scope']
    evidence.setdefault('original_query_scope',deepcopy(query))
    for index in changes:
        column=current['columns'][index];original=deepcopy(column);field=column.pop('field')
        column['kind']='count_rows'
        column['original_attribution']=original
        column['equivalence']={'rule':'count_nonnull_equals_rows_on_not_null',
            'table':query['table'],'field':field,'source':'same_sqlite_read_transaction',
            'schema_sha256':constraints['sha256'],'scope_snapshot_sha256':version['scope_snapshot_sha256'],
            'sql_sha256':query['sql_sha256']}
    return accepted


def _check_conditions(target, conditions, actor, book, *, seller_partition=False):
    from .seller_read_scope import catalog, _matching
    sellers = [c for c in conditions if c.get('field') == 'seller_name']
    others = [c for c in conditions if c.get('field') not in
              {'seller_name', 'company_id', 'invoice_date', 'transaction_date'}]
    expected_filters = [c for c in _expected_filters(target)
                        if c['field'] not in {'invoice_date', 'transaction_date'}]
    expected_fields = {c['field'] for c in expected_filters}
    partitions = [c for c in others if c['field'] in target.group_by and c['field'] not in expected_fields]
    if any(c['field'] != 'direction' or c['operator'] != '=' or c['value'] not in {'收入', '支出'}
           for c in partitions):
        raise RequestDeliveryError('分组分片不能改变本轮请求的业务范围。')
    others = [c for c in others if c not in partitions]
    if {_condition_key(c) for c in others} != {_condition_key(c) for c in expected_filters}:
        raise RequestDeliveryError('实际筛选与本轮业务要求不一致，未交付统计。')
    expected = target.seller
    if expected is None or expected.mode == 'none':
        if sellers:
            raise RequestDeliveryError('实际查询增加了本轮没有要求的销售方限制。')
    elif expected.mode == 'ambiguous':
        raise RequestDeliveryError('销售方尚未唯一确定，请选择完整名称。', 'REQUEST_UNRESOLVED')
    else:
        actual = _matching(catalog(book, actor, target.company_ids), sellers) if sellers else set()
        equivalent = (bool(actual) and actual <= set(expected.names) if 'seller_name' in target.group_by or seller_partition
                      else actual == set(expected.names))
        if not sellers or not equivalent:
            raise RequestDeliveryError('实际销售方集合与本轮绑定要求不一致，未交付统计。')


def _metric_matches(target, fact):
    _, operation, field = fact['metric']
    operation = {'count_rows': 'count', 'count_nonnull': 'count'}.get(operation, operation)
    field = '*' if field is None else field
    return any(metric.operation == operation and metric.field == field for metric in target.metrics)


def _check_date_coverage(target, scope, conditions):
    """A coarse month tag never proves that a predicate kept the whole month.

    Reuse attributed predicates over the bounded ISO-date domain (at most the
    request's 24 months), including conditions inside individual measures.
    """
    from .seller_read_scope import _matching
    field = 'invoice_date' if target.object == 'invoices' else 'transaction_date'
    actual = [c for c in conditions if c.get('field') == field]
    expected = [c for c in _expected_filters(target) if c['field'] == field]

    days = {date(year, month, day).isoformat() for year, month in _periods(scope)
            for day in range(1, monthrange(year, month)[1] + 1)}

    def accepted(predicates):
        selected = set(days)
        for predicate in predicates:
            prefix = predicate.get('prefix_length')
            values = {value[:prefix] if prefix else value for value in selected}
            matched = _matching(values, [predicate])
            selected = {value for value in selected if (value[:prefix] if prefix else value) in matched}
        return selected

    if accepted(actual) != accepted(expected):
        raise RequestDeliveryError('实际日期条件只覆盖所需账期的一部分或改变了日期范围，未交付该统计。')


def _check_grouping(target, fact, conditions):
    dimensions = fact.get('dimensions', {})
    for field in dimensions:
        group = 'period' if field.endswith(('_date_month', '_date_year')) else field
        fixed = (group == 'company_id' and len(target.company_ids) == 1
                 or group == 'period' and len(target.periods) == 1
                 or group == 'seller_name' and target.seller is not None and len(target.seller.names) == 1
                 or any(f.field == field and (f.operator == '=' or f.operator == 'IN'
                            and isinstance(f.value, tuple) and len(f.value) == 1) for f in target.filters))
        if group not in target.group_by and not fixed:
            raise RequestDeliveryError('实际结果按未要求的维度切分，不能作为本轮所需合计。',
                                       reason='unexpected_grouping')
    for group in target.group_by:
        if group == 'period':
            if len(_periods(fact['scope'])) != 1:
                raise RequestDeliveryError('本轮要求分期统计，实际结果合并了多个账期。')
        elif group == 'company_id' and len(_companies(fact['scope'])) == 1:
            continue
        elif group not in dimensions and not any(c.get('field') == group and c.get('operator') == '='
                                               for c in conditions):
            raise RequestDeliveryError('实际分组未保留本轮要求的业务维度。')


def _check_fact(target, fact, conditions, actor, book):
    measured = [*conditions, *({'field': field, 'operator': '=', 'value': value}
        for field, value in fact.get('dimensions', {}).items()
        if (field == 'seller_name' and target.seller is not None and target.seller.mode != 'none'
            or any(f.field == field for f in target.filters)
            and not any(c.get('field') == field for c in conditions)))]
    _check_date_coverage(target, fact['scope'], conditions)
    # An actual seller dimension can identify a set member.  It does not make
    # that member's amount the requested set total: grouping is checked next.
    _check_conditions(target, measured, actor, book,
                      seller_partition='seller_name' in fact.get('dimensions', {}))
    _check_grouping(target, fact, measured)
    return measured


def check_sql(request, result, actor, book, *, proofs=None):
    """Check WHERE and each conditional measure; aliases cannot define metrics."""
    _frame(request, actor, book)
    evidence = result.get('evidence') or {}
    query = evidence.get('query_scope') or {}
    if query.get('status') != 'VERIFIED' or query.get('scope') is None:
        raise RequestDeliveryError('当前证据核验不支持此查询形式，尚未交付结果。', 'SQL_EVIDENCE_UNSUPPORTED')
    targets = _targets(request, query.get('table'), query['scope'])
    if (result.get('status') == 'NO_DATA' and result.get('data', {}).get('rows') == []
            and not result['data'].get('truncated') and not query.get('limited')):
        for target in targets:
            _check_date_coverage(target, query['scope'], query.get('conditions', ()))
            _check_conditions(target, query.get('conditions', ()), actor, book)
            if proofs is not None:
                for metric in target.metrics:
                    proofs.append({'target_id': target.target_id, 'operation': metric.operation, 'field': metric.field,
                                   'scope': deepcopy(query['scope']), 'dimensions': {}, 'absence': True,
                                   'conditions': deepcopy(query.get('conditions', ())), 'all_groups': True})
        return tuple(t.target_id for t in targets)
    from .fact_arithmetic import sql_scalars
    scalar_facts = sql_scalars(result, 'unpublished', '')
    if scalar_facts:
        accepted = []
        for key, (_, fact) in scalar_facts.items():
            column_index = int(key.rsplit('.', 1)[1])
            column = query['columns'][column_index]
            conditions = [*query.get('conditions', ()), *column.get('conditions', ())]
            last_error = None
            matched = False
            for target in _targets(request, query['table'], fact['scope']):
                if not _metric_matches(target, fact):
                    continue
                # Group values are actual result dimensions, not the SQL
                # generator's interpretation of a user condition.
                try:
                    measured = _check_fact(target, fact, conditions, actor, book)
                    accepted.append(target)
                    matched = True
                    if proofs is not None:
                        operation = {'count_rows': 'count', 'count_nonnull': 'count'}.get(fact['metric'][1], fact['metric'][1])
                        proofs.append({'target_id': target.target_id, 'operation': operation,
                            'field': fact['metric'][2] or '*', 'scope': deepcopy(fact['scope']),
                            'dimensions': deepcopy(fact.get('dimensions', {})), 'conditions': deepcopy(measured),
                            'basis': fact.get('basis'),
                            'all_groups': bool(query.get('query_set_complete'))})
                except RequestDeliveryError as error:
                    last_error = error
            if not matched:
                raise last_error or RequestDeliveryError('实际指标、单位或筛选没有对应的本轮业务要求。')
        return tuple(dict.fromkeys(target.target_id for target in accepted))
    if any(column.get('kind') not in {'column', 'date_bucket'} for column in query.get('columns', ())):
        raise RequestDeliveryError('统计结果尚无完整、整数单位的标量证据，未交付该统计。',
                                   'SQL_EVIDENCE_UNSUPPORTED')
    errors = []
    for target in targets:
        try:
            _check_conditions(target, query.get('conditions', ()), actor, book)
            for column in query.get('columns', ()):
                if column.get('conditions'):
                    _check_conditions(target, [*query.get('conditions', ()), *column['conditions']], actor, book)
            return (target.target_id,)
        except RequestDeliveryError as error:
            errors.append(error)
    raise errors[0]


def _identity_targets(request, query, fact, actor, book):
    """Recognize actual grouped identities, without granting their measures."""
    from .seller_read_scope import _matching, catalog
    dimensions = fact.get('dimensions', {})
    matches = []
    for target in _targets(request, query['table'], fact['scope']):
        seller = target.seller
        if seller is not None and seller.mode != 'none':
            if 'seller_name' in dimensions:
                if dimensions['seller_name'] not in seller.names:
                    continue
            else:
                conditions = [c for c in query.get('conditions', ()) if c.get('field') == 'seller_name']
                actual = _matching(catalog(book, actor, target.company_ids), conditions)
                if not actual or not actual <= set(seller.names):
                    continue
        valid = True
        for condition in _expected_filters(target):
            field = condition['field']
            if field in {'invoice_date', 'transaction_date'}:
                continue  # Object clues do not certify a period total.
            if field in dimensions:
                valid = bool(_matching([dimensions[field]], [condition]))
            else:
                valid = condition in query.get('conditions', ())
            if not valid:
                break
        if valid:
            matches.append(target.target_id)
    return matches


def _project_detail_result(request, original, actor, book):
    """Discard only scalar display expressions from proven source-row details."""
    query=original['evidence']['query_scope']
    columns=query.get('columns',())
    if (query.get('row_shape')!='detail'
            or not query.get('row_shape_evidence',{}).get('preserves_filtered_source_rows')
            or any(c.get('kind')=='unattributed' and c.get('row_effect')!='scalar' for c in columns)):
        return original
    targets=[t for t in _targets(request,query.get('table'),query['scope'])
             if any(m.operation=='details' for m in t.metrics)]
    if not targets:return original
    keep=[i for i,c in enumerate(columns) if c.get('kind')=='column']
    fields={columns[i]['field'] for i in keep}
    identity={'company_id','invoice_no','invoice_date'} if query['table']=='invoices' else {
        'company_id','transaction_no','transaction_date'}
    if not identity<=fields:return original
    # Scope/filters are proved before even a partial card is released. Removing
    # a display expression cannot conceal a broader seller or a date restriction.
    ids=[];matched=[];errors=[]
    for target in targets:
        try:
            _check_date_coverage(target,query['scope'],query.get('conditions',()))
            _check_conditions(target,query.get('conditions',()),actor,book)
        except RequestDeliveryError as error:
            errors.append(error)
        else:
            ids.append(target.target_id);matched.append(target)
    if not matched:raise errors[0]
    data=original['data'];old_names=list(data['columns'])
    data['columns']=[old_names[i] for i in keep]
    data['rows']=[tuple(row[i] for i in keep) for row in data['rows']]
    data['derived']=[{str(j):row[str(i)] for j,i in enumerate(keep) if str(i) in row}
                     for row in data.get('derived',[])]
    data['request_projection']={'original_columns':old_names,'source_column_indices':keep,
        'source_columns':deepcopy(columns),'source_projection_complete':query.get('projection_complete'),
        'source_query_set_complete':query.get('query_set_complete'),
        'source_row_indices':list(range(len(data['rows']))),'identity_only':False,'detail_columns_only':True}
    query['columns']=[columns[i] for i in keep];query['projection_complete']=True
    # Render genuine raw invoice fields with their existing cents formatter;
    # an arbitrary SQL alias or the omitted conversion supplies no unit proof.
    if query['table']=='invoices' and 'amount_cents' in fields:
        data['invoice_projection']={c['field']:i for i,c in enumerate(query['columns'])}
    accepted=annotate(original,request,ids)
    if (query.get('query_set_complete') and not query.get('limited') and data.get('truncated') is False):
        from .business_sql import TABLES
        all_fields={part.strip().split()[0] for part in TABLES[query['table']].split(',')}
        accepted['evidence']['business_request']['measures']=[{
            'target_id':target.target_id,'operation':'details','field':metric.field,
            'scope':deepcopy(query['scope']),'dimensions':{},'conditions':deepcopy(query.get('conditions',())),
            'all_groups':True,'source_columns':sorted(fields)} for target in matched for metric in target.metrics
            if metric.operation=='details' and (all_fields<=fields if metric.field=='*' else metric.field in fields)]
    return accepted


def project_sql_result(request, result, actor, book):
    """Retain requested measures, or only identity clues for finer groupings.

    No amounts are recomputed. The original SQL/hash remain in evidence, along
    with a projection map. This is not a compiler or a replacement query.
    """
    from .fact_arithmetic import sql_scalars
    original = deepcopy(result)
    query = original.get('evidence', {}).get('query_scope') or {}
    if query.get('status') != 'VERIFIED':
        return original
    facts = sql_scalars(original, 'unpublished', '')
    if not facts:
        return _project_detail_result(request,original,actor,book)
    columns = query['columns']
    source_projection_complete = query.get('projection_complete')
    requested = {int(key.rsplit('.', 1)[1]) for key, (_, fact) in facts.items()
                 if any(t.object == query['table'] and _metric_matches(t, fact) for t in request.targets)}
    if not requested:
        raise RequestDeliveryError('实际结果没有本轮请求的指标，未交付该统计。')
    keep = [i for i, column in enumerate(columns) if column.get('kind') in {'column', 'date_bucket'} or i in requested]
    data = original['data']
    old_columns = list(data['columns'])
    data['columns'] = [old_columns[i] for i in keep]
    data['rows'] = [tuple(row[i] for i in keep) for row in data['rows']]
    data['derived'] = [{str(j): derived[str(i)] for j, i in enumerate(keep) if str(i) in derived}
                       for derived in data['derived']]
    query['columns'] = [columns[i] for i in keep]
    projected_facts = sql_scalars(original, 'unpublished', '')
    by_row = {}
    for key, (_, fact) in projected_facts.items():
        by_row.setdefault(int(key.split('.')[1]), fact)
    accepted_rows, identity_rows, ids, proofs, first_error = [], [], set(), [], None
    for row_index in range(len(data['rows'])):
        sample = deepcopy(original)
        sample['data']['rows'] = [data['rows'][row_index]]
        sample['data']['derived'] = [data['derived'][row_index]]
        sample['data']['row_count'] = 1
        try:
            row_proofs = []
            ids.update(check_sql(request, sample, actor, book, proofs=row_proofs))
            proofs.extend(row_proofs)
            accepted_rows.append(row_index)
        except RequestDeliveryError as error:
            first_error = first_error or error
            fact = by_row.get(row_index)
            if fact is None:
                continue
            try:
                candidates = _identity_targets(request, query, fact, actor, book)
            except RequestDeliveryError:
                candidates = []
            # Only a grouping mismatch may degrade to nonnumeric clues.
            # A half-month predicate must not be hidden by that fallback.
            if candidates and error.details.get('reason') == 'unexpected_grouping':
                identity_rows.append(row_index); ids.update(candidates)
    rows = sorted(set(accepted_rows + identity_rows))
    if not rows:
        raise first_error or RequestDeliveryError('查询尚未得到可核对的目标结果。')
    if data.get('selection_id') or data.get('invoice_projection'):
        if len(rows) != len(data['rows']):
            raise RequestDeliveryError('当前展示身份不能与原选择集一致，未交付该结果。')
    identity_only = bool(identity_rows)
    if identity_only:
        identity_columns = [i for i, c in enumerate(query['columns']) if c.get('unit') == 'text']
        if not identity_columns:
            raise first_error
        data['columns'] = [data['columns'][i] for i in identity_columns]
        data['rows'] = [tuple(data['rows'][r][i] for i in identity_columns) for r in rows]
        data['derived'] = [{} for _ in rows]
        query['columns'] = [query['columns'][i] for i in identity_columns]
        keep = [keep[i] for i in identity_columns]
        data['request_identity_evidence_only'] = True
    else:
        data['rows'] = [data['rows'][r] for r in rows]
        data['derived'] = [data['derived'][r] for r in rows]
    data['row_count'] = len(rows)
    data['request_projection'] = {'original_columns': old_columns, 'source_column_indices': keep,
                                  'source_columns': deepcopy(columns),
                                  'source_projection_complete': source_projection_complete,
                                  'source_query_set_complete': query.get('query_set_complete'),
                                  'source_row_indices': rows, 'identity_only': identity_only}
    query['projection_complete'] = all(c.get('kind') != 'unattributed' for c in query['columns'])
    if len(rows) != len(result['data']['rows']) or identity_only:
        query['query_set_complete'] = False
    accepted = annotate(original, request, sorted(ids))
    if identity_only:
        accepted['evidence']['business_request']['coverage'] = 'identity_evidence_only'
    else:
        accepted['evidence']['business_request']['measures'] = proofs
    return accepted


def failure(error, request=None):
    evidence = {'source': 'business_request', **error.details}
    from .business_request import BusinessRequest
    if isinstance(request, BusinessRequest):
        # A stale/different-actor frame must not disclose its catalog or text.
        evidence['business_request'] = {'revision': request.revision, 'request_hash': request.request_hash}
    return {'ok': False, 'status': error.status, 'data': None,
            'evidence': evidence, 'error': str(error)}


def annotate(result, request, target_ids):
    accepted = deepcopy(result)
    accepted.setdefault('evidence', {})['business_request'] = {
        'revision': request.revision, 'request_hash': request.request_hash,
        'target_ids': list(target_ids), 'interpretation': 'model_requirement_with_runtime_binding',
        'formal_semantic_proof': False, 'coverage': 'accepted_partial'}
    return accepted


SUMMARY_FIELDS = {
    'invoice_count': ('invoices', 'count', '*', None),
    'invoice_total': ('invoices', 'sum', 'amount_cents', None),
    'bank_income_count': ('bank_transactions', 'count', '*', '收入'),
    'bank_income_total': ('bank_transactions', 'sum', 'amount_cents', '收入'),
    'bank_expense_count': ('bank_transactions', 'count', '*', '支出'),
    'bank_expense_total': ('bank_transactions', 'sum', 'amount_cents', '支出'),
}


def _summary_fields(request, scope, *, targets=None):
    fields, ids = set(), set()
    for field, (object_name, operation, metric_field, direction) in SUMMARY_FIELDS.items():
        for target in request.targets if targets is None else targets:
            if (target.object != object_name or not _companies(scope) <= set(target.company_ids)
                    or not _periods(scope) <= set(target.periods)):
                continue
            if 'period' in target.group_by and len(_periods(scope)) != 1:
                continue
            supported_groups = {'period', 'company_id'} | ({'direction'} if object_name == 'bank_transactions' else set())
            if set(target.group_by) - supported_groups:
                continue
            if target.seller is not None and target.seller.mode != 'none':
                continue
            if not any(m.operation == operation and m.field == metric_field for m in target.metrics):
                continue
            if target.filters and not all(direction in _directions(f)
                                          for f in target.filters):
                continue
            fields.add(field); ids.add(target.target_id)
    return fields, ids


def check_dedicated(request, name, result, actor, book):
    from .fact_arithmetic import basis as measure_basis
    _frame(request, actor, book)
    evidence, data = result.get('evidence') or {}, result.get('data')
    scope = evidence.get('scope') or {}
    if TOOL_SPECS[name].result_adapter == 'summary':
        fields, target_ids = _summary_fields(request, scope)
        if not isinstance(data, dict) or not fields or not fields <= data.keys():
            raise RequestDeliveryError('该汇总没有本轮要求的完整指标证据。', 'TOOL_CAPABILITY_MISMATCH')
        from .fact_arithmetic import cents
        if any(type(data[field]) is not int if field.endswith('_count') else cents(data[field]) is None
               for field in fields):
            raise RequestDeliveryError('统计单位或金额值尚不能核实。', 'SQL_EVIDENCE_UNSUPPORTED')
        accepted = deepcopy(result)
        accepted['data'] = {field: data[field] for field in fields}
        prefixes = {field.rsplit('_', 1)[0] for field in fields}
        if all(data.get(prefix + '_count') == 0 for prefix in prefixes):
            accepted['status'] = 'NO_DATA'
        accepted = annotate(accepted, request, sorted(target_ids))
        accepted['evidence']['business_request']['summary_fields'] = sorted(fields)
        accepted['evidence']['business_request']['measures'] = [
            {'target_id': target.target_id, 'operation': SUMMARY_FIELDS[field][1],
             'field': SUMMARY_FIELDS[field][2], 'scope': deepcopy(scope),
             'dimensions': {'direction': SUMMARY_FIELDS[field][3]} if SUMMARY_FIELDS[field][3] else {},
             'conditions': [], 'all_groups': True,
             'basis': measure_basis({
                 'status': 'VERIFIED', 'scope': scope,
                 'conditions': ([{'field': 'direction', 'operator': '=', 'value': SUMMARY_FIELDS[field][3]}]
                                if SUMMARY_FIELDS[field][3] else [])})}
            for field in fields for target in request.targets
            if field in _summary_fields(request, scope, targets=(target,))[0]]
        return accepted
    object_name = CAPABILITIES[name][0]
    targets = _targets(request, object_name, scope)
    rows = [data] if isinstance(data, dict) else data or []
    from .seller_read_scope import _matching
    from .fact_arithmetic import cents
    ids = set()
    for row in rows:
        matches = []
        for target in targets:
            if target.seller is not None and target.seller.mode != 'none':
                if row.get('seller_name') not in target.seller.names:
                    continue
            if all(_matching([cents(row.get('amount')) if f.field == 'amount_cents' else row.get(f.field)],
                             [_proof_filter(f)])
                   for f in target.filters):
                matches.append(target)
        if not matches:
            raise RequestDeliveryError('明细对象或筛选不属于当前业务要求，未交付该结果。')
        ids.update(t.target_id for t in matches)
    if not rows:
        ids.update(t.target_id for t in targets)
    accepted = annotate(result, request, sorted(ids))
    if 'finance_summary' in accepted['evidence']:
        fields, _ = _summary_fields(request, scope)
        accepted['evidence']['finance_summary'] = {
            k: v for k, v in accepted['evidence']['finance_summary'].items() if k in fields}
    return accepted


def accept_result(request, name, result, actor, book):
    if result.get('status') not in {'SUCCESS', 'NO_DATA'} or name not in CAPABILITIES:
        return result
    if TOOL_SPECS[name].result_adapter == 'sql':
        _frame(request, actor, book)
        projected = project_sql_result(request, canonical_sql_result(result), actor, book)
        if projected.get('data', {}).get('request_projection'):
            return projected
        proofs = []
        accepted = annotate(projected, request, check_sql(request, projected, actor, book, proofs=proofs))
        accepted['evidence']['business_request']['measures'] = proofs
        return accepted
    preflight(request, name, result.get('evidence', {}).get('scope') or {}, actor, book)
    return check_dedicated(request, name, result, actor, book)


def render_projected_summary(data, evidence):
    if not (evidence.get('business_request') or {}).get('summary_fields'):
        return None
    labels = {'invoice_count': ('发票张数', '张'), 'invoice_total': ('发票价税合计', '元'),
              'bank_income_count': ('银行收入笔数', '笔'), 'bank_income_total': ('银行收入合计', '元'),
              'bank_expense_count': ('银行支出笔数', '笔'), 'bank_expense_total': ('银行支出合计', '元')}
    return '；'.join(f'{label} {data[field]} {unit}' for field, (label, unit) in labels.items() if field in data)


def assess_results(request, results):
    """Derive execution coverage from accepted proofs, not tool names or text.

    This deliberately does not certify the generator's final reference choices
    or claim that an available comparison was actually shown to the user.
    """
    from itertools import product
    proofs = []
    for _, result in results:
        meta = (result.get('evidence') or {}).get('business_request') or {}
        if (result.get('status') not in {'SUCCESS', 'NO_DATA'}
                or meta.get('request_hash') != request.request_hash or meta.get('revision') != request.revision
                or meta.get('coverage') == 'identity_evidence_only'):
            continue
        proofs.extend(meta.get('measures', ()))
    assessments, missing = [], []
    for target in request.targets:
        company_axis = [(c,) for c in target.company_ids] if 'company_id' in target.group_by else [tuple(sorted(target.company_ids))]
        period_axis = [(p,) for p in target.periods] if 'period' in target.group_by else [tuple(sorted(target.periods))]
        seller_axis = [None]
        if 'seller_name' in target.group_by:
            seller_axis = list(target.seller.names) if target.seller and target.seller.names else ['all_groups']
        direction_axis = [None]
        if 'direction' in target.group_by:
            direction_axis = sorted(set.intersection(*[_directions(f) for f in target.filters if _directions(f)])
                                    if any(_directions(f) for f in target.filters) else {'收入', '支出'})
        required = set(product(company_axis, period_axis, seller_axis, direction_axis,
                               ((m.operation, m.field) for m in target.metrics)))
        covered = set()
        for proof in proofs:
            if proof['target_id'] != target.target_id:
                continue
            companies = tuple(sorted(_companies(proof['scope'])))
            periods = tuple(sorted(_periods(proof['scope'])))
            dims = proof.get('dimensions') or {}
            conditions = proof.get('conditions') or ()
            sellers, directions = [None], [None]
            if 'seller_name' in target.group_by:
                seller = dims.get('seller_name') or next((c['value'] for c in conditions
                    if c.get('field') == 'seller_name' and c.get('operator') == '='), None)
                sellers = ([seller] if seller else seller_axis if proof.get('absence')
                           or seller_axis == ['all_groups'] and proof.get('all_groups') else [])
                if seller_axis == ['all_groups'] and proof.get('all_groups'):
                    sellers = seller_axis
            if 'direction' in target.group_by:
                direction = dims.get('direction') or next((c['value'] for c in conditions
                    if c.get('field') == 'direction' and c.get('operator') == '='), None)
                directions = [direction] if direction else direction_axis if proof.get('absence') else []
            for seller, direction in product(sellers, directions):
                key = (companies, periods, seller, direction, (proof['operation'], proof['field']))
                if key in required:
                    covered.add(key)
        pending = required - covered
        missing.extend(target.target_id + ':' + repr(key) for key in sorted(pending, key=repr))
        assessments.append({'target_id': target.target_id, 'status': 'complete' if not pending else 'partial',
                            'required': len(required), 'covered': len(covered),
                            'comparisons_requested': len(target.comparisons),
                            'comparison_delivery_verified': False})
    missing.extend(request.unresolved)
    complete = bool(assessments) and not missing
    return {'status': 'unresolved' if request.unresolved else 'complete' if complete else 'partial',
            'complete': complete, 'targets': assessments, 'missing': missing,
            'coverage_kind': 'execution_evidence', 'final_delivery_verified': False}


def assess_selection(request, answer, facts, results):
    """Bind current fact selections to accepted proofs and requested comparisons.

    Arithmetic dependencies do not count as displayed monthly values. A whole
    result reference covers only its actual, accepted scalar children.
    """
    from .fact_arithmetic import derive
    proven = {}
    for index, (name, result) in enumerate(results):
        meta = (result.get('evidence') or {}).get('business_request') or {}
        measures = meta.get('measures', ()) if (
            result.get('status') in {'SUCCESS', 'NO_DATA'}
            and meta.get('request_hash') == request.request_hash
            and meta.get('revision') == request.revision
            and meta.get('coverage') != 'identity_evidence_only') else ()
        for ref, fact in facts.items():
            parent = fact.get('parent_ref', '')
            if fact.get('type') != 'scalar' or parent.rsplit(':', 1)[-1] != f'r{index}.result':
                continue
            metric = fact.get('metric') or ()
            if len(metric) != 3:
                continue
            operation = {'count_rows': 'count', 'count_nonnull': 'count'}.get(metric[1], metric[1])
            matches = []
            for proof in measures:
                target = next((t for t in request.targets if t.target_id == proof['target_id']), None)
                dimensions = proof.get('dimensions') or {}
                if TOOL_SPECS[name].result_adapter == 'summary':
                    dimensions = {k: v for k, v in dimensions.items() if k != 'direction'}
                if (target is not None and metric[0] == target.object
                        and (operation, metric[2] or '*') == (proof['operation'], proof['field'])
                        and _companies(fact['scope']) == _companies(proof['scope'])
                        and _periods(fact['scope']) == _periods(proof['scope'])
                        and fact.get('basis') == proof.get('basis')
                        and (fact.get('dimensions') or {}) == dimensions):
                    matches.append((index, proof))
            if matches:
                proven[ref] = matches
    selected = set()
    comparisons = set()
    invalid = []
    for position, item in enumerate(answer or ()):
        if type(item) is str:
            selected.add(item)
            selected.update(ref for ref, fact in facts.items() if fact.get('parent_ref') == item)
            continue
        if type(item) is not dict or derive(item, facts) is None:
            invalid.append({'answer_index': position, 'reason': 'invalid_arithmetic'})
            continue
        left, right = facts[item['left']], facts[item['right']]
        matched = False
        for _, lp in proven.get(item['left'], ()):
            for _, rp in proven.get(item['right'], ()):
                if lp['target_id'] != rp['target_id']:
                    continue
                target = next(t for t in request.targets if t.target_id == lp['target_id'])
                for number, comparison in enumerate(target.comparisons):
                    same_groups = {k: v for k, v in lp.get('dimensions', {}).items()
                                   if not k.endswith(('_date_month', '_date_year'))} == {
                                       k: v for k, v in rp.get('dimensions', {}).items()
                                       if not k.endswith(('_date_month', '_date_year'))}
                    if (item['op'] == comparison.operation
                            and (lp['operation'], lp['field']) == (rp['operation'], rp['field'])
                            == (comparison.metric_operation, comparison.metric_field)
                            and _periods(left['scope']) == {comparison.left_period}
                            and _periods(right['scope']) == {comparison.right_period}
                            and _companies(left['scope']) == _companies(right['scope']) and same_groups):
                        comparisons.add((target.target_id, number)); matched = True
        if not matched:
            invalid.append({'answer_index': position, 'reason': 'comparison_requirement_mismatch'})
    selected_results = []
    for index, (name, result) in enumerate(results):
        copied = deepcopy(result)
        meta = copied.setdefault('evidence', {}).setdefault('business_request', {})
        meta['measures'] = [proof for ref in selected for source_index, proof in proven.get(ref, ())
                            if source_index == index]
        # Detail rows are delivered by the actual whole-result fact. Scalar
        # arithmetic or an unselected available table cannot certify them.
        result_selected=any(ref in selected and fact.get('type')=='result'
                            and ref.rsplit(':',1)[-1]==f'r{index}.result' for ref,fact in facts.items())
        original_meta=(result.get('evidence') or {}).get('business_request') or {}
        if (result_selected and original_meta.get('request_hash')==request.request_hash
                and original_meta.get('revision')==request.revision):
            meta['measures'].extend(proof for proof in original_meta.get('measures',())
                                    if proof.get('operation')=='details')
        selected_results.append((name, copied))
    assessment = assess_results(request, selected_results)
    # The ordinary axes above have known request domains. Other actual business
    # groups (item, counterparty, date, etc.) come from complete returned sets.
    # Selecting one group from such a set must not certify all groups delivered.
    for target in request.targets:
        fields = set(target.group_by) - {'company_id', 'period', 'seller_name', 'direction'}
        if not fields:
            continue
        expected, shown = set(), set()
        for ref, matches in proven.items():
            for _, proof in matches:
                if proof['target_id'] != target.target_id:
                    continue
                dims = proof.get('dimensions') or {}
                if not fields <= dims.keys() or not proof.get('all_groups'):
                    assessment['missing'].append(target.target_id + ':group_domain_unverified')
                    continue
                key = (proof['operation'], proof['field'], tuple(sorted(_companies(proof['scope']))),
                       tuple(sorted(_periods(proof['scope']))), tuple((f, dims[f]) for f in sorted(fields)))
                expected.add(key)
                if ref in selected:
                    shown.add(key)
        if not expected or expected - shown:
            assessment['missing'].append(target.target_id + ':groups_not_delivered')
    missing_comparisons = []
    for target, target_assessment in zip(request.targets, assessment['targets']):
        missing = [(target.target_id, number) for number in range(len(target.comparisons))
                   if (target.target_id, number) not in comparisons]
        missing_comparisons.extend(missing)
        target_assessment['comparison_delivery_verified'] = not missing
        if missing or any(value.startswith(target.target_id + ':') for value in assessment['missing']):
            target_assessment['status'] = 'partial'
    assessment['missing'].extend(f'{target_id}:comparison.{number}' for target_id, number in missing_comparisons)
    complete = assessment['complete'] and not assessment['missing'] and not invalid
    assessment.update(status='complete' if complete else 'partial', complete=complete,
                      coverage_kind='displayed_fact_selection', final_delivery_verified=complete,
                      valid=not invalid, invalid=invalid)
    return assessment
