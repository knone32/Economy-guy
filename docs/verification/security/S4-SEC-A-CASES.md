# S4-SEC-A 冻结案例

`PUBLIC_SECURITY_REGRESSION`。被测 `5c7a15c105459662f0b20dacd254f8395e1d540d`，生产源码对应 `f6d99267358e5202752afbbdd062600781cdab29`。初始 SHA256 在首次执行前登记。新增发现只追加新 ID 并标记 `DISCOVERED_AFTER_INITIAL_FREEZE`。全程零 Live。SQLite 与 Excel 写入只用独立临时目录及官方虚构夹具的副本。

## 入口与信任边界

| 入口 | 调用者与输入 | 检查及副作用 |
|---|---|---|
| `main.py chat`, `/edit`, 确认提示 | 模拟 CLI 身份和可信操作者输入，聊天内容独立于可信确认 | 绑定本轮草稿或管理候选，提交处复查权限，SQLite 与审计同事务 |
| `Agent.ask → handle_tool` | 用户请求及不可信模型响应，actor 来自 Session | 工具白名单、Schema、ACL、ScopeProof、预算。工具数据和历史不会获得可信消息角色 |
| `provenance`, `context`, `references` | 可信运行时构造 proof，模型可提交参数或引用候选 | 正式 Loop 显式传 proof。`proof=None` 属于 `TRUSTED_INTERNAL_API`，内部函数调用不等于不可信入口可达 |
| `persistence`, `tasks`, `preferences`, `updates`, `write_coordination` | 已鉴权业务调用和绑定的可信批准 | 用户与企业隔离，写入一次性许可、旧值校验、回读与状态分离 |
| `rules` CLI | 本地 `--simulate-rule-manager` 独立模拟管理身份 | 改变隔离规则版本和启停状态。规则只读工具无管理权限 |
| `scheduler` | 模型建议计划，运行时决定执行 | 实际请求与 Handler 计数，逐 ID 返回，限额 9/12/2/1 |
| `model_config`, `model_transport` | 本地 Profile/环境配置，模型不能配置连接 | 按操作者和账号选择，HTTPS URL 校验。仅使用虚构配置和 mock，禁用网络 |
| `trace`, `thinking_protocol` | 来自用户、模型、工具和本地错误的数据 | 私有协议与日志分离，JSONL 脱敏、关联和故障降级 |
| `importer` 与迁移 | 本地操作者选取 Excel 或目标路径，Excel 单元格不可信 | 校验并原子发布，已有库拒绝覆盖，迁移保留数据 |
| `tests/closure_approval.py`, `scripts/verify_c_closure.py` | 测试操作者与虚构库 | 仅测试辅助路径，生产运行时不得引入测试批准或历史 nonce |

`SIMULATED_CLI_IDENTITY` 是比赛本地入口。审计未发现公开服务路由。表中的 `UNTRUSTED_MODEL_INPUT` 按真实 Loop 或调用链注入，公网可达性和真实模型行为均单列未测。

## 复用案例

以 `test` 名称定位原有测试，运行一次全量时复用其断言。以下 B 列表示原断言核验数据库、审计或业务状态。既有子进程保持各自原超时。并发用例最多两个工作者。

| ID | 入口、输入和初态 | PASS 条件与观察 | 原测试选择器后缀 | B |
|---|---|---|---|---|
| ACL-01 | 真实 Handler 与官方库 U001/U002 | 允许合法读写，拒绝越权读写。同号发票按企业分隔 | `test_u002_cannot_read_c002`, `test_u002_cannot_modify_c001`, `test_cross_company_invoice_key_isolated`, `test_permissions_and_readonly_fields` | 是 |
| ACL-02 | Agent 工具参数伪造 actor、确认和管理员工具 | Schema/白名单拒绝，零写入 | `test_model_cannot_override_user_identity`, `test_extra_confirmed_field_rejected`, `test_model_cannot_invoke_commit_or_rule_manage` | 是 |
| ACL-03 | Agent 缺年月、伪来源、历史任务和 Schedule；合法跨轮 | 有来源才读，不能洗白日期，真实范围正常成功 | `test_missing_period_never_executes_monthly_sql`, `test_model_source_label_is_not_a_proof`, `test_old_result_does_not_launder_a_period`, `test_schedule_cannot_authorize_guessed_period`, `test_task_list_cannot_launder_an_unselected_period`, `test_current_complete_then_session_completion` | 否 |
| ACL-04 | 任务/偏好不同用户企业、取消、重启和失效引用 | 读不到他人的状态，取消不撤销已提交事实，不继承授权 | `test_user_company_isolation_and_authorization`, `test_preference_crud_conflicts_and_isolation`, `test_real_process_exit_and_restart_restore_task_and_preference`, `test_cancel_does_not_undo_successful_invoice_commit`, `test_invalidated_reference_never_revives_after_restart` | 是 |
| ACL-05 | 规则管理与权限，R003 阈值及版本 | 独立管理授权，版本冲突/停用及金额门槛按规则 | `test_rule_management_independent_conflicts_and_disable`, `test_rules_versions_threshold_spaces_and_month` | 是 |
| WRITE-01 | 发票 Prepare/Confirm/Commit，错误/重放 | 未授权不更新，无重复审计，跨会话不继承 | `test_no_confirmation_or_old_session_cannot_commit`, `test_revoked_permission_at_commit_and_fingerprint_conflict`, `test_commit_audit_isolation_restart_and_idempotence`, `test_old_confirmation_invalid_after_new_turn`, `test_cancel_clears_pending_intent`, `test_identity_switch_invalidates_draft`, `test_restart_does_not_restore_commit_authority`, `test_pending_draft_and_approval_cannot_cross_switch` | 是 |
| WRITE-02 | 故障注入旧值、审计、提交 ACK、回读、Trace/API | 审计和更新同进退，ACK 不明查审计，故障不掩盖已提交事实 | `test_conflict_and_audit_failure_rollback`, `test_commit_ack_lost_queries_history_instead_of_rewriting`, `test_readback_failure_is_unknown_not_success`, `test_trace_failure_after_verified_commit`, `test_success_then_invalid_response_or_api_error_preserves_evidence` | 是 |
| WRITE-03 | 管理候选、篡改旧对象、过期及重复许可 | 具体批准才保存，跨轮/身份及内容不符拒绝 | `test_approval_is_one_use_and_expires_next_turn`, `test_concurrent_change_between_confirmation_and_write_conflicts`, `test_update_delete_and_target_change_require_confirmation`, `test_scope_old_object_identity_and_fingerprint_rejected` | 是 |
| WRITE-04 | 当前值匹配、权限撤销、日志异常和模型声称成功 | 实时核对，区别匹配与 Commit，无额外审计 | `test_matching_value_is_read_evidence_not_commit`, `test_different_value_or_denied_is_not_a_match`, `test_model_history_claim_requires_a_real_new_readonly_check`, `test_plain_false_commit_is_never_a_receipt` | 是 |
| RES-03 | 长历史、长结果及预算边界 | 保留配对，超限安全停止，无额外授权 | `test_context_bound_keeps_whole_tool_pairs_and_current_input`, `test_oversize_current_tool_result_stops_safely`, `test_two_extensions_then_hard_nine_requests`, `test_multiple_calls_cap_twelve_pair_all`, `test_replan_once_only_and_cannot_erase_executed_fact`, `test_repeat_is_blocked_without_another_handler_execution` | 否 |
| INJ-01 | 备注、偏好、任务和历史中伪命令/角色 | 不能取得系统角色、改写能力或真实执行证据 | `test_invoice_remark_prompt_injection`, `test_bank_remark_prompt_injection`, `test_fake_system_role_inside_tool_result`, `test_tasks_preferences_are_scoped_data_not_system`, `test_restore_tool_does_not_authorize_invoice_prepare`, `test_preference_text_and_model_fields_cannot_grant_authority` | 是 |
| CONFIG-01 | 模拟 Profile 权限、缺失环境和切换 | 私有配置隔离，失败不 fallback，历史不串联 | `test_user_visibility_and_selection_never_falls_back`, `test_legacy_complete_groups_and_no_mixed_fields`, `test_unsafe_urls_and_unsupported_protocol_rejected`, `test_cross_account_and_standard_switch_always_reset_private_history`, `test_atomic_failure_and_malformed_config_preserve_old_file` | 否 |
| TRACE-01 | 结构化凭据、私有推理、URL 与计数 | 机密字段不可见，保留合法计数，Trace 故障不改变业务 | `test_redaction_preserves_business_keys_and_usage`, `test_nested_json_headers_urls_and_mixed_exception_text`, `test_trace_failure_does_not_change_actual_sdk_result` | 否 |

## 独立探针

命令 `python scripts/sec_a_probe.py <ID>`，每次一个新进程和临时目录，外层超时 10 秒。探针内禁用 socket 连接，异常和断言分别记录。B 判定只核验数据库或业务后果，配置和日志自身的问题记录在 D。普通攻击输入最多 65,536 UTF-8 字节，嵌套 32 层，每批新增探针最多两个工具调用。XLSX 只修改官方小夹具的副本，每个文件 128 KiB 上限。SQLite 变异最多两行。所有凭据标记均为合成字符串。

| ID | 入口、初态和受控输入 | PASS 条件与观测 | B |
|---|---|---|---|
| ACL-06 | Agent U001 新会话，用户指定 2026-09 与 2025-08，模型请求两组交叉拼出的 2026-08 | 交叉月份不能进入查询。对照明确 2026-08 必须有数据。捕获实际工具状态与月份 | 是 |
| ACL-07 | 可信直接 `handle_tool` 与 Agent 比较。模型缺日期、伪造 `provenance` 字段，另用跨用户 proof | 兼容直调只在可信内部可成功。Agent 始终传入 ScopeProof，缺日期和伪参数被拒。跨用户 proof 拒绝 | 是 |
| RES-01 | Agent 模型 JSON 工具参数重复键、非法 JSON、数组、32 层嵌套、非法日期、极大年份、Unicode 空白、非法动作/ID | 安全拒绝或停止，不抛到 CLI，不改业务表，返回的合法 ID 配对 | 是 |
| RES-02 | 真实汇总 Handler，虚构 C001 某月两条金额改至 SQLite int64 溢出 | 返回错误，无伪零金额或部分写入，库完整 | 是 |
| RES-05 | 真实发票列表与汇总，合成退款行 `-1` 分及同月正金额 | 支持时明细/汇总与独立 Decimal 一致，或明确拒绝。不得静默给错符号与金额 | 是 |
| RES-06 | Agent U001 新会话，65,536 ASCII 字节的聊天输入 | 默认上下文超过 48,000 字符安全停止，模型调用 0 | 是 |
| RES-04 | 初始化新库，缺页/重复标题/金额与日期异常/重复数据行/损坏文件/错误路径/原目标已存在；一次合法对照 | 畸形输入明确拒绝，不发布半成品，不改已有库，释放暂存文件；合法可导入 | 是 |
| CONFIG-02 | `safe_url` 与本地数值解析，可信 CLI 配置 `https://127.1` 和 `https://127.0.0.1` | 两种回环表示均应拒绝。不建立连接、不查 DNS。记录可信配置可达性 | 否 |
| TRACE-02 | Agent 记录用户输入含纯文本 Cookie 和嵌套 JSON 凭据，合成标记，真实 JSONL | Cookie 和凭据样式均不落明文，业务统计保留 | 否 |
| TRACE-03 | Agent 有 Trace，模型 assistant 合成响应含 JSON 可转义的孤立 surrogate；另做同输入无 Trace 对照 | 安全拒绝或降级，Trace 编码失败不得使 turn 异常退出。数据库无写入 | 是 |
| TRACE-04 | 真实 `rules disable` CLI，模拟独立管理权限，隔离官方规则库 | 改版成功后有可关联的独立管理事件记录 actor、旧/新状态、版本。观察表与 JSONL，缺失判 G06/G07 可审计性缺陷 | 是 |

## DISCOVERED_AFTER_INITIAL_FREEZE

| ID | 入口、初态和受控输入 | PASS 条件与观测 | B |
|---|---|---|---|
| RES-07 | `initialize_database`，用 `data_only=True` 将虚构夹具已有核对缓存物化后保存三个副本。对照仅重存，另两份分别追加重复可选标题 `用途` 或将 F002 改为 -0.01 元并调整核对值 | 对照成功。重复标题必须拒绝，不能以第二列覆盖；负金额若被接受，查询明细必须精确。独立 SQL 查实际保存的值。每份文件上限 128 KiB，原探针和首次结果保留 | 是 |
