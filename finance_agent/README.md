# Economy-guy · 运行参考

首次安装、启动和评审入口见[项目首页](../README.md)。下列命令从 `finance_agent/` 运行，使用已安装 `requirements.txt` 的 Python 3.11+。

## 命令行初始化及升级

新建独立虚构工作库，显式给出 Excel 来源。`init` 完成基础导入，后续迁移补齐审计、规则、任务、偏好和引用结构。`--db` 位于子命令之前。

```powershell
python main.py --db data/review-cli.sqlite3 init --excel tests/fixtures/example.xlsx
python main.py --db data/review-cli.sqlite3 migrate-stage2
python main.py --db data/review-cli.sqlite3 migrate-stage3
python main.py --db data/review-cli.sqlite3 migrate-stage3b
python main.py --db data/review-cli.sqlite3 rules seed --simulate-rule-manager
python main.py --db data/review-cli.sqlite3
```

不指定 `--excel` 时，`init` 使用仓库已有的虚构夹具。导入拒绝覆盖现有库。已有账簿推荐用 TUI「查看升级内容 → 备份并升级」。也可先备份，再执行上述三个迁移。对缺少种子规则的隔离样例库，单独运行 `rules seed`。规则管理员模拟授权独立于发票修改权限。`rules find`、`rules import` 和 `rules disable` 的参数见 `python main.py rules --help`。

## 入口与证据

| 用途 | 入口 |
| --- | --- |
| 工作台 | `python main.py` 或 `python main.py tui`。省略 `--db` 时优先恢复最近使用的账簿。 |
| 兼容数字菜单 | `python main.py home` |
| 查询和审计 | `python main.py summary --help`、`python main.py invoices --help`、`python main.py inspect-update --help` |
| 模型配置 | `python main.py profiles list --user U001`。`profiles check --user U001 --profile <名称>` 校验 Profile 和所引用的环境变量，发送 0 次 API 请求。Windows 已保存密钥由工作台读取。 |
| A/B/C 演示 | `python scripts/demo_stepper.py --mode mock --scenario all`。固定提案验证业务与交互，真实模式须明确选用。 |
| 连续 CLI 对话 | `python main.py --db data/review-cli.sqlite3 chat --mode mock --user U001`。CLI Mock 用固定查询提案，TUI 的「固定脚本测试」提供有限查询示例。 |

Stage 3A 的持久待办和企业偏好保存在业务库。P0.5 工作台可从独立本机会话库恢复聊天及必要只读线索，并重新校验账簿和当前权限。Context Builder 在预算内选择上下文，Reference Resolver 只对实际展示过的对象重查当前数据库。模型循环单轮硬限为 9 次模型请求、12 次实际 Handler 调用、2 次续期、1 次显式重规划。见[现行架构](../docs/ARCHITECTURE.md)。

普通对话和演示分别保存脱敏 Trace。Trace 能用于解释执行过程，提交状态以当前 SQLite 的成功审计与回读为准。遇到未知结果，应先核查历史请求编号。

## 离线复核

```powershell
python -m unittest discover -s tests -q
python -m unittest tests.test_architecture -v
& .\scripts\check_clean_environment.ps1 -Python (Get-Command python).Source
```

若使用项目首页的虚拟环境，将上面的 Python 路径替换为该环境的解释器。清洁检查从当前 Git 工作区仅复制已跟踪文件到独立临时目录，并去除本机导入路径与测试 Excel 环境变量覆盖，再运行全量离线测试。脚本保留临时副本供核对。已存在的项目工作库、日志和本地模型配置不参与复制。
