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


def describe(sql, columns, snapshot, tables, reads):
    base = {'scope': None, 'filters': (), 'conditions': [], 'columns': [],
            'sql_sha256': hashlib.sha256(sql.encode()).hexdigest(), 'status': 'UNKNOWN'}
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
        def predicates(node):
            if isinstance(node, exp.Paren):
                return predicates(node.this)
            if isinstance(node, exp.And):
                return predicates(node.this) + predicates(node.expression)
            if isinstance(node, exp.Between) and not node.args.get('symmetric'):
                name = field(node.this)
                return [{'field': name, 'operator': '>=', 'value': literal(node.args['low'])},
                        {'field': name, 'operator': '<=', 'value': literal(node.args['high'])}]
            if isinstance(node, exp.In) and not node.args.get('query'):
                return [{'field': field(node.this), 'operator': 'IN', 'value': [literal(v) for v in node.expressions]}]
            negated = isinstance(node, exp.Not)
            candidate = node.this if negated else node
            if isinstance(candidate, exp.Anonymous) and candidate.name.lower() == 'is_blank' and len(candidate.expressions) == 1:
                return [{'field': field(candidate.expressions[0]), 'operator': 'is_blank', 'value': not negated}]
            operator = operations.get(type(node))
            if operator is None:
                raise Unsupported('unsupported_predicate')
            left, right = node.this, node.expression
            if isinstance(left, exp.Literal) and isinstance(right, exp.Column):
                left, right = right, left
                operator = {'>': '<', '>=': '<=', '<': '>', '<=': '>='}.get(operator, operator)
            return [{'field': field(left), 'operator': operator, 'value': literal(right)}]

        conditions = predicates(tree.args['where'].this) if tree.args.get('where') else []
        date_field = 'invoice_date' if table_name == 'invoices' else 'transaction_date'
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

        projected = []
        for expression in tree.expressions:
            node = expression.this if isinstance(expression, exp.Alias) else expression
            if isinstance(node, exp.Star) or isinstance(node, exp.Column) and isinstance(node.this, exp.Star):
                projected.extend({'name': name, **attribution(exp.column(name))} for name in fields)
            else:
                projected.append({'name': expression.alias_or_name, **attribution(node)})
        if len(projected) != len(columns) or len(set(columns)) != len(columns):
            raise Unsupported('projection_columns')
        for meta, name in zip(projected, columns):
            meta['name'] = name
        groups = [field(v) for v in tree.args['group'].expressions] if tree.args.get('group') else []
        aggregate = any(p['kind'] != 'column' and not p.get('extent') for p in projected)
        if aggregate and any(p['field'] not in groups for p in projected if p['kind'] == 'column'):
            raise Unsupported('ungrouped_column')
        filters = (tree.args['where'].this.sql(dialect='sqlite'),) if tree.args.get('where') else ()
        return {**base, 'status': 'VERIFIED', 'scope': {'company_ids': companies, 'periods': tuple(actual_periods)},
                'conditions': conditions, 'filters': filters, 'date_field': date_field, 'table': table_name,
                'columns': projected, 'limited': bool(tree.args.get('limit') or tree.args.get('offset')),
                'query_set_complete': not bool(tree.args.get('limit') or tree.args.get('offset'))}
    except (Unsupported, ValueError, TypeError, OverflowError, sqlglot.errors.ParseError) as error:
        return {**base, 'reason': str(error)}
