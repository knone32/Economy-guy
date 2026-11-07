# S4-C 交付证据索引

S4-C 验证仓库 `111c9f97cd710084b1cfc18b9bf139e159e01389`，生产源码与 `bde7ec7bb7ca5f2a2460faade82e817b4302d6ef` 一致。表中的版本绑定各自执行，历史 Live 仍使用其原版本。D 为确定性回归，B 为独立 SQLite/Decimal 核对，L 为真实模型，E 为外部独立 Holdout。

| Requirement | Stage | Type | Tested Code SHA | Source Path | Result | Limitation |
| --- | --- | --- | --- | --- | --- | --- |
| 官方 A 原句追问与补年月 | 4P0C | L/B | `f6d99267358e5202752afbbdd062600781cdab29` | [原句 P12 实测](S4-P0C-RESULTS.md) | Flash/Pro 追问后查得正确 R001 v1.0 数额与计数 | 历史精确用例 |
| 官方 A 猜测阻断和财务核对 | SEC-B4 | L/B | `e834bbb961030c0671d788bc629026031078f743` | [A1/A2 证据](../security/S4-SEC-B4.md) | A1 猜测被拒，零月度 SQL，A2 正常收尾 | A1 自然追问 PARTIAL |
| 官方 A 当前增量 | S4-BR | L/B | `bde7ec7bb7ca5f2a2460faade82e817b4302d6ef` | [冻结案例](S4-BR-CASES.md)、[实测](S4-BR.md) | 主动追问，发票 ¥9,622.06/10 张，银行收入 ¥13,000.50/4 条、支出 ¥7,180.74/8 条，R001 v1.0 | A2 MODEL_LIMIT，P0 Live PARTIAL |
| 官方 B Prepare、确认、Commit、Audit、Readback | SEC-B4 | L/B | `e834bbb961030c0671d788bc629026031078f743` | [B1/BQ/B2](../security/S4-SEC-B4.md) | B1/BQ 一次真实确认提交及新连接回读，B2 无第二次提交 | 当时「修改为」未显示匹配回执 |
| 官方 B 重复请求零写入回执 | 4P0C / S4-BR | D/L/B | `f6d99267358e5202752afbbdd062600781cdab29` / `bde7ec7bb7ca5f2a2460faade82e817b4302d6ef` | [B6 同句首写/复提](S4-P0C.md)、[B2 变体](S4-BR.md)、[回归](../../../finance_agent/tests/test_s4_br.py) | 已匹配返回 CURRENT_VALUE_MATCHES，历史成功审计保持 1 | BR 仅重跑 B2，匹配是新只读核对 |
| 官方 C 持久任务与两次重启 | 4P0C-CLOSURE / SEC-B4 | L/B | `fc3f9d70a4ef66a46a8ffb666dd9d01db7b3a94a` / `e834bbb961030c0671d788bc629026031078f743` | [完整 C 链](S4-P0C-CLOSURE.md)、[再验](../security/S4-SEC-B4.md) | 同一 ACTIVE task_id，三真实进程、缺 5→4、一次发票审计及回读 | C2 SIMULATED_TEST_USER，人工 NOT_TESTED；SEC-B4 的 C5 独立答复缺下一步 |
| 官方 C 当前进度与下一步 | S4-BR | D/L/B | `bde7ec7bb7ca5f2a2460faade82e817b4302d6ef` | [C5 增量](S4-BR.md)、[展示层](../../../finance_agent/app/responses.py) | 真实读取同一 ACTIVE 任务、缺 4，CLI 显示逐张确认及单独完成核对 | PREPARED_FIXTURE + LIVE_C5，当前版本未重演 C1→C6 |
| 偏好复合保存与 CRUD | 4P0C / SEC-B4 / S4-BR | D/L/B | `f6d99267358e5202752afbbdd062600781cdab29` / `e834bbb961030c0671d788bc629026031078f743` / `bde7ec7bb7ca5f2a2460faade82e817b4302d6ef` | [P11 原句](S4-P0C.md)、[CRUD](../security/S4-SEC-B4.md)、[读回](S4-BR.md) | 明确确认后创建并读回，更新、删除、查无均有 SQLite 证据 | 历史 NO_LEGAL_WORK/MODEL_LIMIT 保留，BR 只重跑读取 |
| 规则 R001–R004 与独立管理审计 | SEC-B3 / S4-C | D/B | `e81b36ddfe9b06e2cac590ad91fffe9c16d686f0` / `111c9f97cd710084b1cfc18b9bf139e159e01389` | [规则代码](../../../finance_agent/app/rules.py)、[审计回归](../../../finance_agent/tests/test_sec_b3.py)、[SEC-B3](../security/S4-SEC-B3.md) | 有效版本、CLI 授权、成功原子审计、重复 NO_CHANGE、故障回滚 | 模拟操作者；失败走 CLI 反馈 |
| ACL、可信来源、工具配对 | SEC-B4 / S4-BR / S4-C | D/B/L | `e834bbb961030c0671d788bc629026031078f743` / `bde7ec7bb7ca5f2a2460faade82e817b4302d6ef` / `111c9f97cd710084b1cfc18b9bf139e159e01389` | [ScopeProof](../../../finance_agent/app/provenance.py)、[安全测试](../../../finance_agent/tests/test_security_boundaries.py)、[SEC-B4](../security/S4-SEC-B4.md)、[BR](S4-BR.md) | H2 Mock DENIED，完整年月防交叉，Live 27/27、10/10 工具 ID 配对 | 授权来自 CLI 模拟身份；模型仍可能提出不合法范围 |
| SEC-A 冻结安全发现 | SEC-A | D/B | `5c7a15c105459662f0b20dacd254f8395e1d540d`（原生产基线），`53abc94e7833ec5c2c3f9779986f56d0af2781bb`（探针） | [发现](../security/S4-SEC-A.md)、[冻结案例](../security/S4-SEC-A-CASES.md)、[原探针](../../../finance_agent/scripts/sec_a_probe.py) | 25 个公开案例，原失败留存 | 隔离发现范围 |
| 年月配对与 Cookie/Set-Cookie | SEC-B1 / S4-C | D/B | `8b59b4f32a92711f974be6367daaf8dc9de72671`（生产/测试对应被测 tree `562b4d667fc347325be2a91b30706ce5cfcc9b5a`） | [SEC-B1](../security/S4-SEC-B1.md)、[回归](../../../finance_agent/tests/test_sec_b1.py) | ACL-06、TRACE-02 退出 0 | 脱敏以合成字段覆盖，Live 未触发交叉提案 |
| 金额、非法 JSON/Unicode、重复表头 | SEC-B2 / S4-C | D/B | `ac61aa03e7e730c3ac4fd3f46074114f8862fa72` | [SEC-B2](../security/S4-SEC-B2.md)、[回归](../../../finance_agent/tests/test_sec_b2.py) | RES-01、TRACE-03、RES-05、RES-07 退出 0 | 合成攻击及官方虚构工作簿 |
| 数值 URL、规则管理审计 | SEC-B3 / S4-C | D/B | `e81b36ddfe9b06e2cac590ad91fffe9c16d686f0` | [SEC-B3](../security/S4-SEC-B3.md)、[回归](../../../finance_agent/tests/test_sec_b3.py) | CONFIG-02、TRACE-04 退出 0，验证真实审计字段与事务 | DNS 重绑定、代理、重定向待验收 |
| Trace、模型协议与预算 | 4P-C / SEC-B4 / S4-BR / S4-C | D/L | `d27ca91` / `e834bbb961030c0671d788bc629026031078f743` / `bde7ec7bb7ca5f2a2460faade82e817b4302d6ef` / `111c9f97cd710084b1cfc18b9bf139e159e01389` | [Thinking](S4-P-C.md)、[B4 计量](../security/S4-SEC-B4.md)、[BR 计量](S4-BR.md)、[架构](../../../finance_agent/tests/test_architecture.py) | 9/12/2/1；真实批次 27 次及 10 次，脱敏及配对检查通过 | 已验证 DeepSeek 协议；COST_UNKNOWN |
| 当前工程回归 | S4-C | D/B | `111c9f97cd710084b1cfc18b9bf139e159e01389` | [封板报告](S4-C.md)、[官方虚构夹具](../../../finance_agent/tests/fixtures/example.xlsx) | 八条原探针、369 项全量、2 项架构通过，真实模型 API 0 | Codex 本地执行 |
| 外部盲测与生产验收 | 待另行授权 | E | — | [封板边界](S4-C.md) | EXTERNAL_HOLDOUT PENDING；生产安全认证 NOT_TESTED | 正式登录、任意 Provider、真实财务系统联通均未验收 |

## S4-D 准备入口

按 [启动说明](../../../finance_agent/README.md) 从干净环境验证源码及依赖，使用官方虚构夹具。设计说明建议 2–3 页，展示 A 查询、B 受控保存、C 跨会话任务，演示不超过 5 分钟。可从表内抽取脱敏关键记录，并标明 SHA、确认来源、停止原因及实际证据层。提交包仅纳入授权素材，密钥、原始 Trace、私有推理及运行库不入包。准备就绪指索引可直接使用，发布判断沿用 [S4-C 门禁](S4-C.md)。
