# Economy-guy · 初赛 v2.0.2 运行参考

首次安装及双击启动见[首次启动说明](../README-FIRST.md)。下列命令从 `finance_agent/` 运行，使用已安装 `requirements.txt` 的 Python 3.11+。

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

## 工作台与模型

首次运行按项目首页导入官方虚构 Excel，以 U001 登录。建议最大化终端并保持至少 137 列。首次进入工作台时，宽度不足会弹出提示。紧凑模式使用「查看业务历史」查看结果，再选「返回聊天」。达到推荐宽度后，左侧对话和右侧业务历史同时显示。

在「配置 AI 模型」中新建中文或英文 Profile，从主配置区选择地址预设或输入 HTTPS SDK Base URL。填写服务商指定的模型 ID，使用本人 API Key。详情页「检测连接」分别检查基础连接和工具调用，业务仍需在实际模型和评审环境中验证。

选「＋ 新对话」或按 Ctrl+N 开启会话，从左侧「历史会话」重开旧对话。目录支持日期或金额排序，详情与翻页按当前权限重查。左侧「记录」按操作编号提供可展开的工具、规则和审计信息。

## 入口与证据

| 用途 | 入口 |
| --- | --- |
| 工作台 | `python main.py` 或 `python main.py tui`。省略 `--db` 时优先恢复最近使用的账簿。 |
| 兼容数字菜单 | `python main.py home` |
| 查询和审计 | `python main.py summary --help`、`python main.py invoices --help`、`python main.py inspect-update --help` |
| 模型配置 | `python main.py profiles list --user U001`。`profiles check --user U001 --profile <名称>` 校验 Profile 和所引用的环境变量，发送 0 次 API 请求。Windows 已保存密钥由工作台读取。 |
| A/B/C 演示 | 工作台操作见[演示脚本](../docs/delivery/DEMO-SCRIPT.md)。 |
| 连续 CLI 对话 | `python main.py --db data/review-cli.sqlite3 chat --mode mock --user U001`。CLI Mock 用固定查询提案，评审可用根目录 `RUN-MOCK.bat` 打开五类预置请求的离线工作台。 |

Stage 3A 的持久待办和企业偏好保存在业务库。P0.5 工作台可从独立本机会话库恢复聊天及必要只读线索，并重新校验账簿和当前权限。Context Builder 在预算内选择上下文，Reference Resolver 只对实际展示过的对象重查当前数据库。模型循环单轮硬限为 9 次模型请求、12 次实际 Handler 调用、2 次续期、1 次显式重规划。见[v2.0.0 历史架构](https://github.com/knone32/Economy-guy/blob/preliminary-2026-v2.0.0/docs/ARCHITECTURE.md)。

普通对话和演示分别保存脱敏 Trace。Trace 能用于解释执行过程，提交状态以当前 SQLite 的成功审计与回读为准。遇到未知结果，应先核查历史请求编号。

## 离线复核（仅开发源码包）

固定提案演示可运行 `python scripts/demo_stepper.py --mode mock --scenario all`。Mock 与真实模型验收分别记录。

```powershell
python -m unittest discover -s tests -q
python -m unittest tests.test_architecture -v
& .\scripts\check_clean_environment.ps1 -Python (Get-Command python).Source
```

若使用项目首页的虚拟环境，将上面的 Python 路径替换为该环境的解释器。清洁检查需从 Git 克隆运行。它只复制已跟踪文件到独立临时目录，并去除本机导入路径与测试 Excel 环境变量覆盖，再运行全量离线测试。脚本保留临时副本供核对。已存在的项目工作库、日志和本地模型配置不参与复制。
