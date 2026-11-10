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


def quoted_edit_candidate(text):
    """Extract a uniquely quoted user value; this is evidence, never permission."""
    if (re.search(r"(?:不用|无需|不必|跳过).{0,12}确认|[?？]|(?:不要|别)\s*(?:修改|改|换)", text)
            or re.match(r"\s*(?:请\s*)?(?:查询|查看|列出|核对|假设|如果|例如)", text)):
        return None
    values = list(re.finditer(
        r"(?:换成|改成|修改为|设置为|填成|写成|设为)\s*(?:“([^”]*)”|‘([^’]*)’|\"([^\"]*)\")",
        text,
    ))
    if len(values) != 1:
        return None
    match = values[0]
    prefix = text[:match.start()]
    if not re.search(r"发票|单据|单子|这张|那张", prefix):
        return None
    fields = {"purpose" if item == "用途" else "remark" for item in re.findall(r"用途|备注", prefix)}
    value = next((part for part in match.groups() if part is not None), "")
    if len(fields) != 1 or not value.strip():
        return None
    return {"field": fields.pop(), "new_value": value}


_BATCH_START = r"^(?:(?:请帮我|帮我|麻烦|请)\s*)?(?:把|将)\s*"
_BATCH_SET = r"(?:所有|全部)"
_BATCH_ACTION = r"(?:修改为|改成|改为|填成|填为|设置为)"
_BATCH_EDIT = re.compile(
    _BATCH_START + rf"(?P<company>{_COMPANY}|[甲乙]公司)\s*"
    r"(?P<period>\d{4}\s*(?:年\s*\d{1,2}\s*月|[-/]\s*\d{1,2}))\s*(?:的\s*)?"
    r"(?:(?P<selector>用途为空|备注为空|有备注|必填用途缺失)\s*的\s*)?"
    rf"(?:(?P<all_before>{_BATCH_SET})\s*(?:的\s*)?)?发票"
    r"(?:\s*的?\s*(?P<field>用途|备注))?\s*(?P<all_after>全部|都|统一|批量)?\s*"
    rf"{_BATCH_ACTION}\s*(?P<value>.+)$", re.I,
)
_BATCH_INTENT = re.compile(
    _BATCH_START + r"(?P<target>[^，,。；;？?\n]*?发票[^，,。；;？?\n]*?)"
    rf"(?P<action>{_BATCH_ACTION}|改掉|改一下|清空|修改|改)\s*(?P<value>.*)$", re.I,
)
_BATCH_MODES = {
    "逐项确认": "item", "逐张确认": "item", "一张张让我确认": "item",
    "整批确认": "batch", "一次确认": "batch", "一次确认后自动处理": "auto", "自动连续处理": "auto",
}
_BATCH_SELECTORS = {
    "用途为空": "purpose_blank", "备注为空": "remark_blank", "有备注": "remark_present",
    "必填用途缺失": "required_purpose_missing",
}


def _batch_request_hint(text):
    match = _BATCH_INTENT.fullmatch(text)
    if not match:
        return None
    target = match["target"]
    scope = explicit_scope(target, include_update_aliases=True)
    explicit_set = re.search(rf"{_BATCH_SET}\s*(?:的\s*)?发票", target)
    plural_target = re.search(r"发票\s*(?:的?\s*(?:用途|备注))?\s*(?:全部|都|统一|批量)\s*$", target)
    single = scope.get("invoice_no") or re.search(r"(?:第[^张]{1,8}|这|那|某|单|一)张", target)
    if not explicit_set and (not plural_target or single):
        return None
    missing = []
    if len(scope.get("company_id", ())) != 1:
        missing.append("一个明确的企业")
    if any(len(scope.get(key, ())) != 1 for key in ("periods", "year", "month")):
        missing.append("完整且唯一的年月（例如 2026 年 9 月）")
    if not re.fullmatch(_BATCH_ACTION, match["action"]) or not match["value"].strip():
        missing.append("具体新值")
    if missing:
        return "批量修改还需要：" + "、".join(missing) + "。"
    return "无法核定批量集合。请明确该月的所有发票，或使用用途为空、备注为空、有备注、必填用途缺失筛选。"


def batch_edit_request(text):
    """Return a trusted batch request, an actionable hint, or None for ordinary chat."""
    text = text.strip().rstrip("。！!").strip()
    match = _BATCH_EDIT.fullmatch(text)
    if not match:
        return _batch_request_hint(text)
    selector = _BATCH_SELECTORS.get(match["selector"])
    if not (match["all_before"] or match["all_after"]):
        return "请明确是否要修改全部匹配发票。" if selector else None
    scope = explicit_scope(match["company"] + " " + match["period"], include_update_aliases=True)
    if len(scope.get("periods", ())) != 1 or not scope["periods"][0][0]:
        return "批量修改需要完整且有效的年月（例如 2026 年 9 月）。"
    mode_suffix = re.search(r"[，,]\s*(" + "|".join(_BATCH_MODES) + r")$", match["value"])
    mode = _BATCH_MODES[mode_suffix[1]] if mode_suffix else "item"
    if selector is None:
        if not (match["all_before"] or match["all_after"] in {"全部", "都"}):
            return "请明确该月的所有发票，或指定支持的发票筛选。"
        if not match["field"]:
            return "请明确要批量修改用途还是备注。"
        selector = "all"
    value = (match["value"][:mode_suffix.start()] if mode_suffix else match["value"]).strip()
    if not re.fullmatch(r'“[^”]+”|‘[^’]+’|"[^"]+"|[^“”‘’"，,。！？?；;\r\n]+', value):
        return "请提供具体新值。新值含标点时请用引号包住，并在引号外指定确认方式。"
    if not value.startswith(("“", "‘", '"')) and re.search(
            r"(?:不用|无需|不必|跳过).{0,14}确认|(?:并且|并|然后|再)\s*(?:把|将|修改|更正|更新|清空|查询)", value):
        return "请提供独立的新值。批量修改需要逐张确认或整批授权。"
    if value.startswith("‘"):
        value = "“" + value[1:-1] + "”"
    values = literal_value(value)
    if not values:
        return "请提供具体新值。"
    field = match["field"] or ("备注" if selector.startswith("remark") else "用途")
    year, month = scope["periods"][0]
    return {"company_id": scope["company_id"][0], "year": year, "month": month,
            "selector": selector, "field": "remark" if field == "备注" else "purpose",
            "new_value": values[0], "mode": mode}


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
