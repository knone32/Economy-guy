"""从官方 Excel 导入 Stage 0 模拟数据库。"""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import os
import re
import tempfile
from openpyxl import load_workbook
from .database import connect, create_schema


class ImportError(ValueError):
    """Excel 结构或数据不符合预期时抛出。"""


def _cents(value: object) -> int:
    """用 Decimal 转换元到分，避免 float 金额累计。"""
    try:
        return int((Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) * 100)
    except Exception as error:
        raise ImportError(f"金额无效：{value!r}") from error


def _date_text(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise ImportError(f"日期无效：{value!r}")


def _rows_after_header(sheet, required_headers: set[str]):
    """按实际表头找到数据区域，跳过标题、说明和空行。"""
    header_row, headers = None, None
    for index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        values = list(row)
        if required_headers.issubset({v for v in values if isinstance(v, str)}):
            header_row, headers = index, values
            break
    if not header_row:
        raise ImportError(f"工作表 {sheet.title} 缺少表头：{sorted(required_headers)}")
    mapping = {value: index for index, value in enumerate(headers) if value is not None}
    for values in sheet.iter_rows(min_row=header_row + 1, values_only=True):
        if values[0] is None:
            if any(v is not None for v in values):
                raise ImportError(f"工作表 {sheet.title} 存在无企业编号的数据行")
            break
        if not all(values[mapping[h]] is not None for h in required_headers):
            raise ImportError(f"工作表 {sheet.title} 数据行缺少必需字段")
        yield {header: values[index] for header, index in mapping.items()}


def _import_database(excel_path: str | Path, database_path: str | Path) -> dict[str, int]:
    """仅向调用者创建的临时数据库导入。"""
    excel_path, database_path = Path(excel_path), Path(database_path)
    if not excel_path.is_file():
        raise FileNotFoundError(f"找不到 Excel 文件：{excel_path}")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = load_workbook(excel_path, data_only=True, read_only=True)
    required = {"企业与用户", "发票", "银行流水"}
    if not required.issubset(set(workbook.sheetnames)):
        workbook.close()
        raise ImportError(f"Excel 缺少工作表：{sorted(required - set(workbook.sheetnames))}")
    connection = connect(database_path)
    try:
        create_schema(connection)
        company_sheet = workbook["企业与用户"]
        # 企业和权限的表格结构已由资料确认，仍从 Excel 单元格取得实际名称和权限。
        company_rows = list(_rows_after_header(company_sheet, {"企业编号", "企业名称", "常用简称"}))
        companies = [(r["企业编号"], r["企业名称"], r["常用简称"]) for r in company_rows]
        user_header = next(i for i, row in enumerate(company_sheet.iter_rows(values_only=True), 1) if row[0] == "用户编号")
        headers = next(company_sheet.iter_rows(min_row=user_header, max_row=user_header, values_only=True))
        company_ids = {row[0] for row in companies}
        permission_columns = []
        for index, header in enumerate(headers[2:], 2):
            match = re.search(r"[（(]([^（）()]+)[）)]", str(header))
            if not match or match[1] not in company_ids:
                raise ImportError("权限列无法关联企业")
            permission_columns.append((index, match[1]))
        user_rows = []
        for row in company_sheet.iter_rows(min_row=user_header + 1, values_only=True):
            if not row[0]:
                break
            user_rows.append(row)
        connection.executemany("INSERT INTO companies (company_id,name,short_name) VALUES (?, ?, ?)", companies)
        connection.executemany("INSERT INTO users (user_id,name) VALUES (?, ?)", [(r[0], r[1]) for r in user_rows])
        permissions = []
        for row in user_rows:
            user_id = row[0]
            for index, company_id in permission_columns:
                description = row[index]
                if description not in {"无权访问", "仅查看", "可查看并修改"}:
                    raise ImportError("未知权限描述，拒绝导入")
                permissions.append((user_id, company_id, int(description != "无权访问"), int(description == "可查看并修改")))
        connection.executemany("INSERT INTO permissions (user_id,company_id,can_read,can_modify) VALUES (?, ?, ?, ?)", permissions)

        invoice_rows = list(_rows_after_header(workbook["发票"], {"企业编号", "发票编号", "开票日期", "价税合计（元）"}))
        connection.executemany(
            "INSERT INTO invoices (company_id,invoice_no,invoice_date,seller_name,item_name,amount_cents,purpose,remark) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(r["企业编号"], r["发票编号"], _date_text(r["开票日期"]), r["销售方名称"], r["项目名称（票面）"], _cents(r["价税合计（元）"]), r["用途"], r["备注"]) for r in invoice_rows],
        )
        bank_rows = list(_rows_after_header(workbook["银行流水"], {"企业编号", "流水编号", "交易日期", "收支方向", "金额（元）"}))
        connection.executemany(
            "INSERT INTO bank_transactions (company_id,transaction_no,transaction_date,direction,amount_cents,counterparty_name,remark) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(r["企业编号"], r["流水编号"], _date_text(r["交易日期"]), r["收支方向"], _cents(r["金额（元）"]), r["对方名称"], r["备注"]) for r in bank_rows],
        )
        connection.commit()
        for table, expected in (("companies", len(companies)), ("users", len(user_rows)),
                                ("invoices", len(invoice_rows)), ("bank_transactions", len(bank_rows))):
            # 表名来自内部常量；外部输入不参与 SQL 结构。
            if connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] != expected:
                raise ImportError("数据库记录数核对失败")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ImportError("数据库完整性核对失败")
        # 使用本簿说明中的核对数量和金额，防止漏导或截断表格。
        if "说明" not in workbook.sheetnames:
            raise ImportError("缺少说明表，无法核对导入")
        checked = 0
        for row in workbook["说明"].iter_rows(values_only=True):
            if len(row) < 7 or not isinstance(row[1], (date, datetime)):
                continue
            prefix = _date_text(row[1])[:7] + "%"
            company = row[0]
            invoice = connection.execute("SELECT COUNT(*),COALESCE(SUM(amount_cents),0) FROM invoices WHERE company_id=? AND invoice_date LIKE ?", (company, prefix)).fetchone()
            bank = connection.execute("SELECT COUNT(*) FROM bank_transactions WHERE company_id=? AND transaction_date LIKE ?", (company, prefix)).fetchone()[0]
            amounts = {}
            for direction in ("支出", "收入"):
                amounts[direction] = connection.execute("SELECT COALESCE(SUM(amount_cents),0) FROM bank_transactions WHERE company_id=? AND transaction_date LIKE ? AND direction=?", (company, prefix, direction)).fetchone()[0]
            if (invoice[0], bank, invoice[1], amounts["支出"], amounts["收入"]) != (row[2], row[3], _cents(row[4]), _cents(row[5]), _cents(row[6])):
                raise ImportError("导入结果与Excel核对值不一致")
            checked += 1
        if not checked:
            raise ImportError("说明表没有可读取的核对值")
    finally:
        # Windows 上未关闭连接会锁住 .db，阻碍重复初始化和测试清理。
        connection.close()
        workbook.close()
    return {"companies": len(companies), "users": len(user_rows), "invoices": len(invoice_rows), "bank_transactions": len(bank_rows)}


def initialize_database(excel_path: str | Path, database_path: str | Path) -> dict[str, int]:
    """临时库全部导入成功才发布；已有文件默认拒绝覆盖。"""
    target = Path(database_path).resolve()
    if target.exists():
        raise FileExistsError("数据库已存在，拒绝覆盖；请指定新的数据库路径")
    # 先检查完整输入结构和必需单元格，再创建隔离数据库。
    with_input = load_workbook(excel_path, read_only=True, data_only=True)
    try:
        checks = {"企业与用户": {"企业编号", "企业名称", "常用简称"},
                  "发票": {"企业编号", "发票编号", "开票日期", "销售方名称", "项目名称（票面）", "价税合计（元）", "用途", "备注"},
                  "银行流水": {"企业编号", "流水编号", "交易日期", "收支方向", "金额（元）", "对方名称", "备注"}}
        for sheet, headers in checks.items():
            if sheet not in with_input.sheetnames:
                raise ImportError("缺少工作表：" + sheet)
            # 可空用途/备注只校验表头，其余行校验由导入器完成。
            actual = {v for row in with_input[sheet].iter_rows(values_only=True) for v in row if isinstance(v, str)}
            if not headers.issubset(actual):
                raise ImportError("缺少字段：" + sheet)
    finally:
        with_input.close()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix="finance-import-", suffix=".db", dir=target.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        counts = _import_database(excel_path, temporary)
        # 硬链接原子发布且不会覆盖并发创建的目标。
        os.link(temporary, target)
        return counts
    finally:
        temporary.unlink()
