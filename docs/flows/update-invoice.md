# 实际修改链路

1. main.main读取 `/edit 原始修改要求`；Agent.ask(...allow_prepare=True) → WriteCoordinator.begin创建pending和scope约束；UpdateSession.begin_turn记录本轮expected_scope并清空旧草稿/确认。
2. 同一模型返回clarification信封时自然追问保留。下一次补充由CLI要求continue关联；WriteCoordinator.begin保留原企业/发票约束，明确值变化标记冲突，不能合并成多目标。新/edit表示可信重建意图、清空旧草稿/确认；新主题和/cancel失效。没有关键词业务路由。
3. 模型prepare_invoice_update → Registry严格校验和可信范围派生 → updates.prepare_invoice_update先modify鉴权，再核对Session和Handler目标。错企业/错发票/跨轮冲突=SCOPE_MISMATCH；目标不唯一=AMBIGUOUS，均无草稿。正确目标才读取当前值并创建本轮Draft/request_id；WAITING_CONFIRMATION不写业务库。
4. CLI展示source_request、企业、发票、字段、旧/新值；用户完整输入confirm request_id → Agent.commit_update → WriteCoordinator.commit_update → updates.confirm_draft绑定会话/本轮/指纹。
5. updates.commit_invoice_update：BEGIN IMMEDIATE → 重查授权 → 查request_id成功审计及指纹 → 查旧值 → 白名单字段UPDATE+invoice_audit同事务 → COMMIT。重复请求不重写；冲突/失败回滚。
6. inspect_request/_readback使用新连接：返回历史成功审计和当前发票；WriteCoordinator核对request_id/身份/指纹/企业/发票/字段/旧新值/回读一致性生成回执。未知或证据不完整为UNKNOWN_OUTCOME，先查审计，不自动重试写。
7. WriteCoordinator.events先保存来源trusted_cli的历史事件，再尽力记录JSONL；日志失败不能遮蔽提交回执。CLI展示程序回执，模型原文不能触发COMMITTED。后续model_messages以name=harness_history的assistant数据消息投影历史事件，不追加user、不伪造模型Tool Call；当前值仍需重新查库。取消回执绑定已撤销的request_ids/intent_id，取消不回滚已有业务提交。

原始用户信息、模型追问、Tool Call与真实工具结果保留各自来源。CLI身份/管理能力为比赛模拟；能力不是模型参数。新主题、取消、重启、身份变化不能继承旧确认。

测试：tests/test_stage2.py（事务、审计、幂等、回读、权限、同号）；test_write_receipts.py（成功误报反例、状态和显示顺序）；test_stage25.py（连续补充、来源、注入、状态失效）；test_architecture.py（反向导入）。tests/helpers.py始终使用临时数据库。

Stage 2.5.1安全故障注入见tests/test_security_boundaries.py：合法JSON假提交、隐藏工具、伪角色、备注注入、日志/审计/回读故障及跨用户隔离。故障断言包含实际字段、审计数量及回执；不单靠Prompt文字验收。_check_identity在ask/model_messages/commit/cancel入口重置跨用户会话状态。

tests/test_stage253.py补充错目标、跨轮冲突、明确更正、缺失目标以及日期范围反例；核对草稿、两企业字段和审计数量。原Prepare/Confirm/Commit事务与回读未重写。

Stage 3B：若本轮包含可识别的发票序数线索，Agent.ask先经ContextBuilder.resolve → references.resolve_reference，以展示顺序联合键重新鉴权读当前库。成功后将真实company_id/invoice_no/year/month作为本轮expected_scope送入原Handler；模型换号/换企业无法Prepare。无唯一锚点则直接追问。Context不授予allow_prepare，Prepare仍需要本轮/edit或可信关联补充；每轮清空草稿/确认。引用恢复只恢复对象线索，重启不能恢复旧确认。tests/test_stage3b.py核对正确引用未确认不写库、错引用无草稿及零成功审计。
