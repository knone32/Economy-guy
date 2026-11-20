"""Synthetic file provenance; temporary DB only, no model or business writes."""
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import closing
import sqlite3
from io import BytesIO
from zipfile import ZipFile
import re
import unittest
from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from app.stage2_schema import migrate
from app.materials import import_material, get_paragraph, list_materials, import_docx
from tests.helpers import DatabaseTestCaseMixin


def pdf_pages(path, texts):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 12 Tf 50 750 Td (' + text + ') Tj ET').encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    with path.open('wb') as output:
        writer.write(output)


class MaterialFormatTests(DatabaseTestCaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        migrate(self.db_path)
        self.folder = Path(self.temp.name)

    def excel(self, text='Travel policy'):
        path = self.folder / 'policy.xlsx'
        book = Workbook()
        sheet = book.active
        sheet.title = 'Policy original'
        sheet['A1'] = 'Rule'
        sheet['A4'] = text
        sheet['B4'] = '=1+2'
        book.create_sheet('Second sheet')['C7'] = 'Source item'
        book.save(path)
        book.close()
        return path

    def test_excel_original_rows_formula_dedup_and_version(self):
        path = self.excel()
        before = list(self.connection.execute('SELECT * FROM invoices'))
        first = import_material(self.db_path, 'U001', 'C001', path)
        source = get_paragraph(self.connection, 'U001', first['material_id'], 1, 2)
        self.assertEqual(source['location'], {'kind': 'excel_row', 'sheet': 'Policy original', 'row': 4})
        self.assertIn('=1+2', source['text'])
        self.assertEqual(source['source_type'], 'xlsx')
        self.assertEqual(import_material(self.db_path, 'U001', 'C001', path)['status'], 'NO_CHANGE')
        path = self.excel('Revised policy')
        second = import_material(self.db_path, 'U001', 'C001', path, material_id=first['material_id'])
        self.assertEqual(second['version'], 2)
        self.assertEqual(get_paragraph(self.connection, 'U001', first['material_id'], 1, 2), source)
        self.assertEqual(get_paragraph(self.connection, 'U001', first['material_id'], 2, 3)['location'],
                         {'kind': 'excel_row', 'sheet': 'Second sheet', 'row': 7})
        self.assertEqual(list(self.connection.execute('SELECT * FROM invoices')), before)
        self.assertFalse(second['published'])

    def test_pdf_page_and_private_reference(self):
        path = self.folder / 'policy.pdf'
        pdf_pages(path, ['Policy version one', 'Second page original'])
        result = import_material(self.db_path, 'U001', 'C001', path)
        self.assertEqual(result['paragraph_count'], 2)
        source = get_paragraph(self.connection, 'U001', result['material_id'], 1, 2)
        self.assertEqual(source['location'], {'kind': 'pdf_page', 'page': 2})
        self.assertIn('Second page original', source['text'])
        with self.assertRaises(PermissionError):
            get_paragraph(self.connection, 'U002', result['material_id'], 1, 2)
        self.connection.execute("UPDATE permissions SET can_read=0 WHERE user_id='U001' AND company_id='C001'")
        self.connection.commit()
        with self.assertRaises(PermissionError):
            get_paragraph(self.connection, 'U001', result['material_id'], 1, 2)

    def test_invalid_and_image_only_pdf_and_unauthorized_file(self):
        path = self.folder / 'invalid.pdf'
        path.write_bytes(b'broken')
        with self.assertRaises(ValueError):
            import_material(self.db_path, 'U001', 'C001', path)
        pdf_pages(path, [''])
        with self.assertRaisesRegex(ValueError, '文字|正文'):
            import_material(self.db_path, 'U001', 'C001', path)
        with self.assertRaises(PermissionError):
            import_material(self.db_path, 'U002', 'C002', self.excel())
        self.assertEqual(list_materials(self.connection, 'U001', 'C001'), [])

    def test_empty_workbook_does_not_create_new_version(self):
        first = import_material(self.db_path, 'U001', 'C001', self.excel())
        path = self.folder / 'empty.xlsx'
        book = Workbook()
        book.save(path)
        book.close()
        with self.assertRaises(ValueError):
            import_material(self.db_path, 'U001', 'C001', path, material_id=first['material_id'])
        self.assertEqual(len(list_materials(self.connection, 'U001', 'C001')), 1)

    def rewrite_sheet(self, path, transform):
        buffer = BytesIO()
        with ZipFile(path) as source, ZipFile(buffer, 'w') as target:
            for name in source.namelist():
                content = source.read(name)
                if name == 'xl/worksheets/sheet1.xml':
                    content = transform(content)
                target.writestr(name, content)
        path.write_bytes(buffer.getvalue())

    def test_excel_missing_or_understated_dimension_keeps_actual_original_rows(self):
        for dimension in (b'', b'<dimension ref="A1:A1"/>'):
            with self.subTest(dimension=dimension):
                path = self.excel()
                self.rewrite_sheet(path, lambda xml: re.sub(rb'<dimension[^>]*/>', dimension, xml))
                result = import_material(self.db_path, 'U001', 'C001', path)
                source = get_paragraph(self.connection, 'U001', result['material_id'], 1, 2)
                self.assertEqual(source['location']['row'], 4)
                self.assertIn('Travel policy', source['text'])

    def test_bad_excel_xml_is_explicit_failure_and_creates_no_version(self):
        path = self.excel()
        self.rewrite_sheet(path, lambda xml: b'<worksheet>')
        with self.assertRaisesRegex(ValueError, 'Excel解析失败'):
            import_material(self.db_path, 'U001', 'C001', path)
        self.assertEqual(list_materials(self.connection, 'U001', 'C001'), [])

    def test_word_rejects_doctype_independent_of_xml_encoding(self):
        xml = '''<?xml version="1.0" encoding="ENCODING"?>
<!DOCTYPE document [<!ENTITY item "ENTITY TEXT">]>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:p><w:r><w:t>&item;</w:t></w:r></w:p></w:body></w:document>'''
        path = self.folder / 'source.docx'
        for encoding in ('utf-8', 'utf-16'):
            with self.subTest(encoding=encoding):
                with ZipFile(path, 'w') as archive:
                    archive.writestr('word/document.xml', xml.replace('ENCODING', encoding).encode(encoding))
                with self.assertRaisesRegex(ValueError, '实体声明'):
                    import_docx(self.db_path, 'U001', 'C001', path)
        self.assertEqual(list_materials(self.connection, 'U001', 'C001'), [])


class MaterialFormatWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_dedup_update_and_reopen_original_through_workbench(self):
        from app.cli_workspaces import import_workspace
        from app.model_config import DEFAULT_TEMPLATE
        from app.tui import AgentWorkspace
        from tests.test_tui_p0 import P0Test, FIXTURE
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / 'book.db'
            import_workspace(FIXTURE, database)
            filename = root / 'source.xlsx'
            workbook = Workbook()
            workbook.active.title = 'Original sheet'
            workbook.active['B5'] = 'Original row text'
            workbook.save(filename)
            workbook.close()
            calls = []
            def no_model(*args, **kwargs):
                calls.append(True)
                raise AssertionError('File commands must not invoke model')
            app = AgentWorkspace(database, DEFAULT_TEMPLATE, root / 'absent.json', model=no_model,
                                 session_path=root / 'sessions.db')
            app.mode = 'mock'
            helper = P0Test()
            async with app.run_test(size=(150, 42)) as pilot:
                await helper.sign_in(app, pilot)
                command = '/material-upload C001 "' + filename.as_posix() + '"'
                await helper.send(app, pilot, command)
                await pilot.pause()
                with closing(sqlite3.connect(database)) as connection:
                    material = connection.execute('SELECT material_id FROM materials').fetchone()[0]
                await helper.send(app, pilot, command)
                await pilot.pause()
                workbook = Workbook()
                workbook.active['B5'] = 'New version text'
                workbook.save(filename)
                workbook.close()
                await helper.send(app, pilot, '/material-update C001 ' + material + ' "' + filename.as_posix() + '"')
                await pilot.pause()
                await helper.send(app, pilot, '/source ' + material + ' 1 1')
                await pilot.pause()
                chat = '\n'.join(line.text for line in app.workspace_widget('#chat-log').lines)
                self.assertIn('Original row text', chat)
                self.assertIn('Original sheet', chat)
                self.assertIn('NO_CHANGE', chat)
                with closing(sqlite3.connect(database)) as connection:
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM material_versions').fetchone()[0], 2)
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM invoice_audit').fetchone()[0], 0)
                with closing(sqlite3.connect(database)) as connection:
                    connection.row_factory = sqlite3.Row
                    source = get_paragraph(connection, 'U001', material, 1, 1)
                card = app.business_card('open_material_reference', source, {})
                self.assertIn('原第5行', card[1])
            self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
