# Economy-guy · 财税 Agent 工作台

Economy-guy 是云帐房 2026 AI 技术创新大赛赛题二的初赛原型。工作台用自然语言查询发票与银行流水、核查用途规则，并通过人工确认修改发票用途或备注、保存和恢复缺用途待办。Python 和 Textual 提供交互界面，SQLite 保存业务事实与成功审计，Agent Harness 控制工具调用、范围和权限。

## Windows PowerShell 启动

需要 Python 3.11 或更新版本、交互式 Windows Terminal，以及可调用指定 Qwen 模型的百炼账号。解压初赛运行包后，从解压目录运行：

~~~powershell
cd finance_agent
python -m venv .venv
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install -r requirements.txt
& $py main.py --db data/preliminary-demo.sqlite3
~~~

1. 在账簿页选择「从 Excel 创建新账簿」。输入 `tests/fixtures/example.xlsx` 和新目标 `data/preliminary-demo.sqlite3`，点击「校验并创建新账簿」并确认。程序导入官方 1.1.0 虚构数据并初始化迁移与规则。目标已存在时换一个新路径，或选择打开已有库。
2. 选择比赛模拟账号 `U001`。它可以读取和修改样例中的两家企业。用 `U002` 可观察甲企业只读及乙企业越权拒绝。
3. 点击「配置 AI 模型」，新建或选择已有 Profile。服务商选 **OpenAI 兼容**，模型填 `qwen3.8-max-0902`，高级设置使用百炼控制台提供的 HTTPS Base URL，路径保留 `/compatible-mode/v1`，协议选 `standard`。在隐藏字段填入你自己的 API Key，可选择仅本次使用或 Windows 安全保存。保存配置后显示未验证属正常，发送消息才联网。发送前请核对模型访问权与额度。
4. 在聊天输入「汇总甲企业 2026 年 9 月的发票价税合计、银行收入和支出。」需要另开会话时，选左侧「＋ 新对话」或按 `Ctrl+N`。已归档会话可从「账户 → 我的对话」重开。

更多启动和迁移命令见[运行参考](finance_agent/README.md)。

## 初赛能力与边界

- R001 分别汇总发票金额、银行收入和银行支出。发票目录每页 10 张，支持按日期或金额升降序，金额排序在 SQLite 分页前完成。指代按已展示的顺序重查。
- R002、R003 核查 2026 年 9 月的适用规则。全年用途空值仅描述字段状态。R004 银行流水只读，也无法据此判断某张发票是否已付款。
- 发票写入仅限用途和备注。先查看变更预览，再由真人确认，以 SQLite 事务审计及回读核验结果。待办也需真人确认，可退出后在同一账簿和账号下继续。
- Excel 是只读种子。包内没有预生成 SQLite、真实凭据或私人会话。录屏和分发仅使用独立虚构账簿及脱敏证据。

核心业务和 C/D 多轮交互已有用户真人 Qwen 验收。金额排序、一级新对话及本次窄屏修饰仍待真人确认。见[真人验收记录](docs/delivery/LIVE-ACCEPTANCE.md)和[录制脚本](docs/delivery/DEMO-SCRIPT.md)。

## 交付包

- **初赛运行包**包含运行源码、依赖、空模型模板、虚构样例和演示材料，适合评审直接解压运行。
- **开发源码包**另含工程测试源码、开发脚本、架构与历史记录，适合后续研发。

[GitHub Release](https://github.com/knone32/Economy-guy/releases/tag/preliminary-2026-v1.0.0) · [初赛冻结分支](https://github.com/knone32/Economy-guy/tree/release/preliminary-2026-v1) · [发布及校验说明](docs/delivery/PRELIMINARY-RELEASE.md) · [初赛设计](docs/delivery/SUBMISSION-DESIGN.md)
