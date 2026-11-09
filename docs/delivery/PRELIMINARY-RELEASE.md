# 初赛发布 · preliminary-2026-v1.0.0

- 冻结日期 2026-11-10。冻结分支为 `release/preliminary-2026-v1`，annotated tag 为 `preliminary-2026-v1.0.0`。
- 两包均以冻结 Tag 指向的同一提交构建。**冻结源码 SHA** 以 ZIP 根目录 `VERSION.txt` 的 `source_sha` 为准。在 Git 克隆中可用 `git rev-parse "preliminary-2026-v1.0.0^{commit}"` 读取相同值。
- 下载和 SHA-256 校验见 [GitHub Release](https://github.com/knone32/Economy-guy/releases/tag/preliminary-2026-v1.0.0)。

| 本地生成路径 | 用途 |
| --- | --- |
| `dist/preliminary-2026-v1.0.0/Economy-guy-Preliminary-2026-v1.0.0.zip` | 初赛运行。仅包含运行源码、资源、虚构 Excel 和必要说明 |
| `dist/preliminary-2026-v1.0.0/Economy-guy-Developer-Source.zip` | 后续研发。包含 Git 跟踪的开发源码、测试、工具和历史文档 |
| `dist/preliminary-2026-v1.0.0/SHA256SUMS.txt` | 两个 ZIP 的 SHA-256 校验值 |

解压后按[项目首页](../../README.md)安装依赖并导入 `finance_agent/tests/fixtures/example.xlsx`。它是比赛官方 1.1.0 虚构数据的已跟踪副本，包含两家虚构企业、两个模拟账号、40 张发票及 48 条银行流水。初赛包不含预生成账簿；不要用真人验收库覆盖导入目标。模型密钥由使用者在本机提供。

在 PowerShell 执行 `Get-FileHash -Algorithm SHA256 -LiteralPath <ZIP 文件路径>` 并与 `SHA256SUMS.txt` 比较。此核对只确认下载文件内容。真人验收范围见[验收记录](LIVE-ACCEPTANCE.md)。

后续开发从 `main` 继续。若需修订初赛交付，使用独立提交及新版本 Tag，保持本版引用与资产固定。
