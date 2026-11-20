"""Bounded, inert source units. Never evaluate formulas, macros or PDF actions."""
from datetime import date, datetime, time
from io import BytesIO
import json
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile

MAX_TEXT = 8_000_000
MAX_UNITS = 20_000


def _xlsx(payload):
    from openpyxl import load_workbook
    try:
        with ZipFile(BytesIO(payload)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 80_000_000:
                raise ValueError('Excel解压内容过大')
        book = load_workbook(BytesIO(payload), read_only=True, data_only=False, keep_links=False)
        units, size = [], 0
        try:
            for sheet in book:
                # Uploaded producers may omit or understate <dimension>. It is
                # a hint, never authority for the complete source contents.
                sheet.reset_dimensions()
                for row_index, row in enumerate(sheet.iter_rows(), 1):
                    if row_index > 100_000 or len(row) > 256:
                        raise ValueError('Excel工作表范围过大')
                    cells = []
                    for cell in row:
                        if cell.value is None:
                            continue
                        value = cell.value
                        if isinstance(value, (date, datetime, time)):
                            value = value.isoformat()
                        cells.append({'cell': cell.coordinate, 'type': cell.data_type, 'value': value})
                    if not cells:
                        continue
                    text = json.dumps(cells, ensure_ascii=False, allow_nan=False, default=str)
                    size += len(text)
                    if size > MAX_TEXT or len(units) >= MAX_UNITS:
                        raise ValueError('Excel可读取内容过大')
                    units.append((text, {'kind': 'excel_row', 'sheet': sheet.title, 'row': row_index}))
        finally:
            book.close()
        if not units:
            raise ValueError('Excel无可读取正文')
        return units
    except (BadZipFile, KeyError, ET.ParseError) as error:
        raise ValueError('Excel解析失败，仅支持有效xlsx') from error


def _pdf(payload):
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as error:
        raise ValueError('文字PDF读取需要pypdf依赖') from error
    try:
        reader = PdfReader(BytesIO(payload), strict=True)
        if reader.is_encrypted:
            raise ValueError('不支持加密PDF')
        if len(reader.pages) > 1000:
            raise ValueError('PDF页数过多')
        units, size = [], 0
        for index, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ''
            size += len(text)
            if size > MAX_TEXT:
                raise ValueError('PDF文字正文过大')
            units.append((text, {'kind': 'pdf_page', 'page': index}))
        if not any(text.strip() for text, _ in units):
            raise ValueError('PDF无可读取文字正文；不支持扫描件OCR')
        return units
    except (PdfReadError, KeyError, TypeError) as error:
        raise ValueError('PDF解析失败，仅支持有效文字PDF') from error


def read_units(payload, kind):
    return {'xlsx': _xlsx, 'pdf': _pdf}[kind](payload)
