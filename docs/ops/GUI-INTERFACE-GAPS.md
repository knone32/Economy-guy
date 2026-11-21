# GUI 接口缺口（一次汇总给 Sol）

基线：`sprint/2026-11-20-contract-followup`，本轮冻结提交（Sol 的超时/display-ack
契约基于 `426f7b2`）；业务受测源码 `1a05bc9`。最终 SHA 以仓库当前提交为准。
前端契约：[docs/flows/frontend-session-contract.md](../flows/frontend-session-contract.md)。

## 已由本 GUI 适配

| 能力 | 复用入口 | 文件边界 |
|---|---|---|
| 会话列表/新建/切换/历史 | `SessionHost.list_conversations/.../conversation_view` | `finance_agent/app/gui_host.py` |
| 发送消息/真实工具结果 | `SessionHost.send_message`（内部唯一 `Agent.ask`） | 同上 |
| 单票预览/确认/提交/回读 | `SessionHost` 的 `confirm` 回调、原 `WriteCoordinator`/`Agent.commit_update`；GUI 只桥接 | 同上 |
| 暂缓/取消/恢复 | `SessionHost.pause_current/cancel_current/resume_candidate` | 同上 |
| 查询显示确认/指代续办 | `SessionHost.acknowledge_display` + `display`/`conversation` 投影 | 同上 |
| 未知提交核查 | `SessionHost.inspect_submission` | 同上 |
| 待办详情/恢复/取消 | `SessionHost.resume_candidate/cancel_current/pause_current`；仅当前候选提供取消 | 同上 |
| 设置连接/Profile 清单 | 只读 `GuiHost._connection_info` + `visible_profiles`，不切换 | 同上 |
| 本机 HTTP/页面 | `http.server` + `finance_agent/gui/index.html` | `finance_agent/app/gui_server.py` |

浏览器只拿到投影后的快照和一次性 `preview_id`；`user_id`、身份、`approved`、
`confirmed`、指纹、request_id 均不由客户端传入。

## 宿主切换缺口（一次交 Sol）

- **账号切换**：当前进程由 `--user` 绑定；`SessionHost` 没有运行中切换账号的
  接口，涉及身份/权限/Store 重绑定，GUI 不自行实现；设置页只显示当前账号。
- **账簿切换**：当前进程由 `--db` 绑定；切换需重新打开 Store/Agent 并校验
  权限、候选与未知提交，GUI 不自行切库；设置页只显示当前账簿。
- **模型/Profile 热切换**：设置页接已有 `visible_profiles` 清单和当前连接，
  选择只生成下一次 `run_gui.py --profile ...` 启动命令；运行中切换需要 Sol
  提供宿主接口（重建 Agent/连接，保留 Store 与未知回执门禁），GUI 不做假按钮。
  需要 Sol 明确账号/账簿/模型三者的重绑定事务边界和失败回执。

## 仍需 Sol/后端确认的缺口

0. **`SessionHost` 的同步确认已由 GUI 适配层桥接，待 Sol 确认边界**：
   `app/session_host.py` 的 `send_message` 在原办理链内阻塞等待 `confirm`。
   当前 `gui_host.py` 用 worker 线程 + `threading.Event`，在回调中保存原
   `SessionHost` 绑定快照，浏览器只提交 `preview_id`；不修改 `session_host.py`。
   超时按契约视为**确认中断**：清空当前回调句柄、不得产生批准；页面轮询宿主
   快照关闭弹窗、解除忙碌并显示“未批准/未提交”，旧按钮只得到失效冲突。
   需要 Sol 确认这是允许的适配方式，或提供正式的非阻塞 preview/confirm 接口；
   不能因此让 GUI 自己执行 Prepare/Commit/恢复，也不另建第二套批准状态。
1. **统一宿主 snapshot/RPC 仍以 `SessionHost` 为唯一命令 owner**：当前 GUI
   只在 `SessionHost` 外包一层 HTTP/页面投影；`session_host.py` 的
   `snapshot/switch/send/resume/pause/cancel/inspect/acknowledge_display` 是
   唯一业务入口。`conversation` 同帧 turns/chats 已由宿主提供，GUI 优先消费；
   该 display-ack/超时契约需在 Sol 冻结提交中固定。
2. **历史业务卡不是 SessionHost 快照的一部分**：`SessionHost._save` 的历史
   display 只有 Agent 文本，没有 `result.cards`；GUI 只能展示当前 `result`/
   `historical_result` 卡片，旧轮业务卡未持久化。需要 Sol 确认是否让原 Store
   保存展示投影，或明确 GUI 只在当前轮展示卡片。
3. **单票 vs 批量预览**：当前 GUI 明确只支持单票；`propose_invoice_changes`
   的多票 `invoice_change` 仍由原 `run_invoice_batch`/逐票确认拥有。需要确认
   批量确认窗口是否由 GUI 接入，或保持原工作台入口；不能在 GUI 伪造批量批准。
4. **预览/回执/持久化时序已由 SessionHost 拥有**：GUI 不再自己 `finish` 或
   另记回执；`SessionHost` 的 `_save`/`_persistence` 是唯一来源。GUI 仍需要
   确认：刷新/重启后 `business_status`/`receipt`/`persistence` 的投影字段是否
   稳定，尤其是“已提交但历史保存失败”与“UNKNOWN_OUTCOME”并列时的显示。
5. **未知提交的跨进程门禁**：GUI 只调用 `inspect_submission`；需要确认
   `restore_verification_requests` 在浏览器宿主中的恢复生命周期，以及重启后
   `UNKNOWN_OUTCOME` 是否仍只能用只读核查。
6. **会话切换门禁**：GUI 在存在 pending/draft/预览/未知回执时拒绝切换；需要
   确认这与原 TUI `_safe_to_switch` 的最终规则完全同源，不新增第二套状态机。
7. **当前待办聚合**：GUI 为展示而遍历当前可读企业调用 `list_tasks`；需要
   `SessionStore`/任务 owner 提供当前会话的待办投影，避免界面自行决定范围。
8. **模型连接与 Profile**：GUI 只用 `resolve_connection` 读取已有 profile；
   需要确认未来前端是否允许切换模型，以及切换时能力范围/预算的宿主校验。
9. **错误码**：GUI 只显示原回执/原 status 和宿主中文说明，不解析中文错误文案；
   需要确认稳定的 `failure.stage/original_status/recoverable` 投影。

## 文件边界建议

- `gui_host.py`、`gui_server.py`、`gui/index.html`、`run_gui.py`：本 GUI 所有。
- `agent.py`、`session_host.py`、`write_coordination.py`、`session_store.py`、
  `updates.py`、`ticket_candidates.py`、`responses.py`：**本 GUI 未修改**；
  其中 `session_host.py` 是 Sol 当前提供的接口 owner。若需新接口，由
  Sol/后端 owner 改并给出契约，GUI 只消费。
- `docs/ops/GUI-MINIMAL.md`：运行/接通/未验收清单；不与业务验收混写。
