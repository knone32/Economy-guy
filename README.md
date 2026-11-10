# Economy-guy · 财税 Agent 工作台 · 初赛 v2.0.0

Economy-guy 是云帐房 2026 AI 技术创新大赛赛题二的初赛原型。工作台用自然语言查询发票与银行流水、核查用途规则，并通过人工确认修改发票用途或备注、保存和恢复缺用途待办。Python 和 Textual 提供交互界面，SQLite 保存业务事实与成功审计，Agent Harness 控制工具调用、范围和权限。

## Windows PowerShell 启动

需要 Windows、Python 3.11 或更新版本和可访问模型服务的网络。运行包是 Python 项目，需安装依赖。建议最大化 PowerShell、CMD 或 Windows Terminal，使终端达到 **137 列**。解压后从包含本 README 的目录打开 PowerShell，运行以下命令。

~~~powershell
cd finance_agent
python -m venv .venv
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install -r requirements.txt
& $py main.py --db data/preliminary-demo.sqlite3
~~~

1. 在账簿页选择「从 Excel 创建新账簿」。输入 `tests/fixtures/example.xlsx` 和新目标 `data/preliminary-demo.sqlite3`，点击「校验并创建新账簿」并确认。程序导入官方 1.1.0 虚构数据并初始化迁移与规则。目标已存在时换一个新路径，或选择打开已有库。
2. 选择比赛模拟账号 `U001`。它可以读取和修改样例中的两家企业。用 `U002` 可观察甲企业只读及乙企业越权拒绝。
3. 点击「配置 AI 模型」新建或选择 Profile，名称可以用中文。按服务商填写 Provider、模型 ID 和主配置区的 HTTPS **SDK Base URL**，末尾省略 `/chat/completions`。可选 DeepSeek、OpenAI、硅基流动、阿里百炼等地址预设，或手动填写。例如百炼可选「OpenAI 兼容」，填 `qwen3.8-max-0902`、账号地域对应的地址和 `standard` 协议。使用你自己的 API Key，并先核对模型访问权、额度及计费。密钥可仅本次使用或存入 Windows 凭据管理器。
4. 在 Profile 详情主动点击「检测连接」，查看基础连接和 Function Calling 各自的结果，再选「使用此 AI」。检测最多发送两次请求，可能消耗额度。
5. 输入「汇总甲企业 2026 年 9 月的发票价税合计、银行收入和支出」。双栏左侧是对话，右侧是业务结果与历史。首次登录时宽度不足会弹出提示。选择继续紧凑模式后，通过「查看业务历史」打开查询结果，再点「返回聊天」。拉宽至 137 列即可恢复双栏。
6. 按[演示脚本](docs/delivery/DEMO-SCRIPT.md)验收查询、受控修改和待办恢复。通过左侧「记录」展开操作编号，查看工具、规则、确认、提交和回读证据。「＋ 新对话」或 `Ctrl+N` 可新开对话，「历史会话」可重开旧对话。

更多启动和迁移命令见[运行参考](finance_agent/README.md)。

## 初赛能力与边界

- R001 分别汇总发票金额、银行收入和银行支出。发票目录每页 10 张，支持按日期或金额升降序，金额排序在 SQLite 分页前完成。指代按已展示的顺序重查。
- R002、R003 核查 2026 年 9 月的适用规则。全年用途空值仅描述字段状态。R004 银行流水只读，也无法据此判断某张发票是否已付款。
- 发票写入仅限用途和备注。先查看变更预览，再由真人确认，以 SQLite 事务审计及回读核验结果。待办也需真人确认，可退出后在同一账簿和账号下继续。
- Excel 是只读种子。包内没有预生成 SQLite、真实凭据或私人会话。录屏和分发仅使用独立虚构账簿及脱敏证据。

比赛模拟账号用于演示权限。作品范围限于账簿内业务处理，真实税务申报和银行支付不在其中。连接检测只覆盖基础文本和工具调用。v2.0.0 的完整 Live 验收以评审环境和实际模型结果为准，历史验收见 [v1.0.0 真人记录](https://github.com/knone32/Economy-guy/blob/preliminary-2026-v1.0.0/docs/delivery/LIVE-ACCEPTANCE.md)。

## 交付包

- **初赛运行包**包含运行源码、依赖、空模型模板、虚构样例和演示材料，适合评审直接解压运行。
- **开发源码包**另含工程测试源码、开发脚本、架构与历史记录，适合后续研发。

[v2.0.0 GitHub Release](https://github.com/knone32/Economy-guy/releases/tag/preliminary-2026-v2.0.0) · [发布及校验说明](docs/delivery/PRELIMINARY-RELEASE.md) · [初赛设计](docs/delivery/SUBMISSION-DESIGN.md)
