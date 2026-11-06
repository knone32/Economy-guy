# S4-P0-Closure：可信来源与官方业务缺口收口

## 版本、范围及门禁

- 日期：2026-11-06；分支 main；Base SHA `2b2191d22c85ac475f1b78d23c810eb50482b648`。
- 初始业务补丁 `140bb14c938478fe566500c11644d2ef38d96141`；最终 **Tested Code SHA `f6d99267358e5202752afbbdd062600781cdab29`**。
- Report SHA：包含本报告的 `docs(s4p0c): record P0 closure and live verification evidence` 提交；用 `git log -1 --format=%H -- docs/verification/stage4/S4-P0C.md` 获取。报告提交自身的 SHA 不嵌入自身，最终交付回执另列实际值。
- Windows，Python 3.12.14，openai 1.109.1、openpyxl 3.1.5；使用已有本地隔离环境，没有增加依赖。只做本阶段，不执行 S4-SEC-A 或后续交付。
- **总体 PARTIAL；业务门禁 BLOCKED**：P12、P11、B6 已取得当前代码确定性/Live/SQL证据；C2 的具体内容确认由真实操作者明确暂缓，后续 C1→C6 不能宣称完成。不是通过绿色单测宣布官方业务整体 PASS。
- 所有题目为 **PUBLIC_REGRESSION**；`EXTERNAL_HOLDOUT_PENDING`，未开展或模拟真正盲测，不计为功能失败。

## 冻结及证据隔离

旧 S4-P-E 59 题、初始条件、评分和历史 FAIL 原样保留；旧冻结提交 `a2dbdd6be3e38eae7292137710afd29b34248619`。新问题及诊断 ID 只追加到 [S4-P0C-CASES.md](S4-P0C-CASES.md)，先冻结再运行。新题首次冻结提交 `b6f2a5298f100ccd3554600a82f537856d64ea1a`，当时文件 SHA256 `8506a72b189cd8287c0d0d578221a4a9196921b5b099e01f47035eb5dff20831`；最终追加诊断后文件哈希另列结果索引。R1 为新库同原题复验，不覆盖首次结果。

官方虚构夹具为 `finance_agent/tests/fixtures/example.xlsx`，SHA256 `edb13b2a52d2f875033258836e8fc23c3e1353c46d101184048bac289e52ed0f`。没有读取、修改或重建正式 `data/finance.db`。每组使用独立 SQLite、原有显式加法迁移和规则导入。

本地忽略证据根目录为 `artifacts/s4_p0c/`：测试完整 stdout/退出码、两批 Live 原始 Trace、HTTP 被动计量、CLI 原文、前后表快照、只读 sqlite3/Decimal 核算、具体确认和用户暂缓决定。**这些原始日志、DB、密钥及私有 reasoning 不提交 Git**。本报告及结果附表只发布审查过的虚构业务信息/计数/Trace ID。

真实入口是实际 CLI `main.main → Agent.ask → live_model/ModelTransport → DeepSeek → Tool Registry → SQLite`。测试驱动只供应原始输入、捕获结果和精确 scripted confirmation；没有替换模型、关键词选工具或直接业务调用冒充模型操作。Scripted confirmation 是测试操作者事先绑定内容的模拟确认，**不是真人逐次点击**。C2 非预设文本另实际等待真人决定。

## 修改文件及状态所有者

| 文件/函数 | 实际修改 |
|---|---|
| `app/provenance.py`：`ScopeProof`, `validate_scope` | 新增轻量可信来源证明；模型 source 标签无效，缺来源与范围冲突区分。不是持久意图数据库。 |
| `app/context.py`：`ContextBuilder.proof`, `accept_reference`, `accept_task`, `begin` | 保留当前用户/仍有效会话槽位来源；更正失效旧引用；实际选定任务/引用才可补范围；任务列表不能洗白日期。 |
| `app/tool_registry.py`：`handle_tool` | 权限优先；Schema、expected_scope、来源校验再业务读；Prepare 和 Schedule 同守卫。管理入口原有动作/身份限制不放宽。 |
| `app/agent.py`：现有 `Agent._ask`/finish/分发 | 唯一 Loop 显式传入证明；缺字段生成追问；将最终只读目标核对委托协调器。 |
| `app/responses.py`：`explicit_scope`, `preference_receipt`, `render_stopped` | 支持有限明确中文/数字年月；偏好保存与再次读取分开举证；早期已解决 NOT_FOUND 不再冒充未保存，真实 stop_reason 保留。 |
| `app/updates.py`：`current_target_matches` | 新连接、只读、再查修改权限/联合键/允许字段及当前值；不执行 Prepare、Commit 或审计。 |
| `app/write_coordination.py`：`assess_current_match` | 仅当前可信明确编辑目标可生成 CURRENT_VALUE_MATCHES；不是 COMMITTED/事务 NO_CHANGE，不覆盖真实拒绝/冲突/未知/错误。日志故障不抹去已核对事实。 |
| `app/model_transport.py`：现有请求路径 | 仅官方 DeepSeek 使用 JSON object 输出模式；60 秒超时、SDK 不自动重试；其他 Provider 不强加兼容模式，Thinking 历史回传保留。 |
| `tests/test_stage4p0c.py` | 26 个独立反例；临时库、独立 SQL 真值，无复制刷数。 |

源码路径前缀均为 `finance_agent/`。Task/Preference/权限/审计仍由原业务服务和 SQLite 所有；没有新增 Loop、Planner、持久 Intent Frame、权限系统或状态镜像。`proof=None` 仅保留可信直接 Python 调用兼容性；正式 Agent 的每次 dispatch 均显式传入证明，不能将该内部入口开放给不可信客户端。

另有 8 个旧测试文件只补齐 `.ask()` 输入中原断言所需的明确范围/对象：`test_agent.py`、`test_management_confirmation.py`、`test_security_boundaries.py`、`test_stage252.py`、`test_stage3c.py`、`test_stage4pa.py`、`test_stage4pb.py`、`test_stage4pc.py`。例如预算测试明确所有候选发票编号，否则现在应先缺参停止。**没有删除旧 309 个用例，也没有放宽/删除断言**；相对于 Base，将 `.ask()` 首参数规范化后，八个文件的完整 AST 相同。旧测试不是一字未改，输入契约适配与安全断言保留分别说明。

## P12：来源核验

[Issue #2](https://github.com/knone32/Economy-guy/issues/2) 开工先搜索所有 open/closed 后创建，当前 **OPEN，已更新最终证据**。原 A1、旧 trace `a22be93a9102475b87197ebe2c840931`、旧源码 3a83 和失败事实保留。

Schema 只证明参数格式；ScopeProof 由 Harness 记录 `user_current/session_confirmed/trusted_reference/current_sqlite`，模型候选不授信。月度汇总/列表/缺用途要求公司+年+月；发票详情只需原联合键；明确选定且重新鉴权的当前任务可提供自身日期。ACL 优先，拒绝仍 DENIED；未取得必要槽位来源为 AMBIGUOUS+missing_fields；已知值矛盾为 SCOPE_MISMATCH。不会以成功猜测查询反向建立用户日期，也不以 list_tasks 自动选定某任务年月。

**D PASS**：12 项来源专测覆盖缺年月、只有月份、跨轮补充、企业/月更正、明确中文年月、相对时间保守处理、伪来源、旧 SQL/任务列表洗范围、具体发票无强制年月、Fast Path/Schedule 同守卫及权限优先。模型伪造字段仍被 Schema 拒绝。

**L/B PASS（本轮原题小样本）**：Flash/Pro 都在原 A1 先 WAITING_USER，零月度财税调用；用户补“2026 年 9 月。”后恰调用 C001/2026/9 汇总，正确显示 R001 v1.0。初始补丁和最终补丁各运行一次，没有换成“请先问月份”。模型本轮自然追问，**强制恶意猜测调用的拦截证据来自 D，不伪称在 Live 观察到攻击**。

独立 sqlite3 按实际业务日期过滤、整数分求和及 Decimal 转元：发票 **10 张 / 9622.06**；银行收入 **4 条 / 13000.50**；支出 **8 条 / 7180.74**。独立核算不用被测汇总函数；与实际工具 data、scope、R001 v1.0 一致。

## C2：旧冻结策略与实际操作者决定

| 用例/证据层 | 判定 | 真实事实 |
|---|---|---|
| C1-ORIGINAL-REPLAY / L+B | PASS | 真实 check_missing_purpose，C001/2026-09，R002 v2.0，缺失 **5** 张。 |
| C2-ORIGINAL-REPLAY / E | FAIL（旧四句精确白名单） | 原自然句提案未命中允许 note，scripted confirmation 取消，零任务；不改白名单、不回填历史 PASS。 |
| C2-SEMANTIC-01 / L | PARTIAL | 已真实生成具体候选并在 CLI 展示，待真人核对；不是 Task Manager 已保存。 |
| C2-SEMANTIC-01 / 确认与B | **BLOCKED_USER_DEFERRED** | 用户说“先不要做这个决定 将其留存至报告”。没有批准；CLI 输入 defer 安全结束，底层工具 CANCELLED 只表示未确认，不等于用户取消业务意图。task 表仍为 **0**。 |
| 原链 C3→C6 / L+B | NOT_TESTED / BLOCKED | 不绕过暂缓决定、不另手工创建同一任务来冒充完整链；本阶段没有 semantic 原链 5→4、同 task_id 跨进程恢复成功证据。 |

**留存的候选原文**：`把还没有补完用途的发票继续处理，下次接着补（不要猜用途）`。

- U001 / C001 / 2026-09 / missing_purpose / create，旧对象不存在。
- request_id `8d3d28e13426473a9a6e4a5b918a8e13`；指纹 `03644e25daf0a7a1ee948e8101d6e09c082fc7f03c8f3102facc9a5c6d257c72`；这是已结束轮的历史证据，**不是可重用确认许可**。
- 不使用另一个 LLM 作语义批准者。独立审查结论：旧四句测试白名单不代表任意忠实复述，原 FAIL 是确认策略限制，不能直接证明 Task Manager 故障；新策略必须由操作者批准具体内容。本次仍未批准，不宣称新语义验收 PASS。
- 未建 C2 产品故障 Issue；没有稳定证据把上述确认争议归因数据库缺陷。待独立具体确认及重跑完整链，不能擅自补决定。

**H2 独立初态对照 PASS，不是 C2 PASS**：为检验 Pro 原句“查看当前企业当前月份的未完成用途待办及现在还缺哪些发票用途。”，另建两个逐字节相同的纯测试初态（任务 ACTIVE、缺失4、审计0）。预置任务和修改字段仅为明确测试夹具，标记 `counts_as_live_business=false/not_a_c2_pass=true`，不计模型创建/Commit。先用实际输入建立 C001/2026-09，再问原句；Flash/Pro 都只 list_tasks+check_missing_purpose，**没有 Prepare**，无业务变更。U002/C001、U001/C002 新进程均无法见 U001/C001 的夹具任务（合法查询返回 NO_DATA，不是企业权限拒绝）。这只证明已有任务查询隔离，不替代语义任务创建、恢复授权或 5→4 完整链。

## P11：保存、核对、停止分开举证

[Issue #1](https://github.com/knone32/Economy-guy/issues/1) 保持 **OPEN** 并追加新源码、Flash/Pro 结果，供独立关闭审查；不因单次 Flash 成功自动关闭。

原句不变：“请记住C001的reply_format回复偏好为简洁，并核对保存的内容。”

- Flash：`get NOT_FOUND → create SUCCESS（具体 scripted confirmation）→ get SUCCESS`。
- Pro：`list NO_DATA → create SUCCESS（具体 scripted confirmation）→ get SUCCESS`，不把 list 说成 get NOT_FOUND。
- 两者原题在初始补丁与最终补丁均通过完整保存/再读目标；SQLite 核对精确 U001/C001/reply_format=简洁，原用户要求保留，未改变内容或自动批准。
- 三请求块后停止 **NO_LEGAL_WORK**；回执明确“确认后的偏好保存及后续读取核对完成”，同时保留真实停止原因。`NOT_SUBMITTED` 是独立的发票回执，不代表偏好没有保存。
- 仅当前轮真正保存且随后同对象/同值成功读取才称核对；第一目标已保存但第二目标未完成时明确未核对；重复 get 不抹去已有证据，也不冒充新 SQL。不是所有 NOT_FOUND 全局成功。
- D/L/B 当前用例 PASS；开放复合自然语义和重复调用模型质量不作绝对保证，未重跑旧59题全部或宣称永久修复所有复合意图。

## B6：目标一致不等于本轮 Commit

[Issue #3](https://github.com/knone32/Economy-guy/issues/3) 为独立稳定回执缺陷创建，OPEN，已追加最终证据。

第一补丁 Flash 经 get_invoice 可识别匹配；Pro 引用历史、未新查询，回执仍 NOT_SUBMITTED，**保留该首次 FAIL**。最终补丁在可信当前编辑入口、明确联合键/允许字段/字面新值下，由协调器重新鉴权并独立只读读取 SQLite。只读核对本身不依赖模型成功宣称。

最终两 Profile 都先原句 Prepare→精确 scripted confirmation→真实 COMMITTED；再同句要求“把甲企业 F002 的用途改为项目资料核对。”，得到 **CURRENT_VALUE_MATCHES**，准确说明无需再改、本轮没有 Commit。Flash ANSWERED；Pro 再 get 一次因去重 NO_PROGRESS，真实停止原因保留。此次 Pro requested=2、actual Handler=1；额外协调器 SQL 不能算模型 Tool Call，也不是新成功审计。

B 独立检查：每个 B6 库恰一条 COMMITTED audit；request_id/actor/联合键/字段/旧新值及 SHA256 内容指纹逐项匹配；第一次提交新连接回读已验证；只有 C001/F002/purpose 变化，C002 同号和其他字段不变；重复轮审计数不变。D 新测覆盖无模型工具的历史声明也必须重新读库、拒绝/差值不匹配、日志异常不抹除核对事实。

旧冻结题要求的 NO_CHANGE/旧 FAIL 不被回填；新 CURRENT_VALUE_MATCHES 是独立核对语义，`readback_verified=false` 不冒充事务成功回读。用户目标模糊时不猜，仍追问。

## Pro、协议及 Intent A/B

采用官方 [JSON Output](https://api-docs.deepseek.com/guides/json_mode/) 的 `response_format={"type":"json_object"}`（现有 system 已要求 JSON）；只约束语法，不能证明 Schema、任意文本语义、SQL事实或确认有效。Thinking 历史绑定保持，参考[官方 Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)。DeepSeek SDK 超时设60秒、max_retries=0；没有自动切账户、第二模型格式审核或重复 Commit。

本阶段 Pro 实际21请求 HTTP200；未观察非JSON终答/ReadTimeout/旧 HTTP400，但样本很小，不能宣称超时根治或广泛可靠率。历史非JSON=响应信封/模型格式问题；ReadTimeout=SDK/网络等待类别，与 reasoning_content HTTP400 不同。确定性用例仍检验坏 JSON/API异常/已提交后异常保留事实。

离线4组检查先证明模型候选帧不授予来源/权限。仅实验驱动从本轮已有工具提案派生小 Frame，数据区 model_candidate，无新模型、无持久化、同上下文上限。首轮 B 实验数据消息名称不符合既有 Thinking 私有字段守卫，发生两次本地 **PROTOCOL_ERROR**；这是实验脚本封装错误，**不是 Provider HTTP400 或模型非JSON**。保留失败和已发生用量；仅改实验数据消息为既有 context_data，不放松生产协议。另有未初始化诊断库/路径错误的启动失败，未产生 API，请求数不伪增。

修正后新 ID、同原题、同初态 Flash 配对（只有两个复合链，不能统计为模型排名）：

| 路径 | P12两轮+P11完整目标 | API请求 | Token | SDK客户端耗时合计 |
|---|---|---:|---:|---:|
| A：生产来源校验，无额外Frame | 2/2 PASS | 6 | 20673 | 7673.786 ms |
| B：本地不可信候选数据 | 2/2 PASS | 6 | 20914 | 8389.937 ms |

两组均无无来源执行/越权副作用；B 没有提高本样本完整完成率，增加241 Token和716.151ms。n=2、单次匹配不能作显著性或普遍结论。**不将 Intent Frame 正式上线，不实现强制双阶段抽取**；保留简单 A。

在这两对题的有效R1样本中，两组各4次模型工具请求（summary 1、偏好get/create/get 3），均满足目标工具及参数范围，未出现重复/额外工具；A1追问各1/1，无来源参数尝试各0。这个小分母不能替代公开59题工具准确率或全项目首次完成率；最初B脚本失败独立保留，不从总开销中删除。

## 测试与历史断言

工作目录 `finance_agent/`，python 指已有隔离环境解释器；命令及退出码如下，完整输出留本地。

| 实际命令 | 数量/结果 | 用时 | 退出码 |
|---|---|---:|---:|
| `python -m unittest discover -s tests -q`（Base） | 309 PASS / 0 FAIL / 0 ERROR / 0 SKIP | 32.020s | 0 |
| `python -m unittest tests.test_stage4p0c -v`（最终） | 26 PASS | 2.691s | 0 |
| `python -m unittest tests.test_stage4pe tests.test_stage4pd tests.test_stage4pc -q` | 53 PASS | 3.338s | 0 |
| `python -m unittest tests.test_security_boundaries tests.test_management_confirmation -q` | 50 PASS | 3.062s | 0 |
| `python -m unittest tests.test_architecture -v` | 2 PASS | 0.020s | 0 |
| `python -m unittest discover -s tests -q`（最终被测代码） | **335 PASS / 0 FAIL / 0 ERROR / 0 SKIP** | **33.798s** | **0** |

开发中真实失败日志保留：最初来源反例失败、旧输入缺可信范围造成的回归、尚未实现回执失败；根因分别修复或显式输入契约适配，不删除测试掩盖。早期错误继承收集重复用例在交付前纠正，最终新增独立26项，不把重复数当成果。335=309原用例+26新用例。

安全门禁：U001/U002、银行只读、purpose/remark白名单、Prepare/确认/Commit/同事务审计/回读、跨轮/身份/Provider确认失效、管理提案不能自授权、撤权/冲突/回滚/Trace故障、Thinking/Context/预算配对原回归均 PASS；架构检查证明业务层无反向运行层依赖，唯一生产 Loop 保持。没有开展新安全压力审计。

## Live用量、配对及可信证据

两批 Live 共36个用户轮次（含 setup、失败、重复及独立诊断；**不是36个全部成功场景**）。详细每轮 Profile、Trace ID、实际工具/状态、停止及计量见 [S4-P0C-RESULTS.md](S4-P0C-RESULTS.md)。

| 实际模型 | API attempts/success/failure | Prompt/Completion/Total Token | latency_ms合计 |
|---|---|---|---:|
| deepseek-flash | 41 / 41 / 0 | 149726 / 6064 / 155790 | 63580.415 |
| deepseek-v4-pro | 21 / 21 / 0 | 80484 / 4553 / 85037 | 72186.556 |
| 总计 | **62 / 62 / 0** | **230210 / 10617 / 240827** | **135766.971** |

API计数只算实际模型请求，官方余额 GET 另2次，不计模型。使用同一合法授权账户，Profile global shared-flash/shared-pro；不同子集不直接排名。原生 api.request/response 与被动HTTP观察62次一致；62个真实200不等于业务62次成功。Token 来自 SDK 实际usage，耗时是 SDK客户端请求延迟合计，不是整轮人工等待/CLI进程耗时。账单金额 **UNKNOWN**；已查询官方余额做提醒线核对，不发布余额/归因不可靠的余额差为本轮费用。

46个 Tool Call ID 全部逐ID结果配对，包括 Pro 一次去重 NO_PROGRESS；实际 Handler 合计45。单轮观察最高 model_requests=3、actual_tool_calls=3、requested_tool_calls=3、extensions=0、replans=0。硬限9/12/2/1未改；本轮未触发续期/计划事件记 NOT_OBSERVED，相关硬限路径由确定性旧测试覆盖，不伪造 budget.extended/schedule。

Native事件包含 turn.started/context.selected/model_input/model_reply/tool.requested/tool_result/budget/execution.stopped/turn.finished；发生真实提交时有 update.result；最终目标只读核对为 update.target_checked。上下文/Thinking回放被动比对不保存私有reasoning正文。偏好 NO_LEGAL_WORK 虽有原生通用 error 标签“模型请求上限”，应以 execution.stopped 的真实停止原因解释，不谎称权限/网络错误或目标未完成。

**观察到未授权副作用0**；这是受控案例、快照/审计和 D 回归的范围内结论，不是普遍无漏洞证明。语义C2未确认，tasks=0；H2预置任务不计模型写入成果。

提交前额外核对：八个旧测试规范化输入后的完整AST不变；12项历史报告/冻结材料/fixture的Git内容不变；扫描151个可达历史blob，常见API Key/GitHub Token/私钥标记命中0。此为范围有限的凭据模式扫描，不宣称自动发现所有敏感语义；待提交文件另逐项审阅，只有源码/测试和脱敏文档，没有DB/原始Trace/配置/私有推理。

## 剩余问题与下一阶段建议

1. **BLOCKED**：真实用户暂缓 C2 候选决定；完整语义任务链、同 task_id 跨进程恢复、该链真实Commit后5→4和再次恢复仍未验证。未来须新可信轮重新展示/确认，不复用本次旧nonce。不能宣布官方原业务链完成。
2. **PARTIAL**：P11 两 Profile 精确原句及保存/核对回执已通过；重复读取/三请求块停止提示仍有冗长 UX，不等于未保存。P11/P12/B6 Issue 均 OPEN 待独立审查，不自动关闭。
3. **NOT_TESTED**：泛化自然语言日期/否定/引号语义、跨期复合语义不是本次小型显式槽位解析的保证范围；不宣称彻底 Prompt 注入防护。相对日期无可靠解释就追问。
4. **PARTIAL**：Pro JSON/网络仅当前小样本通过，历史超时未在本轮重现，不能由60秒配置推断已治愈；B6 字面目标解析有意保守，模糊修改继续追问。
5. **EXTERNAL_HOLDOUT_PENDING**：没有外部未知题集，不称盲测通过。

**门禁建议：维持 BLOCKED，不建议凭本轮报告放行“官方P0全部闭环”。** 后续可由用户另行决定 C2 具体确认与原链验收，再独立决定 S4-SEC-A；本轮不执行后续阶段、不代批、不无限优化模型。
