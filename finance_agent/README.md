# 云帐房财税 Agent Harness Stage 0–3A

这是Stage 0数据底座、Stage 1单模型Agent、Stage 2受控保存/规则管理与Stage 3A持久任务/偏好。支持兼容Chat Completions工具调用。

## Windows PowerShell

在 `E:\beside\finance_agent` 中运行：

```powershell
py -3.11 -m pip install -r requirements.txt
py -3.11 main.py init
py -3.11 main.py invoices --user U001 --company C001 --year 2026 --month 9
py -3.11 main.py bank --user U001 --company C002 --year 2026 --month 8
py -3.11 main.py summary --user U001 --company C001 --year 2026 --month 9
py -3.11 main.py test
```

若 `py` 不可用，请把命令开头替换为实际 Python 3.11 路径。`init` 先完整导入临时库再发布；已有目标默认拒绝覆盖。异常输入不损坏旧库。另建模拟库可使用 `--db data/new.db init`，不提供覆盖或增量同步。

## 连续输入 Agent

```powershell
python main.py chat --mode mock --user U001
python main.py chat --mode live --user U001
```

live 配置 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`（也接受 KEY、BASE_URL、MODEL）。CLI 身份仅是模拟，不是真实登录。输入自然语言、补充企业或月份，输入 exit 退出。模型自主追问和选工具；Mock 每轮固定查询 C001 2026-09，不理解自然语言。

唯一循环在app/agent.py，教学入口也复用。每轮最多3次模型请求、12个工具请求；错误/拒绝均配对结果后停止。业务查询使用只读URI；受控提交和明确任务/偏好管理用独立写事务。工具无user_id参数，统一ok/status/data/evidence/error。Trace默认agent_trace.jsonl（可--trace指定），包含mode、trace_id、脱敏输入/上下文、配对结果和错误。请勿输入凭据，通用脱敏无法识别任意无标记秘密。

主工具 `get_finance_summary(company_id, year, month)` 通过现有业务函数返回三项精确金额、发票/银行收入/银行支出分别计数，以及 R001《金额统计说明》1.0 依据。list_invoices、get_invoice、list_bank_transactions 保留原有查询语义。单次查询使用同一只读事务快照。

当前实现包含企业隔离的持久任务与偏好，但普通聊天历史只在当前Session；未做完整Context/Reference Resolver或调度续期，每轮仍最多3次模型请求和12个工具请求。Mock不证明真实模型理解。SQLite是业务唯一事实来源，安全初始化仍核对Excel数量/金额。

## Stage 2 迁移与规则管理

已有工作库使用加法迁移，禁止删除重导。迁移仅新增规则表、成功审计表，不修改发票或银行记录。新初始化的Stage 0库也运行此步骤：

```powershell
python main.py migrate-stage2
python main.py rules seed --simulate-rule-manager
python main.py rules find --simulate-rule-manager
python main.py rules import --file new_rules.json --simulate-rule-manager
python main.py rules disable --rule-id R002 --version 2.0 --simulate-rule-manager
```

`--simulate-rule-manager`明确模拟独立的`rule.manage`能力，不由U001的发票修改权限推导；没有该能力的管理操作默认拒绝。此标志和`--user`均非生产认证，正式部署需由可信登录会话提供能力。普通LLM工具不能导入、发布或停用规则。

导入JSON是规则对象列表，字段与`app/rules.py`的`SEED_RULES`一致。`rule_id/version`唯一；同版不同内容拒绝，变更使用新版本并显式停用旧版本。规则有scope、effective_from、status；解析必须唯一，否则返回缺少规则/版本冲突。规范正文由有限执行参数生成并严格核对，不接受任意文字解释器。规范正文是官方模拟业务规则的执行摘要，不是原文逐字复制。

`check_missing_purpose`仅支持2026-09：C001使用R002 v2.0每张必填；C002使用R003 v1.0大于等于100000分必填。空白字符视为未填，备注不能代替用途。判定和工具证据来自同一`RuleDecision`。金额工具在Stage 2解析R001；未迁移Stage 1库保留已有查询兼容行为。

## Stage 2 受控修改

```powershell
python main.py chat --mode live --user U001
# 输入：/edit 把甲企业F002的用途改为项目资料打印
```

`/edit`是可信CLI开启连续修改意图的显式声明，不是最终确认；自然语言理解和目标/内容提取仍由同一个模型完成。缺少目标或内容时保留自然追问。下一轮直接补充“甲企业F002”，CLI展示原始意图并要求输入`continue`关联，其他输入按新主题、清除旧意图；无需再次`/edit`。`/cancel`取消。精确企业+发票号才可准备，模型仅可调用`prepare_invoice_update(company_id,invoice_no,field,new_value)`。Prepare展示旧/新值但不写数据库，随后必须输入完整`confirm <request_id>`才确认该指纹草稿。每轮清除旧草稿和确认，跨轮只继承已由可信CLI关联的业务意图，不继承最终提交许可；新进程或身份变化全部失效。

提交使用`BEGIN IMMEDIATE`，再查权限、指纹及旧值。UPDATE与成功审计在同一事务，审计失败回滚；COMMITTED/NO_CHANGE之后由新连接回读。同request_id核查历史且不重复更新；若后来值变化，回读同时显示历史提交和当前值不一致。

所有轮次将答复与Harness的`write_receipt`独立展示。模型最终信封分三类：`{"kind":"general","text":"问候或一般概念说明"}`、`{"kind":"information","text":"查询组织建议"}`和`{"kind":"clarification","text":"自然问题","missing_fields":["invoice_no"]}`。一般说明只有在非修改轮、没有本轮工具结果、没有明确数字业务范围时才自然展示，并明确标为“模型生成、未核实、不代表数据库执行或当前业务事实”。数据库information仍由真实只读结果生成，不采信text里的保存声明；追问按合法缺失字段生成。Prepare仅为WAITING_CONFIRMATION；COMMITTED须通过可信CLI、request_id/审计/目标/指纹/回读校验。NO_CHANGE、DENIED、CONFLICT、ERROR独立报告，证据不足或回读异常为UNKNOWN_OUTCOME。

这不是任意自然语言语义验证器：一般说明仍可能说错、模型仍可能误分类或选错追问字段。其文字永远不是执行凭据；已开启修改或发生数据库查询时不能借general绕过证据展示。只有独立Harness回执代表真实操作状态，不靠关键词过滤或第二个审核模型。历史回执保留程序来源及编号，不伪造用户/工具调用，当前值须重查SQLite。教学Demo显式teaching=True与正式执行能力分离。

## Stage 2.5.2 查询范围与回复分类

每个查询结果独立显示实际企业、年月、current_sqlite来源和适用规则名称/版本；发票详情按当前开票日期补充年月。不同企业不无来源合并。仅银行只读查询缺少已导入R004时可继续返回明细，并明确NO_APPLICABLE_RULE，不伪造版本；金额/用途判定保留既有唯一规则要求。

范围检查只提取用户当前输入中明确的企业编号（如C001）与数字年月（2026-09、2026年9月），在Handler重新鉴权后比对工具参数；发票详情还比对当前日期。冲突返回SCOPE_MISMATCH并隐藏金额/明细，提示确认；U002请求C002仍优先DENIED，不泄露结果。多编号/年月仅按显式候选集合比较，不证明复杂配对语义。中文别名、“上个月”等隐含范围和跨轮锚点未做通用解析；无法验证时明确显示工具实际范围，不能静默替用户认定。没有引入关键词业务路由或完整Context Manager。

Agent.last_response.category区分general_unverified、clarification、database_query、operation_result、unverified，operation_receipt始终独立。CLI展示一般说明标签和独立操作回执；一般说明文本不是状态证据。跨轮/edit补充、最终确认、Trace降级规则不变。

```powershell
python -m unittest tests.test_stage252 -v
python -m unittest tests.test_security_boundaries -q
python -m unittest discover -s tests -q
```

```powershell
python main.py inspect-update --user U001 --request-id <保存的请求编号>
```

UNKNOWN_OUTCOME时先运行上述核查，不自动重写；没有成功审计也不能单靠日志断言已保存。审计与规则统一保存在当前SQLite；草稿/确认只在当前Session内存。业务表不增加修改入口，银行及其他发票字段仍只读。Mock聊天仍是固定只读汇总；Stage 2准备/提交通过临时库测试，真实模型另行验证。

## 学习提示

1. `initialize_database` 读取 Excel 的实际表头，把日期转成 ISO 文本、金额转成整数分后写入 SQLite。
2. 数据库中企业编号与业务编号共同组成主键，所以两家企业同号发票不会串数据。
3. 每个查询先调用 `check_permission`；程序而不是自然语言输入决定用户能否读或改。
4. 汇总由 SQL 对整数分 `SUM`，最后才格式化两位小数，因此没有浮点累计误差。

最值得先读的三个函数是 `app.importer.initialize_database`、`app.permissions.check_permission` 与 `app.finance._total`。

## 下一阶段

持久任务管理复用RuleDecision与现有查询；发票仍走Prepare/可信确认/Commit/回读，Commit不注册为模型工具。完整上下文选择、历史列表引用和调度仍延期。

## 最小 Tool Calling 教学实验

`examples/tool_call_demo.py` 只用于学习模型请求工具、Harness 校验执行和工具结果回传。它不修改发票、不会自动初始化数据库；`--user` 仅模拟可信当前用户，不能替代生产登录认证。

```powershell
# 不需要 API Key；终端会明确标记 MOCK / 模拟模型响应
py -3.11 examples\tool_call_demo.py --mode mock --case add
py -3.11 examples\tool_call_demo.py --mode mock --case finance --user U001 --db data\finance.db

# live 模式使用 OpenAI-compatible Chat Completions Tool Calling
$env:OPENAI_API_KEY = "你的密钥"
$env:OPENAI_BASE_URL = "https://你的兼容服务地址/v1"
$env:OPENAI_MODEL = "你的工具调用模型"
py -3.11 examples\tool_call_demo.py --mode live --case add
py -3.11 examples\tool_call_demo.py --mode live --case finance --user U001 --db data\finance.db
```

live 模式逐步输出用户输入、Schema 摘要、模型工具请求、Harness 校验、Python 返回值、工具消息和最终回答。服务商不支持工具调用、缺少环境变量或 API 请求失败时会明确报错。

## Stage 2.5 测试与职责索引

```powershell
python -m unittest tests.test_stage25 tests.test_architecture -v
python -m unittest discover -s tests -v
# 仅复制源码、教学入口和官方模拟测试夹具到临时干净目录再运行全部测试
powershell -File scripts\check_clean_environment.ps1 -Python python
```

测试默认使用tests/fixtures/example.xlsx（官方虚构数据原样副本）；可通过`$env:FINANCE_TEST_EXCEL = "绝对路径"`显式指定。始终导入临时数据库，完全不依赖项目上级目录和正式data/finance.db。不需要API Key。live须独立配置并验收，Mock不证明真实理解；未配置密钥时明确未验证。

生产模型可见和实际允许执行的工具均只包含统一汇总、发票列表/详情、银行列表、用途检查、适用规则、Prepare。教学add与旧summary/单项金额Python实现保留，但隐藏工具请求会被DENIED；可信内部调用须显式能力集。所有入口复用单一Loop/Handler。规则explanation为兼容补充官方限制，旧同版本正文与参数不覆盖。

Trace由app/trace.py记录mode、trace_id、上下文/实际模型输入、工具配对、程序回执及错误，保存前脱敏；历史模型声称不等于执行成功。请勿输入凭据，通用脱敏无法识别任意无标记秘密。运行生成的Trace、数据库、缓存不作为源码提交。

Trace写入OSError会标记`trace_degraded=true`并输出非敏感stderr告警；已核实Commit与SQLite成功审计不因JSONL故障降级或重做。数据库审计失败仍回滚，回读失败仍UNKNOWN_OUTCOME；日志降级不等于业务失败。

```powershell
python -m unittest tests.test_security_boundaries -v
python -m unittest tests.test_architecture -v
python -m unittest discover -s tests -q
```

Stage 2.5.1测试包含攻击性模型、伪角色、隐藏工具、跨用户/企业、Trace磁盘失败、审计失败和回读失败。它们验证确定性安全边界及真实临时库副作用，不证明所有Prompt注入或真实模型语义均可靠。`--user`和`--simulate-rule-manager`仍仅比赛模拟入口，没有生产登录认证保护。

## Stage 2.5.3 修改目标与规则日期

写入范围锁定企业和发票编号。`/edit 修改C001/F002用途为资料打印`开启的意图，不能被模型替换为C002/F002或C001/F003。Prepare业务服务先重查modify权限，再检查可信Session及Handler范围；冲突为SCOPE_MISMATCH，不创建草稿、不写字段或审计。目标缺失或不唯一为AMBIGUOUS，应继续追问；初赛已知“甲企业/乙企业”简称仅在写入边界映射为C001/C002，其他模糊指代不自动解析。

连续补充会保存原来的明确目标，不能把不同企业或发票号合并成允许集合。原意图C001、补充C002将拒绝；用户确实要更正时重新输入`/edit 修改C002/F002...`建立新意图，旧草稿/最终确认清空。每轮仍不继承Commit授权。范围提取是保守字面校验，不保证理解所有自然语言、引号内编号或新内容中的编号；有歧义时请单独明确企业、发票和内容。

Handler调用Prepare始终提供从可信用户输入或WriteCoordinator取得的范围；业务服务同时核对Session约束与调用方约束，不能互相覆盖。底层可信Python业务调用仍可显式传expected_scope；它不接受模型身份/确认字段。字段/内容的自然语言提取仍由模型完成，最终CLI须核对具体内容，不能宣称已实现任意文字语义证明。

`get_applicable_rules`的business_date必须为严格YYYY-MM-DD（拒绝20260901等变体）；鉴权后归一为year/month再与用户数字年月比较。请求2026-08而工具使用2026-09返回SCOPE_MISMATCH，不查询或返回9月规则。Resolver的启用状态、版本唯一性及生效日期判断不变，已有规则不更新覆盖。

```powershell
python -m unittest tests.test_stage253 -v
python -m unittest tests.test_security_boundaries -q
python -m unittest discover -s tests -q
```

本轮初始实际基线为116项通过，所列六项旧协议冲突未复现。两项原先以“改用途”直接准备草稿的测试补充了明确企业/发票输入，原有未确认不写与旧确认失效断言保留；新增模糊目标拒绝反例独立验证。

真实调用链见根目录docs/ARCHITECTURE.md与docs/flows/；ARCHITECTURE_CONTRACTS.md仍为目标。持久任务/偏好见下述Stage 3A，完整Context/Reference Resolver和调度续期未实施。

## Stage 3A 持久任务与偏好

已有Stage 0业务库使用加法迁移，禁止删除重导。以下沿用默认data/finance.db：

```powershell
python main.py migrate-stage2
python main.py rules seed --simulate-rule-manager
python main.py migrate-stage3
$createdTask = python main.py tasks create --user U001 --company C001 --year 2026 --month 9 --note "下次继续补齐九月用途" | ConvertFrom-Json
$taskId = $createdTask.data.task.task_id
python main.py tasks pause --user U001 --company C001 --task-id $taskId
python main.py preferences create --user U001 --company C001 --key reply_format --value "简洁"
```

每条python命令都是独立进程，执行后退出。也可关闭终端后重新打开，重新取ID恢复：

```powershell
cd E:\beside\finance_agent
$storedTasks = python main.py tasks list --user U001 --company C001 | ConvertFrom-Json
$taskId = ($storedTasks.data | Where-Object { $_.status -in @('ACTIVE','WAITING_USER','PAUSED') }).task_id
python main.py tasks resume --user U001 --company C001 --task-id $taskId
python main.py preferences get --user U001 --company C001 --key reply_format
python main.py tasks update --user U001 --company C001 --task-id $taskId --note "用户补充：分次填写"
python main.py tasks wait --user U001 --company C001 --task-id $taskId
python main.py tasks complete --user U001 --company C001 --task-id $taskId
# complete如仍有缺失用途返回CONFLICT，不接受模型口头完成
python main.py tasks cancel --user U001 --company C001 --task-id $taskId
python main.py preferences update --user U001 --company C001 --key reply_format --value "详细"
python main.py preferences delete --user U001 --company C001 --key reply_format
```

任务仅missing_purpose类型、初赛2026-09。ACTIVE/WAITING_USER/PAUSED均占用每用户×企业唯一未完成名额；TaskPolicy先检查，SQLite部分唯一索引防并发。create必须明确后续待办且当前存在缺失用途；一次性查询不自动创建。冲突保留原任务，明确取消后才能另建。update补说明，correct更正年月/说明（非2026-09拒绝）；不跨企业偷偷迁移，需取消并明确新建。终态不可恢复。

resume和complete重新鉴权、重查当前规则/发票；完成必须缺失数为0且有发票，历史完成证据保存在context但不替代当前业务值。取消不撤销发票提交。tasks/preferences是唯一持久状态来源，时间为SQLite UTC。

会话复用原Loop，通过明确动作开启本轮管理意图：

```text
/task create 保存C001 2026-09后续用途待办，下次继续
/task pause 暂停C001任务<task_id>
/task resume 恢复C001任务<task_id>
/preference create 请记住C001的reply_format偏好为简洁
/preference update 把C001的reply_format改为详细
```

普通自然语言也可提出任务/偏好新增、修改和删除候选，例如“请记住C001的reply_format为简洁”“删除C001的reply_format偏好”“把C001 2026-09缺失用途保存成下次待办”。候选没有管理权限；企业、对象或内容不明确时先补充。list_tasks、manage_task(show)、manage_preference(get/list)只读。模型不能自报user_id/confirmed/权限；所有写操作必须在可信CLI核对原始要求、具体对象与旧值/新值后输入完整confirm request_id。CLI身份是比赛模拟入口，非生产登录；规则管理权限仍独立。

验收补丁：`/task`与`/preference`继续兼容、约束本轮领域/动作，也不代表内容授权。普通自然语言通过无权限ManagementCandidate预览，可信确认后才生成ManagementTurn/Approval。其他输入或EOF取消，不保存。没有可信确认回调的Agent只返回WAITING_CONFIRMATION。许可绑定全部参数和旧值，只用一次，下一轮/取消/身份变化失效。请核对模型是否把“简洁”替换成其他内容或选择了错误对象；系统依赖这次具体确认，不用关键词或另一模型猜测语义。直接`tasks/preferences`命令仍使用用户明确参数，不经过模型。

模型追问若带未知missing_fields标签，程序生成通用补充问题，不显示任意模型成功声称，也不把该标签加入业务字段白名单；JSON/字段类型非法仍安全停止。4P-A仅经Mock/临时SQLite验证，真实模型自然理解、选择delete及多轮服务协议仍须另轮live复验。

恢复只返回当前任务和最新缺失项，不恢复Draft/Confirm/Commit。补用途仍须新/edit及最终确认。偏好按用户×企业隔离，无全局偏好；仅明确create/get/list/update/delete，不自动保存闲聊。Stage 3B按当前明确企业选择偏好作为带来源的数据，不注入system。

```powershell
python -m unittest tests.test_stage3a -v
python -m unittest tests.test_architecture -v
python -m unittest discover -s tests -q
```

test_stage3a使用临时库验证状态、限额/真实线程并发、隔离、CRUD、取消不回滚审计与独立子进程退出重启。测试不需要API Key；真实LLM验收另行标记。

## Stage 3B：有限上下文与展示引用

已有工作库只需显式新增锚点表，不删除/重导。未执行此迁移时原查询仍可用，但没有持久引用锚点：

```powershell
python main.py migrate-stage3b
python main.py chat --mode live --user U001 --max-context-chars 48000
# 先要求“列出 C001 2026-09 发票”，实际展示后再问“刚才第二张的用途”。
# 退出进程并重新启动同一chat命令，可以重查已展示引用；不会恢复旧草稿/确认。
python -m unittest tests.test_stage3b tests.test_architecture -v
python -m unittest tests.test_security_boundaries -v
python -m unittest discover -s tests -q
```

ContextBuilder按需选择当前请求、完整近期轮次、同企业/月未完成任务、显式偏好和可信历史数据。上限计量为序列化消息字符数，不含工具Schema，不是token估算。旧轮整段裁剪，保留tool_call_id配对；必需本轮超限时安全停止，请缩小范围。JSONL的context.selected记录来源/范围/裁剪，model_input仍记录实际脱敏输入。

引用只用正式答案实际展示过的顺序/联合键；支持“第2张/第二张”、单对象“那张”，多列表用明确企业或显示的anchor:ID消歧。解析后重新鉴权读SQLite，历史字段不是当前值。企业/月冲突、可信任务切换和取消失效旧锚点；不改变持久任务。昨天/上个月、多对象及复杂排序等指代未实现，证据不足请给企业/年月/发票号。任何引用恢复都不是写入授权，修改仍走/edit → Prepare → 可信确认 → Commit/审计/回读。

Mock与live共用原Loop；自动化测试是Mock/真实临时SQLite，含独立子进程恢复，不代表真实LLM验收。CLI --user仍只是模拟身份。Stage 3B没有摘要模型、向量库或第二Loop；Stage 3C的最小单轮调度见下节。详细引用调用链见上级docs/flows/context-reference.md。

## Stage 3C：最小计划与分块预算

简单查询直接Tool Calling，不多花一次模型请求规划。真正多步依赖才由同一模型提出set_schedule；任务恢复使用一个恢复步骤，不拆分SQL/事务/审计。计划只活在本轮内存，绝不修改长期Task或授予发票写权限。

默认3次模型请求一块；本块取得真实新工具证据、仍有合法未完成就绪步骤且权限有效时续3次，最多两次。单轮硬限9次模型、12次进入Handler的工具调用（含计划控制/参数校验）、1次显式重规划。重复调用、无进展、拒绝、等待用户/确认、完成或硬限都停止；同批全部tool_call_id仍配对回传，被跳过项不执行。模型声明完成不算证据，Prepare仍需可信CLI确认及原事务审计/回读。

```powershell
python main.py chat --mode live --user U001
# 可降低预算；不能超过9/12/2/1硬限
python main.py chat --mode mock --user U001 --block-requests 3 --max-requests 6 --max-tools 8 --max-extensions 1 --max-replans 1
python -m unittest tests.test_stage3c tests.test_architecture tests.test_security_boundaries -q
python -m unittest discover -s tests -q
```

Agent.last_response.execution提供计划和实际计数；JSONL的budget.extended包含续期原因，execution.stopped/turn.finished包含停止原因、当前计划状态及mock/live。计划COMPLETED只表示所列工具步骤取得证据，不等于持久任务完成或发票已保存。Mock CLI仍是原固定示例，不声称理解自然语言；多步/续期使用scripted_model自动化验收。详细实际链路见上级docs/flows/schedule-budget.md；没有动态token估算或Planner Agent。4P-D配置与运行层增量见下。

## 4P-D：可信模型配置与安全切换

财税用户U001/U002与模型服务计费账户是两回事。`config/model_profiles.toml`是无密钥模板，默认未选Profile；动态新增存入默认已忽略的`config/model_profiles.local.json`，加编辑锁、fsync后原子替换。同名（含不同用户/来源）明确拒绝，不覆盖旧配置。仅存`api_key_env`名称，实际Key由已授权环境提供；不在配置、SQLite或Trace保存实际值。`service_account_ref`仅是逻辑标签，不证明服务商真实账户或两把Key同属一账户。

Global新增需独立`--simulate-profile-manager`；U001不默认是管理员。User新增owner取可信CLI `--user`，只列出Global和自己的User配置，不能借模型参数选择他人的配置。此为本机受控模拟隔离，不是生产登录或主机文件/环境变量的多租户保密系统；不要暴露为公网服务。

在finance_agent目录，先由可信本地环境提供示例名称对应的凭据，然后运行（命令不包含Key值）：

```powershell
python main.py profiles add --scope global --simulate-profile-manager --name ds-shared --provider deepseek --service-account-ref company-demo --model deepseek-flash --base-url https://api.deepseek.com --api-key-env DS_SHARED_KEY
python main.py profiles add --scope user --user U001 --name ds-personal --provider deepseek --service-account-ref personal-demo --model deepseek-flash --base-url https://api.deepseek.com --api-key-env DS_U001_KEY
python main.py profiles list --user U001
python main.py profiles check --profile ds-personal --user U001
python main.py --db path\to\temporary.db chat --mode live --user U001 --profile ds-shared
python main.py --db path\to\temporary.db chat --mode mock --user U001 --profile ds-personal
```

check只做本地校验/检查当前引用凭据是否存在，API请求0次；Mock不读取实际Key。根参数`--profiles-file <toml>`、`--profiles-local <json>`可用于隔离实验；自选本地文件也应放入忽略目录，不提交用户私有配置。

选择优先级：CLI `--profile` → `FINANCE_MODEL_PROFILE` → 文件default_profile → 完整旧环境组。Profile选中后只使用该Profile完整参数和它引用的Key，不混入旧模型地址。不存在/无权/缺Key/不支持协议都报错，不fallback。旧入口优先完整OPENAI_API_KEY/OPENAI_BASE_URL/OPENAI_MODEL，否则使用KEY/BASE_URL/MODEL（保留API_KEY别名）；OPENAI组只配置一部分时明确拒绝混组。URL只接受HTTPS、无认证用户信息/查询串/片段，拒绝本机/私网IP字面量；此本地校验不声称能彻底阻止DNS重绑定。

`protocol=auto`沿用4P-C已验证端点/模型；`deepseek-thinking`只用于已验证官方DeepSeek；`standard`不发专用字段，DeepSeek显式standard会发送thinking disabled配置，不暗改auto默认。自定义DeepSeek代理协议不明确时保守拒绝。旧的直接Python live_model接口是无会话Facade，持久会话应使用Agent绑定连接。

可信CLI支持`/provider list`、`/provider status`、`/provider use <profile>`。仅轮次间可切换；待补充修改意图、未确认草稿/管理提案、活动请求/提交、未知提交结果会拒绝，先完成/核查或/cancel。切换总是创建新Agent/Transport，不搬运原assistant/tool历史或reasoning；同用户只保留重新鉴权通过的企业年月及带历史标记的用户目标，Task/Preference重新读取SQLite。任务/偏好/发票不删除，旧Draft/Approval失效；无法安全保留的临时消息不伪称完整继承。Key在连接创建时冻结，环境变量变化不会偷偷换Key；轮换后显式重建连接。更换财税身份会清空旧上下文，私有Profile不再可用。

JSONL原生记录api.request/api.response的Profile、Provider、Model、账户逻辑标签、协议、实际usage或UNKNOWN、SDK成功/HTTP错误类别及客户端latency_ms；SDK成功不臆造精确HTTP状态码。turn.finished包含本轮api_counts与原预算/停止原因；`tool.progress`表示无计划的工具证据，只有真实Schedule才记schedule.progress。Token数保留，不能当人民币实付；上下文和Schema字符量不是Token。私有推理和凭据显式遮蔽，偏好键名和计数不再因包含key/token被一概隐藏。

Commit/审计/回读先核实；附加进度日期缺失/非法、规则/SQLite或其他附加查询异常只让task_progress返回ERROR，不遮蔽原COMMITTED/NO_CHANGE，不重写或新增成功审计。详细真实链路见`../docs/flows/models-profiles.md`。
