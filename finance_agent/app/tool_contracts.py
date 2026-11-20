"""Static tool registration data; classification grants no authority or evidence."""
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class ToolSpec:
    executor: str | None
    parameters: tuple
    read_mode: str
    normal: bool
    reads_financial_data: bool
    answer_fact: bool
    support: bool
    objects: tuple = ()
    result_adapter: str | None = None
    condition_mode: str = 'none'

    def __post_init__(self):
        if (self.read_mode not in {'none','monthly','annual','invoice','sql','directory','reference','rule_history'}
                or self.result_adapter not in {None,'sql','summary','details'}
                or self.condition_mode not in {'none','sql','row','direction','direction_arg'}
                or any(type(v) is not bool for v in (self.normal,self.reads_financial_data,self.answer_fact,self.support))
                or self.executor is not None and type(self.executor) is not str
                or type(self.parameters) is not tuple or any(type(p) is not tuple or len(p)!=2
                    or type(p[0]) is not str or p[1] not in {'string','integer','number','boolean','array','object'}
                    for p in self.parameters)
                or type(self.objects) is not tuple or any(v not in {'invoices','bank_transactions'} for v in self.objects)
                or self.result_adapter and (not self.reads_financial_data or not self.objects)
                or self.reads_financial_data and self.read_mode=='none'
                or self.result_adapter=='sql' and (self.read_mode!='sql' or self.condition_mode!='sql')
                or self.result_adapter=='summary' and self.condition_mode!='direction'
                or self.result_adapter=='details' and self.condition_mode not in {'none','row','direction_arg'}
                or self.condition_mode=='row' and self.read_mode!='invoice'
                or self.condition_mode=='direction_arg' and self.objects!=('bank_transactions',)
                or self.support and self.reads_financial_data):
            raise ValueError('Incomplete or unsupported static tool registration')


# One developer-owned declaration per tool. Executor tokens select only the
# already imported service modules in tool_registry; no model data enters here.
TOOL_SPECS = MappingProxyType({
    'list_materials': ToolSpec(None, (('company_id', 'string'),), 'none', normal=True, reads_financial_data=False, answer_fact=False, support=True),
    'open_material_reference': ToolSpec(None, (('material_id', 'string'), ('version', 'integer'), ('paragraph_id', 'integer')), 'none', normal=True, reads_financial_data=False, answer_fact=False, support=True),
    'use_skill': ToolSpec(None, (('company_id', 'string'), ('skill_id', 'string')), 'none', normal=True, reads_financial_data=False, answer_fact=False, support=True),
    'change_invoice': ToolSpec(None, (('company_id', 'string'), ('invoice_no', 'string'), ('year', 'integer'), ('month', 'integer'), ('field', 'string'), ('new_value', 'string'), ('relation', 'string'), ('value_ref', 'string')), 'none', normal=True, reads_financial_data=False, answer_fact=False, support=False),
    'query_business_sql': ToolSpec(None, (('sql', 'string'), ('read_scope', 'object')), 'sql', normal=True, reads_financial_data=True, answer_fact=True, support=False, objects=('invoices', 'bank_transactions'), result_adapter='sql', condition_mode='sql'),
    'list_invoices': ToolSpec('queries.list_invoices', (('company_id', 'string'), ('year', 'integer'), ('month', 'integer')), 'monthly', normal=True, reads_financial_data=True, answer_fact=True, support=False, objects=('invoices',), result_adapter='details', condition_mode='none'),
    'list_invoice_directory': ToolSpec('queries.invoice_directory', (('company_id', 'string'), ('year', 'integer'), ('month', 'integer'), ('page', 'integer'), ('sort_by', 'string'), ('sort_order', 'string')), 'directory', normal=True, reads_financial_data=True, answer_fact=True, support=False),
    'get_invoice': ToolSpec('queries.get_invoice', (('company_id', 'string'), ('invoice_no', 'string')), 'invoice', normal=True, reads_financial_data=True, answer_fact=True, support=False, objects=('invoices',), result_adapter='details', condition_mode='row'),
    'list_bank_transactions': ToolSpec('queries.list_bank_transactions', (('company_id', 'string'), ('year', 'integer'), ('month', 'integer'), ('direction', 'string')), 'monthly', normal=True, reads_financial_data=True, answer_fact=True, support=False, objects=('bank_transactions',), result_adapter='details', condition_mode='direction_arg'),
    'invoice_total': ToolSpec('finance.invoice_total', (('company_id', 'string'), ('year', 'integer'), ('month', 'integer')), 'monthly', normal=False, reads_financial_data=True, answer_fact=False, support=False),
    'bank_income_total': ToolSpec('finance.bank_income_total', (('company_id', 'string'), ('year', 'integer'), ('month', 'integer')), 'monthly', normal=False, reads_financial_data=True, answer_fact=False, support=False),
    'bank_expense_total': ToolSpec('finance.bank_expense_total', (('company_id', 'string'), ('year', 'integer'), ('month', 'integer')), 'monthly', normal=False, reads_financial_data=True, answer_fact=False, support=False),
    'summary': ToolSpec(None, (('company_id', 'string'), ('year', 'integer'), ('month', 'integer')), 'monthly', normal=False, reads_financial_data=True, answer_fact=False, support=False),
    'get_finance_summary': ToolSpec('finance.get_finance_summary', (('company_id', 'string'), ('year', 'integer'), ('month', 'integer')), 'monthly', normal=True, reads_financial_data=True, answer_fact=True, support=False, objects=('invoices', 'bank_transactions'), result_adapter='summary', condition_mode='direction'),
    'check_missing_purpose': ToolSpec('rules.check_missing_purpose', (('company_id', 'string'), ('year', 'integer'), ('month', 'integer'), ('rule_business_date', 'string')), 'monthly', normal=True, reads_financial_data=True, answer_fact=True, support=False),
    'count_invoice_fields': ToolSpec(None, (('company_id', 'string'), ('year', 'integer'), ('month', 'integer'), ('selector', 'string')), 'monthly', normal=True, reads_financial_data=True, answer_fact=True, support=False),
    'get_annual_finance_summary': ToolSpec('finance.get_annual_finance_summary', (('company_id', 'string'), ('year', 'integer')), 'annual', normal=True, reads_financial_data=True, answer_fact=True, support=False, objects=('invoices', 'bank_transactions'), result_adapter='summary', condition_mode='direction'),
    'list_annual_blank_purpose': ToolSpec('queries.list_annual_blank_purpose', (('company_id', 'string'), ('year', 'integer'), ('page', 'integer')), 'annual', normal=True, reads_financial_data=True, answer_fact=True, support=False),
    'list_annual_bank_income': ToolSpec('queries.list_annual_bank_income', (('company_id', 'string'), ('year', 'integer'), ('page', 'integer')), 'annual', normal=True, reads_financial_data=True, answer_fact=True, support=False),
    'get_applicable_rules': ToolSpec(None, (('company_id', 'string'), ('rule_type', 'string'), ('business_date', 'string')), 'monthly', normal=True, reads_financial_data=False, answer_fact=True, support=True),
    'list_rule_versions': ToolSpec(None, (('company_id', 'string'), ('rule_id', 'string')), 'rule_history', normal=True, reads_financial_data=False, answer_fact=True, support=True),
    'prepare_invoice_update': ToolSpec(None, (('company_id', 'string'), ('invoice_no', 'string'), ('field', 'string'), ('new_value', 'string')), 'none', normal=True, reads_financial_data=False, answer_fact=False, support=False),
    'propose_invoice_changes': ToolSpec(None, (('selection_id', 'string'), ('field', 'string'), ('new_value', 'string'), ('mode', 'string'), ('excluded_invoice_ids', 'array'), ('rule_business_date', 'string'), ('target_year', 'integer'), ('target_month', 'integer'), ('rule_cohort', 'boolean'), ('write_scope', 'object'), ('pending_request_id', 'string')), 'none', normal=True, reads_financial_data=False, answer_fact=False, support=False),
    'add': ToolSpec(None, (('a', 'integer'), ('b', 'integer')), 'none', normal=False, reads_financial_data=False, answer_fact=False, support=False),
    'list_tasks': ToolSpec(None, (('company_id', 'string'),), 'none', normal=True, reads_financial_data=False, answer_fact=False, support=True),
    'manage_task': ToolSpec(None, (('company_id', 'string'), ('action', 'string'), ('task_id', 'string'), ('year', 'integer'), ('month', 'integer'), ('note', 'string')), 'none', normal=True, reads_financial_data=False, answer_fact=False, support=False),
    'manage_display_preference': ToolSpec(None, (('action', 'string'), ('value', 'string')), 'none', normal=True, reads_financial_data=False, answer_fact=False, support=False),
    'manage_preference': ToolSpec(None, (('company_id', 'string'), ('action', 'string'), ('key', 'string'), ('value', 'string')), 'none', normal=True, reads_financial_data=False, answer_fact=False, support=False),
    'resolve_invoice_reference': ToolSpec(None, (('company_id', 'string'), ('ordinal', 'integer'), ('anchor_id', 'string')), 'reference', normal=True, reads_financial_data=True, answer_fact=True, support=False),
    'resolve_recent_invoice': ToolSpec(None, (('source', 'string'),), 'reference', normal=True, reads_financial_data=True, answer_fact=True, support=False),
    'set_schedule': ToolSpec(None, (('goal', 'string'), ('steps', 'array'), ('stop_condition', 'string')), 'none', normal=True, reads_financial_data=False, answer_fact=False, support=True),
})
FINANCIAL_TOOLS = frozenset(n for n,s in TOOL_SPECS.items() if s.reads_financial_data)
CAPABILITIES = MappingProxyType({n:s.objects for n,s in TOOL_SPECS.items() if s.result_adapter is not None})
SUPPORT_TOOLS = frozenset(n for n,s in TOOL_SPECS.items() if s.support)
NORMAL_TOOLS = frozenset(n for n,s in TOOL_SPECS.items() if s.normal)
ANSWER_TOOLS = frozenset(n for n,s in TOOL_SPECS.items() if s.answer_fact)
MONTHLY = frozenset(n for n,s in TOOL_SPECS.items() if s.read_mode=='monthly')
ANNUAL = frozenset(n for n,s in TOOL_SPECS.items() if s.read_mode=='annual')
READ_ONLY_TOOLS = frozenset(n for n,s in TOOL_SPECS.items()
                          if s.read_mode in {'monthly','annual','invoice','sql','directory','rule_history'})
