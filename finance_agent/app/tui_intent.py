"""Conservative natural-language entry to trusted preparation, never to Commit."""
import re

from .responses import explicit_scope


_EDIT = re.compile(
    r"^(?:(?:请|麻烦|帮我|请帮我)\s*)?(?:(?:把|将)\s*(?P<target>[^。\n；;]*?)"
    r"(?:的\s*)?(?P<field>用途|备注)\s*(?:改成|改为|修改为|设为|设置为)|"
    r"(?:修改|更正|更新|补填|填写)\s*(?P<direct>[^。\n；;]*?)(?P<direct_field>用途|备注))"
)
_SUPPLEMENT = re.compile(
    r"^(?:(?:是|企业是|企业为|发票是|发票号是)\s*)?"
    r"(?:(?:甲企业|乙企业|C\d+)(?:[\s，,]*(?:的\s*)?F\d+)?|F\d+)[。！!]?$", re.I
)


def edit_turn(text, pending, *, guided=False):
    """Return fresh intent or narrowly scoped follow-up from user text."""
    text = text.strip()
    match = _EDIT.match(text)
    if match:
        target = match["target"] if match["target"] is not None else match["direct"]
        scope = explicit_scope(target, include_update_aliases=True)
        field = match["field"] or match["direct_field"]
        scope["field"] = ["purpose" if field == "用途" else "remark"]
        if match["field"]:
            value = text[match.end():].strip().removesuffix("。").strip()
            if value.startswith(("“", '"')) and value.endswith(("”", '"')):
                value = value[1:-1]
            if value:
                scope["new_value"] = [value]
        return {"allow_prepare": True, "edit_scope": scope}
    if pending and (_SUPPLEMENT.fullmatch(text) or guided):
        scope = explicit_scope(text, include_update_aliases=True) if _SUPPLEMENT.fullmatch(text) else {}
        return {"continue_edit": True, "edit_scope": scope}
    return {}
