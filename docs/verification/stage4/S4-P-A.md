# S4-P-A：自然语言管理候选、偏好CRUD与安全追问

## 版本与范围
- 修改前：`main@7f9f17be7a50ffcaffa46587c75d9d81f37b4d01`，开始时工作树干净。
- 修改后/被测代码：`0c043151d24ab63394ca674516d711c86435f3ac`。最终测试执行的源码与此提交一致。
- 本报告独立提交；报告SHA以 `git log -1 --format=%H -- docs/verification/stage4/S4-P-A.md` 和最终交付为准，与上述代码SHA区分。
- 依据：AGENTS.md、ARCHITECTURE_CONTRACTS §2/§5、S4-B F01/F04及真实调用链。仅4P-A；没有进入4P-B/C/D/E。
- Python 3.12.14，复用本地隔离解释器；没有安装新依赖。所有新测试用官方虚构夹具和TemporaryDirectory SQLite，未读取/修改正式库。
- **真实API调用0次**。以下为Python确定性测试、Mock及实际CLI/子进程证据，不表示真实模型理解或live验收通过。

## 复现与修复
1. **F01普通自然语言管理被提前DENIED**：Registry原先要求显式ManagementTurn。现在Agent每轮只创建无权限的ManagementProposals生命周期；模型参数经Schema、企业权限及明确范围检查后，成为ManagementCandidate。它不能通过can_manage，业务服务can_propose只允许预览，永远先返回WAITING_CONFIRMATION，不保存。
2. **可信内容授权**：CLI复用原确认入口，展示original_request、完整proposal、current、request_id及fingerprint。用户输入完整confirm request_id后，confirm_management才为自然语言候选建立ManagementTurn/Intent和一次性Approval。业务服务新事务重新鉴权、比对内容指纹和旧对象。取消、非True回调、身份变化、旧值冲突不写入；下一轮及/cancel撤销来源生命周期。
3. **F04偏好删除入口说明**：移除模型必须看见/preference前缀的限制，明确create/update/delete候选及get/list用途；delete使用明确key和空value，展示真实旧对象。显式/task、/preference继续保留领域/动作约束，不会在拒绝后退回自然候选路径。直接argparse管理接口保持兼容。
4. **非法missing_fields导致追问中断**：合法字符串型未知标签使用程序生成的通用补充问题，保留Pending Edit Intent；已知管理标签有明确中文问题。未知标签不映射到业务字段，不展示任意模型text或成功声称。JSON结构/字段类型非法仍安全停止；实际工具参数白名单未放宽。
5. **确认期间身份变化**：先撤销候选/授权，返回DENIED，并完整配对原tool_call_id；在下次身份入口清理历史上下文，避免在配对途中删掉assistant工具请求。

没有改动发票Prepare/Confirm/Commit、审计/回读、单未完成任务索引、Context Controller或Scheduler预算策略。唯一Loop仍为Agent.ask；没有关键词业务路由或第二模型。

## 修改文件与所有权
| 文件 | 本轮职责变化 |
|---|---|
| finance_agent/app/agent.py | 每轮无权限候选生命周期、确认期间身份检查、模型可见管理说明；仍为唯一Loop |
| finance_agent/app/tool_registry.py | 复用manage_task/manage_preference，候选预览与可信确认分流；保留Schema及Handler鉴权 |
| finance_agent/app/persistence.py | ManagementProposals/Candidate、can_propose；确认后建立受限授权，绑定内容/旧值及来源生命周期 |
| finance_agent/app/tasks.py、preferences.py | 允许无权限候选进入预览；实际写入仍须通过原确认和事务校验 |
| finance_agent/app/responses.py | 未知追问标签安全降级，不改变业务工具字段 |
| finance_agent/main.py | 更新CLI提示，普通自然语言也可提出需确认的候选；复用原确认输入 |
| finance_agent/tests/test_stage4pa.py | 19项定向反例/回归测试，含CLI及真实新进程读取 |
| finance_agent/README.md、docs/ARCHITECTURE.md、docs/flows/tasks-preferences.md | 更新实际入口、调用链、权限与验证边界 |
| docs/verification/stage4/S4-P-A.md | 本报告，与代码分开提交 |

SQLite仍是任务/偏好的唯一持久权威；Agent只持有当轮候选/许可生命周期。业务层没有反向导入运行层。没有新增业务状态表或迁移。

## 实际测试与退出码
以下在finance_agent目录运行；python指本地隔离Python解释器。数量不可把重复执行相加为独立用例数。

| 阶段 | 命令 | 实际结果 | 退出码 |
|---|---|---|---|
| 修改前基线 | `python -m unittest discover -s tests -q` | 219通过，0失败 | 0 |
| 先复现反例、未改业务源码 | `python -m unittest tests.test_stage4pa -v` | 当时13项，FAILED(failures=14)，含subTest失败；自然候选被DENIED、未知标签中断 | 1 |
| 首轮实现验证 | `python -m unittest tests.test_stage4pa tests.test_management_confirmation -v` | 当时28项，27通过、1错误：新子进程输出编码不一致 | 1 |
| 最终定向 | `python -m unittest tests.test_stage4pa tests.test_management_confirmation -v` | 34通过，0失败/错误/跳过 | 0 |
| 架构 | `python -m unittest tests.test_architecture -v` | 2通过，0失败/错误/跳过 | 0 |
| 旧安全边界 | `python -m unittest tests.test_security_boundaries -q` | 35通过，0失败/错误/跳过 | 0 |
| 最终全量 | `python -m unittest discover -s tests -q` | **238通过，0失败/错误/跳过**，12.456秒 | 0 |

编码错误只修新测试：子进程显式使用Python `-X utf8`，没有删用例或降低断言。全部原有219项测试源码/断言保持原样，新增19项。完整原始输出本地保存于忽略目录artifacts/s4_pa/，不提交原始日志。

## 验收证据索引
| 检查 | 状态 | 测试函数（test_stage4pa.py，除另注） |
|---|---|---|
| 普通任务/偏好提案，无确认零写入 | PASS | test_natural_task_and_preference_preview_never_writes |
| 候选不是ManagementTurn/Intent授权，直接业务重调仍不写 | PASS | test_candidate_is_not_management_authority_even_in_business_service |
| 确认具体内容后精确保存，任务note/偏好value匹配 | PASS | test_natural_correct_confirmation_saves_exact_content |
| 恶意替换内容、取消及非True确认不落库 | PASS | test_malicious_content_and_cancel_are_not_approved |
| 错误企业范围/越权在确认前拒绝 | PASS | test_wrong_company_is_rejected_before_confirmation |
| 错误对象展示真实旧值，由可信用户拒绝 | PASS | test_wrong_object_is_displayed_and_user_can_reject |
| 旧值变化冲突、身份切换时拒绝且Tool ID配对 | PASS | test_old_value_conflict_after_preview；test_identity_switch_during_confirmation_denies |
| 取消期间撤权、旧ID/Approval跨轮重复使用失败 | PASS | test_cancel_during_confirmation_revokes_candidate_and_explicit_intent；test_old_cli_confirmation_id_cannot_authorize_another_turn；test_approval_is_one_use_and_expires_next_turn |
| 偏好增改删及全新进程当前值/删除后NOT_FOUND | PASS | test_preference_crud_and_delete_survives_new_process（3次真实子进程） |
| 任务说明修改、更正、取消，未改发票/审计 | PASS | test_natural_task_update_correct_cancel_require_exact_confirmation |
| 普通CLI、显式/preference兼容 | PASS | test_real_cli_natural_and_explicit_entry_confirm_proposal；原test_management_confirmation和test_stage3a继续通过 |
| 未知标签正常追问、后续补充、未扩展写入白名单 | PASS | test_unknown_missing_fields_asks_safely_and_preserves_edit_intent；test_unknown_clarification_allows_safe_followup；test_unknown_missing_fields_never_expand_tool_field_whitelist |
| 空对象、恶意confirmed/user_id、非法回复安全停止 | PASS | test_missing_object_and_malformed_question_never_prompt_confirmation；test_candidate_cannot_execute_direct_write_or_forge_confirmation |
| U002发票权限、事务审计回滚、读后核对等原安全边界 | PASS | 原35项test_security_boundaries及全量Stage0–3回归 |
| 单Loop依赖、预算9/12/2/1不回归 | PASS（Python/Mock） | test_architecture与原test_stage3c，包含在238项全量结果内 |

## 保证范围、未验证项与后续
- 不保证自动判断任意自然语言语义一致。模型即使在问候轮提出错误管理候选，也只能进入无权限预览；用户必须核对原始要求、实际对象及旧值/新值，并可拒绝。没有可信确认不能持久化。可信Python回调和直接argparse仍不是生产登录机制。
- 不能把合法JSON或模型文本作为保存证据。SUCCESS只来自业务服务的实际返回；UNKNOWN_OUTCOME仍应重查SQLite，不能当已保存。
- **NOT_TESTED/live**：真实模型能否稳定理解普通自然语言、先查再删、少重复调用及遵守追问格式；需要另轮授权的真实E2E。本轮调用量0，未重新使用任何API凭据。
- **未在本轮修复**：S4-B的DeepSeek thinking/reasoning_content多轮兼容、汇总展示缺口、提交后进度展示、重复调用停止时的体验及Trace事件语义。不能用本次Mock通过宣布这些问题已解决。
- 自然语言管理放行的是候选预览而非Schedule授权；粗计划及续期仍按原权限策略保守拒绝，不以候选扩大计划或预算。
- 建议按下一条明确任务进入4P-B；本轮只完成4P-A，未开始后续阶段。后续真实模型复验至少覆盖普通任务保存、偏好完整CRUD、错误提案取消及旧确认失效。

提交前检查diff/status与显式暂存清单；仅源码、测试和必要文档，无凭据、数据库、虚拟环境或原始日志。推送后以远程main与本地HEAD一致为交付依据。
