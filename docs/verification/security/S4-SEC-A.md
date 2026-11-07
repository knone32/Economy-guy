# S4-SEC-A 独立安全发现

2026-11-07，`knone32/Economy-guy` 的 `main`。**SEC-A DISCOVERY = COMPLETED**。确认 **3 个 P1、5 个 P2**，其中两个异常停止缺陷合并追踪。**SEC-B REQUIRED，安全发布门禁 BLOCKED**。既有业务闭环的 `PROVISIONAL_PASS` 仍按当时证据解释。

| 版本或内容 | 标识 |
|---|---|
| Base / Tested production checkout | `5c7a15c105459662f0b20dacd254f8395e1d540d` |
| 等价生产业务源码 | `f6d99267358e5202752afbbdd062600781cdab29`，`finance_agent/app/` 和 `main.py` Git 内容一致 |
| 探针与案例提交 | `53abc94e7833ec5c2c3f9779986f56d0af2781bb` |
| Report SHA | `git log -1 --format=%H -- docs/verification/security/S4-SEC-A.md` |
| 生产代码 SHA256 | `1a8ad70201f4eaa72428ed14ea4b41a2e14289507565d07825b00f658863b6af`，Base 的 `git archive --format=tar` 选取 `finance_agent/app` 和 `finance_agent/main.py` |
| 案例初始 SHA256 | `b792170ff996ef4cb5bb4a177fd26d59bdb817d64119ec6ca1dd25a8aaaf373f` |
| 案例追加后 SHA256 | `4116f4b2e587ce7c3d13f5910baf6b5059d800cfd897cf16b99176b26dbc19d3` |
| 最终探针 SHA256 | `f8f8c503bf31ee16b2f5350adbc1d94cb84881b6fc7352559d07b3777374b2da` |
| 官方虚构 Excel SHA256 | `edb13b2a52d2f875033258836e8fc23c3e1353c46d101184048bac289e52ed0f` |

业务依据采用仓库内 1.1.0 官方虚构 Excel、总纲 v1.2 及契约 v2 的规则转录。官方参赛说明和业务规则原件在本次可定位资料中缺失，原件逐条复核未测。沿用阶段执行计划与 P-E、P0C、P0C-CLOSURE 的已核对证据。入口与信任边界、期望、原测试选择器及冻结输入见 [案例清单](S4-SEC-A-CASES.md)。

## 覆盖与结果

初始 24 个公开案例，追加 1 个带 `DISCOVERED_AFTER_INITIAL_FREEZE` 的案例。25 个执行完毕。13 个复用案例对应 61 个不同原测试，均在本轮唯一一次全量回归执行。12 个独立探针中 8 个返回预期的失败退出码 1，4 个返回 0。D 按入口安全不变量计，B 按 SQLite、审计或业务事实计。B 的 NOT_TESTED 包含不涉及业务写入或事实核验的配置、日志和协议断言。

| 证据层 | PASS | FAIL | NOT_TESTED |
|---|---:|---:|---:|
| D 确定性运行行为 | 17 | 8 | 0 |
| B SQLite、审计与业务事实 | 16 | 3 | 6 |

`python -m unittest discover -s tests -q` 在 `finance_agent/` 运行，**340/340 PASS**，32.781 秒，退出 0。原有断言和冻结材料保持原样。独立失败入口 `python scripts/sec_a_probe.py <ID>` 保留红线。L 为 `MODEL_BEHAVIOR_NOT_TESTED`，实际模型 API 请求 0。E 为 `EXTERNAL_HOLDOUT_PENDING`。

| 独立探针 | D / B | 首次观测 |
|---|---|---|
| ACL-06 | FAIL / FAIL | 交叉月份和正向对照均 SUCCESS，交叉请求返回 10 行 |
| ACL-07 | PASS / PASS | 内部直接调用 SUCCESS，跨 actor DENIED，正式 Loop 缺日期 AMBIGUOUS，伪造 proof 字段 INVALID_ARGUMENTS |
| RES-01 | FAIL / PASS | `manage_preference` 的 JSON 数组导致 AttributeError，其余八种输入安全拒绝，业务快照相等 |
| RES-02 | PASS / PASS | 两条 int64 最大金额触发 ERROR，data 为 null，完整性检查 ok |
| RES-05 | FAIL / FAIL | 负一分明细 `-1.99`，独立预期 `-0.01`，该组正净额汇总仍正确 |
| RES-06 | PASS / PASS | 65,536 字节用户输入触发 CONTEXT_LIMIT，模型调用 0 |
| RES-04 | PASS / PASS | 首批样本八种拒绝、合法导入成功，已有库字节相同。重复列样本受重存时核对公式缓存丢失影响，不能用其拒绝证明标题检查有效 |
| CONFIG-02 | FAIL / NOT_TESTED | `127.0.0.1` 拒绝，`127.1` 通过。本机数值解码等价于回环 |
| TRACE-02 | FAIL / NOT_TESTED | JSONL 可读到合成 Cookie 值，嵌入 JSON 的 access_token 值已遮蔽 |
| TRACE-03 | FAIL / PASS | 有 Trace 时 UnicodeEncodeError，无 Trace 对照正常 INVALID_RESPONSE，SQLite 无变化 |
| TRACE-04 | FAIL / PASS | R002 v2.0 确实停用，发票和原审计无变动。仅有 `invoice_audit` 表，无规则管理事件 |
| RES-07 | FAIL / FAIL | 物化核对缓存的合法对照成功。重复标题发布新库并保存一条后列用途，负金额导入保存 -1 分且显示错误 |

普通新探针最大实测输入 65,536 UTF-8 字节，JSON 嵌套 32 层，单次模型响应一个工具请求，既有批量测试覆盖 Handler 上限 12 及逐 ID 配对。单库 SQL 变异最多两行。新增 XLSX 均在 128 KiB 文件上限内，RES-07 最大实测 17,103 字节。每个新探针独立子进程超时 10 秒，实测最长约 0.734 秒，无超时。复用并发最多两个工作者，既有重启测试保留原 20 秒超时。网络连接和 DNS 在独立探针中被阻断。原始本地输出保存在忽略目录 `artifacts/s4_sec_a/`。

## 已复现问题与 SEC-B 验收

每项均以表中 ID 从 `finance_agent/` 执行 `python scripts/sec_a_probe.py <ID>`，使用上述 Tested SHA。`P0=0，P1=3，P2=5，P3=0`。分级依据实际入口、影响和独立副作用核验。保留各探针预期，SEC-B 用原命令复验红转绿。

| 严重度、案例 | 可控制输入、实际结果和原因 | 最小修复与通过标准 |
|---|---|---|
| P1 ACL-06 [#4](https://github.com/knone32/Economy-guy/issues/4) | 用户输入 `2026-09 和 2025-08`，不可信模型提出 `2026-08`。真实 Agent 返回授权企业内未请求的 10 行。`explicit_scope` 与 `validate_scope` 分开存/校验年和月，丢失配对。企业 ACL 生效，零写入 | 保留完整年月元组，保留有明确来源的跨轮补齐，交叉组合拒绝且明确年月正向对照继续成功。与 #2 的缺年月根因分别追踪 |
| P1 TRACE-02 [#5](https://github.com/knone32/Economy-guy/issues/5) | 用户消息含自由文本 Cookie，原值留在真实 JSONL `model_input`。`trace.redact` 的结构字段处理覆盖 Cookie，字符串路径缺相同控制。只使用合成值，未观测真实凭据或外传 | 遮蔽自由文本 Cookie/Set-Cookie 和嵌入形式，业务 `preference_key` 与用量计数仍可审计 |
| P1 RES-05 / RES-07 [#6](https://github.com/knone32/Economy-guy/issues/6) | 可信本地导入接受合成 -1 分，SQLite 真值正确，`queries._money` 以有符号整除和余数拼接而显示 `-1.99`。`finance._total` 同一格式模式，负净额汇总尚未单独动态验证 | 明确负值业务契约，支持时统一正确格式化。-1/-99/-100 分、负汇总、零、正值均与独立 Decimal 相符 |
| P2 RES-01 [#7](https://github.com/knone32/Economy-guy/issues/7) | 模型工具 `manage_preference` 的参数 `[]`。Handler 拒绝后，Agent 重解码并把 list 交给 `scheduler.observe`，其 `.get()` 使异常逃逸。该 ID 无工具结果，业务表不变 | 调度器只接收已验证对象或显式错误，保持配对并返回安全停止 |
| P2 TRACE-03 [#7](https://github.com/knone32/Economy-guy/issues/7) | 可由 JSON 转义表示的模型孤立 surrogate，在 Trace 编码时触发 UnicodeEncodeError，当前降级分支只处理 OSError。无 Trace 对照正常拒绝，业务表不变 | 在输入边界拒绝无效 Unicode，或在日志边界安全编码并降级，启用 Trace 时也正常停止 |
| P2 RES-07 [#8](https://github.com/knone32/Economy-guy/issues/8) | 外部工作簿含重复可选 `用途` 标题时，`_rows_after_header` 字典只保留最后列。合法核对缓存仍可通过，导致一条合成用途被保存到新库。已有库未改 | 构建标题映射前拒绝重复，合法对照成功，坏簿不得发布且清理暂存 |
| P2 CONFIG-02 [#9](https://github.com/knone32/Economy-guy/issues/9) | 可信本地配置 `https://127.1` 可过 `safe_url`，`ipaddress` 未识别而按主机名接受。仅数字解码，无真实连接、DNS 或模型配置入口 | 拒绝非规范数值地址，并在 mock 下验证不会生成传输。DNS、代理及重定向留作另项受控验证 |
| P2 TRACE-04 [#10](https://github.com/knone32/Economy-guy/issues/10) | `rules disable` 通过独立模拟权限停用版本，CLI 直接调用规则层，未生成含 actor、版本和前后状态的管理审计。规则状态正确，发票审计保持原状 | 为规则管理建立可关联的变更记录，覆盖成功、失败和无变化，并使用原入口重测 |

实际副作用为未请求月份的本地读取、合成 Cookie 的本地日志留存、新导入库的一条字段覆盖和金额显示失真。未发现越权企业写入、确认绕过、历史许可复用、已有工作库破坏或真实密钥泄漏。发票确认、管理确认、事务回滚和匹配回执复用断言通过。P12 的 `proof=None` 只在可信兼容入口实测成功，正式 Agent 调用链未复现该旁路。生产依赖不引用上轮模拟批准驱动，复用管理确认与重启断言均通过。

## 遗留台账和门禁

| 历史项 | 审计判定 | 边界 |
|---|---|---|
| G06/G07 规则管理与追溯 | 规则权限、启停和版本 VERIFIED。管理审计 REPRODUCIBLE_DEFECT，#10 | 没有证据表明模型能发布规则 |
| Context 和来源、任务恢复/引用 | 跨轮裁剪、任务隔离、失效引用 VERIFIED。组合年月 REPRODUCIBLE_DEFECT，#4 | 复杂语义抽取和超长摘要 DEFERRED_BY_SCOPE |
| Provider Profile 和 Trace | 用户级隔离、切换和私有历史 VERIFIED。非规范地址、自由文本脱敏和编码 REPRODUCIBLE_DEFECT，#9/#5/#7 | 文件符号链接替换、DNS 重绑定、代理与重定向 NOT_TESTED |
| Scheduler、输入和资源 | 硬限与有效 ID 配对 VERIFIED。数组参数的异常停止 REPRODUCIBLE_DEFECT，#7 | 超出本轮输入/文件界限的耗尽、进程强制终止与恢复 NOT_TESTED |
| 审计一致性及退出 | 回滚、ACK 丢失、Trace I/O 降级、真实子进程重启 VERIFIED | 操作系统崩溃及断电恢复 NOT_TESTED |
| 提示注入 | 备注、偏好、任务和伪工具角色的 Harness 阻断 VERIFIED | 规则正文/历史中更广泛的间接攻击与真实模型受诱导率 NOT_TESTED |
| 初赛延期 | 生产登录、GUI、多 Agent、向量库、动态预算估算、复杂长摘要/DAG DEFERRED_BY_SCOPE | 模拟 CLI 可选身份属于约定的本地操作者能力 |

静态假设保留三项。负净额汇总存在同型格式路径，需独立验证。实际 SDK 是否连接缩写地址取决于传输与解析，保持 `HYPOTHESIS / NOT_REPRODUCED`。超出有限输入上限的历史或文件膨胀保持 `HYPOTHESIS / NOT_REPRODUCED`。全部正式攻击从本地模拟入口核验，未对外部系统执行扫描。

建议 SEC-B 先处理 #4 范围来源与 #5 凭据日志，再修 #6 金额。随后在各自边界修 #7 异常停止、#8 导入、#9 配置、#10 管理审计。历史 #1/#2/#3 保持原状态。本轮新增 Issue #4 至 #10，未关闭历史 Issue。进入 SEC-B 需要独立阶段执行，安全发布暂不放行。
