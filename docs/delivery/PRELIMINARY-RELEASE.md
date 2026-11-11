# 初赛 v2.0.2 交付与校验

两份交付包从同一 Git 提交构建。解压后打开根目录的 `VERSION.txt`，以 `source_sha` 核对实际冻结提交。

| 文件 | 内容 |
| --- | --- |
| `Economy-guy-Preliminary-2026-v2.0.2.zip` | 启动器、运行源码、依赖清单、空配置模板、官方虚构 Excel、设计说明和演示稿 |
| `Economy-guy-Developer-Source-v2.0.2.zip` | 另含工程测试源码、开发脚本及架构参考 |
| `SHA256SUMS.txt` | 两个 ZIP 的校验值 |

在 PowerShell 用 `Get-FileHash -Algorithm SHA256 -LiteralPath <ZIP 路径>` 核对摘要。完整解压后双击 `START.bat`，按[首次启动说明](../../README-FIRST.md)导入示例并配置自己的模型。按[录屏稿](DEMO-SCRIPT.md)完成真人验收，当前证据见[运行证据说明](CONTEST-EVIDENCE.md)。

远端同名标签已绑定旧提交 `f38eb06cb693914a5e115f67b359f5ee031992c6`。本次冻结产物以包内提交和校验值为准，作为本地交付。 [历史 v2.0.2 发布](https://github.com/knone32/Economy-guy/releases/tag/preliminary-2026-v2.0.2) · [历史 v2.0.0 发布](https://github.com/knone32/Economy-guy/releases/tag/preliminary-2026-v2.0.0)
