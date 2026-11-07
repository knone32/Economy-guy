# S4-SEC-B3 · Profile URL 校验与规则管理审计

2026-11-07，`knone32/Economy-guy`，`main`。本批处理 #9 和 #10。

- Base SHA `2c1f7c5a2603ad7c50609942c8cd003e8ea29abc`。开工时本地与远端一致，工作区干净。
- Tested Code SHA `e81b36ddfe9b06e2cac590ad91fffe9c16d686f0`，被测 tree `e3902c7b59244d525a4125d1e7ea7e55da5e8478`。Report SHA 可通过 `git log -1 --format=%H -- docs/verification/security/S4-SEC-B3.md` 查询。
- 改动位于 `finance_agent/app/model_config.py`、`rules.py`、`stage2_schema.py`、`finance_agent/main.py`。新增 `finance_agent/tests/test_sec_b3.py` 和本报告。

## 冻结探针与离线 Profile 验证

从 `finance_agent/` 运行，`python` 使用项目既有 Python 3.12.14 验收环境。原 SEC-A 探针、冻结案例及历史报告原样保留。

| 原命令 | Base | Tested Code |
| --- | --- | --- |
| `python scripts/sec_a_probe.py CONFIG-02` | 退出 1。127.0.0.1 拒绝，127.1 接受，本地数值解码为 127.0.0.1 | 退出 0。两种表示均拒绝 |
| `python scripts/sec_a_probe.py TRACE-04` | 退出 1。R002 v2.0 从 ACTIVE 变为 DISABLED，仅有 invoice_audit，无规则审计或管理 Trace | 退出 0。仍成功停用，发现独立 rule_management_audit。下列测试另核对实际审计行 |

#9 先检查 IP 字面量和合法 HTTPS 域名语法，再拒绝由十进制、前导零或十六进制数值组件构成的非规范主机。新增用例覆盖 14 个不安全主机，包括缩写、单整数、八进制、十六进制、回环、私网、IPv6、全角和百分号编码。DeepSeek、OpenAI 与普通合法 HTTPS 域名通过。现有 Global/User 权限和旧环境变量配置仍经原入口校验，非法配置保留已有文件且错误不输出合成密钥。测试阻断并断言 SDK、ModelTransport、DNS 和 socket connect 调用均为 0。实际模型 API 尝试 **0**。

## 规则迁移、原子性与实际 CLI

- `migrate-stage2` 显式新增 `rule_management_audit`，重复执行保留规则、业务表和已有审计。缺表时导入和停用明确拒绝并提示迁移。现有工作库未执行迁移。
- `seed`、`import`、`disable` 对每次实际变更，在同一个 SQLite 写事务中保存一条成功审计。审计包含事件 ID、时间、操作者、动作、规则版本及旧新状态。CLI 的固定 actor 为 `simulated_rule_manager`。可信 Python 入口的默认 actor 标识为 `trusted_python_rule_manager`。
- 重复停用及同内容重复导入返回 `NO_CHANGE`，不增加成功变更记录。混合导入分别报告新增与未变化数量。无权限、规则不存在、同版冲突、非法字段或参数、未迁移旧库及数据库故障均拒绝。失败通过命令错误反馈，成功审计表仅记录实际变更。
- 测试注入规则写入失败及审计 INSERT 失败。停用回滚。批次第二条出错时，第一条已执行的规则插入及成功审计也回滚。停用 R002 v2.0 后解析返回 `NO_APPLICABLE_RULE`，R001/R003/R004 保持原语义。
- 独立真实 CLI 进程验证。无独立权限时退出 2，状态和表快照相同。授权停用退出 0，返回 `SUCCESS_CHANGED`。新连接核对唯一增量为 `(simulated_rule_manager, disable, R002, 2.0, ACTIVE, DISABLED, SUCCESS_CHANGED)`。再次停用退出 0，返回 `NO_CHANGE`，无第二条成功审计。快照仅 `rules` 和 `rule_management_audit` 有预期变化，`PRAGMA integrity_check` 为 `ok`。

## 回归与门禁

- 新增 8 项。定向 96/96，架构 2/2。最终 `python -m unittest discover -s tests -q` 363/363，退出 0，耗时 33.548 秒。SEC-B1/B2 原探针 `ACL-06`、`TRACE-02`、`RES-01`、`TRACE-03`、`RES-05`、`RES-07` 均退出 0。
- 所有 SQLite 写入验收使用官方虚构夹具生成的临时库。发票、银行、发票审计及权限无变化。工作库前后 SHA256 同为 `f190ed7abeacf02d7964439a906e9ae2efe34ec956b2bc4352640549dca19433`。官方虚构 Excel SHA256 同为 `edb13b2a52d2f875033258836e8fc23c3e1353c46d101184048bac289e52ed0f`。未观察到未经授权的副作用。
- SEC-B 工程门禁 **PASS**，安全发布门禁 **BLOCKED**。#9/#10 保持开放等待独立复核，#1～#8 按既定结算。DNS 重绑定、代理、重定向及生产身份认证未验收，外部 Holdout 待提供。建议先独立安全结算，再另行授权 S4-BR。
