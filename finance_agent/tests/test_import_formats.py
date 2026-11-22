"""Word/CSV new-workbook import: same four-table result, fail-closed behaviour.

These are program checks only: no model call, no human approval and no
production database are touched.  The official fictional Excel is the source
of truth; the Word/CSV samples under fixtures/import_samples are generated
from it by build_samples.py.
"""
import base64
import csv
import io
import json
import sqlite3
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from app.cli_workspaces import import_workspace
from app.gui_host import GuiError, GuiHost
from app.gui_server import GuiServer
from app.import_formats import convert_csv_files, convert_docx


FIXTURES = Path(__file__).parent / "fixtures"
EXCEL = FIXTURES / "example.xlsx"
SAMPLES = FIXTURES / "import_samples"
WORD = SAMPLES / "example.docx"
CSV_DIR = SAMPLES / "csv"
CSV_NAMES = ("企业与用户.csv", "发票.csv", "银行流水.csv", "说明.csv")
TABLES = ("companies", "users", "permissions", "invoices", "bank_transactions", "rules")
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def encode(data):
    return base64.b64encode(data).decode()


def file_content(path):
    return encode(Path(path).read_bytes())


def csv_sample_rows(name):
    with (CSV_DIR / name).open("r", encoding="utf-8-sig", newline="") as stream:
        return [row for row in csv.reader(stream)]


def csv_text(rows):
    stream = io.StringIO()
    csv.writer(stream, lineterminator="\r\n").writerows(rows)
    return stream.getvalue().encode("utf-8")


def csv_files(modifications=None):
    files = []
    for name in CSV_NAMES:
        rows = (modifications or {}).get(name)
        if rows is None:
            rows = csv_sample_rows(name)
        files.append({"name": name, "content": encode(csv_text(rows))})
    return files


def database_snapshot(path):
    with closing(sqlite3.connect(path)) as db:
        data = {table: db.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall()
                for table in TABLES}
        data["schema"] = db.execute(
            "SELECT name, sql FROM sqlite_master WHERE type IN ('table','index') ORDER BY name").fetchall()
    return data


def _paragraph(text, heading=False):
    style = '<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>' if heading else ""
    return '<w:p>' + style + '<w:r><w:t xml:space="preserve">' + escape(text) + '</w:t></w:r></w:p>'


def _table(rows):
    width = max(len(row) for row in rows)
    parts = ['<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/></w:tblPr><w:tblGrid>']
    parts.extend('<w:gridCol w:w="1600"/>' for _ in range(width))
    parts.append('</w:tblGrid>')
    for row in rows:
        parts.append('<w:tr>')
        for value in row + [""] * (width - len(row)):
            parts.append('<w:tc><w:tcPr><w:tcW w:w="1600" w:type="auto"/></w:tcPr>' +
                         _paragraph(value) + '</w:tc>')
        parts.append('</w:tr>')
    parts.append('</w:tbl>')
    return "".join(parts)


def _merged_table():
    return ('<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/></w:tblPr><w:tblGrid>'
            '<w:gridCol w:w="1600"/><w:gridCol w:w="1600"/></w:tblGrid>'
            '<w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>' + _paragraph("企业编号") +
            '</w:tc></w:tr></w:tbl>')


def docx_bytes(blocks):
    """Build a small but valid OOXML .docx for negative and positive cases."""
    body = []
    for block in blocks:
        kind = block[0]
        if kind == "heading":
            body.append(_paragraph(block[1], heading=True))
        elif kind == "plain":
            body.append(_paragraph(block[1]))
        elif kind == "table":
            body.append(_table(block[1]))
        elif kind == "merged":
            body.append(_merged_table())
        elif kind == "drawing":
            body.append('<w:p><w:r><w:drawing/></w:r></w:p>')
        elif kind == "raw":
            body.append(block[1])
        else:
            raise AssertionError(kind)
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
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:styles xmlns:w="' + W + '">'
              '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
              '</w:styles>')
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/styles.xml", styles)
    return stream.getvalue()


class ConversionEquivalenceTests(unittest.TestCase):
    """Both new forms must reproduce the official fictional workbook exactly."""

    def test_word_and_csv_import_same_records_amounts_rules_and_migrations(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            official = root / "official.db"
            import_workspace(EXCEL, official)
            expected = database_snapshot(official)
            self.assertEqual(len(expected["invoices"]), 40)
            self.assertEqual(len(expected["bank_transactions"]), 48)
            self.assertEqual(len(expected["companies"]), 2)
            self.assertEqual(len(expected["users"]), 2)
            self.assertEqual(len(expected["permissions"]), 4)
            self.assertEqual(len(expected["rules"]), 5)

            word = convert_docx(WORD.read_bytes(), WORD.name)
            word_xlsx = root / "word.xlsx"
            word_xlsx.write_bytes(word.payload)
            word_book = root / "word.db"
            import_workspace(word_xlsx, word_book)
            self.assertEqual(database_snapshot(word_book), expected)

            converted = convert_csv_files(csv_files())
            csv_xlsx = root / "csv.xlsx"
            csv_xlsx.write_bytes(converted.payload)
            csv_book = root / "csv.db"
            import_workspace(csv_xlsx, csv_book)
            self.assertEqual(database_snapshot(csv_book), expected)

    def test_leading_zero_and_formula_like_text_stay_text(self):
        invoices = csv_sample_rows("发票.csv")
        invoices[1][1] = "0001"
        invoices[1][7] = '=SUM(A1:A2), "含引号"'
        converted = convert_csv_files(csv_files({"发票.csv": invoices}))
        with TemporaryDirectory() as folder:
            root = Path(folder)
            xlsx = root / "converted.xlsx"
            xlsx.write_bytes(converted.payload)
            book = root / "book.db"
            import_workspace(xlsx, book)
            with closing(sqlite3.connect(book)) as db:
                row = db.execute("SELECT invoice_no, remark FROM invoices WHERE company_id='C001' "
                                 "AND invoice_no='0001'").fetchone()
            self.assertEqual(row, ("0001", '=SUM(A1:A2), "含引号"'))

    def test_csv_standard_quoting_and_bom_are_accepted(self):
        # The committed 企业与用户.csv carries a UTF-8 BOM; quoting is exercised
        # by adding an ASCII comma and double quote to one optional field.
        invoices = csv_sample_rows("发票.csv")
        invoices[2][7] = '月末, 已核对 "原件"'
        files = csv_files({"发票.csv": invoices})
        self.assertTrue((CSV_DIR / "企业与用户.csv").read_bytes().startswith(b"\xef\xbb\xbf"))
        converted = convert_csv_files(files)
        with TemporaryDirectory() as folder:
            xlsx = Path(folder) / "converted.xlsx"
            xlsx.write_bytes(converted.payload)
            book = Path(folder) / "book.db"
            import_workspace(xlsx, book)
            with closing(sqlite3.connect(book)) as db:
                remark = db.execute("SELECT remark FROM invoices WHERE company_id='C001' "
                                    "AND invoice_no='F012'").fetchone()[0]
            self.assertEqual(remark, '月末, 已核对 "原件"')


class GuiHostImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.book = self.root / "fictional.sqlite3"
        import_workspace(EXCEL, self.book)
        self.session = self.root / "sessions.sqlite3"
        self.host = GuiHost(self.book, "U001", session_path=self.session, mode="mock",
                            model=lambda *args: self.fail("structured import must not call a model"))
        self.addCleanup(self.host.close)
        # GuiHost creates its own session/identity store; take the "unchanged"
        # baseline after that existing startup so imports are the only variable.
        self.before = database_snapshot(self.book)

    def facts(self):
        return database_snapshot(self.book)

    def context(self):
        return self.host.snapshot()["context"]

    def imports_dir(self):
        folder = self.session.parent / "imports"
        return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []

    def test_word_then_csv_create_selectable_books_without_switching(self):
        before = self.host.snapshot()
        view = self.host.import_workbook(WORD.name, file_content(WORD), context=self.context())
        self.assertFalse(view.get("error"), view.get("error"))
        after_word = self.host.snapshot()
        self.assertEqual(after_word["session"]["workbook"], str(self.book.resolve()))
        self.assertEqual(after_word["session"]["user"], "U001")
        self.assertEqual(len(after_word["settings"]["bindings"]), 4)
        self.assertEqual(self.facts(), self.before)

        view = self.host.import_workbook(None, None, context=self.context(), files=csv_files())
        self.assertFalse(view.get("error"), view.get("error"))
        after_csv = self.host.snapshot()
        self.assertEqual(after_csv["session"]["workbook"], str(self.book.resolve()))
        self.assertEqual(len(after_csv["settings"]["bindings"]), 6)
        self.assertEqual(self.facts(), self.before)
        self.assertEqual(len(self.imports_dir()), 2)
        self.assertNotEqual(before["settings"]["bindings"], after_csv["settings"]["bindings"])

        selector = next(key for key, value in self.host._bindings.items()
                        if value["actor"] == "U001" and value["book"] != self.book.resolve())
        switched = self.host.select_binding(selector, context=self.context())
        self.assertFalse(switched.get("error"), switched.get("error"))
        self.assertNotEqual(self.host.db_path, self.book.resolve())
        invoices = self.host.read_business(
            "list_invoice_directory",
            {"company_id": "C001", "year": 2026, "month": 9, "page": 1,
             "sort_by": "date", "sort_order": "asc"})
        self.assertIsNone(invoices.get("error"))
        self.assertEqual(invoices["workspace"]["result"]["status"], "SUCCESS")
        self.assertEqual(invoices["workspace"]["result"]["data"]["total"], 10)
        self.host.acknowledge_display(invoices["display"]["trace"], context=invoices["context"])
        bank = self.host.read_business(
            "list_bank_transactions",
            {"company_id": "C001", "year": 2026, "month": 9})
        self.assertIsNone(bank.get("error"))
        self.assertEqual(bank["workspace"]["result"]["status"], "SUCCESS")
        self.assertEqual(len(bank["workspace"]["result"]["data"]), 12)
        self.assertTrue(all(row["company_id"] == "C001"
                            for row in bank["workspace"]["result"]["data"]))

    def test_stale_revision_import_is_rejected_without_new_book(self):
        stale = self.context()
        self.assertFalse(self.host.import_workbook(WORD.name, file_content(WORD),
                                                   context=stale).get("error"))
        bindings = len(self.host.snapshot()["settings"]["bindings"])
        staged = self.imports_dir()
        with self.assertRaises(Exception):
            self.host.import_workbook(WORD.name, file_content(WORD), context=stale)
        self.assertEqual(len(self.host.snapshot()["settings"]["bindings"]), bindings)
        self.assertEqual(self.imports_dir(), staged)

    def _assert_rejected(self, name=None, content=None, files=None, fragments=()):
        bindings = len(self.host.snapshot()["settings"]["bindings"])
        staged = self.imports_dir()
        with self.assertRaises(GuiError) as caught:
            self.host.import_workbook(name, content, context=self.context(), files=files)
        message = str(caught.exception)
        for fragment in fragments:
            self.assertIn(fragment, message)
        self.assertEqual(len(self.host.snapshot()["settings"]["bindings"]), bindings)
        self.assertEqual(self.host.snapshot()["session"]["workbook"], str(self.book.resolve()))
        self.assertEqual(self.imports_dir(), staged)
        self.assertEqual(self.facts(), self.before)
        return message

    def test_word_failures_are_rejected_without_book_or_staging(self):
        companies = [["企业编号", "企业名称", "常用简称", ""], ["C001", "甲企业", "甲企业", ""],
                     ["", "", "", ""], ["用户编号", "用户名称", "甲企业（C001）", ""],
                     ["U001", "测试用户一", "可查看并修改", ""]]
        cases = [
            ("old.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", ("只接受",)),
            ("broken.docx", b"not a zip", ("不是有效的 .docx",)),
            ("empty.docx", b"", ("Word 文件为空",)),
            ("oversize.docx", b"x" * 5_000_001, ("超过5MB",)),
            ("scanned.docx", docx_bytes([("drawing",)]), ("缺少固定标题或对应表格",)),
            ("free.docx", docx_bytes([("plain", "企业经营数据自由文本")]), ("标题以外的文本",)),
            ("missing-table.docx", docx_bytes([("heading", "企业与用户")]), ("下缺少对应表格",)),
            ("missing-heading-style.docx", docx_bytes([("plain", "企业与用户"), ("table", companies)]),
             ("未使用 Word 标题样式",)),
            ("merged.docx", docx_bytes([("heading", "企业与用户"), ("merged",)]), ("合并单元格",)),
            ("duplicate.docx", docx_bytes([("heading", "企业与用户"), ("table", companies),
                                           ("heading", "企业与用户"), ("table", companies)]),
             ("重复标题",)),
            ("extra-text.docx", docx_bytes([("heading", "企业与用户"), ("table", companies),
                                            ("plain", "补充说明文字")]), ("标题以外的文本",)),
        ]
        for name, content, fragments in cases:
            with self.subTest(name=name):
                self._assert_rejected(name, encode(content), fragments=fragments)

    def test_csv_failures_are_rejected_without_book_or_staging(self):
        files = csv_files()
        missing = [item for item in files if item["name"] != "说明.csv"]
        duplicate = [dict(files[0]), dict(files[1]), dict(files[1]), dict(files[2])]
        bad_amount = csv_sample_rows("发票.csv")
        bad_amount[1][5] = "abc"
        bad_date = csv_sample_rows("发票.csv")
        bad_date[1][2] = "2026-13-40"
        unknown_company = csv_sample_rows("发票.csv")
        unknown_company[1][0] = "C999"
        duplicate_key = csv_sample_rows("发票.csv")
        duplicate_key[2][1] = duplicate_key[1][1]
        bad_notes = csv_sample_rows("说明.csv")
        bad_notes[2][4] = "1.00"
        bad_permission = csv_sample_rows("企业与用户.csv")
        bad_permission[5][2] = "可修改"
        unknown_permission_company = csv_sample_rows("企业与用户.csv")
        unknown_permission_company[4][2] = "甲企业（C999）"
        bad_header = csv_sample_rows("发票.csv")
        bad_header[0] = bad_header[0][:7]
        cases = [
            ("missing", None, missing, ("缺少 CSV 文件", "说明.csv")),
            ("duplicate", None, duplicate, ("重复文件", "发票.csv")),
            ("invalid-amount", None, csv_files({"发票.csv": bad_amount}),
             ("CSV 文件 发票.csv", "金额无效", "第 2 行")),
            ("invalid-date", None, csv_files({"发票.csv": bad_date}),
             ("CSV 文件 发票.csv", "日期无效", "第 2 行")),
            ("unknown-company", None, csv_files({"发票.csv": unknown_company}),
             ("未在“企业与用户”表登记", "C999")),
            ("duplicate-key", None, csv_files({"发票.csv": duplicate_key}),
             ("发票编号", "重复")),
            ("notes-mismatch", None, csv_files({"说明.csv": bad_notes}),
             ("说明表第", "核对不符")),
            ("permission-value", None, csv_files({"企业与用户.csv": bad_permission}),
             ("未知权限值", "可修改")),
            ("permission-company", None, csv_files({"企业与用户.csv": unknown_permission_company}),
             ("权限列指向未登记企业", "C999")),
            ("header", None, csv_files({"发票.csv": bad_header}),
             ("表头必须与官方模板一致", "缺少：备注")),
            ("wrong-name", None, [{"name": "票据.csv", "content": encode(b"x")}] + files[1:],
             ("不支持的文件", "票据.csv")),
            ("single-csv", "发票.csv", encode(csv_text(csv_sample_rows("发票.csv"))),
             ("CSV 必须一次选择四份固定文件",)),
        ]
        for label, name, payload, fragments in cases:
            with self.subTest(case=label):
                if name is None:
                    self._assert_rejected(None, None, payload, fragments=fragments)
                else:
                    self._assert_rejected(name, payload, None, fragments=fragments)
        # Invalid UTF-8 and malformed quoting never become a workbook.
        invalid_utf8 = [files[0], {"name": "发票.csv", "content": encode(b"\xff\xfe\x00\x01")},
                        files[2], files[3]]
        self._assert_rejected(None, None, invalid_utf8, fragments=("不是 UTF-8 编码",))
        malformed = [files[0], {"name": "发票.csv", "content": encode(b'a,"unterminated\n')},
                     files[2], files[3]]
        self._assert_rejected(None, None, malformed, fragments=("不是标准逗号分隔 CSV",))
        # Four decoded files are limited to the original 5 MB single-workbook cap.
        big = [{"name": name, "content": encode(b"x" * 1_500_000)} for name in CSV_NAMES]
        self._assert_rejected(None, None, big, fragments=("合计", "上限"))


class ImportRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.book = self.root / "fictional.sqlite3"
        import_workspace(EXCEL, self.book)
        self.session = self.root / "sessions.sqlite3"
        self.host = GuiHost(self.book, "U001", session_path=self.session, mode="mock",
                            model=lambda *args: self.fail("structured import must not call a model"))
        self.addCleanup(self.host.close)
        self.server = GuiServer(("127.0.0.1", 0), self.host, "page-token", "<html></html>")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)
        self.url = "http://127.0.0.1:" + str(self.server.server_port) + "/api/import_workbook"

    def _stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def post(self, body, token="page-token"):
        request = urllib.request.Request(
            self.url, data=json.dumps(body).encode("utf-8"),
            headers={"X-GUI-Token": token, "Content-Type": "application/json"})
        try:
            response = urllib.request.urlopen(request)
            return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_route_accepts_single_docx_and_four_file_csv_but_rejects_mixed_shapes(self):
        context = self.host.snapshot()["context"]
        status, body = self.post({"name": WORD.name, "content": file_content(WORD), "context": context})
        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])
        self.assertEqual(body["snapshot"]["session"]["workbook"], str(self.book.resolve()))
        self.assertEqual(len(body["snapshot"]["settings"]["bindings"]), 4)
        context = body["snapshot"]["context"]
        status, body = self.post({"files": csv_files(), "context": context})
        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["snapshot"]["settings"]["bindings"]), 6)
        self.assertEqual(body["snapshot"]["session"]["workbook"], str(self.book.resolve()))
        context = body["snapshot"]["context"]
        status, body = self.post({"name": WORD.name, "content": file_content(WORD),
                                  "files": csv_files(), "context": context})
        self.assertEqual(status, 409)
        self.assertFalse(body["ok"])
        self.assertIn("不能同时提交", body["error"])
        status, body = self.post({"name": "发票.csv", "content": encode(b"x"), "context": context})
        self.assertEqual(status, 409)
        self.assertIn("四份固定文件", body["error"])
        status, body = self.post({"name": "x.xlsx", "content": encode(b"x"), "context": context})
        self.assertFalse(body["ok"])


if __name__ == "__main__":
    unittest.main()
