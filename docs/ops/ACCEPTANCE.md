# 验收（V3；不同SHA不拼接）

7ca6a90原链5HTTP：查询与修改route正确；原澄清格式missing_fields=[purpose]被通用待补接收后目标丢失，FAIL首点为表达/状态交接，非数值或权限错误。修订只将无旧待补、单编辑字段缺值且原展示唯一的澄清候选归一到既有change_invoice，原resolver/fresh/ACL及待补持久化复用，无新值/批准/owner。不跑零API，直接新Live，原run-08失败保留。同原账115请求，零业务写入。

73e3b0e新续办2HTTP：legacy选路PASS，首次get_invoice被原读取依据门禁拒绝，FAIL归工具暴露/执行契约；无越权、无业务写入。仅收紧原legacy工具暴露到现有owner实际可执行能力，保留显式编辑owner合法点读，change_invoice内部目标解析和fresh读取及原分发拒绝不变。不跑零API，下一次真实模型重新建立fresh查询来源后直接办理，旧失败保留、不重算陌生首分。同原账110请求；API0的旧进程会话占锁启动另记。证据为run-07/OBSERVATION.public.json。

ed2e79f续办：选择对象和建立用途待补PASS，模型暂缓意图PASS；原会话持久化FAIL，候选为空。首断点为脱敏器将真实task-chain路径中的sk-误当密钥，候选载荷因此未通过严格原样校验；不是模型暂停错误。修订仅收紧凭据token边界，依最新指示不跑零API，下一次直接Live验证持久化并继续GUI恢复/改口。新增4HTTP，原账108/963780tokens/1495974微元，业务写入/自动批准0。原失败及明细查询旧成绩不改，程序与人工GUI仍分开。证据为本地run-05/OBSERVATION.public.json。

59d7d38已执行原链回归：查询PASS；四个独立逐字段要求、首卡和末答完整，SQLite真值VX-A/347850分/空用途/空备注。第二节点FAIL：开始修改但尚缺新值被模型解释成旧查询的read+unresolved，未选择已支持的legacy，业务工具0；后续暂停/恢复/改口/确认/保存/重启均停止，业务记录/旧审计不变。4HTTP，同原账累计104/933868tokens/1453412微元峰价上界；旧首分不改。仅对已有route补齐读取与变更的定义及继承前提，原Loop/Schema/批准不变，9项相关零API检查通过。下一Live只从原会话已展示对象续办，不重复查询；不把程序接线成功当模型理解通过。详见本地run-04/OBSERVATION.public.json。

明细要求/交付契约修复：具体列举现在使用逐字段details(field)，details(*)仍要求全部业务字段；展示完成不再取决于企业/日期也出现在SELECT。原可信范围及筛选检查不变。四列明细的首卡和末答引用覆盖、少列/星号反例、实际展示引用→原修改入口fresh读取与缺身份拒绝共3项零API检查先红后绿；相关41项范围、ACL、SQL混合卡片、引用及架构检查通过。无新增Schema/模块/Loop/状态owner，无自动批准/提交。当前仅程序证据；下一Live在冻结源码后回归原链，不改下述三轮失败，不宣称陌生泛化。

当前任务串未闭环：7985956、a7ad830、2f11f78三轮均在查询节点停止，各3HTTP。正确首卡不等于整条任务完成：独立要求将具体列举字段表达为details(*)，执行投影与之不一致，最终覆盖仍partial。2f11f78实际模型输入已含缺列说明，后续仍未补全，原失败与回包均保留，停止继续付费。全部依赖的对象办理、暂缓恢复、改口、预览、真人批准保存及重启未执行；不得把此前旧链成功迁到本轮或把程序UI恢复通过当Live。运行库财务数据及旧审计相对基线不变，父库字节未动，自动批准0。新增9请求/75267tokens/121164微元；同原账100/898186/1365694，三限null、unknown_usage=false，金额是峰价上界。详情为本地evidence-root/accountant-task-chain-20261121/TASK-CHAIN-STOP.public.json，第四项陌生/扩展短验收未启动。

当前连续办理任务的GUI补充（尚未Live/真人签收）：原待续页把候选编号、修订和内部字段直接交给用户，与旧截图及现源码一致。现从“待办”按业务摘要选择，隐藏值仍交原恢复入口。实际UI选择→原CAS恢复及旧修订拒绝的1项检查通过；相关恢复交付1项通过，零API、零审计。自然语言、工具Schema、状态owner及批准机制未改；完整自然模型→改口→真人保存→重启尚待本轮执行。桌面观察工具启动失败另记，不把程序画面当作人眼观察。

展示切换的零API补充：在f9acd59上新增“票号＋逐票金额＋窗口数量”检查，实际复现窗口COUNT触发统计优先返回并遗漏两笔明细金额。修订仅收紧整卡切换：所有列须有已渲染的维度或逐行scalar事实，否则沿原逐列展示。该混合检查先红后绿；原纯统计和UNKNOWN一起共3项通过，输入结果/SQL/证据未变。不新增Live，不改原首分，不宣称覆盖所有SQL或真人界面。

## 1b06941：必要契约修复Live结束，随后只修统计卡展示

一个冻结SHA、同原账和规则前提已满足的独立虚构副本，实际7条原计划消息、13HTTP。A02歧义、B01筛选前置、B02保留、B03撤销、C01 Skill简称与C02普通表达共6节点PASS；A03要求/执行/独立真值/末答PASS，首卡cnt:2缺业务标签与单位，原自动FAIL保留，canonical LIMITED。B02/B03/C01为此前未执行消息的首次执行，其余披露后回归；不宣称新陌生盲测或总体泛化。唯一六列表及原件为本地v3-c2-acceptance/read-context-skill-compat-next-v1/FINAL-SIX-COLUMN-1B.public.json，不再复制第二张成绩表。

原SQL独立核对吻合，运行副本和旧封存库字节不变，业务写入/发票审计/草稿/确认0，真人GUI未测试。新增13请求/103960tokens/277079微元；同原账累计91/822919/1244530微元，三限null、unknown_usage=false、原全部历史保留，费用为保守峰价上界而非供应商账单。

最后仅tui.py的SQL统计卡复用既有事实渲染，不改要求、工具参数、SQL/证明器、覆盖、Loop或owner。2项显示正反检查通过；原A03实际回包零API重渲染已明确显示张数和元金额，原结果与末答未变。此为程序证据，原卡/自动FAIL及13b首分不改，新展示SHA未重跑Live，不能移植1b06941成绩。无需再为确定性重述付费。证据在本地evidence-root/READ-CONTRACT-COMPAT-A03-CARD-RENDER.public.json。

---

## 13b67a8：4零API＋3组读取/上下文/Skill首执

结论：三组均未整体签收。固定一个SHA和一个新独立虚构账簿；计划8条、实际5条用户消息，9个真实HTTP。只按首次偏离停止依赖，独立对照继续；无重放、无源码/提示词/规则改动。表中SHA均为真实受测版本，后续记录提交不迁移成绩。程序卡片适配不是真人桌面验收。

| 场景 | SHA | 首个偏离层 | 用户可见结果 | 账簿变化 | 结论／证据 |
|---|---|---|---|---|---|
| 零API① 等价协议 | 13b67a8 | 无 | 三种表示绑定相同，冲突来源拒绝 | 无；审计0 | PASS；source-forms.json |
| 零API② 既有工具 | 13b67a8 | Runtime能力契约 | 规则缺项、目录和展示引用缺适配；backend0 | 无；审计0 | FAIL；three-tool-paths.json／CORRECTION.json |
| 零API③ Skill可见性 | 13b67a8 | 独立语义输入 | Skill已启用，业务定义未进入首输入 | 无；审计0 | FAIL；skill-first-semantic-input.json |
| 零API④ 完整／部分收尾 | 13b67a8 | 无 | 全指标事实直出；缺张数仍partial | 无；审计0 | PASS；准备参数错误保留，CORRECTION.json |
| A01 完整名称 | 13b67a8 | 无 | 唯一销售方金额/张数卡片及末答正确 | 无；审计0 | PASS；A01-original-first.json |
| A02 共享简称 | 13b67a8 | 无 | 两家可区分候选并追问，未合并统计 | 无；审计0 | PASS；A02-original-first.json |
| A03 仅回答名称 | 13b67a8 | 工具说明／Schema层级不一致 | 要求继承正确，但多余顶层seller被拒，无统计 | 无；审计0 | 原FAIL保留；A03-original-first.json |
| B01 筛选前置 | 13b67a8 | SQL证据核验 | 要求正确；查询形式未获证据支持，无统计 | 无；审计0 | FAIL；B01-original-first.json |
| B02 保留筛选 | 13b67a8 | 前置失败，停止依赖 | 未发送模型输入 | 无；审计0 | NOT_RUN；依赖B01 |
| B03 明确撤销筛选 | 13b67a8 | 前置失败，停止依赖 | 未发送模型输入 | 无；审计0 | NOT_RUN；依赖B01 |
| C01 Skill术语 | 13b67a8 | 零API③门禁 | 未发送模型输入 | 无；审计0 | SKIP；不判模型词义能力 |
| C02 普通表达 | 13b67a8 | 验收库配置／工具依赖 | 要求正确；空rules表导致无适用规则，无统计 | 无；审计0 | 原交付FAIL保留；C02-original-first.json |

证据根目录为本地business-20261120/v3-c2-acceptance/read-context-skill-13b67-v1-complete/。原独立首表FINAL-FIRST-UNIFIED-SIX-COLUMN.public.json不变；USER-SIX-COLUMN-FIRST.public.json仅投影上述六列并追加归因，不修改原分。所有实际要求已由独立SQL/业务合同核对，不能拿生成SQL自身作用户要求的依据。

A03参数确实超出Schema，Runtime拒绝符合契约；补充审查确认，当时模型实际工具描述写“可选seller”，却未说明它只能位于read_scope.seller，给出了与Schema不一致的层级指引。因此不能只记作模型不遵协议，原FAIL不改。当前第一刀统一说明与Schema：BusinessRequest由Runtime持有，SQL仍落实筛选/指标/分组；兼容候选只能位于read_scope，顶层seller继续拒绝，不静默删除。描述契约红例复现后，3项零API契约正反检查通过；尚未迁移为修后Live成绩。B01原件仅明确SQL_EVIDENCE_UNSUPPORTED；is_blank是允许的SQLite函数，静态代码可定位=0形式等归因能力边界，但未通过重放动态隔离唯一内部原因，不能称SQL非法或业务理解失败。C02只读依赖检查确认rules为空，不把验收前提缺失算作模型不理解，也不补规则改原首分。B两项改口和Skill词义能力均尚未验证，不追加相似题。

新增9请求／55505tokens／133971微元峰价保守上界；同账累计78／718959／967451，unknown_usage=false、累计三限null。整个虚构库字节未变，审计/草稿/确认0。原Live分数、旧提交链及人工GUI反馈继续单列。

修后新增程序证据（不改上表）：B01原SQL与原用户/前SQL要求原样使用，分层隔离出布尔比较、常量投影、冗余条件三道限制；修后金额1829.25元，完整覆盖且仅交付所需SUM，原额外COUNT被既有投影排除。证据在本地evidence-root/b01-sql-contract-diagnostic.json及b01-sql-contract-repaired.json，后者保留随后发现的blank=False措辞错误，另以正反展示检查修复，不覆盖原记录。SQL有限正反5项、措辞1项、真实Agent首语义Skill采集与相关负例/架构8项分别通过；一处测试目标拼错未执行，补跑仅该项通过。Skill隔离切片另有28项受影响检查，不与主树数字相加；已存在的旧助手mock协议测试失败保留，不宣称全量全绿。新Live仍待统一候选冻结。

工具接入新增程序证据：隔离切片72项相关检查通过，有限字段收口后只补相应13项；单次集成复核发现引用覆盖既有可信scope，修前正反复现后，仅4项相关检查确认修复。主树实际Agent三个原失败入口分别走通独立语义→绑定→原工具→覆盖及原展示；不冒充自然模型。接线中暴露display_ids=None与reference未纳只读集合两处交接，按首错修复并仅复核未通过路径；目录原有专用renderer与通用business_card不同，检查入口误用另记。没有执行写入、自动批准或全量测试。新Live仅在清洁冻结候选上运行，程序数字不累加为成功率。

---

## 展示层修订：零API隔离检查通过，非新Live

验收只覆盖会计在不展开技术详情时可读修改对象、字段与原新值、用户要求/fresh核对依据、影响张数/未改字段、未保存状态。规则来源单独展示名称/版本/条件/实际命中，不臆造法规依据；query/partial主文保留金额、张数和限制，去除原SQL表达及财务JSON。原机器证据仍留技术/审计记录，业务核验与审批/Commit路径未改。

11项受影响程序检查通过；原160×48隔离预览可见摘要与按钮、技术详情默认收起且可展开、cancel-first保持，取消返回False后零草稿/批准/审计、临时账簿字节不变。原核验统计数值/范围/覆盖不变。没有模型API，没有再次修改原已提交的NV-C，没有声称真人已理解新摘要或修后自然语言泛化。截图及日志仅在本地evidence-root/readable-display-20261121/，不入Git。

提交前另补齐金额列表条件逐项分转元的展示，只复核对应1项，未重复其余已通过检查；原金额、单位元数据及SQL条件均未改变。

---

## 00cb8b3：本轮同账公开业务链闭合

真实模型的歧义追问、选择后首卡及末答通过；目标统计3478.50元／1张与独立真值一致，现有覆盖检查完整，未再请求模型复述。原候选恢复、补值和fresh预览由原owner执行，用户点击后原回执COMMITTED并核实新连接回读；唯一审计对应同预览request_id，仅NV-C备注改变，用途和其他票未动。实际新进程原工作台的目录／发票详情再次读取一致，零API，无旧候选复活。新增5物理HTTP，旧失败/原分不改；这是公开回归，不是陌生首执。

人工操作与正式GUI签收分开：用户曾报告看到并点击确定，随后迟到问卷又报未看到预览；这些原话保留。当前实际窗口是保存后的重启详情，不能据此再提交一次，也不把程序/回执等同完整GUI人眼验收。当前授权链所需写入、审计和重启已完成，停止追加同类检查和Live。

[结果与分账](../../../evidence-root/STAGE1-SAMEBOOK-CLOSURE-00cb8b3-RESULT.json)；[反馈补充](../../../evidence-root/STAGE1-SAMEBOOK-CLOSURE-00cb8b3-HUMAN-FEEDBACK-ADDENDUM.json)。

---

## 当前修订仅程序通过，Live／人工未签收

可选Source默认表示与完整统计事实直出已完成受影响正反检查；核心仍是同一要求、同一结果proof、同一事实覆盖与渲染。原SQL写法、失败回包及首分不改。程序证据不能替代Live。下一次使用原公开同账簿及原待续候选，经原工作台／既定DeepSeek路径执行查询和选择，完整交付后立即推进恢复补值与预览；原Approval只由真人操作，预览不计保存。审计、新连接及重启回读后才可签收闭环。不会新增陌生题、同类矩阵或架构范围。

---

## 7ec8358 只查询 Live 结果（冻结源码不改）

一次公开续查已执行，真实SQL与首卡事实PASS：C001、2027-04、砚川展览服务有限公司、3478.50元、1张均与独立SQLite真值一致。首帧多余relation_source:null触发一次结构补正；末答第四个逻辑请求在HTTP前被原64总限拒，实际HTTP3。最终是PARTIAL_RESULT／final_selection_not_verified的Runtime原结果回退；未见模型错误末答，亦不能称完整末答闭环或自然语言泛化通过。

旧候选PAUSED，业务／审计／草稿／批准0，guard_halted=false。恢复办理NOT_RUN；GUI人眼、真人批准、保存、提交后重启NOT_TESTED。原账64／629620／758261微元峰价上界，物理请求额度用尽，停止付费。原评分与所有raw保留，不靠脚本补成功。仅验收记录更新，不修改受测源码。

[独立证据](../../../v3-c2-acceptance/public-chain-mixed-diagnostic-20261121/runs/public-query-only-7ec8358/INDEPENDENT-OBSERVATION.public.json)

---

## 当前签收边界（上海2026-11-21；仅第一阶段）

有限默认值／来源／继承检查已结束：root121项受影响检查通过；独立业务谓词满足，原报告的拒绝码期望差异保留，不能称原报告全绿。原f618／804b公开content本地诊断仅为程序证据，原df684／8b61 Live失败保持。当前冻结修订的下一次Live只验选择销售方后的统计卡与末答，不自动扩大到恢复办理。GUI人眼、真人批准、保存、提交后重启均NOT_TESTED。原账61／608090／691874，余3物理请求。

最新公开混合诊断（df68496，非陌生首执）在选择销售方的第一次真实 HTTP 后失败：业务字段对齐，来源对象／字符串协议错配被误作缺原话；0 Handler／统计卡，末答拒绝。恢复、补值、fresh Approval 均 NOT_RUN。旧候选仍 PAUSED，账簿／audit／批准0。原结果保留，不能与程序成功拼成已闭环。

修订只统一已有 scope Source 声明，原真实 content 原样的零 API owner 对照已交付正确范围、3478.50元／1张；114项受影响／架构通过，修后 Live 待验。纯脚本原 Workspace 同链此前已到 fresh 原预览（NV-C备注旧备注→公开链闭环复核，用途不改），仍不是真人批准或真实模型写入证据。原池现60／602203／664656，余4次；原64／700000／2.20元不变。

| 证据层 | 实际结果 | 不能据此声称 |
| --- | --- | --- |
| 6937c3e 同版 DeepSeek S 首执 | S01 目标新期间金额／张数正确交付；S02 两个可区分销售方加明确追问，未合并；旧候选均 PAUSED、零写。S02 原措辞评分 1 的独立追加纠正为 2，原记录保留 | 选择后的统计交付、恢复修改、真人保存、四对验收通过 |
| 本轮最小 Runtime 修订 | 原 native→歧义→仅全名程序提案不改，首个丢失点修复后实际统计 3478.50 元／1 张与 SQLite 真值一致；原临时上下文仍空，源来自已核上一份要求；108 项受影响／架构通过 | 真实模型已自主完成该续办、同版真人验收完成 |
| 本轮链闭合 | 正在继续同一公开虚构案例；到批准处必须停给真人 | 已保存、已审计或已重启回读 |

第一阶段退出条件仍未满足。取消不落账、改口后旧批准失效及正确提交后新连接／进程回读，必须分别据实核对；不固定回复句式、SQL 或调用次数。程序和模型分开记账。原 R／O／K 失败不改分，不把 6937 的 S 成功迁给后续源码。完整回归仍失败，暂不重复全量。

当前正式预算为 59／593310／612638 微元峰价上界，余 5／106690／1587362；历史费用 UNKNOWN。真人批准／保存／提交后重启 NOT_TESTED；无自动批准。证据入口同 [STATE](STATE.md)。下面保留旧验收快照。

---

## R真实首执后的统一入口修订（待新同版自然语言验收）

- R01/R02确已在冻结 `d45b829` 各首执一次，合计2个真实HTTP；均未完成交付，原首分永久保留。R01查询提案的目标销售方、新期、SUM/COUNT经独立真值核对正确；R02是分组候选探索，未完成澄清，后续歧义语义为UNKNOWN，不能说已误合并或完全理解。共同首断点：native pending绕过独立要求阶段，天然SQL提案未带旧intent.read，ReqNone被分发安全拒绝；首卡失败，末答无请求事实，旧pending仍active、零写/草稿/批准。
- 封存前SCHEMA-ONLY的live_executed=false是历史快照，不是当前状态。最新入口见 `v3-c2-acceptance/sealed-r01-r02-v1/public/CURRENT-STATUS.public.json`；实际HTTP输入类别附录纠正：当时只发送invoice_change的known/missing，未发送原native原句或两家seller目录，不把模型未见信息算漏判。
- 当前修订只统一普通自然语言的首语义入口，pending不再关闭preflight。原read/legacy/general输出schema不增加：有效read绑定后Runtime才暂停原native owner，legacy继续原协调器。失效旧状态不供语义来源、不泄漏值、不阻当前明确新读；有效原用户source、有限known/missing只作上下文，不是新读scope或授权。SQL及工具提案不进入该阶段，bind/首卡证据门、草稿/批准owner不改。
- 148项受影响定向/架构组合通过。独立最小检查：read绑定后pause、legacy保留、坏来源不提前pause；6项helper来源边界通过。旧正例的金额、范围、零写、待补保持断言保留，去除固定四轮/旧sidecar必经夹具；兼容负例仍逐ID配对并拒绝跳回写路径。不增请求块或额度，不重复完整回归。本修订尚无真实模型通过结论。
- 上次R准备曾由根把预算owner误写C2，SharedBudget在HTTP前拒绝。独立确认零HTTP/零原题发送/零凭据读取，原AUTH/claim/run全保全，另记INVALID_PREPARATION，不算模型首错；更正为原契约owner=C后才发生上述两次真实首执。产品和题未改来绕过护栏。
- 当前预算55请求/565682tokens/553394微元峰价上界，余9请求/134318tokens，原64/700000/2.20元与未知历史费保留。接下来冻结修订，由独立验收另封S01/S02（各至多4、共8；不要求实际次数），不重放R、不改题措辞。即便通过，只证明既有待补中的一次新查询/消歧，不能证明追问后续办或旧票恢复批准保存。

---

## d45b829 冻结验证：先真实模型，不再扩接口

- 代码冻结：`d45b829134f75608fa37c43ad34ded7b52a1dfe5`，`frozen-read-handoff-d45b829` 与根 315 个 tracked 文件逐字节一致；63 个 app 文件摘要 `e21fc4ba6bc6e1fe0ef4049dc3b53d91bf626d3304d99cdc09f2e7cd1a84f010`。后续文档变动不算产品改版。
- 待补原生单票转查询已复用原协调器暂挂、同 Loop 独立绑定新要求；旧票号、月份及修改字段不自动继承。草稿和批准生命周期未复制。普通明细行语义与列事实资格分开，未知聚合/窗口不当展示列丢弃；原 `is_blank(单个原字段)` 保留。工具注册声明集中，原 10 组集合保持等价，六项适配能力未扩大。
- 程序证据：140 项定向/架构通过；独立投影 10 项通过；真实挂载 Workspace 程序链首卡/末答为新月 9046.35 元、10 张，旧候选 PAUSED、草稿/批准/audit0。独立 SessionStore 进程恢复另有证据。均为 API0，不能替代真实模型或真人签收。
- 冻结版全量：1166 项、468 FAIL、203 ERROR、462.400 秒。相对上一 1136 项，消除函数地址差异后新增/消失失败 header 均 0；仍不通过，不折算业务失败率。保留原日志，当前不重复全量。
- 用户最新决定：先验当前冻结版真实模型，允许不同合法回复、SQL 和调用次数。独立 R01/R02 已封存，只变销售方全名唯一/简称两家这一条件，固定明确企业、同一新账期、金额和张数、旧 native 待补状态及可见结果。旧待补以真实 Agent 非 Live 准备，陌生新问才为模型首执；不得强迫 intent/SQL/四次回包。R 私题与真值不供根或模型读取。
- R 尚未收费执行。统一账本仍 53 请求 / 544661 tokens / 522563 微元峰价上界，未知历史费用不记零。R 分配各至多 5、合计至多 10，仍原 64 / 700000 / 2.20 元总限；AUTH 仅准备，须 runner 审查及自动审批后启动。重复 O 授权不增执行次数，O01 FAIL、O02 PASS、整对 FAIL 原分不改。
- 公共 runner 审查先发现 setup 顺序会由切模型取消候选，已仅改测试胶合为先切模型再持久/恢复真实 native 状态；未收费、不算模型 FAIL、不改产品。继续审标准 Workspace→Agent.ask→ModelTransport，原题单次原样送入，无输出清洗或预定路径。
- 剩余缺口：旧通用 pending 安全交接、显式准备会话汇总后草稿、同版自然语言泛化、真实人批准/提交/重启回读未过。额外新 Tool alias 实验在 DESCRIPTIONS 登记处失败，属额外改版证据；按用户最新要求仅记账，不为假想失败扩冻结接口。D07、整行引用相减分别记录。不得晋级 main。

证据入口：`evidence-root/READ-HANDOFF-d45b829-FREEZE.json`、`READ-HANDOFF-d45b829-FULL-RESULT.json`；`v3-c2-acceptance/detail-projection-independent-1795185671065246100/SUMMARY.public.json`；项目根 `pending-read-workspace-check/run-1795185801170679900/UI-HANDOFF-REVIEW.json`；`v3-c2-acceptance/sealed-r01-r02-v1/public/SEAL-MANIFEST.public.json`。

---

## 普通请求入口与分发闭环候选（O 原分保持）

用户已核实单位“金额换成元”触发旧 invoice_intent_source，导致 O 两题跳过独立要求。根另以公开虚构“金额以元显示／金额换算为元”在 05b 动态复现同类入口分歧；证据 `../evidence-root/unit-display-entry-1795179080837136600/RESULT.json`。当前改动让普通只读轮进入要求阶段，不再依据旧修改关键词跳过；读取期间推导亦不取该关键词判断。已绑定读取要求后，由该要求持有当前动作解释。

Agent 财务分发独立于旧 _business_contract_required 开关验证：当前 BusinessRequest，或既有 WriteCoordinator 中经核对的显式单票编辑 Session。后者只允许相同企业＋票号的 get_invoice，不能授权汇总、SQL、其他票或失效状态；权限仍在执行处 fresh 核对。before-handler trace 与结果 evidence.read_basis 记录实际依据；没有依据即零 Handler。

O01 投影能力限制另修：仅请求已绑定路径允许保留已证明的原 SUM/COUNT，未归因的附加展示列先从结果投影删除；完整保留原 SQL/hash、原列归因与映射。WHERE、范围、日期、分组、单位与指标核验照旧；默认旧路径仍 UNKNOWN。COUNT 非空字段等价只依据同一 SQLite 读事务捕获的 NOT NULL 约束；nullable、DISTINCT 不泛化。is_blank 空串统一为证明器 True，False 保留非空语义，不重算金额。

106 项定向/架构通过。独立闭环 17 项有效控制通过；两个无权限正例的无效夹具记录保留后仅补验。原公开 9 项、两组两轮及新 J 同一源码全部通过：J 原 B 加“金额换成元”，先要求再执行，卡片/末答 1797、2357 元／各 2 张／差 560 元，新增 ROUND 列不作为金额事实，原 Scope/条件不变。证据：项目根 `business-request-matrix/ENTRY-CLOSURE-PUBLIC-REGRESSION-1795181100193228500.json`，`../v3-c2-acceptance/UNIT-ENTRY-DISPATCH-PROJECTION-INDEPENDENT-REVIEW.public.json`。自然写入测试夹具增加必经的 kind=legacy 回复，原待确认/零审计业务断言保留；显式编辑 fresh get→prepare 仍待真人确认，未提交。

05b 完整回归 1124 项／426FAIL／186ERROR／680.262 秒不通过；不能迁移为本候选成绩。本源完整回归正在运行。修后新主路线尚无同版真实模型通过结论，O 原首 O01 FAIL、O02 PASS、整对 FAIL 永久保留。

O 外发初拒后，用户已明确授权各一次首执；已完成 2 个请求，不因重复答复增执行次数。统一账本现 53／544661／522563 微元峰价上界，余 11／155339／1677437，原 64／700000／2.20 元总限不增，历史总支出 UNKNOWN。私题/完整回包公开仍未授权，不披露不绕过；新公开 D01 J 标准模型回归仅准备、未收费，不重跑 O。

---

## 读取要求结构重述候选（首分不重算）

针对已获准的无业务值结构摘要，只加强有限 JSON 协议并沿用 Agent 原 Loop 允许一次结构重述。仅合法 JSON 的 `kind=read`、纯结构 INVALID_ARGUMENTS 且已有模型槽可用时进入；输入仍只有原独立要求上下文和静态错误提示，不读取失败回复/SQL/执行提案。严格 bind、重复键、ACL、来源、范围、对象消歧和卡片/末答核对不放宽；全部调用计原预算，无新 Loop 或草稿 owner。

88 项组件/架构通过。独立实际 Agent 11 项黑白对照通过，正确结构继续真实 SQL/候选，secondbad/改票/重复键/无槽/ACL/来源/语义歧义/截断均遵守停止边界；原失败正文 sentinel 未进入补正输入，业务/审计零写。公开原 9 项及两组两轮再回归通过，未触发多余结构补正调用。证据：项目根 `business-request-matrix/PROTOCOL-PUBLIC-REGRESSION-1795178067386666500.json`；`../v3-c2-acceptance/structure-repair-independent-1795178112606624000/SUMMARY.public.json`。

此版本完整回归正在运行，不能迁移 9e78334 全量或 Live 成绩。O01/O02 新对已零 API 独立封存、尚未首执；待新冻结/同账授权及零收费标准传输重绑，计划各最多 6 次物理请求。旧 N/K 首 FAIL 永久保留，不以换题重算。

---

## 9e78334 同版陌生首执与完整回归（结果保留）

独立 DeepSeek N01/N02 各首执一次，均 FAIL：独立要求阶段分别因多余顶层字段、未决项/销售方值类型不合契约而被 INVALID_ARGUMENTS 阻断；无 SQL、无统计卡片，未交付数字或候选追问，账簿零写。不能因对象/指标/歧义语义识别改善判成功。首报告：`../v3-c5-sealed/n01-n02-sealed/public/N-FIRST-9e78334-REPORT.json`；原 N/K 首分永久保留。

9e7833448f5199cd20110324d395de0cf66886c6 最终完整回归：1115 项／427FAIL／185ERROR／568.623 秒，仍不通过；79 组件与同版公开 9 项、两组两轮替换对照属于程序证据。原断言保留。完整回归记录：`../evidence-root/BUSINESS-REQUEST-9e78334-FULL-RESULT.json`；UI Approval ERROR 本次未再出现不能当已修。

共享账本 51 请求／523016 tokens／505052 微元峰价保守上界（非账单），余 13／176984／1694948；旧 49 条前缀保留、unknown_usage=false、原 64／700000／2.20 元限不增、历史总支出 UNKNOWN 保留。未自动批准、未合 main、未推送。

自动审批拒绝公开私有 N 原题及完整回包；该动作未执行，不绕过。后续只使用获准的不含题面/业务值结构摘要 `N-SEMANTIC-STRUCTURE-ONLY.json`。目前优先修通用结构接口，不修改 N 首分或放宽来源、ACL、对象歧义、卡片核对边界。

---

## 独立读取要求：第一步候选（2026-11-20）

当前分支仍为 `sprint/2026-11-20-contract-followup`，保留 `097d04d` 及此前所有提交。`Agent.ask` 先独立形成只读要求，再绑定企业/销售方、执行并核对卡片和末答；要求判定不读取拟执行 SQL。实现边界见 [读取契约](../BUSINESS_REQUEST_CONTRACT.md)。这是模型语义解释，不是形式证明或写入授权。

79 项新要求/分发/结果/末答/架构组件通过。最终源码真实 Textual 9 项公开程序对照全通过，显式只读 replace 与默认 update 两组各两轮对照也通过（同一 app hash 集）；此前入口漏接和合法集合误拒的原 FAIL 记录保留。最终程序证据：项目根 business-request-matrix/run-1795176300849900700 与 relation-run-1795176427532020200；卡片和末答 B 为 560 元、C 合法集合为 8560 元，业务零写入。独立 Agent 末答控制已验证反向补正正确与再次反向安全回退；并非 Live 或真人验收。

初版全量 1103 项／427FAIL／186ERROR／683.395 秒，不通过。相较 7914d9a，191 个旧参数化测试标题仍失败，新增 422 个标题；14 个旧标题在 FAIL/ERROR 间转换。新增失败没有一律归为旧 mock：已实证显式新查询被旧筛选束缚（现补只读 replace）和未适配工具能力限制。原断言全部保留，最终源码全量正在运行。证据 `business-20261120/evidence-root/business-request-full-first.log` 及独立 `d01-semantic-review-work/artifacts/business-request-full-triage/FULL-LOG-COMPARISON.json`。

N01/N02 仍未首执，必须新冻结源、同账授权和零收费标准传输重绑定后各一次。原 K01/K02 仍仅属于 92f708e 且均 FAIL；不能改分。账本仍 49 请求／511727 tokens／445084 微元峰价上界，原总限 64／700000／2.20 元不增，历史 42 元累计 UNKNOWN 保留。

范围尚有限：只适配登记的 SQL/汇总/发票与银行列表等接口；未适配工具不算支持。多轮改票要求与原草稿修订关联、新工具通用接入尚未完成；D07、整行引用相减和真人批准/提交/重启仍另列。无业务写入、无自动批准、未合 main、未推送。

---

## D01 92f708e 首执 FAIL（不可改分）

后续证据能力分类：36项定向通过。实际Textual原SQL加合法但尚不归因算术谓词→SQL_EVIDENCE_UNSUPPORTED／dataNone／“统计核验能力受限”；精确卖方换广LIKE→SCOPE_MISMATCH／dataNone／范围不一致。两个首工具后停止，卡片与末答无统计数值，零API／业务零写。总项目根 k01-proof-classification/run-1795168283439703700 保存raw，旧文案harness误判记录保留，不当产品失败或真实Live成绩。

7914d9a分类修复全量1038项／160FAIL／31ERROR，无新增失败／错误标题，仍不通过全套。隔离语义review新阶段未进入主候选：C2已实证CASE投影seller过滤漏检与重复JSON字段误接受，待修复后重新审查，不进入新陌生题Live。N01/N02仍SEALED_NOT_TESTED，旧K首FAIL保持不变。

公开零API A/B/C程序对照通过，不等于陌生题通过。K01精确卖方正确SQL被runtime误拒；K02歧义简称跨卖方合计被放行，两题正式同版DeepSeek首执均FAIL。新增3物理请求／34835tokens，业务表零写入。证据 ../v3-c5-sealed/k01-k02-sealed/public/K-FIRST-92f708e-REPORT.json。

首执披露后定位：月份OR触发sql_evidence unsupported_predicate，改成等价IN静态对照VERIFIED。后续OR修复及同题检查统一标AFTER_DISCLOSURE_SCRIPTED，不当Live或改首分；新版本正式Live尚未执行。K02用户关系约束仍是实际漏口。

K01 OR修复：35项定向通过。B真实Textual原用户／原SQL／原read_scope脚本模型回归通过，卡片6895元／3张、8300元／2张；末答差额1405元、数量差-1张。产物总项目根 k01-or-repair/run-1795167617925099800；外连0、业务表零写、原fixture哈希不变、运行中app哈希一致。仅程序修后成绩，不移用为新SHA真实Live成绩。

764e6f6产品源码全量1036项／160FAIL／32ERROR；新增失败为旧同字段OR必须UNKNOWN断言，保留原断言并新增正控制实核已归因筛选数不冒称全月，通过。新增Approval挂载错误保留，一次隔离复核通过仍未关闭归因。详见 ../evidence-root/D01-OR-FULL-COMPARISON.json 及 d01-or-new-ui-error-isolated.log。本轮无新增Live，旧K01/K02成绩仍仅属于92f708e。

## R5待正式同版验收
当前新切片仅有77根核心、37独立fresh控制、重复展示修复66根相关项及独立窄边界证据（有重叠，不合计成唯一测试数）；实际Textual完整查询→fresh详情→继续修改预览通过属脚本模型程序控制。全量及新陌生Live尚待独立冻结，人工链仍未验，不能宣称R4原失败已翻分。C5仅已封题/未建正式fixture/无模型授权，实际可能触发预算或人工依赖NOT_RUN。最新可交付已审查包仍R4 f31fc88且整体不通过；下一包需新SHA重新核。

## R4冻结前判断（15:45）
当前新工程程序切片通过，但同版完整全量/真实模型/真人尚未签收；不建议晋级main。R4完整SHA和文件清单由V3-FREEZE-R4.json记录。R3只有D02/D04完整通过，D01/D07/D08存在真实交付/语义失败；三项修改预览未做人验，四个依赖轮次NOT_RUN。故六业务B1/B2/B6仍有明确缺口，B3提交链、B4新聊天真实记忆、B5提交后故障恢复仍未完成。八项能力入口虽有程序证据，完整同版Live与真人边界仍分别PARTIAL/NOT_TESTED。包完整不等于业务通过。

新展示目标切片经独立审查新增反例后已收窄，45项来源/预览回归通过；一次最终引用补正新7项及根集成检查通过，原无效父引用仍被原gate拒。自动审批拒绝的多行展示扩展未实施，仅采用完整未分页单票及禁止旧引用的替代。所有这些是离线程序控制，未改R3原分；当前R4没有首执成绩。

## 最新R3状态（2431b6f；15:04）

15:17首执收束：C2共10/14用户回合、16次新增付费物理请求，无重跑覆盖。D02/D04完整通过；D01不完整交付；D07业务未完成；D08第二轮INTENT/TOOL错误被RUNTIME安全阻断但结果与交付仍不完整。D03/D05/D06仅各首轮正确预览五维全2，真人提交链NOT_TESTED；D05/D06其余4轮依赖真人，明确NOT_RUN，不因用户暂无法查看判产品FAIL。全部观察到的业务表零写、审计0。正式独立矩阵分别为../v3-c2-acceptance/R3-HEADLESS-FIRST-REVIEW.public.json、R3-VISIBLE-FIRST-REVIEW.public.json。完整四对尚不能签收。

后续工程切片不改原2431分数：日期prefix归因efc18e8使公开D01四条SQL全部UNKNOWN→VERIFIED，真实行集与独立fixture一致；但原最后answer把多列result当subtract父事实，真实select仍拒绝，不能宣布D01完整修好。证据../v3-c2-acceptance/regression-D01-R3/CURRENT-GATE-REPLAY-1795158925168498000/ACTUAL-GATE-REPLAY.public.json。根相关37项程序回归36PASS、1quoted票号既有FAIL，A正在修；日期专项14PASS。新修复没有真实模型通过证据。

同版全量951项/754通过/168FAIL/29ERROR，套件FAILED；新增失败14条逐项分析中，原断言未放宽。C2 v2正式首执正在执行，尚无完整四对评分，不能迁移5b结果。D03已到正式工作台逐张预览，15:04独立fresh读取仍原用途和备注、审计0，处于待真人批准或拒绝；尚不能签收提交/唯一审计/重启回读链。D01/D02采集已完成不等于业务通过。

R3交付包280源码hash与冻结完全一致，仅包装完整性通过（V3-R3-PACKAGE-ROOT-REVIEW.json）。下面R2及更早记录均为历史同SHA结果，不覆盖本节，也不拼接为R3通过。

当前重冻候选以../evidence-root/V3-FREEZE-R2.json为准。原718、阶段1819的程序与Live证据仅属各自SHA；新的正式Live与真人链尚NOT_TESTED，不建议晋级。

| 业务 | 当前同版状态 | 首个缺口 |
|---|---|---|
| B1 查询正确完整 | PARTIAL_PROGRAM | 金额/COUNT公开失败及完整交付缺新Live |
| B2 自然多轮 | PARTIAL_PROGRAM | 陌生改口/否定/取消/切话题整体未验 |
| B3 正式写入 | PARTIAL_PROGRAM | 正常工作台真人批准/唯一审计/重启回读未验 |
| B4 长期记忆 | PARTIAL_PROGRAM | 新聊天真实自然语言恢复与偏好未验 |
| B5 异常恢复 | PARTIAL_PROGRAM | 同版真人写后回执丢失与核实未验 |
| B6 最终状态可理解 | PARTIAL_PROGRAM | 正文/工具/工作台同版观察未验 |

旧7a1fdf4原计划4对8场必须保留：P1 FAIL（指标偏离+范围阻断）；P2 NOT_TESTED；P3 INVALID（采集器）；P4 FAIL（输出截断、末轮语义未观测）。成对通过0/4，不反复刷原题。详../C-STAGE-RESULT.md。V3新四对待C封存，正式首执均NOT_TESTED；新成绩另列不覆盖旧分。

| 复赛能力 | 已有实现/真实入口 | 证据类型与缺口 |
|---|---|---|
|01 助手|assistant_cli/F5/双层ACL|程序已有；同版Live待验|
|02 Tool/Skill|受控登记/共享版本/启停|程序已有；双助手Live待验|
|03 多轮|pending/改口/暂停/取消|程序已有；陌生Live/真人待验|
|04 记忆|持久任务/偏好/新聊天恢复|跨进程程序已有；自然续办待验|
|05 知识|资料原段/规则发布换版/日期|程序CLI已有；真实模型更新链待验|
|06 文件|Word不可变版本/去重/原段|程序已有；Excel原行/PDF页码缺口待核|
|07 上下文|裁剪/可信草稿/历史恢复|程序已有；裁剪后Live待验|
|08 恢复|请求核账/幂等/CAS/截断状态|程序已有；同版真人重启待验|

真实可见批准、批准后提交、审计及重启回读：NOT_TESTED。正式库未修改，未合main、未推送。只有C出具冻结候选正式成绩。

## V3阶段冻结1819（不是完成声明）

1819a5bb6cd2205ba72e95b3594cb5a876b6b8ba独立源码与完整日志：../frozen-v3-1819a5b、../evidence-root/v3-frozen-1819a5b-full.log；901项537.674秒，686通过、182FAIL、33ERROR。原718的215条失败名称集合完全相同，不能据此将其全部关闭。6659另一次unknown_cancel的首次断言失败保留；1819原样通过，B独立7次低量对照未复现，归因仍未关闭。

新增程序能力：日期分组/企业年月标量、恢复修订号、Excel原行及PDF页码/不可变版本、坏XML/伪小dimension/UTF16 DTD拒绝、预算已知usage保留；不是Live/真人分数。当前旧失败中已证实普通只读分发创建缺失DB，待新候选修复。

正常console零API可见性已由用户回答“能看到工作台”证实；真人批准/实际提交/审计/批准后重启仍NOT_TESTED。C全新四对8场仍全部NOT_TESTED（收费hold；不是INVALID首执）。采集器synthetic自测错误与重试独立保存，未触碰原题成绩。原7a四对评分完全不改。


重冻前只读修复：普通配置读取创建缺失DB的真实缺陷已修，根10项定向通过（包括原test_empty_and_missing_database不变断言、缺失路径不创建、legacy无DDL、F5真实程序入口）；新冻结仍须独立全量。源于旧接口替身的query_continuity两子例已经精确归因，不外推其他失败。

## 5b84同版正式首执（已完成，FAIL）

原计划四对8场11轮全部首执，整场0/8、成对0/4；C03/C05普通console，其他headless。P1 FAIL，P2 FAIL，P3端到端FAIL且独立pending生命周期NOT_TESTED（产品未建立有效前态），P4 FAIL。首偏离C01 TOOL，其余7场RUNTIME；C06后轮另有INTENT/TOOL错误被来源门禁挡住，不能将其计为自然语言成功。所有业务表零写，无预算/环境故障；输出截断未在此套观察到，不外推P4已全面解决。正式报告../v3-c-acceptance/R2-ACCEPTANCE-RESULT.public.json；仅C03已公开供回归，原首执hash和分数不变。

六项业务均仍不能同版签收：B1没有完整查询交付；B2上游来源阻断多轮前态；B3未到真人预览，批准/审计/重启未测；B4长期记忆本套未验；B5故障恢复本套未验；B6正确模型动作/追问未正确交付。八项已有程序实现/入口仍分别保持PARTIAL，不用此套FAIL抹掉旧程序证据，也不把程序证据当Live通过。

预算新12请求/114636tokens/CNY0.094341峰价保守上界，原账合25/249911/CNY0.228819；余39/450089/CNY1.971181。42元历史UNKNOWN，不当零。真人操作仍NOT_TESTED；main未合，未推送，不建议晋级。下一轮C2支持范围v2在零模型首执前独立修正规格并重封，旧v1保持NOT_TESTED；原5b四对不重抽或改分。

R3冻结前新旧核心95项程序检查通过（44.094秒）；其原安全断言与事实口径不放宽。旧controlled_read_scope“Context必须为空”和旧未登记单字简称sidecar许可断言有明确契约迁移边界，原测试不改，最终全量仍要逐项报告。R3尚无同版Live/真人分数，不能移用5b或任何其他SHA成绩。
