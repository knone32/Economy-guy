# Economy-guy 交互演示

在 Windows PowerShell 中进入仓库的 `finance_agent` 目录，使用装有 `requirements.txt` 依赖的 Python 3.11 或更新版本。

```powershell
python scripts/demo_stepper.py --mode mock --scenario all
python scripts/demo_stepper.py --mode live --profile shared-flash --scenario all
```

`--scenario A`、`B`、`C` 可单独运行，默认 `all`。Mock 使用固定模型提案走正式 Agent，验证交互、权限、事务和数据库结果。Live 发送实际请求，模型可能追问、选错工具或提早停止，每次运行保留真实结果。

Live 默认选用现有 `shared-flash` Profile。它须通过现有 Profile 管理配置，绑定 `deepseek-flash`、`https://api.deepseek.com` 和本机授权的凭据环境变量。可以用 `python main.py profiles list --user U001` 查看 Profile 元数据，或给演示器传入 `--profiles-file` / `--profiles-local` 选择已有配置。缺失、无权使用或绑定不符时显示 `BLOCKED`。只有显式选择 `--mode live` 才会消耗 API。

- **Enter / Space** 推进一步。Windows PowerShell 的交互控制台可直接按空格。其他终端使用 Enter。
- **Q / Ctrl+C** 安全退出或中断，已核实的结果仍保存在该次运行目录。
- 出现 **SIMULATED_TEST_USER** 时先核对屏幕上的具体内容，再推进。演示器按本轮身份、权限、对象、内容、草稿编号和指纹模拟一次确认，仍走正式事务及回读。生产 CLI 仍要求正式人工确认。

| 场景 | 演示内容 |
| --- | --- |
| A | C001 缺年月时追问，补充 2026-09 后核对发票和银行金额、数量、规则及对话收尾。 |
| B | 由模型提出 F002 用途草稿，展示后模拟确认。独立核对 Commit、审计和回读，再检查重复请求的 `CURRENT_VALUE_MATCHES`。 |
| C | 核实 5 张缺项并经具体确认创建待办。两次实际启动新 Python 进程，以相同任务 ID 分别读到 5 张和 4 张缺项。 |

每次运行都用官方虚构 Excel 夹具和正式迁移，为所选场景建立各自的 SQLite 库。成功、部分完成、失败和阻塞显示为 `PASS`、`PARTIAL`、`FAIL`、`BLOCKED`，被跳过的依赖步骤在报告中标为 `NOT_TESTED`。Live 批次最多 24 次实际 HTTP 请求尝试，发送前写入子进程共用的 SQLite 台账。失败也计入，SDK 自动重试为 0。每一步的模型请求上限为 1–3，沿用 Harness 的 9 / 12 / 2 / 1 安全硬限。

启动时会打印运行目录。每次运行保存在 Git 忽略的 `artifacts/demo_runs/run-*/`。先看 `summary.md`，其中有场景判定、最终 SQLite 事实、业务变化、模拟确认次数、HTTP 状态和可观测 Token 用量。需要复核时用 `steps.jsonl` 和脱敏 `trace_*.jsonl` 查看工具 ID、查询范围、Harness 停止原因和耗时。用量无法观测时标为未知。开发验证使用 Mock，真实模型表现及可录屏条件由用户启动 Live 后实际核对。
