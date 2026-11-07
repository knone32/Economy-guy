# Economy-guy｜财税 Agent Harness 项目总控总纲（真实运行优先版）

**版本**：v1.2（继承 v1.1 的官方要求、架构和安全契约；补齐 S4-P-E 真实验收后的 P0 阻碍、结构化意图候选方案及后续安全审计阶段）  
**编制日期**：2026-11-06  
**仓库**：[`knone32/Economy-guy`](https://github.com/knone32/Economy-guy)（Private）  
**最新被测仓库**：`111c9f97cd710084b1cfc18b9bf139e159e01389`（S4-C 验证基线）；**生产源码提交**：`bde7ec7bb7ca5f2a2460faade82e817b4302d6ef`（S4-BR）。

**适用范围**：云帐房 2026 AI 技术创新大赛赛题二「财税 Agent Harness」，**不含** Sky Core 研究及其他 AI 比赛。  
**文档性质**：项目目标和验收台账；它不是新开发指令，也不是未经运行证明的「已完成认证」。

> **项目一句话目标**：用一套 Python + SQLite + 单 LLM Agent Loop，在模拟财税数据上完成**自然语言查询 → 受控发票修改 → 多轮缺用途任务恢复**，把模型意图与可信执行分开；每一次查询、写入、记忆和停止都有能复核的证据。**优先完成初赛 P0，再考虑扩展。**
>
> **2026-11-06 最新决策**：Stage 4P 的工程缺口修复优先级不变，但**从「严格压缩 API 调用次数」转向「真实运行数据优先，调用效率可观测」**。Mock 仍为确定性回归和边界注入的必需工具，不删除、不伪装成模型理解；业务场景完成必须以**真实 LLM + 可信 CLI + SQLite/Trace**的复核证据为准。用户表示 DeepSeek 账户目前约有 **50 元余额**（用户陈述，未查询服务商账单），不再沿用旧计划的 18 次 API 全期硬限制。

### 2026-11-07 S4-C 最新状态快照

| 项目 | 结算 |
| --- | --- |
| 版本 | S4-C Base/Verified Code `111c9f97cd710084b1cfc18b9bf139e159e01389`，生产代码 `bde7ec7bb7ca5f2a2460faade82e817b4302d6ef`。BR Report `111c9f97cd710084b1cfc18b9bf139e159e01389`。S4-C Report SHA 取 [封板报告](verification/stage4/S4-C.md) 的提交 |
| 4P0C-CLOSURE | 测试 checkout `fc3f9d70a4ef66a46a8ffb666dd9d01db7b3a94a`，生产 `f6d99267358e5202752afbbdd062600781cdab29`。C1→C6 持久链在绑定本轮提案的模拟确认下通过，真人 C2 NOT_TESTED / USER_DEFERRED |
| SEC-A / SEC-B1～B3 | SEC-A 完成 25 项公开隔离发现。SEC-B 工程修复 PASS，B1/B2/B3 历史全量分别 345/355/363，原始失败和各自被测 SHA 见 [证据索引](verification/stage4/S4-C-EVIDENCE-INDEX.md) |
| SEC-B4 | `e834bbb961030c0671d788bc629026031078f743`，27 次 Flash，132,701 tokens。原 A/B/C Live 均 PARTIAL，C 持久链与偏好数据库业务有证据 |
| S4-BR | 工程 PASS，10 次 Flash，40,108 tokens，补齐 B2 已匹配回执和 C5 下一步。A1 主动追问，A2 财务事实正确，MODEL_LIMIT 自然收尾使 P0 Live 仍 PARTIAL。B/C 与偏好分别采用历史链加当前增量证据 |
| S4-C | 本地新跑 369/369、架构 2/2、八条原探针全部退出 0，模型 API 0。#1–#10 逐项核对原关闭条件、留言并关闭，局限见 [封板报告](verification/stage4/S4-C.md) |
| S4-D 准入 | EVIDENCE GATE PASS，PREPARATION READY。索引可直接用于启动复验、设计说明、脱敏运行记录和 ≤5 分钟演示，执行须另行授权 |
| 发布范围 | OFFICIAL_P0_LIVE PARTIAL，EXTERNAL_HOLDOUT PENDING，PRODUCTION_SECURITY_CERTIFICATION NOT_TESTED，SECURITY_RELEASE_GATE BLOCKED，历史实际费用 COST_UNKNOWN |

### 历史状态速览（按各自被测版本）

| 对象 | 当前事实 | 验收属性 |
|---|---|---|
| S4-A | `3c45103` 的 219/219 回归，Codex 本机报告通过；报告 `08b3ed5` | **本地实测报告**，不是 GitHub CI 复跑 |
| S4-B | DeepSeek Flash 对旧业务代码执行 41 轮、64 次 Chat Completions 尝试；A/B/C **整体 FAIL**，但 Prepare/Commit/审计、任务跨进程等子链路已证实 | **真实 API 运行记录**，对 `08b3ed5` 基线有效 |
| S4-P-A / 4P1 | 新增无权限自然语言管理候选、具体内容确认、偏好 CRUD 和追问修复；代码 `0c043151`、报告 `7a9f3271` | **238/238 本地回归报告**（219 旧 + 19 新）；**0 次 live API** |
| S4-P-B | P02/P04/P05及自然候选计划兼容；代码`ccd184ff`，本地256/256；13次真实API尝试 | **DETERMINISTIC PASS / LIVE PARTIAL / PROVIDER_BLOCKED**；L1自然汇总、L3提交/剩余4项/重启读取通过，原L2 NOT_FOUND失败，真实重复未观察到 |
| S4-P-C | Thinking多轮协议已验收，最终代码d27ca91，274/274及9次HTTP200（阶段合计24次） | P07跨轮/提交后续问PASS；原说明扩写MODEL_BEHAVIOR_FAIL保留，P11 OPEN |
| S4-P-D | 代码bd59b2e，304/304；Profile、冻结连接/切换、Trace及提交后进度隔离；15次HTTP200 | D历史门禁满足；原Pro续问PARTIAL、真实第二账户NOT_TESTED仍保留 |
| S4-P-E | 代码3a83a2c，309/309；59条冻结PUBLIC_REGRESSION含24变体；298次真实API尝试，294 HTTP200，4失败usage未知 | **整体BLOCKED**：Flash同题49/59→51/59；A1猜月份、原C2确认未完成、Pro非JSON/超时等保留；H2只读及P11部分修复；EXTERNAL_HOLDOUT_PENDING不是功能失败；未启动后续审计 |
| S4-P0-Closure（历史结算） | f6d9926；335/335，62次真实API；P12来源/A1→A2、P11保存核对、B6无重复写回执有证据；Intent B无收益不采用 | 上轮C2真人具体确认USER_DEFERRED、原链BLOCKED的历史结果不改，见S4-P0C报告 |
| S4-P0C-CLOSURE（2026-11-07） | 生产源码未变；5新测试、340/340；11次Flash API，三个真实进程完成C1→C6，真实task/Commit/audit/readback/缺5→4 | **PASS_WITH_SIMULATED_CONFIRMATION / P0 ENGINEERING GATE=PROVISIONAL_PASS**；仅本轮冻结策略，新C2模拟确认不批准上轮旧候选；真人C2未测/仍暂缓，外部Holdout待提供、安全审计未执行 |
| S4-SEC-A / SEC-B / S4-BR / S4-C | 各阶段实测及边界 | 见上方 S4-C 快照与证据索引 |

**事实划线**：4P-E 的 309/309 是 Codex 本地 unittest 报告，**不是独立 CI 复跑**；公开集 59 条已冻结，但 Codex 已知，**不是真正 Holdout**。4P-E 成功响应可观测 usage 合计 **1,167,596 Token**，另有 4 次无 HTTP 响应用量未知；实际余额和人民币费用均未核对。HTTP200、Tool Call 配对、SQLite 查询正确与“完整业务目标完成”必须分开评分。

---

## 0. 状态标签、证据优先级与阅读办法

### 0.1 统一标签

- **[官] 官方必需**：直接出自 1.1.0 赛题材料。
- **[约] 已冻结工程约定**：项目讨论确认的安全、所有权和开发边界，不代表全部已经实现。
- **[实] 当前源码已核实**：以所标注的**被测 Code SHA**为准；不能把报告提交 SHA 当作修改后的源码。
- **[测-本地报告]**：Codex 本机执行并提交了测试结果与命令，GitHub 上可核实测试文件/断言/数量；**没有 GitHub CI 或本次独立复跑则不写「外部实测」**。
- **[live-旧代码]**：真实 API、真实 CLI 和隔离 SQLite 的运行记录真实存在，但发生于 4P-A 之前的 SHA；可证明旧故障与部分成功，不自动证明补丁后的 live 通过。
- **[live-当前待测]**：新提交尚未以真实模型复验的行为；Mock 绿灯不替代 live 成功。
- **[缩] / [延]**：已同意的初赛简化 / P0 后延事项，不可误判为不达标。
- **[缺]**：设计或用户体验要求未满足且已有具体反例；**[阻断]**：协议/环境故障阻碍继续实验，不能据此推断业务数据库损坏。
- **[历史]**：v1.0、204/204 快照、S4-A 之前的静态审查，用于回顾而不是最新完成度。

任何报告必须写 `base_sha / tested_code_sha / report_sha`，并把 Mock / SQLite / live / GitHub CI 分列。

### 0.2 设计与事实发生冲突时

**官方 1.1.0 赛题及规则** → **双方已明确确认的最新工程决定** → **V2 架构/接口契约的已决定部分** → **代码与可复现测试显示的当前事实**。  
其中「是什么」由代码、实际执行与证据回答；「应当是什么」由官方和工程约定回答。任何较早文档中的“未来计划”，不因后来有同名模块就自动算实现。**候选方案不能冒充决定。**

### 0.3 此次审计依据（可追溯）

1. 官方 `01_参赛说明.docx`、`03_业务规则.docx`，版本 **1.1.0**，以及官方示例 Excel。
2. V0 `云帐房_财税AgentHarness_总路线图与Codex提示词_20261104.md`。
3. V1 `财税Harness_架构定稿与实施工作流_v1_20261105.md`。
4. V2 `finance_harness_ARCHITECTURE_CONTRACTS.md`，当前仓库版本路径 `docs/ARCHITECTURE_CONTRACTS.md`。
5. V3 `财税_Agent_Harness_工程总纲_2026-11-05.md`（编写时截至 Stage 2.5.3，因此其中“Stage 3 未实现”是**历史状态**，不可用于当前结论）。
6. 仓库 `AGENTS.md`、`docs/ARCHITECTURE.md`、`docs/flows/*.md`、`finance_agent/{main.py,app/*.py,tests/*.py,README.md}`，**当前业务源码核对至 4P-E `3a83a2c87afe`，最新历史报告提交为 `09d851d1e364`**；早期 `0c043151` / `7a9f3271` 只代表 4P-A 历史。
7. 历史 `stage3_acceptance.zip` 的 204/204 旧基线；S4-A 的 219/219 Codex 本地报告；S4-B DeepSeek 实际 41 轮/64 次调用及失败复现；S4-P-A 的 238/238 Codex 本地报告和 19 项新增测试。
8. 项目其他讨论：Context Controller 边界已定但内部算法未定；Task 与 Schedule 区分；3 请求一块；初赛不做动态估算；P0 优先。4P-D 的 Global/User Profile 和安全切换已有实现证据；生产认证及真实跨账户凭据验证仍不在已通过范围。
9. [4P-E 冻结公开题](verification/stage4/S4-P-E-CASES.md)、[逐题结果](verification/stage4/S4-P-E-RESULTS.md)、[4P-E 报告](verification/stage4/S4-P-E.md)（冻结题集提交 `a2dbdd6be3e3`、被测代码 `3a83a2c87afe`、报告 `09d851d1e364`）。本次增加对 P12、C2、P11 和结构化意图方案的审查区分：**观测事实 ≠ 根因假设 ≠ 待测设计**。

> **版本有效性**：任何新 commit 合入后都应更新本文“审查基线”和状态标签；不能默默沿用旧的通过数。旧版《Stage 4P 修复计划与分阶段 Codex 提示词》中 4P-B「0 次 API」及全期「18 次」等预算条款**已被 v1.1 真实运行优先决定取代**，其他工程安全约束继续有效。仓库中的既有 `S4-A.md`、`S4-B.md`、`S4-P-A.md` **保留原状**；主控总纲引用它们，不以修改历史报告的方式粉饰通过率。

---

## 1. 官方课题：不可被内部架构优化取代的验收项目

### 1.1 官方三场景（全部属于 P0）

| 编号 | 官方目标 | 必须能现场证明 | 当前判断 |
|---|---|---|---|
| O-01 | **查询资料** | 输入企业、年月；分别计算发票价税合计、银行收入、支出；说明适用规则与版本；无记录/越权分开 | [live-旧代码] A1/A3 及明确汇总对照成功；原 A2 连续补月份时仅出明细，**整体未过**；4P-B 待修/再测 |
| O-02 | **补充并保存** | 明确企业+发票+用途/备注新值；验证权限；真正保存并从新连接回读 | [live-旧代码] B1/B2 真实成功且审计回读匹配；B3 部分异常、同会话 Thinking HTTP 400，**场景整体未过** |
| O-03 | **多轮检查** | 列出 2026-09 缺用途发票；用户补充/更正；保存未完成任务；**退出进程再回来继续处理并更新结果** | [live-旧代码] 缺项 5→4、任务跨进程恢复真实成功；自然语言持久化 G01 已在 4P-A **离线修复待 live**；同会话后续被 Thinking 协议阻断 |

### 1.2 官方七项基础要求（不是全部都需要新模块）

| 编号 | 官方要求 | 关键验收边界 |
|---|---|---|
| O-04 | 模型理解与决策 | 模型决定回答/追问/调用工具/结束，不能只靠关键词固定回复伪装理解 |
| O-05 | 记忆管理 | 持久任务**进度**和用户明确偏好；查看、更正、删除；跨用户与企业隔离；每用户×企业最多一项未完成任务 |
| O-06 | 规则 KB | 规则导入、查找、更新、停用，说明版本；管理 CLI 即可，无后台要求 |
| O-07 | 模型输入 | 选择本轮必要对话、任务、偏好、规则、工具结果；限制输入长度；当前事实重新查库 |
| O-08 | 数据操作 | 程序金额与参数、权限检查；仅按明确要求改值；写后回读；失败不误报和不重复写入 |
| O-09 | **运行记录** | 能查看**实际模型输入、使用的记忆/规则、工具调用及结果**，知道答案/写入依据；不可记录模型密钥 |
| O-10 | 自然业务交流 | 说清已完成/未完成，回应补充、更正，只追问缺项，避免技术 JSON 淹没回答 |

### 1.3 官方模拟数据与权限（不可变业务约束）

- 两企业：`C001` 甲、`C002` 乙；两模拟用户：`U001`、`U002`。
- **40 张发票、48 条银行流水**；2026 年 8 月、9 月。每企业×每月 10 张发票、12 条流水（其中 8 条支出、4 条收入）。
- `U001` 可以查询、修改两企业许可字段；`U002` 只能查询 `C001`，不能改发票，也不能访问 `C002`。
- 发票按 **`(company_id, invoice_no)` 联合定位**；银行数据只读，不可推断与某张发票已付款/一一匹配。
- 发票金额为**价税合计**；发票总额、银行收入、银行支出分别统计；整数分/Decimal，输出元两位小数；缺数据为 `0.00`，**DENIED/ERROR 不是 0**。
- 仅允许发票 `purpose`、`remark` 字段变更。企业、发票编号、日期、金额、销售方、项目名称及银行记录都不能改。
- 8 月仅用于金额查询，初赛用途合规检查限定 **2026-09**。不能从销售方/项目/备注猜出用途；空白和纯空格视为未填用途。
- 不开展真实记账、付款、税务申报、发票 OCR 或真实企业业务审批。

### 1.4 规则版本（必须与当前 DB 规则解析一致）

| 规则 | 范围/版本 | 官方执行事实 |
|---|---|---|
| R001 v1.0 | C001/C002 | 发票价税合计、收入与支出独立统计；不以差额冒充支出 |
| R002 v1.0 | C001，**停用** | 历史千元门槛不可用于 2026-09 判定 |
| R002 v2.0 | C001，自 2026-09-01 | **所有** 9 月发票用途必填，不设金额门槛 |
| R003 v1.0 | C002 | 9 月**≥ 1000.00 元**的发票用途必填，恰好 1000 元算必填 |
| R004 v1.0 | C001/C002 | 银行全部只读；无发票逐条对应推断 |

规则正文负责解释，结构化 `params_json` 是执行参数；同一 `(rule_id,version)` 不可静默覆盖不同内容；根据企业、生效日期、启用状态选**唯一适用规则**，没有唯一依据应报无适用/冲突。

### 1.5 评分与交付

官方权重：**完成度 40% / AI 应用合理性 25% / 问题理解 15% / 后续完善 10% / 创新 10%**。提交源码、依赖和启动说明、建议 2–3 页设计说明、关键运行记录、**≤5 分钟演示**，应可按说明独立启动、验证当前库与实际写入。比赛截止日期与入口须以主办方通知为准；早期**11 月 13 日左右**仅是内部交付准备安排，不作为已核实的官方截止。

---

## 2. 设计版本沿革：哪些约定是稳定的，哪些被后续补充

| 阶段/文件 | 明确了什么 | 与后续版本的关系 |
|---|---|---|
| V0 · 11/04 总路线图 | 三场景 P0、单模型 Tool Calling、SQLite、权限/规则、跨会话记忆、真实模型验收、CLI 优先 | **基本目标未变**；自然语言业务推进是最初诉求 |
| V1 · 11/05 架构定稿 | 状态所有权、单 Agent、可信事务确认、Task/Task Schedule 分离、Context/Reference 分工、Trace、3+3+3、12 工具硬限 | **工程基线**；以最小闭环实现，不为漂亮架构重构 |
| V2 · 11/05 接口契约 | TaskPolicy+SQLite 部分唯一索引、展示锚点、计划约束/进度证据、规则唯一决策、多 tool_call 配对 | 部分是**目标设计**，实现应逐项核对；不是“契约里有名字 = 已实现” |
| V3 · 11/05 统一总纲 | 汇总设计冻结项和 Stage 2.5.3 状态，规划 3A/B/C | 其中「Stage 3 未实现」现已过期；不能覆盖新 commit |
| Stage 3A/B/C · 当前仓库 | 持久任务/偏好、上下文/引用、计划/预算、管理确认 | S4-A 报告 219/219；S4-P-A 报告 238/238；**完整真实三场景尚未过** |
| S4-A / S4-B · 11/06 | 同一 SHA 回归 + DeepSeek Flash 三场景真实取证 | S4-A 本地 PASS；S4-B A/B/C 整体 FAIL，细分子链路/具体失败已记录 |
| S4-P-A · 11/06 | 自然语言无权限管理候选、可信确认、偏好 CRUD 与安全追问 | 代码 `0c043151`；19 个新增测试，238/238 本地回归，**尚无补丁后 live** |
| S4-P-B～E · 后续 | 业务结果/任务推进 → Thinking 协议 → Profile/日志 → 全量独立复验 | 目标已冻结；实验费用政策从「请求数硬封顶」转为「真实证据+支出观察+故障止损」 |

### 2.1 已冻结的工程约定（变更需显式讨论）

**边界/技术**

- D01 单 Agent Loop、单个主模型；OpenAI-compatible Chat Completions Tool Calling；Python 3.11+、SQLite、CLI。禁止无必要的多代理、Reasonix 式自动路由、Redis/RAG/向量库和机械重构。
- D02 模型只负责理解、提出工具和必要追问；Python 负责业务计算、规则、权限、事务和最终证据。不能以 Prompt 代替校验。
- D03 **业务事实当前值只认 SQLite**；Excel 为只读初始化种子，不得因新 init 或迁移删库重导。
- D04 `Agent Runtime → Registry/Context/Scheduler → Business Services → SQLite`；业务模块不反向依赖 OpenAI 消息格式或 Agent Loop。
- D05 单一可变状态一个权威：任务≠计划≠上下文焦点≠草稿确认≠提交审计。Context Controller 不接管所有状态。

**安全/权限/修改**

- D06 身份由可信 Session（当前比赛模拟 CLI `--user`）提供；模型参数没有 `user_id`/`confirmed`；真实账号密码与 Auth/Session **P0 后**再做。模拟身份绝不称生产登录。
- D07 授权按用户×企业×操作 `read/modify`；`rule.manage` 独立授权；银行只读。
- D08 模型公开 Tool List 与内部 Registry 不相同，Python Handler **再次执行白名单/Schema/权限校验**；隐藏工具不可仅靠“不宣传”保护。
- D09 发票只改用途/备注；本次意图明确、目标唯一；**Prepare → CLI 可信确认 → 事务 Commit + audit → 新连接 Readback**；不能跳过。稳定 request_id 和指纹；错旧值 CONFLICT；未知结果先查审计不盲试。
- D10 新会话、身份切换、取消、任务恢复不能沿用旧草稿和最终写入授权；日志不能当业务提交事实。
- D11 长期任务/偏好模型提案须针对**具体内容、对象和旧值**经可信确认，不能只因“允许 create”就保存模型任意文字。此项是 Stage 3 验收后新增并已实现的安全加固。

**任务/上下文/执行预算**

- D12 任务真实持久化：`task_id`，按用户企业隔离，最多一个未完成；`ACTIVE/WAITING_USER/PAUSED` 占名额，`COMPLETED/CANCELLED` 不占；SQLite 部分唯一索引配合 TaskPolicy；取消不回滚已提交发票。
- D13 Task Manager =「要完成什么」；Task Scheduler =「这一轮怎么做」；Context =「这次模型知道什么」；Reference Resolver =「这句指的是哪个曾展示的对象」。不能复制任务权威状态。
- D14 切换查询话题不自动取消长期任务；新任务冲突要用户决定保留/替换；恢复重新验用户、规则和 DB，**没有旧写入确认**。
- D15 Context 按需选择近期消息、持久任务、明确偏好、可信历史锚点与必要证据；历史值不是当前金额；多候选引用问清楚，不准猜测发票。
- D16 不要求每轮强制先规划，**简单查询 Fast Path**；多步时由同一个模型可选短 Schedule，不加 Planner Agent；计划无业务授权。
- D17 **模型请求预算每块 3、最多续 2 次，总上限 9；实际进入 Handler 的工具调用每轮最多 12；显式重规划至多 1**。续期必须由可信工具证据、剩余合法依赖和权限支撑；不能靠模型自称取得进度。
- D18 初赛固定增量预算；不做动态 Token 费用预测器。可留简单策略接口；长期记忆不等于永久追加聊天全文。

**可观察性/工程工作流**

- D19 结构化 ToolResult `ok/status/data/evidence/error`，区分成功无数据、无权限、错误、待确认、冲突、未知结果；不会把失败变成成功。
- D20 JSONL Trace 用于每轮模型上下文、调用、工具结果、规则来源、上下文选择、预算/停止与结果；真实 SQLite 发票审计用于提交，不是一个日志替代另一个。
- D21 测试 Mock、真实 SQLite 单测、live API E2E 必须独立标注；Trace 故障不能改变 SQLite 已成功 Commit 的事实。
- D22 每次开发先读 AGENTS/相关源码 → 定范围 → 最小修改 → 定向测试 → 全量回归 → 检查 diff/实际副作用 → 最少文档 → Git commit/push → ChatGPT 独立审查；不删除旧测试以求绿。
- D23 P0 先做官方最小闭环；P1 稳定性/可观察性；弱模型优化、复杂摘要/长对话 A/B、真实登录、GUI、预算预测、通用 DAG 都不抢占 P0。
- **D24 [新冻结] 真实 API 为业务验收主要证据**：Mock 负责注入确定性异常、预算边界、恶意工具提案、事务和回归，不删除；财税问答、自然追问、工具选择、多轮回复、任务偏好管理的用户体验必须用 live 验收。**同一用例优先先 Mock/SQLite 红绿验证，再 live 真实抽样；关键 P0 场景最终必须 live。**
- **D25 [新冻结] API 调试预算采用可观测消费与人工账单核对**：不再强制 4P-B=0 次、整个 4P ≤18 次调用。账户约 50 元为用户报告的当时余额，并非程序已认证额度；保留约 15 元作为最终交付/意外处理缓冲，建议累计额外花费达到约 35 元即暂停核账或重新决定。按真实 usage 记录 Token、API 请求数、成功率与耗时；账单金额以提供商官方后台为准。重复相同故障两轮没有新信息则停止盲试。
- **D26 [新冻结] Provider 支持不能破坏业务独立性**：4P-C 先修现有 DeepSeek Thinking 必要协议回传，4P-D 做命名 Profile、密钥隔离与安全切换。禁止运行中自动模型路由、自动降级或跨模型继承旧会话思考/未确认授权；不得因为多模型配置抢占 4P-B 的业务优先级。
- **D27 [新冻结] 运行数据与证据必须分层**：生产安全 Trace / API usage 元数据 / SQLite 审计与回读 / Mock 单测 / Git 提交与报告分别保存与关联；记录 `trace_id/task_id/request_id/tool_call_id`，不要用 Trace 文本代替交易事实；真实 reasoning 不进可分享日志。

### 2.2 未冻结、不能擅自当强制架构的讨论内容

- Context Controller 的内部层数、最近保留「4–6 轮」的说法、评分/裁剪算法、是否长对话摘要、持久消息表的具体设计：**未定稿**。
- 时间指代（昨天第二张）、复杂历史列表检索和一般化解析：V2 提出了方向，P0 只要求**不猜测、能用可信锚点处理基础指代**；全面语义实现尚未决定。
- `initial_budget(schedule)` / `extension_budget(schedule,progress)` 是**建议的预留接口形状**，不是必须严格照此命名；当前实现可用等效固定策略。
- 面向真实公司的账号密码、密钥存储、管理员初始化、GUI：职责边界已定，具体协议**未定**，且明确延期。

---

## 3. 当前真实架构和状态所有权

```text
用户自然语言 / 可信模拟 CLI（/edit、/task、/preference、直接 tasks/preferences/rules）
   │
   ├─ 可信模拟身份 user_id；未来 Auth / Session（未实现）
   ▼
finance_agent/app/agent.py::Agent.ask  ← 单一模型调用循环
   ├─ context.py::ContextBuilder          【本轮模型输入/焦点；不存任务】
   │    ├─ references.py                  【真实展示锚点/引用复核】
   │    ├─ tasks.py                       【只读取当前任务事实】
   │    └─ preferences.py                 【只读取显式偏好】
   ├─ scheduler.py::TurnExecution         【本轮计划、请求与调用计数】
   ├─ tool_registry.py::handle_tool      【白名单、严格入参、范围及权限】
   ├─ persistence.py::ManagementProposals 【普通自然语言无权限提案；确认后才建一次性授权】
   ├─ write_coordination.py             【短期发票草稿与回执】
   └─ trace.py                            【JSONL观测，不决定事务】
          │
          ▼
   业务服务：queries.py、finance.py、rules.py、tasks.py、preferences.py、updates.py
          │
          ▼
 SQLite：发票、流水、权限、规则、任务、偏好、引用锚点、invoice_audit

可信 CLI 的最终发票确认 → WriteCoordinator → updates.commit_invoice_update
                              → 同事务 UPDATE + invoice_audit → 新连接回读
```

### 3.1 状态归属台账

| 状态/对象 | 权威管理者 | 持久化？ | 明确不负责什么 |
|---|---|---|---|
| 当前身份及模拟权限 | CLI Session + `permissions.py`/SQLite | 模拟身份在进程，企业权限在 SQLite | LLM 不可指定可信 user_id |
| 发票、银行、金额 | SQLite business tables + queries/finance | 是 | 历史 Prompt/Excel 不负责当前值 |
| 规则版本及结构化执行参数 | `rules.py` + SQLite rules | 是 | 模型生成规则文字不能变更规则 |
| 长期用途待办 | `tasks.py` + SQLite tasks | 是 | Scheduler 不管理其状态 |
| 明确偏好 | `preferences.py` + SQLite preferences | 是 | 不作为鉴权或操作指令 |
| 展示列表锚点 | `references.py` + SQLite reference_anchors | 是 | 旧列表不等于当前发票字段 |
| 当前语言焦点、裁剪选择 | `context.py` ContextBuilder | 进程内，必要锚点外存 | 不拥有长期任务和预算 |
| 当前轮次计划、预算、进度证据 | `scheduler.py` TurnExecution | 每条用户消息内存；Trace 留快照 | 计划不是业务授权或长期任务 |
| 发票准备草稿、可信确认 | `updates.py`/WriteCoordinator | 当前 Session | 重启不恢复写入许可 |
| 长期状态候选及内容确认 | `persistence.py` ManagementProposals/Candidate → 可信 ManagementTurn/Approval | 候选仅本轮预览；确认一次性，不入任务数据库 | 模型提案不具有写入权限；不代替真实登录 |
| 已成功提交的发票变更 | SQLite `invoice_audit` + 发票现值 | 是 | JSONL / LLM 不能伪造已提交 |
| 运行轨迹 | `trace.py` JSONL | 配置路径可写时持久 | 不具备与 SQLite 事务一致性 |

---

## 4. 模块实现矩阵（当前 `0c043151` 源码 + 历史 live 证据）

「已实现」只代表源代码与相应接口存在；「PASS」必须写出确定性/Mock/SQLite/live 及版本。以下状态不把 S4-B 旧版本失败错误归咎于 S4-P-A 新代码，也不把 4P-A 的 Mock 通过当作 live。

| 模块 / 文件 | 当前能力 | 验证边界与下一步 | 归属 |
|---|---|---|---|
| `main.py` | 模拟身份 CLI、管理/规则/数据命令、聊天、`/edit`；**普通自然语言现可触发无权限管理候选** | [实/测-本地报告] 4P-A Mock CLI 与显式入口通过；真实语义选择未验证 | O-03/O-05 |
| `app/database.py` / `importer.py` / `stage*_schema.py` | Excel 只读初始化、SQLite 权威、加法迁移 | S4-A/P-A 回归报告覆盖；正式库仍不得用于实验 | 基础设施 |
| `app/agent.py` | 单 Loop、工具 ID 配对、预算、Trace、管理候选生命周期 | 4P-A 代码变更；**DeepSeek Thinking `reasoning_content` 仍被过滤**，4P-C 修复 | O-04/O-07 |
| `app/tool_registry.py` | Schema/权限/范围/白名单；自然候选只进预览 | 4P-A 新测试覆盖无授权直接执行失败；多步计划管理候选尚需针对性验收 | O-08 |
| `app/persistence.py` | `ManagementProposals/Candidate` → 可信确认 → `ManagementTurn/Approval`，指纹/旧值/一次性 | 4P-A 19 新测试及旧确认测试通过（本地报告）；仍需 live | O-05/O-08 |
| `app/tasks.py` | 单未完成任务、持久状态、恢复时重查当前规则和发票 | S4-B 真实跨进程恢复、缺项 5→4；**不必新建任务 DAG**；4P-B 关注用户可见进度 | O-03/O-05 |
| `app/preferences.py` | 用户×企业 CRUD、候选预览与受控写入 | 4P-A Mock/SQLite/子进程删除测试通过；S4-B 旧代码偏好删除 live 失败，补丁后待复验 | O-05 |
| `app/responses.py` | 安全结构化追问、未知合法 `missing_fields` 通用降级、可信渲染 | 4P-A 修复非法字段导致中止；4P-B 继续修复「成功事实被 NO_PROGRESS 隐藏」与汇总输出 | O-10 |
| `app/queries.py` / `finance.py` | 当前发票/银行查询、金额按整数分统计 | S4-B 明确汇总对照与 SQLite 一致；原 A2 上下文补月份却不完整，4P-B 修 | O-01 |
| `app/rules.py` | 规则导入/停用/唯一 RuleDecision | S4-B C001 R002 v2.0 / C002 R003 v1.0 实际核实；管理员历史审计仍非 P0 已完成项 | O-06 |
| `app/updates.py` / `write_coordination.py` | Prepare、可信确认、提交+同事务 Audit+Readback、原值冲突、幂等 | S4-B 真实 B2/C4 Commit 成功；保留一切安全界限；提交后进度展示受协议阻断 | O-02/O-03 |
| `app/context.py` / `references.py` | 必要历史选取、当前任务/偏好/锚点；可信列表引用 | 48000 字符上限非实际 Token；原 DeepSeek 旧历史协议不完整，4P-C 最小适配 | O-07 |
| `app/scheduler.py` | Fast Path/粗计划，9 模型、12 Handler、2 续期、1 重规划，工具配对 | S4-A/P-A 回归；S4-B live 最大 M/R/T=3/7/4，**没有 live 触发续期**；4P-D 修日志事件名 | O-04/O-09 |
| `app/trace.py` | JSONL 输入/工具/预算/回执，失败降级、模式标记 | S4-B live 54/54 配对；缺真实 usage/latency/cost 与 provider metadata；4P-C 禁止泄露 thinking | O-09 |
| `tests/test_stage3a.py`, `3b.py`, `3c.py` | 20 / 28 / 23 用例 | 被包含在 Codex 本地 238/238 中；GitHub 尚无自动 CI 重跑 | 基线 |
| `tests/test_management_confirmation.py` | 15 项内容确认边界 | 被包含在 238/238 中，旧断言未被删改 | 安全 |
| `tests/test_stage4pa.py` | 19 项候选、安全回调、偏好 CRUD、未知追问、真实子进程测试 | 代码静态可数，报告 19/19；真实 API 待测 | 4P-A |
| `AGENTS.md`, `docs/ARCHITECTURE_CONTRACTS.md`, `docs/flows` | 短工程约定、目标契约、真实流程说明 | 总纲可做主控索引，不能替代 AGENTS 或擅改旧验收报告 | 治理 |

**正式模型业务 Tool List：仍为 12 个**，清单及参数沿用 v1.0 的原版记录（`get_finance_summary`、`list_invoices`、`get_invoice`、`list_bank_transactions`、`check_missing_purpose`、`get_applicable_rules`、`prepare_invoice_update`、`list_tasks`、`manage_task`、`manage_preference`、`resolve_invoice_reference`、`set_schedule`）。教学隐藏工具依旧不意味着正式授权。

## 5. 模型请求、工具调用、调度预算：实际**五个不同计数/状态**

本章直接依据 `agent.py`、`scheduler.py`，未来 Codex 不能把它们都叫“工具次数”。

| 字段 / 概念 | 计数方式（当前源码） | 实际含义及可验证证据 |
|---|---|---|
| `model_requests` | `TurnExecution.start_request()` 在实际调用模型**之前** `+=1` | 一条用户消息内尝试了多少次模型 API 请求；API 抛异常仍计入；硬限**≤9** |
| `requested_tool_calls` | 遍历 LLM 返回的每个 `tool_calls` 时 `+=1` | **模型提出了多少个工具调用**，包括后来被拒/跳过的；**可能 >12**；此字段不是实际执行数 |
| `actual_tool_calls` | `TurnExecution.dispatch()` 通过重复/额度检查后 `+=1`，随后进入 `handle_tool()` | **进入 Handler 的调用尝试数**，包含 Handler 内部参数无效/业务拒绝的尝试，也包含 `set_schedule`；硬限**≤12**。**不等于成功数据库操作次数** |
| `progress_count` | `observe()` 对 `SUCCESS/NO_DATA` 等可接受的真实工具证据递增 | 运行进度证据计数，**不等于已完成任务数、已补齐发票数或成功 Commit 次数**；即使只读 `NO_DATA` 也可能代表一步已查明 |
| `extensions` / `replans` / `block_limit` / `stop_reason` | `TurnExecution` 控制并通过 `snapshot()` 留痕 | 续期次数 ≤2；显式重规划 ≤1；当前预算块上限 3→6→9；为何停止 |

### 5.1 执行时序（不可混淆）

```text
用户消息到达 → 新建 TurnExecution（计数全部从 0 开始）
  ├─ start_request 检查软/硬上限 → model_requests +1
  ├─ Trace model_input（实际 messages + 正式 Tool Schemas）
  ├─ 请求 LLM → assistant 回复 tool_calls[]
  └─ 每个 tool_call：
       requested_tool_calls +1 → 先做可见 Tool List 校验
       → 如果本轮已经停止、未知/隐藏工具：返回对应拒绝（不进入 Handler）
       → 否则 dispatch：重复或超额度跳过；正常则 actual_tool_calls +1
       → handle_tool：Schema、权限、范围、业务服务
       → 无论执行/拒绝，按 tool_call_id 追加成对 tool 结果
       → observe：用实际工具证据更新计划及 stop_reason
  └─ 需要下一次模型调用？到第 3 次时检查是否可续：
       有真实新证据 + 仍有就绪且合法步骤 + 没停滞 → 扩 3 次
       否则安全停止；硬上限 9 次模型、12 次 Handler 尝试
```

**示例**：一个模型回复中一次提出 14 个工具调用：`requested_tool_calls` 可以等于 14，但如果先执行 12 个，其余 2 个要有逐 ID 结果而**不能真的进入 Handler**。因此「requested_tools > 12」本身不违反最初约定的「最多 12 次**实际**工具调用」。如果比赛希望另限**模型提案数量**，需另外定义，不可误称当前失败。

### 5.2 预算的边界与局限

- `BudgetPolicy(block_requests=3,max_requests=9,max_tools=12,max_extensions=2,max_replans=1)` 当前限制用户只能降低而不能超过 9/12/2/1 上限。
- 简单查询无需 `set_schedule`，通常一次模型请求直接 Tool Calling；没有必要为了“可规划”每轮付额外模型调用。
- 如果没有既定计划/合法剩余步骤，或本块无新进度，默认不续下一块。
- **无 Token 估算器**，也未计费用；9 只是模型请求次数，不是 Token 数。实际成本还受提示词长度、工具 Schema、返回文本、模型价格影响。
- `ContextBuilder.max_chars=48000` 默认只计算被选择的**序列化消息字符数**；不含工具 Schema，不能声称是实际 API token 数/硬窗口保证。
- `actual_tool_calls` 中的“实际”是**进入 Handler 的调用尝试**，不是数据库成功写入次数；SQL 查询可能在工具实现内产生多个确定性操作，不拆作多次模型工具调用。
- `self.messages` 在进程内保存全部历史，Context Builder 为每次**模型输入**裁剪；这与“进程常驻内存历史永久受限”不是同一件事。
- **真实 API 的费用预算 ≠ 单轮算法预算**：本轮 9/12/2/1 硬限不得调整；但 4P 调试不再以整个阶段 18 次请求硬封顶。真实调用与 Token 数据见第 9.4～9.7 节。

### 5.3 未来日志验收的最低计数断言

1. 单轮 `model_requests ≤ 9`、`actual_tool_calls ≤ 12`、`extensions ≤ 2`、`replans ≤ 1`，每条新用户消息重新计数。
2. ToolCall 需每个 `tool_call_id` 有且仅有一个工具结果，包括非法参数、DENIED、预算跳过。
3. `requested_tool_calls` 与 `actual_tool_calls` 分开报告；超额提案不允许执行。
4. `budget.extended` 必须有真实进度/剩余依赖依据；不能用模型文本授权额外请求。
5. `WAITING_CONFIRMATION`、`DENIED`、`NO_PROGRESS`、`TOOL_LIMIT` 等安全停止不应误报 `COMPLETED` 或 `COMMITTED`。
6. 每次模型请求都要有对应 `model_input` Trace；API 失败也要保留合适错误与终止原因，不泄露密钥。

---

## 6. 日志、证据、审计：实际有多少种，记录了什么，没记录什么

### 6.1 必须区分三类“记录”

| 类别 | 当前保存位置 | 功能与可信度 | 不可以用来证明什么 |
|---|---|---|---|
| **A. Agent 运行日志（JSONL Trace）** | `trace.py` 输出到 CLI 指定 `--trace` 路径 | 看模型实际输入/输出、工具/规则证据、预算、错误及回复；便于调试与演示 | 不能代替数据库成功提交证明；Trace 写失败不等于业务失败 |
| **B. 发票提交审计（SQLite invoice_audit）** | SQLite，与发票 UPDATE **同一事务** | 可信 `request_id`、fingerprint、actor、企业、发票、字段、旧/新值、状态等；新连接回读 | 不是完整对话记录，不包含所有被拒绝的尝试或全部模型历史 |
| **C. 持久任务/偏好/引用状态** | SQLite tasks、preferences、reference_anchors | 支持跨进程恢复当前状态、当前偏好和历史列表锚点；包含时间字段/来源信息的部分状态 | **不等于完整逐变更事件审计或逐条操作时间线**；无法把它们直接称作「任务日志」 |

### 6.2 当前 JSONL 事件结构及已看到的事件

`write_trace()` 每行结构大体是：

```json
{"trace_id":"...","mode":"live|mock","event":"...","data":{}}
```

**现有 `trace.py` 本身未为每个事件添加独立 `timestamp` 字段**。一个轮次由 `trace_id` 关联；`mode` 区分 Mock/live。事件名和 payload 依调用点而定。S4-B 已记录 41 条 `turn.finished`、54 组 Tool Call 的逐 ID 配对与真实响应 usage，但 Provider/Model/latency 主要来自当次外部测试记录，**不是当前 Trace 原生完整支持**。

| 事件/类别 | 触发位置 | 核心含义 |
|---|---|---|
| `turn.started` | `Agent.ask` 开始 | 可信用户轮次开始；建立 trace_id、当轮执行控制器 |
| `context.selected` | `Agent.model_messages` | 本次选了什么来源、范围、字符数、上限、裁剪与遗漏、来源归属 |
| `model_input` | 调用模型前 | **实际传给模型的 messages 和 tools Schema**（经 `redact` 再写 JSONL）；可证明输入选择结果 |
| `model_reply` | 模型返回后 | 原始模型答复结构和 tool_calls（过滤之后），不是执行成功事实 |
| `tool.requested` | 每个模型工具提案 | 模型想调用什么及 raw arguments；不等于实际运行 |
| `tool_result` | 每个 tool_call 配对完成 | 工具状态、业务/规则证据、错误、被拒原因或待确认信息 |
| `budget` | `start_request` 成功计数 | 当前模型请求数/预算快照 |
| `budget.extended` | 第 3/6 次请求后合法续期 | 本块有新工具证据、剩余合法依赖，block_limit 延至 6/9 |
| `schedule.created` / `schedule.replanned` | `set_schedule` 验证安装 | 本轮粗计划创建或一次显式修订，不能视为业务事务 |
| `schedule.progress` | `observe()` 接受工具证据 | 当前实现即使 `schedule=None` 也可能发出（S4-B 观察 32 条）；这不是存在真实计划的证明，4P-D 需修正语义 |
| `execution.stopped` | `TurnExecution.stop()` | 停止原因：ANSWERED、WAITING_USER、NO_PROGRESS、DENIED、MODEL_LIMIT、TOOL_LIMIT、CONTEXT_LIMIT 等 |
| `reference.resolved` / `reference.unresolved` | `ContextBuilder.resolve` 后 | 可信锚点的解析结果或缺乏唯一证据 |
| `reference.displayed` | 真实结果展示后 | 哪些列表被记录为可引用锚点及其 scope |
| `context.error` / `context.limit` | 处理引用故障或输入超限 | 观察错误与安全停止，不能误报查询成功 |
| `update.result` | `WriteCoordinator` 的确认/取消 | 程序权威回执（含状态、回读验证布尔值），不是 LLM 文本 |
| `turn.finished` | `Agent.finish` | 最终文字、tools_attempted、操作回执、执行快照、停止原因 |
| `error` | LLM / JSON 结构异常等 | 失败性质和安全终止；避免打印密钥/底层异常 |

**真实性约束**：`Trace` 中出现 `COMMITTED` 字样不能单独作提交证据；必须由 `invoice_audit` 与当前发票值共同核对。`trace_degraded` 表示记录受损但不能更改数据库已提交事实。

### 6.3 各业务动作的日志覆盖（当前完整性矩阵）

| 行为 | JSONL Trace | SQLite 业务证据 | 当前差距 |
|---|---|---|---|
| 模型查询金额、发票、流水 | 有 model_input、tool.requested/result、turn.finished | 当前只读工具结果来自 SQLite | S4-B 旧代码 A2 原始连续提问未完整汇总；4P-B 需 live 对照 |
| 模型规则查询、缺用途检查 | tool_result/evidence 中可携带 rule 与 scope | SQLite rules + 当前发票 | 执行规则版本可追溯；未要求独立规则命中事件表 |
| 模型 Prepare 发票修改 | tool_result WAITING_CONFIRMATION、回执 | 当前会话 Draft（未写库） | **不能**据此称发票已提交 |
| CLI 可信确认 + Commit | `update.result`（Trace 可写时） | 同事务 `invoice_audit` + 发票字段 + 新连接回读 | 双证据链已实现，S4-B 的 B2 已有真实 live 成功；完整场景未全部通过 |
| 发票越权、冲突、取消 | ToolResult/回执和部分 Trace | 不写成功 audit | SQLite invoice_audit **不是所有拒绝事件日志** |
| 模型创建/修改任务 | tool.requested/result；提案/确认结果可在 evidence 中记录 | tasks 当前状态和 updated_at | 没有独立**每次任务状态变更事件表**；任务进度偏粗 |
| 模型修改偏好 | tool.requested/result，确认摘要 | preferences 当前值/explicit_request/updated_at | 没有单独偏好变更历史流水；删除后不能仅凭当前表还原历史 |
| 直接 `tasks/preferences` CLI 命令 | **未见统一写入 Agent Trace 的入口** | SQLite 状态发生变更 | 如果演示要复盘所有直接 CLI 行为，需要额外证据/命令输出；非现有统一日志覆盖 |
| `rules seed/import/disable` 管理 CLI | **未见统一写入 Agent Trace 或独立规则变更审计的入口** | rules 表当前规则内容/启停状态 | V1 曾设想「记录规则管理日志」，目前尚未证实完整落地；P1 可补，不能误称已实现 |
| 一次消息的预算/计划/结束 | budget、schedule.*、execution.stopped、turn.finished | `Agent.last_response.execution` 当前进程可查看 | 没有真实 token 用量/延迟/费用字段；没有 CI 自动统计保证 |
| Trace 写盘失败 | 降级警告与 `trace_degraded` | SQLite 提交仍按自己的事务判断 | 不允许用缺少 Trace 推断没提交 |

### 6.4 Trace 的安全范围

- `redact()` 对字典键中 `key/password/token/secret` 等字段和部分字符串模式做遮盖；这是**规则脱敏**，不是任意敏感信息均可识别的保证。
- 原始用户请求、发票用途/备注、偏好值可能仍出现在 model_input / tool_result / trace；比赛演示只用官方虚构数据，**正式财务资料不应未经审查直接落此类日志**。
- 当前 Trace 中未见强制事件时间戳、实际 token 使用、provider 返回的 usage、调用时延、累计费用、模型端拒绝率等字段；**S4-B 的 usage 来自独立 live 调用捕获**，不是 Trace 本身原生支持。如果报告使用这些指标，必须标注采集来源；4P-D 可实现最小 usage/latency 元数据，不强制费用推算或账单读取。
- `trace_id` ≠ `task_id` ≠ `request_id` ≠ `tool_call_id`：分别对应**轮次**、**长期任务**、**待确认写入操作**、**一次模型工具提案**。日志中可能互相包含，但尚未证明所有路径自动构成可跨系统查询的统一关联索引。

### 6.5 建议的 Stage 4 观测证据包（不会强制新建复杂系统）

1. 一条自然语言查询的 `turn.started → context.selected → model_input → model_reply → tool.requested → tool_result → turn.finished`。
2. 一条需追问的查询：缺失范围、clarification 与下一轮正确工具结果。
3. 一条发票修改：本轮文本/目标 → WAITING_CONFIRMATION → 可信确认 → `invoice_audit` → 新连接回读 → `update.result`。
4. 一条长期任务：当前缺项数 → 创建 → 跨进程恢复 → 发票补充 → 再查缺项数 → 完成或 WAITING_USER。
5. 一个 Scheduler 多步/扩预算的 Mock 可复现例子，显示 `model_requests/requested_tool_calls/actual_tool_calls/extensions/replans/stop_reason`；另明确真实模型里是否有触发续期的例子。
6. 展示 R002 2.0 / R003 1.0 的真实 ToolResult 规则证据，以及 U002 的 DENIED。
7. Trace 中的敏感字段检查结果；不要把 `.env`、私有财务数据、完整生产日志上传 Git。

---

## 7. 当前设计偏差、已知缺口与真实失败台账

**状态依据**：以 4P-E 被测代码 `3a83a2c87afe`、冻结题集和正式 Live 报告为准。旧 S4-B/A/B/C/D 报告不得改写；旧代码失败不自动等于新代码失败，Mock PASS 不自动等于 Live PASS。以下 P0 为问题优先级，P01/P11/P12 为缺陷标识，二者不可混淆。

| ID / 分类 | 已证实的现象与证据 | 当前判定 | 最小下一步 |
|---|---|---|---|
| **P01 / G01** 自然语言管理 | 4P-A 形成无权限候选+具体确认；4P-E Flash 偏好 CRUD、H1 自然任务创建及跨进程诊断成功；原 C2 多轮主链仍 FAIL | **安全链 PASS / 原 C 链 FAIL** | 不重写管理授权；审核 C2 的候选 note 与冻结确认规则，按原题复验 |
| **P02** 成功回执与重复 | 4P-B 保留已执行证据；4P-E B6 真实重复 get → NO_PROGRESS，用户未得到冻结要求的 NO_CHANGE 回执；P11 Pro 保存成功后重复读取提示也可能误导 | **部分修复，真实 UX 缺口仍在** | 以已核实当前值表达“无需变更”，同时保留停止原因；不捏造 Commit/审计 |
| **P03** 偏好删除 | 4P-E Flash 自然增/查/改/删与重启持久化成功；Pro SQL 删除成功却生成非法最终输出 | **Flash Live PASS / Pro 回复 FAIL** | 区分数据库事实与模型最终格式错误，不因回答失败回滚已核实删除 |
| **P04** 汇总完整性 | 4P-E 补年月后 A2 正确汇总及 R001；但 A1 缺日期时先擅查九月，见 P12 | **结果与 SQL 一致 / 目标范围尚不安全** | 修来源约束而非金额算法 |
| **P05 / G02** 持久任务推进 | H1 独立诊断：真实任务创建、进程重启、缺项 5→4 与继续 ACTIVE 均有 SQL 证据；原 C2 不落库使原 C3/C5/C6 失败 | **底层持久性 PASS / 原 C 整链 FAIL** | 优先解决 C2 语义确认，再全链原题复验 |
| **P06** 非法追问结构 | 4P-A 离线降级曾修复；4P-E Pro 多次返回非法最终 JSON 或普通文本，被安全拒绝 | **保守拒绝有效 / Pro 真实可用性不足** | 不放松业务执行凭据；分类协议/模型格式/超时，有限诊断 |
| **P07** Thinking 协议 | 4P-C 真实同会话消息回传修复；4P-E 294 次 HTTP200 中未出现旧 reasoning_content 缺失 HTTP400 | **本轮旧错误未复现** | 继续保留隐私、裁剪和逐 ID 配对回归 |
| **P08/P09/P10** 配置、Trace、会话 | 4P-D 304/304 与 15 次真实请求；4P-E 仍有 Provider 用量元数据；两模型同 Key，对第二真实账户、其他兼容 Provider 无 Live 证明 | **当前范围内通过 / 未测项保留** | 不因功能完成扩张到生产认证、自动路由 |
| **P11** 复合偏好意图 | 原句 Flash 已完成 get NOT_FOUND→可信 create→get；Pro 超时、重复/软限收尾仍不稳定 | **部分修复；[Issue #1](https://github.com/knone32/Economy-guy/issues/1) OPEN** | 保留原题和失败；针对完整目标成功回执复验，满足后再关闭 |
| **P12** 缺失参数来源 | 4P-E A1 Flash 未获年份/月却先查询 2026-09，之后才追问；SQL 数据虽真实，但请求范围没有可信用户来源 | **P0 OPEN，尚无 GitHub Issue** | 下一独立阶段创建 Issue；优先在工具执行前验证必要年月/企业来源；无来源就追问 |
| **C2（确认标准争议，待定缺陷号）** | 原题“把这些还没有补完用途的发票记成一个待办，我下次继续处理。”；冻结脚本仅允许四句 note，模型长描述被取消；另一次接近原话的 note 也因不在白名单而取消 | **冻结评分 FAIL，不足以证明自然语义本身 FAIL** | **不改旧测试**；外部审核原意一致/范围正确/无额外指令的客观准则，另建新版 Case |
| **H2** 只读越界提案 | 4P-D/4P-E 早期模型对只读问题提出 Prepare，被 Harness DENIED；4P-E 缩小本轮工具暴露后 Flash 原句 PASS，Pro 仍有超时/格式失败 | **安全阻断有效；泛化待测** | 只读/写入能力按可信会话最小授权，补自然语言变体验收 |
| **B6（回执协议，待定缺陷号）** | 重复目标已达到但模型仅查询或重复读取，缺少符合用户预期的 NO_CHANGE 回执，实际无第二条审计 | **UX FAIL / 幂等事实 PASS** | 核对旧值/新值和当前目标满足性，不强制模型必须产生新写入 |
| **Pro 稳定性（待定缺陷号）** | 非 JSON 最终回复、ReadTimeout；Pro 有效正式子集 14/23，未和 Flash 使用完整等量题集 | **LIVE PARTIAL，不能直接排名** | 区分模型格式与网络失败；同题小样本重跑、不择优、记录 usage |
| **G06/G07；G08～G11** | 规则管理直接 CLI Trace 尚非统一；字符上限/引用/预算简化被接受，GUI、生产登录、DAG、复杂摘要未在 P0 范围内 | **P1/P2 检查待做，部分属已接受延期** | 后续有限 SEC-A 判断缺陷与范围延期，不把未开发功能一律算漏洞 |

### 7.1 已确认的开发阻力（按阻断顺序）

1. **P12：参数合法但来源不合法。** 现有 JSON Schema、企业权限和 SQLite 可全部通过，却仍可能使用模型猜出的年月；必须区分“授权读企业”与“用户指定本次业务范围”。这是当前最优先的 Harness 级修复目标，不能只改 Prompt。
2. **C2：候选提案与自动确认脚本之间的语义错位。** 严格确认实现了“未授权不写”，但把有限同义句白名单当作所有可确认的自然语言表达，会造成测试假阴性。不能从 SQL 持久性诊断 PASS 倒推原 C2 PASS，也不能为追求 PASS 悄悄放宽冻结题。
3. **P11/B6：复合目标与正确停止回执不一致。** 实际 get/NOT_FOUND、create、get/成功或当前值已满足的组合，仍可能被重复防护/软限收尾覆盖；修复前须区分真实结果、剩余目标、停止原因。
4. **Pro 最终输出/超时。** 4P-C 已解决特定 Thinking 历史协议 HTTP400，但 Pro 多次输出不满足当前 JSON 信封；不能通过放松写入确认换取漂亮回复。网络超时与模型格式需分开统计。
5. **经验测试覆盖不足。** 4P-E 59 条均为 PUBLIC_REGRESSION，5 项新单测只覆盖已知最小反例；尚无外部未知 Holdout、正式权限/资源压测、非官方数据泛化证明。304→309 项增长不等于这些能力已解决。
6. **费用与开发节奏。** 4P-E 单阶段 298 次 API 尝试、成功响应 usage 1,167,596 Token；实际人民币扣费/余额 UNKNOWN。后续优先固定反例+少量对照，而非无新诊断重跑全部 59 题或直接放大压测。

### 7.2 待验证方案：结构化意图与参数来源（不是已冻结的新架构）

**现有事实**：Tool Calling 已有结构化参数、Schema、Handler 鉴权，但这些机制主要校验参数类型/可访问性，**不保证参数由用户本轮明确提出**。简单给 LLM 强制 JSON/Strict Function Calling 无法单独证明字段来源。

**建议的最小实验（S4-P0-Closure 再决定）**：
- 先在现有可信上下文/工具执行边界建立必要槽位的来源约束：`company_id / year / month` 对汇总必须来自本轮明确表达、经允许延续的可信会话范围或可信补充；缺项时生成结构化追问，不靠模型补默认年月。工具参数与来源不一致即安全拒绝。
- 可尝试小型 **Intent Frame** 候选（意图、必要 slots、null 缺项、只读/写入目标、复合目标剩余项），但其模型输出和自报 `source=user_explicit` **仍是不可信数据**；Harness 必须独立关联用户原句、授权上下文和当前 SQLite，不引入隐式权限。
- 最先**不额外增加模型请求**，用现有 Tool Calling + Harness 校验复现 P12；若复合意图如 P11/C2 确需单独抽取，先 A/B 测试对成功率、误调用、追问、耗时、Token 的实际影响。需要额外请求时计入原有 `model_requests≤9`，不得增加第二个无预算的识别模型。
- 不引入新的长期 Intent 数据库、第二 Agent、自动路由或任意语义可信度打分；只有实测改善且无安全回归，才讨论是否推广到其他业务。

### 7.3 GitHub Issue 治理（后续 Codex 指令）

- **P11** 保留 [Issue #1](https://github.com/knone32/Economy-guy/issues/1) 为 OPEN，当前 Flash PASS 不代表 Pro 和软限 UX 全部解决。
- **P12** 是明确可复现的 P0 根因候选。**下一阶段 Codex 先搜索重复 Issue，无重复再创建 P12 Issue**，附原 A1、被测 SHA、预期与实际、无授权范围/无实际越权写入的准确边界、冻结测试链接、最小复验标准；Issue 创建是远端操作，**不需要 git push**。本轮总纲更新不宣称已经创建。
- **C2、B6、Pro 问题**先做独立根因分组，实际证实不同根因后再开 Issue；不要为同一根因每个模型/表述重复开工单。
- Issue 的关闭必须依赖冻结原题、修复前后当前 SHA、确定性反例、Live 实证与 SQLite 副作用检查。Issue 记录不能替代测试或用户确认。

### 7.4 不变的安全判断

- HTTP200 不等于业务 PASS；模型提出错误 Prepare 被 Harness DENIED 只能记 `SAFETY_PASS / MODEL_DECISION_FAIL`。
- 未经可信确认的任务/偏好或发票更改绝不写入；恶意参数即使格式正确也不产生权限。
- 无当前授权范围不能用模型“推测的日期”作为本轮查询许可；但必须谨慎定义何为用户明确表达/可信延续，防止误拦合法的跨轮补充。
- 不因为 C2 的严格脚本拒绝就宣称 Task Manager 坏掉；H1 的持久任务恢复与缺项 5→4 已有独立 SQLite 证据。
- 不删除 Mock 安全反例，不修改旧验收报告/已冻结题集；外部 Holdout 必须在新代码 SHA 冻结后提供。

## 8. 阶段目标全景台账（按最新 4P 决定与依赖展开）

| 编号 | 最低可验收交付 | 目前状态 | 最小下一步 |
|---|---|---|---|
| S0～S2.5 | 安全初始化、金额/权限、规则版本、发票受控写入与审计 | [实/测-本地报告] 旧边界仍在 238/238 回归；B2 真实 Commit 成功 | 4P-B～E 不退化 |
| S3A | 任务/偏好持久、一个未完成任务索引、跨进程恢复 | [实/测-本地报告/live-旧代码] 真正恢复成功 | 4P-B 关注剩余事项用户体验 |
| S3B | Context 选择、历史锚点与保守歧义处理 | [实/测-本地报告] live 仍需复杂对话验证 | 不新增完整历史搜索 |
| S3C | 3+3+3、9 模型/12 Handler/2 续期/1 重规划 | [实/测-本地报告] live 已显示正常停止与工具计数，未触达扩预算 | 4P-E 保留极限 Mock 及有限 live |
| S4-A | 当时 Stage3 补丁的独立执行报告 | **已完成阶段**：219/219 Codex 本地报告，报告 `08b3ed5` | 旧报告不改写 |
| S4-B | 真实 LLM 三场景故障取证 | **已完成取证**：41 轮、64 次 Chat 请求；A/B/C 整体 FAIL，记录 F01～F05 | 作为 4P 的复现依据，不再次无目的全量回放 |
| **4P-A** | 无权限自然语言管理候选、可信内容确认、偏好 CRUD、未知追问 | **已完成离线修复**：代码 `0c043151`，19 新用例，总 238/238；0 live | 4P-B/E 针对性 live 验证 |
| **4P-B** | 已完成业务事实/停止原因分开、财务完整汇总、当前任务剩余展示 | **离线256/256；live部分通过**，代码ccd184ff；见S4-P-B | 原L2 FAIL与真实重复未观察到保留；同会话HTTP400待C/E，不宣布完整live通过 |
| **4P-C** | DeepSeek Thinking 多轮协议兼容、思考隐私、工具 ID 配对 | **已完成，274/274**；最终代码 `d27ca917`，本阶段最终 9/9 HTTP200（阶段合计 24 次） | P07 在 4P-E 未复现原 HTTP400；其他 Provider live 不能自动算通过 |
| **4P-D** | Provider Profile/独立 Key/安全切换、Trace 语义与最小调用元数据 | **304/304及15次HTTP200**；P08～P10；[报告](verification/stage4/S4-P-D.md) | D/L/B：Key冻结/权限与两模型协议通过，F002单次审计+缺项5→4，原续问PARTIAL/只读对照PASS；无自动路由；E未执行 |
| **4P-E** | 冻结 59 条公开题、全量测试与官方三场景 live 回归 | **执行与报告完成；309/309；官方业务门禁 BLOCKED** | [报告](verification/stage4/S4-P-E.md)、[题集](verification/stage4/S4-P-E-CASES.md)、[逐题结果](verification/stage4/S4-P-E-RESULTS.md)；A FAIL、B PARTIAL、C FAIL；费用 UNKNOWN、Holdout 未测 | 
| **S4-P0-Closure / CLOSURE** | P12/P11/B6 与三进程持久链 | 历史模拟确认链通过 | 保留此前 C2 暂缓及旧失败 |
| **S4-SEC-A** | 隔离冻结安全发现 | 25 个公开案例已执行 | 历史发现见原报告 |
| **S4-SEC-B** | 最小安全修复及公开 Live | 工程 PASS，SEC-B4 Live PARTIAL | 不以安全回归替代业务验收 |
| **S4-BR** | 两项交互补丁与独立 SQL 核对 | 工程 PASS | P0 Live PARTIAL，B/C 使用组合证据 |
| **S4-C** | 证据索引、Issue 结算与回归 | EVIDENCE GATE PASS | 见 [封板报告](verification/stage4/S4-C.md) |
| **S4-D** | 启动说明、设计、关键记录、≤5 分钟演示及安全交付 ZIP | PREPARATION READY，执行待授权 | 安全发布 BLOCKED；如实保留 P0 和 Holdout 状态 |
| P1/P2/P3 | 长对话摘要、动态估算、生产认证、GUI、DAG、复杂模型路由 | 延后 | 当前任务不执行 |

### 8.1 新的执行顺序（每阶段单独提交、独立门禁）

**已执行**：`4P-B → 4P-C → 4P-D → 4P-E → S4-P0-Closure/CLOSURE → S4-SEC-A → S4-SEC-B → S4-BR → S4-C`。历史业务失败保持原判定。

**待授权阶段**：S4-D 准备就绪。交付准备与安全发布分别记录，后者仍为 BLOCKED。

- **阶段交付模式**：锁定 HEAD + 审核冻结原题/已有失败 Trace → 先记录独立真值/根因假设 → 最小红色反例 → 仅修改必要代码 → 定向与全量 unittest → 小批量同原题 live/独立 SQLite → Git 代码/报告分开提交 → ChatGPT 外部核验。业务写事务必须在隔离临时数据库操作。新题和新评分规则要用独立 Case ID，不得覆盖 4P-E 公开冻结历史。
- **实时结果与预算**：4P-E 已消耗 298 次 API 尝试并提供关键失败证据；后续从已冻结失败原题中定向复验，不再为无新诊断的同一失败反复跑完整 59 题。实际余额/人民币费用须对服务商后台，不用 Token 估算。
- **旧报告/原代码**：S4-A/B、S4-P-A/B/C/D/E 历史报告和 4P-E-CASES 原始冻结题一律保留；新增阶段报告写 Base/Tested/Report SHA 并追溯旧 Case ID；问题编号与优先级分开。
- **停止规则**：同一故障连续两次测试没有新的诊断信息或无安全边界内的最小可行改法，登记 FAIL/BLOCKED，不循环烧 Token。真实 API 出现不可恢复协议错误，离线诊断后再测，不拿 Model 调用当调试断言。

### 8.2 官方三场景验收对话要点

- **A 查询**：自然语言问 C001 九月汇总、故意缺月份、补充月份、改企业；分别验证金额/数量/R001、空集与 DENIED。**不要只用明确“使用 get_finance_summary”这种强提示作为自然通过。**
- **B 修改**：自然提出明确 C001/F002 的用途或备注 → 真实 Tool Calling Prepare → 可信确认 → SQLite Audit+Readback → 同会话继续查当前状态；取消/无权限/旧确认不发生错误写入。
- **C 多轮**：检查 C001 2026-09 缺用途 → 直接自然语言要求保存未完事项 → 可信确认 → 退出 Python 进程 → 恢复 → 补一张用途并真实提交 → 查询缺项 5→4 及下一步 → 后续完成时才标完成。其他用户/企业不能访问。
- **偏好**：自然语言增/查/改/删、可信确认、退出与重启、按用户企业隔离；不能把模型输出当真实状态。

### 8.3 实际调用路径阶段迁移策略

| 开发环节 | Mock/确定性 | 实际 DeepSeek/其他有凭据服务 | DoD |
|---|---|---|---|
| 功能逻辑修复前 | 用 S4-B 失败轨迹重建可复现断言 | 可做极短故障重现；已有足够证据时不必再烧 API | 明确红色反例 |
| 功能修复中 | 低成本快速回归、异常与权限注入 | 只有必要交互用 live 校验目标选择 | 代码最小变化、不破坏安全 |
| 修复完成/阶段验收 | 全量单测+模拟协议/数据库 | **实际模型使用自然输入、真实 Tool Calling、当前 SQLite**；保存退出码/Trace | 二者分别 PASS/FAIL，不互相替代 |
| Stage 4 最终验收 | Mock 保留为抗回归测试集合 | **完整三场景真实 API 的交互和持久审计** | 官方 P0 全部实测通过 |

**特别注意**：Mock 从未设计来“仿真模型智力”，故不会删除或用 live 替换所有 Mock。真正替换的是**原先用 Mock 代表用户交互已完成的验收假设**。

## 9. 完成定义（DoD）、证据与测试基线

### 9.1 真实版本/测试证据（从旧到新）

- **204/204**：此前管理确认补丁**前**的 ZIP，属于历史外部复跑；仅保存历史，不是最新状态。
- **219/219**：S4-A 的 `3c45103` 被测源码，Codex 在本地 Windows + Python 环境执行并提交 `08b3ed5` 报告；GitHub 只见报告与测试代码，无独立 CI。
- **S4-B live**：`08b3ed5` checkout，DeepSeek Flash；41 个轮次，64 次 Chat Completions 尝试，60 HTTP200 / 3 HTTP400 / 1 ConnectError，成功响应的 usage 203,781 prompt + 14,209 completion = **217,990 total_tokens**；原 A/B/C 三场景整体未通过。M/R/T 上限现场观察为 3/7/4，54 个 ToolCall 请求/结果均配对。真实费用未知。
- **238/238**：S4-P-A 代码 `0c043151`，Codex 报告 219 旧 + 19 新，通过，0 错误/跳过；报告提交 `7a9f327`。源码和新增测试存在、旧 219 项测试未被修改；原始 stdout 本地忽略，**没有 GitHub CI**。
- **256/256**：4P-B代码`ccd184ff`，原238项断言不改、新增18项，本地全量PASS；没有GitHub CI。13次真实API尝试（12 HTTP200、1 HTTP400），成功usage 43987 prompt + 2067 completion = 46054 total；失败usage和费用未知。8组Tool Call逐ID配对，L1自然汇总及L3当前进度/跨进程核验通过。
- **274/274**：4P-C 最终代码 `d27ca917`，DeepSeek Thinking 同进程工具续问真实通过；旧缺失 reasoning_content 的 HTTP400 在 4P-E 未复现。
- **304/304**：4P-D 代码 `bd59b2e3`，Global/User Profiles、安全切换、Trace usage/latency 及提交后附加进度隔离；15 次 HTTP200，两模型使用同一合法 Key，真实第二独立服务账户未测。
- **309/309**：4P-E 代码 `3a83a2c8`，新 5 项确定性测试；59 条冻结 PUBLIC_REGRESSION（24 条变体），Flash 最终 51/59、Pro 有效子集 14/23；阶段 298 次 API 尝试、294 HTTP200、4 次无响应、成功响应 usage 1,167,596 Token，失败 usage/费用 UNKNOWN。**官方 A FAIL / B PARTIAL / C FAIL，偏好 Flash CRUD PASS**。
- **4P-E 当时缺口**：P12 无年月来源、C2 原题确认策略争议、P11/B6 复合目标与回执、Pro 非法 JSON/超时；有害 Prepare 被拦截与已完成业务应分开评分。EXTERNAL_HOLDOUT_PENDING 不代表功能 FAIL，也不能写已通过。

- **369/369**：S4-C 在 `111c9f97cd710084b1cfc18b9bf139e159e01389` 新跑，2 项架构与八条原冻结探针另列，真实模型 API 0。当前 D/B/L/E 索引见 [S4-C](verification/stage4/S4-C-EVIDENCE-INDEX.md)。

上述通过数是**各自 SHA 上的总数**，不要累加、替代或直接推算下一版本通过数。4P-E 的 59 题属于开发者已见的 PUBLIC_REGRESSION，非外部 Holdout；修复后原题必须留存最初失败分数，不允许根据答案改题。

### 9.2 各层测试分离

1. **Python/SQLite 确定性测试**：数据导入、金额、权限、规则版本、事务审计、状态机、并发与迁移。
2. **Mock Agent 测试**：多 tool_call、模型恶意参数、格式/计划/计数、确认与取消、预算边界。此类测试不证明模型理解自然语言。
3. **独立子进程测试**：持久任务/偏好/锚点恢复、旧草稿无效、当前 SQLite 与规则重新查询。
4. **真实模型 live E2E（现行优先）**：模型是否主动追问、正确工具选择、交互自然、一次性确认、真正连续的场景 C；还应采集服务商 API 的实际 Token/延迟/错误、轮次与工具数。**官方最终评审重点，不能因为 Mock 通过而跳过**。
5. **可复现证据**：固定 SHA、命令、模拟数据 hash/版本、exit code、已脱敏 Trace、数据库审计/回读与失败项。真实 API 记录应包含 `profile/provider/model`（如可用）、请求/响应标识、Token usage、耗时和错误类别；费用仅可标官方账单核实或未知。

### 9.3 每轮 Codex 交付报告模板（建议写入 AGENTS 的简短引用，不必复制本文）

```text
Repo / Branch / Commit SHA:
本轮目标 ID (如 S4-B / G01):
改动文件与真正生效的函数:
定向测试: <命令 / 数量 / 成败>
全量回归: <命令 / 数量 / 成败>
Mock / live / 实际 SQLite / 子进程分别验证了什么（含实时模型标识和真实场景原文）:
Trace: trace_id、model_requests、requested_tool_calls、actual_tool_calls、extensions、replans、stop_reason、usage（若提供）、latency（若采集）
业务写入: request_id、审计状态、当前回读是否一致（仅虚构数据）；真实API尝试数/成功数/失败数/可得Token/服务商账单核对状态
目标是否完成 / 仍未验证 / 是否推送 commit:
```

**行动约束**：一次只领取一个目标 ID；Codex 先读 `AGENTS.md` 和适用 `ARCHITECTURE_CONTRACTS.md`，只改相关模块；不能自作主张开启 P1/P2/P3；GitHub 一次提交对应可解释的单阶段目标。下一轮由 ChatGPT 按**固定 SHA**审查，避免旧文件误传。

---

### 9.4 真实 API 为主的验收与 Mock 分工（本次新增冻结）

**不删除 Mock，也不让 Mock 充当真实模型**。三条证据跑道独立维护：

| 跑道 | 必须做什么 | 不能由什么替代 |
|---|---|---|
| **D：确定性单测/Mock** | Schema 错误、恶意工具、权限绕过、取消、旧值冲突、一次性确认、重复调用、预算极限、跨进程 | 不能推断模型在自然语言中能做正确选择 |
| **L：真实 LLM + Harness** | 原始自然语言输入、思考/非思考工具协议、追问、更正、查询/保存/恢复、最终回复与停止 | 不能用 scripted_model、提示模型要调哪个工具或直接 SQL 改库凑成 PASS |
| **B：真实 SQLite/审计** | 独立查询前后值、业务规则、权限、request_id、同事务审计/回读、任务和偏好重启持久性 | 不能用最终模型文本、JSONL 或 Mock 回执替代 |

典型开发循环：**D 先还原缺陷 → 最小修补 → D 定向通过 → L 真实请求观察 → B 权威状态核验 → D 全量回归 → 固定 SHA 的报告/提交**。API 非常廉价时也不省掉 D 的安全反例；API 很贵时也不能让 D 冒充 L。

### 9.5 实际运行指标字典（按请求/轮次/场景三级）

| 级别 | 记录字段 | 来源 / 重要注意 |
|---|---|---|
| **API 请求** | `provider, profile, model, thinking_mode, trace_id, request_index, request_status/http_category, latency_ms, prompt_tokens, completion_tokens, total_tokens, finish_reason` | 只有实际服务商返回才标 usage；无该字段写 `unknown`，尤其失败请求的计费未知。`reasoning_content` **绝不**写常规日志 |
| **单轮执行** | `model_requests, requested_tool_calls, actual_tool_calls, extensions, replans, block_limit, progress_count, stop_reason, error_category` | 以 `TurnExecution.snapshot()` 为准；`actual_tool_calls` 是进入 Handler **尝试数**，不是成功更新数 |
| **工具事件** | `tool_call_id, name, validated_args_scope, status, evidence.rule, source, result_type, was_dispatched` | 54/54 等配对率应可从真实 Trace 计算；只存必要脱敏字段，遇敏感对象不要全量留正文 |
| **业务变更** | `task_id, request_id, actor, company_id, invoice_no, field, audit_status, readback_verified, current_missing_count` | SQLite 事务成功证据权威；偏好/任务当前状态要从各自持久表和权限重新查 |
| **完整场景** | `case_id, expected, actual, pass_fail_blocked, used_tool_names, turn_count, api_attempts, actual_sqlite_check, transcript_reference, tested_sha` | 按官方 A/B/C 和偏好增查改删划分；一次场景失败不代表所有子项失败 |
| **运行成本** | `usage_source, tokens_observed, backend_charge_cny, billing_checked_at, unknown_requests, run_total` | 余额和扣费需要服务商官方账单手工确认；不要用估算 Token 价格填作实际扣费 |

**可计算但不要误读的指标**：真实场景完成率、首次成功率、平均请求/场景、Token/场景、延迟 P50/P95（样本太少须标注样本数）、Tool Call 配对率、拒绝率、任务完成前的累计工具尝试、回读一致率、跨进程恢复成功率。**模型输出是否自然**需用明确人工评价标准，不能只看长短或调用次数。

### 9.6 采集与存储设计：足够可追溯、不建监控平台

1. **原始运行记录**：本地忽略目录 `artifacts/live/<run_id>/` 存经审查的真实输入、完整必要步骤、HTTP 分类、usage、SQLite 前后快照及哈希；不要上传原始请求、密钥和未经清理的 reasoning。Mock 使用独立 `artifacts/mock/...`。
2. **汇总报告（允许入 Git）**：`docs/verification/stage4/S4-P-[B-E].md`，记录被测 SHA、场景编号、真实 Provider/Model、`trace_id`、工具计数、服务商成功 usage 和失败未知数、数据库事实核验、错误/剩余问题；任何可以识别真实用户或企业的信息不上传。
3. **模型消息元数据**：首选给传输层加入轻量的调用测量钩子；不能把 `reasoning_content` 混进 `model_input`/`model_reply` 常规 JSONL。私有协议状态受当前 Agent 会话约束，切换 provider 时作废。Trace 写失败不能遮盖已 Commit 的事实。
4. **实验一致性**：同一官方虚构 Excel seed、隔离临时 DB、固定 git SHA，测试期间不要修改正式 `data/finance.db`；多模型对比时保持用户语句、数据库初始状态和安全提示一致，比较才有意义。
5. **真实工具调用与费用**：同时记录模型请求次数、工具请求条目数、实际 Handler 尝试、真正成功 Commit、任务/偏好实际新增改删；不能把任何一个数直接当另一个。
6. **最低安全要求**：脱敏之后仍可能泄露用途、备注、偏好等业务文本。演示与 Git 只使用官方虚构数据；日志不入库的机制不等于无需访问控制。临时原始记录需受限存放并可按期清理。

### 9.7 费用和调试止损（替换旧 4P 的「18 次请求」规定）

- 用户报告 DeepSeek API 账户约 **¥50**；本文件不能验证当前实际余额、定价或每次扣费，**不据此计算能调用多少次**。
- **建议而非程序强制**：将约 **¥35** 作为本轮新增调试累计费用的提醒线，预留约 **¥15** 用于最终演示和突发故障。以**自此刻起**官方后台可确认的实际扣费为准；余额变化后重设，而不是把历史 S4-B 217,990 Token 推算成支付金额。
- 不再规定「4P-B 必须 0 次 API」或「整个 4P 只能 18 次调用」。各子阶段允许以真实 API 做有限目标测试，并记录**请求尝试、实际用量和已知收费**；达到提醒线时暂停核账，是否继续由用户决定。
- **止损针对无进展而非针对正常调用**：相同 HTTP400/格式错误重复两轮没有新诊断信息，转离线复现；若新诊断已定位且测试修正，就继续 live。不要编造完成、不要自动换模型扩大消费。
- **两个预算层严格独立**：程序单轮安全硬限（≤9 模型、≤12 Handler、≤2 续期、≤1 重规划）始终不变；调试账户余额不会改变安全上限。

### 9.8 4P-B～E 真实运行门禁（新计划取代旧零调用指令）

| 阶段 | Mock/确定性 DoD | Live 最低证据（必须标注实际 SHA） | 可延后或 BLOCKED 项 |
|---|---|---|---|
| 4P-B | P02/P04/P05 的旧失败轨迹反例 + 安全回归 | 原 A2 连续补月份的完整汇总与 R001；重复调用后正确呈现已成功事实；任务剩余缺项真实 SQL 对照 | 旧 Thinking 协议阻断的**同会话**全链路留给 C/E，不误标通过 |
| 4P-C | Thinking on/off 多轮工具协议、Context 整轮裁剪、不泄露思考 | DeepSeek Thinking 模式「工具调用→返回→同会话再工具/答复」成功，HTTP400 不再复现 | 缺合法凭据则 BLOCKED，不能用 Mock 声称 live 成功 |
| 4P-D | Profiles 优先级、Key 隔离、旧配置、安全切换、Trace 语义 | 有凭据的 Provider 至少一次真实请求与 Tool Calling 对照；缺凭据的 Provider 标 NOT_TESTED | 不要求所有未来服务商实时测试；不自动故障切换 |
| 4P-E | 当前 SHA 全量测试、旧授权/预算等全部安全反例 | **官方完整三场景+偏好增查改删**，覆盖最初自然语言原句、可信确认、重启恢复、SQLite 审计回读 | 任何未执行场景标 NOT_TESTED，不能拿单一工具成功替代总体 PASS |

**验收原则**：对用户可感知的 P0 业务，只有 D（安全回归）、L（真实交互）、B（当前 SQLite 事实）三条证据均满足，才可给该场景最终 `PASS`；阶段过程允许 `PASS / PARTIAL / FAIL / BLOCKED / NOT_TESTED`。

---

## 10. 设计决策索引与下一步决策点

### 10.1 仍冻结、不重开的决定

- 官方查询、保存、多轮恢复都是 P0；Python/SQLite/单 Agent Loop、Tool Calling 和 CLI 仍为可交付路线。
- 可信身份和权限始终属于 Harness；模型不拥有 `confirmed/user_id`，不能自批管理操作；所有写入按具体对象和内容确认，再以数据库事实判断成功。
- 规则、Task、Context、Reference、Scheduler/预算与发票写入各自拥有独立权威状态。Task 不因一次工具成功就自动完成，Context 不管理真实财务值。
- 程序内部的 3+3+3、9/12/2/1 **安全限额不变**；不同于用户愿意投入的 DeepSeek 调试账户预算。
- **4P-A 已完成离线修复**，不因 Model 仍可能犯错而推倒候选/确认机制；P02/P04/P05 交 4P-B，P07 交 4P-C，Profile 和 P08/P09/P10 交 4P-D。
- 真正的能力证明以 live、受控确认、真实 SQLite 和 Trace **联合验收**；Mock 作为安全回归，不删不冒充 live。
- GitHub 每段单独代码/报告 SHA、只提交脱敏材料，原始日志/虚构测试 DB 本地忽略；禁止 force push、破坏性 reset、覆盖用户改动、自动跨模型补救重试。
- 不增 Planner Agent、任务 DAG、GUI、生产认证、向量库或复杂历史摘要；这些不抢 P0。

### 10.2 尚须由真实运行数据决定的事项

1. **P12 意图/参数来源**：优先验证既有 Harness 是否能在不增加模型请求的前提下禁止缺年月时猜测查询，并保留合法跨轮追问与更正；强制 JSON 本身不是可信来源证明。
2. **Intent Frame 候选是否值得投入**：对 P11/C2 的复合目标，是否需要轻量 `intent/slots/missing_fields/effect`；先 A/B 量化首次完成率、无来源参数、工具选择、额外 usage 和延迟，再决定是否成为固定协议。不默认每轮双模型调用。
3. **C2 同义表达确认标准**：旧四项白名单保留历史评分；外部审查建立不扩写行为、不改变对象/范围、证据可溯源且用户精确确认的新 Case，避免为通过而改写旧题。
4. **P11/B6 正确结果呈现**：从 SQLite 当前状态确认是否已达到目标，保留已完成事项与停止原因，不因为重复查询/软限把已持久化变更说成未发生。
5. **Pro 可靠性与可比性**：验证非法 JSON 与超时的分类，不能拿 Pro 14/23 与 Flash 51/59 当等量严格模型排名；任何新兼容层必须保持私有 reasoning、可信确认和安全停止。
6. **P1/P2 与安全补查**：先在 SEC-A 冻结攻击/资源用例并限时运行，区分真实可复现漏洞与比赛范围外的生产认证、GUI、DAG 等；SEC-B 仅修已证实根因。正式公网安全不在当前原型验收范围。
7. **真实 API 用量和成本**：已有 provider/model、token、latency 记录，实际扣费与余额未核对；小批量高价值复验优先，现有单轮 9/12/2/1 安全硬限不变。

### 10.3 主控总纲维护规则

每次阶段结算只更新：**当前 HEAD、被测代码 SHA、该阶段的历史报告链接、对应的 P 编号状态、D/L/B 证据、实际模型用量和下一阶段门禁**。V0～V3 的设计沿革和已冻结安全契约不反复重写；不复制总纲到 `AGENTS.md`。

## 11. 历史判定（截至 4P-E 被测源码 `3a83a2c87afe` / 报告 `09d851d1e364`）

**基础设施已有真实成果**：Python + SQLite 单 Agent Loop、业务权限/规则、受控 Prepare→Confirm→Commit→Audit→Readback、持久 Task/Preference、Context/引用、3+3+3 预算与 Tool Call 配对、DeepSeek Thinking 协议、多模型 Profile 安全切换、Trace/usage 已形成当前代码与历史实测证据。

**测试基线不是业务完成率**：Codex 本地 309/309 PASS；4P-E 59 条公开题 Flash 最终 51/59、Pro 有效子集 14/23，且 Pro 并未运行完整同量题集；外部未知 Holdout 尚未提供。4P-E 的 A FAIL / B PARTIAL / C FAIL 是本轮**不可覆盖的官方业务门禁**；偏好 Flash CRUD 和 H1 任务持久恢复的局部成功不替代原主链。

**当前最优先阻力**：P12 缺年月却先查库；C2 固定 note 白名单造成的原链取消与测试确认有效性争议；P11/B6 的完成事实与重复/软限停止回执；Pro 非 JSON/超时。尤其 P12 需要“参数来源证明”，不只是 JSON Schema 合法；C2 需要不削弱可信确认的语义标准。未发现“权限系统可被模型直接越过”的已证实事实，不可将拒绝成功称为模型决策正确或宣称全面无漏洞。

**当时建议**：以独立任务执行 `S4-P0-Closure`：先建 P12 Issue、冻结原 A1/C2/P11/B6/H2 对照和判定边界，尝试无额外请求的来源核验，再决定是否做轻量 Intent Frame A/B。随后在隔离环境进行 `S4-SEC-A` P1/P2 与权限/资源/提示注入审计、必要的 `SEC-B` 修复，再独立复核 `S4-BR`、证据封板 `S4-C` 和交付 `S4-D`。每轮另行授权，不能因文档更新自动执行。

**本轮文档提交的范围**：仅更新此总纲的进度/缺陷/阻力与候选方案。未修改生产代码、冻结题集或历史报告；未创建/关闭 GitHub Issue，也未执行新的单测或真实 API。后续任务有需要时由 Codex 在 GitHub 正常创建或更新 Issue，并提供 URL 与根因证据。

## 附：对应仓库的直接阅读入口

- [工程约定 AGENTS.md](https://github.com/knone32/Economy-guy/blob/0c043151d24ab63394ca674516d711c86435f3ac/AGENTS.md)
- [架构与接口契约](https://github.com/knone32/Economy-guy/blob/0c043151d24ab63394ca674516d711c86435f3ac/docs/ARCHITECTURE_CONTRACTS.md)
- [单 Agent Loop](https://github.com/knone32/Economy-guy/blob/0c043151d24ab63394ca674516d711c86435f3ac/finance_agent/app/agent.py)
- [工具注册与 Handler](https://github.com/knone32/Economy-guy/blob/0c043151d24ab63394ca674516d711c86435f3ac/finance_agent/app/tool_registry.py)
- [Context Builder](https://github.com/knone32/Economy-guy/blob/0c043151d24ab63394ca674516d711c86435f3ac/finance_agent/app/context.py)
- [Task Manager](https://github.com/knone32/Economy-guy/blob/0c043151d24ab63394ca674516d711c86435f3ac/finance_agent/app/tasks.py)
- [Preference Store](https://github.com/knone32/Economy-guy/blob/0c043151d24ab63394ca674516d711c86435f3ac/finance_agent/app/preferences.py)
- [Schedule / Budget](https://github.com/knone32/Economy-guy/blob/0c043151d24ab63394ca674516d711c86435f3ac/finance_agent/app/scheduler.py)
- [Trace 写入](https://github.com/knone32/Economy-guy/blob/0c043151d24ab63394ca674516d711c86435f3ac/finance_agent/app/trace.py)
- [发票事务及审计](https://github.com/knone32/Economy-guy/blob/0c043151d24ab63394ca674516d711c86435f3ac/finance_agent/app/updates.py)
- [长期管理确认补丁及测试](https://github.com/knone32/Economy-guy/blob/0c043151d24ab63394ca674516d711c86435f3ac/finance_agent/tests/test_management_confirmation.py)

**版本追加入口**：[S4-A 验收报告](https://github.com/knone32/Economy-guy/blob/7a9f32713e2a98054b9ee7f9aeda6d01452b2747/docs/verification/stage4/S4-A.md) · [S4-B 真实 API 报告](https://github.com/knone32/Economy-guy/blob/7a9f32713e2a98054b9ee7f9aeda6d01452b2747/docs/verification/stage4/S4-B.md) · [S4-P-A 验收报告](https://github.com/knone32/Economy-guy/blob/7a9f32713e2a98054b9ee7f9aeda6d01452b2747/docs/verification/stage4/S4-P-A.md)。

**维护说明**：文件是人和 Codex 共用的**主控对照文档**，不是取代 `AGENTS.md` 的长篇 system prompt。之后每次更新只改“审查基线、目标台账、缺口 ID、验收证据”，不必重写历史章节；本次文件为本地修订稿，**未自动提交到 GitHub**。


## 12. S4-P0-Closure结算（2026-11-06）

- Base `2b2191d22c85`；被测业务源码 `f6d99267358e5202752afbbdd062600781cdab29`；实际报告及逐轮索引：[S4-P0C](verification/stage4/S4-P0C.md)、[RESULTS](verification/stage4/S4-P0C-RESULTS.md)。报告SHA取包含报告的docs(s4p0c)提交，不与被测源码混称。
- D：原309+新26，共335/335；旧测试只适配明确范围输入，不删用例、不改安全断言。L/B：Flash/Pro原A1先追问、A2查正确SQL/R001；P11具体确认后保存再读核对；B6一次Commit及重复请求只读匹配、无第二审计。P12 Issue #2、P11 #1、B6 #3均OPEN待独立审查。
- C2旧冻结四句策略仍FAIL；新语义提案已经生成，但真实用户明确暂缓具体内容决定，零任务。不得将H2独立预置任务夹具或过去H1成功替代C1→C6完整语义链，本阶段门禁仍BLOCKED。
- 小样本Intent A/B均2/2、各6模型请求；B未提升目标完成且增加Token/延迟，生产不实施强制Intent抽取。两次初始B实验脚本协议封装错误保留，不冒充Provider故障。
- 本轮实际62模型API请求、240827 Token、SDK延迟合计135766.971ms，全部返回200不等于全部业务PASS。官方余额已只读核对，实际费用归因UNKNOWN。单轮观察不超过3模型/3Handler、0续期/0重规划；硬限9/12/2/1不变。
- 后续：等待操作者另行决定C2具体确认和完整链复验，满足P0闭环后再独立决定S4-SEC-A；不自动开始。EXTERNAL_HOLDOUT_PENDING。旧4P-E历史与FAIL不回填覆盖。
