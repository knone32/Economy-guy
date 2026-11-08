# Economy-guy · UX-Locate

基线 `main@866b85c33d08c5c1f8dc6dca43d02a316d45bcc9`。本地与远端一致，起始工作区干净。定位了 **四类问题、五条代码路径**。原始 A/B/C 均匹配，四类问题均在隔离虚构账簿复现。本轮真实外部 API 请求 **0**。生产实现、试用库与正式工作库未修改。

## 根因矩阵

| 问题 | 实际观察与最小复现 | 直接原因、状态所有者与模型影响 | UX-Fix 最小边界 |
| --- | --- | --- | --- |
| 1. 明确发票误入引用（L1） | B1 两页共 20 张。随后 B2 明确甲企业 F002，但加“这张”就 `AMBIGUOUS`。以两份相同初态的临时账簿先展示相同目录，仅去掉“这张”，从 **0 请求／0 Handler** 变为 **2／1**，`get_invoice` 成功。 | `reference_hint` 命中“这张”。`Agent._ask` 先调用 `ContextBuilder.resolve`，再计算 `exact_invoice`，且精确查询条件要求 `not reference`。失败引用提前返回。目录卡片并未形成锚点，`record_displayed` 的取键分支未覆盖 `list_invoice_directory`，原始 B1 也记录 `anchors=[]`。状态归 Context/Reference，B2 本轮模型未参与。 | 优先识别唯一、明确的企业与发票联合键，把冗余指示词与真实序数分开。范围冲突、多候选、拒绝及读写边界仍按原契约处理。目录序数如需支持，应单独定义页与展示顺序，明确 F002 的修复不依赖此扩展。 |
| 2. 引用错误暴露内部结构（L2） | 原始 B2 及 Mock 都显示“请明确引用对象”接内部 JSON，包含 `status`、`evidence`、`data` 和 anchor 术语。无锚点“那张”仍按安全规则追问。 | `Agent._ask` 把失败对象同时交给 `reference.unresolved` Trace 和 `json.dumps(reference)` 用户答复。`finish_turn` 的筛选不处理这一形态。状态归 Harness 引用结果，展示归 TUI。模型未参与。 | 只调整引用失败的用户文案映射。区分缺线索、权限拒绝、对象失效和存储故障，给出可执行的中文下一步。完整脱敏状态继续留在 Trace，权限拒绝不得透露对象。 |
| 3. 查询读起来机械且重复（L3、L5） | A2 数值正确，Agent 显示范围与技术来源，TUI 另显示账期合计。B1 两页产生两条相同的范围说明，C 同样两条。Mock 中 `get_finance_summary` 与 `list_invoices` 同轮成功时也产生两条完全相同的范围行、两类业务卡片；模型特有措辞未出现在 Harness 答复。 | `Agent._ask` 解析合法 `information` 后，在正式入口用 `render_information(read_results)` 取代模型文本。`render_information` 逐结果调用 `render_scope`，随后 `business_card` 又生成卡片。`finish_turn` 删除部分金额、用途及内部细节行，仍保留每条范围。模型选择工具会影响卡片数量，重复与最终措辞由 Harness/TUI 产生。替换模型措辞用于防止未经核实的业务事实或成功声明。 | 在渲染层以已验证范围、规则和证据组织一次业务表述。保留多页、多账期、不同来源或不同规则各自的证据。不要按字符串全局去重，也不直接透传模型 `information.text`。 |
| 4. 待办成功与进度提示冲突（L4） | 原始与 Mock 均为缺用途检查成功 5 张、经可信确认创建成功 ACTIVE，同时展示“无法核实同一任务与缺失用途的完整进度”和保存回执。Mock 确认前数据库快照不变，确认后新增一条待办、无发票审计。 | `handle_tool` 的 `_confirm_proposal` 经可信回调及正式事务返回成功并附 `management_confirmation`。`_verified_task_progress` 遇该证据有意停止把管理结果当作只读任务证据。`render_information` 的兜底只按工具名判断组合，误把“创建 + 检查”当成未通过的进度查询。`run_turn` 独立识别可信成功并显示保存回执。Task Manager/SQLite 保存任务，回复层组合状态，模型的最终成功措辞不参与认定。 | 分开表达“待办已保存，状态进行中”“当前检查仍缺 5 张”“合并进度只在同一已鉴权任务与范围经读证据核实时显示”。修改回复分支与回执展示。保留管理确认、写事务和进度核验条件。 |

以上四类均为 `CONFIRMED_CODE_PATH`、`CONFIRMED_REPRODUCTION`、`TRACE_CONFIRMED`。UX-Fix 建议是修复设计 `HYPOTHESIS`，尚未实施。四类均无需改变现有工程约定。

## 原始会话取证

在 Windows PowerShell 试用环境中，以 `accountant_trial.sqlite3` 的账簿身份和 U001 查找本地 Session Store。五条原话分别唯一命中同一聊天的顺序 1–5，并通过保存的 Trace ID 关联本地脱敏 JSONL。原始 Trace 的模式均为 `live`，provider/model 均为 `deepseek/deepseek-flash`。可见的 `context.selected` 中 `read_workspace` 为空。以下仅摘录匹配回合的业务摘要。

| 回合与 Trace ID | 原始 API 成功响应／模型请求；工具（顺序） | 最终模型信封摘要 → Harness/TUI |
| --- | --- | --- |
| A1 `15d438062a8e4034ab7f8f492e74b290` | 1／1；无工具，`WAITING_USER` | `clarification`，问甲企业的业务年份与月份 → 仅显示“请提供年份和月份”。 |
| A2 `474375fed59e470dad07abfd1a980b8a` | 2／2；`get_finance_summary(C001,2026,9) → SUCCESS`，R001 v1.0。 | `information`，给出三项金额、笔数和统计口径 → Harness 输出实际查询范围与统计结果；TUI 保留技术范围行并显示账期合计卡。发票 ¥9,622.06／10 张、收入 ¥13,000.50／4 条、支出 ¥7,180.74／8 条。 |
| B1 `06a3401326194b6397d49ac75ec3df50` | 3／3；`list_invoice_directory(C001,0,0,page=1) → SUCCESS`；同参第 2 页成功。每页 10，总计 20。 | `information`，称已分两页列出 20 张 → Harness 输出两条相同范围；TUI 显示两页业务卡，Trace 记 **0 个锚点**。 |
| B2 `888df84d27f74a1e8609834e78270be2` | 0／0；无工具、无 `api.response`；`reference.unresolved / AMBIGUOUS`。 | 无模型信封 → Harness 拼接中文追问和引用错误对象；Session Store 保存同一段用户可见文本。 |
| C `06b3c62b01184cec8f26539edf661173` | 2／2；`check_missing_purpose(C001,2026,9) → SUCCESS`，5 张、R002 v2.0；`manage_task(create,C001,2026,9,task_id="") → SUCCESS`，备注与原要求一致，确认来源 `trusted_cli`。 | `information`，说明已保存、进行中、仍缺 5 张 → Harness 重复两次相同范围并报组合进度未核实；TUI 同时显示“当前缺失用途 5 张”和“已按本次确认保存”。 |

原始三个工具执行回合中的五条调用均按 ID 配对。独立只读 SQLite 查询复核了三项金额、C001 总目录 20 张、F002 属 2026-09 且用途为空。C001/2026-09 当前仍缺 5 张，Trace 返回的同一任务在当前库中为 U001 的 ACTIVE 缺用途待办，成功发票修改审计为 0。会话保存的是 TUI 的文字与卡片内容，实际终端逐像素外观与按键顺序 `NOT_VERIFIED`。真实模型证据只适用于这些原始回合，去掉“这张”后的成功对照为 Mock；定位无需另行请求用户复做操作。

## 定向验证与下一阶段

- 用官方虚构夹具、临时 SQLite、正式 `Agent.ask` 与 Textual Pilot 重放 A1/A2、两页目录、带“这张”的明确 F002、无“这张”的对照、目录后的“刚才第二张”、新会话无锚点的“那张”，以及缺项检查与确认创建的组合。另在相同目录前置状态做措辞单变量对照，在同轮两个不同只读工具上核对重复范围。网络传输拦截器调用 0 次。
- 现有定向 unittest **8 项通过**。覆盖当前重查、无锚点和多个候选、同号跨企业及用户隔离、展示后撤权、TUI 目录和详情、取消与模型增写备注拒绝、确认及任务跨进程回读。此次无生产改动，未重跑全量。
- UX-Fix 优先处理 [context.py 的识别和解析](../../finance_agent/app/context.py#L16)、[Agent 的前置引用及失败出口](../../finance_agent/app/agent.py#L299)，再集中修改 [responses.py 的范围与进度渲染](../../finance_agent/app/responses.py#L73)、[TUI 的业务卡片和回执投影](../../finance_agent/app/tui.py#L692)。Tool Registry 和 Task Manager 用作核对证据的边界，当前证据不要求修改其事务。
- 验收至少锁住联合键和 ACL、撤权后重查、真实序数与无锚点仍安全追问、冲突范围不被略过、工具逐 ID 配对、单轮 9／12／2／1 上限、取消或未确认不写入、一次性确认不能重用、操作成功仅认实际事务和回读。展示层应同时测试同范围和不同范围、管理成功／取消／失败、已核实进度与未核实进度。
- 已满足 UX-Fix 的证据进入条件，明确了复现、模块、最小边界和安全验收点。修复后的真人 Windows Terminal 体验仍需复验，是否进入下一阶段由用户另行授权。本轮停在定位。

报告 SHA 可用 `git log -1 --format=%H -- docs/delivery/UX-LOCATE.md` 查询。
