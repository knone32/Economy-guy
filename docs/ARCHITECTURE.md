# 当前实际架构 Stage 3C

本文件记录实际实现；ARCHITECTURE_CONTRACTS.md仍是目标契约。代码位于finance_agent/，只有app.agent.Agent.ask一个模型循环。

| 模块 | 实际职责与状态所有者 |
| --- | --- |
| main.py | argparse、模拟用户、关联连续修改、最终确认交互；不计算业务金额 |
| app/agent.py | 模型调用/有界循环/消息配对；保留Agent与handle_tool兼容Facade；持有当前会话消息 |
| app/context.py | ContextBuilder选择、限长及焦点更正；reference_hint仅解析有限序数线索；无任务/偏好权威副本 |
| app/scheduler.py | BudgetPolicy固定块长/硬限；TurnExecution独占本轮计划、依赖进度、重复检测、请求/执行计数与停止原因；不持久化任务 |
| app/references.py | 唯一SQLite展示锚点存储、加法迁移和resolve_reference；只存有序联合键，不存金额、用途或确认 |
| app/tool_registry.py | 生产/教学Schema、严格JSON字段类型校验、分发及执行时鉴权 |
| app/responses.py | 校验最终信封；按真实工具结果生成查询/管理答复，按缺失字段追问，不以模型文字证明操作状态 |
| app/write_coordination.py | WriteCoordinator拥有pending、UpdateSession、receipt、可信events；无持久任务 |
| app/trace.py | write_trace/redact记录脱敏事件，不决定业务成功 |
| app/updates.py | Prepare/Confirm/Commit/inspect_request；事务写入、成功审计和新连接回读 |
| app/rules.py | 版本管理与唯一RuleDecision；规则引用和判定共享该证据 |
| app/tasks.py | TaskPolicy与任务转换；SQLite tasks是唯一持久状态，恢复/完成重查当前业务 |
| app/preferences.py | 用户×企业明确偏好CRUD；SQLite preferences为唯一持久状态 |
| app/persistence.py | ManagementIntent/ManagementTurn、内容与旧值绑定的一次性ManagementApproval、结果协议；不含LLM消息格式 |
| app/stage3_schema.py | 任务/偏好加法迁移与部分唯一索引 |
| app/finance.py、queries.py、permissions.py | 精确统计、当前数据库读取、授权 |
| app/database.py、stage2_schema.py、importer.py | SQLite与加法迁移、安全首次种子导入 |

依赖方向：CLI → Agent → ContextBuilder / Registry / WriteCoordinator / TurnExecution → 业务服务 → SQLite。Registry校验计划工具/范围/权限，TurnExecution只接收执行结果与授权回调，不执行业务。ContextBuilder只调用任务、偏好和引用服务读取/维护相应来源，不接管它们的状态。Trace和回复解析无业务权力。业务层不得反向导入context/scheduler等运行层；标准库AST测试检查显式导入，无完整动态依赖平台。

业务字段、规则版本、成功审计的权威存储均为SQLite。pending是当前Session待补充意图；draft是本轮精确目标草稿；confirmation是绑定指纹的本轮可信确认。三者不同，均不跨进程继承。WriteCoordinator.events只记录历史操作事实，不能替代SQLite当前值。

上下文：Agent.messages保留用户、真实模型响应及实际工具结果，模型请求前由ContextBuilder.build选择完整近期轮次。最终模型JSON只保留一次；程序收尾消息使用name=harness_output。context_data提供带来源及范围的任务/偏好/锚点数据，reference_data为本轮重新鉴权的引用重查；harness_history是source=trusted_cli、historical=true的历史回执投影，保留event_id/turn_id/request_id。它们均为assistant数据，不进入user/system角色、不编造Tool Call，也不授予权限。模型不能自行设置name。当前值须重查SQLite。

已实现Stage 0–2加固、Stage 3A任务/偏好、Stage 3B轻量Context/展示引用解析及Stage 3C最小单轮计划/分块预算。未实现通用调度引擎、完整历史检索/摘要、GUI。静态检查和Mock不能证明真实理解或抵抗所有Prompt注入。

执行能力：生产Schema与实际执行许可分别检查。Agent保存初始能力集，调用时再与当前Schema取交集传给Handler；Handler默认仅允许生产工具，Python可信内部调用需显式能力集。教学add/旧汇总不能仅凭内部REGISTRY存在而在生产执行。每次读写仍独立鉴权。

保证边界：正式入口不展示任何模型information.text；财务信息由本轮真实工具证据生成，无证据降级为未核实。追问仅使用严格校验的missing_fields生成自然问题，不执行或转述text里的任意状态声明。模型仍决定问题理解、缺失字段与工具调用；但它可能选错企业/月或提错问题，展示的数据字段也可能含不可信指令文本。因此不声称实现任意自然语言的绝对语义真实性判断或彻底解决Prompt注入。业务数据按数据展示，不能提升角色、权限或产生确认。真实成功仅由审计、request_id、目标、指纹、旧/新值及回读匹配的回执表达。

Stage 2.5.2补充：responses.parse_final允许general说明类型。非修改轮、无查询工具结果且无数字业务范围时，模型自然文本可以作为明确标记的未核实一般说明展示，不是数据库/执行事实；模型分类不是真实性证明。其他information仍按执行证据展示。Agent.last_response.category记录一般说明、追问、查询、操作或未核实类别，operation_receipt独立保持权威状态。可能存在一般说明误分类或语义错误，不宣称任意自然语言真实性保证。

responses.explicit_scope提取明确编号/数字年月；Stage 3B选择器还识别官方企业简称，将明确范围传给Registry。Handler先鉴权再比较，冲突返回SCOPE_MISMATCH，无结果泄露。查询证据包含实际scope/source/rule，render_information逐个标注；get_invoice从当前日期补年月。跨轮只支持有展示锚点的有限引用，不支持任意中文历史时间表达。范围约束不是修改授权。

Stage 2.5.3：explicit_scope增加发票号提取；include_update_aliases=True仅为写目标支持官方两个企业简称。WriteCoordinator.pending.scope拥有当前意图的明确目标，连续补充只补缺失字段，不把不同值并集合；冲突标记保留至重新/edit。UpdateSession.expected_scope是该意图本轮约束的快照引用，不是第二个持久状态存储。begin_turn照常清除草稿和确认。

Prepare分发不再绕过范围：Registry从可信Session或用户原始要求取得目标，传至updates.prepare_invoice_update；服务先鉴权、再合并核对Session与调用方约束。SCOPE_MISMATCH/AMBIGUOUS均不创建草稿；拒绝不泄露业务值。业务层不导入responses或Agent，范围解析仍在现有运行层，业务服务只检查显式约束字典。底层可信Python调用允许不传范围以保留原API；模型入口则必须派生完整唯一目标。

Stage 2.5.3规则查询在Handler鉴权后校验日期并比较年月，原版本记录未改变。Stage 3A仅新增下述Task/Preference Store，没有新Loop、完整Reference Resolver或调度。

Stage 3A：Task Manager限于tasks.py的一个缺失用途任务类型、单用户企业名额与状态转换，不是通用引擎。WriteCoordinator仍只拥有短期修改意图、草稿/确认，不复制持久task。任务与偏好不写发票，取消不回滚invoice_audit。ManagementIntent由可信CLI固定actor/domain/action；服务在写事务内再次鉴权。Registry释放预检只读事务，再由业务服务独立事务处理，避免自身读锁阻塞提交。

Stage 3验收补丁：actor/domain/action本身不再足以授权模型保存具体内容。Agent持有本轮ManagementTurn，Registry只接受该模型会话上下文；tasks/preferences在写入前经persistence.require_management_confirmation返回具体提案及旧对象。可信CLI回调明确确认后，confirm_management形成精确绑定的一次性许可；服务新事务再次校验用户/企业、参数指纹与旧值。取消、跨轮、身份变化或内容/目标错配不写库；直接argparse管理参数仍为可信输入，兼容直接业务API。发票Prepare/Commit、Context、Scheduler实现均未改。真实调用链见flows/tasks-preferences.md。

恢复走list_tasks/manage_task(resume)，读取自己的持久记录并重新check_missing_purpose；偏好get/list作为数据，不提升为system。Stage 3B按唯一企业及明确年月选择未完成任务和该企业显式偏好；重启可恢复必要展示锚点，不自动恢复历史聊天、旧草稿/确认。独立子进程恢复测试见tests/test_stage3a.py和test_stage3b.py，调用链见flows/tasks-preferences.md和flows/context-reference.md。

Stage 3B限长单位为ensure_ascii=False序列化消息的字符数（默认48000，可配置，不是token估算；工具Schema另计）。固定system和本轮用户/完整工具交换为必需部分，超限停止；附加数据和历史轮次按预算选择/整段丢弃，无摘要模型。Trace记录来源、范围、字符数、遗漏及裁剪原因，并记录最终实际model_input。Agent.messages保留会话记录，模型请求不会无限拼接它。

reference_anchors经显式migrate-stage3b创建。只有正式信息渲染真实展示列表/对象后保存有序联合键及display_id、owner、scope、source、时间；教学自由文本和未展示工具结果不建锚点。最新一次展示有多个列表时不选默认列表，可由明确企业/anchor消歧。解析后检查当前权限、联合键及当前日期并重读字段；找不到/序号错误/证据不足时AMBIGUOUS或NOT_FOUND，不用历史字段充当当前值。公司/月/目标冲突、可信任务切换及取消失效旧焦点和引用，不更改任务事实。元数据失效失败时本会话阻断引用；底层存储故障时跨重启无法承诺该失败的失效动作已持久化，须重新展示/明确目标。

Trace是可选JSONL可观测性，不是SQLite成功审计。运行层捕获日志OSError，标记trace_degraded并以不含路径/异常原文的stderr告警；即使stderr本身不可写，回执仍标记降级。已核实提交不因日志故障改为失败，不盲重写；提交本身或回读结果不明仍为UNKNOWN_OUTCOME。

Stage 3C每次Agent.ask新建TurnExecution，长期tasks表、WriteCoordinator和SQLite事实不归它所有。简单查询没有计划或额外规划请求。真正依赖链由同一模型按需set_schedule；恢复任务在真实manage_task(resume)处创建一个恢复步骤，不拆SQL/规则检查。模型只能给目标/工具参数约束/前序依赖/停止描述，不能给status。Registry严格检查嵌套字段、可见工具、真实企业权限、已知目标范围和本轮可信管理/Prepare意图。计划只是路线，不能验证任意自然语言目标的全部语义；DONE仅表示匹配的实际工具步骤已成功/无数据，不表示长期任务或发票已提交。

BudgetPolicy默认3次一块，取得真实新工具证据且有合法就绪步骤时续3次，至多两次；每条消息硬限9次模型、12次实际Handler调用、1次显式重规划。可配置减少硬限和调整块长，不能通过参数突破上述上限。续期时重新检查当前工具能力、企业权限及本轮写入意图。NO_CHANGE不购买续期；重复工具名+标准化参数直接拒绝重执行；无计划不凭一串无界查询续期。计划/重规划本身不计业务进展。

计数区分requested_tool_calls（模型提出，含跳过）与actual_tool_calls（实际进入Handler，含参数校验失败及set_schedule控制调用）；被运行层拒绝的重复/超限/停止后调用不计实际次数。多call始终逐ID配对；第一个停止原因保留，后续调用DENIED且不执行。预算/错误停止仍展示实际证据，不采用模型完成声称。WAITING_CONFIRMATION使计划/对应步骤等待用户，不能自动Commit；后续CLI提交仍以原审计/回读回执为准，不由计划证明。

运行状态在Agent.last_response.execution及Trace budget/budget.extended/schedule.* /execution.stopped/turn.finished中可查。ContextBuilder按上限投影harness_schedule为assistant数据，不能获得system权限。计划每轮重建，不跨进程恢复；持久任务恢复继续由Task Manager负责。实际链路与测试见flows/schedule-budget.md。
