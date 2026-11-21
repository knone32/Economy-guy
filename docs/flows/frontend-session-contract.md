# 前端会话接口草案

依据：bcd17ea 的现有 Agent、WriteCoordinator、SessionStore、ReferenceResolver 和 ConversationUI。此文件是待接入契约，不代表已存在 Dot/DSH、Chat 前端、HTTP 服务或生产认证。原业务主干验收先完成；本草案不新增执行 Loop、状态机或持久存储。

## 状态归属

| 信息 | 唯一依据 | 前端职责 |
| --- | --- | --- |
| 当前有效业务要求 | Agent 的 BusinessRequest，附用户原话来源及修订 | 展示范围、指标与未决项；不从 SQL 或回答反推要求 |
| 单票对象、字段、待补内容 | 原 invoice_action／pending owner | 展示已知与待补；不从模型正文绑定身份 |
| 可恢复候选、取消记录、会话历史 | 原 SessionStore／TicketCandidates 的真实记录和修订 | 用实际记录提供恢复选择，终态不可复活 |
| 当前对象事实、范围、权限 | SQLite、ReferenceResolver、fresh 读取 | 历史只作历史，恢复后重新核权读取 |
| 预览与批准 | 原 UpdateSession／WriteCoordinator | 展示原预览；真人确认由受信宿主入口执行 |
| 是否落账 | 原 Commit、成功审计、新连接回读及其回执 | 按回执展示；不根据模型文字或网络完成状态宣布成功 |

薄适配器只编排以上入口并投影结果，不保存另一份权威状态。会话标识、epoch、候选修订是定位及并发控制信息，不是权限或批准凭据。

## 调用边界

以下是宿主侧接口设计，不是允许客户端任意构造身份的 Python RPC。
`session` 由宿主绑定实际账号、账簿身份和当前会话；前端不能传 `authorized`、`confirmed`、角色或自行指定模型执行身份。未来远程接入必须另有真实登录与可信确认通道，不能把当前模拟账号当生产认证。

| 操作 | 输入 | 复用入口与约束 |
| --- | --- | --- |
| `snapshot(session)` | 无业务改动参数 | 读取当前 owner、当前会话、真实持久记录与回执；只读 |
| `list_conversations(session)` | 无模型正文 | SessionStore.list_chats；依当前权限遮蔽不可读内容 |
| `new_conversation(session, expected_context)` | 观察到的会话及 epoch | 原导航确认、SessionStore.new_chat；先核对正在运行、未知提交及待办保存边界 |
| `switch_conversation(session, chat_id, expected_context)` | 本账号账簿内真实会话 ID | 原 switch_chat；成功后销毁旧 Agent 执行上下文，按目标会话恢复 |
| `send_message(session, text, expected_context)` | 原始用户消息 | 唯一 Agent.ask；原独立要求、工具分发、范围核验和事实交付照常执行 |
| `list_candidates(session)` | 无模型自报对象 | 原 list_invoice_candidates；仅返回当前可读且可恢复的真实候选 |
| `resume_candidate(session, id, revision, expected_context)` | 列表中的原 ID／修订 | 原 resume_invoice_candidate、recover_candidate、restore_invoice_candidate；重新核权，修订变化即拒绝旧操作 |
| `pause_current(session, expected_context)` | 当前事项，不接收待办 JSON | 原暂停及持久化入口；原 owner 先有可信候选，存储成功后才宣布可恢复 |
| `cancel_current(session, expected_context)` | 当前事项，不撤销历史事务 | 原 cancel_update，撤销执行与批准，再由原 Store 留终态；持久化失败必须单独返回 |
| `inspect_submission(session, request_ref)` | 原执行记录的请求引用 | 原 inspect_request／reconcile_update，只读核查审计与当前值，不发起第二次提交 |

`expected_context` 至少包含当前 chat、epoch，以及涉及候选时的 id／revision。宿主执行时再次核对实际 actor、账簿身份、会话及修订；过期请求返回冲突和重新读取提示，不在新上下文中悄悄重放。

本接口没有可由模型调用的 `commit`，也没有 `approve=true`。批准桥接继续使用原宿主确认回调与当前草稿指纹。前端普通事件不能自行产生可信批准；切换、改口、取消或重启后必须重新预览与真人确认。

## 统一结果快照

返回结构按字段职责分开，避免一个 `success` 掩盖部分完成或存储失败：

```text
version
context: chat_id, epoch, candidate_id?, candidate_revision?
turn: turn_id?, execution_state, stop_reason?, coverage
requirement: current_targets, unresolved, source_refs, revision?
invoice: known, missing_fields, lifecycle?, fresh_check_required
receipt: 原 WriteCoordinator 回执，request_ref?, readback_verified
persistence: turn_history, candidate, reference_state
available_actions: 宿主当前允许的操作
history: 明确标为历史的摘要或展示记录
failure: stage?, original_status?, recoverable?, message?
```

- `coverage` 保留完整／部分／未核验；有首卡不能自动成为完整交付。
- `invoice.lifecycle` 来自实际候选记录，不能由 `kind`、模型文字或客户端按钮推断。
- `persistence` 各项分别报告 `saved / failed / unavailable / not_attempted`；内存存在不算跨重启可恢复。
- `receipt` 与 `persistence` 相互独立。发票已经落账而聊天保存失败，仍如实保留提交回执；不能显示成“发票未保存”并建议重交。
- `available_actions` 是当前实际状态与权限的投影，不是授权；执行入口仍重复核验。
- 快照读取期间若会话或候选修订变化，返回冲突；不拼接不同会话的 owner 和 Store 状态。
- 未识别的底层错误保留原状态并报告能力限制，不通过解析中文错误文案伪造精确错误码。

## 显示与异常

| 实际情况 | 用户应看到 | 后续允许动作 |
| --- | --- | --- |
| 缺新值，未要求暂缓 | 已选对象、待补字段、未提交 | 补充、更正、明确暂缓或取消 |
| 明确暂缓且候选已存 | 已暂缓，可恢复；不是发票保存成功 | 从真实待办恢复；恢复不带批准 |
| 待办持久化失败 | 当前窗口保留情况、跨重启恢复未确认 | 保留窗口、重新核对存储；不伪报已暂缓可恢复 |
| 模型连接中断 | 原 API／响应失败状态、已取得结果、真实业务回执 | 新查询可重新提出；不自动重复业务提交 |
| 已尝试提交但结果不明 | 原 request_ref、UNKNOWN_OUTCOME、待核实 | 只读查审计／当前值，禁止自动重交 |
| 审计确认历史提交，但当前值已变 | 历史提交与当前值分别显示 | 不宣称当前仍等于批准值；新修改重新预览确认 |
| 会话或修订过期 | 当前操作未在新上下文执行 | 刷新状态后由用户重新选择 |

网络请求成功、模型说完成、会话写入成功都不是发票落账证明。查询／模型重试与业务提交必须分开：原模型自动重试为零；未知提交绝不因重连、重启或重复点击自动再执行。

## 有限连续性

仅保留当前有效要求及其原话来源、可信引用标识、待补字段、候选修订和取消终态。既有历史裁剪及摘要仍由 ContextBuilder 管理。摘要不承载当前金额、权限、草稿、批准令牌或提交许可。

跨会话不继承另一会话的目标和筛选；恢复同一会话时也必须标明历史与当前事实的区别。来源已丢失时追问或重新读取，不从摘要制造锚点。取消记录／修订优先于旧摘要；旧摘要不能复活已取消事项。前端不能自行把模型正文填回有效业务要求。

## 现有实现与待完成接线

- 已有：候选持久化、修订 CAS、取消终态、权限复核、原引用读取、原提交回执与审计核查。bcd17ea 的缺值等待及明确暂缓已有有限 Live 回归证据；不迁移为后续接口验收成绩。
- 仍在验：多对象与取消的剩余真实交接；不重跑已签收提交链。
- 待接线：从 ConversationUI 提取必要的编排与状态投影，供未来前端调用；目前没有上述统一接口的生产实现。
- 新风险须实际验证：同一要求跨会话／重启的连续性；持久化失败时真实回执；未知提交的核查状态跨重启恢复和写入门禁。现有 TUI 的进程内未知提交门禁不能自动算跨进程验收通过。
- 本草案不承诺已完成远程认证、远程可信真人确认、前端安装或人眼可用性验收。

当前新增接线仅限真实故障暴露的原未知提交恢复：`WriteCoordinator.restore_verification_requests(request_ids, actor, book)` 是受信 SessionStore 适配入口，恢复原 checkpoint 的核查引用，不接受模型正文或前端自报授权，不重建 Draft。`has_unverified_update` 统一原提交/取消/恢复门禁；`reconcile_update` 仍只读核查原审计与当前值。TUI复用该owner，没有增加统一远程API实现。该修订尚待同一原请求的原工作台恢复验证，不能据方法存在就签收异常恢复。

验证追加：上述恢复入口在af64a09已由原工作台实际通过故障保持／只读核查恢复，未重写财务。启动时再由同一owner检查历史UNKNOWN引用，成功与暂不可读分开显示。其余snapshot/前端命令仍为设计；有效BusinessRequest目前主要在同一Agent内传递，新Agent的结构化要求恢复尚未接线，不能据原raw历史恢复声称跨对话筛选继承已通过。现有有限原话、候选修订、取消终态和来源引用不包含批准，长期记忆不在本轮范围。

有限连续性接线追加：`Agent.business_request_snapshot()`、`Agent.restore_business_request(snapshot)` 和 `SessionStore.business_request_snapshot()` 复用同一不可变 BusinessRequest。快照只在原 Store 的当前账号／账簿／chat 下保存，Store以加法列迁移；宿主必须先装载当前chat的快照、再begin、再调用唯一Agent.ask，最后原子finish。恢复只做固定业务类型的反序列化并重查目录与权限，不是从聊天／SQL重建要求；显式取消、分界和未完成新轮使旧快照失效。当前接入TUI，CLI仅同步显式取消时的旧读取要求失效；未来snapshot/RPC宿主仍未实现。新自然语言跨会话证据待冻结验证，不把接口存在当通过。

持久化Source的`key`使用`source_ref`存储名，恢复时映回同一Source；无授权标记存为`business_authorization=false`。模型可见Schema不变。原因是通用凭据脱敏会遮蔽名为key、authorization的字段，不能为了保存业务引用而放宽凭据字典的保护。原用户引文等内容仍经过原脱敏一致性检查，不能借此存储密钥。

验收只补这些交接风险；每次先说明要区分的两种解释，首错定位，不扩大全量、不堆同题重试。旧首执失败、程序证据、真实模型回归和真人操作分开记录。


## 40dd2c2 实际接入与验收界限

原 TUI 已通过同一账号／账簿两对话的真实模型续查与正常冷启动续查：不同销售方的有效要求分别由原 SessionStore 保存，经原 Agent 类型及目录／权限核对后使用，实际首卡和末答完整交付。只读 `seller.names` 镜像只有与 Runtime 独立绑定的集合完全相同时才接受，不参与身份或权限判定；存储的 Source 引用使用 `source_ref`，不放宽全局脱敏规则。来源、范围、部分交付核验继续保留。

此实现只覆盖原 TUI 的有限当前读取要求连续性；上文“新 Agent 恢复尚未接线／自然语言证据待验证”为当时历史状态，现由本节取代。通用 `snapshot(session)`、远程命令宿主、Dot/DSH、Chat 前端仍是设计；没有第二状态 owner，也不从摘要恢复草稿、授权或批准。未知提交继续交给原 WriteCoordinator 只读核实，不用新模型回答或再次提交来猜测结果。

## DSH 可调用宿主适配（进程内）

`app.session_host.SessionHost(store, agent_factory, confirm=trusted_human_callback)` 已提供薄调用入口；没有 HTTP 服务、前端或生产认证。`store` 必须是宿主以实际账号／账簿打开的原 `SessionStore`；`agent_factory(actor, workbook)` 必须创建同身份的新原 `Agent`，模型配置和密钥由宿主持有。消息线程调用同步方法，确认回调在原办理链等待真人决定，前端自行转发到 UI 主线程。不得把客户端函数或模型参数接成该回调。

```python
host = SessionHost(store, agent_factory, confirm=human_dialog)
view = host.snapshot()
view = host.send_message(user_text, expected=view['context'])
```

可调用方法：`snapshot()`、`list_conversations()`、`new_conversation(expected=...)`、`switch_conversation(chat, expected=...)`、`send_message(text, expected=...)`、`resume_candidate(id, revision, expected=...)`、`pause_current(expected=...)`、`cancel_current(expected=...)`、`preview()`、`inspect_submission(expected=...)`。候选列表在快照 `candidates` 中，恢复采用原 CAS 修订。宿主绑定 generation／revision／chat／candidate token；过期或并行命令抛 `SessionConflict`，必须刷新，不能自动重放。退出后关闭宿主持有的 `store`。

统一快照分开给出 `requirement`、`pending`、`candidates`、`proposal`、`preview`、`receipt`、`persistence` 和 `result`（正文、覆盖与原事实渲染卡片）。草稿指纹、批准 token 不作为客户端命令参数。`preview()` 只读；实际确认由原 `run_invoice_batch` 或原单票 coordinator 执行。未安装可信确认通道时只返回核验提案，不代批、代拒或提交。持久化失败单列 `persistence.status=FAILED`，不能覆盖实际提交回执；未知提交先用原 owner 核查，不重提。

适配器不恢复聊天正文中的对象、事实或批准；只读取原 Store 当前 BusinessRequest、reference_state 与原待补记录。历史未知请求交原 WriteCoordinator，只读核实。新前端应采用快照及实际回执展示状态，不能从模型末答猜是否保存。本节的具体 Live／程序验证范围以同 SHA 验收记录为准，接口存在本身不等于人工可用性通过。
