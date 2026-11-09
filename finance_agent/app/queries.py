"""带权限的只读业务查询。"""
import sqlite3
from .permissions import check_permission


class QueryError(ValueError):
    """调用参数、权限或查询对象不正确。"""


def _check_month(year: int, month: int) -> str:
    if not isinstance(year, int) or not 1 <= year <= 9999 or not isinstance(month, int) or not 1 <= month <= 12:
        raise QueryError("年份必须为 1 到 9999 的整数，月份必须是 1 到 12")
    return f"{year:04d}-{month:02d}"


def _year_prefix(year):
    if type(year) is not int or not 1 <= year <= 9999:
        raise QueryError("年份必须为 1 到 9999 的整数")
    return f"{year:04d}-%"


def _authorize(connection: sqlite3.Connection, user_id: str, company_id: str) -> None:
    if not user_id or not company_id:
        raise QueryError("用户编号和企业编号不能为空")
    result = check_permission(connection, user_id, company_id, "read")
    if not result.allowed:
        raise QueryError(f"查询被拒绝：{result.reason}")


def _invoice_dict(row: sqlite3.Row) -> dict:
    return {"company_id": row["company_id"], "invoice_no": row["invoice_no"], "invoice_date": row["invoice_date"], "seller_name": row["seller_name"], "item_name": row["item_name"], "amount": _money(row["amount_cents"]), "purpose": row["purpose"], "remark": row["remark"]}


def _money(cents: int) -> str:
    yuan, remainder = divmod(abs(cents), 100)
    sign = "-" if cents < 0 else ""
    return f"{sign}{yuan}.{remainder:02d}"


def available_periods(connection, user_id, company_id):
    """Current monthly counts from both authorized business tables."""
    _authorize(connection, user_id, company_id)
    rows = connection.execute("""
        WITH activity AS (
            SELECT substr(invoice_date,1,7) AS period, count(*) AS invoices, 0 AS bank
              FROM invoices WHERE company_id=? GROUP BY period
            UNION ALL
            SELECT substr(transaction_date,1,7), 0, count(*)
              FROM bank_transactions WHERE company_id=? GROUP BY 1
        )
        SELECT period, sum(invoices), sum(bank) FROM activity GROUP BY period ORDER BY period DESC
    """, (company_id, company_id))
    return [tuple(row) for row in rows]


INVOICE_PAGE_SIZE = 10
_INVOICE_ORDER = {
    ("date", "asc"): "invoice_date ASC, invoice_no ASC",
    ("date", "desc"): "invoice_date DESC, invoice_no ASC",
    ("amount", "asc"): "amount_cents ASC, invoice_date ASC, invoice_no ASC",
    ("amount", "desc"): "amount_cents DESC, invoice_date ASC, invoice_no ASC",
}
# Match Python str.strip() for invoice purposes, including full-width spaces.
PURPOSE_WHITESPACE = "".join(chr(code) for code in range(0x3001) if chr(code).isspace())


def invoice_directory(connection, user_id, company_id, year, month, page, sort_by="date", sort_order="asc"):
    """A stable, bounded invoice directory with a count from the same transaction."""
    _authorize(connection, user_id, company_id)
    filters = "company_id = ?"
    values = [company_id]
    if (year, month) != (0, 0):
        filters += " AND invoice_date LIKE ?"
        values.append(_year_prefix(year) if month == 0 else _check_month(year, month) + "%")
    data = _invoice_page(connection, company_id, filters, values, page, sort_by=sort_by, sort_order=sort_order)
    return {**data, "sort_by": sort_by, "sort_order": sort_order}


def list_annual_blank_purpose(connection, user_id, company_id, year, page):
    """筛选用途字段的当前值，独立于必填规则。"""
    _authorize(connection, user_id, company_id)
    return _invoice_page(connection, company_id,
                         "company_id=? AND invoice_date LIKE ? AND trim(coalesce(purpose,''),?)=''",
                         [company_id, _year_prefix(year), PURPOSE_WHITESPACE], page)


def _page_offset(page):
    if type(page) is not int or not 1 <= page <= 2_147_483_647:
        raise QueryError("页码超出范围")
    return (page - 1) * INVOICE_PAGE_SIZE


def _invoice_page(connection, company_id, filters, values, page, *, sort_by="date", sort_order="asc"):
    if type(sort_by) is not str or type(sort_order) is not str or (sort_by, sort_order) not in _INVOICE_ORDER:
        raise QueryError("发票目录排序参数不受支持")
    order = _INVOICE_ORDER[sort_by, sort_order]
    offset = _page_offset(page)
    total = connection.execute(f"SELECT count(*) FROM invoices WHERE {filters}", values).fetchone()[0]
    rows = connection.execute(
        f"""SELECT invoice_no, invoice_date, amount_cents, purpose
              FROM invoices WHERE {filters} ORDER BY {order} LIMIT ? OFFSET ?""",
        [*values, INVOICE_PAGE_SIZE, offset],
    )
    return {"total": total, "page": page, "page_size": INVOICE_PAGE_SIZE,
            "rows": [{"company_id": company_id, "invoice_no": row["invoice_no"],
                      "invoice_date": row["invoice_date"], "amount": _money(row["amount_cents"]),
                      "has_purpose": bool((row["purpose"] or "").strip())} for row in rows]}


def list_invoices(connection, user_id: str, company_id: str, year: int, month: int) -> list[dict]:
    """查询指定企业、年月的发票，结果为空是正常成功结果。"""
    prefix = _check_month(year, month); _authorize(connection, user_id, company_id)
    rows = connection.execute("SELECT * FROM invoices WHERE company_id = ? AND invoice_date LIKE ? ORDER BY invoice_date, invoice_no", (company_id, prefix + "%")).fetchall()
    return [_invoice_dict(row) for row in rows]


def get_invoice(connection, user_id: str, company_id: str, invoice_no: str) -> dict | None:
    """以企业编号和发票编号共同定位发票，防止跨企业读取。"""
    _authorize(connection, user_id, company_id)
    if not invoice_no:
        raise QueryError("发票编号不能为空")
    row = connection.execute("SELECT * FROM invoices WHERE company_id = ? AND invoice_no = ?", (company_id, invoice_no)).fetchone()
    return _invoice_dict(row) if row else None


def list_missing_purpose_invoices(connection, user_id: str, company_id: str, year: int, month: int) -> list[dict]:
    """列出用途为空或只含空白字符的发票，不做修改。"""
    prefix = _check_month(year, month); _authorize(connection, user_id, company_id)
    rows = connection.execute("SELECT * FROM invoices WHERE company_id = ? AND invoice_date LIKE ? AND (purpose IS NULL OR trim(purpose) = '') ORDER BY invoice_date, invoice_no", (company_id, prefix + "%")).fetchall()
    return [_invoice_dict(row) for row in rows]


def list_bank_transactions(connection, user_id: str, company_id: str, year: int, month: int) -> list[dict]:
    """查询指定企业、年月的银行流水，所有字段只读。"""
    prefix = _check_month(year, month); _authorize(connection, user_id, company_id)
    rows = connection.execute("SELECT * FROM bank_transactions WHERE company_id = ? AND transaction_date LIKE ? ORDER BY transaction_date, transaction_no", (company_id, prefix + "%")).fetchall()
    return [_bank_row(row) for row in rows]


def list_annual_bank_income(connection, user_id, company_id, year, page):
    _authorize(connection, user_id, company_id)
    offset = _page_offset(page)
    values = (company_id, _year_prefix(year))
    filters = "company_id=? AND transaction_date LIKE ? AND direction='收入'"
    total = connection.execute(f"SELECT count(*) FROM bank_transactions WHERE {filters}", values).fetchone()[0]
    rows = connection.execute(f"""SELECT * FROM bank_transactions WHERE {filters}
        ORDER BY transaction_date, transaction_no LIMIT ? OFFSET ?""", (*values, INVOICE_PAGE_SIZE, offset))
    return {"total": total, "page": page, "page_size": INVOICE_PAGE_SIZE,
            "rows": [_bank_row(row) for row in rows]}


def _bank_row(row):
    return {"company_id": row["company_id"], "transaction_no": row["transaction_no"],
            "transaction_date": row["transaction_date"], "direction": row["direction"],
            "amount": _money(row["amount_cents"]), "counterparty_name": row["counterparty_name"],
            "remark": row["remark"]}
