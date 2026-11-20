# B：单票连续补充与未知提交结果（2026-11-20）

基线：`b002eeaa93e3d13e7c0f669a417ebb12fcd86452`，分支 `sprint/2026-11-20-ticket`。本切片只新增 `finance_agent/tests/test_ticket_continuity_20261120.py`；**业务源码、事务机制、模型提示及既有断言均未改**，未推送。

## 已有机制与本轮证据

- 用正式 `Agent.ask` / `change_invoice`，脚本模型明确给出业务参数：甲企业待补票号 → 临时只读乙企业 → 回到甲企业 → 仅补票号。待补记录及原始来源逐项相等，最后正式预览仍为甲企业、原字段和原内容。另行验证更换企业后 fresh 读取该企业同号发票，未以先前查询对象替代目标。
- 明确模型 `turn_action=stop` 后，原 `pending_intent` 失效；随后同样仅补票号不能恢复原字段、新值或企业。这里验证的是结构化模型决定后的 Runtime 边界，不是自然语言理解能力。
- 身份、read/modify 权限变化及模型夹带 confirmed/authorized 参数均不能产生预览/确认。工具表不含 Commit、confirm_draft、commit_update、inspect_request。独立修改夹具原值后，正式预览显示 fresh 原值。所有普通测试都拒绝预览，数据库快照不变。
- 独立程序故障测试使用临时官方虚构夹具，**模拟可信确认，不是真人批准或 Live**。事务后 `_readback` 确定性抛出异常，实际字段已保存、成功审计已写，但回执为 `UNKNOWN_OUTCOME`。临时数据库触发器独立计数：全流程 **1 次字段 UPDATE、1 条成功审计**。
- 复用同一 request_id/fingerprint 再调用正式提交入口时，未知结果守卫在 Commit 前拦截；只读 reconcile 按该 request_id 核对审计和当前值。关闭/重开 SessionStore 和新建 Agent 后，lookup 仍是原请求；新 Agent 没有草稿/确认，旧 request 不能提交；inspect_request 新连接回读成功。任务表前后相同。Stage2 既有同请求幂等测试也通过。

状态边界：会话内待补只保留业务数据和来源，不保留提交许可；它不是持久 Task。进程重启后当前合同不会恢复单票待补/草稿/确认。本轮验证了未知结果的存储 lookup 和数据库只读恢复，**未验证完整 UI 重启恢复**；不能把 SessionStore 重开等同于用户看见恢复结果。

## 检查结果（全部离线、0 模型 HTTP）

运行目录 `finance_agent/`；解释器为当前 Codex Python，PYTHONPATH 指向 `reliability-v2-20261119/runtime-deps`。

```text
python -m unittest tests.test_ticket_continuity_20261120 -v
Ran 7 tests ... OK

python -m unittest tests.test_ticket_continuity_20261120 tests.test_stage2 -q
Ran 21 tests ... OK

python -m unittest tests.test_business_sources tests.test_business_target_continuity tests.test_business_ownership tests.test_unknown_cancel tests.test_write_receipts tests.test_architecture -q
Ran 61 tests ... FAILED (failures=16, errors=1)
```

最后一条是相关模块回归，不是全量。无产品代码变化，以下为公开 b002 基线已有失败，不能把新 7 条通过折算成原行为全部通过；未为刷绿重跑/修改这些测试。`test_business_sources`、`test_business_target_continuity`、`test_unknown_cancel` 和 `test_architecture` 在该命令中没有失败记录。失败模块及完整测试名如下；子例失败按 unittest 原记录计数：

| 模块 / 测试名 | 记录 | 首错与判断 |
| --- | --- | --- |
| `tests.test_business_ownership.BusinessOwnershipTests.test_current_correction_conflict_cannot_reuse_old_value` | 1 error | `KeyError: new_value`；旧断言要求拒绝冲突后仍保留旧值，与 DOT-OVERNIGHT 撤销活动旧值合同冲突。旧兼容合同，不改断言。 |
| `tests.test_business_ownership.BusinessOwnershipTests.test_same_business_contract_owns_state_fresh_read_and_real_preview` | 1 failure | `invoice_change is None`；脚本每次回显历史 new_value，未作 `value_ref=previous` 修正，与现行补丁/来源合同不符。旧兼容合同。 |
| `tests.test_write_receipts.WriteReceiptTests.test_confirmed_field_reconciles_same_value_after_model_final_without_tools` | 2 failures | current=你好/办公；旧字段澄清期待“用途改成”，实际结构说明未产生该提示。旧字段兼容入口，未进一步判定根因。 |
| `tests.test_write_receipts.WriteReceiptTests.test_invoice_field_continuation_retires_on_new_scope_and_rechecks_permissions` | 5 failures | action=account/cancel/different_invoice/permission/changed_value；起始 pending 为 None，尚未到各权限/取消子例判断。旧字段兼容入口，未进一步判定根因。 |
| `tests.test_write_receipts.WriteReceiptTests.test_natural_invoice_edit_reconciles_verified_current_value_without_write` | 2 failures | U001、回执测试、合法/截断 final；fulfillment 实际 UNVERIFIED_RESULT，期待 VERIFIED_GOALS。最终交付口径，未判定；不在 B 修改区。 |
| `tests.test_write_receipts.WriteReceiptTests.test_query_retains_natural_answer` | 1 failure | 实际 API/结构失败提示，期待“请提供企业和月份”。旧最终回复兼容，未判定；不在 B 修改区。 |
| `tests.test_write_receipts.WriteReceiptTests.test_recent_invoice_typo_does_not_ask_for_literal_value_again` | 1 failure | 旧字段澄清期待“用途改成”，实际结构说明提示。旧字段兼容入口，未进一步判定根因。 |
| `tests.test_write_receipts.WriteReceiptTests.test_recent_single_invoice_final_reconciles_only_the_verified_literal_value` | 4 failures | U001、回执测试；information 的 get_invoice/resolve_recent_invoice/无 lookup，以及 clarification 的 get_invoice；fulfillment 实际 UNVERIFIED_RESULT，期待 VERIFIED_GOALS。最终交付口径，未判定；不在 B 修改区。 |

本轮声明的单票动作链未发现实际机制阻断，所以没有重写已有机制。上述失败仍保留，不声称已修好。

## 未验与交接

- 当前模型自然语言选参是否正确、真实模型 HTTP、真人审批写入均未验；不调用付费模型。
- 新故障测试没有挂载 TUI，`UNKNOWN_OUTCOME` 只断言 Agent 真实回执。相关旧 `test_unknown_cancel` 实际运行了 TUI 模拟流程，但不把它合并表述为本轮故障已完成用户可见 UI 验收。
- 单票会话暂缓的跨进程续办没有实现/宣称；完整 UI 恢复、最终可见未知状态与真人批准窗口留主控单独验收。
- 未运行全量测试，未扩大任务/偏好或最终答复改动范围；`git diff --check` 通过。

## 独立补证：实际 Workbench 故障页面与 App 重开

追加任务只新增 `tests/test_ticket_fault_ui_20261120.py` 一个 Textual Pilot 测试，未改产品源码。以下补证替代上面首切片“故障没有挂载 UI / 完整 UI 重启恢复未验”的具体缺口；真人批准和真实模型仍未验。

入口为真实 `AgentWorkspace`、150×42 的头显测试、登录 U001、脚本 `change_invoice`、实际单票 Approval 弹窗。**测试程序模拟按下确认按钮**，不是人工批准或桌面真实点击。独立临时官方虚构库触发器计数；故障注入函数先用独立 SQL 确认真实事务+审计已经完成，再在 `_readback` 抛一次异常；`assert_called_once()` 验证仅注入一次。

实际可见结果：

- 对话：“发票修改结果未知。请先核查审计，再决定是否重试。”
- 业务卡：“成功 0…结果未知 1…”、“结果未知，请核查审计”；原值到新值仍可见。
- 页脚：“提交结果未知，请先查看执行记录再决定是否重试”。上述区域断言没有“保存成功”或“已保存并回读”。
- 保持未知结果时，用同 request_id/fingerprint 再提交被守卫拦截；Workbench 再发送 `/edit` 也不出现确认屏、不产生草稿，仍只有 **1 次字段 UPDATE、1 条成功审计**。
- 关闭第一个 App，再创建新 App 并重新登录（同一测试进程，**不是操作系统跨进程重启验收**）。实际恢复器只读核查同 request_id，审计 COMMITTED 且 fresh `current_matches=true`。登录页内历史显示：“已在 SQLite 成功审计中核实上次提交。请查看当前发票。”
- 打开并展开真实执行记录页，显示原 request_id、成功审计及原/新值。标题保守保留“审计已证实提交 · 回读未核实”，历史操作仍标结果未知；未把历史未知卡改写成新的提交。新 Agent 会话 ID 不同，旧草稿/确认/pending 均未继承，旧 request 提交为 DENIED；SQL计数仍不变。

首个测试驱动错误是直接 `select_pane` 只切页、没有刷新记录组件而产生 `NoMatches: operation-1`。已改成与工作台导航一致的 `show('records')` 刷新入口；没有产品阻断或源码修复。

```text
python -m unittest tests.test_ticket_fault_ui_20261120 -v
Ran 1 test in 1.982s ... OK
```

0 模型 HTTP、0 付费调用。未重跑 61 项或全量。渲染 SVG 截图和实际 UI 字符/独立 SQL 抓取保存在工作区本地 `business-20261120/b-ticket-ui-evidence/`，不提交验收产物：`01-program-preview`、`02-unknown-visible`、`03-restarted-login`、`04-restarted-original-record`（各有 `.svg` 和 `.json`）。本次证据 request_id 为 `9ab732964a29409bb90c904c763fe13e`。

## P1 修复：未提交单票候选跨进程续办

用户六项第 4 项明确要求继续未完单票，因此把首切片观察到的“待补重启丢失”作为业务缺口修复。开始前合并主控 `30cb025`（无冲突），未改 A 模块或 Agent.ask 主循环。

**首红**：真正子进程通过 Workbench 生成甲企业 2026-09、备注“跨重启待复核”、缺票号的 Runtime 待补并退出；新 App 登录只有原历史“请补充发票编号”，没有活动候选恢复。`test_real_process_restart_recovers_source_then_requires_fresh_preview` 在期望可见“未提交的单票候选”处失败。根因是 SessionStore 原来不保存 Runtime pending，ensure_agent 没有候选恢复入口；不能用历史正文或已提交审计代替它。

最小改动：

- SessionStore 加法迁移 `chats.invoice_pending`，保存 Runtime 单票 pending 原槽位、source_request 和 provenance，封装 actor、稳定 workbook identity、chat。与本轮 finish 的历史记录在同一事务更新；不是模型可调用入口，也没有序列化 draft/confirmation。一次只恢复当前同一对话的唯一候选，不从其他聊天挑选。
- 只读插话正常结束仍保存同一候选。`begin` 先清除上一快照；若最新轮已经开始但未完成，重开标记中断，不把可能被最新原话撤销的上一快照恢复成活动要求。该保守策略可能要求用户重新明确中断前内容。
- TUI 登录时按当前身份/账簿重新核对候选结构及企业 read/modify 权限，再解释已知槽和缺项；权限变化则拒绝并撤下候选。用户本轮明确继续且模型选择 `change_invoice` 后才沿原来源核对、对象/ACL、fresh read 和全新正式预览办理。Agent 新增的专用恢复方法只填候选数据，不恢复草稿、确认或自动执行。
- ask 外的取消同步持久撤下候选：未建 Agent 的 `/cancel`、F4、Agent reset、新对话/切历史、模型上下文分界、进入任务。新对话先撤下旧对话候选再切换，避免清错目标聊天。普通 App 退出/重开保留已结束回合的候选。

实际跨进程 UI 显示：“已找回未提交的单票候选。企业：C001；年：2026；月：9；字段：备注；新内容：跨重启待复核…仍需补充：票号…尚未保存。” 先插入乙企业只读，候选及来源仍逐项相等；随后仅补 F006，预览显示独立新连接改过的“原值　重启后独立原值”和“新值　跨重启待复核”。没有自动批准，测试拒绝预览，成功审计为 0。

新增 3 个测试：真正子进程退出重开+来源不丢+只读插话+fresh 预览；取消反例的 5 个子例（未建 Agent、F4、新对话后重开旧对话、进入预置夹具任务、begin 未 finish 中断）；read/modify 分别撤销及不同 actor 不能恢复。任务由隔离 SQL 预置，不称模型保存或人工管理批准。

最终定向检查：新增 `PendingTicketRecoveryTests` 3 项通过；既有本轮连续补充 7 项、故障 UI 1 项、架构 2 项也通过。开发中一次元组/JSON 规范化导致候选拒存已修正；一次新对话测试过早关闭未 mount 的弹窗，改为等待真实 mount 后通过。未重跑 61 项或全量，原基线失败台账仍保留。

本地公开截图/字符及原候选来源对照：`business-20261120/b-ticket-pending-ui-evidence/05-pending-restored-after-process.{svg,json}`、`06-restored-fresh-preview.{svg,json}`。0 模型 HTTP、0 付费，恢复正例未批准发票。

范围限制：本补丁恢复**已结束回合的 active 单票待补候选**。在正式确认弹窗尚未结束时关闭/崩溃，不把当时的完整 draft、批准或未完成 turn 恢复为可执行要求；需要用户重新明确。未做任意自然语言 NLU 或真人确认验收，也未建立通用长期记忆框架。

## B v2：跨新聊天显式续办与修订保护（基线 66aeec2）

本节替代前节「仅同一对话恢复、切新聊天撤销候选」的范围限制。最初公开反例在 `list_invoice_candidates` 缺失处报 AttributeError；原实现只有 chats.invoice_pending，生命周期归聊天且没有修订比较。

- 新增独立 `invoice_candidates` 加法表，按可信 actor 与稳定 workbook identity 隔离。保存的只是来源核对后的业务槽位、来源链、稳定候选 ID、revision 和 ACTIVE/PAUSED/CANCELLED/COMPLETED 状态。取消与完成保留终态墓碑、移出可续列表；任何旧 revision 更新均拒绝，不从历史正文重造候选。
- Workbench 新聊天保持暂缓候选，默认不激活旧业务。输入 `/pending` 查看可读改候选和修订，复制 `/resume <id> <revision>` 显式选择，再明确继续/补充。本轮模型只传增量；来源槽由运行时合并，重新核权、fresh 读值、生成全新正式预览。候选 ID/revision 不是批准，不恢复 request fingerprint、草稿或 confirmation。
- `/pause` 与结构化最终答复 `turn_action=pause` 保存 PAUSED、退休执行状态；`/cancel` 与 `turn_action=stop` 取消。新聊天、切历史改为暂缓，普通退出保留候选；进入任务/显式边界仍按原规则撤销当前绑定事项。
- 正式单票预览前 checkpoint 业务候选为 PAUSED；若进程在弹窗中断，列表里仍可显式找回业务数据，不继承当时批准。每轮与预览 checkpoint 持有 expected revision；持久化以事务 CAS 更新，Agent 准备/提交前也核验修订。旧聊天快照只有 revision 匹配且候选仍 ACTIVE 时才可用于原聊天恢复。

新增公开 `tests.test_ticket_durable_20261120` 5 项（全部通过，0 模型 HTTP）：实际 Workbench 新建不同 chat ID → 列表 → 显式 resume → 独立 SQL 改原值 → 新正式预览（程序拒绝，无审计）；模型 pause/stop 的持久状态分验；新聊天取消后不能复活；旧 revision 不能覆盖新内容或取消；已显示的旧批准窗在独立修订取消后，即使程序点击确认也不能提交，发票及审计不变。最后一项模拟可信界面选择，不是真人批准。

额外定向首次运行 51 项有 3 项失败，均来自原 `tests.test_p05_sessions`（SDK 布线、偏好确认、查询语义跨进程）。在未改动且 HEAD=66aeec2 的原 b-ticket 树独立运行这 3 项，重现相同 3 项失败；未改旧断言或归入本切片通过。初次旧恢复子进程测试另因 Windows 子进程编码不匹配失败，设置 `PYTHONUTF8=1` 后真正子进程恢复项通过。全量回归另行运行，不能据定向通过声称全绿。

入口：`app/ticket_candidates.py`（可信持久态/CAS）；`SessionStore`（迁移及回合事务绑定）；`ConversationUI` 与 `AgentWorkspace.submitted`（列表/选择/暂缓）；`invoice_action.change_invoice`（预览前业务快照）；`Agent.pause_invoice_update` 与 `responses.parse_final`（pause/stop 分态）。未读 private 题，未调用产品 API/付费模型、未推 main。真人 UI、任意自然语言准确性、真实跨进程审批弹窗强杀恢复未验；既有真正子进程待补恢复及本轮实际新聊天恢复分别验证，不混称同一场验收。
