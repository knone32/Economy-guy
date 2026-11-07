# Economy-guy · 财税 Agent 工作台

用自然语言查询发票与银行流水，由 Harness 校验范围、权限和规则，并通过可核查的确认流程修改发票用途或备注。

这是云帐房 2026 AI 技术创新大赛赛题二的初赛原型，覆盖查询与规则依据、受控修改、持久待办三条业务链。工作台还支持发票目录分页、会话恢复、历史对象重查以及个人与企业偏好。见[官方赛题二](https://aicxds.yunzhangfang.com/challenge-02.html?v=20261016-6)。

## 三分钟启动

在 Windows PowerShell 的交互终端中，从仓库根目录运行。需要 Python 3.11 或更新版本。

```powershell
cd finance_agent
python -m venv .venv
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install -r requirements.txt
& $py main.py --db data/review.sqlite3
```

首次启动时，在账簿选择页找到「从 Excel 创建新账簿」。填入 `tests/fixtures/example.xlsx` 和新路径 `data/review.sqlite3`，点击「校验并创建新账簿」并确认。工作台会执行所需迁移并初始化规则。仓库已有夹具来自官方 1.1.0 虚构示例。若使用主办方提供的其他样例，将 Excel 路径改为你有权使用的本地文件。目标库已存在时，选择打开已有库或指定新路径。

选择模拟账号 `U001` 后，可直接浏览发票和待办。`U002` 可用于观察只读权限。已有旧账簿可通过「查看升级内容 → 备份并升级」补齐结构。规则缺失时可单独初始化。命令行导入和升级步骤见[运行参考](finance_agent/README.md)。

## 配置模型或离线演示

- **先看 A/B/C**。在同一 PowerShell 窗口运行 `& $py scripts/demo_stepper.py --mode mock --scenario all`。用 Enter 或空格逐步查看查询、确认修改和跨进程恢复待办。演示使用独立虚构库及模拟确认。[交互演示说明](docs/delivery/INTERACTIVE_DEMO.md)
- **体验自然语言**。在工作台点击「配置 AI 模型」，选择已授权的 Profile，或新建个人配置，填入服务商、模型、HTTPS 端点和密钥环境变量名。密钥可由该环境变量提供，也可在界面隐藏输入。Windows 支持选择系统凭据管理器保存。仓库模板为空，配置检查本身不调用 API。发送真实 AI 消息才联网。[工作台指南](docs/delivery/P0-AGENT-WORKSPACE.md)

## 架构与安全

Python 驱动 Textual 工作台，通过 OpenAI-compatible Tool Calling 使用一个 LLM。单一 Agent 循环经 Tool Registry 调用业务服务，SQLite 保存当前数据、规则、待办和成功审计。Context Builder 选择必要历史，Trace 记录脱敏执行证据。规则管理走独立模拟管理员入口。

账号及权限由比赛模拟会话和账簿决定。模型只能提出工具调用与写入草稿。财务修改仅限用途、备注，经用户确认、事务审计及回读才认定结果。银行流水只读，恢复会话后需要重新核验权限和业务数据。请仅在隔离账簿中演示，凭据留在本机。

## 验收与交付资料

- [初赛设计说明](docs/delivery/SUBMISSION-DESIGN.md)与[提交清单](docs/delivery/SUBMISSION-CHECKLIST.md)。
- [P0 最终记录](docs/delivery/P0-FINAL-CLOSURE.md)包含离线 A/B/C 闭环。完整真实 TUI A/B/C 仍待验收。
- [P0.5 真实验收](docs/delivery/P0-5-FINAL.md)中 DeepSeek L1–L3 通过，L4 偏好持久化通过，简洁表达检查未通过。官方 Qwen3.8-Max 兼容性尚待验证。评审模型见[主办方公告](https://m.saikr.com/contest/notice_detail/50275)。
