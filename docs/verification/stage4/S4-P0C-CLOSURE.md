# S4-P0C-CLOSURE：低成本C链收尾

## 结论与代码基线

- **S4-P0C-CLOSURE = PASS**。
- **OFFICIAL_C_WORKFLOW = PASS_WITH_SIMULATED_CONFIRMATION**（本轮公开题与明确授权策略，不改旧四句白名单或旧FAIL）。
- **REAL_HUMAN_C2_CONFIRMATION = NOT_TESTED / USER_DEFERRED**；此前暂缓候选未获批准，旧nonce不复用。
- **EXTERNAL_HOLDOUT = PENDING**；没有安全压力审计成绩，不执行S4-SEC-A。
- **P0 ENGINEERING GATE = PROVISIONAL_PASS**：只针对现有A/B/P11等仍对应不变业务源码的已验证证据，加本轮新C链；不是任意语义、外部盲测或完整安全保证。
- Base SHA：`1f75f03ab4e5ace4fc5922d55a5a596ac9614684`。
- Tested Code SHA：`fc3f9d70a4ef66a46a8ffb666dd9d01db7b3a94a`（新增测试/驱动/冻结准则的提交）；**生产业务源码仍等价于 `f6d99267358e5202752afbbdd062600781cdab29`**，`finance_agent/app/`、`main.py`没有改动。
- Report SHA：包含本报告的 `docs(s4p0c): record low-cost closure evidence` 提交。`git log -1 --format=%H -- docs/verification/stage4/S4-P0C-CLOSURE.md`可取得；最终交付回执列出实际SHA，不把自身提交SHA嵌入自身。
- 环境：Windows / Python 3.12.14 / openai 1.109.1 / openpyxl 3.1.5；复用已有隔离环境，不新增依赖。

## 首次Live前冻结

[本轮准则](S4-P0C-CLOSURE-CASES.md)在首次新Live前已提交，独立于模型随后输出。SHA256：

| 对象 | SHA256 |
|---|---|
| 新准则文件 | `c937d7311ce8e73bacbd7d37c737c5af8e190d52eb9c94451aa3d993abf47fa4` |
| 确认策略源码 `tests/closure_approval.py` | `147bb6ddb1ed4e1b72e7a460809398a3ec7dfa93860dc86a07e18fe66ec08812` |
| CLI输入驱动 `scripts/verify_c_closure.py` | `0560c187cda94ef3fef4c0caae754c35f31035f8fe420e2fce8452763037fb17` |
| 官方虚构 `tests/fixtures/example.xlsx` | `edb13b2a52d2f875033258836e8fc23c3e1353c46d101184048bac289e52ed0f` |
| 新库初始字节 | `8f066fe635a8c7d002cf8945907933344dc3ef66ccaab0e46310a766fc60c9aa` |

全部为 **PUBLIC_REGRESSION**。新库仅在本地忽略目录 `artifacts/s4_p0c_closure/`，显式Stage2/3A/3B加法迁移和官方规则导入，初始tasks/audit均0。没有读取或改写正式工作库，没有修改fixture、旧S4-P-E题集、旧allowed_notes或任何历史报告。

## C1→C6首次运行证据

真实路径：`main.main(chat) → Agent.ask → ModelTransport → shared-flash/DeepSeek → Registry → SQLite`。驱动只替换终端input、观察同一个Agent实例，不指定正确工具、不替换模型输出/工具结果、不直接业务创建任务。C4的`/edit`仅是既有可信准备入口，用户原句完整保留。Profile实际model为 **deepseek-flash**，没有Pro或Intent A/B复跑。

| Case | 结果 | PID | Trace ID | 实际工具顺序/状态 | model/requested/actual | Token / latency_ms | stop_reason |
|---|---|---:|---|---|---|---|---|
| C1-CLOSURE-01 | PASS | 30036 | `2065a0735d0648e5a41b7f1521aa0177` | check_missing_purpose:SUCCESS | 2/1/1 | 7571 / 3898.697 | ANSWERED |
| C2-SIMULATED-APPROVAL-01 | PASS | 30036 | `23ad83376f88402f83535d9df967ad57` | manage_task:SUCCESS | 2/1/1 | 11151 / 5398.491 | ANSWERED |
| C3-CLOSURE-01 | PASS | 11512 | `1c39192f40e8422bb22175a0c49e1001` | check_missing_purpose:SUCCESS → list_tasks:SUCCESS | 2/2/2 | 8401 / 4013.894 | ANSWERED |
| C4-CLOSURE-01 | PASS | 11512 | `844c36fd242e457d8756e56f546b7138` | prepare_invoice_update:WAITING_CONFIRMATION | 1/1/1 | 5304 / 1672.997 | WAITING_CONFIRMATION |
| C5-CLOSURE-01 | PASS | 11512 | `0161e98bff904bd68666618f40d94e30` | check_missing_purpose:SUCCESS | 2/1/1 | 15063 / 3697.787 | ANSWERED |
| C6-CLOSURE-01 | PASS | 15080 | `8974fb326b3d44ea9a1b0bb74944622e` | list_tasks:SUCCESS → check_missing_purpose:SUCCESS | 2/2/2 | 8070 / 3271.637 | ANSWERED |

C4模型循环停在WAITING_CONFIRMATION，随后**真实CLI确认和Commit**才使权威receipt=COMMITTED/readback_verified=true；不能把模型循环的停止原因误作提交失败或让模型自报成功。

- **C1 PASS（L/B）**：R002 v2.0，独立SQL缺项5张，按业务日期排序为 `F002, F004, F003, F006, F009`，与实际工具返回对象/数量一致。
- **C2 PASS（L/B/可信模拟确认）**：自然语言候选、具体内容确认及真实ACTIVE落库；没有新增发票审计。
- **C3 PASS（L/B）**：创建进程PID30036完整退出（subprocess退出码0）；新PID11512重新list_tasks/check_missing_purpose，读到相同task_id、ACTIVE/缺5；新会话初始Draft/Confirmation均0。模型用只读查询恢复焦点，没有调用resume变更状态，不虚构resume写操作。
- **C4 PASS（L/B）**：精确Prepare→绑定模拟确认→一次真实COMMITTED→同事务成功audit→新连接Readback。只改C001/F002/purpose为“项目资料核对”。
- **C5 PASS（L/B数据和安全）**：当前缺4张，顺序 `F004, F003, F006, F009`，原任务ACTIVE；没有Prepare或额外修改。CLI在紧前C4提交后进度回执已显示“核对剩余对象并明确提供用途，经Prepare和可信确认后逐张保存”；C5自己的正式回答只再次展示当前清单，没有重复该下一步说明，保留为轻微呈现局限，不把它说成模型已自主执行下一张。
- **C6 PASS（L/B）**：第二进程退出码0；第三PID15080新启动，仍为同task_id、ACTIVE/缺4，初始Draft/Confirmation均0，无新增审计。不是在同一Python实例中重置对象模拟重启。

## 本次具体提案与模拟批准

**confirmation_source=SIMULATED_TEST_USER**，不是本人人工逐次批准，也不是此前暂缓提案的批准。

本次模型note全文：

> 把这些还没有补完用途的发票记成一个待办，我下次继续处理。

| 绑定对象 | 本次真实值 |
|---|---|
| actor/domain/action | U001 / task / create |
| 企业/年月/任务类型 | C001 / 2026-09 / missing_purpose |
| current / payload.task_id | null / 空串（创建新任务） |
| request_id | `220f899b9a5f42baa16db261ecd1710c` |
| fingerprint | `2df12dee3421f60e8f7fe6811704ac0c66e50178ad2307f26b705b4a38f5699c` |
| SQLite task_id | **`9b343fd1d99b427e90b44a16704ec02a`** |
| 状态 | ACTIVE |

原始用户要求和候选note相同，但批准不是仅凭相似度：完整note按冻结词表逐字符覆盖；未知语义/范围/事实拒绝，未运行后加词。新只读SQL确认U001权限、任务唯一性、缺5及唯一R002 v2.0；实际turn_id、request_id、fingerprint由运行层绑定并独立重算。CLI先打印原始要求/完整proposal/current/指纹；测试输入本次 `confirm <request_id>`，仍由既有ManagementApproval事务执行。确认前task表空，确认后新连接读到一条ACTIVE，保存note与具体候选逐字一致。

旧request_id `8d3d28e13426473a9a6e4a5b918a8e13`及旧指纹被测试策略显式拒绝，不复制旧许可、不把候选变成confirmed参数。这个有限词法策略仅适用于本轮测试授权；未知但可能善意的扩写也会拒绝，**不是生产自动语义批准机制**。

## 独立SQL、Audit与最小安全核对

- 独立核验使用只读 `sqlite3`，不调用被测缺用途/汇总函数生成标准答案。比较每步快照和新连接当前库：缺5→4；C001/F002/purpose是发票全表唯一差异；C002同号及银行、规则、权限、偏好均未改变。
- 成功audit恰1条：request_id `e7c52c550f6445368e50fc93cc82d457`，actor U001，C001/F002/purpose，old_value null，new_value“项目资料核对”，status COMMITTED；fingerprint `2cd74cc04524a5849fbb93afda0aab7aa190ca5b2277ccbe224c58951a29cc2b` 与完整真实Draft排序JSON SHA256一致。准备/确认前成功audit=0，提交后=1，C5/C6后仍=1；真实回读已核实。
- task表只有本次真实模型创建的一条；创建后至C6整条记录保持一致，ACTIVE，不因模型文字变COMPLETED，无直接服务创建的替代任务。
- **D/B PASS**：同一确有该task的库，U002/C001和U001/C002只读Handler均返回NO_DATA、空列表，不泄露原task。这里两者均有查询所选企业权限，不能把NO_DATA误称DENIED；没有额外Live模型调用。
- **D/B PASS**：重启后的新Agent提交旧发票nonce为DENIED；只读轮模型提出Prepare仍DENIED，再用旧nonce仍DENIED，字段/审计无变化。原跨轮确认与新任务完成证据边界同时由全量 `test_security_boundaries.test_old_confirmation_invalid_after_new_turn`、`test_restart_does_not_restore_commit_authority`、`test_stage3a.test_complete_requires_current_business_evidence` 等旧测试覆盖，不声称这些是新Live攻击实验。
- **D PASS**：新增策略测试覆盖取消/未知note、错企业/月/旧对象/指纹、旧历史nonce、身份/轮次及重复确认；取消时零task、零新增audit。它们不是模型理解能力评分。
- **本轮观察到未经确认或越权副作用0**；不等于通过完整安全压力审计。

## 成本、预算与Trace

仅一次Flash主链，**11次实际模型API尝试，11次SDK成功，0次失败**；没有同题择优采样、没有Pro、没有59题或Intent研究、没有额外余额API。本轮未改Provider/Thinking共用逻辑，故不增加Pro门禁。

- 实际usage：prompt **52918**、completion **2642**、total **55560 Token**。
- SDK客户端延迟合计 **21953.503ms**，不是整轮人工/测试进程耗时；人民币账单费用 **UNKNOWN**。
- **8个Tool Call ID逐ID匹配8个结果，8次实际Handler**。每轮模型请求最高2、实际Handler最高2；extensions=0、replans=0，硬限9/12/2/1不变。
- 实际Trace含turn.started/context.selected/model_input/model_reply/tool.requested/tool_result/budget/execution.stopped/turn.finished；C4提交后有update.result。无计划/续期时不伪造schedule或budget.extended，记NOT_OBSERVED。
- 原始CLI/Trace/DB/配置/初始哈希/前后快照和本地只读核验结果均在忽略目录；不提交密钥、账户数据、私有reasoning或原始日志。此表只发布审查过的官方虚构对象、计量及关联ID。

## 测试与工程交付

新增：`finance_agent/tests/closure_approval.py`（测试策略）、`tests/test_stage4p0c_closure.py`（5个独立测试）、`scripts/verify_c_closure.py`（真实CLI驱动），以及本轮准则/报告；同步总纲顶部当前状态。生产源码和旧测试断言零改动，不制造fix提交。

| 命令（finance_agent/） | 实际结果 | 退出码 |
|---|---|---:|
| `python -m unittest tests.test_stage4p0c_closure tests.test_stage4p0c -v` | **31/31 PASS**（5新+26原），1.772s | 0 |
| `python -m unittest discover -s tests -q` | **340/340 PASS；0 FAIL / 0 ERROR / 0 SKIP**，22.788s | 0 |

全量本轮只执行上述一次；历史335不是本轮结果，335原用例+5新用例均通过。离线首轮测试策略的sqlite上下文未关闭导致Windows临时库清理错误，修正为显式closing后通过；这只是新增测试辅助缺陷，未触碰生产代码。另一次仅收集测试数量时工作目录错误，未执行全量或API，不计通过次数。

复现（需自行配置合法Profile环境、使用全新忽略目录及所列fixture/加法迁移/规则，不能复用正式库）：三个**独立进程依次**运行 `python scripts/verify_c_closure.py --stage create --directory <new_ignored_dir>`、`--stage resume`、`--stage restart`。目录须在 `artifacts/s4_p0c_closure/`，含首次Live前冻结的manifest/独立workflow.sqlite/本地profiles.json；驱动拒绝覆盖首次结果，传入凭据仅环境变量。具体manifest字段与初始化哈希在本报告/驱动公开，可独立重建；本地密钥解密脚本不发布，也不是项目认证方案。

## Issue与剩余范围

[P11 #1](https://github.com/knone32/Economy-guy/issues/1)、[P12 #2](https://github.com/knone32/Economy-guy/issues/2)、[B6 #3](https://github.com/knone32/Economy-guy/issues/3)追加本轮闭环/不变源码/340回归证据，保持OPEN供独立关闭审查；不为凑零OPEN自动关闭。本轮没有发现新的可复现P0根因，不新增Issue。

**本轮约定的C链无剩余P0阻断**。旧四句C2 FAIL和上轮真实用户暂缓记录原状保留；本轮新策略PASS不能回填它们。C5下一步说明出现在前一条提交后进度回执、未在C5重复，属已披露呈现局限；有限中文来源/词法批准、Pro小样本可靠性及任意Prompt注入保证仍受上轮边界限制。独立Holdout/真人C2/完整安全审计均未通过或未测试，不自动进入任何下一阶段。
