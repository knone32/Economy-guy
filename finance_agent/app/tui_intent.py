"""Bind only explicit user expressions to the current invoice edit."""
import re

from .responses import explicit_scope


_COMPANY = r"(?:甲企业|乙企业|C\d+)"
_INVOICE = r"F\d+"
_EDIT = re.compile(
    r"^(?:(?:请帮我|帮我|麻烦|请)\s*)?(?:(?:把|将)\s*(?P<target>[^。\n；;]*?)"
    r"(?:的\s*)?(?P<field>用途|备注)\s*(?P<verb>修改为|设置为|改成|改为|设为|清空)|"
    r"(?P<direct_verb>修改|更正|更新|补填|填写|清空)\s*(?P<direct>[^。\n；;]*?)(?P<direct_field>用途|备注))"
)
_SUPPLEMENT = re.compile(
    rf"^(?:(?:我说的是|企业是|企业为|发票号是|发票是|是)\s*)?"
    rf"(?:{_COMPANY}(?:[\s，,]*(?:的\s*)?{_INVOICE}|的)?|{_INVOICE})$", re.I
)
_CORRECTION = re.compile(
    rf"^(?:不是\s*(?P<old>{_COMPANY}|{_INVOICE})\s*[，,]\s*(?:而?是)|"
    r"(?P<kind>企业|发票(?:号)?)\s*(?:更正为|改为|改成|应为))\s*"
    rf"(?P<new>{_COMPANY}|{_INVOICE})(?:的)?$", re.I
)
_VALUE = re.compile(r"^(?P<replace>新值|用途|备注|新用途|新备注)?\s*(?:更正为|改为|改成|填成|填为|是|为|写)\s*(?P<value>.+)$")
_PLACEHOLDER = re.compile(r"(?:[.…?？_—\-·\s]+|待定|待补充|未指定|稍后再填)$")
_CANCEL = re.compile(r"^(?:算了(?:[，,]\s*)?)?(?:不修改了|不改了|取消(?:本次)?修改|取消)$")


def literal_value(text):
    text = text.strip()
    if (text.startswith("“") and text.endswith("”")) or (text.startswith('"') and text.endswith('"')):
        text = text[1:-1]
    return [text] if text.strip() and not _PLACEHOLDER.fullmatch(text) else []


def _edit_scope(match, text):
    target = match["target"] if match["target"] is not None else match["direct"]
    scope = explicit_scope(target, include_update_aliases=True)
    field = match["field"] or match["direct_field"]
    scope["field"] = ["purpose" if field == "用途" else "remark"]
    value = text[match.end():].strip()
    if (match["verb"] or match["direct_verb"]) == "清空":
        values = [""] if not value else []
    else:
        if not match["field"]:
            value = re.sub(r"^(?:修改为|设置为|改成|改为|设为|为)\s*", "", value)
        values = literal_value(value)
    if values:
        scope["new_value"] = values
    return scope


# These checks bind literal evidence, without deciding the target query.
_INVOICE_GROUP = rf"{_INVOICE}(?:\s*[、和及与]\s*{_INVOICE})*"
_EXCLUDED = re.compile(
    rf"(?:除了?|排除|不含|不包括)\s*(?P<before>{_INVOICE_GROUP})|"
    rf"(?P<after>{_INVOICE_GROUP})\s*(?:之外|以外|不要动|别动|不改|不修改|保持原样)", re.I,
)
_FIELD_NAMES = {"purpose": "用途", "remark": "备注"}
_HYPOTHETICAL = re.compile(r"^\s*(?:如果|假如|假设|例如|怎样|如何|能否|能不能)")


def invoice_intent_source(text):
    """Only explicit edit language may leave a read-only continuation clue."""
    return (not _HYPOTHETICAL.match(text) and re.search(r"发票|(?<![A-Za-z0-9])F\d+|这张|那张", text, re.I)
            and re.search(r"[改填补设写换][^，,。；;\n]{0,2}[为成]\s*\S|改一下|^\s*修改|(?:用途|备注)\s*修改\s*[。！!]?$", text))


def literal_single_invoice_edit(text):
    """Recognize a direct single-invoice assignment for read-only reconciliation."""
    text = text.strip().rstrip("。！!").strip()
    match = _EDIT.match(text)
    if (not match or not match["target"] or not match["verb"] or match["verb"] == "清空"
            or not re.fullmatch(rf"{_COMPANY}\s*(?:的\s*)?{_INVOICE}\s*(?:发票)?\s*(?:的\s*)?",
                                match["target"], re.I)
            or re.search(r"[，,；;。？！!?\n]", text[match.end():])):
        return None
    scope = _edit_scope(match, text)
    if all(len(scope.get(key, ())) == 1 for key in ("company_id", "invoice_no", "field", "new_value")):
        return scope
    return None


def invoice_supplement(text, missing):
    """A new request is never interpreted as a short literal supplement."""
    value = text.strip().rstrip("。！!").strip()
    if "year" in missing and re.fullmatch(r"\d{4}", value) and int(value):
        return {"year": [int(value)]}
    scope = explicit_scope(value, include_update_aliases=True)
    if {"year", "month"} & set(missing):
        month = r"(?:1[0-2]|0?[1-9]|十一|十二|[一二三四五六七八九十])\s*月份?"
        period = re.fullmatch(
            rf"(?:(?:我\s*)?(?:需要|想)?\s*(?:查询|查|看)\s*)?"
            rf"(\d{{4}}\s*年(?:\s*{month})?|{month})(?:\s*的)?", value)
        if period:
            return explicit_scope(period[1]) or None
    if {"company_id", "invoice_no", "invoice_reference"} & set(missing) and _SUPPLEMENT.fullmatch(value):
        return scope
    if "field" in missing and value in _FIELD_NAMES.values():
        return {"field": value}
    if "new_value" in missing and re.fullmatch(r"新值\s*(?:是|为)\s*.+", value):
        return {"new_value": value}
    return None


def invoice_change_evidence(text, field, new_value, *, rule_field=None):
    """Require a literal value and reject clear read-only, hypothetical or forbidden requests."""
    if not new_value.strip() or _HYPOTHETICAL.match(text) or text.rstrip().endswith(("?", "？")):
        return False
    label = _FIELD_NAMES[field]
    if rule_field is not None and field != rule_field:
        return False
    if re.search(rf"{label}\s*(?:别动|不要动|不改|不修改|保持原样)|(?:不改|不修改|不要修改|别改)\s*{label}", text):
        return False
    if label not in text and field != rule_field:
        return False

    literal = re.escape(new_value)
    value = rf'(?:“{literal}”|‘{literal}’|"{literal}"|{literal})'
    for match in re.finditer(rf"{value}(?=$|[\s，,。；;！!])", text):
        clause = re.split(r"[，,。；;\n]", text[:match.start()])[-1]
        if re.search(r"不要|别|禁止|不许|无需|不必", clause):
            continue
        # Match literal action evidence without parsing a specific field/verb sentence shape.
        mentioned = {name for name in _FIELD_NAMES.values() if name in clause}
        if ((mentioned and mentioned != {label}) or
                (not mentioned and rule_field is None and all(name in text for name in _FIELD_NAMES.values()))):
            continue
        if re.search(r"[改填补设写]|处理", clause) and not re.match(r"\s*(?:查询|查看|统计|列出|检查|解释|比较)", clause):
            return True
        if re.fullmatch(r"\s*新值\s*(?:是|为)\s*", clause) and invoice_intent_source(text):
            return True
    return False


def excluded_invoice_ids(text):
    return {invoice.upper() for match in _EXCLUDED.finditer(text)
            for invoice in re.findall(_INVOICE, match["before"] or match["after"], re.I)}


def edit_turn(text, pending, *, guided=False):
    text = text.strip().rstrip("。！!").strip()
    if pending and _CANCEL.fullmatch(text):
        return {"cancel": True}
    parts = re.split(r"\s*[，,；;。]?\s*(?:并且|并|然后|再)\s*"
                     r"(?=把|将|修改|更正|更新|补填|填写|清空)", text, maxsplit=1)
    if len(parts) == 2 and re.match(r"(?:先\s*)?(?:查询|查|汇总|列出|检查)", parts[0]):
        read_request, write_request = parts
        match = _EDIT.match(write_request)
        if match:
            scope = _edit_scope(match, write_request)
            value = write_request[match.end():].strip()
            quoted = re.fullmatch(r'“[^”]*”|"[^"]*"', value, re.S)
            if (not quoted and re.search(r"[，,；;。]|\n|(?:并且|并|然后|再)\s*(?:把|将|修改|更正|更新|清空|查询|查)", value)
                    or any(len(scope.get(key, ())) != 1 for key in ("company_id", "invoice_no", "field", "new_value"))):
                scope.pop("new_value", None)
            return {"allow_prepare": True, "edit_scope": scope, "read_request": read_request}
    match = _EDIT.match(text)
    if match:
        return {"allow_prepare": True, "edit_scope": _edit_scope(match, text)}
    if not pending:
        return {}
    correction = _CORRECTION.fullmatch(text)
    if correction:
        scope = explicit_scope(correction["new"], include_update_aliases=True)
        kind = correction["kind"]
        if kind and ("company_id" if kind == "企业" else "invoice_no") not in scope:
            return {}
        old = explicit_scope(correction["old"] or "", include_update_aliases=True)
        if old and (old.keys() != scope.keys() or any(
                pending["scope"].get(key) not in (None, value) for key, value in old.items())):
            return {}
        return {"continue_edit": True, "edit_scope": scope, "edit_correction": True}
    if _SUPPLEMENT.fullmatch(text):
        return {"continue_edit": True, "edit_scope": explicit_scope(text, include_update_aliases=True)}
    if text in {"清空", "留空", "设为空值"}:
        return {"continue_edit": True, "edit_scope": {"new_value": [""]}, "edit_correction": True}
    match = _VALUE.fullmatch(text)
    if match:
        label = match["replace"]
        if label in {"用途", "新用途", "备注", "新备注"}:
            expected = "purpose" if label.endswith("用途") else "remark"
            if pending["scope"].get("field") != [expected]:
                return {}
        values = literal_value(match["value"])
        if values:
            return {"continue_edit": True, "edit_scope": {"new_value": values}, "edit_correction": True}
    # An unlabeled sentence is never assumed to be a value. The user can explicitly
    # bind literal text with the supplement control and quote the complete value.
    if guided and text.startswith(("“", '"')) and text.endswith(("”", '"')) and literal_value(text):
        return {"continue_edit": True, "edit_scope": {"new_value": literal_value(text)}, "edit_correction": True}
    return {}
