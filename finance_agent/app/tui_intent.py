"""Bind only explicit user expressions to the current invoice edit."""
import re

from .responses import explicit_scope


_COMPANY = r"(?:甲企业|乙企业|C\d+)"
_INVOICE = r"F\d+"
_EXPLICIT_MONTH = (r"\d{4}\s*(?:年\s*(?:的\s*)?(?:1[0-2]|0?[1-9]|十一|十二|[一二三四五六七八九十])\s*月"
                   r"|[-/]\s*(?:1[0-2]|0?[1-9]))")
_INVOICE_OWNER_MONTH = rf"(?:{_COMPANY}\s*(?:的\s*)?{_EXPLICIT_MONTH}|{_EXPLICIT_MONTH}\s*(?:的\s*)?{_COMPANY})"
_NAMED_INVOICES = rf"{_INVOICE}(?:\s*(?:以及|[、和及与，,])\s*{_INVOICE})+"
_ASSIGNMENT = r"修改为|设置为|改成|改为|设为"
_ASSIGNED_VALUE = (r'“[^”\r\n]+”|"[^"\r\n]+"|「[^」\r\n]+」|『[^』\r\n]+』'
                   r'|[^，,；;。！？!?（）()\[\]【】\r\n“”"「」『』]+')
_JOINT_TARGET = rf"{_COMPANY}\s*(?:的\s*)?{_INVOICE}\s*(?:发票)?\s*(?:的\s*)?"
_EDIT = re.compile(
    r"^(?:(?:请帮我|帮我|麻烦|请)\s*)?(?:(?:把|将)\s*(?P<target>[^。\n；;]*?)"
    rf"(?:的\s*)?(?P<field>用途|备注)\s*(?P<verb>{_ASSIGNMENT}|清空)|"
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
    quotes = (("“", "”"), ('"', '"'), ("「", "」"), ("『", "』"))
    if any(text.startswith(start) and text.endswith(end) for start, end in quotes):
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
_NEGATED_EDIT = re.compile(r"不|别|禁止|无需")
_QUOTED_TEXT = re.compile(r'“[^”\r\n]*”|‘[^’\r\n]*’|「[^」\r\n]*」|『[^』\r\n]*』|"[^"\r\n]*"')


_EDIT_ACTION = r"[改填补设写换]"


def invoice_intent_source(text):
    """Only explicit edit language may leave a read-only continuation clue."""
    action_text = _QUOTED_TEXT.sub("值", text)
    return (not _HYPOTHETICAL.match(text) and re.search(r"发票|(?<![A-Za-z0-9])F\d+|这张|那张|(?:把|将)\s*[它他]", text, re.I)
            and re.search(rf"{_EDIT_ACTION}[^，,。；;\n]{{0,2}}[为成]\s*\S|改一下|^\s*修改|(?:用途|备注)\s*修改\s*[。！!]?$", action_text))


def literal_single_invoice_edit(text, *, reference=None, allow_deictic=False):
    """Recognize a direct single-invoice assignment for read-only reconciliation."""
    text = text.strip().rstrip("。！!").strip()
    match = _EDIT.match(text)
    if (not match or not match["target"] or not match["verb"] or match["verb"] == "清空"
            or re.search(r"[，,；;。？！!?\n]", text[match.end():])):
        return None
    scope = _edit_scope(match, text)
    reference_target = r"[它他]"
    if allow_deictic:
        reference_target = rf"(?:{reference_target}|[这那](?:一)?张(?:发票|票)?)"
    if reference is not None and re.fullmatch(rf"{reference_target}\s*(?:的\s*)?", match["target"]):
        scope.update({key: [reference[key]] for key in ("company_id", "invoice_no")})
    elif not re.fullmatch(_JOINT_TARGET, match["target"], re.I):
        return None
    if all(len(scope.get(key, ())) == 1 for key in ("company_id", "invoice_no", "field", "new_value")):
        return scope
    return None


def literal_named_invoice_edit(text):
    """Bind a plain named list with one explicit company, month, field and value."""
    text = text.strip().rstrip("。！!").strip()
    text = re.sub(r"^(?:请帮我|帮我|麻烦|请)\s*", "", text)
    leading = re.match(r"(?:把|将)\s*", text)
    separator = r"\s*(?:的\s*)?" if leading else r"\s*[，,：:]\s*"
    if leading:
        text = text[leading.end():]
    target = (rf"{_INVOICE_OWNER_MONTH}\s*(?:的\s*)?(?:发票\s*)?{_NAMED_INVOICES}"
              r"(?:\s*(?:这\s*)?(?P<count>[1-9][0-9]?|[一二两三四五六七八九十])\s*张)?\s*(?:发票)?")
    match = re.fullmatch(
        rf"(?P<target>{target}){separator}"
        rf"(?P<field>用途|备注)\s*(?:都|均|一并|统一|分别)?\s*(?:{_ASSIGNMENT}|填成|填为)\s*"
        r'(?P<value>“[^”\r\n]+”|"[^"\r\n]+"|[^，,。；;：:！？!?（）()\[\]【】［］{}｛｝\r\n“”"]+)'
        rf"(?:\s*[，,；;]\s*排除\s*(?P<excluded>{_INVOICE_GROUP}))?"
        r"(?:\s*[，,；;]\s*(?P<batch>(?:请\s*)?(?:整批|一次性)确认))?",
        text, re.IGNORECASE)
    if not match:
        return None
    value = match["value"].strip()
    values = literal_value(value)
    if not values or (value[0] not in ('“', '"') and re.search(
            r"如果|若|假如|除非|前提|仅(?:限|当)|只(?:限|有|在|改)|"
            r"(?:金额|价税)\s*(?:超过|大于|小于|不少于)|(?:再|另|并)(?:查|改)", value)):
        return None
    excluded = {number.upper() for number in re.findall(_INVOICE, match["excluded"] or "", re.I)}
    if excluded != excluded_invoice_ids(text):
        return None
    scope = explicit_scope(match["target"], include_update_aliases=True)
    count = match["count"]
    if count:
        size = int(count) if count.isdigit() else "一二三四五六七八九十".index(
            "二" if count == "两" else count) + 1
        if len(scope["invoice_no"]) != size:
            return None
    return {**scope, "field": {"用途": "purpose", "备注": "remark"}[match["field"]],
            "new_value": values[0], "excluded": excluded,
            "batch_confirmation": bool(match["batch"])}


def unresolved_invoice_field(text, scope, *, candidate=None, recent_reference=False):
    """Extract only a literal value from a single assignment eligible for a field question."""
    text = text.strip().rstrip("。！!").strip()
    if any(label in text for label in _FIELD_NAMES.values()):
        return None
    match = re.fullmatch(
        rf"(?:(?P<marker>把|将)\s*)?(?P<target>[^，,。；;？！!?\r\n]+?)\s*(?:{_ASSIGNMENT})\s*"
        r"(?P<value>[^，,。；;？！!?\r\n]+)", text)
    if not match:
        return None
    target = match["target"]
    values = literal_value(match["value"])
    if not values:
        return None
    if re.fullmatch(_JOINT_TARGET, target, re.I):
        explicit = explicit_scope(target, include_update_aliases=True)
        if all(explicit.get(key) == [scope[key]] for key in ("company_id", "invoice_no")):
            return values[0], None
    if candidate and values[0] != candidate["new_value"]:
        return None
    labels = (_FIELD_NAMES[candidate["field"]],) if candidate else _FIELD_NAMES.values()
    if candidate and match["marker"] and re.fullmatch(r"[\u3400-\u9fff]{1,3}", target):
        return values[0], labels[0]
    # A near match can only suggest a question about a verified reference.
    owner, separator, field = target.rpartition("的")
    field = field.strip()
    if (recent_reference and separator and (match["marker"] or re.search(r"[把将]", owner))
            and not (_HYPOTHETICAL.match(owner) or _NEGATED_EDIT.search(owner))
            and re.fullmatch(r"[\u3400-\u9fff]{2}", field)):
        matches = [label for label in labels
                   if sum(actual != expected for actual, expected in zip(field, label)) == 1]
        if len(matches) == 1:
            return values[0], matches[0]
    return None


def invoice_query_followup(text):
    """Bind a first invoice and an explicit request for one more in the same company."""
    scope = explicit_scope(text, include_update_aliases=True)
    numbers, companies = scope.get("invoice_no", ()), scope.get("company_id", ())
    if len(numbers) != 1 or len(companies) > 1 or invoice_intent_source(text):
        return None
    read = r"查询|查看|核实|查|看"
    # Keep the sequencing word with the following clause, where it can mark an additional read.
    clauses = re.split(rf"\s*[，,；;。！!?？]\s*|\s*(?=(?:然后|接着|再)\s*(?:{read}))", text)
    first = next((i for i, clause in enumerate(clauses)
                  if re.search(rf"\b{re.escape(numbers[0])}\b", clause, re.I | re.ASCII)), None)
    if first is None or not re.search(read, clauses[first]):
        return None

    later = clauses[first + 1:]
    more = rf"(?:还|再)(?:\s*(?:想|要|需要|有|也|请|帮我|顺便|多|{read})){{0,8}}\s*一张"
    another = re.compile(rf"另(?:外)?一张|第二张|{more}")
    rest = "，".join(later)
    if not any(another.search(clause) for clause in later):
        return None
    if not re.search(rf"{read}|(?:号码|编号|票号).{{0,12}}(?:发|给|补)", rest):
        return None
    if (re.search(r"(?:不(?:要|用|必|再)?|别|无[需须])\s*(?:再|去|先)?\s*(?:查|看|核实)", text)
            or re.search(r"不在|不同(?:一家|一?个)?(?:企业|公司)|别家|另一家", rest)):
        return None
    return {"company_id": companies[0] if companies else None, "invoice_no": numbers[0]}


_CHAIN_ITEM = r"第\s*[一二12]\s*张|首张|前一张|后一张|另(?:外)?一张"


def _chain_position(label):
    return "first" if re.sub(r"\s+", "", label) in {"第一张", "第1张", "首张", "前一张"} else "second"


def invoice_followup_action(text, chain):
    """Resolve an explicit continuation before generic display-list references."""
    literal = text.strip().rstrip("。！!?？").strip()
    literal = re.sub(r"^(?:请帮我|帮我|麻烦|请)\s*", "", literal)
    clauses = re.split(r"\s*[，,；;。！!?？]\s*", literal)
    clauses = [clause for clause in clauses if clause]
    kept = set()
    actions = []
    for clause in clauses:
        keep = re.fullmatch(rf"({_CHAIN_ITEM})(?:发票)?\s*(?:照旧|不变|保持原样|继续查)", clause)
        if keep:
            kept.add(_chain_position(keep[1]))
        else:
            actions.append(clause)

    retire = r"取消|撤掉|撤销"
    omit = rf"(?:先|就)?(?:{retire}|不(?:用|必)?(?:再)?(?:查|看|等)(?:了)?)"
    whole = r"(?:(?:这|本)(?:一)?轮|(?:两|二|2|这两)张(?:发票)?)(?:的)?(?:查询)?"
    cancelled = set()
    for clause in actions:
        if re.fullmatch(rf"(?:算了|{omit}|{whole}\s*{omit}|(?:{retire})\s*{whole})(?:吧)?", clause):
            cancelled.add("all")
            continue
        cancel = re.fullmatch(
            rf"(?:(?:只|仅)?(?:{retire})\s*(?P<before>{_CHAIN_ITEM})(?:发票)?|"
            rf"(?P<after>{_CHAIN_ITEM})(?:发票)?(?:的?\s*(?:查询|编号|票号))?\s*{omit})(?:吧)?", clause)
        if not cancel:
            break
        cancelled.add(_chain_position(cancel["before"] or cancel["after"]))
    else:
        if cancelled:
            if cancelled & kept or ("all" in cancelled and kept):
                return "clarify", None, {}
            position = "all" if "all" in cancelled or len(cancelled) == 2 else next(iter(cancelled))
            return "cancel", position, {}

    change = r"改查|改为|改成|更正为|应为|是|换成"
    correction = re.fullmatch(
        rf"(?:把|将)?\s*({_CHAIN_ITEM})(?:发票)?\s*(?:(?:的?编号\s*)?(?:{change})|"
        rf"(?:我)?(?:刚才)?(?:报错了|说错了|写错了)，\s*(?:{change}))\s*"
        rf"((?:{_COMPANY}\s*(?:的\s*|/\s*|编号\s*)?)?{_INVOICE})\s*(?:查一下|看一下|看看|吧)?",
        "，".join(actions), re.IGNORECASE)
    if correction:
        position = _chain_position(correction[1])
        if position not in kept:
            return "read", position, invoice_followup_key(correction[2])
        return "clarify", None, {}

    # Unclear control commands must not become a lookup of an ordinal in an unrelated list.
    control = (
        rf"^(?:(?:只|仅)?(?:{retire})\s*(?:{_CHAIN_ITEM}|{whole})|(?:把|将)\s*(?:{_CHAIN_ITEM})|"
        rf"(?:{_CHAIN_ITEM}|{whole})(?:发票)?(?:的?\s*(?:查询|编号|票号))?\s*"
        rf"(?:(?:我)?(?:刚才)?(?:报错|说错|写错)|改查|改为|改成|更正|应为|换成|{omit}))"
    )
    if kept or cancelled or any(re.match(control, clause) for clause in actions):
        return "clarify", None, {}

    replacement = _CORRECTION.fullmatch(literal)
    if replacement and replacement["old"]:
        positions = [position for position in ("first", "second")
                     if chain.item(position).invoice_no == replacement["old"].upper()]
        target = invoice_followup_key(replacement["new"])
        if len(positions) == 1 and "invoice_no" in target:
            return "read", positions[0], target

    position = chain.next_position()
    if position is not None:
        if re.fullmatch(rf"{_COMPANY}\s*(?:的\s*)?(?:/|编号(?:是|为)?)\s*{_INVOICE}", literal, re.I):
            return "read", position, invoice_followup_key(literal)
        supplied = invoice_supplement(literal, ("company_id", "invoice_no"))
        if supplied and ("invoice_no" in supplied or not chain.company_for(position)):
            return "read", position, {key: values[0] for key, values in supplied.items()}
    return None


def invoice_followup_key(text):
    scope = explicit_scope(text, include_update_aliases=True)
    return {key: values[0] for key, values in scope.items()}


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


def invoice_choice_reply(text):
    """Recognize a standalone response to a pending invoice-number question."""
    value = text.strip().rstrip("。！!").strip()
    if value == "算了" or _CANCEL.fullmatch(value):
        return {"cancel": True}
    value = re.sub(r"^(?:就选|就|选)\s*", "", value)
    value = re.sub(r"\s*(?:(?:这|那)(?:一)?张(?:发票|票)?\s*)?(?:吧|就行)?$", "", value).strip()
    supplied = invoice_supplement(value, ("invoice_no",))
    if supplied and supplied.get("invoice_no"):
        return supplied
    selected = re.fullmatch(
        rf"(?:(?:这次|本次)\s*)?(?:(?:复核|修改)\s*)?(?:标记|对象|目标|票号)\s*"
        rf"(?:落在|选择|选|是|为)\s*(?P<number>{_INVOICE})"
        rf"(?:\s*[，,]\s*(?P<keep>{_INVOICE_GROUP})\s*(?:保持原样|别动|不改))?", value, re.I)
    if not selected:
        return None
    number = selected["number"].upper()
    kept = {invoice.upper() for invoice in re.findall(_INVOICE, selected["keep"] or "", re.I)}
    return {"invoice_no": [number]} if number not in kept else None


def _quoted_invoice_choice(text):
    """Bind a literal label to one field while leaving the target unresolved."""
    match = re.fullmatch(
        rf"(?P<label>复核标签|备注内容|用途内容|新值)\s*(?P<value>{_ASSIGNED_VALUE})\s*"
        r"只加到这(?:两|2)笔中的(?:一|1)笔\s*[，,]\s*(?:写进|填入)\s*(?P<field>用途|备注)栏",
        text.strip().rstrip("。！!").strip())
    if (not match or match["value"][0] not in '“"「『'
            or not (values := literal_value(match["value"]))):
        return None
    if match["label"] in {"用途内容", "备注内容"} and not match["label"].startswith(match["field"]):
        return None
    return {"field": ["purpose" if match["field"] == "用途" else "remark"], "new_value": values}


def _questioned_invoice_choice(text):
    match = re.fullmatch(
        rf"(?P<owner>{_INVOICE_OWNER_MONTH})\s*(?:的\s*)?(?P<numbers>{_NAMED_INVOICES})\s*[，,]\s*"
        r"(?P<field>用途|备注)\s*各是什么\s*[？?]\s*(?P<assignment>.+)", text, re.I)
    if not match or not (change := _quoted_invoice_choice(match["assignment"])):
        return None
    read = f'查看 {match["owner"]} 的 {match["numbers"]} 的{match["field"]}'
    scope = explicit_scope(read, include_update_aliases=True)
    if len(scope["invoice_no"]) != 2:
        return None
    return {"read": read, "read_scope": scope, "write": match["assignment"],
            "write_scope": None, "pending_choice": change}


def invoice_change_boundary(text, field, new_value, *, rule_field=None):
    """Existing literal/negative checks, independent of positive action sentence forms."""
    if not new_value.strip() or _HYPOTHETICAL.match(text) or text.rstrip().endswith(("?", "？")):
        return False
    label = _FIELD_NAMES[field]
    if rule_field is not None and field != rule_field:
        return False
    if re.search(rf"{label}\s*(?:别动|不要动|不改|不修改|保持原样)|(?:不改|不修改|不要修改|别改)\s*{label}", text):
        return False
    if label not in text and field != rule_field:
        return False
    quotes = tuple(_QUOTED_TEXT.finditer(text))
    literal = re.escape(new_value)
    value = rf'(?:“{literal}”|‘{literal}’|"{literal}"|「{literal}」|『{literal}』|{literal}(?=$|[\s，,。；;！!]))'
    return any(not any(q.start() <= match.start() and match.end() <= q.end()
                       and q[0][1:-1] != new_value for q in quotes)
               for match in re.finditer(value, text))


def invoice_change_evidence(text, field, new_value, *, rule_field=None):
    """Legacy positive-action evidence; structured continuation reuses only its boundaries."""
    if not invoice_change_boundary(text, field, new_value, rule_field=rule_field):
        return False
    label = _FIELD_NAMES[field]
    choice = _quoted_invoice_choice(text)
    if choice:
        return choice["field"] == [field] and choice["new_value"] == [new_value]

    literal = re.escape(new_value)
    value = rf'(?:“{literal}”|‘{literal}’|"{literal}"|「{literal}」|『{literal}』|{literal})'
    quotes = tuple(_QUOTED_TEXT.finditer(text))
    for match in re.finditer(rf"{value}(?=$|[\s，,。；;！!])", text):
        if any(quote.start() <= match.start() and match.end() <= quote.end()
               and quote[0][1:-1] != new_value for quote in quotes):
            continue
        clause = re.split(r"[，,。；;\n]", text[:match.start()])[-1]
        if re.search(r"不要|别|禁止|不许|无需|不必", clause):
            continue
        # Match literal action evidence without parsing a specific field/verb sentence shape.
        mentioned = {name for name in _FIELD_NAMES.values() if name in clause}
        if ((mentioned and mentioned != {label}) or
                (not mentioned and rule_field is None and all(name in text for name in _FIELD_NAMES.values()))):
            continue
        if re.search(rf"{_EDIT_ACTION}|处理", clause) and not re.match(r"\s*(?:查询|查看|统计|列出|检查|解释|比较)", clause):
            return True
        if re.fullmatch(r"\s*新值\s*(?:是|为)\s*", clause) and invoice_intent_source(text):
            return True
    return False


def excluded_invoice_ids(text):
    return {invoice.upper() for match in _EXCLUDED.finditer(text)
            for invoice in re.findall(_INVOICE, match["before"] or match["after"], re.I)}


def named_invoice_read_and_edit(text):
    """Split a named detail read and a separate assignment to one of those invoices."""
    text = text.strip().rstrip("。！!").strip()
    read_start = r"(?:(?:请帮我|帮我|请|麻烦|先)\s*)*(?:查询|查看|查一下|查|看看|看一下|核对|核实)\s*"
    edit_start = r"(?:(?:请帮我|帮我|请|麻烦|只|仅)\s*)*(?:把|将|修改|更正|更新)"
    connect = r"然后(?:再)?|随后|接着|同时|再|并且|并"
    masked = re.sub(r'“[^”]*”|「[^」]*」|『[^』]*』|"[^"]*"', lambda m: " " * len(m[0]), text)
    boundary = re.search(rf"(?:[，,；;。]\s*(?:(?:{connect})\s*)?|\s*(?:{connect})\s*)"
                         rf"(?=(?:{read_start}|{edit_start}))", masked)
    if boundary:
        first, second = text[:boundary.start()].strip(), text[boundary.end():].strip()
        read, write = (first, second) if re.match(read_start, first) else (second, first)
    else:
        # A shared owner and period may precede a subject-first assignment.
        subject = re.fullmatch(
            rf"(?P<owner>{_INVOICE_OWNER_MONTH})\s*[，,]\s*(?P<target>{_INVOICE})\s*的\s*"
            rf"(?P<field>用途|备注)\s*(?:请\s*)?(?:{_ASSIGNMENT}|写成|写为|填成|填为)\s*"
            rf"(?P<value>{_ASSIGNED_VALUE})\s*[。；;]\s*"
            rf"(?P<numbers>{_NAMED_INVOICES})\s*的\s*(?P<read_field>用途|备注)\s*"
            r"(?:也\s*)?(?:报一下|列出来|告诉我)"
            r"(?:\s*[，,]\s*(?P<two>两张的\s*)?(?P<keep>用途|备注)\s*(?:都\s*)?保持原样)?",
            text, re.I)
        if not subject:
            return _questioned_invoice_choice(text)
        numbers = explicit_scope(subject["numbers"])["invoice_no"]
        if subject["two"] and len(numbers) != 2:
            return None
        read = f'查看 {subject["owner"]} 的 {subject["numbers"]} 的{subject["read_field"]}'
        write = f'把 {subject["target"]} 的{subject["field"]}改成{subject["value"]}'
        if subject["keep"]:
            write += f'，{subject["keep"]}保持原样'
    if (not re.fullmatch(rf"{read_start}{_INVOICE_OWNER_MONTH}\s*(?:的\s*)?(?:发票\s*)?{_NAMED_INVOICES}"
                         r"\s*(?:发票\s*)?(?:的\s*)?(?:用途|备注)", read, re.I)
            or not re.match(edit_start, write)):
        return None
    read_scope = explicit_scope(read, include_update_aliases=True)
    request = {"read": read, "read_scope": read_scope, "write": write, "write_scope": None}
    command = re.sub(r"^(?:(?:请帮我|帮我|请|麻烦|只|仅)\s*)+", "", write)
    match = _EDIT.match(command)
    if not match or (match["verb"] or match["direct_verb"]) == "清空":
        return request
    field = match["field"] or match["direct_field"]
    assignment = r"\s*" if match["verb"] else rf"\s*(?:{_ASSIGNMENT}|为|成)\s*"
    tail = re.fullmatch(
        assignment
        + rf'({_ASSIGNED_VALUE})'
        + r'(?:\s*[，,；;]\s*(用途|备注)\s*(?:别动|不动|不要改|别改|不改|不修改|保持原样))?\s*',
        command[match.end():])
    if not tail or tail[2] == field:
        return request
    value = tail[1].strip()
    if not value or (value[0] not in '“"「『' and re.search(
            r"如果|若|假如|前提|仅限|排除|不含|别动|不动|不要改|保持原样|"
            r"只(?:限|在|改)|(?:再|另|并)(?:查|改)", value)):
        return request
    values = literal_value(value)
    target = (match["target"] or match["direct"] or "").strip()
    if not values:
        return request
    change = {"field": ["purpose" if field == "用途" else "remark"], "new_value": values}
    if re.fullmatch(r"(?:(?:其中|之中|里面)\s*)?(?:任意|某)?\s*(?:一|1)\s*张\s*(?:发票|票)?\s*(?:的)?", target):
        if invoice_change_evidence(write, change["field"][0], values[0]):
            request["pending_choice"] = change
        return request
    if not re.fullmatch(
            rf"(?:(?:{_INVOICE_OWNER_MONTH}|{_COMPANY})\s*(?:的\s*)?)?(?:发票\s*)?{_INVOICE}\s*(?:发票)?\s*(?:的)?",
            target, re.I):
        return request
    scope = explicit_scope(target, include_update_aliases=True)
    if (not set(scope["invoice_no"]) <= set(read_scope["invoice_no"])
            or any(key in scope and scope[key] != read_scope[key] for key in ("company_id", "periods"))):
        return request
    request["write_scope"] = {**read_scope, **scope, **change}
    return request


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
