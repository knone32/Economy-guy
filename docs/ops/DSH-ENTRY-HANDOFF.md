# DSH 原会话薄适配交接

最新工作台入口以 [2026-11-22 接口归属](DSH-WORKBENCH-INTERFACE.md) 与 [限定验收](WORKBENCH-ENTRY-ACCEPTANCE-20261122.md) 为准：产品冻结 394441c；以下保留原 1a05bc9 证据，不迁移成绩。

受测业务源码：`1a05bc993e19817d0015b3adab81d1cd38874905`。入口：`app.session_host.SessionHost`；详细契约见 [frontend-session-contract](../flows/frontend-session-contract.md)。本文件后的文档提交不迁移受测成绩。

宿主以真实绑定的账号／账簿打开原 SessionStore，并提供构造原 Agent 的 factory。模型配置和现有 WindowsVault 凭据留在宿主。同步方法运行在宿主 worker；真人确认 callback 必须来自可信 UI，不能由模型或 RPC 的 approved/confirmed 字段产生。

| 操作 | 接入要求 |
| --- | --- |
| snapshot / list_conversations | 使用原 owner 当前状态；并发切换时 SessionConflict 后刷新 |
| new_conversation / switch_conversation | 每次传最近快照 context；正在运行、旧 token 或未知提交不得自动重放 |
| send_message | 原始用户文字；唯一 Agent.ask；不传用户自报身份、授权或提交标志 |
| resume_candidate / pause_current / cancel_current | 候选 ID／revision 来自实际列表；原 CAS、待补与终态持有状态 |
| preview | 只读原提案／草稿；没有批准 token；真正确认仍在宿主原回调 |
| inspect_submission | 原 WriteCoordinator 只读核查；结果未知先核查，不能盲目再提交 |

前端先展示 business_status、receipt、persistence；result 为当前结果，historical_result 仅作历史。暂停／取消后 result=null，不能把旧的“等补值”正文继续当当前指令。persistence=FAILED 不表示已核实的财务提交失败，也不允许自动重试。宿主忙碌时其他线程读写被拒绝；确认 UI 使用回调提供的绑定快照。

实际入口已验证：历史真人提交的只读 COMMITTED 投影；存储异常不覆盖财务回执；真实待补的暂停／取消投影；Store 已切换但旧 Agent 未替换时，同线程混合读取与跨线程读取／取消被拒绝；完成导航后新会话干净。程序调度／故障证据与新的 Live 前置分开。既有 A/B、重启及真人保存证据按原 SHA 复用。

本轮真实模型首错是单票明细字段已显示却被覆盖检查漏计；1a05bc9 保留独立要求和范围核验，补精确单票字段证明，原 get_invoice 四字段引用回归 4/4。原失败保留。全轮 8 HTTP、零业务写入、零新批准；未重跑完整链或全量。具体原件在本地 evidence-root/recovery-boundary-20261121/fb85-entry-boundary-fixed/CLOSEOUT.public.json。

尚未代表通过：DSH 前端实际接入、真人 GUI 可用性、新批准／保存或陌生泛化。不得把本接口或旧摘要当授权。GUI 文件已在 `011e359` 接入原 `SessionHost`；本轮确认超时/display-ack 交接以最终冻结提交和 GUI 文档为准，真人窗口操作仍未代签。
