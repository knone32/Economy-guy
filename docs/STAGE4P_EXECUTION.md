# Economy-guy · Stage 4P 业务闭环与运行层稳定化

**版本**：v1.1（2026-11-06；替代旧版 API 次数与 Mock-only 预算约束）  
**仓库**：`knone32/Economy-guy` · `main`  
**规划基线 HEAD**：`7a9f32713e2a98054b9ee7f9aeda6d01452b2747`（S4-P-A 验收报告提交）；当前被测代码 `0c043151d24ab63394ca674516d711c86435f3ac`。  
**验收依据**：官方参赛说明与业务规则 1.1.0；根目录 `AGENTS.md`；`docs/ARCHITECTURE_CONTRACTS.md`；`docs/verification/stage4/S4-A.md` 与 `S4-B.md`；此前《项目总控总纲 v1.0》。  
**状态口径**：S4-A 有 Codex 本地 **219/219** 回归报告；S4-B 在旧版本真实调用 DeepSeek，三场景整体 A/B/C **FAIL**（部分子链路已成功）；**S4-P-A 已完成**，代码 `0c043151`，19 个新测试、本地全量 **238/238**，尚无补丁后 live 验证。本任务书的 B～E 仍是**未执行的目标**。

> **总目标**：优先消除 S4-B 已有证据的业务与设计缺口，再修复阻断多轮交互的协议错误，最后实现低复杂度多提供商配置与日志语义改进。保持单 Agent Loop、Python+SQLite、CLI、严格可信授权及原业务规则。**4P 内不自动进入 S4-C/D。**
>
> **新增冻结决定**：**真实 LLM 是用户可感知业务的最终验收依据，Mock 是不可删除的确定性回归设施**。不再对 4P-B 禁止 API、不再按 4P 全程 18 次硬封顶；真实模型、受控 CLI、SQLite/审计的证据必须同时存在。DeepSeek 约 50 元余额仅为用户当前陈述，实际扣费以官方后台为准。完整规则见《项目总控总纲 v1.1》第 9.4～9.8 节。

### 版本迁移说明

- 原 `4P-A` Prompt 已经执行，**保留为历史，不应重发**。
- 以下 B/C/D/E 提示词按本 v1.1 标准执行；旧版「0 次」「最多 6/2/10 次」「18 次总硬限」不再生效。
- **4P-B 仍先修业务**；遇已知 Thinking HTTP400 不盲试，4P-C 处理协议后再做同会话 live 复验。

## 0. 任务分层与缺口映射

| ID | 已观测故障（S4-B） | 目标行为 | 执行阶段 | 判定 |
|---|---|---|---|---|
| P01 / G01 | 自然语言 `manage_task` / `manage_preference` 被 `DENIED`，无 ManagementTurn | 可先产生**无执行权**的操作提案；可信用户核对内容、确认后才可持久写入 | 4P-A | P0 |
| P03 | 显式偏好删除也可能没有正确调用、模型误报缺少入口 | 偏好增/查/改/删均能在自然语言和显式命令下闭环；旧值和 key 正确绑定 | 4P-A | P0 |
| P06 | 模型产生 `missing_fields=[purpose]` / `[new_remark_value]` 等非法字段 | 安全解释/重新追问，不能放松白名单、伪造业务状态或无限重试 | 4P-A | P0 |
| P02 | 已保存任务/已读偏好，模型重复调用后 `NO_PROGRESS` 覆盖成功事实 | 最终回执分别说明**先前已完成的业务事实**、最后停止原因及剩余工作 | 4P-B | P0 |
| P04 | A2 原连续提问返回明细却缺总额/银行收支/数量/R001 | 与用户实际目标对应的汇总工具、规则证据和完整答案；不做关键词场景路由 | 4P-B | P0 |
| P05 / G02 | 成功修改后不能在当前会话展示剩余事项；重启仍能读到 5→4 | 重新查 SQLite/RuleDecision；展示最新缺失数和下一步，不能把协议错当 Task 状态丢失 | 4P-B + 4P-C | P0 |
| P07 | DeepSeek 思考模式 `reasoning_content` 被丢弃，后续 HTTP 400 | 同提供商、同会话携带必要私有协议字段；不污染 Trace/其他提供商 | 4P-C | P0 |
| P08 | 无 schedule 却发 `schedule.progress`（本次 32 条） | 区分工具证据进展、真正的计划进展；事件名与 payload 符合语义 | 4P-D | P1 |
| P09 | 单套全局 KEY/BASE_URL/MODEL | 命名 Profile + 独立密钥环境变量 + 旧配置兼容 + 便捷选择 | 4P-D | P1 |
| P10 | 切换提供商协议历史/写入确认可能串用 | 切换只在安全轮次边界完成；重建短期 Agent，不继承旧草稿/思考字段，持久 SQLite 状态不丢 | 4P-D | P1 |

**明确不等于缺陷**：S4-B 的 B2 已验证真实 `Prepare→可信确认→Commit→Audit→Readback` 成功；C4 的真实 SQLite 缺失数 5→4；任务跨进程恢复成功；54 个 Tool Call 请求/结果逐 ID 配对；工具硬限没有超标。这些不能因为重新修复而被推翻。**禁止未经证据重建任务存储或写入协调器。**

## 1. 不可改变的工程契约

1. **架构**：`main.py` 可信 CLI → `app/agent.py::Agent.ask` 单一 Loop → Tool Registry/Context/Scheduler/WriteCoordinator → 业务服务 → SQLite。Task、Preference、Context、Reference、Schedule 各自保留已有唯一状态所有者；业务服务不能反向依赖 Agent。**不得引入多 Agent、自动路由、向量库、生产认证、GUI、任务 DAG/子项引擎和新的框架依赖链。**
2. **官方事实**：只改发票 `purpose/remark`；银行完全只读；金额用整数分或 Decimal。U001 可读改 C001/C002，U002 只读 C001。2026-09 C001 用 R002 v2.0 全部必填，C002 用 R003 v1.0 ≥1000 元必填；R002 v1.0 停用；R001 汇总、R004 银行只读。缺年月且没有可靠上下文先追问。
3. **写入安全**：模型只能提出；可信 CLI 展示具体对象、旧值和新值，用户确认后才能授权。发票仍走 Prepare → Confirmation → 事务 Commit+Audit → 新连接 Readback。任务/偏好确认必须绑定本轮用户、企业、动作、目标、原始请求、具体内容与旧值；一次性、跨轮/身份/进程失效；不能由模型自己创建授权、填 `confirmed=true` 或绕过 Handler 鉴权。
4. **错误真实性**：`DENIED` ≠ `NO_DATA`；`NO_CHANGE` ≠ 新的业务更新；`UNKNOWN_OUTCOME` 先按 request_id 查询，**绝不盲重试写**；计划完成不等于任务完成。拒绝/失败不能变成成功，但也不得抹掉此前在本轮真实完成的操作。
5. **硬预算**：每用户轮次默认块长 3、至多 2 次续期，共 ≤9 次模型请求；≤12 次**实际进入 Handler**调用；≤1 次重规划。`requested_tool_calls` 是提案数，不作为 12 次 Handler 硬限。每个 Tool Call ID 必须恰好一个结果，包括被拒/预算跳过。不得为了方便适配模型改大预算或重置本轮计数。
6. **日志**：JSONL Trace 记录运行事实；SQLite 发票审计才是提交凭证。不能把模型文本/旧对话/Trace 声明当作已提交事实；Trace 故障不得改变 SQLite 业务结论。密钥、Token、私有 reasoning 和未脱敏真实业务内容不可写入可分享产物。

## 2. 开发预算与止损（Codex 必须遵守）

### 2.1 Token 与工程改动预算
- **只读取当前阶段相关文件**：先 `AGENTS.md`、对应契约节、S4-B 精确复现与关联函数/测试；不要每轮重复遍历全部仓库。全量测试只在已有清晰修改后进行。
- 每轮工作：① 选择 1～2 个可复现反例 → ② 最小补丁 → ③ 定向单测 → ④ 全量回归一次 → ⑤ diff/安全检查 → ⑥ 文档和 Git 提交。优先扩展既有测试文件；只有新职责足够独立时才加小模块。
- **同一故障最多两次针对性修复**：两次仍失败，记录 BLOCKED、根因证据、未解决风险，停止扩张。不要让无界自我反省、反复重构、跨模型复核或自动寻找方案消耗预算。
- 报告不要重复粘贴完整测试 stdout、整个源码或长篇思路；只给命令、数量、退出码、关键差异与证据路径。测试原始输出留本地忽略目录。
- 不以刻意缩短行数、单行拼接、冗余代理层、跨模块机械拆分来节省 Token。**可维护性优先于表面代码行数。**

### 2.2 真实 API 及余额管理（新规则）

- **4P-B 开始允许真实 API**：先通过确定性反例修复，再及时用真实自然语言与官方虚构 SQLite 做目标交互测试；不必等到 4P-E 才首次 live。4P-C 的 Thinking 协议修复仍必须在独立离线测试后通过真实多轮接口验证。
- 4P-D 对有已授权凭据的 Provider 做小规模真实 Tool Calling 冒烟；没有凭据的提供商标 `NOT_TESTED`，不得自动寻找或替换密钥。
- 4P-E 应覆盖**完整三场景与偏好 CRUD**的真实模型交互，不以预设「最多 10 次」导致半数场景无法测试；无实际执行的仍标 NOT_TESTED。
- 取消旧「4P-B 0 次」「C 6 次」「D 2 次」「E 10 次」「总计 18 次」硬封顶。真实请求次数是**必须计量的指标**，不是强迫用 Mock 代替真实场景的目标。
- 用户报告 DeepSeek 账户当前约 **¥50**；建议把自本次决策开始**累计可核实的额外账单支出达到约 ¥35**作为费用提醒线，尽量留约 ¥15 给最终演示。这里既不是程序自动止付，也不是服务商的余额查询；核账以官方后台为准，不能凭 Token 猜出精确费用。
- 每次真实调用记录 provider/model/profile（如有）、HTTP/异常类别、请求尝试数、成功/失败数、可获得的 prompt/completion/total_tokens、延迟、Tool Call 数；**usage 不可用/失败请求消耗未知要写 unknown**。原始 Key、reasoning、真实业务内容不提交 Git。
- **止损针对无信息重复**：同样 HTTP400 或格式故障连续两次复现无新增线索，先离线定位再重新调用；正常诊断、正常场景覆盖不应因次数过少被迫停止。严禁未经请求自动调用其他收费模型或反复改写已提交业务操作。
- **两种预算独立**：每个用户轮次的 `≤9 model_requests / ≤12 actual_tool_calls / ≤2 extensions / ≤1 replan` 属不可放宽的执行安全硬限，绝不因 API 账户余额而修改。

### 2.3 阶段止损
- 各阶段完成后必须**停止并回报**；不得自行进入下一阶段。若独立阶段暴露前置依赖问题，只允许做最低必要的前置兼容处理，并明确登记；不得以此开启全面重构。
- 验收允许 `PASS / FAIL / BLOCKED / NOT_TESTED`；环境缺 Key 不造假，API 失败不改写为业务错误，未经 live 的能力不能宣称实测通过。

## 3. GitHub 与代码治理（每个子阶段都执行）

1. 目标仓库 `knone32/Economy-guy`，约定集成分支 `main`。每段开始记录 `git rev-parse HEAD`、`git status --short`、`git remote -v`，核对是否有未提交改动和远端新提交。**如果用户已有未提交改动，先保护并报告；不得 checkout/reset/clean 覆盖。**
2. 在现有工程约定下**默认对 main 做小而独立的提交**（每个子阶段至少一个可解释 SHA），不强制增加多分支/PR 流程；若远端保护策略或用户显式要求分支，再使用短生命周期修复分支，不自行合并未经外部验收的 PR。
3. 修改前锁定基线 SHA；修改后运行定向测试与 `python -m unittest discover -s tests -q`（在 `finance_agent/`），运行 `test_architecture`；记录测试 SHA。只用虚构 fixtures 和临时 SQLite；绝不修改正式 `data/finance.db`。
4. 提交前 `git diff --check`、`git status`、`git diff`、`git diff --cached --stat`；**只显式 `git add` 本段相关文件**，不要盲目 `git add .`/`git add -A`。检查待提交文件和历史敏感信息；仓库禁止提交 `.env`、密钥、凭据、正式/测试运行 SQLite、原始 Trace、缓存、虚拟环境和大体积 artifacts。
5. Commit 命名建议：`fix(s4p-a): ...`、`fix(s4p-b): ...`、`fix(s4p-c): ...`、`feat(s4p-d): ...`、`test(s4p-e): ...`。每段报告 `base_sha`、`code_sha`、`report_sha`、变更文件及原因；若一提交同时包含代码与报告，明确它就是被测提交；**不能用测试前 SHA 代替最终代码 SHA**。
6. 无冲突时普通 `git push origin main`；**禁止 force-push、破坏性 reset/clean、改写历史和自动合并冲突**。远端已前进时先 `git fetch` 并检查差异；存在未知更改或冲突则停止并报告，不擅自 rebase/覆盖。推送后核对远程分支 HEAD 等于已提交 SHA。
7. 4P 的验收记录使用 `docs/verification/stage4/S4-P-A.md` ... `S4-P-E.md`，每份简短；最后在 `S4-P.md` 建立索引。**`AGENTS.md` 只做短项目地图/当前状态更新**，详细流程保留 `docs/flows/`。不要把本任务书整篇复制进去，不要每次修改所有文档。
8. GitHub 上的 CI 状态和本机运行结果分别记；没有 CI 时不得写“CI 已通过”。本阶段可以使用现有本地 unittest，**不强制新增 Actions 工作流**。

## 4. 执行顺序

`4P-A（已完成离线） → 4P-B（业务结果/任务推进 + 目标 live） → 4P-C（DeepSeek 多轮协议 + 真实协议复验） → 4P-D（Provider Profile/Trace + 可用模型冒烟） → 4P-E（全量 + 官方完整三场景 live）`

**说明**：4P-C 解决真实 live 多轮测试阻断；B 先修设计/业务路径，**允许真实 API 测不受已知协议问题阻断的路径**。如果 B 某个多轮场景仍因 DeepSeek HTTP400 无法继续，应标 `PROVIDER_BLOCKED / 待 4P-C/E 复验`，不得对数据库功能误判或提前宣告成功。

---

# 5. 分段 Codex 指令（一次只发送对应子阶段）

## Prompt · S4-P-A：自然语言管理入口、偏好 CRUD 与追问协议（已完成/历史留存）

你正在维护 `knone32/Economy-guy`，本轮**只执行 Stage 4P-A**。请先读取 `AGENTS.md`、`docs/ARCHITECTURE_CONTRACTS.md` §2/§5、`docs/verification/stage4/S4-B.md` 的 F01/F04 与 `app/agent.py`、`app/persistence.py`、`app/tool_registry.py`、`app/tasks.py`、`app/preferences.py`、`main.py` 相关函数和现有测试。先记录真实 HEAD/工作树；不重复阅读无关目录。

目标：修复 P01/P03/P06。**不能让模型自己给自己 ManagementTurn/Approval**。自然语言“记住偏好”“删除偏好”“记下后续用途待办”只能让模型输出**无执行权的候选提案**。Harness 先做只读参数/范围/权限预检、核对现有对象，随后可信 CLI 明确显示 `user/company/action/key或task_id/old/new/source_request`，用户精确确认后由可信层生成并消费一次性许可；进入新事务再鉴权、核对旧值/指纹并执行。保留现有 `/task`、`/preference` 显式入口作兼容和安全对照。

不得：把普通文本关键词识别当授权；`can_manage=True` 只因为模型调用了工具；模型自行回传 `confirmed=true`；降低修改/删除边界；把权限拒绝改为只读空值。偏好删除必须先核对真实 key/值，歧义时只追问。对非法 `missing_fields` 不能当作合法业务字段；允许窄范围、安全的协议修正/追问，失败就给出可信错误提示，无无限重试或虚构结果。

先新增失败反例，再实现最小改动。必测：普通任务/偏好创建提案、用户不确认零落库；正确确认后仅精确内容落库；错误企业、错误 key、错 value、过期旧值、跨轮/跨身份、一次性重复、取消全部拒绝；显式命令兼容；自然语言偏好删除及跨进程核验；非法追问字段不能越权。仅用 Mock + 临时 SQLite，**本轮禁止真实 API**。

完成后运行定向与 219 项基线全量回归（新增数量单独报告），仅提交本轮相关文件与 `S4-P-A.md`；常规 push `main` 并核对远端 SHA。输出变更、测试、仍待 live 验证项、SHA，然后**停止**。不进入 4P-B/C/D。

## Prompt · S4-P-B：权威结果呈现、查询完整性及任务推进

继续 `knone32/Economy-guy`，本轮**只执行 Stage 4P-B**。以 **4P-A 代码 `0c043151d24ab63394ca674516d711c86435f3ac`，报告 `7a9f32713e2a98054b9ee7f9aeda6d01452b2747`** 为参考基线，执行前以 Git 真实 HEAD 为准。读 `AGENTS.md`、`ARCHITECTURE_CONTRACTS` 对应章节、最新《项目总控总纲 v1.1》第 7/8/9 节、S4-B F02/F03，以及 `Agent.ask`、`responses.py`、`write_coordination.py`、`tasks.py`、`scheduler.py` 的直接关联函数和测试。

**预算策略修订**：不再禁止真实 API。先用离线回归定位/修复，再通过 DeepSeek 等已合法配置的真实模型，在官方虚构隔离库针对性验证 A2 汇总、P02 成功回执和 P05 当前缺项；收集实际 Tool Calling、trace_id、SQLite 核验、usage/延迟/错误，不把 Model 行为由 Mock 伪造。碰到已知 Thinking HTTP400 时保留 BLOCKED 证据，4P-C 修复后补测，不反复无进展调用。

解决 P02/P04/P05：
1. 当工具已经真正 `SUCCESS`/管理写入经可信确认成功时，后续重复调用得到 `NO_PROGRESS`/预算停止，最终对用户仍应**分别说明先前已完成的权威事实、当前未完成项目和本轮停止原因**；不能把后续拒绝改称成功，也不能凭模型文本称已保存。对 `COMMITTED` 只能采用真实 SQLite 审计+回读；任务/偏好据当前持久服务返回值。
2. 对原 A2“帮我看甲企业发票银行收支”→补“2026 年 9 月”，确保模型被明确引导选择适当汇总工具，并最终呈现发票价税合计/张数、银行收入和支出/条数及 R001 规则。设计仅做**通用工具说明、目标证据完整性检查/权威展示**，不能写“匹配某些中文关键词就固定回答”的假 Agent。
3. 成功修改一张用途后，从**当前 SQLite+RuleDecision** 计算缺失数和剩余对象，展示给用户；长期任务依然由 Task Manager 保存，不能引入 task_items/DAG/第二状态权威；不因缺失数减少一张就声称全部完成。若真正全部完成，必须有当前证据并遵循状态机及确认边界。
4. 针对已有 B2/C4 成功证据不退化，保留原 `request_id`/审计/回读以及 Scheduler 硬限和 Tool Call 配对。慎重处理“同轮工具成功 + 后续模型失败”的用户可见呈现，不因直接格式化结果而越权。

新增 S4-B 同形状 Mock/SQLite 反例：重复查询、重复管理写入、NO_PROGRESS 后已保存证据保留、真实停止原因、C001 九月正确汇总、写后缺失 5→4 / 重启再次查询、U002 越权不可泄漏。

**真实 API 目标用例**：使用原始自然语言而不是告诉模型明确调用哪个工具；至少测试 A2 的自然追问→补月份→完整汇总（金额/计数/R001）和一个已知成功结果后重复工具请求的用户呈现；尝试当前缺项展示时若被旧 Thinking 协议阻断，记录与业务无关的 PROVIDER_BLOCKED。记录每次实际模型/工具次数和 SQLite 查询结果，费用只按官方账单核实。

定向测试→全量回归→安全 diff→提交 `S4-P-B.md` 和相关源码→push `main` 核验 SHA。报告将 Mock/真实 API/SQLite 和失败项分开。阻塞于 DeepSeek HTTP400 的 live 部分注明 **待 4P-C/E**。完成即停止。

## Prompt · S4-P-C：DeepSeek Thinking 多轮协议兼容

继续 `knone32/Economy-guy`，本轮**只执行 Stage 4P-C**；先读 S4-B F02（原始错误 `The reasoning_content in the thinking mode must be passed back to the API.`）、`app/agent.py::live_model/Agent.ask/model_messages`、`app/context.py`、`app/trace.py`、相关 tests。当前代码存在过滤 assistant 到 `role/content/tool_calls` 而丢弃服务商 reasoning 字段的问题。

修复 P07：仅在提供商协议要求时保留并回传必要的 `reasoning_content` 或等效字段；保留 Tool Call ID/结果配对、原 assistant 工具请求顺序及 Context 整轮裁剪。该思考字段属于**会话私有协议状态**，不是用户业务证据、长期记忆或对话指令；不得在可分享 Trace、普通模型回答、SQLite、Git 或跨 Provider 会话中暴露。对不支持此字段的标准兼容接口不得盲发。先核对当前服务商官方文档再确定最小传输形状，不扩展 Anthropic 原生协议或 Responses API。

优先离线测试：thinking on 多轮工具、同轮多工具、旧历史裁剪、thinking off/普通 Provider、模型回复缺必要字段、异常 API 安全停止、Trace 中无原始思考内容；旧 219 项与 A/B 新增测试不能退化。

离线测试绿后，用当前合法配置的 DeepSeek 做**足以确定协议是否正确的真实多轮测试**：思考模式工具→结果→同会话新问题→工具或最终回答，必要时补测 Commit 后再次查询剩余任务；只用隔离虚构库。**不沿用 6 次请求硬限**；同类失败两次无新诊断则转离线修复，避免重复消耗。缺凭据则 BLOCKED，不改用 Mock 冒充 live。记录真实请求数、HTTP 类别、usage/延迟（如可取得），费用以账单为准。提交 `S4-P-C.md`、代码和测试；push main 验证 SHA；完成停止。

## Prompt · S4-P-D：多 Profile 配置、可信切换与日志语义

继续 `knone32/Economy-guy`，本轮**只执行 Stage 4P-D**。先核对 4P-C 的协议测试和 SHA，再读当前 `live_model/main.py/trace.py/scheduler.py`、S4-B F05 和 `AGENTS.md`。修 P08/P09/P10，**不要创建大型适配器框架**。

最小方案：Python 3.11 `tomllib` 读取无密钥 `config/model_profiles.toml`：Profile 至少记录 `provider/model/base_url/api_key_env`，可选可验证的厂商专用思考参数。实现 `python main.py profiles list/check` 和 `chat --profile <name>`；兼容旧完整 `OPENAI_API_KEY/OPENAI_BASE_URL/OPENAI_MODEL` 或 `KEY/BASE_URL/MODEL` 运行入口。配置优先级明确写进 README，混合/缺失配置必须报错，不能误用另一 Provider Key。Profile 仅存环境变量**名称**；密钥实际值不写配置、Trace、异常或 stdout。

允许在可信 CLI **完成当前轮次且无未确认草稿/管理提案**时执行 `/provider use <profile>`：安全地结束旧临时 Agent、清除旧协议 thinking 历史/草稿/审批/工具待完成项，再创建新 Agent；SQLite 任务、偏好、业务值保留，重新鉴权与查库。若实现运行中切换会引入复杂状态同步，则先实现“明确退出并用 `--profile` 启动新进程”的安全路径，记录 P10 的交互切换为 `NOT_IMPLEMENTED`，不能用不安全的原地切换凑完整。

`app/scheduler.py` 无 schedule 时工具进展不得记作虚假的 `schedule.progress`；使用语义正确的工具进展事件或只在有 schedule 时发对应事件。保留原 `progress_count`/预算快照，不因改日志改变硬限和行为。Trace 可加入 `profile/provider/model` 及真实 usage 可用时的计数、错误分类，但**不记录原始思考、密钥及不必要的额外全文日志**；不建动态成本估算器或监控平台。

新增配置优先级/缺失 Key/恶意配置 URL/切换安全/跨 Provider 消息隔离/旧兼容/日志事件语义测试。离线先过，再针对**实际有凭据的每个已验证 Provider**做必要的真实 Tool Calling 冒烟；没有凭据标 NOT_TESTED，不自动换到别人的付费账户。**取消 0/2 次旧硬限**，按实际调用和账单观察执行，重复无进展停止。定向+全量+安全 diff，报告 `S4-P-D.md`；提交并 push main，核实远端 SHA；停止。

## Prompt · S4-P-E：封板、回归与有限 live 复验

继续 `knone32/Economy-guy`，本轮**只执行 Stage 4P-E**，以 A/B/C/D 已提交的当前 HEAD 为代码基线；先读四段验收报告与 S4-B 精确失败 Trace ID，不重构任何模块。

1. 使用干净隔离环境/官方虚构 fixtures 执行 Stage 3/S4-A 既有 **219 项**及 4P 新增所有测试；逐项记录实际总数/FAIL/ERROR/SKIP/退出码，且不要重复统计定向子集。
2. 重点检查安全：无授权不保存、错提案拒绝、跨轮/身份旧确认拒绝、发票 Commit+审计+回读、权限/联合键/规则边界、Trace 故障不影响已提交事务。
3. 以**真实 DeepSeek 或已配置的合法模型**执行官方完整三场景并核对实际持久业务：A2 连续追问后汇总/R001；B2 可信确认保存后同会话继续；C2 普通话生成待确认任务并保存、重启恢复；C4 补一张后再次获得剩余缺项；偏好自然增/查/改/删、隔离和跨进程核验。**取消 10 次请求硬限**，但按实际 usage/延迟/失败类别记账并遵守无进展止损；不得把未执行的项目写成 PASS。
4. 校验运行日志：`model_requests ≤9`、`actual_tool_calls ≤12`、`extensions ≤2`、`replans ≤1`、ToolCall ID 对齐、模型真实输入/上下文来源、规则版本、审计 request_id、stop_reason、续期实际有没有发生；未观测项注明 `NOT_OBSERVED`。
5. 对可切换模型 Profile，至少离线确认配置和历史隔离；只有已合法配置真实凭据的 Provider 才允许 live 断言。禁止自动 fallback 到另一个付费服务。
6. 若发现 P0 回归：先登记缺陷，最多两轮局部修复并复测；如果超过预算/超出最小范围，停止并报告 BLOCKED，保留已有效证据。

输出 `docs/verification/stage4/S4-P-E.md` 和 `S4-P.md` 索引，列每项 `PASS/FAIL/BLOCKED/NOT_TESTED`、执行源码 SHA、报告 SHA、API 尝试数、可取得的实际 usage、证据路径与尚未解决问题；与先前 `S4-B.md` 区分，**不能悄悄改写旧报告**。必要文档同步后 commit/push `main`，核对远端 HEAD，结束；不要自行开展 S4-C/D 或完整新一轮 41 场景实测。

---

## 6. 每阶段给 ChatGPT 的最小验收回执

```text
Stage: S4-P-[A/B/C/D/E]
Base SHA:
Tested code SHA:
Report SHA:
Changed files:
Targeted tests: <n passed>/<n run>, failures/errors/skips, exit code
Full tests: <n passed>/<n run>, failures/errors/skips, exit code
Live provider / model: <none | actual>
Live API attempts this stage / total across 4P:
S4-B original failure IDs now: PASS / FAIL / BLOCKED / NOT_TESTED
Safety checks / business SQLite facts:
Trace & model_requests/requested_tool_calls/actual_tool_calls/stop_reason:
Open issues and evidence paths:
Git remote HEAD verified: yes/no
Next stage suggested (do not execute):
```

## 7. 用户与 ChatGPT 的阶段门禁

- **A 通过条件**：天然语言提案与显式入口都有可信确认，错误对象/内容无写入；偏好 CRUD 形成可执行闭环；Mock+SQLite 验收，无 API。
- **B 通过条件**：查询完整、成功证据保留、任务剩余项以实时 SQLite 呈现；与 thinking 协议阻断相关的 live 尚待复验不虚报。
- **C 通过条件**：离线正确保留必要 provider 协议字段且不泄露；DeepSeek 最小多轮 live 不再因缺 reasoning 400（有凭据且预算允许时）。
- **D 通过条件**：多 Profile 配置可靠、密钥隔离、旧入口可用、切换安全、Trace 事件准确；可选 CLI 原地切换不得以不安全设计凑功能。
- **E 通过条件**：当前 SHA 的全量回归与**完整官方三场景真实 API + 可信确认 + SQLite 权威检查**有可核对证据；偏好 CRUD 和重要旧失败路径也有 live 记录；S4-B P0 失败项已解决或明确阻塞；只在实际通过后建议进入 S4-BR/S4-C。**报告提交成功不代表业务验收自动全绿。**

**计划结束。**
