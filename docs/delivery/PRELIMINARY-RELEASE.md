# 初赛发布 · preliminary-2026-v2.0.0

冻结标识为 annotated tag `preliminary-2026-v2.0.0`。两个 ZIP 均从该 Tag 对应的同一提交构建，包根目录 `VERSION.txt` 的 `source_sha` 可用 `git rev-parse "preliminary-2026-v2.0.0^{commit}"` 核对。

| 下载文件 | 用途 |
| --- | --- |
| `Economy-guy-Preliminary-2026-v2.0.0.zip` | 评审运行。含 Python 运行源码、依赖清单、配置模板、官方虚构 Excel 和启动及演示说明 |
| `Economy-guy-Developer-Source-v2.0.0.zip` | 工程审阅。另含测试源码、开发脚本和架构资料 |
| `SHA256SUMS.txt` | 两个 ZIP 的 SHA-256 |

从 [GitHub Release](https://github.com/knone32/Economy-guy/releases/tag/preliminary-2026-v2.0.0) 下载后，在 PowerShell 执行 `Get-FileHash -Algorithm SHA256 -LiteralPath <ZIP 路径>`，与校验清单比对。按[项目首页](../../README.md)安装 Python 3.11+ 依赖并导入 `finance_agent/tests/fixtures/example.xlsx`。发布包包含虚构 Excel 种子，账簿与模型密钥由评审在本机创建和配置。

建议终端至少 137 列。低于该宽度时，通过「查看业务历史」访问结果。左侧「记录」可按操作编号展开工具、规则和审计信息。模型检测与业务验收分别进行，评审可按[演示脚本](DEMO-SCRIPT.md)验证查询、修改与待办恢复。

[v1.0.0 发布说明](https://github.com/knone32/Economy-guy/blob/preliminary-2026-v1.0.0/docs/delivery/PRELIMINARY-RELEASE.md)与[原发布资产](https://github.com/knone32/Economy-guy/releases/tag/preliminary-2026-v1.0.0)供历史查阅。
