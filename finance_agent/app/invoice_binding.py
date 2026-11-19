"""Bind optional invoice write roles to real user text and current selections."""
import re

from .responses import request_scope as explicit_scope
from .tui_intent import excluded_invoice_ids, invoice_value_source


WRITE_SCOPE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["company_id", "year", "month", "invoice_nos"],
    "properties": {"company_id": {"type": "string"}, "year": {"type": "integer"},
                   "month": {"type": "integer"},
                   "invoice_nos": {"type": "array", "minItems": 1, "maxItems": 20,
                                   "items": {"type": "string"}}},
}


def validate_write_scope(scope):
    if (type(scope) is not dict or set(scope) != {"company_id", "year", "month", "invoice_nos"}
            or type(scope["company_id"]) is not str
            or type(scope["year"]) is not int or not 1 <= scope["year"] <= 9999
            or type(scope["month"]) is not int or not 1 <= scope["month"] <= 12
            or type(scope["invoice_nos"]) is not list or not 1 <= len(scope["invoice_nos"]) <= 20
            or any(type(n) is not str or re.fullmatch(r"F\d+", n, re.I) is None for n in scope["invoice_nos"])
            or len(set(n.upper() for n in scope["invoice_nos"])) != len(scope["invoice_nos"])):
        raise ValueError("修改范围结构无效")
    return scope


def bind_write_scope(source_request, proposal, selection):
    """Model supplies roles; code checks source membership, fresh keys and scope."""
    scope = validate_write_scope(proposal["write_scope"])
    if selection is None:
        raise ValueError("修改范围没有本轮可信选集")
    company = scope["company_id"]
    numbers = {n.upper() for n in scope["invoice_nos"]}
    named = explicit_scope(source_request, include_update_aliases=True)
    if company not in named.get("company_id", ()) or not numbers <= set(named.get("invoice_no", ())):
        raise ValueError("修改对象没有可核验的用户来源")
    if set(selection[0]) != {(company, n) for n in numbers}:
        raise ValueError("独立修改范围与本轮选集不一致")
    declared_exclusions = {n.upper() for n in proposal["excluded_invoice_ids"]}
    literal_exclusions = excluded_invoice_ids(source_request)
    declared_exclusions |= literal_exclusions
    if (declared_exclusions & numbers
            or not declared_exclusions <= set(named.get("invoice_no", ()))):
        raise ValueError("排除对象与用户来源或修改范围不一致")
    field_evidence = ({"field": [proposal["field"]], "new_value": [proposal["new_value"]]}
                      if invoice_value_source(source_request, proposal["field"], proposal["new_value"]) else None)
    return {"write": source_request, "excluded": declared_exclusions, "field_evidence": field_evidence,
            "write_scope": {"company_id": [company], "year": [scope["year"]],
                            "month": [scope["month"]], "periods": [(scope["year"], scope["month"])],
                            "invoice_no": sorted(numbers)}}
