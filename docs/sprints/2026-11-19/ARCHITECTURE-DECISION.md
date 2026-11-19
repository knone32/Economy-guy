# 架构职责决策（主会话负责）

目标：真实DeepSeek自然语言单票修改→缺目标待补→用户补目标→fresh事实→可信绑定→正式预览，确认/拒绝仍由真人界面；只有预览Live通过才验证后续写链。用户现授权架构职责纠偏，取代第四阶段停止开发状态；历史候选/证据/账本保持。

## 已确认的冲突与分类

A：R3A真实Trace行5/18仅有完整selection提案，行21最终正文识别未选对象但无pending事件，行22 ANSWERED。部分语义正确、动作选择/输出协议遗漏；Runtime窄门接受回答且交付抹掉待补说明，非合规提案被拒。
B：R2P.1 explicit_invoice_candidates_required使pending未建，R2P.2原company在首轮明确但后续AMBIGUOUS；缺可信来源为状态链级联，不可通过信模型ID解决。
C：R2Q初始BETWEEN查询与独立真值相同但scope UNKNOWN/unsupported_predicate，扩大读取后预算拒绝导致缺比较。属于范围证明/结果交付/预算，不把未知末回复算NLU失败。已实现typed事实不删除；本切片不虚称修完任意SQL分析。
D：S4A request→合法pending成功；补目标fresh正确，propose多company_id被实际anyOf拒。业务槽正确但工具参数非法，Runtime按协议拒绝；该合同让同一企业在一分支必需/可用、另一分支禁止，并让模型搬运selection/pending引用。

## 方案比较

|方案|内部字段/重复状态|能力与安全|时间成本/同类风险|
|---|---|---|---|
|A 保留双模式，仅容许并校验company或拆名字|仍要求LLM维护action切换、selection、pending_id、mode、excluded以及跨工具读取|可保原底座；不能静默删字段|改动小，但只是多放一字段，未消除引用搬运和状态协议遗漏|
|B 单票业务动作一致参数，Runtime组织内部读取/提案|LLM只给已知company/年月/票/field/new_value，后轮可仅补票；不传生命周期、selection、确认、mode|Runtime校原话/已验证pending、身份/范围/ACL，fresh读取后调用原plan和preview/事务底座；复杂集合/规则接口保留|局部调用链改动较A多，移除一类参数切换和重复状态责任，今晚可小切片验证|

选择B。不重写Agent Loop/权限/DB/事务/审计。新增单票业务入口change_invoice，旧集合/规则提案仍供该能力使用；Runtime拥有该入口建立的pending时只向模型展示一致单票接口，避免切回旧内部协议。旧API保留兼容和已有批量能力，不伪装为新接口成绩。最终JSON旧状态协议不再用于该入口；只展示已知业务槽，不要求返回内部request_id。必要内部proof为服务端创建，不能由模型提供。

## 各边界职责

自然语言/业务动作由模型决定；Tool Registry严格校声明的业务参数，未知/授权参数拒绝，不删键；来源绑定从当前明确原文与同actor/book的已验证pending获得，不从任意readset建写对象；Runtime生命周期/actor/book/执行引用服务端持有；SQLite和现有plan负责权限/实际对象/日期/现值；UpdateSession/正式preview/真人确认/事务幂等审计回读不改；结果证据仍绑定指标/范围/真实回执，不能模型自报保存。

补目标只在已存在此业务动作的可信pending中接纳当前唯一明确标识符，缺对象不猜；初始完整对象仍需现有写角色来源证明。完整参数由Runtimefresh读取再调用原plan，不要求模型先get再复述ID；内部调用独立标记runtime，不伪造model toolcall。

## 安全门禁与进度

权限/企业隔离/当前actor/book/原文field-value来源/明确对象/正式preview/人工确认/事务/审计/幂等/回读不得变；模型没有提交入口。冲突先拒或追问，不按问句添词表。

当前起点业务SHA5253deea95fbc8090fb4253d6f5ffce8318f7fb3，控制f1a97b0，独立business-ownership主会话直接实现，尚未冻结/无新Live。预算用户新授权12请求/180000total/输出2048，旧封账不动。先公开Trace机制及必要正反例，再冻结、C两个独立新表达；只有真preview通过且真人实际操作确认才能验写，不允许自动批准。若再次出现职责冲突先停定位，不自动全仓重构或大型下一轮。

## 实施后冻结状态

已实现B：change_invoice只有company_id/invoice_no/year/month/field/new_value，一套业务参数在两轮保持一致，未知项省略。Runtime状态保存业务来源；后续仅票号或重复known均可，实际fresh读生成执行证据，服务端BoundIntent只从验证后数据建立，再用原plan和Workbench预览。内部读取以business.invoice_read标记，不伪造成模型ToolCall。旧propose保留完整批量/规则合同；第四阶段action=request已明确退休，避免两个不完整办理入口竞争。非法参数仍拒，不删键。

独立窄审确认known重复曾要求当前重证，现改为继承已验证字段/值来源，当前字段或明确字面内容冲突拒；初始字段/值来源不凭任意读取建立。唯一字段与字面值不要求同分句，多字段仍保留已有来源角色校验。未证明任意未加引号的自然语言更正都被理解，须Live评分。

程序验证：evidence-business/final-checks.log相关35/35，含新完整业务API正式preview取消无写、冲突来源/ACL/日期、原事实与复杂SQL选集正常/缺票保护。旧request 7检查2fail2error原样保留retired-wire-contract.log，不计新能力通过。首次导入NameError、测试callback签名错误及相对日志路径错误保留既有日志/记录，均非Live。无全仓审计/全量刷题。

冻结候选c9b8948398e4e194e0e02bf226ac3d8158db43f6（实施97d6cce），独立frozen-runtime-business；business-acceptance/FREEZE.json锁source/profile/依赖/driver。C此后才生成两新目标/SQLite真值/表达。当前尚未证明Live预览，两场仅reject，真人确认后写入另阶段，不自动批准。比较SQL范围/末交付旧问题C未在本切片实施，不宣称四类问题全部解决。

## C阶段与用户明确人工核验续接

C两场已封存business-acceptance/MANIFEST.json64文件。第一场2轮真实模型业务动作→Runtime待补/fresh读取→正式Approval与SQLite匹配，record后仅reject，场景PASS。第二场2轮业务及Prepare正确，但Approval.on_mount #cancel NoMatches，原turn-2结果/actual body未保存，UI交付FAIL/最终STATE未测；不能从正确Prepare推preview成功，也不将未完成归NLU。独立root跨库SQL/seed/快照相同、audit0，C4请求32848tokens/无未知用量，原分不改。

UI调度零API探针未复现，根因未定为产品或runner，未修改候选、未重跑第二挑战。用户随后明确授权“继续人工预览核验”，不计原挑战补分；business-human独立目录继承本轮C四请求前缀继续同12/180000总限，不动C封条。真实原生Workbench固定同c9源码，只增加挂载后只读记录器/预算守卫，没有Pilot/自动approve；登录/输入/确认由用户本人。只有实际预览独立核对正确后才可由用户决定确认。当前人工窗口已启动PID30188，尚未新增API或业务写入。

computer-use技能禁止自动终端及认证对话框，故不使用UI自动输入登录或请求；该限制已链接告知用户，由真人操作，不将自动测试视为批准。所有原始server draft/实际挂载preview记录、用户输入Trace及真实DB/audit供核验。未完成之前不宣称整体门禁已过或提交成功。

人工阶段启动更正：初始PID30188只是进程成功，未验证可见窗口；MainWindowHandle0、无SessionStore、无新增API，不能将其报告为已打开真实窗口。验证命令行/预算/空会话后仅停止自己的空闲进程，所有fixture/日志保留。新增START-HERE.cmd由用户桌面双击直接启动；manual_workbench只在明确idle restart且业务表未变/无已登录会话/无新增API时允许复用初始fixture，不重放已执行业务。当前等待用户操作，人工预览/确认/提交均未观察。RESULT-business.md和NEXT-DECISION-business.md为真实当前结论，不是完整链已通过。

## 用户续接：先做新Live与接口职责测验

用户明确要求暂不发人工通知，先再做一轮Live和接口职责测验。仍同c9产品冻结，不改源码；当前同一授权12/180000已用4/32848，未重置/加授权。人工未登录无新API，TESTING-LEASE防与测验并发读取旧前缀。business-live2从5追加，旧C和旧四账全部原样保留。

新runner仅等待真实Approval Mount完成、两按钮存在且cancel聚焦后才保存/拒绝，依据本地Textual1.0实际代码顺序；零模型ready probe通过。这不是宣称原NoMatches仅runner或已修产品UI；原错误仍未定根因，旧分不改。C在新runner元数据冻结后才生成新目标/SQLite真值/表达：一场3轮实质更正后补目标预览，一场1轮相近词汇但真实只查询语义对照，最多4输入，不择优重跑。

职责程序检查当前冻结8业务+4权限+2原选集保护=14/14（INTERFACE-CHECK.log），不计NLU。观测重点为业务参数/Runtime状态/来源及fresh职责，不是单纯通过数字。任务进行中，不自动调用approve/Commit或开启新修复。

## 新Live与接口职责测验结论

用户“先再测、不发人工通知”已完成，产品c9未改。business-live2两新场景4输入首执：连续更正办理FAIL，转述修改但真实只查询对照PASS；全层2/4，formal preview0。模型更正remark/季度交接待核正确且业务参数合法，但Runtime坚持同一原文业务分句，拒绝后保留旧purpose/生产资料领用，补票再发生源缺失级联。

root原输入/原参数/原pending零API重放：通用字段/值边界True，同分句检查False，pending_transition.py:211 SCOPE_MISMATCH；当前原话字段和值均存在，位置形式约束覆盖了合理语义。来源层仍扮演第二自然语言解释器，这是职责残留，不是缺字段工单。UI又把字段值错误泛化为企业/账期错误。不能因安全无写就说办理正确。

接口职责程序14/14只是机制；独立root SQL/DB/66封条/ledger复核一致。新增5/42274，累计9/75122（同12/180000），余3/104878。本轮停止API，不开新修复/大架构计划，不发人工操作通知。原C NoMatches未在本轮触达，根因/修复状态仍未证。候选仍不晋级，下一职责决策应针对来源证明和业务语义的边界，不加词表/分句特判或放宽真实授权。

## 来源职责修复决策（实施中）
公开ROOT-LIVE2-RESPONSIBILITY证明合法remark/原文新值被同分句约束拒绝，旧purpose待补未失效，界面误报企业账期。保留分句规则只放宽标点仍是第二语义解释器，拒绝该方案。
选择局部业务来源绑定：field为受限模型业务槽；新值须当前用户原文字面或有效待补来源，记录消息ID/hash/span。可选relation表示补充/替换/歧义，value_ref表示当前/上一有效内容/清空；不是内部生命周期或许可。Runtime自行管理superseded/on_hold，替换验证失败也不能复活旧执行候选。普通读工具不变更待补；不从最终正文推断动作。
来源存在不等于模型语义关联必然正确，转述与否定由模型决定；缺少唯一语义选择须clarify，预览和真人确认保障实际修改授权。企业/对象仍须明确标识符或可信同actor/book pending，fresh读取及ACL/确认/事务不变。不会把同消息包含词串宣称为完整语义证明。
实施位置source-semantics，候选尚未冻结；零新增Live。正式程序路径后再评估新Live就绪，不沿用旧剩余额度。

### 实施与边界（来源修复候选冻结前）
已实现business_sources单一绑定模块，正式单票request_change委托此模块；旧高级/兼容接口保留，不代表全仓已移除语言门禁。语义字段不是数据库事实或许可；来源只证明出处。企业年月配对/对象范围验证失败不得保存为known，先保留可信旧范围并暂停修改内容。来源成功后的fresh读取/账期/提案失败保留新候选，不回退旧修改。
新内容须本轮字面；沿用同字段值省略new_value，显式提供历史值要value_ref=previous。这是业务引用关系而非内部状态ID，但有旧调用兼容性成本。自动接受重复旧值的实验曾让陈旧内容进入预览（source-related.log），已撤销，未用引号扫描/关键词去判断是否更正。
最终13项来源/状态/真实Workbench挂载拒绝检查通过；先前37项必要契约通过，最后范围失败保留可信旧范围的变更仅相关13项复验。旧8项6通过/1失败/1错误原样保留，不宣称全绿。正确重复旧值无引用会澄清为P1兼容性风险；另一个旧断言期望拒绝更正后保留旧值，与任务失效目标冲突，仍保留失败成绩。
公开3轮正式程序重放与独立SQLite一致，真实预览挂载成功，仅拒绝，业务及运行表相同/audit0。没有新Live，模型采用relation/value_ref及陌生语义仍未证明。暂不晋级，不修改写入确认/事务/审计底座。
