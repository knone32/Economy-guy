# S4-C · 工程证据封板

2026-11-07，`knone32/Economy-guy`，`main`。Base 与 Verified Code SHA 均为 `111c9f97cd710084b1cfc18b9bf139e159e01389`。起始本地和远端一致，工作区干净。最新生产提交 `bde7ec7bb7ca5f2a2460faade82e817b4302d6ef`，本轮生产代码、测试、历史报告及冻结用例原样保留。Report SHA 用 `git log -1 --format=%H -- docs/verification/stage4/S4-C.md` 查询。

核对了本地官方 1.1.0《参赛说明》《业务规则》和工程映射。三场景共用处理流程，金额和保存状态来自当前库；只允许明确授权的用途/备注修改，银行只读；R001/R002/R003/R004 按范围、日期和启用状态使用。交付要求源码、依赖与启动说明、简要设计、关键运行记录和不超过 5 分钟的演示。原件保留在本地材料包，仓库映射及核验入口见 [证据索引](S4-C-EVIDENCE-INDEX.md) 和 [项目总纲](../../PROJECT_MASTER_PLAN.md)。

## 当前复跑

在 `finance_agent/` 使用项目既有 Python 3.12.14。以下均绑定 Verified Code SHA。

| 命令 | 结果 |
| --- | --- |
| `python scripts/sec_a_probe.py ACL-06` | 0，交叉年月拒绝，明确对照成功 |
| `python scripts/sec_a_probe.py TRACE-02` | 0，合成 Cookie 标记遮蔽 |
| `python scripts/sec_a_probe.py RES-01` | 0，数组及非法参数安全停止 |
| `python scripts/sec_a_probe.py TRACE-03` | 0，有无 Trace 均安全停止 |
| `python scripts/sec_a_probe.py RES-05` | 0，负金额明细和汇总符合真值 |
| `python scripts/sec_a_probe.py RES-07` | 0，重复表头拒绝，负分导入和显示正确 |
| `python scripts/sec_a_probe.py CONFIG-02` | 0，规范和非规范回环均拒绝 |
| `python scripts/sec_a_probe.py TRACE-04` | 0，独立审计表可见；全量复跑包含实际审计及事务字段断言 |
| `python -m unittest tests.test_architecture -v` | 2/2，退出 0 |
| `python -m unittest discover -s tests -q` | 369/369，退出 0，38.757 秒 |

实际模型 API 尝试 **0**。本轮为 Codex 本地 D/B 回归。历史 L 计量单列，SEC-B4 27 次/132,701 tokens，BR 10 次/40,108 tokens。服务商费用 COST_UNKNOWN。工作库与官方虚构夹具哈希一致，回归仅使用隔离库。

## 官方业务证据

| 场景 | 结算 |
| --- | --- |
| A | PARTIAL。BR A1 主动追问且零月度 SQL；A2 独立核对 ¥9,622.06/10 张、收入 ¥13,000.50/4 条、支出 ¥7,180.74/8 条、R001 v1.0。MODEL_LIMIT 自然收尾缺口保留。SEC-B4 A1 模型曾猜测且被拦 |
| B | 组合业务证据通过。SEC-B4 历史首写/回读与 BR B2 可信已匹配回执各自绑定原 SHA，后者无新增提交或成功审计。最新版本完整 B 链未重跑 |
| C | 组合业务证据通过。4P0C-CLOSURE 和 SEC-B4 证实 ACTIVE、三真实进程和缺项 5→4。BR 预置隔离夹具的 C5 显示下一步，最新版本完整 C 链未重跑。C2 为 SIMULATED_TEST_USER，人工确认 NOT_TESTED / USER_DEFERRED |
| 偏好 CRUD | 业务 PASS。原 P11 精确请求历史同轮确认保存再查，SEC-B4 CRUD，BR 自然语言读回。历史自然收尾 NO_LEGAL_WORK/MODEL_LIMIT 保留 |
| 安全与外部盲测 | D/B 回归 PASS。E 为 EXTERNAL_HOLDOUT PENDING，生产安全认证 NOT_TESTED |

历史 S4-B 在 `08b3ed5df7873fd84322d41123fe20e1c5c80d4f` 的 A/B/C FAIL、4P-E 在 `3a83a2c87afe7cf555704f2ebc0284fcc4c68308` 的 A FAIL/B PARTIAL/C FAIL 及整体 BLOCKED 原样保留。本轮复核未扩大旧 Live 结论。 [S4-B](S4-B.md) · [4P-E](S4-P-E.md)

## Issue 逐项结算

复核了 #1–#10 的原始复现、原关闭条件和补充评论。#1 的原句同轮业务证据、#2 的来源拒绝与精确历史对照、#3 的原回执与 BR 变体分别成立。其余七项均按各自冻结故障及定向断言结算。GitHub 已逐项留言并确认状态。

| Issue | 原始故障 | 修复代码 SHA | 冻结/新增测试 | Live/SQLite 证据 | 当前限制 | 实际状态 |
| --- | --- | --- | --- | --- | --- | --- |
| [#1](https://github.com/knone32/Economy-guy/issues/1) | P11 查无即停，无新增候选 | `f6d99267358e5202752afbbdd062600781cdab29` | P11 原句、复合回执与偏好确认回归 | 历史 Flash 原句 get/NOT_FOUND→具体确认 create→同轮 get；Pro 从 list/NO_DATA 继续，两者新连接核对 | 历史 NO_LEGAL_WORK/MODEL_LIMIT，任意复合体验未保证 | [CLOSED](https://github.com/knone32/Economy-guy/issues/1#issuecomment-6703320204) |
| [#2](https://github.com/knone32/Economy-guy/issues/2) | P12 无来源猜月份却读到 SQLite | `f6d99267358e5202752afbbdd062600781cdab29` | P12 来源/权限、ACL-06 和完整配对回归 | 原句历史 Flash/Pro 验证。B4 真实猜测被拦且零月度 SQL，BR A1 主动追问、A2 金额/规则正确 | BR A2 MODEL_LIMIT，任意自然语言来源解析未验收 | [CLOSED](https://github.com/knone32/Economy-guy/issues/2#issuecomment-6703320982) |
| [#3](https://github.com/knone32/Economy-guy/issues/3) | B6 已匹配值无可信零写入回执 | `bde7ec7bb7ca5f2a2460faade82e817b4302d6ef` | 原改为和修改为，联合键、权限、禁止无确认写入、回执回归 | 4P0C 历史同句首写/复提。BR 原失败变体返回 CURRENT_VALUE_MATCHES，审计 1→1 | BR 未重跑全 B 链；旧冻结 NO_CHANGE/FAIL 保留 | [CLOSED](https://github.com/knone32/Economy-guy/issues/3#issuecomment-6703321772) |
| [#4](https://github.com/knone32/Economy-guy/issues/4) | 独立年/月集合放行交叉组合 | `8b59b4f32a92711f974be6367daaf8dc9de72671` | ACL-06、test_sec_b1 年月回归 | 交叉拒绝前未进入查询，两个原配对及明确 2026-08 可查，跨轮唯一补齐 | Live 未触发交叉提案，拒绝由确定性注入验证 | [CLOSED](https://github.com/knone32/Economy-guy/issues/4#issuecomment-6703322665) |
| [#5](https://github.com/knone32/Economy-guy/issues/5) | 自由文本 Cookie 头值落盘 | `8b59b4f32a92711f974be6367daaf8dc9de72671` | TRACE-02、实际 Agent JSONL 脱敏测试 | Cookie/Set-Cookie 合成标记不可见，保留后续行、业务键名和用量 | 冻结字段范围与合成标记 | [CLOSED](https://github.com/knone32/Economy-guy/issues/5#issuecomment-6703323430) |
| [#6](https://github.com/knone32/Economy-guy/issues/6) | -1 分显示 -1.99 元 | `ac61aa03e7e730c3ac4fd3f46074114f8862fa72` | RES-05、RES-07、整数分和汇总测试 | SQLite 为 -1 分、显示 -0.01 元，负汇总及极值独立 Decimal 核对 | 退款与红字会计流程超出本项范围 | [CLOSED](https://github.com/knone32/Economy-guy/issues/6#issuecomment-6703324113) |
| [#7](https://github.com/knone32/Economy-guy/issues/7) | 数组触发 AttributeError，surrogate 导致 Trace 编码异常 | `ac61aa03e7e730c3ac4fd3f46074114f8862fa72` | RES-01、TRACE-03、两条独立回归 | 合法 ID 配对并安全停止，有/无 Trace 拒绝非法 Unicode，数据库无变化 | 有界合成输入 | [CLOSED](https://github.com/knone32/Economy-guy/issues/7#issuecomment-6703324808) |
| [#8](https://github.com/knone32/Economy-guy/issues/8) | 重复 Excel 表头被最后一列覆盖 | `ac61aa03e7e730c3ac4fd3f46074114f8862fa72` | RES-07、重复必需/可选标题与缓存测试 | 合法对照成功，异常表头无发布/遗留暂存，既有库无变化 | 官方表结构及精确重复字段 | [CLOSED](https://github.com/knone32/Economy-guy/issues/8#issuecomment-6703325749) |
| [#9](https://github.com/knone32/Economy-guy/issues/9) | 127.1 被当域名放行 | `e81b36ddfe9b06e2cac590ad91fffe9c16d686f0` | CONFIG-02、OfflineProfileTests | 非规范数值拒绝，合法配置通过，传输/DNS/socket 调用为 0 | DNS 重绑定、代理、重定向另行验证 | [CLOSED](https://github.com/knone32/Economy-guy/issues/9#issuecomment-6703326445) |
| [#10](https://github.com/knone32/Economy-guy/issues/10) | CLI 规则状态变化缺独立审计 | `e81b36ddfe9b06e2cac590ad91fffe9c16d686f0` | TRACE-04、RuleAuditTests | 独立 CLI 和新连接查状态与 actor/版本，事务原子、故障回滚、重复 NO_CHANGE | 失败走 CLI 反馈，模拟身份，持久审计只记实际变更 | [CLOSED](https://github.com/knone32/Economy-guy/issues/10#issuecomment-6703327057) |

本轮关闭 #1–#10，十项中剩余 OPEN 为 0。关闭范围限原缺陷。A2 自然收尾、人工 C2、外部 Holdout 和真实服务商账单仍留在交付限制中。

## 门禁与 S4-D 准入

- **S4-C EVIDENCE GATE = PASS**，**S4-D PREPARATION = READY**。索引可供后续整理源码、启动说明、2–3 页设计、脱敏运行记录及 ≤5 分钟演示。S4-D 仍须另行授权。
- **S4-BR ENGINEERING = PASS**，**OFFICIAL_P0_LIVE = PARTIAL**，**EXTERNAL_HOLDOUT = PENDING**。
- **PRODUCTION_SECURITY_CERTIFICATION = NOT_TESTED**，**SECURITY_RELEASE_GATE = BLOCKED**。正式身份认证、任意提供商协议兼容、真实财务系统连接、DNS 重绑定/代理/重定向均无完整验收依据。证据封板只授权使用相应范围的工程结论。
