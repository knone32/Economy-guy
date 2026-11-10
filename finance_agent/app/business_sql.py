"""Bounded, permission-scoped SQLite snapshots for model-authored reads."""
from contextlib import closing
from decimal import Decimal
import json
import math
import re
import sqlite3
from time import monotonic

from .permissions import check_permission
from .provenance import SOURCES, ScopeProof
from .queries import _money
from .stage2_schema import open_existing


# The projection names and declarations below are fixed application SQL.
TABLES = {
    "invoices": ("company_id TEXT, invoice_no TEXT, invoice_date TEXT, seller_name TEXT, "
                 "item_name TEXT, amount_cents INTEGER, purpose TEXT, remark TEXT"),
    "bank_transactions": ("company_id TEXT, transaction_no TEXT, transaction_date TEXT, direction TEXT, "
                          "amount_cents INTEGER, counterparty_name TEXT, remark TEXT"),
}
FUNCTIONS = frozenset("""
    abs avg coalesce count dense_rank glob ifnull instr is_blank length like lower ltrim
    max min nullif rank replace round row_number rtrim substr substring sum trim typeof upper
""".split())
MAX_SOURCE_ROWS = 4000
MAX_SOURCE_BYTES = 2_000_000
MAX_CELL_BYTES = 16_384
MAX_RESULT_ROWS = 30
MAX_RESULT_BYTES = 10_000
MAX_SQL_BYTES = 4096
_QUERY = re.compile(r"\s*(?:SELECT|WITH)\b", re.I)
_KEY_QUERY = re.compile(r"\s*SELECT\s+company_id\s*,\s*invoice_no\s+FROM\s+invoices(?=\s|;|$)", re.I)
_PARTIAL_QUERY = re.compile(r"\b(?:LIMIT|OFFSET|GROUP|HAVING|WINDOW|UNION|INTERSECT|EXCEPT)\b", re.I)
_AGGREGATES = {"avg", "count", "min", "max", "sum", "dense_rank", "rank", "row_number"}


class BusinessSQLError(ValueError):
    def __init__(self, status, message, *, missing=()):
        super().__init__(message)
        self.status = status
        self.missing = missing


def _authorizer(action, table, field, database, _context):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and database in {"main", None} and table in TABLES:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and field in FUNCTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _scope(proof, actor):
    if not isinstance(proof, ScopeProof) or proof.actor != actor:
        raise BusinessSQLError("DENIED", "当前查询没有可信会话身份")
    workspace = proof.read_workspace or {}

    def trusted(key):
        if key in workspace:
            return workspace[key]
        return proof.values.get(key, ()) if proof.sources.get(key) in SOURCES else ()

    companies = tuple(sorted(set(trusted("company_id"))))
    periods = tuple(sorted(set(trusted("periods"))))
    annual_year = proof.annual_year
    missing = []
    if not companies:
        missing.append("company_id")
    if annual_year is None and not periods:
        date_fields = [key for key in ("year", "month") if not trusted(key)]
        missing.extend(date_fields or ("year", "month"))
    if missing:
        raise BusinessSQLError("AMBIGUOUS", "请补充可信企业和年月，或明确完整年度", missing=missing)

    if (annual_year is not None and not 1 <= annual_year <= 9999
            or any(not 1 <= year <= 9999 or not 1 <= month <= 12 for year, month in periods)):
        raise BusinessSQLError("SCOPE_MISMATCH", "请提供有效的年份和月份")
    if annual_year is None and len(companies) > 1 and len(periods) > 1:
        raise BusinessSQLError("SCOPE_MISMATCH", "多家企业涉及不同账期，请按一个共同账期或分企业查询")
    scope = {"company_ids": companies}
    if annual_year is not None:
        scope["year"] = annual_year
    else:
        scope["periods"] = periods
    if len(companies) == 1:
        scope["company_id"] = companies[0]
    if annual_year is None and len(periods) == 1:
        scope["year"], scope["month"] = periods[0]
    return scope


class BusinessSQL:
    """One lazy in-memory snapshot owned by a single Agent turn."""

    def __init__(self, path, actor, proof):
        self.path, self.actor, self.proof = path, actor, proof
        self.connection = None

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def scope(self):
        return _scope(self.proof, self.actor)

    def _check_access(self, source, scope):
        if any(not check_permission(source, self.actor, company, "read").allowed for company in scope["company_ids"]):
            raise BusinessSQLError("DENIED", "当前账号没有所请求企业的读取权限")

    def _snapshot(self, scope):
        with closing(open_existing(self.path, readonly=True)) as source:
            source.execute("BEGIN")
            self._check_access(source, scope)
            if self.connection is not None:
                return self.connection

            memory = sqlite3.connect(":memory:", cached_statements=0)
            try:
                memory.execute("PRAGMA temp_store=MEMORY")
                source.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_CELL_BYTES)
                deadline = monotonic() + 2
                source.set_progress_handler(lambda: monotonic() > deadline, 1000)
                companies = scope["company_ids"]
                dates = ([f"{scope['year']:04d}-"] if "periods" not in scope else
                         [f"{year:04d}-{month:02d}-" for year, month in scope["periods"]])
                rows_left, bytes_left = MAX_SOURCE_ROWS, MAX_SOURCE_BYTES
                for table, schema in TABLES.items():
                    columns = tuple(column.split()[0] for column in schema.split(", "))
                    date_column = columns[2]
                    # Company and dates are bound values, never model SQL.
                    company_params = ",".join("?" for _ in companies)
                    date_params = ",".join("?" for _ in dates)
                    cursor = source.execute(
                        f"SELECT {', '.join(columns)} FROM {table} WHERE company_id IN ({company_params}) "
                        f"AND substr({date_column},1,?) IN ({date_params}) LIMIT ?",
                        (*companies, len(dates[0]), *dates, rows_left + 1),
                    )
                    memory.execute(f"CREATE TABLE {table} ({schema})")
                    placeholders = ",".join("?" for _ in columns)
                    for row in cursor:
                        rows_left -= 1
                        bytes_left -= sum(len(value.encode("utf-8")) if isinstance(value, str) else
                                          len(value) if isinstance(value, bytes) else 8 for value in row)
                        if rows_left < 0 or bytes_left < 0:
                            raise BusinessSQLError("SQL_SCOPE_LIMIT", "查询范围数据过大，请缩小企业或账期")
                        memory.execute(f"INSERT INTO {table} VALUES ({placeholders})", tuple(row))
                memory.commit()
                memory.create_function("is_blank", 1, lambda value: value is None or not str(value).strip(),
                                       deterministic=True)
                memory.execute("PRAGMA query_only=ON")
                memory.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_CELL_BYTES)
                memory.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_SQL_BYTES)
                memory.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 48)
                memory.set_authorizer(_authorizer)
            except BaseException:
                memory.close()
                raise
            self.connection = memory
            return memory

    def query(self, sql):
        if len(sql.encode("utf-8")) > MAX_SQL_BYTES or not _QUERY.match(sql):
            raise BusinessSQLError("SQL_REJECTED", "请输入一条 SELECT 或只读 WITH 查询")
        scope = self.scope()
        try:
            db = self._snapshot(scope)
        except sqlite3.Error as error:
            if getattr(error, "sqlite_errorcode", None) in {sqlite3.SQLITE_TOOBIG, sqlite3.SQLITE_INTERRUPT}:
                raise BusinessSQLError("SQL_SCOPE_LIMIT", "查询范围数据过大，请缩小企业或账期") from None
            raise BusinessSQLError("ERROR", "无法读取当前账簿快照") from None

        deadline = monotonic() + 0.4
        steps = 0

        def stop():
            nonlocal steps
            steps += 1000
            return steps >= 250_000 or monotonic() > deadline

        reads, functions = set(), set()
        selects = 0

        def authorize(action, table, field, database, context):
            nonlocal selects
            allowed = _authorizer(action, table, field, database, context)
            if action == sqlite3.SQLITE_READ and allowed == sqlite3.SQLITE_OK:
                reads.add(table)
            elif action == sqlite3.SQLITE_SELECT:
                selects += 1
            elif action == sqlite3.SQLITE_FUNCTION:
                functions.add(field)
            return allowed

        db.set_authorizer(authorize)
        db.set_progress_handler(stop, 1000)
        try:
            with closing(db.execute(sql)) as cursor:
                if not reads:
                    raise BusinessSQLError("SQL_REJECTED", "查询必须读取至少一张业务投影表")
                columns = [column[0] for column in cursor.description]
                rows, derived, truncated = _bounded_rows(cursor, columns)
        except sqlite3.Error as error:
            if getattr(error, "sqlite_errorcode", None) in {sqlite3.SQLITE_INTERRUPT, sqlite3.SQLITE_TOOBIG}:
                raise BusinessSQLError("SQL_QUERY_LIMIT", "SQL 超过执行资源上限，请简化查询") from None
            raise BusinessSQLError("SQL_REJECTED", "SQL 无效或包含未获准的操作、表或函数") from None
        finally:
            db.set_progress_handler(None, 0)
        data = {"sql": sql, "columns": columns, "rows": rows, "row_count": len(rows),
                "truncated": truncated, "derived": derived}
        # The selectable form projects original keys directly, without aliases,
        # aggregation, subqueries or paging. General SQL still returns read results.
        keys = ()
        if (rows and not truncated and columns == ["company_id", "invoice_no"]
                and selects == 1 and reads == {"invoices"} and not functions & _AGGREGATES
                and _KEY_QUERY.match(sql) and not _PARTIAL_QUERY.search(sql)):
            keys = tuple(rows)
            placeholders = ",".join("(?,?)" for _ in keys)
            dates = db.execute(
                f"SELECT company_id, invoice_date FROM invoices WHERE (company_id, invoice_no) IN (VALUES {placeholders})",
                tuple(value for key in keys for value in key),
            )
            actual = sorted({(company, day[:7]) for company, day in dates})
            data["selection_scope"] = [{"company_id": company, "period": period} for company, period in actual]
        return scope, data, keys


def _bounded_rows(cursor, columns):
    rows, derived = [], []
    remaining = MAX_RESULT_BYTES - len(json.dumps(columns, ensure_ascii=False).encode("utf-8"))
    indexes = {name: i for i, name in enumerate(columns)}
    ratio = ("numerator" in indexes and "denominator" in indexes
             and columns.count("numerator") == columns.count("denominator") == 1)
    for row in cursor:
        if len(rows) == MAX_RESULT_ROWS:
            return rows, derived, True
        if any(isinstance(value, bytes) or (isinstance(value, float) and not math.isfinite(value)) for value in row):
            raise BusinessSQLError("SQL_REJECTED", "请返回有限数值或文本，二进制结果不受支持")
        display = {str(i): _money(value) for i, (name, value) in enumerate(zip(columns, row))
                   if name.endswith("_cents") and type(value) is int}
        if ratio:
            n, d = row[indexes["numerator"]], row[indexes["denominator"]]
            if type(n) is int and type(d) is int:
                display["percentage"] = f"{Decimal(n) * 100 / Decimal(d):.2f}%" if d else None
        remaining -= len(json.dumps((row, display), ensure_ascii=False).encode("utf-8"))
        if remaining < 0:
            if not rows:
                raise BusinessSQLError("SQL_QUERY_LIMIT", "单行结果超过展示上限，请减少投影字段")
            return rows, derived, True
        rows.append(row)
        derived.append(display)
    return rows, derived, False
