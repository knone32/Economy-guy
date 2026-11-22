"""Regenerate the fixed Word/CSV import samples from the official fictional Excel.

The official workbook ``../example.xlsx`` is the source of truth.  This script
only materialises the already-fixed Word/CSV forms for the acceptance fixtures:
four Word heading-styled paragraphs (企业与用户 / 发票 / 银行流水 / 说明), one
table under each heading, and four CSV files named after the four worksheets.

Run from this directory:  python build_samples.py
"""
from datetime import date, datetime
from decimal import Decimal
import csv
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parent
EXCEL = ROOT.parent / "example.xlsx"
DOCX = ROOT / "example.docx"
CSV_DIR = ROOT / "csv"
SHEETS = ("企业与用户", "发票", "银行流水", "说明")
INVOICE_FIELDS = ("企业编号", "发票编号", "开票日期", "销售方名称", "项目名称（票面）",
                  "价税合计（元）", "用途", "备注")
BANK_FIELDS = ("企业编号", "流水编号", "交易日期", "收支方向", "金额（元）", "对方名称", "备注")
NOTES_FIELDS = ("企业编号", "月份", "发票张数", "流水条数", "价税合计（元）",
                "银行支出（元）", "银行收入（元）")
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _text(value):
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float):
        return str(Decimal(repr(value)).quantize(Decimal("0.01")))
    return str(value)


def _find_header(rows, fields):
    wanted = set(fields)
    for index, row in enumerate(rows):
        if wanted.issubset({value for value in row if isinstance(value, str)}):
            return index, list(row)
    raise SystemExit("missing header: " + "、".join(fields))


def _flat_rows(rows, fields):
    header_row, header = _find_header(rows, fields)
    mapping = {name: index for index, name in enumerate(header) if name}
    data = [list(fields)]
    for row in rows[header_row + 1:]:
        if not row or all(value is None for value in row) or not row[0]:
            break
        data.append([_text(row[mapping[field]]) for field in fields])
    return data


def _companies_rows(rows):
    header_row, _ = _find_header(rows, ("企业编号", "企业名称", "常用简称"))
    companies = []
    index = header_row + 1
    while index < len(rows) and rows[index][0]:
        companies.append([_text(value) for value in rows[index][:3]])
        index += 1
    while index < len(rows) and rows[index][0] != "用户编号":
        index += 1
    if index >= len(rows):
        raise SystemExit("missing user permission header")
    user_header = [_text(value) for value in rows[index]]
    while user_header and not user_header[-1]:
        user_header.pop()
    users = []
    index += 1
    while index < len(rows) and rows[index][0]:
        users.append([_text(value) for value in rows[index][:len(user_header)]])
        index += 1
    width = len(user_header)
    result = [["企业编号", "企业名称", "常用简称"] + [""] * (width - 3)]
    result.extend(row + [""] * (width - len(row)) for row in companies)
    result.append([""] * width)
    result.append(user_header)
    result.extend(row + [""] * (width - len(row)) for row in users)
    return result


def build_rows():
    workbook = load_workbook(EXCEL, data_only=True)
    try:
        company_rows = _companies_rows([list(row) for row in workbook["企业与用户"].iter_rows(values_only=True)])
        invoice_rows = _flat_rows([list(row) for row in workbook["发票"].iter_rows(values_only=True)], INVOICE_FIELDS)
        bank_rows = _flat_rows([list(row) for row in workbook["银行流水"].iter_rows(values_only=True)], BANK_FIELDS)
        notes_rows = _flat_rows([list(row) for row in workbook["说明"].iter_rows(values_only=True)], NOTES_FIELDS)
    finally:
        workbook.close()
    return {"企业与用户": company_rows, "发票": invoice_rows, "银行流水": bank_rows, "说明": notes_rows}


def write_csv(rows):
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    for index, sheet in enumerate(SHEETS):
        target = CSV_DIR / (sheet + ".csv")
        # One real-world twin keeps the UTF-8 BOM; the others are plain UTF-8.
        encoding = "utf-8-sig" if sheet == "企业与用户" else "utf-8"
        with target.open("w", encoding=encoding, newline="") as stream:
            writer = csv.writer(stream, lineterminator="\r\n")
            writer.writerows(rows[sheet])


def _paragraph(text, heading=False):
    style = '<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>' if heading else ""
    return ('<w:p>' + style + '<w:r><w:t xml:space="preserve">' + escape(text) + '</w:t></w:r></w:p>')


def _table(rows):
    width = max(len(row) for row in rows)
    parts = ['<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/></w:tblPr><w:tblGrid>']
    parts.extend('<w:gridCol w:w="2400"/>' for _ in range(width))
    parts.append('</w:tblGrid>')
    for row in rows:
        cells = row + [""] * (width - len(row))
        parts.append('<w:tr>')
        for value in cells:
            parts.append('<w:tc><w:tcPr><w:tcW w:w="2400" w:type="auto"/></w:tcPr>' +
                         _paragraph(value) + '</w:tc>')
        parts.append('</w:tr>')
    parts.append('</w:tbl>')
    return "".join(parts)


def write_docx(rows):
    body = []
    for sheet in SHEETS:
        body.append(_paragraph(sheet, heading=True))
        body.append(_table(rows[sheet]))
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="' + W + '"><w:body>' + "".join(body) +
                '<w:sectPr/></w:body></w:document>')
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                     '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                     '</Types>')
    relationships = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                     '</Relationships>')
    document_relationships = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                              '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                              '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                              '</Relationships>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:styles xmlns:w="' + W + '">'
              '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
              '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>'
              '<w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr>'
              '<w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
              '</w:styles>')
    with ZipFile(DOCX, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/_rels/document.xml.rels", document_relationships)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/styles.xml", styles)


def main():
    rows = build_rows()
    write_csv(rows)
    write_docx(rows)
    print("wrote", DOCX.name, "and", len(SHEETS), "CSV files")


if __name__ == "__main__":
    main()
