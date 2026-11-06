# S4-P-C：DeepSeek Thinking协议、会话隔离与真实验收

## 版本与阶段结论
- Base SHA：`e6a88583336e76bda131bed82642e1e33fdd3970`，开始时main工作树干净、远端一致。
- 最终Tested Code SHA：`d27ca91709e076eb9be6ebff8cb8427b52812aa2`。首轮协议源码为`47e0b63144100b89c9f96dd6aff62487d52cb321`；后续只补普通Mock与live环境隔离，并在最终SHA重新执行全量及真实链路。
- Report SHA：本报告独立提交；用 `git log -1 --format=%H -- docs/verification/stage4/S4-P-C.md` 查得，最终回执给出实际值。文档提交不改被测源码。
- **P07 Protocol PASS；私有字段隔离/Trace遮蔽 PASS；最终SHA的C-L1/C-L2/C-L3 PASS；C-L4 NOT_TESTED。** 首轮C-L3另有MODEL_BEHAVIOR_FAIL，未因HTTP200或后续对照成功抹掉，见下文。
- 仅登记P11和修4P-C；不修P11、不实现Profile、不进入4P-D/E，不修改业务SQL/规则/发票事务、4P-B结果呈现或Scheduler预算。

## P11远端Issue（只登记）
- 先检索仓库open/closed Issues中的P11、NOT_FOUND、preference，无同题结果；正常通过已授权GitHub连接创建并重新fetch核实。
- **[#1](https://github.com/knone32/Economy-guy/issues/1)，OPEN**：`[P11][P0][UX] Composite preference intent stops at NOT_FOUND instead of continuing to create`。
- 包含S4-P-B代码`ccd184ff`、Trace `e8d2e799d3d84ece9424a722c9b4d3d8`、原始复合请求、NOT_FOUND停止零写入、明确新增对照、风险及不可全局成功/自动创建/绕确认的安全要求。建议4P-E前独立修复与live复验；本轮没有关闭Issue或改该业务行为。Issue创建即远端生效，不依赖git push。

## 官方协议、根因与最小实现
- 2026-11-06重新核查[DeepSeek官方思考模式文档](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/)：默认Thinking开启；带tools的后续请求需回传历史assistant实际reasoning_content，包括未调用工具的最终回复；无tools时不要求回传。本轮没有关闭Thinking、修改effort或用其他服务规避。
- P07原根因是Agent把SDK回复归一为role/content/tool_calls，丢失必要字段。新增`app/thinking_protocol.py`，不增加Loop或业务状态：实际模型消息为PrivateAssistant（dict中只有业务字段，私有reasoning为仅进程属性）。normalize严格检查字段；实际缺失/None/错误类型不补造，真实空字符串原样保留。
- `ThinkingProtocol.wire`只为实际发送的已选消息还原协议字段；`Agent.model_messages/live_model`复用该路径。实际原tool_calls与tool_call_id顺序不变，不把reasoning用于工具参数、金额、权限或提交凭据。
- 仅官方HTTPS `api.deepseek.com`根路径或`/v1`、已核实模型deepseek-flash/deepseek-v4-pro使用该协议。自定义DeepSeek代理缺明确协议配置则安全停止；普通兼容API不带字段。服务配置在Thinking会话中变化时PROTOCOL_ERROR，要求新Agent，不跨Provider传递旧私有历史；没有切换CLI/自动fallback。
- 本地context_data/harness_history/harness_schedule/reference_data/harness_output保留程序来源name，未发生模型推理，仅在传输副本有明确空协议槽；这不是把实际模型缺字段伪造为推理，也不改变来源为用户或系统指令。实际模型缺字段仍拒绝。
- ContextBuilder.build新增可选measure，按完整待发送消息计字符，包含完整reasoning，仍非Token计数且不含tools Schema；当前必需段超限CONTEXT_LIMIT，旧用户轮次整体取舍，不截断字段或拆散工具对。仅被选中消息携带其字段；不新增长期记忆，原进程历史生命周期不冒称永久内存上限。
- 身份切换清除旧消息/许可；新Agent和新进程不恢复私有字段或Draft/Confirm。普通Mock默认不启用厂商协议，即使本地已配置live变量也能使用原模拟响应；协议单测显式启用模拟适配器，未暗改真实Thinking默认值。

## 日志与隐私边界
- `model_input/model_reply`在Agent出口明确遮蔽；Trace.redact同时递归遮蔽嵌套reasoning_content/reasoning/thinking，标为`[PRIVATE_PROTOCOL_HIDDEN]`。脱敏副本从不作为下一次API输入。
- `protocol.selected`只记录是否启用、字段数量和字符数；异常为安全类别/固定说明，不写底层异常中的私有正文。dict/JSON/repr不包含PrivateAssistant私有属性；业务解析继续只处理公开字段。
- 真实HTTP被动观察器仅临时比较必要字段与服务响应的摘要是否相等；持久证据只有精确匹配布尔值、字段长度、请求状态、usage/耗时，**未保存原始推理或其摘要值**。源码、报告、普通Trace、CLI输出、SQLite中均未发现实际推理正文。
- 两轮live共19份长度>32字符的非空推理样本在进程结束前检查原文及JSON转义形态，均未进入产物/SQLite；短值由字段级隔离和遮蔽保证不经该字段出口。离线独立哨兵另覆盖异常/嵌套Trace及数据库。该保证是协议字段隔离，不声称能识别模型在自由content/tool参数里主动复述的任意敏感语义；本次没有观察到此类复述。

## 修改文件与确定性证据
修改：`app/agent.py`（归一/传输/安全停止）、`app/context.py`（完整传输计字符）、`app/trace.py`（私有字段遮蔽）；新增`app/thinking_protocol.py`和`tests/test_stage4pc.py`；增量更新`docs/flows/context-reference.md`。业务服务、Scheduler和旧测试断言未改。总纲仅更新P07/源码引用/P11链接。

在finance_agent/执行，python为本地隔离Python3.12.14、openai1.109.1，无新依赖；以下数量不相加为独立用例数：

| 命令/阶段 | 实际结果 | 退出码 |
|---|---|---|
| 修改前 `python -m unittest discover -s tests -q` | 256通过，0失败/错误/跳过 | 0 |
| 首先 `python -m unittest tests.test_stage4pc -v` | 初稿12项，8失败/1错误：字段丢失、私有字段未遮蔽等；原始before.txt保留 | 1 |
| Mock环境兼容独立反例 | 1项失败：live环境令普通Mock响应被要求提供reasoning；最小隔离后通过 | 1（修复前） |
| 最终 `python -m unittest tests.test_stage4pc -v` | **18通过，0失败/错误/跳过** | 0 |
| `python -m unittest tests.test_stage4pa tests.test_stage4pb tests.test_management_confirmation tests.test_security_boundaries -q` | **87通过，0失败/错误/跳过** | 0 |
| `python -m unittest tests.test_architecture -v` | **2通过，0失败/错误/跳过** | 0 |
| `python -m unittest discover -s tests -q` | **274通过，0失败/错误/跳过**，31.786秒 | 0 |

新增18项验证：工具与无工具最终回复跨轮精确回传、多调用/拒绝/预算配对、含私有字段的当前超限及旧轮裁剪、真实空值和非法字段区别、OFF/无tools/普通SDK负载、嵌套日志不泄漏、身份/新进程隔离、范围更正、代理保守拒绝、服务变更不出站、Commit后API故障不重写及普通Mock不受live变量影响。原256项源码/断言保持原样。OFF仅显式适配器单测，未声称真实OFF接口实测。

## 最终SHA真实验收
真实路径：main.main(chat live) → 原Agent/live_model → 官方DeepSeek → Registry → 隔离SQLite。辅助程序只提供stdin/精确scripted confirmation和被动测量，实例model仍为原live_model；不是scripted_model。真实配置deepseek-flash / https://api.deepseek.com，thinking与reasoning_effort均未额外设置，使用官方默认。

| Case / Trace ID | M/R/T | 实际结果 | 状态 |
|---|---|---|---|
| C-L1 `f9f18f90a9db47f1bcd8b59a14b5c947` | 2/1/1 | get_finance_summary SUCCESS，ANSWERED；工具后的请求精确回传实际字段，金额/计数/R001与SQL一致 | PASS |
| C-L2 `9962b1feda564e39849c3002e5692fdb` | 2/1/1 | 同一Agent续问当前发票数，get_finance_summary SUCCESS，ANSWERED；前轮无tool_calls最终assistant也精确回传 | PASS |
| C-L3创建 `15ee36ac128b4c79ad289e91b9859411` | 2/1/1 | manage_task SUCCESS，实际内容确认后保存ACTIVE，ANSWERED | PASS（明确说明对照） |
| C-L3提交 `be64dd7a02ad4367a3f90cd8da1b62a6` | 1/1/1 | prepare_invoice_update WAITING_CONFIRMATION，可信脚本确认后真实COMMITTED/Readback | PASS |
| C-L3续问 `f507074417694285afddd603a0cdf2bf` | 2/2/2 | 同一Agent/进程check_missing_purpose + list_tasks SUCCESS，ANSWERED；当前4项及原任务均匹配SQLite | PASS |
| C-L4标准提供商对照 | — | 没有另一个已配置、获授权Provider的测试入口；未寻找密钥/购买服务/自动fallback | NOT_TESTED；普通协议离线已测 |

真实原文：C-L1“查询C001 2026年9月发票与银行收支汇总。”→C-L2“同一企业同一个月的发票有几张？请查询当前数据。”；C-L3明确待办说明“下次继续补齐用途”→`/edit 将C001的F002发票用途改为项目资料核对。`→原被阻断的“C001 2026年9月的待办现在还剩哪些缺失用途？下一步应处理什么？”。均未强制指定查询工具。

### 首轮失败与复验区别（不粉饰）
- 首轮代码47e0b63共15次HTTP200。C-L1/C-L2及提交后续问协议正常；原C-L3创建Trace `4237d8c4daf147f79268886e6e051e15`，模型把明确说明扩写成含发票明细的长note，严格scripted confirmation拒绝，CANCELLED，任务0条。属于**MODEL_BEHAVIOR_FAIL**，不是PROVIDER_PROTOCOL_FAIL或BUSINESS事务失败。
- 首轮随后发票提交及同会话查询恢复，但无任务，不能算完整C-L3 PASS。只进行一次明确“不扩写说明”的诊断对照，在另一个全新库实际完成任务→Commit→续问。之后发现并修复独立Mock环境兼容问题，故在最终d27ca91再次复核C-L1/C-L2和该明确说明对照；不是对原失败无限重试，也不把对照替换原失败。
- 真实原句的宽泛管理语义仍需4P-E验证；P11继续OPEN，不因协议恢复而宣称所有复合业务意图已修复。

## 当前SQLite、Audit、确认与会话事实
- 最终同一PID **64400** 完成创建、Commit和续问。task_id=`c2907d2755134007beff3b8622362085`，U001/C001/2026-09，note精确“下次继续补齐用途”，状态保持ACTIVE。创建确认前任务0条；没有手动更改任务表或自动COMPLETED。
- 最终实验库只有1条COMMITTED审计：request_id=`a02acb4997f541e0ba636a28248207b3`，actor U001，C001/F002，purpose，None→项目资料核对；fingerprint=`8002362ce860eabcd8a2b4ab54b5c871ed5d244e9a18f7d1652dd42f577765cd`。独立重算与草稿/审计一致，新只读连接回读一致；确认前发票/审计未变。
- 逐字段比较仅目标purpose变化，C002同号及其他字段不变；当前缺失5→4。续问工具返回的4个联合键与独立当前SQL集合一致，使用R002 v2.0，任务ID与持久记录一致。没有因API或模型错误重写已有Commit。
- 本次全部确认是**scripted confirmation，非真人确认**，由真实CLI展示提案后按精确目标/内容输入完整confirm ID。原note错配的取消证明脚本没有替模型自动放行。
- 最终26项独立协议/隐私/SQLite/Trace检查通过；首轮28项通过但含明确标识的模型取消路径，不能将检查全绿解释成原创建语义成功。

## 真实请求、用量、计数和本地证据
- **最终SHA：9次请求，9 HTTP200，0失败**；实际prompt_tokens=42610、completion_tokens=2058、total_tokens=44668。首轮SHA：15次请求，15 HTTP200，实际76184/3682/79866。**本阶段合计24次，24 HTTP200，118794 prompt + 5740 completion = 124534 total_tokens**；均有usage，无未知用量请求。费用/余额/累计¥35提醒线是否达到未经后台核账，记未知，不以Token估算实际扣费。
- 最终每Case总tokens及逐请求客户端耗时秒：C-L1 6941 `[1.337,1.679]`；C-L2 8273 `[2.832,0.937]`；创建8397 `[2.101,2.041]`；提交5232 `[2.065]`；续问15825 `[1.397,3.993]`。首轮15项实际耗时/usage在独立元数据中保留，不称服务端推理延迟。
- 最终5轮，model_input/model_reply/context.selected/protocol.selected/budget各9；tool.requested/tool_result **6/6逐ID配对**，execution.stopped/turn.finished各5，update.result 1。首轮8轮、15请求、12/12工具配对；合计18/18不等于18次业务成功。首轮两个独立库各1次提交+最终独立库1次提交，不能误称同库重复提交。
- 两轮单轮最大M/R/T=2/2/2、extensions=0、replans=0、block_limit=3；没有实际续期/重规划，NOT_OBSERVED，不生成假事件。Scheduler原schedule.progress语义仍留4P-D，本轮不改预算/停止算法。
- 被动传输核验所有历史实际模型assistant（含最终无工具回复）的字段均与服务先前返回精确相等；真实空字符串也按原样比较。当前被选消息计字符包含私有字段且未超48000；Trace保留业务上下文和工具依据，但明确隐藏私有字段正文。
- 本地忽略目录：初轮`artifacts/s4_pc/live_20261106T060159/`、最终`artifacts/s4_pc/live_20261106T060857/`，含虚构快照、确认/CLI证据、脱敏Trace、仅协议元数据、audit_summary.json；测试输出在artifacts/s4_pc/。**不提交这些日志/数据库/配置、原始推理、API密钥或虚拟环境**；没有读取/修改正式finance.db。

## 门禁与剩余事项
P07、真实跨轮/提交后续问、字段级隐私、原安全回归已达到4P-C门槛；建议独立验收后进入**S4-P-D（仅建议，不执行）**。首轮note扩写仍为模型行为失败，P11 OPEN，真实OFF/其他Provider NOT_TESTED；最终官方完整三场景和偏好CRUD仍留4P-E，不因本轮HTTP200宣布全项目验收完成。历史S4-A/S4-B/S4-P-A/S4-P-B未改。
