# 财税 Agent Harness | 架构与接口契约（v2，2026-11-05）

> 本文为实现目标，不代表当前代码已经具备相应功能。以官方赛题 1.1.0 及真实测试结果为最终验收依据。初赛只实现必需的最小闭环，GUI 延后。

## §1 状态所有权、依赖方向与实现范围

**单一调用链**：CLI / Session → Context Builder → 单一 LLM Agent Loop → Tool Registry/Execution Guard → Business Services（Authorization、Invoice、Rules、Tasks、Preferences）→ SQLite。Trace 监听真实过程；CLI 的最终确认可直接调用受控业务入口，不必绕 LLM。

| 对象 | 权威所有者 | 生命周期 | 不可做的事 |
|---|---|---|---|
| 当前身份、企业访问权 | Session + Authorization | 当前会话/每次调用重新查权 | 接受 LLM 自报身份或授权 |
| 发票/流水金额和字段 | SQLite 业务表 | 持久化 | 把 Excel/旧聊天当当前数据 |
| 规则正文、版本、执行参数 | Rule Store / Resolver | 持久化 | 模型自行推导规则门槛 |
| 长期未完成任务 | Task Manager | 跨对话、跨进程 | 用聊天摘要替代状态或确认 |
| 用户明确长期偏好 | Preference Store | 持久化，支持 CRUD | 任意聊天内容自动当偏好 |
| 当前对话焦点、历史列表锚点 | Context Builder + 会话存储 | 当前/必要锚点持久化 | 把引用当最新业务值 |
| 本轮 Schedule、预算、Tool Call | Agent Runtime | 每条用户消息；审计摘要可留存 | 把工作计划当业务授权 |
| 已提交业务操作 | SQLite Audit + 发票表 | 持久化 | 用模型声称或 JSONL 判断成功 |

**关键区分**：Task Manager 保存“用户要完成什么”；Task Scheduler 保存“本轮如何推进”；Context Manager 负责“当前语言中的指代如何对应有证据的对象”。三个模块不能复制一个可变权威任务状态。

**必须保留的扩展边界**：任务独立 `task_id`；初赛单用户×单企业最多 1 个未完成任务由 `TaskPolicy` 检查，并用 SQLite 部分唯一索引防并发；以后支持同企业多任务需迁移/移除该索引并扩展选择逻辑，**不是仅修改一个配置值就完成**。`task_items`、任务 DAG 与优先级引擎暂不做。

## §2 Agent Loop、工具和错误协议

模型自主理解用户需求并决定回答、追问、选择工具、结束；不写关键词路由器。默认 Fast Path 直接 Tool Calling；对真正多步依赖或恢复任务可使用可选短计划，**不在每个模型循环强制规划**。模型无须输出内部思维链。

**推荐初赛模型可见业务工具**（按阶段注册；仅作清晰接口契约，内部 Python 函数可复用）：
- `get_finance_summary(company_id, year, month)` → 发票价税合计、银行收入、支出、分别计数、R001 名称/版本；
- `list_invoices(company_id, year, month)`、`get_invoice(company_id, invoice_no)`；
- `list_bank_transactions(company_id, year, month)`；
- `check_missing_purpose(company_id, year, month)` → RuleResolver + 当前数据库返回必填缺失及规则依据；
- `get_applicable_rules(company_id, rule_type, business_date)` → 已验证适用规则；
- `prepare_invoice_update(company_id, invoice_no, field, new_value)` → 仅生成待确认操作；
- Stage 3 按需提供 `list_tasks` / 受控 `manage_task` / `manage_preference`，不能借管理接口绕过写入确认或鉴权。

**不提供**：任意 SQL、直接 Commit、密码/权限管理、规则发布/停用、审计修改。`user_id`/`confirmed` 永远不在模型工具参数内；使用统一 Tool Registry 映射到现有业务服务。工具在模型侧不可见不等于真正被授权，执行 Handler 必须再鉴权。

**工具结果**统一 `ok/status/data/evidence/error`，至少区分：`SUCCESS`、`NO_DATA`、`INVALID_ARGUMENTS`、`AMBIGUOUS`、`NOT_FOUND`、`DENIED`、`CONFLICT`、`WAITING_CONFIRMATION`、`COMMITTED`、`NO_CHANGE`、`UNKNOWN_OUTCOME`。有权限但无记录为零+显式空集；权限拒绝不可泄露记录是否存在。LLM 可有限修正参数错误；DENIED 不能换参数循环绕权，UNKNOWN_OUTCOME 先查业务审计。

**循环协议**：一次模型响应可返回多个 tool_calls；记录原始 assistant tool_calls，并按 `tool_call_id` 给每个请求返回结果（包括校验失败/额度拒绝），再给模型下一轮消息。限制模型请求次数与工具次数分别计数；到最后一次模型调用时如仍产出工具调用，必须安全处理并能由 Harness 输出真实收尾结果，尤其不允许自动执行需再确认的写入。Mock 和 live 使用同一 Loop，真实 API 需要独立 E2E 证明。

## §3 数据库、导入、精确定位和写入事务

**Excel** 为只读种子，**SQLite** 为当前业务权威。第一次初始化先校验输入，再用临时数据库建表并导入、核对，最后仅在目标不存在时原子落地；已有库默认拒绝覆盖。升级表结构通过迁移，不允许 `unlink()` 后重导。导入使用显式 SQL 列表，不永久写死仅 C001/C002 企业行，不把异常数据静默吞掉。测试和演示库隔离。

**发票定位**必须 `(company_id, invoice_no)` 联合主键，旧列表/对话中模糊对象先由引用解析器生成候选，取得唯一且明确的业务标识后才能 Prepare。限制 `purpose/remark`；销售方、项目、金额等和银行记录只读。

**Prepare**：本轮有明确修改意图，确认目标、字段、新值，读取当前旧值及版本/哈希，创建操作草稿与稳定 `request_id`。`confirmed` 只能由可信 UI/CLI 针对该草稿产生，并与发票/字段/新值绑定；跨会话不继承。

**Commit（受控 Python 入口，不给模型）**：事务内重查授权与当前值（可用旧值条件更新或 `revision`），核对同一 `request_id` 及其操作内容指纹；仅允许目标字段更新；写入成功审计和相应可原子提交的任务进度；同一事务 COMMIT。提交后重新打开连接回读，分别报告 COMMITTED、NO_CHANGE、CONFLICT、DENIED、UNKNOWN_OUTCOME。审计失败则整个事务回滚。Commit 结果不明时**先按 request_id 查询审计，不盲目二次写入**；若后来其他操作改了值，区分“本次曾提交”和“当前值已变化”。取消任务不逆转已成功提交发票。

**审计两层**：SQLite 成功审计和业务变更同事务，存 `request_id`、可信 actor、company、invoice、field、old/new、commit_at；运行轨迹 JSONL 按 `trace_id` 记录真实模型输入（按配置脱敏）、取用的上下文、规则、工具调用及结果、budget、最终回复。Task/Trace/Operation/Tool Call 使用 `task_id/trace_id/request_id/tool_call_id` 关联；普通失败事件不能伪装成成功审计。

## §4 规则 KB、版本与执行事实

初赛最小规则存储建议：`rule_id, version, name, company_scope, effective_from, status, rule_type, params_json, content`；`(rule_id,version)` 唯一；可用一个 SQLite 表处理 C001/C002 和全局规则。R001/R004 跨企业生效；R002 v1.0 停用保留，R002 v2.0 C001 2026-09 全部必填；R003 v1.0 C002 金额 >=100000 分必填；仅检查 2026-09 用途。纯空白/空格为未填，备注不能代替用途。禁止推断发票已付款或根据销售方猜用途。

规则管理由**独立可信管理员入口**经 `rule.manage` 权限进行；企业发票 modify 不等于可改规则。初始化导入幂等，同号同版不同内容拒绝冲突；业务含义变化新建版本，旧版留存，停用不物理删除。适用性解析按规则类型、企业、业务日期、有效状态；无唯一有效规则时返回 NO_APPLICABLE_RULE/RULE_CONFLICT，不自作主张选最高版本。

**单一 RuleDecision** 同时提供给业务判定、工具证据和 LLM 引用；正文是解释依据，`params_json` 是执行参数，两者必须一致。规则管理员不得借改知识库文本绕过发票字段白名单或银行只读的系统边界。未完成任务恢复时重查适用规则与当前发票。

## §5 Task、Context、Reference Resolver、Scheduler

### 持久化任务
- 独立 `task_id/user_id/company_id/task_type/year/month/status/context_json/created_at/updated_at`。状态建议 `ACTIVE/WAITING_USER/PAUSED/COMPLETED/CANCELLED`；前三者占用初赛单未完成名额。SQLite 层并发保护配合 TaskPolicy。
- 用户**明确存在后续事项**时创建；一次性查询通常不创建。切换查询话题只改变焦点，不自动取消或暂停。明确暂停则 PAUSED；更正原任务更新该任务；新任务冲突应让用户选择保留或取消旧任务并替换，不能悄悄覆盖。完成依据可验证的业务目标和当前 DB，不由 LLM 自述；取消不回滚已提交业务数据。
- 跨会话恢复：先可信身份/任务归属与企业权限 → 恢复企业月份及意图 → 重新查规则和当前业务数据 → 决定下一步。多个企业都有候选待办时不能猜企业。旧授权、旧准备草稿不得直接自动 Commit。

### 上下文与引用解析
- ContextBuilder 只选择必要的最近消息、关联任务、明确长期偏好、适用规则与上轮工具证据，限制长度；不默认所有历史压进 Prompt。用户明确更正/删除偏好时修改持久化 Preference Store，保证跨用户/企业隔离。
- 历史显示发票列表时保存**实际展示顺序**和来源锚点（`reference_id, user_id, company_id, task_id?, message_id/时间, ordered_invoice_keys`）。模型把“昨天第二张”等解析成时间/序数/任务等**线索**，Harness 依据锚点匹配并按当前权限过滤，不接受模型编造的历史发票编号；多个可能列表、证据不足时返回 AMBIGUOUS/NOT_FOUND 请用户确认。找到编号之后仍重新读库；历史引用不等于当前字段值和写入授权。
- 长对话摘要是加分扩展：P0 先保留结构化关键任务/偏好与选择性输入，后续可以实现原始对话保留+触发摘要+更正后失效校验，不冒充已落地。

### 本轮 Task Schedule 与预算
- Schedule 是**每条用户消息的临时粗粒度执行路线**，不是长期 Todo；`goal, steps[{step_id, action, depends_on, status}], stop_condition, revision`。只有必要时模型提出短计划；普通查询直接 Tool Calling，不强迫每轮输出完整计划。模型计划只能建议工具/依赖，Harness 验证其存在、授权、是否与目标相关；不能让计划自动放大权限。
- 真实工具结果、审计、任务变化构成进度证据；仅模型说“完成”不算。SQL、鉴权、审计、回读等内部确定性步骤不应拆成每步一次 LLM。等待用户/确认为停止条件；实际完成直接停止。
- **固定增量预算**：每块 3 次模型请求，每条用户消息硬上限 9 次模型请求/12 次工具请求，最多一次显式重规划，参数可配置。达到软限时 Harness 用真实新证据/合法剩余依赖/无重复停滞等条件决定是否续 3 次；没有进展不能无限续，模型不得给自己授权。若计划失效、出现新依赖，可让**同一个模型**有限次分析剩余路线；已有计划不强制重复输出。
- `BudgetPolicy.initial_budget(schedule)=3` 与 `extension_budget(schedule,progress)=3` 作为预留接口，初赛不创建、查询预算估算表，也不增加 Planner Agent。单轮不同于持久化跨日任务预算；预算不足时 Harness 必须根据真实状态安全收尾，不宣称未完成操作成功。

## §6 验收、日志和交付原则

**官方基础**：三场景共享 Agent Loop；模型自主追问、工具与结束；规则 KB 导入/查找/更新/停用；任务跨会话；长期明确偏好 CRUD；按需上下文；可追踪真实输入/工具/依据；修改后真实回读。

**每层测试**：① Python 确定性单测：金额、权限、规则版本、Excel 安全初始化、发票修改事务审计、幂等冲突、任务隔离；② Mock Agent：多个工具调用 ID、非法 JSON、预算、API 故障与拒绝；③ 真实模型 E2E：自然语言追问/更正、查询、确认修改、任务恢复。Mock 不能证明模型真实理解。

**具体边界用例**：U002 不能读 C002 或修改 C001；C001/C002 同号不串；C002 恰好 1000 元边界；R002 v1.0 停用且 C001 9 月按 v2.0 全必填；无记录不是无权限；未确认不写；审计写入失败回滚；同 request_id 重试不二次修改；确认后发票内容变更返回冲突；重启后重新授权/查库；更正月份不使用旧数据；LLM 错称已保存时被真实状态纠正。

**可观测**：至少事件 `turn.started/context.selected/llm.request/llm.response/tool.requested/tool.completed/schedule.updated/budget.extended/turn.finished`；Mock/live、实际脱敏模型输入、规则证据和工具执行须能联结。日志不可含密钥；不能用 JSONL 缺失推断业务事务失败。

**提交**：README 可从干净环境执行，真实数据与测试 DB 隔离；2–3 页设计说明、关键真实日志、≤5 分钟演示，三核心场景最优先；未完成或只有设计的能力如实标注。额外分：长对话摘要与最近 N 轮 vs 选择性上下文的准确率/耗时/Token A/B，仅在 P0 真正跑通后尝试。
