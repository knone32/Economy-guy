# R3-Closure

- Base SHA `03162e92b0f49c6eefa732520a88e74b4eebfd0f`
- Tested Code SHA `260cab92a33d203b05ec886c501a65d22ccefe2b`
- Report SHA 由包含本文件的独立文档提交标识，可运行 `git log -1 --format=%H -- docs/delivery/R3-CLOSURE.md` 核对。

## 行为与证据

| 目标 | 修复前 | 修复后 |
| --- | --- | --- |
| 年度只读 | 年度工具提案返回 DENIED | 单一明确年度或明确沿用已鉴权年度焦点后，可按企业统计全年发票及银行收支，或分页列出用途空值。独立 SQLite SQL 核对金额、条数和发票编号。错年、含糊、越权和数据库错误各自区分；无记录才返回零值。 |
| C5 | 查到 ACTIVE 和剩余 4 张，未说明 F002 当前已填写 | 对同一任务重新鉴权并在只读快照中核对当前规则、发票及成功审计。F002 有相符补齐审计时单列记录，无充分审计时只显示当前值已填写。分别给出待办状态、剩余数量和下一步。 |
| 无效最终信封 | 两页目录已显示，提示仍要求重新描述 | 保留两页可信卡片及逐 ID 工具结果，明确说明模型未能整理回复。Trace 保留 `INVALID_RESPONSE` 和 `invalid_final_envelope`，普通聊天不展示未核验成功声明。 |

年度用途空值是字段查询。月度 `check_missing_purpose` 仍只检查官方 2026-09；C001 样例的 R002 v2.0 与缺 5 张基线通过。年度金额沿用整数分、发票价税合计及银行收支分算。有业务记录时要求各有记录月份使用一致的金额规则。无规则或冲突时返回对应状态。

C5 仅在本轮工具证据能对应唯一待办与缺项检查，且只读复查一致时补充进度。成功审计无待办 ID，不能证明由某个待办促成写入。任务状态与写入回执各自独立，进度查询不会完成任务。独立 SQLite 快照确认查询未改业务表、待办或成功审计。正式工作库和 R2 试用库前后文件哈希一致。

## 验证

- 红灯 `python -m unittest tests.test_r3_closure -q`，退出 1。初始三个反例全部失败，分别为年度 DENIED、C5 缺当前值、无效信封缺清楚的收尾说明。
- 定向 `python -m unittest tests.test_r3_closure tests.test_sec_b1 tests.test_s4_br tests.test_r3_ux_a tests.test_ux_fix.AccountantTrialTests.test_save_and_current_progress_are_separate -q`，23 项通过，含 8 项本轮用例。
- 全量 `python -m unittest discover -s tests -q`，459 项通过（451 项既有基线及 8 项新增）。首轮 459 项中有 1 项失败，旧 Pilot 断言缺少已重新核对提示。恢复该提示后重新执行定向和全量，旧断言保留。
- 架构 `python -m unittest tests.test_architecture -v`，2 项通过。
- Mock 通过生产 Agent 验证范围、工具 ID、C5 当前值和真实本地受控提交及回读。Pilot 验证年度卡片、明确复用年度焦点及无效最终信封下的两页目录，逐行解析 JSONL 核对协议错误。均使用官方虚构夹具和隔离 SQLite。
- Live `NOT_TESTED`，真实 API 尝试 0。Windows Terminal 真人复验待办。历史真实证据仍按原被测 SHA 归档。 [Submission-R2](SUBMISSION-R2.md)

真人复验用虚构账簿，以 U001 输入「查甲企业 2026 年发票价税、银行收支和用途为空的发票」，再用已有 F002 补齐记录的同一待办询问当前进度。对照年度与 2026-09 卡片以及 F002、剩余数和待办状态。无效信封复现使用本报告的 Pilot，安全发布门禁沿用原状态。
