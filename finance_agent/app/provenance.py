"""可信运行层的范围证据；模型参数和自报来源不能构造此许可。"""
from dataclasses import dataclass
from copy import deepcopy

SOURCES={'user_current','session_confirmed','trusted_reference','current_sqlite'}
MONTHLY={'get_finance_summary','summary','list_invoices','list_bank_transactions',
         'invoice_total','bank_income_total','bank_expense_total','check_missing_purpose','get_applicable_rules'}

@dataclass(frozen=True)
class ScopeProof:
    actor: str
    values: dict
    sources: dict
    read_workspace: dict | None = None

    def metadata(self):
        """可记录的来源，不含凭据或模型自报权限。"""
        return {'values':deepcopy(self.values),'sources':dict(self.sources)}

def validate_scope(proof,user_id,name,args,partial=False):
    """权限由Handler先检查；来源缺失和已知范围冲突分别返回。"""
    if proof is None:
        # 仅兼容直接可信Python调用；正式Agent总是传ScopeProof，包括空范围。
        return None
    if not isinstance(proof,ScopeProof) or proof.actor!=user_id:
        return {'status':'DENIED','error':'可信范围身份不一致','evidence':{}}
    accepted_sources = SOURCES
    directory = name == 'list_invoice_directory'
    filtered = directory and args.get('year', 0) != 0 and args.get('month', 0) != 0
    if (name in MONTHLY or directory) and proof.read_workspace:
        workspace = proof.read_workspace if not directory or filtered else {
            'company_id': proof.read_workspace['company_id']}
        proof = ScopeProof(proof.actor, {**proof.values, **workspace},
                           {**proof.sources, **dict.fromkeys(workspace, "workspace_read")})
        accepted_sources = SOURCES | {"workspace_read"}
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
