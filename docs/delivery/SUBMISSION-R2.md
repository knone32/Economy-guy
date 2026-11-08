# Economy-guy · Submission-R2 真实业务验收

**R2_PARTIAL · 2026-11-08。** A、B 的真实业务路径和 D 只读核对取得证据。C 的真实持久化、跨进程恢复、受控修改及剩余进度均通过。C5 单轮没有说明 F002 已补齐，因此完整业务说明仍为 PARTIAL。

## 版本与执行范围

- Base SHA 与被测生产代码 SHA 均为 `204654368ed3282e17cc51c788b3f0763101945f`。开工时本地和远端一致，工作区干净。本轮只改验收驱动、离线测试和交付文档。
- 验收驱动与测试提交为 `f71688d7ffc4916d8327d74f93f39d195006f018`。Report SHA 用 `git log -1 --format=%H -- docs/delivery/SUBMISSION-R2.md` 核对。各次 Pilot 补测使用同一生产代码和请求台账，原阶段结果未覆写。
- Windows PowerShell、Python 3.12.14、Textual 1.0.0、OpenAI SDK 1.109.1。真实 Textual 控件由 Pilot 操作。Windows Terminal 实机和真人确认均为 **PENDING**。
- A/B/C/D 分别用独立的官方虚构账簿。每库初始 40 张发票、48 条流水、5 条种子规则、0 条待办、0 条偏好及 0 条成功发票修改审计。B/C 的 F002 初始用途为空，C 起始时没有继承 B 的修改。

## Live 证据

U001 的 `shared-flash` 通过离线凭据预检。SDK 实际 POST 至 `https://api.deepseek.com/chat/completions`，响应模型标识 `deepseek-flash`，协议 `deepseek-thinking`，Trace 元信息一致。服务方公布的版本为 DeepSeek-V4.1-Flash-1017，HTTP 响应未返回更细构建号。[官方模型与费率](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)

共 **23 次实际 API 尝试，全部 HTTP 200**。SDK 自动重试 0。已观测输入 102,661、输出 4,639，共 **107,300 tokens**。按高峰价、输入全作未命中保守估算 **¥0.242434**，账单金额未观测。单请求发出前预留最高 ¥5.24288，共用台账限制总尝试 30 次及保守费用 ¥10。SDK 往返 0.787–3.376 秒，累计 40.977 秒。

| 场景 | 证据及判定 |
| --- | --- |
| A · PASS | A1 模型主动追问年月，0 工具、0 月度业务 SQL。A2 补充 2026-09，A3 通过工作台预选 C001／2026-09 后直接问，两轮均调用 `get_finance_summary` 并正常结束。实际 SQL 均限定该企业和月份。答复、规则及独立 SQL 一致，发票 ¥9,622.06／10 张、收入 ¥13,000.50／4 条、支出 ¥7,180.74／8 条，R001 v1.0。 |
| B · PASS WITH SIMULATED CONFIRMATION | B1 合法 Prepare，预览显示 C001／F002、原值为空、用途改为“资料打印”。确认前独立快照无写入。Pilot 确认后仅变更该字段，新增恰好一条成功审计，新连接回读与请求编号、指纹、新旧值相符。B2 同一句再次发送，回执 `CURRENT_VALUE_MATCHES`，未再提交。B3 的 U002 对现有 Profile 不可见，未发请求。独立 Pilot 合成提案以同一句和同一目标验证 `DENIED`、无草稿、无审计。 |
| C · PARTIAL | C1 正确走 `check_missing_purpose`，R002 v2.0、缺 5 张。C2 模型提案经具体弹窗模拟确认，持久化唯一 ACTIVE 待办。C12、C34、C5 最终工作进程 PID 分别为 12600、33548、37524。C3 重新登录、重读并恢复同一任务焦点，未恢复旧草稿、确认或模型私有协议。C4 模拟确认后仅补齐 F002 用途，新连接回读与唯一审计一致。C5 新进程重查同一待办，结果为 ACTIVE、缺 4 张，显示剩余事项及下一步，也做了一次额外同账期汇总。C5 未再次明确 F002 已补齐。C4 的成功回执与 C5 的剩余结果可分别核对。 |
| D · PASS | D1 两次目录工具分别返回第 1、2 页。工作台保存的两张展示卡各与独立 SQL 对应 10 张，总数 20 张。D2 `get_invoice` 按 C001／F002 返回详情，界面字段与 SQL 一致。D3 沿发票焦点调用缺用途检查，范围 C001／2026-09、R002 v2.0、缺 5 张。D 全程无业务写入。 |

实际确认共 3 次，分别是 B1 发票、C2 待办和 C4 发票。全部标为 `SIMULATED_CONFIRMATION`。可信确认、事务及回读走正式代码，确认动作由 Pilot 执行。

| 轮次 | 模型请求／实际 Handler／续期／重规划 | 停止原因 |
| --- | --- | --- |
| A1 | 1／0／0／0 | WAITING_USER |
| A2、A3、B2、C1、C2、D2、D3（每轮） | 2／1／0／0 | ANSWERED |
| B1、C4（每轮） | 1／1／0／0 | WAITING_CONFIRMATION，随后独立可信确认及事务回执 |
| C5 | 3／3／0／0 | ANSWERED |
| D1 | 3／2／0／0 | ANSWERED |

C3 与 C5 的任务界面恢复各使用 0 次 API。Trace 共核对 14 个工具提案及 14 个同 ID 结果，全部满足 9／12／2／1。A3 和 C5 初次停在 Pilot 控件操作，C5 第一次补测仍在发请求前超时。补测改用布局就绪后的键盘焦点，继续使用原台账。B3 的首次驱动等待没有发送请求。D1 初次验收断言只接受第一页，独立对照已保存的真实两页卡片后，仅补 D2/D3，未重发 D1。驱动原始失败状态保留在本机忽略目录 `artifacts/submission_r2/run-1rmt21d1/`。初始汇总仅覆盖第一轮 14 次，最终口径为同一 SQLite 台账与各阶段侧录共 23 次。

## 数据库与标准协议预检

独立连接复核 A/D 无业务变化，B 仅发票和成功审计变化，C 仅任务、发票和成功审计变化。流水、规则、偏好及种子规则审计均无业务变更。展示锚点、账簿标识及本地 Session Store 属会话元数据。当前工作库 SHA-256 前后一致。JSONL 逐行解析检查凭据模式和私有推理遮蔽。原始 Trace、运行库和本地配置未提交。

合成 HTTP 使用真实 SDK 发出标准 Chat Completions，核对多工具 JSON 参数和同 ID 的结果、后续轮次的 assistant/tool 消息、正常输出、超时零重试、预算耗尽后仍配齐工具结果。结合现有异常输入与 Trace 回归，覆盖标准协议边界。该预检没有构造官方端点或模型别名。评审 Key 和官方调用配置未提供，状态 **OFFICIAL_QWEN_LIVE_NOT_TESTED**。[主办方评审模型公告](https://m.saikr.com/contest/notice_detail/50275)

- 定向回归 90 项通过。补充验证 4 项通过，另完成 A3 与 C5 的零网络 Pilot 检查。
- 全量 unittest 435 项通过，零失败、零跳过。单独运行架构测试 2 项通过。

C5 表达缺口、真人确认、Windows Terminal 实机及官方模型验证仍阻断“完整真实验收通过”的声明。仓库可按 [Submission Checklist](SUBMISSION-CHECKLIST.md) 准备参赛材料，平台提交状态待外部核实，既有安全发布门禁保持 BLOCKED。
