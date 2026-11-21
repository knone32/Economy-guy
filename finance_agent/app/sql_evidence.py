"""Same-string SQL scope/units, independent of SQLite's execution authority.

Only attributed expressions produce proof. Unsupported expressions remain
executable under the existing authorizer but do not acquire VERIFIED evidence.
"""
from datetime import date, timedelta
import hashlib
from pathlib import Path
import re
import sys

WHEEL = Path(__file__).resolve().parents[1] / 'vendor/sqlglot-30.33.0-py3-none-any.whl'
if hashlib.sha256(WHEEL.read_bytes()).hexdigest() != 'a5b279fe7397a9fb6cdd0274a13a5fcee0fa83ac6ff617083f1f2832031e90bc':
    raise ImportError('SQL evidence parser integrity mismatch')
if str(WHEEL) not in sys.path:
    sys.path.insert(0, str(WHEEL))
import sqlglot
from sqlglot import exp
if sqlglot.__version__ != '30.33.0':
    raise ImportError('Unexpected SQL evidence parser version')


class Unsupported(ValueError):
    pass


def describe(sql, columns, snapshot, tables, reads, *, allow_partial_projection=False):
    base = {'scope': None, 'filters': (), 'conditions': [], 'columns': [],
            'sql_sha256': hashlib.sha256(sql.encode()).hexdigest(), 'status': 'UNKNOWN','row_shape':'unknown'}
    try:
        trees = sqlglot.parse(sql, read='sqlite')
        if len(trees) != 1 or not isinstance(trees[0], exp.Select):
            raise Unsupported('not_one_select')
        tree = trees[0]
        if len(list(tree.find_all(exp.Select))) != 1 or any(tree.args.get(k) for k in ('with_', 'joins', 'having', 'qualify', 'windows')):
            raise Unsupported('compound_select')
        source = tree.args.get('from_')
        table = source.this if source else None
        if not isinstance(table, exp.Table) or table.name.lower() not in tables:
            raise Unsupported('unknown_table')
        table_name = table.name.lower()
        if reads != {table_name}:
            raise Unsupported('read_set_mismatch')
        fields = [x.strip().split()[0] for x in tables[table_name].split(',')]
        qualifiers = {table_name, table.alias_or_name.lower()}
        date_field = 'invoice_date' if table_name == 'invoices' else 'transaction_date'

        def field(node):
            if (not isinstance(node, exp.Column) or node.name.lower() not in fields
                    or node.table and node.table.lower() not in qualifiers):
                raise Unsupported('unknown_column')
            return node.name.lower()

        def literal(node):
            if isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal) and not node.this.is_string:
                return -int(node.this.this)
            if not isinstance(node, exp.Literal):
                raise Unsupported('nonliteral_predicate')
            return node.this if node.is_string else int(node.this)

        operations = {exp.EQ: '=', exp.NEQ: '!=', exp.GT: '>', exp.GTE: '>=', exp.LT: '<', exp.LTE: '<=', exp.Like: 'LIKE'}

        def predicate_target(node):
            if isinstance(node, exp.Trim):
                # SQLite's one-argument TRIM removes U+0020 at both ends.
                # Retain that transform in the cohort, never treating it as
                # raw equality or as normalization of identity/date/money.
                if any(value is not None for key, value in node.args.items() if key != 'this'):
                    raise Unsupported('unsupported_text_trim')
                name = field(node.this)
                if name not in {'seller_name', 'item_name', 'purpose', 'remark',
                                'direction', 'counterparty_name'}:
                    raise Unsupported('unsupported_text_trim_field')
                return {'field': name, 'transform': 'trim_ascii_space'}
            if isinstance(node, exp.Substring):
                name = field(node.this)
                start, length = literal(node.args.get('start')), literal(node.args.get('length'))
                if name != date_field or start != 1 or length not in (4, 7):
                    raise Unsupported('unsupported_date_prefix')
                return {'field': name, 'prefix_length': length}
            return {'field': field(node)}

        def predicates(node):
            if isinstance(node, exp.Paren):
                return predicates(node.this)
            if isinstance(node, exp.And):
                return predicates(node.this) + predicates(node.expression)
            if isinstance(node, exp.Or):
                # A union of equalities on one identical target is exactly IN.
                # Keep all other disjunctions unknown: distributing unrelated
                # predicates could enlarge the attributed seller/date cohort.
                def alternatives(part):
                    if isinstance(part, exp.Paren):
                        return alternatives(part.this)
                    if isinstance(part, exp.Or):
                        return alternatives(part.this) + alternatives(part.expression)
                    items = predicates(part)
                    if len(items) != 1 or items[0]['operator'] not in {'=', 'IN'}:
                        raise Unsupported('unsupported_disjunction')
                    return items

                items = alternatives(node)
                target = {k: v for k, v in items[0].items() if k not in {'operator', 'value'}}
                if any({k: v for k, v in item.items() if k not in {'operator', 'value'}} != target
                       for item in items):
                    raise Unsupported('mixed_disjunction_targets')
                values = [value for item in items for value in
                          (item['value'] if item['operator'] == 'IN' else [item['value']])]
                return [{**target, 'operator': 'IN', 'value': list(dict.fromkeys(values))}]
            if isinstance(node, exp.Between) and not node.args.get('symmetric'):
                name = field(node.this)
                return [{'field': name, 'operator': '>=', 'value': literal(node.args['low'])},
                        {'field': name, 'operator': '<=', 'value': literal(node.args['high'])}]
            if isinstance(node, exp.In) and not node.args.get('query'):
                return [{**predicate_target(node.this), 'operator': 'IN', 'value': [literal(v) for v in node.expressions]}]
            negated = isinstance(node, exp.Not)
            candidate = node.this if negated else node
            if isinstance(candidate, exp.Anonymous) and candidate.name.lower() == 'is_blank' and len(candidate.expressions) == 1:
                return [{'field': field(candidate.expressions[0]), 'operator': 'is_blank', 'value': not negated}]
            if isinstance(node, (exp.EQ, exp.NEQ)):
                left, right = node.this, node.expression
                if isinstance(left, exp.Literal):
                    left, right = right, left
                if (isinstance(left, exp.Anonymous) and left.name.lower() == 'is_blank'
                        and len(left.expressions) == 1):
                    # The registered deterministic helper returns exactly 0/1.
                    # Strings and other numbers are not Boolean declarations.
                    if (not isinstance(right, exp.Literal) or right.is_string
                            or right.this not in {'0', '1'}):
                        raise Unsupported('unsupported_blank_boolean')
                    value = right.this == '1'
                    if isinstance(node, exp.NEQ):
                        value = not value
                    return [{'field': field(left.expressions[0]), 'operator': 'is_blank', 'value': value}]
            operator = operations.get(type(node))
            if operator is None:
                raise Unsupported('unsupported_predicate')
            left, right = node.this, node.expression
            if isinstance(left, exp.Literal) and isinstance(right, exp.Column):
                left, right = right, left
                operator = {'>': '<', '>=': '<=', '<': '>', '<=': '>='}.get(operator, operator)
            target = predicate_target(left)
            if target.get('prefix_length') and operator != '=':
                raise Unsupported('date_prefix_operator')
            return [{**target, 'operator': operator, 'value': literal(right)}]

        conditions = predicates(tree.args['where'].this) if tree.args.get('where') else []
        companies = tuple(snapshot['company_ids'])
        periods = (set(map(tuple, snapshot['periods'])) if snapshot.get('periods') else
                   {(snapshot['year'], m) for m in range(1, 13)})
        lower, upper = date.min, date.max
        for condition in conditions:
            name, operator, value = condition['field'], condition['operator'], condition['value']
            if name == 'company_id':
                if operator not in {'=', 'IN'}:
                    raise Unsupported('company_operator_not_attributed')
                values = value if isinstance(value, list) else [value]
                companies = tuple(c for c in companies if c in values)
            if name != date_field:
                continue
            if condition.get('prefix_length'):
                length = condition['prefix_length']
                values = value if operator == 'IN' else [value]
                if not values:
                    raise Unsupported('empty_date_prefix')
                accepted = set()
                for prefix in values:
                    pattern = r'[0-9]{4}' if length == 4 else r'[0-9]{4}-[0-9]{2}'
                    if type(prefix) is not str or not re.fullmatch(pattern, prefix):
                        raise Unsupported('date_prefix_format')
                    y = int(prefix[:4])
                    m = 1 if length == 4 else int(prefix[5:])
                    date(y, m, 1)  # Reject invalid calendar components, never coerce.
                    accepted.update((y, month) for month in (range(1, 13) if length == 4 else (m,)))
                periods.intersection_update(accepted)
                continue
            if operator == 'LIKE':
                month = re.fullmatch(r'(\d{4})-(\d{2})-?%', value)
                year = re.fullmatch(r'(\d{4})-?%', value)
                if month:
                    y, m = map(int, month.groups()); lo = date(y, m, 1); hi = date(y + (m == 12), m % 12 + 1, 1)
                elif year:
                    y = int(year[1]); lo, hi = date(y, 1, 1), date(y + 1, 1, 1)
                else:
                    raise Unsupported('date_pattern')
                lower, upper = max(lower, lo), min(upper, hi)
            elif operator in {'=', '>', '>=', '<', '<='}:
                day = date.fromisoformat(value)
                if day.isoformat() != value:
                    raise Unsupported('date_format')
                if operator in {'=', '>='}: lower = max(lower, day)
                if operator == '>': lower = max(lower, day + timedelta(days=1))
                if operator in {'=', '<='}: upper = min(upper, day + timedelta(days=1))
                if operator == '<': upper = min(upper, day)
            else:
                raise Unsupported('date_operator')
        actual_periods = []
        for y, m in sorted(periods):
            lo, hi = date(y, m, 1), date(y + (m == 12), m % 12 + 1, 1)
            if lo < upper and hi > lower:
                actual_periods.append((y, m))
        if not companies or not actual_periods or lower >= upper:
            raise Unsupported('empty_scope_intersection')

        def attribution(node):
            if isinstance(node, exp.Column):
                name = field(node)
                return {'unit': 'cents' if name == 'amount_cents' else 'text', 'kind': 'column', 'field': name}
            if isinstance(node, exp.Substring):
                # ISO date prefixes are dimensions, never measures. Only the
                # business table's actual date column can establish a period.
                name = field(node.this)
                start, length = literal(node.args.get('start')), literal(node.args.get('length'))
                if name != date_field or start != 1 or length not in (4, 7):
                    raise Unsupported('unsupported_date_bucket')
                return {'unit': 'text', 'kind': 'date_bucket', 'field': name,
                        'granularity': 'year' if length == 4 else 'month'}
            if isinstance(node, exp.Window):
                if (node.args.get('partition_by') or node.args.get('order') or node.args.get('spec')
                        or node.args.get('alias') or tree.args.get('group') or tree.args.get('distinct')):
                    raise Unsupported('window_frame')
                return {**attribution(node.this), 'extent': 'filtered_set_before_pagination'}
            if isinstance(node, exp.Count) and isinstance(node.this, exp.Star) and not node.expressions:
                return {'unit': 'count', 'kind': 'count_rows'}
            if isinstance(node, exp.Count) and isinstance(node.this, exp.Column):
                return {'unit': 'count', 'kind': 'count_nonnull', 'field': field(node.this)}
            if isinstance(node, (exp.Min, exp.Max)) and isinstance(node.this, exp.Column):
                return {**attribution(node.this), 'kind': type(node).__name__.lower()}
            if isinstance(node, exp.Sum):
                if isinstance(node.this, exp.Column) and field(node.this) == 'amount_cents':
                    return {'unit': 'cents', 'kind': 'sum', 'field': 'amount_cents'}
                case = node.this
                if isinstance(case, exp.Case) and not case.this and len(case.args.get('ifs') or []) == 1:
                    branch = case.args['ifs'][0]
                    extra = predicates(branch.this)
                    if literal(case.args.get('default')) != 0:
                        raise Unsupported('conditional_sum_default')
                    value = branch.args['true']
                    if isinstance(value, exp.Column) and field(value) == 'amount_cents':
                        return {'unit': 'cents', 'kind': 'conditional_sum', 'field': 'amount_cents', 'conditions': extra}
                    if literal(value) == 1:
                        return {'unit': 'count', 'kind': 'conditional_count', 'conditions': extra}
            if isinstance(node, exp.Coalesce) and len(node.expressions) == 1 and literal(node.expressions[0]) == 0:
                return attribution(node.this)
            raise Unsupported('unattributed_projection')

        # Cardinality follows the AST, never whether an output value has units.
        # Unknown functions can be user-defined aggregates/row generators.
        def validate_projection(node):
            for part in node.walk():
                if isinstance(part, exp.Column):
                    if isinstance(part.this, exp.Star):
                        if part.table and part.table.lower() not in qualifiers:
                            raise Unsupported('unknown_column')
                    else:
                        field(part)
                if isinstance(part, exp.Anonymous):
                    # This exact deterministic helper already belongs to the
                    # snapshot runtime and predicate attribution contract.
                    if part.name.lower()!='is_blank' or len(part.expressions)!=1:
                        raise Unsupported('unknown_projection_function')
                    field(part.expressions[0])
                if isinstance(part, (exp.UDTF, exp.Explode, exp.GenerateSeries)):
                    raise Unsupported('row_expanding_projection')

        aggregate = any(isinstance(part, exp.AggFunc) and part.find_ancestor(exp.Window) is None
                        for expression in tree.expressions for part in expression.walk())
        window = any(expression.find(exp.Window) is not None for expression in tree.expressions)
        projected = []
        for expression in tree.expressions:
            node = expression.this if isinstance(expression, exp.Alias) else expression
            validate_projection(node)
            if isinstance(node, exp.Star) or isinstance(node, exp.Column) and isinstance(node.this, exp.Star):
                projected.extend({'name': name, **attribution(exp.column(name))} for name in fields)
            else:
                try:
                    meta = attribution(node)
                except Unsupported as error:
                    if not allow_partial_projection:
                        raise
                    if node.find(exp.Window) is not None:
                        raise Unsupported('unsupported_window_projection')
                    # Only the request-bound adapter may retain independently
                    # attributed columns and discard this unproved expression.
                    # WHERE, grouping and set completeness still need proof.
                    meta = {'kind':'unattributed','unit':None,'reason':str(error),
                            'row_effect':('aggregate' if any(isinstance(part,exp.AggFunc)
                                and part.find_ancestor(exp.Window) is None for part in node.walk()) else 'scalar')}
                projected.append({'name': expression.alias_or_name, **meta})
        if len(projected) != len(columns) or len(set(columns)) != len(columns):
            raise Unsupported('projection_columns')
        for meta, name in zip(projected, columns):
            meta['name'] = name
        dimension_kinds = {'column', 'date_bucket'}

        def dimension(meta):
            if meta['kind'] not in dimension_kinds:
                raise Unsupported('unsupported_group_expression')
            return (meta['kind'], meta['field'], meta.get('granularity'))

        groups = []
        for expression in tree.args['group'].expressions if tree.args.get('group') else ():
            if isinstance(expression, exp.Literal) and not expression.is_string:
                ordinal = literal(expression)
                if not 1 <= ordinal <= len(projected):
                    raise Unsupported('group_ordinal')
                meta = projected[ordinal - 1]
            elif (isinstance(expression, exp.Column) and not expression.table
                  and expression.name.lower() not in fields):
                # SQLite resolves a source field before a same-named alias.
                aliases = [p for p in projected if p['name'].lower() == expression.name.lower()]
                if len(aliases) != 1:
                    raise Unsupported('group_alias')
                meta = aliases[0]
            else:
                meta = attribution(expression)
            groups.append(dimension(meta))
        projection_complete = all(p['kind'] != 'unattributed' for p in projected)
        distinct = bool(tree.args.get('distinct'))
        if distinct and not projection_complete:
            # Dropping an output expression must not conceal DISTINCT's row key.
            raise Unsupported('partial_distinct_projection')
        def constant_dimension(meta):
            # A bare source column in an aggregate is deterministic only when
            # an attributed raw equality fixes its value. Do not infer this
            # from returned rows, labels, or an arbitrary representative row.
            if meta['kind'] != 'column':
                return False
            for condition in conditions:
                if (condition.get('field') != meta['field'] or condition.get('transform')
                        or condition.get('prefix_length')):
                    continue
                values = ([condition['value']] if condition['operator'] == '=' else
                          condition['value'] if condition['operator'] == 'IN' else [])
                if not values or len(set(values)) != 1:
                    continue
                value = values[0]
                if type(value) is (int if meta['field'] == 'amount_cents' else str):
                    meta['constant_evidence'] = dict(condition)
                    return True
            return False

        if (aggregate or groups) and any(dimension(p) not in groups and not constant_dimension(p)
                                         for p in projected if p['kind'] in dimension_kinds):
            raise Unsupported('ungrouped_column')
        filters = (tree.args['where'].this.sql(dialect='sqlite'),) if tree.args.get('where') else ()
        return {**base, 'status': 'VERIFIED', 'scope': {'company_ids': companies, 'periods': tuple(actual_periods)},
                'conditions': conditions, 'filters': filters, 'date_field': date_field, 'table': table_name,
                'columns': projected, 'limited': bool(tree.args.get('limit') or tree.args.get('offset')),
                'projection_complete':projection_complete,
                'row_shape':('distinct' if distinct else 'grouped' if groups else
                             'aggregate' if aggregate else 'window' if window else 'detail'),
                'row_shape_evidence':{'has_aggregate':aggregate,'has_window':window,'has_distinct':distinct,
                                      'preserves_filtered_source_rows':not bool(aggregate or groups or distinct)},
                'query_set_complete': not bool(tree.args.get('limit') or tree.args.get('offset'))}
    except (Unsupported, ValueError, TypeError, OverflowError, sqlglot.errors.ParseError) as error:
        return {**base, 'reason': str(error)}
