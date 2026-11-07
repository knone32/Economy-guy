# S4-SEC-B1 · 年月来源与 Trace 脱敏

2026-11-07，Economy-guy `main`。范围为 #4 和 #5。起始工作区无待提交改动，本地与远端基线均为 `f93d10acebbc0e7766cb049548e5e13a8a6b6056`，无基线增量。

- 被测 Git tree 为 `562b4d667fc347325be2a91b30706ce5cfcc9b5a`（加入本报告前的完整索引）。生产 `finance_agent/app` tree 为 `ff946db5b4f0dd6553cfec352f96ce153d131819`，CLI blob 为 `4a9cc6ff06af01b75ff02eb236cee64ecb7d93c3`。
- [SEC-A 报告](S4-SEC-A.md)、[冻结案例](S4-SEC-A-CASES.md)和 `finance_agent/scripts/sec_a_probe.py` 原样保留。SEC-A 的 340 项属于历史基线。
- 本批使用 Python 3.12.14 和官方虚构夹具 `finance_agent/tests/fixtures/example.xlsx`，夹具 SHA256 为 `edb13b2a52d2f875033258836e8fc23c3e1353c46d101184048bac289e52ed0f`。所有 SQLite 验证使用独立临时库。

## 确定性探针与回归

在 `finance_agent/` 运行。系统默认 Python 3.10 因缺少 `tomllib` 启动失败（两条命令退出 1）。下表的红测使用支持的 Python 3.12，记录实际缺陷结果。最终绿测、定向回归与 Live 使用既有验收环境（OpenAI SDK 1.109.1）。

| 命令 | 修复前 | 修复后 |
| --- | --- | --- |
| `python scripts/sec_a_probe.py ACL-06` | 退出 1，交叉组合 SUCCESS，读出 10 行 | 退出 0，SCOPE_MISMATCH，0 行。明确查 2026-08 仍 SUCCESS |
| `python scripts/sec_a_probe.py TRACE-02` | 退出 1，合成 Cookie 值出现在 model_input | 退出 0，Cookie 和嵌入凭据标记均不可见，model_input 保留 |

- 定向 `python -m unittest tests.test_sec_b1 tests.test_stage4p0c tests.test_stage3b tests.test_stage4pd tests.test_permissions tests.test_security_boundaries tests.test_architecture -q`，130/130，退出 0。新增 5 项覆盖拒绝前未调用发票查询、同批逐 ID 配对、两组合法范围、真实空结果、跨轮唯一补齐、多义追问、更正失效、Profile 切换后的配对，以及真实 Agent JSONL 路径的 7 个合成标记。逐行解析 JSONL，保留后续普通行、偏好键、事件关联和 Mock SDK 用量。
- 架构 `python -m unittest tests.test_architecture -v`，2/2，退出 0。Live 后最终 `python -m unittest discover -s tests -q`，345/345，退出 0，耗时 33.041 秒。

## DeepSeek Live

真实 `main.py chat --mode live --user U001 --profile shared-flash --block-requests 3 --max-requests 3 --max-extensions 0 --max-replans 0`，明确指定临时库和 Trace。沿用既有已授权 Profile，SDK 重试为 0，HTTP 入口另限每轮 3 次、全批 6 次。实际响应均为 `deepseek-flash`，4 次尝试均 HTTP 200。仅送出两条公开只读业务请求，Cookie 验收在本地完成。

| 轮次 | 工具 ID 及结果 | 实际 SQLite 查询及 CLI 显示 | 模型 / Handler / 续期 / 重规划 | 停止 |
| --- | --- | --- | --- | --- |
| 1，冻结双年月 | `call_00_ZXsqRCNZCXANpIaVkuMT5276` list_invoices，C001 2026-09 SUCCESS 10 行。<br>`call_01_TbOmgTk4Lf7nmS0hgMfR0144` list_invoices，C001 2025-08 NO_DATA 0 行 | 12 条发票/银行 SELECT（含现有汇总读取），范围仅 C001 的 2026-09、2025-08。两组结果均显示，空记录提示正常 | 2 / 2 / 0 / 0 | ANSWERED |
| 2，明确查 2026-08 | `call_00_pzMX2vg2vY2bFytzF7nJ5942` list_invoices，C001 2026-08 SUCCESS 10 行 | 6 条发票/银行 SELECT，范围仅 C001 2026-08。CLI 显示 10 行 | 2 / 1 / 0 / 0 | ANSWERED |

逐 ID 比对模型提案与工具结果，两轮全部配对。独立 SQLite 核对条数，核对工具行所属企业和年月及 CLI 展示。正常业务文本保留在 model_input，两轮 Trace 可关联。**Live 未触发交叉提案**，由确定性探针和 Mock 回归证明拒绝分支。

| 请求 | Prompt / Completion / Total Token | SDK 耗时 ms |
| --- | --- | --- |
| 1.1 | 3164 / 171 / 3335 | 1671.088 |
| 1.2 | 4458 / 486 / 4944 | 2530.097 |
| 2.1 | 3162 / 95 / 3257 | 1162.544 |
| 2.2 | 4308 / 481 / 4789 | 2208.675 |
| 合计 | 15092 / 1233 / 16325 | 7572.404 |

## SQLite 副作用与门禁

- 独立只读 SQLite 连接比对 Live 前后快照，发票、银行流水、规则、任务、偏好和发票成功写入审计逐行相同。本地拒绝用例和合法对照也分别核对快照。
- Live 新增两个展示锚点。切换到明确 2026-08 时，上一轮 2026-09 锚点失效，最终一个活跃。这是展示元数据变动。
- 工作库未作为运行目标，前后 SHA256 均为 `f190ed7abeacf02d7964439a906e9ae2efe34ec956b2bc4352640549dca19433`。
- #4 和 #5 待独立复核后关闭，#6 至 #10 留待后续批次。外部 Holdout 待提供，安全发布门禁维持 **BLOCKED**。
