# S4-P-B：权威结果呈现、财务汇总与当前任务进度

## 版本、边界与结论
- Base SHA：`b70545a6da6be436a0e988f80255afaec8871544`；开始时main工作树干净、远端一致。
- Tested Code SHA：`ccd184ff9c877a685127cc8922d15ae10aec7aec`。确定性测试和以下live均使用此源码；后续报告/总纲提交不改源码。
- Report SHA：独立文档提交，使用 `git log -1 --format=%H -- docs/verification/stage4/S4-P-B.md` 或最终回执取得，避免自引用SHA。
- **4P-B DETERMINISTIC PASS / LIVE PARTIAL / PROVIDER_BLOCKED**。不能宣布完整live通过：L2原请求失败，重复工具调用live未观察到，提交后同会话被既有Thinking协议阻断。建议单独授权4P-C，未自动执行。
- Python 3.12.14、openai 1.109.1、openpyxl 3.1.5；DeepSeek `deepseek-flash`，Base URL `https://api.deepseek.com`。复用原已授权DPAPI本地配置，未打印/提交密钥，没有新依赖。
- 所有实验使用官方虚构fixture新建的3个隔离SQLite，Stage2/3A/3B加法迁移及官方规则；没有读取或修改正式finance.db。所有确认均为 **scripted confirmation，非真人确认**：实际CLI展示具体内容后，仅目标/字段/内容与预定义验收输入匹配才输入完整confirm ID。

## 复现、改动及职责
| 编号 | 根因与修复 | 实现位置 |
|---|---|---|
| P02 | 原finish错误分支抛弃read_results。现在所有逐ID结果含跳过项进入本轮证据，异常收尾只渲染真实SUCCESS/NO_DATA/NO_CHANGE及实际停止原因、未完成项；拒绝项不展示data，不修改Scheduler停止状态 | Agent.ask、responses.render_stopped/render_information |
| P04 | 原补月份后模型可能只选择明细。增加通用综合工具说明及“补充仍继续原目标”提示；明细工具也在同一鉴权快照复用finance.get_finance_summary返回金额/计数，按各自真实范围展示R001，不跨范围拼加。金额规则缺失时保留原明细及summary_status，不渲染缺依据附加汇总 | agent.SYSTEM、tool_registry.handle_tool、responses.render_information/render_scope |
| P05 | 原Commit后无当前任务进度展示。仅在原审计/request_id/指纹/Readback全部核实的COMMITTED/NO_CHANGE后，tasks.task_progress只读查匹配未完成任务，复用_check/RuleDecision重算；CLI只格式化当前剩余对象。进度失败独立报告，不否定已核实Commit，不自动完成任务 | tasks.task_progress、WriteCoordinator.commit_update、main.main、responses.render_task_progress |
| 组合目标 | 原计划校验拒绝自然语言候选。复用_management_context允许有效候选预览排入依赖步骤；具体管理工具仍须可信内容确认，计划及续期不生成Approval/扩大权限 | Registry._set_schedule/remaining_work_allowed；原TurnExecution不改 |

改动源码6个：app/agent.py、responses.py、tasks.py、tool_registry.py、write_coordination.py、main.py。新增tests/test_stage4pb.py（18项）；更新docs/flows/query.md、update-invoice.md、tasks-preferences.md。业务计算、规则解析、事务更新、Context、Scheduler、Schema未重写；原238项测试文件及断言全部保留。

异常收尾保留事实但不新增可复用引用锚点；等待确认明确“尚未保存”，预算/上下文上限明确标注。自由文本不是成功凭证。正常问候与追问能力继续由原安全协议处理。

## 确定性测试证据
命令均在finance_agent/执行，python指本地隔离解释器。重复运行子集不累计为独立测试数量。

| 执行 | 结果 | 退出码 |
|---|---|---|
| 修改前 `python -m unittest discover -s tests -q` | 238通过，0失败/错误/跳过 | 0 |
| 先新增反例 `python -m unittest tests.test_stage4pb -v` | 初稿15项，12个失败（含subTest）/3错误，原样保留before.txt；涵盖丢失成功证据、缺汇总、无进度接口及计划拒绝 | 1 |
| 首次回归（中间版本） | 指定安全子集140项5失败；全量253项7失败：补充金额规则错误阻断旧明细、错误收尾锚点和必要停止提示退化 | 1 |
| 最终 `python -m unittest tests.test_stage4pb -v` | **18通过，0失败/错误/跳过** | 0 |
| `python -m unittest tests.test_stage4pa tests.test_management_confirmation tests.test_stage3a tests.test_stage3b tests.test_stage3c tests.test_security_boundaries -q` | **140通过，0失败/错误/跳过** | 0 |
| `python -m unittest tests.test_architecture -v` | **2通过，0失败/错误/跳过** | 0 |
| `python -m unittest discover -s tests -q` | **256通过，0失败/错误/跳过**，24.595秒 | 0 |

没有删改旧断言：中间失败修复为“金额规则缺失不阻断既有只读明细”“错误收尾不新建锚点”“保留确认/上下文/预算提示”。新反例编写时另纠正了NOT_FOUND应为正常空结果的假设、规则DISABLED枚举拼写，未降低业务断言。完整输出在本地忽略目录artifacts/s4_pb/，Git不提交原始日志。最终全量发生于live前，live后源码未变。

18项新测试覆盖：读取/任务保存/偏好更新后重复、API/非法回复/工具预算停止后保留事实、混合DENIED/INVALID_ARGUMENTS/ERROR不泄露数据、无证据不成功；A2跨轮、修改夹具金额1分验证非硬编码、企业月份空集与更正；5→4和新进程读取、remark/NO_CHANGE/取消/冲突、规则与权限错误；组合计划确认/取消/无回调零写入。原安全套件继续证明发票审计回滚、U002隔离、确认内容绑定、Trace故障及9/12/2/1边界。

## 真实DeepSeek目标测试
实际路径为main.main(chat live) → 原Agent/live_model → 官方API → Registry → SQLite。辅助脚本只驱动stdin、精确scripted confirmation并被动捕获HTTP使用量，断言实例model仍为原live_model；没有构造live Tool Call、修改请求体、关闭Thinking或注入协议字段。

| Case / Trace ID | M/R/T | 实际工具、停止原因 | 状态与核验 |
|---|---|---|---|
| L1_A1 `3efac544ca2a49189758fcf45704a739` | 1/0/0 | 无工具；WAITING_USER | PASS：原问句“帮我看看甲企业的发票和银行收支。”→请提供年份和月份，不猜月份 |
| L1_A2 `a78dd194e40248cca6c7927f43cdeed8` | 2/1/1 | get_finance_summary SUCCESS；ANSWERED | PASS：同进程只补“2026 年 9 月。”，显示C001范围、全部金额/计数与R001 v1.0 |
| L2_save_verify `e8d2e799d3d84ece9424a722c9b4d3d8` | 1/1/1 | manage_preference(get) NOT_FOUND；NOT_FOUND | FAIL/UX：原“请记住C001的reply_format回复偏好为简洁，并核对保存的内容。”模型先查不存在对象，未产生提案、无写入；不是P02成功被覆盖 |
| L2_create_retry `4b9d0bde5927418a8cc90f035b052016` | 2/1/1 | manage_preference(create) SUCCESS；ANSWERED | PASS（仅诊断对照）：新进程一次明确“为C001新增一个长期回复偏好，名称reply_format，内容简洁。”，精确提案确认后保存并展示。原L2仍FAIL |
| L3_create `d1c139112c4c419b850adb483e3d7d2f` | 3/2/2 | check_missing_purpose SUCCESS、manage_task SUCCESS；ANSWERED | PASS：普通自然语言先检查5项后产生无权限候选，具体说明确认后保存ACTIVE；没有/task前缀 |
| L3_commit `d7dddae134e0463da36ff195fd103fa0` | 1/1/1 | prepare_invoice_update WAITING_CONFIRMATION；Loop等待，CLI后COMMITTED | PASS：真实/edit、脚本可信确认、审计回读；CLI直接显示当前剩余4项、任务仍ACTIVE及下一步 |
| L3_followup `5a6e79bdc2ba4f9db83882a6dbe68a9c` | 1/0/0 | HTTP400；API_OR_RESPONSE_ERROR | PROVIDER_BLOCKED：同进程“C001 2026年9月的待办现在还剩哪些缺失用途？下一步应处理什么？”；未回滚已有提交，不重试已知故障 |
| L3_restart `3ecc029db57c4a9aa5c273fd1920a5b4` | 2/2/2 | list_tasks SUCCESS、check_missing_purpose SUCCESS；ANSWERED | PASS：全新进程重新读取相同task_id及真实4项，无旧草稿/确认 |

M为模型请求尝试，R为模型提案条目，T为实际Handler尝试。**真实重复调用/NO_PROGRESS未观察到**，P02该分支仅Mock验证，未强迫模型重复来制造live PASS。上述L3创建原句保留组合语义，并额外明确待办说明为“下次继续补齐用途”，没有指定工具名。

协议失败原文：`The reasoning_content in the thinking mode must be passed back to the API.`。本轮未修复；属于4P-C/E复验事项，不能归因为Task Manager存储损坏。仅发生一次，无同故障盲重试；L2仅一次新增目标的诊断对照。

## SQLite、Audit与跨进程独立核验
- 23项独立只读检查全部通过。L1整数分SQL：价税合计962206分/10张；收入1300050分/4条；支出718074分/8条，与用户可见9622.06、13000.50、7180.74逐项一致；R001 v1.0来自当前规则。
- 任务及偏好确认提示出现时，各自对应表仍0条。确认后仅保存U001/C001的指定内容；原L2 NOT_FOUND之后偏好仍0，对照确认后reply_format=简洁。
- 任务ID `340f72ae08314a88bddd270a90ef7862`；创建PID42352 → 提交PID60356 → 重启查询PID26852，是真实不同Python进程。任务始终ACTIVE，目标U001/C001/2026-09，未手工更新任务表。
- Commit request_id `573f0e44449840cfa4fc606fc19ce7fa`；actor U001，C001/F002，purpose，None→项目资料归档。成功审计仅1条；指纹独立重算为 `730cb79524cd43231bb330658a08f1886601ee2cee29bf15d529ef9b50950913`，与原草稿/审计一致，新只读连接回读同值。
- Prepare确认前发票和审计未变；逐字段比较仅C001/F002 purpose改变，C002同号及所有其他字段、银行、规则不变。用途缺失5→4，回执task_progress、实际CLI文字和新进程缺失对象集合均与当前SQLite一致。
- 同会话HTTP400后审计/任务/当前缺项事实均保持，不将新轮NOT_SUBMITTED解释为上一轮提交不存在。发票进度展示是当前快照，不是新的成功发票数或自动任务完成。

## Trace、预算及真实用量
- 8轮，13个model_input/budget/context.selected，12个model_reply；1次HTTP400有错误与安全终止，无伪造回复。turn.started/turn.finished/execution.stopped各8。
- **8个tool.requested与8个tool_result逐ID、顺序完整配对**。update.result 1次，与真实COMMITTED审计/回读核对。
- 单轮最大model_requests=3、requested_tool_calls=2、actual_tool_calls=2；extensions=0、replans=0、block_limit=3。没有schedule.created、budget.extended或replan：NOT_OBSERVED；Mock覆盖必要组合计划和硬限，不生成假live事件。
- 原schedule.progress无计划也触发的问题仍存在：本次6条，留4P-D处理，不能把它们算作真实计划。
- **API尝试13次，HTTP200=12、HTTP400=1**；本轮无GET /models或额外探针。成功响应实际prompt_tokens=**43987**、completion_tokens=**2067**、total_tokens=**46054**；1次失败usage未知，不当0。真实费用/余额未查询、未知，未按Token估算实际扣费；约¥35提醒线只能由官方账单核实。
- 被动HTTP测量的逐请求耗时（秒）：L1_A1 `[1.460]`；L1_A2 `[0.821,1.456]`；原L2 `[2.038]`；L2对照 `[1.162,1.088]`；L3创建 `[1.775,1.261,2.172]`；Commit `[1.304]`；失败续问 `[0.250]`；重启 `[1.309,1.923]`。含客户端请求/响应时间，不称服务端推理时延。
- 本地忽略证据：`artifacts/s4_pb/live_20261106T053026/`（配置与密钥不在此报告）；包含每轮原始输入/结果、必要脱敏HTTP元数据、Trace、前后虚构快照、PID、audit_summary.json。私有协议reasoning正文未保存，仅被动记录是否存在；原始日志/数据库/配置均未提交Git。

## 门禁与剩余问题
- P02/P04/P05确定性修复与原安全回归通过；L1完整自然连续查询、L3自然任务创建/受控提交/当前进度/重启读取已有真实证据。
- **未满足完整live门禁**：原L2的“先get不存在偏好”使新增意图提前停止；真实重复调用分支NOT_OBSERVED；提交后同会话继续仍PROVIDER_BLOCKED。没有用诊断对照覆盖原失败、没有改变Scheduler停止语义来伪装通过。
- 下一步建议单独授权4P-C解决必要Thinking回传，并在4P-E复验同会话完整流程及偏好管理语义；L2 NOT_FOUND的交互策略需保留为独立UX缺口，不在本轮扩大修复。未实现Provider Profile、日志新平台或任何4P-C/D/E功能。
- 历史S4-A/S4-B/S4-P-A报告保持原状。只提交本轮源码/测试/流程及本报告和总纲增量，不提交实验产物或凭据；Git远端核对结果以最终回执为准。
