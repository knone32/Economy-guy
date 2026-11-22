"""Convert the fixed Word/CSV import forms into the official four-sheet workbook input.

The GUI import entry accepts the original ``.xlsx`` workbook, one ``.docx``
document that carries the four fixed sheets as headings plus tables, or exactly
four CSV files named after the four official worksheets.  This module only
adapts those two forms into the same workbook bytes that the existing
``cli_workspaces.import_workspace`` already validates; it never opens, creates,
publishes or replaces a database.

The accepted Word/CSV layout is deliberately fixed and strict:

* Word: four Word heading-styled paragraphs named 企业与用户 / 发票 / 银行流水 /
  说明, each immediately followed by exactly one table.  No other body text,
  table, merged cell or nested table is accepted.  (Old .doc, scanned or
  free-text documents therefore fail closed.)
* CSV: exactly four UTF-8 (BOM allowed) comma-separated files named
  企业与用户.csv / 发票.csv / 银行流水.csv / 说明.csv, with standard quoting.
* Fields are the official worksheet fields, in order; no column inference or
  default values are added.  Dates, counts and amounts are type-checked with a
  file/table/row location so the caller can show the concrete failure.
"""
from __future__ import annotations

import base64
import binascii
import csv
import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from openpyxl import Workbook


COMPANIES = "企业与用户"
INVOICES = "发票"
BANK = "银行流水"
NOTES = "说明"
SHEET_ORDER = (COMPANIES, INVOICES, BANK, NOTES)
CSV_FILENAMES = tuple(sheet + ".csv" for sheet in SHEET_ORDER)

COMPANY_FIELDS = ("企业编号", "企业名称", "常用简称")
USER_FIELDS = ("用户编号", "用户名称")
INVOICE_FIELDS = ("企业编号", "发票编号", "开票日期", "销售方名称", "项目名称（票面）",
                  "价税合计（元）", "用途", "备注")
BANK_FIELDS = ("企业编号", "流水编号", "交易日期", "收支方向", "金额（元）", "对方名称", "备注")
NOTES_FIELDS = ("企业编号", "月份", "发票张数", "流水条数", "价税合计（元）",
                "银行支出（元）", "银行收入（元）")
INVOICE_OPTIONAL = {"用途", "备注"}
BANK_OPTIONAL = {"备注"}
PERMISSION_VALUES = ("无权访问", "仅查看", "可查看并修改")
DIRECTIONS = ("收入", "支出")

# Four decoded CSV files share the original 5 MB single-workbook limit.
MAX_TOTAL_BYTES = 5_000_000
MAX_CSV_ROWS = 10_000
MAX_CSV_COLUMNS = 64
MAX_CSV_CELL = 10_000
MAX_WORD_ROWS = 10_000
MAX_WORD_COLUMNS = 64
MAX_WORD_CELL = 10_000
MAX_DOCX_UNCOMPRESSED = 20_000_000
MAX_DOCUMENT_XML = 8_000_000

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_PERMISSION_HEADER = re.compile(r"^(?P<label>.+?)[（(](?P<company>[^（）()]+)[）)]$")
_DATE = re.compile(
    r"^(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})"
    r"(?:[ T](?P<hour>\d{1,2}):(?P<minute>\d{1,2}):(?P<second>\d{1,2}))?$")
_MONTH = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{1,2})$")
_AMOUNT = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")
_COUNT = re.compile(r"^\d+$")


class ImportFormatError(ValueError):
    """The selected files are not the fixed Word/CSV import form."""


class ConvertedImport:
    """Validated four-sheet input plus a file/table/row explanation on failure."""

    __slots__ = ("payload", "source", "typed", "lines", "origin")

    def __init__(self, payload, source, typed, lines, origin):
        self.payload = payload
        self.source = source
        self.typed = typed
        self.lines = lines
        self.origin = origin

    def explain(self, error):
        """Locate the first failed cross-check row without changing any value."""
        message = str(error)
        if "核对值不一致" in message:
            detail = _notes_mismatch(self.typed, self.lines)
            if detail:
                return detail
        return ""


# --------------------------------------------------------------------------- public entry points
def convert_docx(payload, filename="导入.docx"):
    """Return the validated four-sheet workbook for one fixed-template .docx."""
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise ImportFormatError("Word 文件为空，未创建新账簿。")
    filename = _safe_name(filename, ".docx")
    raw, origin = _parse_docx(bytes(payload), filename)
    canonical, lines, typed = _validate_sheets(raw, origin)
    source = "Word 文档 " + filename
    return ConvertedImport(_workbook_bytes(canonical), source, typed, lines, origin)


def convert_csv_files(files):
    """Return the validated four-sheet workbook for the four fixed CSV files."""
    entries = _csv_entries(files)
    raw, origin = {}, {}
    for name, data in entries:
        sheet = CSV_FILENAMES.index(name) if name in CSV_FILENAMES else None
        if sheet is None:
            raise ImportFormatError("不支持的文件名：" + name)
        sheet = SHEET_ORDER[sheet]
        raw[sheet] = _csv_rows(data, "CSV 文件 " + name)
        origin[sheet] = "CSV 文件 " + name
    canonical, lines, typed = _validate_sheets(raw, origin)
    return ConvertedImport(_workbook_bytes(canonical), "四份 CSV 文件", typed, lines, origin)


# --------------------------------------------------------------------------- naming / decoding helpers
def _safe_name(name, suffix):
    if not isinstance(name, str) or not name.strip():
        raise ImportFormatError("缺少文件名，未创建新账簿。")
    base = Path(name.replace("\\", "/")).name
    if not base.lower().endswith(suffix):
        raise ImportFormatError("文件扩展名必须为 " + suffix + "，未创建新账簿。")
    return base


def _where(origin, line=None):
    if line is None:
        return origin
    return origin + " 第 " + str(line) + " 行"


# --------------------------------------------------------------------------- CSV parsing
def _csv_entries(files):
    if not isinstance(files, (list, tuple)):
        raise ImportFormatError("CSV 导入必须一次提交四份固定文件的列表。")
    entries, seen = [], set()
    for item in files:
        if not isinstance(item, dict):
            raise ImportFormatError("CSV 文件项格式无效。")
        name = item.get("name")
        content = item.get("content")
        if not isinstance(name, str):
            raise ImportFormatError("CSV 文件缺少名称。")
        base = Path(name.replace("\\", "/")).name
        if base not in CSV_FILENAMES:
            raise ImportFormatError(
                "不支持的文件：" + base + "；必须一次提交四份固定文件：" + "、".join(CSV_FILENAMES) + "。")
        if base in seen:
            raise ImportFormatError("重复文件：" + base + "；每份 CSV 只能提交一次。")
        if not isinstance(content, str):
            raise ImportFormatError(base + " 缺少文件内容。")
        try:
            data = base64.b64decode(content, validate=True)
        except (binascii.Error, ValueError):
            raise ImportFormatError(base + " 内容不是合法 Base64。") from None
        if not data:
            raise ImportFormatError(base + " 文件为空。")
        seen.add(base)
        entries.append((base, data))
    missing = [name for name in CSV_FILENAMES if name not in seen]
    if missing:
        raise ImportFormatError("缺少 CSV 文件：" + "、".join(missing) + "；必须一次提交四份固定文件。")
    total = sum(len(data) for _, data in entries)
    if total > MAX_TOTAL_BYTES:
        raise ImportFormatError(
            "CSV 四份文件合计 " + str(total) + " 字节，超过 " + str(MAX_TOTAL_BYTES) + " 字节上限。")
    return [(name, dict(entries)[name]) for name in CSV_FILENAMES]


def _csv_rows(data, label):
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportFormatError(label + " 不是 UTF-8 编码（仅支持 UTF-8，可带 BOM）。") from None
    if "\x00" in text:
        raise ImportFormatError(label + " 含二进制内容，不是标准 CSV。")
    try:
        rows = []
        for row in csv.reader(io.StringIO(text, newline=""), strict=True):
            if len(rows) >= MAX_CSV_ROWS:
                raise ImportFormatError(label + " 行数过多。")
            if len(row) > MAX_CSV_COLUMNS:
                raise ImportFormatError(label + " 列数过多。")
            if any(len(cell) > MAX_CSV_CELL for cell in row):
                raise ImportFormatError(label + " 存在过长的单元格。")
            rows.append(row)
    except csv.Error as error:
        raise ImportFormatError(label + " 不是标准逗号分隔 CSV：" + str(error)) from None
    return rows


# --------------------------------------------------------------------------- Word parsing
def _parse_docx(payload, filename):
    try:
        with ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            total = 0
            for info in infos:
                total += info.file_size
                parts = Path(info.filename.replace("\\", "/")).parts
                if info.filename.startswith("/") or ".." in parts:
                    raise ImportFormatError("Word 文档包含不安全的压缩路径。")
            if total > MAX_DOCX_UNCOMPRESSED:
                raise ImportFormatError("Word 文档解压后过大。")
            if "word/document.xml" not in {info.filename for info in infos}:
                raise ImportFormatError(
                    "不是有效的 .docx（缺少 word/document.xml）；旧 .doc、扫描件或损坏文件不支持。")
            document = archive.read("word/document.xml")
    except BadZipFile:
        raise ImportFormatError("不是有效的 .docx 文件；旧 .doc、扫描件或损坏文件不支持。") from None
    except (OSError, RuntimeError) as error:
        raise ImportFormatError("Word 文档无法读取：" + type(error).__name__) from None
    if len(document) > MAX_DOCUMENT_XML:
        raise ImportFormatError("Word 正文过大。")
    try:
        root = ET.fromstring(document)
    except ET.ParseError:
        raise ImportFormatError("Word 文档结构无法解析。") from None

    body = root.find(W + "body")
    if body is None:
        raise ImportFormatError("Word 文档缺少正文。")

    blocks = []
    for child in body:
        if child.tag == W + "p":
            text = _paragraph_text(child)
            if text.strip():
                blocks.append(("p", child))
        elif child.tag == W + "tbl":
            blocks.append(("t", child))
        elif child.tag == W + "sectPr":
            continue
        else:
            raise ImportFormatError("Word 正文包含无法识别的结构：" + _tag_name(child.tag) + "。")

    heading_set = set(SHEET_ORDER)
    raw, origin, seen = {}, {}, set()
    index = 0
    while index < len(blocks):
        kind, node = blocks[index]
        if kind != "p":
            raise ImportFormatError("表格前缺少四个固定标题；仅接受“标题＋对应表格”。")
        text = _paragraph_text(node).strip()
        if text not in heading_set:
            raise ImportFormatError("Word 正文包含标题以外的文本：" + _short(text) +
                                    "；仅接受四个固定标题及其对应表格。")
        if not _heading_paragraph(node):
            raise ImportFormatError("标题“" + text + "”未使用 Word 标题样式，无法确认表格归属。")
        if text in seen:
            raise ImportFormatError("重复标题：" + text + "；四个固定标题各只能出现一次。")
        seen.add(text)
        if index + 1 >= len(blocks) or blocks[index + 1][0] != "t":
            raise ImportFormatError("标题“" + text + "”下缺少对应表格。")
        raw[text] = _table_rows(blocks[index + 1][1], text)
        origin[text] = "Word 文档 " + filename + " 的标题“" + text + "”表格"
        index += 2
    missing = [name for name in SHEET_ORDER if name not in raw]
    if missing:
        raise ImportFormatError("Word 文档缺少固定标题或对应表格：" + "、".join(missing) + "。")
    return raw, origin


def _tag_name(tag):
    return tag.rsplit("}", 1)[-1]


def _paragraph_text(node):
    return "".join(part.text or "" for part in node.iter(W + "t"))


def _short(text):
    text = text.replace("\n", " ")
    return repr(text if len(text) <= 40 else text[:40] + "…")


def _heading_paragraph(node):
    properties = node.find(W + "pPr")
    if properties is None:
        return False
    style = properties.find(W + "pStyle")
    if style is not None:
        value = (style.get(W + "val") or "").strip().casefold()
        if value in {"heading1", "heading2", "heading3", "heading 1", "heading 2",
                     "heading 3", "1", "2", "3"}:
            return True
        if "heading" in value or value.startswith("标题"):
            return True
    outline = properties.find(W + "outlineLvl")
    return outline is not None and (outline.get(W + "val") or "").strip() == "0"


def _table_rows(table, heading):
    rows = []
    for row_index, row in enumerate(table.findall(W + "tr"), 1):
        if row_index > MAX_WORD_ROWS:
            raise ImportFormatError("表“" + heading + "”行数过多。")
        cells = []
        for cell in row.findall(W + "tc"):
            properties = cell.find(W + "tcPr")
            if properties is not None and (properties.find(W + "gridSpan") is not None
                                           or properties.find(W + "vMerge") is not None):
                raise ImportFormatError(
                    "表“" + heading + "”第 " + str(row_index) + " 行包含合并单元格，结构不明。")
            if cell.find(".//" + W + "tbl") is not None:
                raise ImportFormatError(
                    "表“" + heading + "”第 " + str(row_index) + " 行包含嵌套表格，结构不明。")
            text = "\n".join(part for part in
                             (_paragraph_text(item) for item in cell.findall(W + "p")) if part.strip())
            if len(text) > MAX_WORD_CELL:
                raise ImportFormatError("表“" + heading + "”第 " + str(row_index) + " 行存在过长的单元格。")
            cells.append(text)
        if len(cells) > MAX_WORD_COLUMNS:
            raise ImportFormatError("表“" + heading + "”列数过多。")
        rows.append(cells)
    if not rows:
        raise ImportFormatError("表“" + heading + "”没有数据行。")
    width = max(len(row) for row in rows)
    return [row + [""] * (width - len(row)) for row in rows]


# --------------------------------------------------------------------------- shared validation
def _clean_row(row):
    return [(str(value).strip() if value is not None else "") or None for value in row]


def _clean_rows(rows):
    return [_clean_row(row) for row in rows]


def _trim(row):
    values = list(row)
    while values and values[-1] is None:
        values.pop()
    return values


def _blank(row):
    return all(value is None for value in row)


def _validate_sheets(raw, origin):
    typed, lines = {}, {}
    canonical_companies, company_ids = _validate_companies(
        raw.get(COMPANIES, []), origin.get(COMPANIES, "企业与用户"))

    invoices = _validate_flat(INVOICES, INVOICE_FIELDS, INVOICE_OPTIONAL,
                              raw.get(INVOICES, []), origin.get(INVOICES, "发票"))
    bank = _validate_flat(BANK, BANK_FIELDS, BANK_OPTIONAL,
                          raw.get(BANK, []), origin.get(BANK, "银行流水"))
    notes = _validate_flat(NOTES, NOTES_FIELDS, set(),
                           raw.get(NOTES, []), origin.get(NOTES, "说明"))

    known = set(company_ids)
    _check_references(invoices, known, origin.get(INVOICES, "发票"), "发票编号")
    _check_references(bank, known, origin.get(BANK, "银行流水"), "流水编号")
    _check_references(notes, known, origin.get(NOTES, "说明"), None)

    typed[INVOICES] = [row for _, row in invoices]
    lines[INVOICES] = [line for line, _ in invoices]
    typed[BANK] = [row for _, row in bank]
    lines[BANK] = [line for line, _ in bank]
    typed[NOTES] = [row for _, row in notes]
    lines[NOTES] = [line for line, _ in notes]
    canonical = {
        COMPANIES: canonical_companies,
        INVOICES: [list(INVOICE_FIELDS)] + typed[INVOICES],
        BANK: [list(BANK_FIELDS)] + typed[BANK],
        NOTES: [list(NOTES_FIELDS)] + typed[NOTES],
    }
    return canonical, lines, typed


def _validate_companies(rows, origin):
    rows = _clean_rows(rows)
    table = origin
    if not rows:
        raise ImportFormatError(table + "：缺少企业与用户表格内容。")
    header = _trim(rows[0])
    if header != list(COMPANY_FIELDS):
        raise ImportFormatError(
            _where(table, 1) + "：企业表头必须为 企业编号、企业名称、常用简称；实际为 " +
            "、".join(value or "（空）" for value in header) + "。")

    companies, company_ids = [], set()
    index = 1
    while index < len(rows) and not _blank(rows[index]):
        row = _trim(rows[index])
        line = index + 1
        if len(row) < 3 or any(value is None for value in row[:3]):
            raise ImportFormatError(_where(table, line) + "：企业编号、企业名称、常用简称均不能为空。")
        if len(row) > 3:
            raise ImportFormatError(_where(table, line) + "：企业表只有企业编号、企业名称、常用简称三列。")
        if row[0] in company_ids:
            raise ImportFormatError(_where(table, line) + "：企业编号重复：" + row[0] + "。")
        company_ids.add(row[0])
        companies.append(row[:3])
        index += 1
    if index >= len(rows) or not _blank(rows[index]):
        raise ImportFormatError(table + "：企业列表后缺少空行，无法区分用户权限表。")
    index += 1
    if index >= len(rows):
        raise ImportFormatError(table + "：缺少用户权限表头。")

    user_header = _trim(rows[index])
    user_line = index + 1
    if len(user_header) < 3 or user_header[0] != USER_FIELDS[0] or user_header[1] != USER_FIELDS[1]:
        raise ImportFormatError(
            _where(table, user_line) + "：用户权限表头必须为用户编号、用户名称和每个企业一列权限；"
            "实际为 " + "、".join(value or "（空）" for value in user_header) + "。")
    permission_headers = user_header[2:]
    if any(value is None for value in permission_headers):
        raise ImportFormatError(_where(table, user_line) + "：权限列中间存在空表头。")
    matched, columns = set(), []
    for column, value in enumerate(permission_headers, 3):
        match = _PERMISSION_HEADER.match(value)
        if not match:
            raise ImportFormatError(
                _where(table, user_line) + " 第 " + str(column) +
                " 列：权限列标题应类似 甲企业（C001），以便关联企业编号。")
        company_id = match.group("company")
        if company_id not in company_ids:
            raise ImportFormatError(
                _where(table, user_line) + " 第 " + str(column) +
                " 列：权限列指向未登记企业 " + company_id + "。")
        if company_id in matched:
            raise ImportFormatError(
                _where(table, user_line) + " 第 " + str(column) +
                " 列：企业 " + company_id + " 的权限列重复。")
        matched.add(company_id)
        columns.append(company_id)
    missing = [company_id for company_id in company_ids if company_id not in matched]
    if missing or len(columns) != len(companies):
        raise ImportFormatError(
            table + "：权限列与企业不一一对应；缺少企业 " + "、".join(missing or ["（无）"]) + " 的权限列。")

    users, user_ids = [], set()
    width = 2 + len(permission_headers)
    index += 1
    while index < len(rows) and not _blank(rows[index]):
        row = _trim(rows[index])
        line = index + 1
        if len(row) != width or any(value is None for value in row[:2]):
            raise ImportFormatError(
                _where(table, line) + "：用户行必须包含用户编号、用户名称和 " +
                str(len(permission_headers)) + " 个企业权限值（共 " + str(width) + " 列）。")
        if row[0] in user_ids:
            raise ImportFormatError(_where(table, line) + "：用户编号重复：" + row[0] + "。")
        for column, value in enumerate(row[2:], 3):
            if value not in PERMISSION_VALUES:
                raise ImportFormatError(
                    _where(table, line) + " 第 " + str(column) + " 列：未知权限值 " + repr(value) +
                    "；仅支持 无权访问、仅查看、可查看并修改。")
        user_ids.add(row[0])
        users.append(row[:width])
        index += 1
    for later in range(index, len(rows)):
        if not _blank(rows[later]):
            raise ImportFormatError(_where(table, later + 1) + "：用户权限表后存在无法识别的行。")

    padding = [None] * (width - 3)
    canonical = [list(COMPANY_FIELDS) + padding]
    canonical.extend(row + padding for row in companies)
    canonical.append([None] * width)
    canonical.append([USER_FIELDS[0], USER_FIELDS[1]] + list(permission_headers))
    canonical.extend(users)
    return canonical, [row[0] for row in companies]


def _validate_flat(sheet, fields, optional, rows, origin):
    rows = _clean_rows(rows)
    if not rows:
        raise ImportFormatError(origin + "：缺少“" + sheet + "”表格内容。")
    header = _trim(rows[0])
    if header != list(fields):
        missing = [field for field in fields if field not in header]
        extra = [value for value in header if value not in fields]
        detail = []
        if missing:
            detail.append("缺少：" + "、".join(missing))
        if extra:
            detail.append("多出：" + "、".join(extra))
        raise ImportFormatError(
            _where(origin, 1) + "：表头必须与官方模板一致（" + "、".join(fields) + "）；" +
            ("；".join(detail) if detail else "字段顺序或名称不一致") + "。")
    data, ended = [], False
    for position in range(1, len(rows)):
        line = position + 1
        if _blank(rows[position]):
            ended = True
            continue
        if ended:
            raise ImportFormatError(_where(origin, line) + "：数据区结束（空行）后仍有内容。")
        row = _trim(rows[position])
        if len(row) > len(fields):
            raise ImportFormatError(_where(origin, line) + "：存在多余列。")
        row = row + [None] * (len(fields) - len(row))
        for column, field in enumerate(fields):
            if field not in optional and row[column] is None:
                raise ImportFormatError(_where(origin, line) + "：必需字段“" + field + "”为空。")
        data.append((line, _coerce_row(sheet, fields, row, origin, line)))
    return data


def _coerce_row(sheet, fields, row, origin, line):
    values = []
    for field, text in zip(fields, row):
        if text is None:
            values.append(None)
            continue
        try:
            if sheet == INVOICES and field == "开票日期":
                values.append(_parse_date(text))
            elif sheet == INVOICES and field == "价税合计（元）":
                values.append(_parse_amount(text))
            elif sheet == BANK and field == "交易日期":
                values.append(_parse_date(text))
            elif sheet == BANK and field == "金额（元）":
                values.append(_parse_amount(text))
            elif sheet == BANK and field == "收支方向":
                if text not in DIRECTIONS:
                    raise ImportFormatError("收支方向只能是 收入 或 支出；实际为 " + repr(text) + "。")
                values.append(text)
            elif sheet == NOTES and field == "月份":
                values.append(_parse_month(text))
            elif sheet == NOTES and field in {"发票张数", "流水条数"}:
                if not _COUNT.match(text):
                    raise ImportFormatError("字段“" + field + "”必须为非负整数；实际为 " + repr(text) + "。")
                values.append(int(text))
            elif sheet == NOTES and field in {"价税合计（元）", "银行支出（元）", "银行收入（元）"}:
                values.append(_parse_amount(text))
            else:
                values.append(text)
        except ImportFormatError as error:
            raise ImportFormatError(_where(origin, line) + "：" + str(error)) from None
    return values


def _check_references(rows, company_ids, origin, key_field):
    seen = set()
    for line, row in rows:
        company_id = row[0]
        if company_id not in company_ids:
            raise ImportFormatError(
                _where(origin, line) + "：企业编号 " + repr(company_id) + " 未在“企业与用户”表登记。")
        if key_field is not None:
            key = (company_id, row[1])
            if key in seen:
                raise ImportFormatError(
                    _where(origin, line) + "：" + key_field + " " + repr(row[1]) +
                    " 在企业 " + company_id + " 下重复。")
            seen.add(key)


# --------------------------------------------------------------------------- typed value parsing
def _parse_date(text):
    match = _DATE.match(text)
    if not match:
        raise ImportFormatError("日期格式无效：" + repr(text) + "；应为 yyyy-mm-dd。")
    try:
        value = datetime(int(match.group("year")), int(match.group("month")),
                         int(match.group("day")), int(match.group("hour") or 0),
                         int(match.group("minute") or 0), int(match.group("second") or 0))
    except ValueError:
        raise ImportFormatError("日期无效：" + repr(text) + "。") from None
    if match.group("hour") is not None and (value.hour or value.minute or value.second):
        raise ImportFormatError("日期时间必须为当日零点：" + repr(text) + "。")
    return value


def _parse_month(text):
    match = _DATE.match(text)
    if match:
        if (match.group("day").lstrip("0") or "0") != "1":
            raise ImportFormatError("月份必须为该月1日或 yyyy-mm；实际为 " + repr(text) + "。")
        return _parse_date(text)
    match = _MONTH.match(text)
    if not match:
        raise ImportFormatError("月份格式无效：" + repr(text) + "；应为 yyyy-mm 或该月1日日期。")
    try:
        return datetime(int(match.group("year")), int(match.group("month")), 1)
    except ValueError:
        raise ImportFormatError("月份无效：" + repr(text) + "。") from None


def _parse_amount(text):
    if not _AMOUNT.match(text):
        raise ImportFormatError("金额无效：" + repr(text) + "；应为普通十进制数字。")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ImportFormatError("金额无效：" + repr(text) + "。") from None
    if not value.is_finite():
        raise ImportFormatError("金额无效：" + repr(text) + "。")
    return value


# --------------------------------------------------------------------------- workbook writing
def _workbook_bytes(sheets):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet in SHEET_ORDER:
        worksheet = workbook.create_sheet(sheet)
        for row_index, row in enumerate(sheets[sheet], 1):
            columns = max(len(row), 1)
            for column_index in range(1, columns + 1):
                value = row[column_index - 1] if column_index <= len(row) else None
                cell = worksheet.cell(row=row_index, column=column_index)
                cell.value = value
                # Text stays text; a value starting with "=" must never become a formula.
                if isinstance(value, str) and value.startswith("="):
                    cell.data_type = "s"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# --------------------------------------------------------------------------- failure diagnosis
def _cents(value):
    return int((Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) * 100)


def _notes_mismatch(typed, lines):
    """Replay the original 说明 cross-check only to name the failed row."""
    companies = typed.get(COMPANIES) or []
    invoices = typed.get(INVOICES) or []
    bank = typed.get(BANK) or []
    notes = typed.get(NOTES) or []
    note_lines = lines.get(NOTES) or []
    for index, row in enumerate(notes):
        company, month, expected = row[0], row[1], row[2:7]
        prefix = month.strftime("%Y-%m")
        invoices_rows = [item for item in invoices
                         if item[0] == company and item[2].strftime("%Y-%m") == prefix]
        bank_rows = [item for item in bank
                     if item[0] == company and item[2].strftime("%Y-%m") == prefix]
        invoice_count = len(invoices_rows)
        invoice_amount = sum(_cents(item[5]) for item in invoices_rows)
        bank_count = len(bank_rows)
        outgoing = sum(_cents(item[4]) for item in bank_rows if item[3] == "支出")
        incoming = sum(_cents(item[4]) for item in bank_rows if item[3] == "收入")
        actual = (invoice_count, bank_count, invoice_amount, outgoing, incoming)
        wanted = (expected[0], expected[1], _cents(expected[2]), _cents(expected[3]), _cents(expected[4]))
        if actual != wanted:
            line = note_lines[index] if index < len(note_lines) else index + 2
            return (
                "说明表第 " + str(line) + " 行（" + str(company) + " " + prefix +
                "）与导入明细核对不符：实际发票 " + str(invoice_count) + " 张/" +
                _yuan(invoice_amount) + " 元、流水 " + str(bank_count) + " 条、支出 " +
                _yuan(outgoing) + " 元、收入 " + _yuan(incoming) + " 元；核对值为发票 " +
                str(expected[0]) + " 张/" + _yuan(_cents(expected[2])) + " 元、流水 " +
                str(expected[1]) + " 条、支出 " + _yuan(_cents(expected[3])) + " 元、收入 " +
                _yuan(_cents(expected[4])) + " 元。")
    return ""


def _yuan(cents):
    return format(Decimal(cents) / 100, ".2f")
