# S4-P-D：Profile、连接隔离及运行可靠性

## 版本、范围和环境
- 日期：2026-11-06；仓库 knone32/Economy-guy，main。
- Base SHA：`dda0ca8db5c609cea3d6688b731f0bd7fde3cc5d`；开工工作树干净，远端与该SHA一致。
- Tested Code SHA：`bd59b2e380f51a5839e2cb94fe050f49b26aa823`。下述最终离线结果和全部本阶段live均对应这份代码。
- Report SHA：包含本文件及总纲增量的文档提交（由本文件Git历史确定；不将文档提交冒充被测代码）。
- Windows PowerShell，Python 3.12.14，openai 1.109.1，openpyxl 3.1.5；使用现有隔离环境，未增加依赖。
- 只实现4P-D；未执行4P-E，未修P11。历史S4-A/B/P-A/P-B/P-C报告保持原状。

## 改动和状态所有权

| 文件 | 实际改动 |
|---|---|
| app/model_config.py（新增） | Profile校验、TOML+本地JSON、作用域、优先级、原子添加、冻结ModelConnection |
| app/model_transport.py（新增） | 唯一生产SDK调用位置、冻结凭据、协议绑定、实际usage/延迟/安全错误分类 |
| app/agent.py | 唯一Agent.ask循环保留；绑定Transport，轮次边界switch_model重建实例，保留可重查范围；计数和Trace元数据 |
| app/thinking_protocol.py | 显式连接可关闭旧环境绑定检查；原私有字段重放/裁剪协议保留 |
| app/trace.py | 按字段语义脱敏，保留业务key/Token计数，嵌套JSON/URL/异常文本处理 |
| app/scheduler.py | 无真实计划时改发tool.progress；预算/停止逻辑不变 |
| app/write_coordination.py | 已核实回执先保留，隔离附加日期解析/任务进度异常 |
| main.py | profiles list/check/add、chat --profile、/provider list/status/use；不增加模型配置工具 |
| config/model_profiles.toml（新增） | 空的非敏感静态模板；本地JSON覆盖默认忽略Git |
| tests/test_stage4pd.py（新增） | 30项确定性/Mock/临时SQLite回归；此前274项断言文件均未改 |
| README.md、docs/ARCHITECTURE.md、docs/flows/models-profiles.md | 配置命令、真实依赖及切换边界 |
| .gitignore | 排除本地Profile和编辑副产物 |

以上app等相对路径均在finance_agent/下。业务服务仍不依赖Agent/Transport/Profile；SQLite持有业务、任务和偏好事实，Profile不增加业务表。没有第二Agent Loop、自动模型路由、生产认证或新秘密存储平台。

## 配置、可信入口和会话边界
- Global添加必须显式`--simulate-profile-manager`，不会因为U001就默认管理员；User owner来自可信CLI `--user`。用户仅能列出/选择Global及自己的User Profile。`--user`仍只是比赛模拟身份，不提供生产多租户安全。
- Profile记录profile_name/scope/owner_user_id/provider/service_account_ref/model/base_url/api_key_env/protocol。service_account_ref是本地逻辑标签，不证明真实账户身份。
- 默认静态config/model_profiles.toml + Git忽略的config/model_profiles.local.json；精确字段白名单、跨来源重名/默认冲突拒绝。添加用独占编辑锁、fsync临时文件、原子替换；失败保留原文件。
- 选择顺序：CLI > FINANCE_MODEL_PROFILE > 文件默认 > 完整旧环境变量组。OPENAI_*或KEY/BASE_URL/MODEL（兼容API_KEY别名）不得混拼；指定配置失败不fallback。Mock不需要真实Key，check不产生API请求。
- Key只从选中Profile声明的环境引用解析一次，ModelConnection不在repr/Trace暴露Key；轮换须可信重建连接，不逐轮偷读环境。凭据不写TOML/JSON、SQLite或Git。
- URL拒绝非HTTPS、userinfo、query/fragment、非443、明显本地/私网IP等；不宣称防止DNS重绑定或提供公网SSRF完整防护。自定义服务端点仍需操作者信任。
- `/provider use`只在轮次之间运行，拒绝活动执行、未确认草稿、待确认管理提案及UNKNOWN_OUTCOME；成功后旧实例退休，旧草稿/确认/管理许可撤销。
- 同/异逻辑账户、换模型、Key轮换一律新协议实例；不搬运原assistant/tool/reasoning或旧回执。仅携带重新鉴权的企业/年月及标明历史来源的用户目标，任务/偏好从SQLite重读。对无法安全保留的临时消息，CLI明确提示已重建。
- 未配置的Python Agent仍可构造用于离线恢复检查，但连接错误在创建时冻结；不能在后续加Key后悄悄变成live连接。CLI live显式解析失败即报错。

## 离线证据（实际执行）

解释器为本地忽略环境`artifacts/s4_b/runtime/Scripts/python.exe`；以下命令在finance_agent/执行。

| 命令 | 结果 | 退出码 |
|---|---:|---:|
| 修改前 python -m unittest discover -s tests -q | 274/274 PASS | 0 |
| python -m unittest tests.test_stage4pd -v | 30/30 PASS | 0 |
| python -m unittest tests.test_stage4pc tests.test_stage4pb tests.test_stage4pa -q | 55/55 PASS | 0 |
| python -m unittest tests.test_security_boundaries tests.test_management_confirmation -q | 50/50 PASS | 0 |
| python -m unittest tests.test_architecture -v | 2/2 PASS | 0 |
| python -m unittest discover -s tests -q | **304/304 PASS**，17.356秒 | 0 |

最终均0失败/0错误/0跳过，定向集合不重复计入全量。新增测试最初因配置模块尚缺、提交后日期异常等失败；首次全量也发现旧恢复测试无配置构造Agent的兼容问题，修复实现后重跑通过，未放宽原断言。原始结果本地artifacts/s4_pd/{baseline,before,targeted_final,stages_final,security_final,architecture_final,regression_final}.txt。

| 边界 | 对应新增测试/证据 | 结论 |
|---|---|---|
| 独立Global管理、User隔离、不fallback、优先级及旧变量 | ProfileTests的12项 | PASS |
| 配置异常、原子失败、锁冲突、不安全URL、明文Key拒绝 | ProfileTests | PASS |
| 同/异账户、标准协议、冻结Key/轮换 | SessionTests.test_same_account_model_switch_keeps_business_scope_not_protocol / test_cross_account_and_standard_switch_always_reset_private_history / test_credentials_are_frozen_and_rotation_requires_new_connection | PASS（确定性） |
| 身份变化、旧草稿/Approval、活动提交不能切换 | SessionTests的对应identity/pending/switch/approval用例 | PASS |
| Thinking历史字段、整轮裁剪、实际字符上限 | tests.test_stage4pc + live被动传输核验 | PASS |
| tool.progress与真实schedule.progress，旧预算不变 | TraceTests + tests.test_stage3c | PASS |
| usage有/无、API失败UNKNOWN、日志不可写 | test_native_usage_known_unknown_and_failure_are_not_estimated / test_trace_failure_does_not_change_actual_sdk_result | PASS（Mock注入） |
| preference_key、Token计数、嵌套JSON/Header/URL/混合异常脱敏 | TraceTests的两项redaction测试 | PASS |
| 日期None/非法、RuntimeError/SQLite异常/无效进度不覆盖COMMITTED/NO_CHANGE | ReliabilityTests的3项，真实临时事务/审计 | PASS |
| 审计回滚、权限/联合键、取消/冲突及规则冲突 | 原Stage0–3及安全回归 | PASS；没有把事务异常并入进度catch |

附加进度catch只包已验证提交之后的辅助函数，规则服务返回的错误结构继续保留，不自动完成任务、不重新Commit。专门“提交后注入RULE_CONFLICT返回”的组合未单独新增测试，原规则冲突测试与该透传分支分别覆盖，不冒称真实坏库验证。

## 真实API：配置、案例和SQL核对

实际链路：CLI → 唯一Agent.ask → 绑定ModelTransport → OpenAI SDK → 官方DeepSeek Chat Completions → Registry → 隔离SQLite。旧live_model保留为兼容入口；没有scripted_model替代实际模型。验收驱动仅提供用户输入及精确**scripted confirmation，非真人确认**，被动记录HTTP/协议元数据，不改模型响应。

私有配置shared-flash(Global)、own-flash(User U001)、shared-pro(Global)；服务标记authorized-deepseek-demo，官方https://api.deepseek.com，auto协议。前两者分别引用不同环境变量名，但**实际为同一把已有授权Key**，明确不声称拥有两个真实服务账户。第二个独立真实账户不存在，没有购买/搜索或自动fallback。

| Case | 真实输入/行为 | M / requested / actual | 停止与结果 |
|---|---|---:|---|
| L1汇总 | C001 2026-09发票/银行完整汇总及R001 | 2/1/1 | ANSWERED，PASS |
| L1续问 | 同一企业同月当前发票张数 | 2/1/1 | ANSWERED，PASS；Thinking完整重放 |
| L2 own-flash | U001自己的User Profile实际汇总 | 2/1/1 | ANSWERED，PASS；配置引用成功，不等同跨真实账户隔离 |
| L5任务 | 明确原样note“下次继续补齐用途”，核对后确认 | 2/1/1 | ANSWERED，任务确实创建ACTIVE |
| L5发票 | /edit C001/F002用途→项目资料核对，精确确认 | 1/1/1 | Loop WAITING_CONFIRMATION；随后可信CLI COMMITTED+readback_verified |
| L3切换/L5原续问 | /provider use shared-pro；“查看当前企业当前月份的未完成用途待办及现在还缺哪些发票用途。” | 2/3/3 | **PARTIAL / MODEL_BEHAVIOR_FAIL**：正确查任务/缺项后又提prepare，被DENIED；不是API/切换失败，不抹去已查事实 |
| L3/L5只读对照前 | 新CLI shared-flash只读查C001 2026-09，锚定后切Pro | 2/2/2 | ANSWERED，PASS |
| L3/L5只读对照后 | 明确只读“当前企业当前月份…不准备、不修改…不变更任务” | 2/2/2 | ANSWERED，PASS，任务同ID，仍ACTIVE、缺失4项 |
| L4真实不同账户 | 无第二套合法凭据 | — | NOT_TESTED；不同dummy Key/历史隔离已有确定性测试 |

两次`/provider use`为可信命令，不产生API，不计模型用户轮次。第二次是针对误提修改的一次明确只读诊断对照，不能替代原输入PARTIAL。没有自动修复模型或额外审核模型。

独立只读SQLite核验：
- 汇总C001 2026-09：10张/9622.06元，银行收入4条/13000.50元，支出8条/7180.74元；R001 v1.0与工具呈现一致。
- Prepare后的确认前字段/审计未变。最终仅C001/F002 purpose从NULL变为“项目资料核对”，其他字段、C002同号、全部银行和规则记录不变。
- 成功审计恰好1条：request_id `b34ee97d395a480392d20dc7788282f6`，actor U001，联合键C001/F002，字段purpose；从实际草稿独立重算SHA256与审计fingerprint一致，新只读连接值与回执一致。
- 任务ID `b324af202e364b9a965444ab88d02aa5`，范围C001/2026-09，note精确一致；切换及后续新进程对照后仍ACTIVE，未自动完成。缺项5→4：F004、F003、F006、F009，R002 v2.0；工具集合与SQL一致。
- 两次Pro会话首个真实请求的旧模型assistant历史数均0；真实任务上下文及企业/月来自可重查范围，未带旧reasoning、发票确认或未完成Tool Call。

## 原生Trace、用量与隐私
- 本阶段**15次API尝试，15次HTTP200，0次API失败**；SDK返回模型deepseek-flash 11次、deepseek-v4-pro 4次。原生api.request/api.response各15，与被动HTTP计量逐条usage一致。
- SDK实际usage合计：prompt_tokens **58200**，completion_tokens **3018**，total_tokens **61218**。均KNOWN；失败/缺usage的UNKNOWN由Mock验证，不凭空制造live失败。
- 原生客户端往返latency_ms：最小1173.900，最大7906.206，逐请求合计39487.855；包括SDK调用开销，非服务端独立推理时间、非用户端全流程总耗时。
- 4P累计可核对API尝试：A 0 + B 13 + C 24 + D 15 = **52**；不混入S4-B旧64次。实际费用、账户余额及是否到¥35提醒线未经后台对账，UNKNOWN，不用Token估算账单。
- 8个模型交互轮次；model_input/model_reply/context.selected/protocol.selected/budget各15；tool.requested/tool_result **12/12按(trace_id, tool_call_id)完整配对**，含被拒prepare；execution.stopped/turn.finished各8，update.result 1。
- 每轮最大M/requested/actual=2/3/3；extensions=0、replans=0、block_limit=3。真实Schedule、续期、重规划均NOT_OBSERVED；本次无schedule.progress，有tool.progress 10条，未假造计划事件。
- 原生Trace根字段含可信actor、profile、scope、provider、model、逻辑account_ref、mode；API事件记录protocol_mode/usage/latency、安全错误类别，轮末api_counts与模型请求数一致。成功SDK不提供精确HTTP状态时存SDK_SUCCESS/http_status=null，由被动HTTP200单独佐证，不猜200。
- 被动检查全部实际模型历史（含最终无Tool Call回复）reasoning_content与先前服务响应精确一致，仅内存比对，不落原文或凭据指纹。四组隐私检查通过；Key和非空私有思考正文均未出现在本地普通Trace/CLI/SQL证据。
- 本地忽略证据：`artifacts/s4_pd/live_20261106T072226Z/`，含CLI确认、快照、api_usage.jsonl、各组Trace、audit_summary.json及privacy检查；驱动在artifacts/s4_pd/live_pd.py，独立只读核验audit_pd.py。上述不上传Git；正式data/finance.db未读写。

## 门禁与未验证项
- P08/P09/P10的本阶段最小门禁满足：304/304回归、可信配置/冻结连接/安全切换、真实两种模型Tool Calling、任务连续性和SQLite审计证据可核对。建议独立审查后进入4P-E，**本轮不执行**。
- 原续问Pro误提prepare是模型行为偏差，已DENIED且没有额外写入；原输入PARTIAL保留，不能将只读对照说成原句全通过。
- 真实第二账户、其他Provider/标准协议的live、真实Key轮换、坏库/网络故障及完整官方三场景+偏好CRUD本轮NOT_TESTED；对应适用的Mock/离线覆盖不能代替live。
- 无生产登录、远程多租户凭据隔离、服务商真实账户归属证明、DNS级SSRF防护或任意自然语言语义保证。不支持Profile更新/删除命令；用户自选本地文件路径需放忽略目录。
- [P11 Issue #1](https://github.com/knone32/Economy-guy/issues/1)已通过GitHub重新读取，仍**OPEN**，未修改或关闭；完整交付仍受其独立修复/验收门禁约束。
- 提交前检查了109个可达历史文本blob的常见Key/Token/私钥签名及新报告，0命中；已跟踪文件无运行库/本地Profile/凭据/原始artifacts。此为签名检查，不宣称能识别任意语义上的秘密。历史报告及此前测试文件与Base一致，只有新增test_stage4pd.py。
