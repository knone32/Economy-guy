# S4-BR · 最小交互补丁与独立业务复核

2026-11-07，`knone32/Economy-guy`，`main`。Base `8b058c07bfd348a629d1d45af9efb83df39512c6`，起始本地与远端相同，工作区干净。Tested Code `bde7ec7bb7ca5f2a2460faade82e817b4302d6ef`，tree `66cda1e3e7150a12773f95478760afc9dd2939d8`。Report SHA 用 `git log -1 --format=%H -- docs/verification/stage4/S4-BR.md` 查询。

首次发送前冻结 [增量公开案例](S4-BR-CASES.md)，SHA256 `04446318851ec9471786e9f21d6305017ff95ebdab08aeb6a737d14dd1500051`，测试驱动 `finance_agent/scripts/verify_s4_br.py` SHA256 `0c46c16d4845d548a00b24329a2a10aae6c9dd5cb97be4c2298de4d8e13ead04`。只修改生产 `finance_agent/app/write_coordination.py` 和 `finance_agent/app/responses.py`。原 [SEC-B4 案例及结算](../security/S4-SEC-B4.md) 和 4P0C-CLOSURE 历史记录保持原样。

## 阶段裁决

| 项目 | 结果与证据 |
| --- | --- |
| BR_DETERMINISTIC | PASS。新增 6 项，Base 退出 1（4 个断言失败），修复后 6/6，退出 0。定向 111/111，最终 369/369 |
| BR_SQLITE | PASS。独立只读 SQLite/Decimal 核验，四个 Live 库完整性均 ok，允许的展示元数据单列 |
| BR_LIVE_INCREMENTAL | PASS。B2、PREPARED_FIXTURE + LIVE_C5、偏好读回通过。A 的财务事实通过，自然收尾 PARTIAL |
| OFFICIAL_A | PARTIAL。当前版本 A1 主动追问，零工具和月度 SQL，A2 数值及规则正确，但 MODEL_LIMIT 收尾 |
| OFFICIAL_B | 业务证据组合通过。复用 SEC-B4 的真实 B1/BQ，当前补跑 B2 已匹配回执。当前版本未重跑完整 B 链 |
| OFFICIAL_C | 业务证据组合通过。复用 SEC-B4 模拟 C2 确认和三进程持久链，当前用预置可信夹具补跑 C5。当前版本未重跑完整 C1–C6 |
| PREFERENCE_CRUD | 业务 PASS。复用 SEC-B4 创建、读取、更新、删除及不存在核对，保留当时各轮 MODEL_LIMIT。当前版本只重跑自然语言读取 |
| SECURITY_REGRESSION | PASS。八条 SEC-A 原探针均退出 0，定向覆盖 SEC-B1/B2/B3、4P0C、可信确认、权限、架构和预算边界 |
| EXTERNAL_HOLDOUT | PENDING。业务真值由独立 SQL 核对，仍由 Codex 执行公开回归。真实人工 C2 确认 NOT_TESTED |

**S4-BR 工程门禁 PASS，整体 P0 Live 门禁 PARTIAL，安全发布门禁 BLOCKED。** 保留 A2 的自然收尾缺口，并区分历史完整链和当前增量复核。

## 红绿与业务事实

- #3 原句「将 C001 企业 2026 年 9 月 F002 发票的用途修改为项目资料核对。」在 Base 的实际回执为 NOT_SUBMITTED。「备注修改为」同样复现。扩展现有可信编辑匹配。重复字段指令、空值和发票日期与明确年月冲突时均不给出已匹配回执。原合法动词仍通过。定向验证唯一企业/发票、允许字段、可信编辑、ACL、新连接查值、历史成功审计保持、当前不匹配和普通聊天拒绝。初次 Prepare/Commit 的审计与新连接回读仍通过。
- C5 原句「核对 C001 2026 年 9 月当前用途待办和还缺哪些发票，并说明下一步。」Base 两个读取均成功且缺 4，CLI 无可信下一步。修复只在本轮已鉴权、唯一匹配的任务与用途检查一致时复用任务进度渲染。错企业/年月、结果拒绝、多任务、缺本轮任务证据或只存在历史任务读取时均不合成。正向用例保持两次模型调用，业务快照不变。
- **Live B2** 模型实际 `get_invoice` 读回「项目资料核对」，Harness 另以新只读连接核对，Trace 为 `matched=true, committed_this_turn=false`。CLI 展示「无需再次修改」，回执 CURRENT_VALUE_MATCHES，历史审计仍恰 1 条，本轮增量 0，无草稿或确认。
- **PREPARED_FIXTURE + LIVE_C5** 可信测试先创建任务，再按真实 Prepare、绑定草稿、Commit/Audit/Readback 准备 F002。独立 SQL 从缺 5 变为缺 4，此变化属于夹具准备。Live 任务 `7019066bdd754fbfb530c5e9a87d02d6` 始终 ACTIVE，缺 F004、F003、F006、F009。CLI 显示任务、企业/月、状态、数量和缺项，建议逐张 Prepare、可信确认、Commit，全部补齐后单独核对确认完成。Live 无写入和新增审计，未重演 C1→C4。历史 SEC-B4 task_id 与三进程见原报告，C2 确认来源为 SIMULATED_TEST_USER。
- **A1/A2** A1 模型直接给出 year/month 追问，WAITING_USER，月度 SQL 0。A2 11 条月度发票/银行 SELECT 均为 C001/2026-09。独立整数分 SUM/COUNT 为发票 962206/10、银行收入 1300050/4、支出 718074/8，工具与 CLI 金额、数量及 R001 v1.0 一致。Harness 在 MODEL_LIMIT 展示已核实结果。离线实际 Agent 独立验证 2026-07 空范围 NO_DATA、U002/C002 DENIED、无年月猜测 AMBIGUOUS。2025-08 无生效 R001，返回 NO_APPLICABLE_RULE，独立于空记录。
- **偏好** 从独立预置可信本地记录读回 U001/C001/reply_format=简洁，ANSWERED，无变更。无 Live 确认或提交。B/C 历史发票审计都来自明确绑定的测试夹具准备，各保留 1 条，与 Live 账本分离。
- 四个 Live 库的 invoices、bank_transactions、rules、rule_management_audit、tasks、preferences、invoice_audit、permissions 均逐行相同。允许的 reference_anchors 增量 B2 +1、C5 +1、A/P 0。工作库 SHA256 前后均 `f190ed7abeacf02d7964439a906e9ae2efe34ec956b2bc4352640549dca19433`，官方夹具 SHA256 `edb13b2a52d2f875033258836e8fc23c3e1353c46d101184048bac289e52ed0f`。

## Live 请求与工具证据

真实 CLI 复用 B4 观察驱动和已授权 shared-flash。发送前跨进程 SQLite 计数，离线验证第 15 次拒绝及失败占用。实际 10 次 HTTP 200，SDK 重试 0、Pro 0、无切换。五轮最大模型 3、实际 Handler 6，续期/重规划均 0。工具 10/10 逐 ID 配对，120 条 JSONL 可解析，私有推理未遮蔽字段计数 0，无预算违规。费用 COST_UNKNOWN。

| 轮 | PID / Trace | 工具 ID、名称和状态 | 模型 / Handler / 续期 / 重规划 | 停止 |
| --- | --- | --- | --- | --- |
| B2 | 27700 / `27aca6094a20438c8b5ee23b4acf1122` | `call_00_o6rTvt0Zam2N1oqF4Rkm1819` get_invoice SUCCESS | 2 / 1 / 0 / 0 | `ANSWERED` |
| C5 | 18816 / `4c873023da474a2f8109d2050bc5803e` | `call_00_Rk1dbcU5xogk4dquEBDS6831` list_tasks SUCCESS<br>`call_01_TqRFXkkTYaK5CSJm0G3r7617` check_missing_purpose SUCCESS | 2 / 2 / 0 / 0 | `ANSWERED` |
| A1 | 27384 / `e9d0535dcfee49948e0ca5d87fe48ca8` | 无 | 1 / 0 / 0 / 0 | `WAITING_USER` |
| A2 | 27384 / `31aa62efba95489c93329c1c296f23e1` | `call_00_av4wB3UNRHAlm0vcrLj59781` get_finance_summary SUCCESS<br>`call_00_Eoy8lUxvrQ8xBSPFgQys9652` list_invoices SUCCESS<br>`call_00_2RzW0Cr1tcIAhtbsYCDJ5358` get_applicable_rules SUCCESS<br>`call_01_bfAI4FPdYJq8RXAfVLn11008` get_applicable_rules SUCCESS<br>`call_02_AbWjXFtLKXEji2pXZo9c1874` get_applicable_rules SUCCESS<br>`call_03_uXwIRvMGIhQ24sf7iQLN9263` get_applicable_rules SUCCESS | 3 / 6 / 0 / 0 | `MODEL_LIMIT` |
| P2 | 25264 / `bd4359d50af745e89a24b5ae308c44ca` | `call_00_5xIlkDRkv98jKFPOUjbC4957` manage_preference SUCCESS | 2 / 1 / 0 / 0 | `ANSWERED` |

| 请求 | 模型 / HTTP | Prompt / Completion / Total Token | SDK ms |
| --- | --- | --- | --- |
| B2.1 | deepseek-flash / 200 | 3346 / 277 / 3623 | 2670.990 |
| B2.2 | deepseek-flash / 200 | 3771 / 147 / 3918 | 1717.260 |
| C5.1 | deepseek-flash / 200 | 3221 / 178 / 3399 | 1820.282 |
| C5.2 | deepseek-flash / 200 | 4358 / 436 / 4794 | 3657.530 |
| A1.1 | deepseek-flash / 200 | 3062 / 179 / 3241 | 2029.046 |
| A2.1 | deepseek-flash / 200 | 3325 / 436 / 3761 | 3783.228 |
| A2.2 | deepseek-flash / 200 | 4094 / 591 / 4685 | 4481.564 |
| A2.3 | deepseek-flash / 200 | 5731 / 409 / 6140 | 2047.969 |
| P2.1 | deepseek-flash / 200 | 3080 / 107 / 3187 | 1382.607 |
| P2.2 | deepseek-flash / 200 | 3336 / 24 / 3360 | 822.808 |
| 合计 | 10 次 | 37324 / 2784 / 40108 | 24413.284 |

## 回归和 Issue 结算

从 `finance_agent/` 使用 Python 3.12.14。红绿命令 `python -m unittest tests.test_s4_br -q`。原八探针 `python scripts/sec_a_probe.py <ID>` 的 ID 为 ACL-06、TRACE-02、RES-01、TRACE-03、RES-05、RES-07、CONFIG-02、TRACE-04。定向 `python -m unittest tests.test_s4_br tests.test_sec_b1 tests.test_sec_b2 tests.test_sec_b3 tests.test_stage4p0c tests.test_stage4p0c_closure tests.test_permissions tests.test_security_boundaries tests.test_write_receipts tests.test_architecture -q`，111/111，退出 0。Live 后唯一一次 `python -m unittest discover -s tests -q`，369/369，退出 0，36.533 秒。

| Issue | 去重结算建议 |
| --- | --- |
| #1 | 已有足够的限定业务证据。SEC-B4 真实 NOT_FOUND 后继续确认创建，本次读回通过。复合自然结束仍保留历史 MODEL_LIMIT |
| #2 | 可信来源拒绝已验证。SEC-B4 真实猜测被拦，本次离线复现拒绝，A1 Live 主动追问。更广泛的自然语言体验待独立复核 |
| #3 | 本次修复通过，原句红转绿，Live 返回 CURRENT_VALUE_MATCHES，无新提交 |
| #4、#5 | 完整年月配对、Cookie 脱敏原探针及独立测试通过，可进入独立关闭审查 |
| #6、#7、#8 | 负金额、异常参数/Unicode、重复表头原探针及回归通过，可进入独立关闭审查 |
| #9 | 非规范数值主机修复通过。DNS 重绑定、代理和重定向缺独立证据 |
| #10 | 规则审计原探针与事务/故障断言通过。生产操作者认证超出初赛模拟身份范围 |

Issues #1–#10 保持开放。仅给 #3 追加本次修复证据。建议独立复核以上结算与 A2 UX 后再决定下一阶段。
