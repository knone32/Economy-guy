"""可信运行层的范围证据；模型参数和自报来源不能构造此许可。"""
from dataclasses import dataclass, replace
from copy import deepcopy
import hashlib

SOURCES={'user_current','session_confirmed','trusted_reference','current_sqlite'}
READ_SOURCES = SOURCES | {'model_read_candidate','controlled_read_scope'}
from .tool_contracts import READ_ONLY_TOOLS, MONTHLY, ANNUAL


def is_annual_query(name, scope):
    return name in ANNUAL or (name == "list_invoice_directory" and bool(scope.get("year")) and not scope.get("month"))


@dataclass(frozen=True)
class ScopeProof:
    actor: str
    values: dict
    sources: dict
    read_workspace: dict | None = None
    annual_year: int | None = None
    directory_scope: tuple[str, int, int] | None = None
    directory_sort: tuple[str, str] | None = None

    def metadata(self):
        """可记录的来源，不含凭据或模型自报权限。"""
        return {'values':deepcopy(self.values),'sources':dict(self.sources), **({'annual_year': self.annual_year} if self.annual_year else {})}


def supplement_read_literals(proof, expected, raw, *, raw_sources=None):
    """Fill missing read-only literal slots without inventing cross-quote pairs.

    Only the get_invoice dispatcher uses this. Existing current/reference slots
    win; quoted data never enters the shared context or any write proof.
    Multiple companies or periods cannot be reliably paired by literal sets.
    """
    keys = ('company_id', 'invoice_no', 'year', 'month', 'periods')
    candidates = {k: list(raw.get(k, ())) for k in keys}
    if any(len(candidates[k]) > 1 for k in ('company_id', 'year', 'month', 'periods')):
        return proof, expected
    workspace = proof.read_workspace or {}
    known = {k: expected.get(k) or proof.values.get(k) or workspace.get(k) or () for k in keys}
    for key in keys:
        a, b = candidates[key], known[key]
        if key == 'periods':
            a, b = list(map(tuple, a)), list(map(tuple, b))
        if a and b and not set(a) <= set(b):
            return proof, expected
    values, sources, scope = deepcopy(proof.values), dict(proof.sources), deepcopy(expected)
    for key in keys:
        if candidates[key] and not expected.get(key) and not proof.values.get(key):
            values[key] = candidates[key]
            sources[key] = (raw_sources or {}).get(key, 'user_current')
            scope[key] = candidates[key]
    return replace(proof, values=values, sources=sources), scope


def current_sql_invoice_identity(results, target, proof, expected):
    """Return only a unique current SQL original key, for one read call.

    The runtime owns results; model labels/text never establish identity. All
    complete direct invoice projections contribute, so two singleton results
    cannot silently choose one another. No date or write source is created.
    """
    identities = set()
    known = {key: expected.get(key) or proof.values.get(key)
             or (proof.read_workspace or {}).get(key) or ()
             for key in ('company_id', 'year', 'month', 'periods')}
    for name, result in results:
        evidence = result.get('evidence', {})
        data = result.get('data') or {}
        query = evidence.get('query_scope') or {}
        if (name != 'query_business_sql' or result.get('status') != 'SUCCESS'
                or evidence.get('source') != 'current_sqlite'
                or query.get('status') != 'VERIFIED' or query.get('table') != 'invoices'
                or query.get('query_set_complete') is not True
                or query.get('limited') is not False or query.get('display_truncated') is not False
                or data.get('truncated') is not False or type(data.get('sql')) is not str
                or query.get('sql_sha256') != hashlib.sha256(data['sql'].encode('utf-8')).hexdigest()):
            continue
        columns, rows = data.get('columns', ()), data.get('rows', ())
        projected, indexes = query.get('columns', ()), data.get('invoice_display_identity', {})
        if (not rows or len(projected) != len(columns)
                or any(meta.get('kind') != 'column' for meta in projected)
                or any(type(indexes.get(key)) is not int or not 0 <= indexes[key] < len(columns)
                       or projected[indexes[key]].get('field') != key
                       or projected[indexes[key]].get('name') != columns[indexes[key]]
                       for key in ('company_id', 'invoice_no'))):
            continue
        scope = query.get('scope') or {}
        periods = tuple(map(tuple, scope.get('periods', ())))
        if ((known['periods'] and not set(periods) <= set(map(tuple, known['periods'])))
                or (known['year'] and any(y not in known['year'] for y, _ in periods))
                or (known['month'] and any(m not in known['month'] for _, m in periods))):
            return {}
        for row in rows:
            if len(row) != len(columns):
                return {}
            key = tuple(row[indexes[field]] for field in ('company_id', 'invoice_no'))
            if (any(type(value) is not str or not value for value in key)
                    or key[0] not in scope.get('company_ids', ())):
                return {}
            identities.add(key)
    selected = (target.get('company_id'), target.get('invoice_no'))
    if len(identities) != 1 or selected not in identities:
        return {}
    return {'company_id': [selected[0]], 'invoice_no': [selected[1]]}


def validate_scope(proof,user_id,name,args,partial=False):
    """权限由Handler先检查；来源缺失和已知范围冲突分别返回。"""
    if proof is None:
        # 仅兼容直接可信Python调用；正式Agent总是传ScopeProof，包括空范围。
        return None
    if not isinstance(proof,ScopeProof) or proof.actor!=user_id:
        return {'status':'DENIED','error':'可信范围身份不一致','evidence':{}}
    accepted_sources = READ_SOURCES if name in READ_ONLY_TOOLS else SOURCES
    directory = name == 'list_invoice_directory'
    if directory and proof.directory_scope is not None:
        company, year, month = proof.directory_scope
        requested = (args.get("company_id", company), args.get("year", 0), args.get("month", 0))
        if requested != (company, year, month):
            return {"status": "SCOPE_MISMATCH", "error": "目录参数与已核验的上一轮范围不一致",
                    "evidence": {"scope": args, "prior_directory_scope": proof.directory_scope}}
        return None
    filtered = directory and args.get('year', 0) != 0 and args.get('month', 0) != 0
    if is_annual_query(name, args):
        company = (proof.read_workspace or {}).get("company_id") or proof.values.get("company_id")
        source_ok = bool(proof.read_workspace or proof.sources.get("company_id") in accepted_sources)
        missing = [key for key, present in (("company_id", source_ok and company and len(company) == 1),
                                             ("year", proof.annual_year is not None)) if not present]
        if missing:
            return {"status": "AMBIGUOUS", "error": "请明确企业和完整年度",
                    "evidence": {"missing_fields": missing, "provenance": proof.metadata()}}
        if (("company_id" in args and args["company_id"] != company[0])
                or ("year" in args and args["year"] != proof.annual_year)):
            return {"status": "SCOPE_MISMATCH", "error": "参数与可信年度范围不一致",
                    "evidence": {"scope": args, "provenance": proof.metadata()}}
        return None
    if proof.annual_year is not None and (name in MONTHLY or directory):
        return {"status": "SCOPE_MISMATCH", "error": "全年查询不能替换成月度查询或跨年目录",
                "evidence": {"scope": args, "provenance": proof.metadata()}}
    if (name in MONTHLY or directory) and proof.read_workspace:
        workspace = proof.read_workspace if not directory or filtered else {
            'company_id': proof.read_workspace['company_id']}
        proof = ScopeProof(proof.actor, {**proof.values, **workspace},
                           {**proof.sources, **dict.fromkeys(workspace, "workspace_read")})
        accepted_sources = accepted_sources | {"workspace_read"}
    required=['company_id']
    if name in MONTHLY or filtered or (name=='manage_task' and args.get('action') in {'create','correct'}):required+=['year','month']
    if name in {'get_invoice','prepare_invoice_update'}:required+=['invoice_no']
    missing=[key for key in required if (key in args or not partial) and
             (not proof.values.get(key) or proof.sources.get(key) not in accepted_sources)]
    conflicts=[key for key in required if key in args and key not in missing and args[key] not in proof.values[key]]
    if 'year' in required and 'year' in args and 'month' in args and not missing:
        periods = proof.values.get('periods')
        if not periods or proof.sources.get('periods') not in accepted_sources:
            missing = ['year', 'month']
        elif (args['year'], args['month']) not in periods:
            conflicts = list(dict.fromkeys([*conflicts, 'year', 'month']))
    if conflicts:
        return {'status':'SCOPE_MISMATCH','error':'参数与可信范围不一致','evidence':{'conflicting_fields':conflicts,'scope':args,'provenance':proof.metadata()}}
    if missing:
        return {'status':'AMBIGUOUS','error':'缺少可信范围，请补充必要字段','evidence':{'missing_fields':missing,'source':'scope_provenance','provenance':proof.metadata()}}
    return None
