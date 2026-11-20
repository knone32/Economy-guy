"""User-owned immutable source versions. Upload never publishes executable rules."""
import json
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile, BadZipFile
from io import BytesIO
import xml.etree.ElementTree as ET

from .permissions import check_permission
from .stage2_schema import open_existing


DDL = """
CREATE TABLE IF NOT EXISTS materials (
 material_id TEXT PRIMARY KEY, owner TEXT NOT NULL, company_id TEXT NOT NULL,
 name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS material_versions (
 material_id TEXT NOT NULL REFERENCES materials(material_id), version INTEGER NOT NULL,
 sha256 TEXT NOT NULL, original BLOB NOT NULL, PRIMARY KEY(material_id,version),
 UNIQUE(material_id,sha256));
CREATE TABLE IF NOT EXISTS material_paragraphs (
 material_id TEXT NOT NULL, version INTEGER NOT NULL, paragraph_id INTEGER NOT NULL,
 text TEXT NOT NULL, PRIMARY KEY(material_id,version,paragraph_id),
 FOREIGN KEY(material_id,version) REFERENCES material_versions(material_id,version));
CREATE TABLE IF NOT EXISTS material_locations (
 material_id TEXT NOT NULL, version INTEGER NOT NULL, paragraph_id INTEGER NOT NULL,
 source_type TEXT NOT NULL, location_json TEXT NOT NULL,
 PRIMARY KEY(material_id,version,paragraph_id),
 FOREIGN KEY(material_id,version,paragraph_id)
 REFERENCES material_paragraphs(material_id,version,paragraph_id));
CREATE TABLE IF NOT EXISTS rule_material_sources (
 rule_id TEXT NOT NULL, rule_version TEXT NOT NULL, material_id TEXT NOT NULL,
 version INTEGER NOT NULL, paragraph_id INTEGER NOT NULL, effective_to TEXT,
 PRIMARY KEY(rule_id,rule_version),
 FOREIGN KEY(rule_id,rule_version) REFERENCES rules(rule_id,version),
 FOREIGN KEY(material_id,version,paragraph_id)
 REFERENCES material_paragraphs(material_id,version,paragraph_id));
"""


def migrate(path):
    connection = open_existing(path)
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + DDL + "COMMIT;")
    finally:
        connection.close()


def _authorize(connection, user_id, company_id):
    if not check_permission(connection, user_id, company_id, "read").allowed:
        raise PermissionError("没有资料企业读取权限")


class _NoDoctype(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise ValueError('不支持Word实体声明')


def _paragraphs(payload):
    try:
        with ZipFile(BytesIO(payload)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > 8_000_000:
                raise ValueError("Word正文过大")
            xml = archive.read(info)
        # ElementTree does not resolve external entities; reject DTDs explicitly.
        if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
            raise ValueError("不支持Word实体声明")
        root = ET.fromstring(xml, parser=ET.XMLParser(target=_NoDoctype()))
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = ["".join((node.text or "") if node.tag == ns + "t" else
                              "\t" if node.tag == ns + "tab" else "\n"
                              for node in paragraph.iter()
                              if node.tag in {ns + "t", ns + "tab", ns + "br"})
                      for paragraph in root.iter(ns + "p")]
        if not any(text.strip() for text in paragraphs):
            raise ValueError("Word无可读取正文")
        return paragraphs
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError("Word解析失败，仅支持有效docx") from exc


def import_docx(path, user_id, company_id, source_path, name=None, material_id=None):
    if Path(source_path).suffix.lower() != '.docx':
        raise ValueError('仅支持docx资料')
    return import_material(path, user_id, company_id, source_path, name, material_id)


def import_material(path, user_id, company_id, source_path, name=None, material_id=None):
    source = Path(source_path)
    kind = source.suffix.lower().lstrip('.')
    if kind not in {'docx', 'xlsx', 'pdf'}:
        raise ValueError('仅支持docx、xlsx和文字PDF资料')
    name = source.name if name is None else name
    if type(name) is not str or not name.strip() or len(name) > 255:
        raise ValueError("资料名称无效")
    connection = open_existing(path)
    try:
        _authorize(connection, user_id, company_id)
    finally:
        connection.close()
    if source.stat().st_size > 10_000_000:
        raise ValueError("资料文件过大")
    payload = source.read_bytes()
    if len(payload) > 10_000_000:
        raise ValueError('资料文件过大')
    if kind == 'docx':
        units = [(text, {'kind': 'word_paragraph', 'paragraph': i})
                 for i, text in enumerate(_paragraphs(payload), 1)]
    else:
        from .material_readers import read_units
        units = read_units(payload, kind)
    paragraphs = [text for text, _ in units]  # Complete parse before any mutation.
    digest = sha256(payload).hexdigest()
    migrate(path)
    connection = open_existing(path)
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            _authorize(connection, user_id, company_id)
            row = None
            if material_id is not None:
                row = connection.execute("SELECT material_id FROM materials WHERE material_id=? AND owner=? AND company_id=?",
                                         (material_id, user_id, company_id)).fetchone()
                if row is None:
                    raise PermissionError("更新资料不存在或不可访问")
            duplicate = connection.execute("""SELECT v.material_id,v.version FROM material_versions v
                JOIN materials m USING(material_id) WHERE owner=? AND company_id=? AND sha256=?""",
                (user_id, company_id, digest)).fetchone()
            if duplicate and (material_id is None or duplicate["material_id"] == material_id):
                return {"status": "NO_CHANGE", "material_id": duplicate["material_id"], "version": duplicate["version"],
                        "sha256": digest, "paragraph_count": len(paragraphs), "published": False}
            material_id = row[0] if row else uuid4().hex
            if row is None:
                connection.execute("INSERT INTO materials VALUES (?,?,?,?)", (material_id, user_id, company_id, name))
            old = connection.execute("SELECT version FROM material_versions WHERE material_id=? AND sha256=?",
                                     (material_id, digest)).fetchone()
            if old:
                version, status = old[0], "NO_CHANGE"
            else:
                version = connection.execute("SELECT COALESCE(MAX(version),0)+1 FROM material_versions WHERE material_id=?",
                                             (material_id,)).fetchone()[0]
                connection.execute("INSERT INTO material_versions VALUES (?,?,?,?)", (material_id, version, digest, payload))
                connection.executemany("INSERT INTO material_paragraphs VALUES (?,?,?,?)",
                                       [(material_id, version, i, text) for i, text in enumerate(paragraphs, 1)])
                connection.executemany('INSERT INTO material_locations VALUES (?,?,?,?,?)',
                    [(material_id, version, i, kind, json.dumps(location, ensure_ascii=False))
                     for i, (_, location) in enumerate(units, 1)])
                status = "SUCCESS_CHANGED"
        return {"status": status, "material_id": material_id, "version": version,
                "sha256": digest, "paragraph_count": len(paragraphs), "published": False}
    finally:
        connection.close()


def get_paragraph(connection, user_id, material_id, version, paragraph_id):
    row = connection.execute("""SELECT m.owner,m.company_id,m.name,p.*,v.sha256
        FROM material_paragraphs p JOIN materials m USING(material_id)
        JOIN material_versions v USING(material_id,version)
        WHERE p.material_id=? AND p.version=? AND p.paragraph_id=?""",
        (material_id, version, paragraph_id)).fetchone()
    if row is None or row["owner"] != user_id:
        raise PermissionError("资料不存在或不可访问")
    _authorize(connection, user_id, row["company_id"])
    result = {key: row[key] for key in ("material_id", "version", "paragraph_id", "company_id", "name", "text", "sha256")}
    # Pre-migration Word sources remain readable without writing on a read path.
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='material_locations'").fetchone()
    location = connection.execute('SELECT source_type,location_json FROM material_locations WHERE material_id=? AND version=? AND paragraph_id=?',
                                  (material_id, version, paragraph_id)).fetchone() if exists else None
    result['source_type'] = location['source_type'] if location else 'docx'
    result['location'] = json.loads(location['location_json']) if location else {'kind': 'word_paragraph', 'paragraph': paragraph_id}
    return result


def source_label(source):
    location = source.get('location', {})
    if location.get('kind') == 'excel_row':
        return f"工作表“{location['sheet']}” · 原第{location['row']}行"
    if location.get('kind') == 'pdf_page':
        return f"PDF第{location['page']}页"
    return f"Word第{source['paragraph_id']}段"


def list_materials(connection, user_id, company_id):
    _authorize(connection, user_id, company_id)
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='materials' AND type='table'").fetchone()
    if not exists:
        return []
    return [dict(row) for row in connection.execute("""SELECT m.material_id,m.name,v.version,v.sha256,
        (SELECT COUNT(*) FROM material_paragraphs p WHERE p.material_id=m.material_id AND p.version=v.version) paragraph_count
        FROM materials m JOIN material_versions v USING(material_id)
        WHERE owner=? AND company_id=? ORDER BY m.name,v.version""", (user_id, company_id))]
