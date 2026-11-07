# S4-SEC-B4 · 安全最终回归与官方三场景 Live 验收

2026-11-07，`knone32/Economy-guy`，`main`。

- Base 与生产源码 SHA `1ef3cbe293198d0656bcb27c51a040187bce69b1`。开工本地与远端一致，工作区干净。Tested Code SHA `e834bbb961030c0671d788bc629026031078f743`，含测试辅助与冻结案例，生产 `finance_agent/app/` 和 `main.py` 相对 Base 无差异。
- Report SHA 用 `git log -1 --format=%H -- docs/verification/security/S4-SEC-B4.md` 查询。
- 首次 Live 前冻结 [PUBLIC_LIVE_REGRESSION 案例](S4-SEC-B4-LIVE-CASES.md)，SHA256 `54ea2c334f53f5c72d7ccc00d48218a21c52e4ad1ff54a9fa8f31fc52649c8e7`。驱动 `finance_agent/scripts/verify_sec_b4.py` SHA256 `29616c8a8fc656d7df49b8ceeb85f53ba597599925b5b0813cd94f5c2e4a6d25`。首次运行后两者未改，原 SEC-A 探针及历史记录保留。

## 分层结算

| 层 / 场景 | 结果 | 证据 |
| --- | --- | --- |
| D / 安全 | PASS | 原八条探针均退出 0，含 SEC-B3 审计内容断言的定向 65/65。最终全量 363/363，退出 0，32.813 秒 |
| L / A | PARTIAL | A1 模型猜 2026-09，工具 AMBIGUOUS。Harness 提示「请提供年份和月份」，月度业务 SQL 为 0。A2 跨轮补齐后 ANSWERED，R001 v1.0 和金额/数量完整 |
| L / B | PARTIAL | B1 真实 Prepare、绑定确认、一次 COMMITTED 和新连接回读通过。BQ 再读成功。B2 无重复写入，可信回执为 NOT_SUBMITTED，未达到要求的已匹配回执 |
| L / C1–C6 | PARTIAL | 持久任务及两次重启链完整通过，C2 使用本次模拟确认。C5 独立答复未显示请求的下一步说明，C4 的提交后进度回执已显示该说明 |
| L / 偏好 | PASS（业务） | 真实模型完成 create/get/update/delete/get，五轮均在冻结轮限处 MODEL_LIMIT，由 Harness 展示真实结果，最终查无记录 |
| D+B / H2 | PASS | U002 的不可信 Prepare 提案 h2-denied 对应 DENIED，实际 Handler 1，库无变化、无草稿、无成功审计。Live API 0 |
| E / 外部 Holdout | PENDING | 本批全为公开回归。真实人工 C2 确认为 NOT_TESTED / USER_DEFERRED |

**S4-SEC-B4 = PARTIAL，SEC-B 工程门禁 PASS，官方 P0 Live 门禁 PARTIAL，安全发布门禁 BLOCKED。** 本轮结果与历史 SEC-A、4P-E、4P0C 的记录分别保留。

## B · 独立 SQLite 与确认

- A 的独立整数分 SUM/COUNT 为发票 962206/10、银行收入 1300050/4、支出 718074/8，与真实工具和 CLI 一致。A2 实际月度发票/银行 SELECT 共 12 条，范围仅 C001/2026-09。A 的业务表无变化。
- B 与 C 各唯一成功发票审计，均为 U001/C001/F002/purpose，null→「项目资料核对」，与实际草稿指纹相符。B1 与 C4 回执 COMMITTED 且 readback_verified=true。B2 真实 get_invoice 读到新值，但没有独立已匹配回执。隔离 Mock 最小复现用相同库初态和同一个合法 get_invoice。请求中的「用途修改为」得到 NOT_SUBMITTED，仅改为「用途改为」即得到 CURRENT_VALUE_MATCHES。两者均只新增展示锚点，发票成功审计 0。根因在 `write_coordination.py` 的字面匹配动词范围，沿用 Issue #3 跟踪。
- C2 真实任务为 `9d0b864480e84b1594cccdb1bb96d1eb`，C001/2026-09，ACTIVE。候选说明为「把这些还没有补完用途的发票记成一个待办，我下次继续处理（C001 2026年9月尚未填写用途的发票）」。既有策略核对权限、唯一 R002 v2.0、缺 5、无旧对象、完整词法及本轮指纹，通过后仅输入当前请求的确认。历史 C2 许可未复用。
- C1/C3 独立 SQL 缺项为 F002、F004、F003、F006、F009。C4 提交后 C5/C6 为 F004、F003、F006、F009，任务记录仍相同。C1–C2 PID **2656**，C3–C5 PID **30328**，C6 PID **11156**，均为独立启动的 CLI Python 进程且退出 0。两次重启后的草稿和确认初值均 0。C5 模型最终文本含下一步提示，CLI 仅展示任务和缺项。此前 C4 的可信进度输出包含下一步。
- P 只改变 U001/C001/reply_format，状态为无记录→简洁→条目式→无记录，P2 读回简洁，P5 真实工具为 NOT_FOUND。C 与 P 的管理确认、B/C 的草稿确认均由 **SIMULATED_TEST_USER** 提供。无 SQL 替代 Live 写入。
- A/B/C/P/H2 五库 `PRAGMA integrity_check` 均为 ok。银行、规则、规则管理审计、权限及非目标发票均无变化。允许的展示锚点增量 A +2、B +2、C +4、P/H2 0。无未经授权业务变更。工作库和官方夹具前后 SHA256 分别保持 `f190ed7abeacf02d7964439a906e9ae2efe34ec956b2bc4352640549dca19433` 和 `edb13b2a52d2f875033258836e8fc23c3e1353c46d101184048bac289e52ed0f`。

| 确认轮 | 实际 request_id | 独立重算并核对的 fingerprint |
| --- | --- | --- |
| B1 | `685ee908c14f4dab9a09d9c0eafe2d5a` | `1b885af06a8bb3693ab34ff2079119bdb31b7105d1c3fccffba08737d07d8d15` |
| C2 | `fde51983a8744788a6d82366e7b303c9` | `3d6827b92ecc4d3f04a8929ae83c4a7a499e1c22f85209768dc4a67331e7f972` |
| C4 | `1a97a68899014133a3598c9b8e26b786` | `97a1aa226fc55de542546a00c65a8fcfe38b770421f99e28e67f7cbb32f0a937` |
| P1 | `eaf493a917484e19b2e70dd3e1eb7925` | `6f6fe871ff6e71c8877d41c66082d5d5ff5e00f9f9d4e067f0348adc22749b82` |
| P3 | `b24693fdeca1411c97c3b4f1568ec029` | `8bcf010cb40bd7058ad84d2726b9f4378a4dddcafb2d775d0b15b3db7b8c98f6` |
| P4 | `fab7e28674d64c74bb4d814232de4306` | `b192a21da1ad3e10138722b7df51407e064c0adbd01eb7ddac3bc955be0a4653` |

## L · 工具配对和请求计量

沿用 shared-flash，SDK 自动重试 0，Pro 0，未切换账户或模型。发送前由跨进程 SQLite 账本原子占用预算，离线演练证实单轮上限、批次第 31 次及失败计数。实际 **27** 次全部 HTTP 200，A/B/C/P 分别 4/6/11/6。超过目标区间上沿 1 次，低于硬限 30，无预算违规。全轮最大模型 3、实际 Handler 7，续期和重规划均 0。Live 工具提案及结果 **27/27** 逐 ID 配对。330 条 JSONL 事件可解析，私有推理字段未脱敏计数 0。费用 **COST_UNKNOWN**。

| 轮次 | PID / Trace ID | 实际工具 ID、名称和状态 | 模型 / Handler / 续期 / 重规划 | 停止原因 |
| --- | --- | --- | --- | --- |
| A1 | 30684 / `ff261fc9c0d94515b6a38496479b9e9c` | `call_00_BsGjhi7MUcmA3xCTp3pv7191` get_finance_summary AMBIGUOUS | 1 / 1 / 0 / 0 | `AMBIGUOUS` |
| A2 | 30684 / `f239f873ef0940aeb2925f7284f1fa08` | `call_00_bed1TWUzxYUv27AzCk3Y5527` get_finance_summary SUCCESS<br>`call_01_GX0SrgUn4vHM3tHw9J1P0234` list_invoices SUCCESS<br>`call_00_AsL5b7iYs1s1liaApYWY9432` get_applicable_rules SUCCESS<br>`call_01_WT67y6juWRClZ3WdTwZE0988` get_applicable_rules SUCCESS<br>`call_02_lBFGk1J3jK8L8VRSsaF98435` get_applicable_rules SUCCESS<br>`call_03_TvCOkMyCstO0yifCdxJ33380` get_applicable_rules SUCCESS<br>`call_04_qbSr8slNVDL8FX5v8S208126` check_missing_purpose SUCCESS | 3 / 7 / 0 / 0 | `ANSWERED` |
| B1 | 2572 / `64b7c4c65132484da31785e4af29b2d5` | `call_00_F85YzuBW41A7IHViAw5M4929` get_invoice SUCCESS<br>`call_00_V3rbGkmkJUohGJTG61yw9401` prepare_invoice_update WAITING_CONFIRMATION | 2 / 2 / 0 / 0 | `WAITING_CONFIRMATION` |
| BQ | 2572 / `789e841585ea4f42bf3acb3cbfafae08` | `call_00_yLIPXWBahfBOiz93e0bE2066` get_invoice SUCCESS | 2 / 1 / 0 / 0 | `ANSWERED` |
| B2 | 2572 / `3fa7c1113a35487b8e9042f6b01c8846` | `call_00_Kard4lMslzy5KBpCkjnX3670` get_invoice SUCCESS | 2 / 1 / 0 / 0 | `ANSWERED` |
| C1 | 2656 / `30d5c0a41988420986adce430f4fb503` | `call_00_g9OBdYSsazWvgVZry0qv4285` check_missing_purpose SUCCESS | 2 / 1 / 0 / 0 | `ANSWERED` |
| C2 | 2656 / `d820deec8ca7436c9ed6cdc65a78f424` | `call_00_8EsjVdzhQlx7hwe8tGQy0344` manage_task SUCCESS | 2 / 1 / 0 / 0 | `ANSWERED` |
| C3 | 30328 / `ba2941106ef442509c796ac56a371d8c` | `call_00_rr4JauoFoO96x3G2fCDs5663` list_tasks SUCCESS<br>`call_01_b7DTpqiNKDXQL2SE8PK96673` check_missing_purpose SUCCESS | 2 / 2 / 0 / 0 | `ANSWERED` |
| C4 | 30328 / `43e633abb10d4cdaac69d0e84757ef91` | `call_00_YPXKpTybY1HV5QVNxgDj1257` prepare_invoice_update WAITING_CONFIRMATION | 1 / 1 / 0 / 0 | `WAITING_CONFIRMATION` |
| C5 | 30328 / `98c69ebcd6ab404c998872c4c01d6548` | `call_00_5T5nCc0OwNNep376x0oS3420` list_tasks SUCCESS<br>`call_01_XSRACG60RwXSQxvZvWLZ4085` check_missing_purpose SUCCESS | 2 / 2 / 0 / 0 | `ANSWERED` |
| C6 | 11156 / `58381f51c9ef4f7798fff9f79f6ff1e9` | `call_00_Rg3Rcy8sXb1y4ey6Jnd66762` list_tasks SUCCESS<br>`call_01_fnCnNmYEwYmr70nHwunr8962` check_missing_purpose SUCCESS | 2 / 2 / 0 / 0 | `ANSWERED` |
| P1 | 33056 / `0d53d1554dd347b79ded16beaebbba33` | `call_00_6ScSLwzBRyLMP6Io5EWu6991` manage_preference NOT_FOUND<br>`call_00_TzUkyF2oQTZaCtHgw90S5201` manage_preference SUCCESS | 2 / 2 / 0 / 0 | `MODEL_LIMIT` |
| P2 | 33056 / `109c1f84587b4abf92a7a49c97b54bfd` | `call_00_BkPM3qX0GuBxpLxxqbA13757` manage_preference SUCCESS | 1 / 1 / 0 / 0 | `MODEL_LIMIT` |
| P3 | 33056 / `98c9c92f41a14ca2b05ae5d6e0be90a7` | `call_00_2Yc3vLye0DxeeBFdkDNM1263` manage_preference SUCCESS | 1 / 1 / 0 / 0 | `MODEL_LIMIT` |
| P4 | 33056 / `eb49db0324d24d1c966f15ab7e7d12be` | `call_00_UIDA5SJRTq1BoviO3bEw4638` manage_preference SUCCESS | 1 / 1 / 0 / 0 | `MODEL_LIMIT` |
| P5 | 33056 / `7a318fac6df84d2b991751f4797b956d` | `call_00_W8A8Nv3ltCf0gp5CbtIo1867` manage_preference NOT_FOUND | 1 / 1 / 0 / 0 | `MODEL_LIMIT` |

| 请求 | 实际模型 / HTTP | Prompt / Completion / Total Token | SDK ms |
| --- | --- | --- | --- |
| A1.1 | deepseek-flash / 200 | 3062 / 177 / 3239 | 1936.596 |
| A2.1 | deepseek-flash / 200 | 3426 / 328 / 3754 | 1902.496 |
| A2.2 | deepseek-flash / 200 | 5129 / 576 / 5705 | 3117.144 |
| A2.3 | deepseek-flash / 200 | 8400 / 440 / 8840 | 2814.855 |
| B1.1 | deepseek-flash / 200 | 3347 / 246 / 3593 | 2310.367 |
| B1.2 | deepseek-flash / 200 | 3738 / 116 / 3854 | 758.779 |
| BQ.1 | deepseek-flash / 200 | 4696 / 93 / 4789 | 939.452 |
| BQ.2 | deepseek-flash / 200 | 4937 / 210 / 5147 | 2129.590 |
| B2.1 | deepseek-flash / 200 | 5471 / 153 / 5624 | 1738.606 |
| B2.2 | deepseek-flash / 200 | 5772 / 146 / 5918 | 1860.929 |
| C1.1 | deepseek-flash / 200 | 3136 / 103 / 3239 | 1692.098 |
| C1.2 | deepseek-flash / 200 | 4084 / 244 / 4328 | 2835.460 |
| C2.1 | deepseek-flash / 200 | 4470 / 232 / 4702 | 1916.100 |
| C2.2 | deepseek-flash / 200 | 5958 / 190 / 6148 | 1750.885 |
| C3.1 | deepseek-flash / 200 | 3352 / 169 / 3521 | 1581.753 |
| C3.2 | deepseek-flash / 200 | 4589 / 361 / 4950 | 2451.991 |
| C4.1 | deepseek-flash / 200 | 5215 / 134 / 5349 | 1370.652 |
| C5.1 | deepseek-flash / 200 | 6932 / 153 / 7085 | 1305.159 |
| C5.2 | deepseek-flash / 200 | 8083 / 502 / 8585 | 3225.367 |
| C6.1 | deepseek-flash / 200 | 3345 / 163 / 3508 | 1578.189 |
| C6.2 | deepseek-flash / 200 | 4506 / 205 / 4711 | 1511.422 |
| P1.1 | deepseek-flash / 200 | 3063 / 159 / 3222 | 1867.902 |
| P1.2 | deepseek-flash / 200 | 3303 / 99 / 3402 | 1145.931 |
| P2.1 | deepseek-flash / 200 | 3933 / 109 / 4042 | 1342.308 |
| P3.1 | deepseek-flash / 200 | 4418 / 179 / 4597 | 1578.572 |
| P4.1 | deepseek-flash / 200 | 5113 / 116 / 5229 | 1456.609 |
| P5.1 | deepseek-flash / 200 | 5523 / 97 / 5620 | 1180.501 |
| 合计 | 27 次 | 127001 / 5700 / 132701 | 49299.713 |

## 复现和后续范围

从 `finance_agent/` 用项目 Python 3.12.14 执行 `python scripts/sec_a_probe.py <ID>`。本批八个 ID 为 ACL-06、TRACE-02、RES-01、TRACE-03、RES-05、RES-07、CONFIG-02、TRACE-04。定向为 `python -m unittest tests.test_sec_b1 tests.test_sec_b2 tests.test_sec_b3 tests.test_stage4p0c_closure tests.test_architecture tests.test_security_boundaries -q`，Live 后为 `python -m unittest discover -s tests -q`。

首次批次通过 `verify_sec_b4.py --profiles <已授权本地Profile配置> --cases-sha256 54ea2c334f53f5c72d7ccc00d48218a21c52e4ad1ff54a9fa8f31fc52649c8e7` 启动。依赖现有合法凭据环境。仅保留本地忽略目录中的首次 Trace、逐轮状态、进程退出、独立 SQL 和控制台输出。报告发布脱敏证据。

Issues #1–#10 保持开放。#1 获得一次新的 NOT_FOUND 后创建证据，#2 获得猜测提案被阻断证据，#3 仍有动词变体可复现。建议先独立结算这三个业务边界，再单独授权后续阶段。
