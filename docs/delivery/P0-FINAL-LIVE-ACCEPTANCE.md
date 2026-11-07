# P0 最终验收 · Economy-guy

**判定 `P0_BLOCKED`。** F1–F4 与 A/B/C 离线链路通过。DeepSeek Flash 真实验收因凭据未设置而阻断，Windows Terminal 实机验收为 `NOT_TESTED_ON_WINDOWS`。

## 1. 版本与环境

- 仓库 `knone32/Economy-guy`，分支 `main`。起始本地及远端 SHA 均为 `cf07b859a83182998e6c9c0bfddccf1ceecad746`，工作区干净。
- 最终被测代码 `81dbbe812fb626e2710b662d1cee46c3a539fe90`。报告提交可用 `git log -1 --format=%H -- docs/delivery/P0-FINAL-LIVE-ACCEPTANCE.md` 核对。
- Windows PowerShell，Python 3.12.14，Textual 1.0.0。界面操作通过 Textual Pilot，测试库均从官方虚构夹具 `finance_agent/tests/fixtures/example.xlsx` 初始化。
- `shared-flash` 对 U001 可见，离线校验为 `deepseek-flash`、`https://api.deepseek.com`。凭据引用 `DEEPSEEK_API_KEY` 在进程、用户和机器范围均未设置。未输出凭据值。

## 2. F1–F4

| 项目 | 原缺口和修复 | 核对与边界 |
| --- | --- | --- |
| F1 多轮补充 | 短语识别过窄。已允许“甲企业”“甲企业的”“是甲企业”“我说的是甲企业”、明确更正和自然取消。 | “不是甲企业，是乙企业”只更正同一未完成意图的对应字段。新主题不会沿用修改许可。已展示草稿可 Esc 取消后发送更正，旧草稿不能提交。 |
| F2 新值来源 | 旧逻辑只强制企业和发票。现在 TUI Prepare 前检查企业、发票、字段和新值四项，并比较模型提案。 | 空白、空引号和省略号先追问。可说“新值是资料打印”或明确说“清空”。候选不一致不会创建草稿。 |
| F3 首次配置 | 个人 Profile 原来需要切出 TUI。现在设置内可新建、选择并离线验证，隐藏输入 Key 只设置进程环境。 | 配置合法、Key 就绪与联网状态分开。Global 管理继续使用独立管理入口。 |
| F4 只读工作区 | 选择企业和账期原来只改变显示。现在通过 Agent 接收经鉴权的查询来源，范围仅供月度只读工具使用。 | 当前明确企业和账期优先。实测工作区为甲企业时，明确查询乙企业仍查乙企业，随后“当前企业”回到已选甲企业。该来源不能授权发票或待办写入。 |

## 3. A/B/C

| 场景 | 模式 | 实际 API 请求 | 数据库与交互证据 | 模型理解 / Harness | 结果 |
| --- | --- | ---: | --- | --- | --- |
| A | 合成 HTTP / Pilot | 0 | A1 无月度 SQL 并追问。A2 SQL 范围 C001 / 2026-09，发票 9,622.06、收入 13,000.50、支出 7,180.74，R001 v1.0，无业务变更。 | 合成回复按脚本提供工具，真实 Harness 和界面通过。 | PASS（离线） |
| B | 合成 HTTP / Pilot | 0 | 自然语言触发 Prepare，默认焦点为取消。模拟确认后 F002 用途为“资料打印”，只增一条成功审计。独立核对 actor、企业、单据、字段、新旧值、编号、指纹和回读。 | 合成提案，真实 Harness 事务通过。 | PASS（离线） |
| C | 合成 HTTP / Pilot | 0 | C1 核对 5 张及 R002 v2.0，C2 经弹窗仅新增任务。三个 Python 进程共享隔离 C 库，C4 修改 F002 后缺项 5→4，C5 仍为同一 U001 的 ACTIVE 任务，未新增重复审计。 | 合成提案，真实管理确认、SQLite 和进程恢复通过。 | PASS（离线） |
| A/B/C | DeepSeek Flash Live | 0 | 预检阶段停止，无 Live 查询、写入或恢复证据。 | 模型理解与 Live Harness 链均未执行。 | BLOCKED_CREDENTIALS |

离线驱动记录了 9 次合成 HTTP 往返，外部请求为 0。C 进程 PID 分别为 35976、16432、37504。脱敏过程、独立库和逐阶段结果保留在本机忽略目录 `artifacts/p0_final_offline/synthetic-6np_nlpk/`。测试弹窗由 `SIMULATED_TEST_USER / Textual Pilot` 操作。

## 4. 七条待办约定

1. **PASS（离线）** 用户归属取可信身份。U002 查看 U001 私人任务返回不可见。实现位于 `app/tasks.py` 的 `manage_task` 和 `task_details`。
2. **PASS（离线）** 对象关联当前工作库、C001、2026-09 及 `missing_purpose`，由持久任务字段与规则解析共同核对。位置同上。
3. **PASS（离线）** 待办备注须保留当前用户原句，具体候选须经确认。Esc 或模型增写备注均未保存。实现位于 `app/tui.py` 的 `confirm_management`。
4. **PASS（离线）** 创建前检查 read 和 modify。U002 不能创建执行型任务，撤销修改权后记录仍在，可读与可执行分离。实现位于 `app/tasks.py`。
5. **PASS（离线）** 待办详情的关联表可点击。内部路由按任务和当前用户重新鉴权，见 `app/tui.py` 的 `task_detail_widgets`、`finance_widgets`。
6. **PASS（离线）** 发票、规则和缺项从当前 SQLite 重算，C5 恢复显示 4 张。返回待办和继续对话复用活跃 Agent，重启时创建新 Agent。见 `task_details`、`Agent.focus_task` 和 TUI 导航。
7. **PASS（离线）** 仍有缺项时完成被拒。通过真实发票事务补齐后任务仍为 ACTIVE，取消完成确认仍为 ACTIVE，仅在当前确认和重查证据成立后才改为 COMPLETED。见 `manage_task` 与 `app/persistence.py`。

## 5. 安全与界面

定向测试覆盖未授权写入、跨企业目标、过期草稿、模型自报授权、重复确认、权限撤销和 SQL 独立核对。未观察到越权写入或意外业务变化。模拟身份始终显式标注。正式库 SHA-256 前后一致，`f190ed7abeacf02d7964439a906e9ae2efe34ec956b2bc4352640549dca19433`。

Textual Pilot 验证了登录、折叠导航、账户与 Profile、输入框、鼠标确认、Tab 聚焦、Enter 默认取消、Esc、后台模型等待、关联表、执行记录和换账号隔离。Windows 窗口控制无法建立连接，实际 Windows Terminal 键鼠与渲染仍为 `NOT_TESTED_ON_WINDOWS`。原 argparse 命令纳入回归。

## 6. API 使用与继续执行

真实请求、输入和输出 Token 均为 0，未发生本轮测试计费。未获得真实 HTTP 或模型协议结果。自动审批拒绝了包含条件式 Live 启动的合并命令，理由是将该命令视为受开发阶段零请求预算限制、可能外发测试数据。随后独立离线预检确认凭据缺失。

在有权使用 Flash 的本机，先通过 TUI 隐藏输入或从安全方式为启动终端配置该 Profile 引用的环境变量。TUI 内输入的值仅对该 TUI 进程有效，独立脚本需在自己的启动终端取得凭据。在 `finance_agent/` 执行：

```powershell
python -m pip install -r requirements.txt
python scripts/verify_p0_tui_live.py --profile shared-flash --preflight
python scripts/verify_p0_tui_live.py --profile shared-flash
```

第一条验收命令仅预检，第二条会产生真实请求。正式驱动使用独立 A/B/C 库、实际 TUI Pilot 和三个 C 进程。共用台账发送前计数，最多 30 次，SDK 重试为 0，传输或协议故障时停止新增请求。由于账户费率与缓存计费拆分未验证，费用标为 UNKNOWN。每次实际尝试的 UTC 时间、场景、Profile、HTTP、协议状态、Token 与累计编号写入本机忽略目录 `artifacts/p0_final_live/`。

## 7. 回归

在 `finance_agent/` 使用上述 Python 3.12.14 环境运行：

| 命令 | 通过 | 失败 | 跳过 |
| --- | ---: | ---: | ---: |
| 基线 `python -m unittest discover -s tests -q` | 400 | 0 | 0 |
| `python -m unittest tests.test_tui_p0 tests.test_architecture -q` | 17 | 0 | 0 |
| 最终 `python -m unittest discover -s tests -q` | 407 | 0 | 0 |

## 8. 最终判定

`P0_BLOCKED`。仍需为可见的 DeepSeek Flash Profile 配置本机凭据并通过 A/B/C 真实验收。Windows Terminal 实机交互须单列复核。
