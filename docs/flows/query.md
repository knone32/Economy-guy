# 实际查询链路

4P-B：综合查询优先由模型选择get_finance_summary；用户补充年月时继续原目标，无关键词路由。list_invoices/list_bank_transactions也在已鉴权的同一快照经finance.get_finance_summary提供金额/计数证据，响应层只展示对应明细工具范围的部分，并注明R001。无可用金额规则时保留原只读明细与summary_status，不展示缺依据的附加汇总。

Agent.ask的read_results保留所有逐ID结果（含跳过）。异常/重复/预算停止时responses.render_stopped仅展示本轮真实SUCCESS/NO_DATA/NO_CHANGE及实际stop_reason、未完成项，不展示DENIED项data，不采模型成功声称。此异常收尾不新增可复用引用锚点；Scheduler判定及计数不变。tests/test_stage4pb.py覆盖重复读取、管理成功后重复、混合拒绝、API/格式失败及预算停止。

入口finance_agent/main.py的main(chat) → app.agent.Agent.ask → ContextBuilder.begin/resolve → model_messages → ContextBuilder.build（按来源/预算装配）→ live_model或注入Mock → app.tool_registry.handle_tool → permissions.check_permission → finance.get_finance_summary或queries.list_invoices/get_invoice/list_bank_transactions → 只读业务事务。

Registry生产工具为统一汇总、发票列表/详情、银行列表、规则查询、用途检查与Prepare。add/summary及旧金额函数保留Python实现，但生产Schema和实际执行许可均不包含它们；教学Agent显式teaching=True，可信内部调用显式传allowed_tools。Agent每次执行按初始许可与当前Schema交集授权，再由Handler校验字段类型及企业权限。拒绝也按真实tool_call_id回传，不提供SQL或Commit。

返回ok/status/data/evidence/error；金额整数分累计，空集与拒绝区别。用途检查使用rules.resolve_rule的唯一RuleDecision。规则补充explanation仅为非持久化官方限制说明，不覆盖同版本正文。

副作用：发票/银行只读，更新会话消息并尽力追加脱敏Trace；Stage 3B已迁移时，实际展示发票后写reference_anchors元数据，更正/取消可失效锚点。不自动迁移或初始化，不更新业务字段或授予写权限。模型最终信封经responses.parse_final；information由render_information基于实际工具结果生成，逐项显示企业/年月/来源/规则，clarification由render_clarification提问。general明确未核实且不作执行凭据。Trace故障只标记trace_degraded，不改变业务事实。

范围链：Agent.ask → responses.explicit_scope（当前输入明确编号/数字年月）→ tool_registry.handle_tool(expected_scope=...) → check_permission → scope_mismatch → 查询或SCOPE_MISMATCH。发票详情结果还按当前日期复核。输入无法可靠解析的别名/时间不猜，展示实际scope。check_missing_purpose/get_applicable_rules/银行明细也携带scope/source和规则证据；缺R004时银行只读结果明确标记rule_status，不伪造版本。

Stage 2.5.3规则日期：get_applicable_rules在check_permission之后严格解析YYYY-MM-DD，得到实际year/month后再scope_mismatch。错误格式=INVALID_ARGUMENTS，错月份=SCOPE_MISMATCH，未启用/无规则=NO_APPLICABLE_RULE，多条适用=RULE_CONFLICT，权限不足=DENIED，不能混淆。rules.resolve_rule保留原版本/状态/企业/生效日期选择并增加规范日期校验。

test_stage252.py验证一般问候/概念、实际范围/冲突/多企业来源；原六项协议冲突测试在本轮初始实测已通过，保留其当前断言。安全35项继续验证写入/权限/日志边界。

对应测试：tests/test_agent.py、test_queries.py、test_finance.py、test_permissions.py、test_stage25.py、test_architecture.py。tool_call_id配对及额度失败仍由原有Loop负责；真实模型另行验收。

Stage 3B引用与上下文实际调用链、迁移和边界见[context-reference.md](context-reference.md)。test_stage252的未知别称用“甲方公司”，保留无法验证别称时必须展示实际范围的原断言；官方“甲企业”现可识别，另测模型错企业时SCOPE_MISMATCH。

Stage 3C普通查询仍走Fast Path，无额外规划模型调用。模型调用和工具分发前接入TurnExecution计数/重复/依赖守卫；可选计划仅使用set_schedule工具，业务Handler鉴权仍实际执行，详见[schedule-budget.md](schedule-budget.md)。

4P-E：Agent._ask在当前调用方工具子集内生成turn_tools；仅当WriteCoordinator.begin认可本轮准备流程时暴露prepare_invoice_update。只读轮不暴露该工具，伪造调用仍由白名单拒绝，不恢复调用方已隐藏的工具。test_stage4pe及原test_security_boundaries验证只读/合法编辑/子集边界。缺失日期的任意自然语言语义仍不是Handler已完整验证的事实：S4-P-E的A1有模型猜月份后查询的反例，不能以本轮过滤写工具声称已解决该问题。
