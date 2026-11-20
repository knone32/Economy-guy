# 验收（V3；不同SHA不拼接）

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
