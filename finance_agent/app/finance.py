"""从当前数据库计算精确金额汇总。"""
from .queries import QueryError, _authorize, _check_month, _money
from .queries import list_invoices, list_bank_transactions


def get_finance_summary(connection, user_id: str, company_id: str, year: int, month: int) -> dict:
    """同一数据库快照中读取各项金额和记录计数。"""
    invoices = list_invoices(connection, user_id, company_id, year, month)
    bank = list_bank_transactions(connection, user_id, company_id, year, month)
    return {
        "invoice_total": invoice_total(connection, user_id, company_id, year, month),
        "bank_income_total": bank_income_total(connection, user_id, company_id, year, month),
        "bank_expense_total": bank_expense_total(connection, user_id, company_id, year, month),
        "invoice_count": len(invoices),
        "bank_income_count": sum(r["direction"] == "收入" for r in bank),
        "bank_expense_count": sum(r["direction"] == "支出" for r in bank),
    }


def _total(connection, user_id: str, company_id: str, year: int, month: int, table: str, date_column: str, direction: str | None = None) -> str:
    prefix = _check_month(year, month); _authorize(connection, user_id, company_id)
    sql = f"SELECT COALESCE(SUM(amount_cents), 0) AS cents FROM {table} WHERE company_id = ? AND {date_column} LIKE ?"
    values = [company_id, prefix + "%"]
    if direction:
        sql += " AND direction = ?"; values.append(direction)
    cents = connection.execute(sql, values).fetchone()["cents"]
    return _money(cents)


def invoice_total(connection, user_id: str, company_id: str, year: int, month: int) -> str:
    """按价税合计计算发票总额。"""
    return _total(connection, user_id, company_id, year, month, "invoices", "invoice_date")


def bank_income_total(connection, user_id: str, company_id: str, year: int, month: int) -> str:
    """仅统计收入，不与支出抵销。"""
    return _total(connection, user_id, company_id, year, month, "bank_transactions", "transaction_date", "收入")


def bank_expense_total(connection, user_id: str, company_id: str, year: int, month: int) -> str:
    """仅统计支出，不从收入中相减。"""
    return _total(connection, user_id, company_id, year, month, "bank_transactions", "transaction_date", "支出")
