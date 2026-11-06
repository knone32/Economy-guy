# S4-A：当前版本独立回归基线

## 版本与范围
- 验收日期：2026-11-06（北京时间）。仓库 `knone32/Economy-guy`，分支 `main`。
- **被测 Code SHA：`3c45103f8167ba9482e3d961b359d6bb8bce0daa`**，与给定历史基线相同；测试开始时工作树干净。
- **证据提交 SHA：与被测代码 SHA 区分**。本轮仅新增本报告，最终提交号以 `git log -1 --format=%H -- docs/verification/stage4/S4-A.md` 查询；最终回复给出实际 SHA，不向文件写入它自身尚未产生的提交哈希。
- 本次没有修改源码、测试断言、架构或依赖，没有开始 S4-B/G1/G2。旧快照的204项结果不作为本次证据。
- Python 3.12.14 / Windows AMD64；SQLite 3.53.1；openpyxl 3.1.5。声明依赖为 `openpyxl>=3.1,<4`、`openai>=1,<2`，当前解释器没有安装openai SDK，也没有API配置；没有安装/升级依赖或调用真实模型。
- 使用包内官方1.1.0虚构夹具 `finance_agent/tests/fixtures/example.xlsx`，已与本地官方副本比较SHA-256相同；每个测试使用隔离临时SQLite。测试前后所有原有Git跟踪文件及正式财务数据库哈希保持不变。

## 本轮实际执行

工作目录为 `finance_agent/`，使用上述Python解释器；设置UTF-8输出、禁写字节码、显式FINANCE_TEST_EXCEL指向虚构夹具，并从测试子进程环境移除live API配置。下列命令均为本轮重新执行：

| 命令 | 通过/总数 | 失败 | 错误 | 跳过 | 退出码 |
|---|---:|---:|---:|---:|---:|
| `python -m unittest tests.test_management_confirmation -v` | 15/15 | 0 | 0 | 0 | 0 |
| `python -m unittest tests.test_stage3a tests.test_stage3b tests.test_stage3c tests.test_security_boundaries tests.test_architecture -q` | 108/108 | 0 | 0 | 0 | 0 |
| `python -m unittest discover -s tests -q` | 219/219 | 0 | 0 | 0 | 0 |

定向组是全量的子集，不能相加声称为独立用例总数。失败堆栈：无（上述三组均成功）。入口与用户要求一致，无调整或新增测试。

完整stdout/stderr、命令、退出码、测试数量、环境、源码/正式库前后哈希及测试函数行号仅保存在本地忽略目录：`artifacts/s4_a/20261106T102507+0800-3c45103f8167/`，不入Git。日志完整性摘要：

| 本地原始输出 | SHA-256 |
|---|---|
| `management_confirmation.txt` | `f0a90f61218e06c1eb22917ece083711b8fd728cada351978a43d0d300f4c75c` |
| `stage3_security.txt` | `9dca1fa5aca6e90bc24610ae0105da214300c7661a6634dff283f46b3752ab6e` |
| `full.txt` | `a90160ee9a81bdd7b1d02a51c7f583df5c57a2baa3c7025f90a0341a8001367f` |

## 安全与预算验收矩阵

以下证据均为当前 `finance_agent/tests/` 下的现有测试函数。PASS仅保证列明的Python/Mock/真实临时SQLite场景，不等于真实LLM验证。

| 检查 | 结论 | 对应证据（测试文件：函数） |
|---|---|---|
| 错误偏好内容未经可信确认不能保存 | PASS | `test_management_confirmation.py: test_malicious_preference_value_not_saved_without_confirmation`，核对实际preferences行数为0 |
| 错误任务说明未经可信确认不能保存 | PASS | `test_management_confirmation.py: test_malicious_task_note_not_saved_without_confirmation`，核对实际tasks行数为0 |
| 具体对象/内容正确确认可保存；取消不保存 | PASS | `test_correct_confirmation_saves_exact_preference`、`test_task_note_correct_confirmation_and_cancel`、`test_cancel_or_non_boolean_confirmation_never_saves`（均在test_management_confirmation.py） |
| 管理确认不可跨轮、跨身份、重复使用 | PASS | `test_management_confirmation.py: test_unused_confirmation_expires_on_next_turn_and_identity_change`、`test_approval_fingerprint_binds_key_value_company_and_one_use` |
| 不能替换已确认的企业/对象/内容 | PASS | `test_management_confirmation.py: test_task_approval_binds_note_and_joint_target`、`test_approval_fingerprint_binds_key_value_company_and_one_use`；另测确认期间旧值变化CONFLICT及撤权DENIED |
| U002不能读取C002或修改C001发票 | PASS | `test_security_boundaries.py: test_u002_cannot_read_c002`、`test_u002_cannot_modify_c001` |
| Commit必须有可信确认、同事务成功审计与回读 | PASS | 全量中的 `test_stage2.py: test_no_confirmation_or_old_session_cannot_commit`、`test_commit_audit_isolation_restart_and_idempotence`、`test_conflict_and_audit_failure_rollback`；失败回滚、当前值与审计数量均有断言 |
| 任务恢复不继承旧发票写入许可 | PASS | `test_stage3a.py: test_restore_tool_does_not_authorize_invoice_prepare`、`test_restart_has_no_old_draft_or_confirmation`，无草稿/确认及无成功审计 |
| 单轮model_requests ≤ 9 | PASS | `test_stage3c.py: test_two_extensions_then_hard_nine_requests`，实际计数9；`test_budget_config_may_reduce_but_not_bypass_hard_limits`拒绝更高配置 |
| actual_tool_calls ≤ 12，并与requested区分 | PASS | `test_stage3c.py: test_multiple_calls_cap_twelve_pair_all`，模型提出14项、实际进入Handler 12项，多余项配对拒绝；本轮不把requested条目数解释为实际执行数 |
| extensions ≤ 2，replans ≤ 1 | PASS | `test_stage3c.py: test_two_extensions_then_hard_nine_requests`、`test_replan_once_only_and_cannot_erase_executed_fact`及配置硬限反例 |
| 所有Tool Call ID均配对，包括拒绝、错误和预算跳过 | PASS | `test_stage3c.py: test_multiple_calls_cap_twelve_pair_all`、`test_denied_stops_and_keeps_first_reason_with_multiple_calls`、`test_last_model_request_prepare_only_waits`；全量中的 `test_agent.py: test_errors_pair_all_results_and_stop` |
| Scheduler重复/无进展/权限拒绝/等待确认/硬限安全停止 | PASS | `test_stage3c.py: test_repeat_is_blocked_without_another_handler_execution`、`test_no_progress_cannot_extend`、`test_denied_stops_and_keeps_first_reason_with_multiple_calls`、`test_prepare_waits_and_never_extends_or_commits`、`test_two_extensions_then_hard_nine_requests` |
| 任务完成必须有真实业务依据，不认模型口头完成 | PASS | `test_stage3a.py: test_complete_requires_current_business_evidence`（补齐实际发票、5条成功审计、规则检查缺失数0）；`test_stage3c.py: test_fake_model_completion_keeps_pending_steps` |
| JSONL Trace记录mock、续期理由与最终执行状态 | PASS | `test_stage3c.py: test_trace_budget_reasons_and_mode`；全量中的 `test_agent.py: test_trace_redacts_and_marks_mode` |
| Trace故障不掩盖已提交事务、不重复写入 | PASS | `test_security_boundaries.py: test_trace_failure_after_verified_commit`、`test_trace_failure_does_not_duplicate_commit`，核对COMMITTED、降级标志及SQLite事实 |
| 真实LLM/API端到端的规划、追问、确认及Trace | NOT_TESTED | 本次只用Mock，SDK和API配置未就绪，不以单测代替真实模型验收 |
| 目标契约§6事件名称对外部消费者的兼容性 | NOT_TESTED | 当前使用model_input/model_reply/tool_result/schedule.progress等实际事件名；本轮检验既有字段与状态，未验证其与目标示例llm.request/tool.completed等名称的外部映射 |

## 结论与S4-B准入

- 本轮回归FAIL项：无。管理确认补丁和旧安全边界的现有用例通过，代码与测试没有为验收改变；仅提交本脱敏报告，原始运行日志不提交。
- 当前S4-A明确采用actual_tool_calls执行上限口径。旧验收关于原始requested条目≤12的条件性FAIL不能与本次明确区分两类计数的判据混用；原始提案可能超过12，但实际执行受限且拒绝结果完整配对。
- **具备进入S4-B的回归基线条件：是。** 这只表示可以由用户另行授权开展真实模型验收；本轮没有开始S4-B，也没有取得真实模型通过结论。
- 真正执行S4-B前仍需准备隔离的测试库、安装声明的openai SDK、配置合法API服务；再核验真实工具调用/用户确认/回读和Trace。没有生产登录，本轮CLI身份及确认回调仍是比赛模拟可信入口。
- 其他未验证边界：干净venv联网安装/跨平台执行、任意自然语言内容语义一致性、任意Prompt注入和整个服务商token窗口（当前Context限制消息字符数，不含工具Schema）。这些不是本轮219项通过可推出的结论。
