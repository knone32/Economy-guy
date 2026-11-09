# Astra → Sol High：关键修复与 Demo 交接

日期：2026-11-09。Repository：knone32/Economy-guy，分支 main。起点 `757d9d5b194fde953cad52cad3e61fb926989d3b`。
本文件与修复同一提交；用 `git log -1 --format=%H -- docs/delivery/ASTRA-HANDOFF.md` 获取该提交。

**结论：查询链路已取得针对性 Qwen Live 证据；可以开始真人 Demo 彩排，尚不能宣称完整 Demo/安全发布通过。**
真人确认提交、待办保存及重启恢复、最终录屏尚未执行。不要继续架构研究或扩展测试矩阵。

## 1. 四个核心问题与已实施修复

| 问题 | 实际证据 | 代码与修复 | 剩余风险 |
| --- | --- | --- | --- |
| 最终信封成为只读结果的额外失败门槛 | 原 Trace 1052–1072，`4aab798ffe6c4e9495769357cc92535b`：get_applicable_rules SUCCESS，随后两个 JSON 对象导致 INVALID_RESPONSE；812–832 的用途检查同样失败 | `app/agent.py` 无 tool_calls 分支：已有本轮 current_sqlite、全部 SUCCESS/NO_DATA、无管理/发票修改时，即使最终信封无效，也用 render_information 返回实际结果，停止状态 EVIDENCE_RETURNED；不展示模型金额或操作声明 | 该状态仅表示展示了列出的事实，不证明任意复合意图全部完成；剩余计划保持 PENDING。拒绝、失败与管理写入不走此恢复路径 |
| 内部上下文被当作 assistant 输出示例复制 | 上述失败原文追加 source=context_selection，与 ContextBuilder 注入对象一致；995–1005 的无工具 R002 回答在 json_mode=true 下也追加对象 | `app/context.py:ContextBuilder.build` 将 context_data 改为位于真实请求之前的 user 输入数据，不再作为 assistant 回答示例；仍由固定 system 声明数据不授予权限 | 复制与角色布局的关联有直接证据，但不能证明它是模型不稳定的唯一原因；没有做大规模 A/B。JSON 模式只限制语法，不能证明信封或业务正确；未更改供应商传输参数 |
| 必要查询未调用，以及规则类型选择错误 | 原 Trace 963–972，`7a6d06d778d44bcb8f77e023eb397a21`：直接复述历史金额、0 Handler。此次首批 R002 又实际选了 amount/R001 | `app/agent.py` 对有可信范围、含明确查询/财税线索、无本轮证据的 information/无效回答，只给一次纠正；清除该未核实回答、仅保留只读工具，继续用原预算/鉴权。`app/tool_registry.py` 明确 R001→amount、R002/R003→purpose、R004→bank | 有限线索只决定是否提醒查询，不选择/执行工具，不保证任意自然语言覆盖。第二次仍无证据则停止；当前 fresh Live 未触发纠正分支，该分支只有定向回放证据。错误工具类型仍可能发生，应看真实工具/规则而非模型结论 |
| 业务解释和失败后的可执行提示被展示层丢失 | 原 Trace 1073–1093，R003 已拿到含边界的 RuleDecision；TUI 用途卡片原先只展示数量/编号。错误停止分支直接拼接技术码与整个结果对象 | `app/responses.py` 与 `app/tui.py` 直接显示真实规则正文；失败提示说明权限、范围、取消、冲突及下一步，UNKNOWN_OUTCOME 明确先查审计，禁止盲重提。诊断码保留在执行状态/Trace。P1-I 原路径保留 | 当前 CLI 的部分完成诊断仍含状态码；TUI 使用自然语言 notice。规则正文目前沿用官方整数分表述，例如100000分，未另造计算规则 |

源日志确实读取：`finance_agent/data/logs/tui_trace.jsonl`，读取时 SHA256：
`a3f96b11e6bc26998d304591cb3f22e9321f31cedeacddb5eed6d5f3af9cf3af`。日志可能继续追加，以上行号与哈希针对本次读取快照。

年度待办旧故障不能算本次新修复：原 Trace 920–941 的 month=0 在当前 P1-I 代码已被范围协商拦截。此次原始响应回放和 fresh Live 均得到全年空值结果 + 仅支持2026-09的说明 + 明确替代建议，没有创建待办。

### 保留与未做

- 未改数据库、权限、规则判定、金额算法、事务/审计、Prepare/确认/Commit、持久待办确认、银行只读或9/12/2/1硬限。未接触用户既有工作库。
- 不放宽 parse_final，不把模型生成的“已保存”当成回执。恢复路径仅使用真实 Handler 结果；真实展示的列表才建立引用。
- 没有新增代理、路由器、规划器、持久状态机或工具；仅现有 Loop 中的一次局部纠正。
- 当前正常只读查询仍通常2次模型请求。没有在任意一次 SUCCESS 后提前停止，因为同一请求可能还有分页、第二企业、规则核验或后续待办；缺乏完整意图证明时不能把部分工具成功当作全部完成。现有明确计划完成路径仍可直接停止。后续不得为省一次请求牺牲这些语义。

## 2. 本轮实际验证

### Fresh Qwen Live（13次实际 HTTP 请求）

使用已授权 Windows Credential Manager 中 U001 的现有 Qwen 配置，未打印/保存密钥。
服务端返回 `qwen3.8-max-0902`；本次绑定配置 protocol=auto，enable_thinking=false，json_mode=false。
13次均 HTTP 200，usage 完整，共70206 tokens。HTTP成功不等于业务成功，失败轮计入总数。
使用 `tests/fixtures/example.xlsx` 初始化两个全新隔离账簿；各完成场景对比全部业务表内容哈希一致，排除允许变化的 reference_anchors。没有确认任何发票或待办写入。另用只读新连接直接SQL核对：发票962206分、收入1300050分、支出718074分；C002三张边界缺项和C001全年10张空值一致，invoice_audit/tasks均0条。

| 场景 | 请求数 | 业务结果 | trace_id |
| --- | ---: | --- | --- |
| C001 2026-09 发票/银行汇总 | 2 | PASS：9622.06/13000.50/7180.74元，10/4/8条，R001 v1.0 | 09ce60697fcb4eec8fc6b4c354da6843 |
| 接着“查一下甲企业这个月的发票与银行收支” | 2 | PASS：沿当前会话2026-09范围重新调用工具，没有复用历史金额 | 结果文件 repeat_current |
| R002首试，修复中间态 | 2 | FAIL：误选amount得到R001；且新增规则渲染分支误放在任务进度函数，触发NameError。未写库；该渲染错误已修复并定向测试，不能删掉这次失败 | 首批Trace最后一轮，6次请求总计中的第5–6次 |
| R002复验（携带前两轮真实查询历史） | 2 | PASS：purpose，R002 v2.0，“每张发票用途必填”，不采用旧1000元门槛 | 78d9861d62014208b69e6191633323d3 |
| C002用途缺项与1000元边界 | 2 | PASS：3张，F002/F005/F006；R003 v1.0，大于或等于100000分 | 692b810b7bcc45dbb25eea619cc35f94 |
| 全年空用途发票创建待办 | 2 | PASS（范围协商）：10张字段空值；建议明确选择C001 2026-09；任务未创建。最终状态SCOPE_MISMATCH属于预期拒绝，不是创建成功 | 8f39b989046a43558f2791217c1f93dc |
| F002用途改为资料打印 | 1 | PASS到Prepare：WAITING_CONFIRMATION；字段/审计均未变化。Commit未执行 | 734f5047b1e14bb78b745d3c362e74f4 |
| 真人确认Commit/待办保存、重启恢复、U002 fresh Live、最终TUI录屏 | 0 | NOT_TESTED | 无 |

以上是 Agent.ask + 真实 ModelTransport 调用，不是本轮真人 TUI 验收。最终一次纠正条件/提示收紧未改变上述已执行路径，但纠正分支仍须在真人使用中观察。

本机证据（均忽略、不提交）：
- `finance_agent/artifacts/astra/20261109-161500/`：首批虚构库、live.jsonl、前2个完成场景的result.json；R002中断须看Trace，不能只读result.json。
- `finance_agent/artifacts/astra/20261109-161816/`：后4场景的虚构库、live.jsonl、result.json。
- `finance_agent/artifacts/astra/replay.json`：原始R002污染、缺用途污染、年度month=0三条响应回放；分别EVIDENCE_RETURNED/EVIDENCE_RETURNED/SCOPE_MISMATCH。0次HTTP，只证明已知路径恢复，不是fresh Live。

### 离线兼容性证据

- 新增 `tests/test_astra_delivery.py` 8项：污染结果回收、无工具纠正、次数上限、纠正禁写、输入上下文角色、年度协商、规则渲染、部分计划未完成。
- 一次全量 `python -m unittest discover -s tests -q`：508项，32个失败记录（含subtest）。主要是旧“最终JSON失败应整体失败/文案必须含技术码”断言，以及纠正过宽、UNKNOWN_OUTCOME提示退化；均定位并修正。**不声称最终版本全量绿灯**，没有无意义再跑整套。
- 随后按受影响模块复验：143项通过；TUI/范围/目录等21项通过；另1项Qwen TUI收尾通过；补验52项中51项先通过，最后1项（2个subtest）完成机器状态断言迁移后单独通过。合计217个不同受影响测试已通过，含架构2项。
- 有一次命令误写不存在的 `tests.test_p1h.AccountTests`，产生1个loader错误；同批真实21项已通过，实际需要的Workbench测试已按正确类名单独通过。日志保留，不算业务失败或成功测试。
- 测试仅临时SQLite/虚构数据/模拟传输，不能用这些数量证明Live通过。未删除测试或降低权限、确认、审计、字段、ID配对断言；展示文案断言迁移到结构化停止状态，补充实际显示断言。

## 3. Sol High直接执行清单（按顺序，不重新研究）

1. **5分钟核对起点**：`git status --short`、`git log -1`，阅读本文件及本次diff。不要动用户工作库、原Trace、凭据或本机证据。无需重读两天报告。
2. **先做真人TUI彩排**：新建隔离虚构库（命令见下）。使用账户自己的已保存Qwen配置。首轮上限12次实际HTTP，使用执行记录/Trace统计；单轮原9/12/2/1限制不变。预算不足另批开始，不能重放不明提交。
3. **完成真正写入闭环**：U001发送“把甲企业 F002 的用途改成资料打印。”；真人核对旧值/新值后确认。核对只有C001/F002 purpose变更、一条COMMITTED审计、新连接readback一致。再查C001 2026-09应剩4张。人工取消另一次草稿，确保无新增审计。
4. **待办持久化**：发送“按甲企业2026年9月创建待办，下次继续补齐用途。”；真人核对预览并确认。退出重开同一隔离库/会话后，从待办打开并读取当前状态和剩余4张；不能凭历史消息说恢复成功。年度请求仍只给9月选择，不以“好”代替内容确认。
5. **安全反例各一次**：U002通过自己的配置请求C002查询应DENIED且无数据；U002修改C001应拒绝；取消/重启后旧确认不能提交。遇UNKNOWN_OUTCOME先用inspect-update核对request_id，禁止盲重提。权限与事务失败才是阻断问题，不以再加Prompt代替修复。
6. **只修复复验出现的阻塞**：若再次复制context_selection，检查EVIDENCE_RETURNED是否仍展示真实结果；无证据时应只纠正一次。若R002再次选amount，保留tool args/当前用户问题，不把R001结果认作R002验收。若模型在已有查询后提出无关追问，保留已展示结果并记录是否还有真实未完成范围；不要添加大范围关键词路由。
7. **录制与封包**：按下述≤5分钟稿录制。检查现有比赛包中的README、设计说明和操作命令与此提交一致；只更新必要项，不另建工程总纲。代码、文档与视频标注真实使用SHA。工作库、凭据、Trace、ZIP和个人Profile不要进入Git；按官方提交渠道另行交付。提交推送main，不force push。

新虚构库启动（finance_agent目录；Python使用已有依赖环境）：

```powershell
$demoLab = Join-Path $env:TEMP ("economy-demo-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $demoLab | Out-Null
python -c "from pathlib import Path; import sys; from app.cli_workspaces import import_workspace; import_workspace(Path('tests/fixtures/example.xlsx'),Path(sys.argv[1])/'demo.sqlite')" "$demoLab"
python main.py --db "$demoLab/demo.sqlite"
```

不要在命令中传Key，不要重新导入覆盖任何既有库。已保存Profile按可信账户选择，若不可用记Live BLOCKED，不向用户索取明文Key。

## 4. 五分钟Demo操作稿（待真人彩排验收）

| 时间 | 操作/口述 | 屏幕必须出现 |
| --- | --- | --- |
| 0:00–0:25 | 说明虚构数据，U001登录并选择Qwen | 当前账户/账簿/模型，不能露Key |
| 0:25–1:05 | “汇总甲企业2026年9月发票和银行收支。” | 三个精确合计及R001 |
| 1:05–1:40 | “乙企业2026年9月哪些发票缺用途？1000元也要填吗？” | 3张缺项、R003含等于门槛 |
| 1:40–2:10 | “甲企业2026年9月有哪些发票缺用途？” | 5张、R002 v2.0；按需问旧v1.0不作为当前依据 |
| 2:10–3:10 | “把甲企业F002用途改成资料打印。”真人确认 | Prepare旧/新值→确认→可信成功回执/回读；再次查询剩4张 |
| 3:10–4:15 | 明确创建9月待办并真人确认；重开/恢复 | 同一待办持久存在，重查剩4张 |
| 4:15–4:50 | 展示全年请求的9月替代建议或U002拒绝（二选一，事前彩排） | 不暗改范围/不越权；无伪造成功 |
| 4:50–5:00 | 指出执行记录与提交SHA | 不用Mock测试数量作结论 |

若Qwen响应导致超时，压缩口述和非核心问答，保留三核心场景及真人确认过程，不能把演示脚本或静态截图冒充实际执行。
