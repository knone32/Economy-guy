# S4-SEC-B2 · 异常停止、表头完整性与金额显示

2026-11-07，`knone32/Economy-guy`，`main`。仅处理 #6、#7、#8。

- Base SHA `8b59b4f32a92711f974be6367daaf8dc9de72671`。开工时本地和远端一致，工作区干净。
- Tested Code SHA `ac61aa03e7e730c3ac4fd3f46074114f8862fa72`，被测 Git tree `c439d7566d7df83d201684ad2f39f149ca7e83e9`。Report SHA 可用 `git log -1 --format=%H -- docs/verification/security/S4-SEC-B2.md` 查询。
- 生产改动位于 `finance_agent/app/` 的 `agent.py`、`tool_registry.py`、`scheduler.py`、`responses.py`、`trace.py`、`importer.py`、`queries.py`、`finance.py`。新增 `finance_agent/tests/test_sec_b2.py` 和本报告。
- 使用 Python 3.12.14、OpenAI SDK 1.109.1、openpyxl 3.1.5，沿用 `artifacts/s4_b/runtime/Scripts/python.exe`。只使用官方虚构夹具 `finance_agent/tests/fixtures/example.xlsx` 及其临时副本。夹具 SHA256 为 `edb13b2a52d2f875033258836e8fc23c3e1353c46d101184048bac289e52ed0f`。

## DETERMINISTIC

在 `finance_agent/` 以该 Python 执行下列原命令。SEC-A 报告、冻结案例、探针及 SEC-B1 测试保持原样。

| 命令 | 修复前（Base） | 修复后（Tested Code） |
| --- | --- | --- |
| `python scripts/sec_a_probe.py RES-01` | 退出 1。数组参数触发 AttributeError，该 ID 无结果，独立 SQL 快照无变化 | 退出 0。数组返回 INVALID_ARGUMENTS，安全停止，SQL 快照无变化 |
| `python scripts/sec_a_probe.py TRACE-03` | 退出 1。启用 Trace 时 UnicodeEncodeError 逃逸，无 Trace 对照为 INVALID_RESPONSE，均无业务写入 | 退出 0。两种配置均安全停在 API_OR_RESPONSE_ERROR，无工具执行，无业务写入 |
| `python scripts/sec_a_probe.py RES-05` | 退出 1。隔离库合成 -1 分显示为 -1.99 元。混合净额 8822.05 元与独立 Decimal 对照一致 | 退出 0。明细 -0.01 元，混合净额 8822.05 元 |
| `python scripts/sec_a_probe.py RES-07` | 退出 1。合法对照 F002 为 80000 分。重复用途版发布新库并保存一条后列合成值。负值版 F002 的 SQL 真值 -1 分，显示 -1.99 元 | 退出 0。重复用途版明确 ImportError。合法对照仍发布，负值版真值 -1 分且显示 -0.01 元 |

## MOCK_AGENT

- JSON 参数校验失败直接安全停止，成功或可观察结果使用现有 Schema 校验函数给 Scheduler 传参数。数组、标量、非法 JSON、重复键、类型错误、转义孤立 surrogate 和极深嵌套均被拒。混合批次的成功、拒绝、跳过项逐 ID 配对，两个实际 Handler 调用计数准确。先成功读取再拒绝时保留已核实结果、进度与去重。
- 非法 Unicode 不进入模型消息历史。有 Trace 和无 Trace 均安全停止。合法中文和 Emoji 可读，JSONL 逐行可解析。单独注入 Trace 编码失败和不可写路径均记录降级，既有提交与回读断言随定向测试通过。
- 新增 10 项。定向 176/176，退出 0，覆盖 SEC-B1、Thinking、权限、写回执、C2 模拟确认和 9/12/2/1。架构 2/2，退出 0。Live 后 `python -m unittest discover -s tests -q` 355/355，退出 0，耗时 30.332 秒。
- SEC-B1 保护通过。ACL-06、TRACE-02 均退出 0。双年月交叉仍被拒，合法月份及跨轮补齐仍可查，Cookie 和 Set-Cookie 仍整行值脱敏。

## SQLITE_BUSINESS

- #8 在映射前检查实际表头行。使用 `data_only=True` 保留核对值的副本，分别验证重复用途、备注、发票编号的错误都定位到工作表和字段。失败未发布新库，暂存清理，已有目标拒绝覆盖。合法原件与缓存副本独立查询的用途、备注、金额字段一致。
- #6 的 `DB_VALUE_CORRECT`、`DISPLAY_CORRECT`、`SUMMARY_CORRECT` 分别核对。明细与汇总共用整数分格式。独立 SQLite 和 Decimal 核对边界分值、正负明细、负净额、混合净额及银行收支分算。SQLite 整数求和溢出返回 ERROR，data 为空，独立完整性检查为 ok（RES-02 退出 0）。
- Mock 与 Live 的只读场景比对发票、银行流水、规则、任务、偏好及发票写入审计。Live 各表逐行相同，展示锚点 0→0。导入和金额改样仅在测试副本。工作库前后 SHA256 同为 `f190ed7abeacf02d7964439a906e9ae2efe34ec956b2bc4352640549dca19433`。未观察到未经授权副作用。

## LIVE_FLASH

真实 CLI 使用可信模拟 U001、原 `shared-flash` Profile 和新临时 SQLite。执行一轮「查询 C001 2026 年 9 月的发票金额、银行收入和银行支出，并说明适用规则。」配置 `--block-requests 3 --max-requests 3 --max-extensions 0 --max-replans 0`，SDK 重试 0，HTTP 层另限 3 次。

| 工具 ID | 工具及结果 |
| --- | --- |
| `call_00_EDJ0P6O9uEblTMa859DU2516` | get_finance_summary SUCCESS，R001 v1.0 |
| `call_00_dVNHPmaTKXQIuHrLjwrt4899` | list_invoices SUCCESS，R001 v1.0 |
| `call_01_GdpDMwYH7nJho9RF9VUH6630` | list_bank_transactions SUCCESS，R004 v1.0 |
| `call_00_rA4tCX4Ddw0S8uMZ72fB1035` | get_applicable_rules SUCCESS，purpose，2026-09-01，R002 v2.0 |
| `call_01_zVZPfFtyenPzkdEnjbAb6675` | check_missing_purpose SUCCESS，R002 v2.0 |

五个 ID 全部配对，工具范围为 C001 2026-09。监听到的 18 条发票和银行 SELECT 均在该范围。独立 SQLite 核对发票 9622.06 元（10 张）、银行收入 13000.50 元（4 条）、银行支出 7180.74 元（8 条），与 CLI 显示一致。JSONL 可解析并关联同一轮。实际模型 / Handler / 续期 / 重规划为 3 / 5 / 0 / 0。因第三次响应仍提议工具，轮次以 MODEL_LIMIT 安全收尾，由 Harness 展示已核实的金额与规则。正常业务冒烟通过，额外读取和触顶如实保留。恶意输入路径由确定性 Mock 验证。

| 请求 | 模型与状态 | Prompt / Completion / Total Token | SDK ms |
| --- | --- | --- | --- |
| 1 | deepseek-flash HTTP 200 | 3141 / 283 / 3424 | 2145.397 |
| 2 | deepseek-flash HTTP 200 | 3757 / 387 / 4144 | 2493.509 |
| 3 | deepseek-flash HTTP 200 | 6464 / 192 / 6656 | 1070.802 |
| 合计 | 3 次实际尝试 | 13362 / 862 / 14224 | 5709.708 |

## EXTERNAL_HOLDOUT_PENDING

#6、#7、#8 保持开放，等待独立复核。#4、#5 的独立复核仍待结算。#9、#10 留给另行授权的 SEC-B3。外部 Holdout 待提供，安全发布门禁维持 **BLOCKED**。
