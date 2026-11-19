# 证据索引

所有相对路径以 C:/Users/Lenovo/Documents/ChatGPT/economyguy 为根。原始 Trace/SQLite/密钥不得提交；以下只索引既存证据，历史结果不算新候选当前通过。

- 基线：github-main-publish-20261119，HEAD 8d70924a9871a0f44ec5149fb68ccf7531706546；E:/beside HEAD 3111bd7f84e249590f77482874f98e51561f46a5；两者本轮初查均干净。实际已运行进程加载版本仍未知，新验收用明确启动路径。
- 既存综合调查：baseline-audit-20261119-8d70924/AUDIT-REPORT.md；A/CAPABILITY-MATRIX.json；B/FAILURE-CHAINS.json（若存在以实际路径为准，不重复全面扫描）。
- 公开业务矩阵：BUSINESS-INTENT-MATRIX.md；历史 D02/D03/D05/D08/D10 相关报告由 A 定向定位。
- R1/U06 原始 Live：route1-targeted-repair-20261119/revision3/live/fixed/U06/trace.jsonl，首次date排序偏离，后正确SQL被UNKNOWN证据拒收。
- R2/R3 原脚本控制：route1-targeted-repair-20261119/revision3/guard-controls/；只证明程序错误放行，不是真实NLU成绩。
- 上轮完整结论：reliability-v2-20261119/REPORT.md；A/REPORT.md、A/DIFF-REVIEW.md、B/REPORT.md、C/REPORT.md、C/SCORES.json、C/FINAL-AUDIT.json。
- 上轮候选：4a718b94050136f1ad508e0544fbe25f29b89e7f，公开核心23/23；全量722项163失败27错误；同环境基线714项187失败27错误；不重跑无关全量，失败差异见B/full-diff.json。
- 上轮真实新题：19物理请求/153070 total_tokens；12输入完整6、正确追问/拒绝2、失败4。全部已公开成为回归，不能作本轮隐藏题重复计分。
- 最新公开失败：G1b输出顺序丢失；G3第3轮正确终止答复被抹；G4第1轮冲突范围模型误合并（安全阻断）；G5a引用中的唯一票号被可信来源移除。原始calls/最终回复/数据库见上轮C/live对应目录。
- 上轮真值记录勘误：C/ORACLE-RECORDING-ERRATUM.md、ROOT-LIVE-AUDIT.json；G1原查询记录因字典引用混入银行列，独立SQL值一致，封存原件/成绩未改。本轮须避免共享可变对象污染独立真值记录。
- 本轮契约提交：0589d164223be774d254f83fddbcf25022586f5f；独立分支sprint/2026-11-19-model-first、investigation、execution各用独立worktree。
- 本轮环境：model-first-20261119/evidence/preflight-1795084778148633000/RESULT.json（受审用户上下文，无网络）；Python/依赖、明确源码路径、fixture hash和只读计数均记录；两个既有官方DeepSeek profile的凭据存在仅布尔。常规sandbox对照preflight-1795084731653578100/RESULT.json无法读Vault，非凭据不存在。
- 冻结前业务验收规则：model-first-20261119/evidence/ACCEPTANCE-PROTOCOL.md。尚无具体新目标/问句/答案，C未启动。
- 用户本轮新预算明确授权：model-first-20261119/evidence/AUTHORIZATION.json，24请求/240000 total_tokens/单次输出2048；冻结前0调用。
- 受审只读进程核对：model-first-20261119/evidence/PROCESS-PATH-CHECK.json，未发现运行中的Python进程；不声称旧目录HEAD就是用户正在运行版本。
- 本轮A已完成：model-first-20261119/evidence/A/REPORT.md、findings.json、historical-excerpts.json、current-boundary-probes.json。原D03/D05 SQL窄探针在当前8d709已VERIFIED，R1精确探针UNKNOWN/unverified_query_scope，G5 raw标识符与request_scope引用剔除差异直接复现；只是程序窄验证，不算完整Agent或Live通过。
- 通用验收driver预备：model-first-20261119/acceptance/driver.py，复用旧无题基础设施，计划从冻结后新建frozen-runtime启动；支持封存的隔离夹具可信UI模拟批准/拒绝，不能称真人。尚无具体新题、无新增API。runtime snapshot独立于root持续更新的STATE文档，以保持评分时代码不变。
- B可审阅提交：1f035545fb6e5b1568788149d353eb2b08f22f34，7文件369新增/8删除；只在execution分支，root待复核集成。核心26/26、相关77项与基线差异目前为B报告，精确日志待落盘核实；不是Live证据。
- B与A发现初稿范围扩大：model-first-20261119/evidence/A/diff-scope-baseline.json、diff-scope-candidate.json，及B/read-scope-before.log保留首个FAIL；修复提交c3a3bb79a08504f467453e5b9b12d65d6c771da0，B/core-after-scope-fix.log为27核心通过。尚未整合/冻结/Live，不抹掉初稿失败。
- B相关程序原始证据：model-first-20261119/evidence/B/REPORT.md、results.json、related-final.log、related-baseline.log、related-diff.json。77项候选9fail3error vs基线6fail3error，新增3旧模型原文显示断言仍为失败，未删改旧测试。
- 限定复核完成：evidence/A/DIFF-REVIEW.md，scope从基线拒绝→初稿误放→修正拒绝三份探针保留；独立引用正例1/1。B最终core-after-scope-fix.log 27/27，source-dependent-final.log 6/6。
- 主会话已cherry-pick为4df8369与1e1e977d33310a9e5f278fcbb1a9d080472842a1，finance_agent与B最终无diff；evidence/ROOT-INTEGRATION-CHECKS.log独立33/33，通过架构、证据、来源、只读/写区分、未确认预览/三轮待补等相关检查。不是Live成绩。
- 正式冻结：838569ef36b3d1352a3b9ffb5c696edc1663a704，detached model-first-20261119/frozen-runtime；全部tracked哈希/clean与33程序检查见evidence/CODE-FREEZE.json。此SHA冻结后才新启动sprint_c_acceptance（fork none）。
- 新验收运行与题/真值/分项评分/预算将只记录model-first-20261119/acceptance。root本轮尚不读新题；C不参与开发，仍共享存储所以不是严格隐藏盲测。
- 可运行入口辅助：model-first-20261119/RUN-CANDIDATE.ps1 固定frozen-runtime源码、现有Python/deps、独立manual-runtime虚构数据库，绝不指向正式业务库；仅现有Textual工作台，无新GUI。LAUNCHER-CHECK.json记录CLI help和脚本解析通过，未实际启动手工UI/未发API，不能当真人启动验收。
- C首轮已暂停待终审：acceptance/budget.json 14请求/124400tokens；权限拒绝文案与当前权限/成功读取矛盾触发保守停测。原始题/真值/Trace不改。一个多轮case首轮后stdin EOF，后3轮未测，保留原记录，不择优重跑；末提交case停止未测。最终五项与分类以C报告及root复核为准。
- C首轮已结案：acceptance/REPORT.md、SCORES.json、FAILURES.json、FINAL-VERIFICATION.json、ARTIFACT-MANIFEST.json；8首执4合格4P1、4未测，实际preview/commit均0。所有题现为公开回归，不能再隐藏计分。
- root独立重算与冻结复核：evidence/ROOT-ROUND1-AUDIT.json，oracle全部raw_sql_records新连接重算完全一致，tracked不变，14条账本连续/tokens124400一致。普通sandbox只读连接无权，已在同受审上下文完成；零模型/不改原题与成绩。
- 迭代2限定建议：evidence/A/ITERATION2-REVIEW.md；实际diff复核待A交付；evidence/B/iteration2-core-final.log 30/30、iteration2-dependent.log 7/7为B报告待root集成核实。
- 第二候选验收预登记/全局余额：acceptance-v2/PROTOCOL.md、evidence/ITERATION2-BUDGET-PLAN.json；2类最多4新输入，不增加授权。v2启动case必须PTY（root零API探针isatty=true）；旧14条ledger原样复制前缀，后续15起编号，全冲刺24/240000硬限。
- 迭代2最终代码/审查：B abf5fba+bda30ad；evidence/A/ITERATION2-DIFF.md保留selected-workspace遗漏的首失败及修复、跨来源负例和类型核对；evidence/B/ITERATION2.md、iteration2-results.json，最终31核心+7相关通过，不算语言成绩。
- root集成为ea70577、a598f4228c0bc01e23653f26c6cf7f9659d8f9c9；ROOT-INTEGRATION2-CHECKS.log独立37/37、ROOT-INTEGRATION2-PREVIEW.log1/1，finance_agent与B bda最终无diff。冻结第二runtime后不再改代码。
- 第二/最终冻结代码SHA：0638f8dcd34aa7a2debbcd19a2ed7d1369bb1ebe，model-first-20261119/frozen-runtime-v2；evidence/CODE-FREEZE-v2.json锁tracked哈希/clean/driver/协议/root38检查/旧消耗14与124400。此后C才新任务生成新目标，不读新修复实现。
- C2运行冻结/新题封条：acceptance-v2/FREEZE.json、CHALLENGE-SEAL.json；PTY=True，旧14条ledger前缀和原授权保护已复核。新目标/双连接SQL/表达在新SHA冻结后生成并封存；首新输入新2请求20504tokens，累计16/144904。root评分结束前不读新题或向开发披露。
- 最终验收已结案：acceptance-v2/REPORT.md、SCORES.json、FAILURES.json、FINAL-VERIFICATION.json、ARTIFACT-MANIFEST.json；4输入首执=合理待补1PASS、2P1、1预算部分执行，完整办理0，preview/approve/commit均0。新增7请求70595tokens，全局21/194995；没有覆盖/回写首轮评分。
- root终审：evidence/ROOT-ROUND2-AUDIT.json，所有原始SQL记录独立重算相同、两冻结不变、首轮protected文件不变、全局ledger前14条/连续21条/usage一致。末请求去私有reasoning的最小报文42494，预留lower bound52734>余额45005，补充证明guard拒绝而非已证供应商网络故障；零新增API，原C推断报告不改。
- 最终结果/明日决策：model-first-20261119/RESULT.md、NEXT-DECISION.md；预算封账evidence/BUDGET-CLOSED.json。可运行脚本RUN-FINAL-CANDIDATE.ps1固定frozen-runtime-v2与manual-runtime-v2虚构库，FINAL-LAUNCHER-CHECK.json仅语法/CLI帮助检查，不称真人UI验收；FINAL-CANDIDATE-CODE.patch在原基线apply --check通过。
- 本轮环境、测试、修改、冻结和Live证据：主会话按阶段追加；新产物保存 model-first-20261119/evidence/，不混改历史目录。

## 用户19:47续接的独立第二轮

- 实际恢复核查：integration HEAD30b8efed29184a113e81b193b5b39c29a0dd32e8、frozen-runtime-v2 HEAD0638f8dcd34aa7a2debbcd19a2ed7d1369bb1ebe、main8d70924均干净；读取MISSION/STATE/EVIDENCE、NEXT-DECISION及两轮FAILURES原件。续接契约ed9c385f43e6a74127f9dc6f5832f2a545e93ffa后新建round2-intent与round2-delivery。
- 独立新增预算：evidence-round2/AUTHORIZATION.json，用户明确授权18请求/180000 total_tokens/单次输出2048；旧21/194995不动。本轮证据目录evidence-round2，验收目录round2-acceptance，不覆写旧文件。
- 预登记：round2-acceptance/PROTOCOL.md，3类最多7输入，持续更正/合法预览批准/事务审计/真进程重启回读、取消安全、复杂比较；具体目标与问法只能完整代码冻结后由C生成。
- 0API进程基础设施：evidence-round2/RESTART-INFRASTRUCTURE.json与其指向create/reopen.json，Python PID42360→57472、同chat、draft/pending为空；只测空会话进程/存储，不算实际业务重启或语言能力。driver支持checkpoint+--resume新进程，不重放旧输入；PTY硬检查与模拟审批前独立核草稿保留。
- 第二轮集成：B共享39f45及交付1b0f330、A意图9b7a35已分别cherry-pick，当前e68e12f43ff1c58e19c400f25c37a715dfb7c34f，尚未冻结。evidence-round2/ROOT-JOINT-CORE.log独立43/43仅程序契约；A/REPORT.md和B/REPORT.md含首红、最终相关检查及局限，均API0。
- root集成负例发现字段来源误拼：evidence-round2/ROOT-FIELD-INHERITANCE-BEFORE.json与probe_field_inheritance.py保留pending旧remark+当前purpose新值却产生remark草稿，audit0；A处理兼容桥冲突，修正前不冻结。
- 实际验收runner零API检查：evidence-round2/RESTART-RUNNER-CHECK.json，不同Python PID、同chat、索引[1,2]、无错误；仅基础设施，非真实业务/自然语言验收。原两进程probe及日志均保留。
- 冻结前追加修正：A 0ab51d883b8e0ac4fd98fc9a3ef43551e0ca2e00与87c2ca1baff8f4479ecedac84b11b74d79fb4eb3由root集成为3ddda59/f0d918c；显式pending字段同样不允许跨字段来源拼值，预算收尾不越当前block。A/field-bundle-before/after/final.log、source-budget-before/final.log保留首红及正反结果。B/budget-cross-before.json独立证实原extensions=1缺口；无新问句词表/正则。
- root最终程序61/61：evidence-round2/ROOT-FINAL-CONTRACT.log，20意图状态契约、原核心事实/预算/架构、权限、确认失效、提交回执、未知提交、审计回滚、幂等相关。仍不是Live理解成绩，不将更宽既有错误改为PASS。
- root字段首红独立复验：evidence-round2/ROOT-FIELD-INHERITANCE-AFTER.json及probe_field_inheritance_after.py，错误remark草稿拒绝、invoice_change null、audit0，BEFORE原件未覆盖。此后冻结并由C独立新题，不边评分边修。
- 第二轮正式冻结：完整SHA2430ba08693776512823c8c254995f86defe0c7a，detached frozen-runtime-round2，224 tracked hash及clean见evidence-round2/CODE-FREEZE-round2.json；finance_agent与root61项实际受测f0d918c无diff，仅控制文档变化。runtime/profile/采样/依赖/driver/scaffold锁见round2-acceptance/FREEZE.json。零模型请求冻结，随后才重启C生成新题。
- 本轮C只读冻结元数据和预登记协议，禁止读实现分支/成功答案挑题；共享存储不称严格隐藏盲测。新账本18/180000，旧保护哈希evidence-round2/HISTORICAL-PROTECTION.json。主会话验收结束前不向A/B泄新题。
- 可运行新候选入口RUN-ROUND2-CANDIDATE.ps1固定新runtime与全新manual-runtime-round2虚构库；LAUNCHER-CHECK.json仅语法及代码等价检查，不称人工GUI/模型验收，未启动额外API。
- 首执已结束，C未追加API：新13请求/124751tokens、剩5/55249；一个token_reservation拒绝reserved57125>remaining55249，before_http=true，未产生第14条物理请求。evidence-round2/ROOT-FREEZE-BUDGET-AUDIT.json独立核新账本计数/连续已知成功用量总和、224源码文件hash无变、旧两轮FAILURES与旧ledger/封账hash不变。正式成绩待C封存及root SQLite复核，不以HTTP200推定端到端成功。
- C正式结案并公开为回归：round2-acceptance/REPORT.md、SCORES.json、FAILURES.json、FINAL-VERIFICATION.json、MANIFEST.json（80文件）。6首执=2有限通过、3P1输入、1预算partial；INTENT6/6不代表业务完成，完整链/preview/approve/commit均0。没有基于失败新题改候选或择优复跑。
- root最终零API独立审：evidence-round2/root_final_audit.py、ROOT-FINAL-BUSINESS-AUDIT.json，6个原始SQL记录在3库分别新连接重算一致，各表与final快照一致、业务表与seed相同/audit0、sealed80文件hash全同，ledger连续/官方endpoint/13请求124751tokens一致。原始system确要求pending.scope候选invoice_no，实际两次模型省略；不能误称已符合协议的提案被拒。
- root真实首错区分：两次模型pending信封缺槽是协议失败而非语义误解；后续更正公司来源缺失是级联。正确BETWEEN SQL范围证据UNKNOWN/unsupported_predicate引发更多读取，budget发送前拒绝导致比较交付不完整；没有把原始NO_DATA改答案或把未知最终回复归NLU失败。
- 当前结果/决策：RESULT-round2.md、NEXT-DECISION-round2.md；新独立预算evidence-round2/BUDGET-CLOSED.json封13/124751，剩5/55249不续测，旧21/194995不动。安全没有本轮已知P0，但真实完整修改门禁未过，不晋级为明日扩展基线，不自动合main/推送/发布。
- 过拟合窄审：evidence-round2/ROOT-OVERFIT-REVIEW.json仅检查本轮production diff与来源/事实契约，未见固定票号/题名/金额/月/新正则问句补丁；受控purpose/remark字段枚举为保守来源冲突，不能宣称已移除所有旧语言启发式或证明泛化提升。

## 第三轮最短更正→预览

- 用户明确缩小范围，独立授权12请求/160000 total_tokens/maxoutput2048；round3-acceptance/AUTHORIZATION.json及PROTOCOL.md先登记两场各最多2输入，首场失败即停，成功才第二场；严禁approve/commit，不续旧两封账。
- root精确复核第二轮原始Trace：R2P.1 pending.transition_rejected.reason=explicit_invoice_candidates_required，R2P.2企业AMBIGUOUS为此前pending失败级联。明确企业存在首轮原话，不增信任自由模型company_id的旁路。
- A最小提交406f7ccb595519f0a8630662633987c8a7ddcf42已集成ae6148f48b6009e1273e3b8beac7d1d9eb6e39f8。生产2文件3增4删，允许invoice未知pending保留唯一可信企业/账期及原字段新值，不自动继承全部mentions/read集合；实际后轮显式目标+fresh selection/权限/field/value/确认保护不变。
- 程序证据evidence-round3/A/{REPORT.md,results.json,before.log,after.log,related.log,baseline-legacy.log}；4新正反例真实业务API预览取消后不写、无目标/错企业/错字段/无源值拒。相关47/48有1旧echo失败，冻结2430同复现，不改答案不隐藏。root独立ROOT-CONTRACT.log 30/30（4新+20既有意图+4权限+2架构），不是NLU分。
- 第三轮冻结ae6148f48b6009e1273e3b8beac7d1d9eb6e39f8，frozen-runtime-round3；round3-acceptance/FREEZE.json固定正式入口/profile/依赖/fixture/driver/source hashes，零HTTP冻结后才C生成新目标/SQLite真值/表达，非严格盲测。新driver副本仅限reject并修list/tuple比较；原driver/原失败/旧账不改。
- 第三轮首错门禁已执行：round3-acceptance/REPORT.md、SCORES.json、FAILURES.json、FINAL-VERIFICATION.json、MANIFEST.json共39文件封存；仅R3A.1首执P1（model最终省missing_fields/pending/pending_change→runtime ANSWERED/pending=null→UI只事实），其余3输入UNTESTED，正式preview/approve/commit0，无补题/复跑/代码修改。
- 新账本evidence-round3/BUDGET-CLOSED.json独立封2请求19136tokens，剩10/140864不续用，无预算阻断；旧两封账不变。root终审ROOT-FINAL-BUSINESS-AUDIT.json重新独立SQL/各表快照/seed/audit0/官方endpoint/连续用量相同，C39文件封条无变。评分条目4含3未测，root初稿字段误名scored_inputs原件initial保留，最终明确executed1/untested3，不改C评分。
- ROOT-FREEZE-BUDGET-AUDIT.json在真实Windows用户上下文完整只读验证冻结源码及旧round2 80文件哈希无变；sandbox读旧DB权限不足的初稿incomplete保留，未将其作为通过依据。无新增API。
- 第三轮结果与最新决策RESULT-round3.md、NEXT-DECISION-round3.md：当前契约仍依赖模型显式给待补生命周期信号，本次完全省略且未触发补正，候选列表冗余修复不足以保证完整路径。按用户停止规则停止该候选晋级，不继续确认/提交/恢复或加新机制。全部题结案后转公开回归，旧记录不覆盖。

## 第四阶段：一次业务动作接口实验

- 只读诊断：evidence-stage4/DIAGNOSIS-DECISION.md六问，REAL-TRACE-EXTRACT.json保留R3A实际请求行5/18、工具、完整可见输出行8/21、ANSWERED行22；ACTUAL-SCHEMA-PROMPT-EVIDENCE.json在两次真实请求中核19工具及5行相关SYSTEM指示。私有reasoning原记录已隐藏，不能声称内部推理全可见。
- 结论：原tool必须完整selection+字段/新值/模式/排除列表，没有缺目标业务动作入口；SYSTEM却分配最终JSON生命周期责任，部分语义识别与动作协议遗漏分开。未声明事件且窄门未触发可ANSWERED，最终事实交付抹掉待补说明。不是继续放松来源可解。
- 唯一设计：现有propose action=request允许已知不完整业务槽，服务端绑定actor/book/request_id、来源/权限、pending/missing_fields并直接WAITING_USER，不再同轮最终JSON造pending。anyOf与实参validator保留默认完整提案5必需；request不能传selection/mode/write_scope/身份/确认/内部ID。完整提案仍fresh读和原权限/确认/事务底座，不推readset写目标。
- 实施8dbfb9108f6d77d3b9f171c86f20c494c01a9933已root集成5253deea95fbc8090fb4253d6f5ffce8318f7fb3。A/REPORT.md、results.json、public-baseline-before/source-boundary-before及after日志保留原失败及新helper两source首红（查询字段串值、未选两票任选ID），以已有invoice_value_source/literal_single_invoice_edit收紧，无新词表/正则。root ROOT-CONTRACT.log20/20；A相关33/33+cancel/stale3/3，不计NLU。
- A只读原冻结复现时曾在旧freeze目录误建自己的runner/空证据目录，已移至外部证据，未修改任何旧原文件；最终需核旧冻结clean/hash，不能把移动证据隐去。报告保留操作说明。
- 新预算用户独立授权stage4-acceptance/AUTHORIZATION.json：8请求/120000tokens/输出2048，当前冻结时0。PROTOCOL.md单场最多2输入、首失败即停、不approve/commit/第五轮，旧21/194995、13/124751、2/19136封账不续花。
- 冻结5253deea95fbc8090fb4253d6f5ffce8318f7fb3至frozen-runtime-stage4，stage4-acceptance/FREEZE.json锁实际source/工具入口/profile/依赖/driver/scaffold/fixture。冻结后才C独立目标→SQLite→新表达封存；不读实现选题，非严格隐藏盲测。源码评分期间不变。
- 第四阶段正式结案：stage4-acceptance/REPORT.md、SCORES.json、FAILURES.json、ACTUAL-MODEL-INPUTS/ACTUAL-PROPOSE-TOOL-DEFINITIONS/ACTUAL-SCHEMA-ARGUMENT-AUDIT、FINAL-VERIFICATION/MANIFEST共46文件封存。首输入真实request→合法pending PASS，第二输入propose多company_id不符实际anyOf，未到正式preview，场景0/1、输入1/2；无修改参数/代填/重放/第五轮。
- root独立终审evidence-stage4/ROOT-FINAL-BUSINESS-AUDIT.json跨新连接SQL/快照/seed同、audit0、46封条无变、3连续官方请求31644tokens一致。ROOT-INTERFACE-AUDIT.json直接从原trace核唯一extra company_id/无缺required、fresh selection为本轮真实get_invoice返回；新5253与旧ae源哈希及旧round3 39文件相同。旧全保护同时见C FINAL-VERIFICATION。
- 新独立预算evidence-stage4/BUDGET-CLOSED.json封3/31644，剩5/88356不续用，无guard/未知usage，旧三账不动。C辅助评分写盘路径笔误HARNESS-NOTES透明记录，独立判断及DB核验先于continue，未重放或改标准。
- 当前结果与工程决策RESULT-stage4.md、NEXT-DECISION-stage4.md：高层动作入口局部有效，但当前双模式接口仍参数协议失败；停止候选晋级。证据不支持大规模改核心，先定清业务参数与执行引用责任；不自动第五轮相同实验或写入链，不合main/推送。

## 架构职责纠偏（用户明确新授权）

- 决策ARCHITECTURE-DECISION.md逐项A/B比较和四类首错，不推断整架构错误。主会话直接business-ownership实施；A仅独立窄审来源/权限，C冻结后独立验收，不并行重复扫仓。
- 实施97d6ccef279eab2e817df6ba2cf73f8c88a15829已集成c9b8948398e4e194e0e02bf226ac3d8158db43f6；新增一致单票change_invoice业务入口，Runtime拥有pending/来源继承/fresh证据/内部proof并调用原plan/预览底座。旧批量规则完整合同保留、S4 request分支退休，不静默删多余字段。runtime读取独立trace不是modelcall。
- 程序evidence-business/final-checks.log35/35；旧request线协议retired-wire-contract.log7项2fail2error保留。首导入NameError与preview测试callback参数错误均保留first-contract/core-after-import日志，修正后实际原preview函数取消无写；若干相对日志路径错未执行测试，不计通过。所有脚本测试不计NLU。
- A窄审发现重复trusted known仍要求当前原话重证，机制修为状态来源继承（包含空值），当前字段/明确字面冲突拒；不匹配新请求源的自由企业/票/字段新值仍拒。现actor/book、fresh日期、实际ACL、原正式preview/确认链未见直接绕过；不宣称任意NL语义已证。
- 冻结frozen-runtime-business c9b8948，business-acceptance/FREEZE.json锁正式source/依赖/profile/fixture/driver，随后才C两新目标→独立SQLite→表达seal。新独立授权12/180000/max2048，旧四账全关不动；C只reject，实际人工确认方可后续写审计回读。
- C阶段business-acceptance/REPORT/SCORES/FAILURES/FINAL-VERIFICATION/MANIFEST64文件封存，首场正式preview通过，第二场模型/Runtime/Prepare正确但实际UI Approval.on_mount #cancel NoMatches（产品或runner根因未定），不计第二preview成功，不重跑。root evidence-business/ROOT-C-AUDIT.json跨新连接SQL/DB/snapshot/seed一致、业务/audit无写、4官方连续请求32848tokens与64封条相同；4输入实际均执行，不将STATE未测当输入未测。
- UI-SCHEDULING-PROBE.json/log零模型调度探针未复现，不能据此宣称仅验收器bug。未改产品或C driver/分数。用户后续明确授权“继续人工预览核验”，与旧C挑战分开记。
- business-human/授权+SESSION/LAUNCH固定同c9源、官方虚构新账簿、C4/32848不可变预算前缀，同本轮12/180000总限。manual_workbench.py真正app.run，无Pilot/自动approve；原Approval挂载后仅只读记录body/draft。PID30188窗口已启动，输入/登录/确认由用户本人（computer-use技能禁止自动终端/认证已告知）。原C封条/账本不修改。
- 人工启动更正：无可见窗口/无登录/无新增API的自有空闲PID30188已停止，SESSION-attempt1与before-attempt1及IDLE-RESTART-ALLOWED保留；START-HERE.cmd供用户真实桌面直接双击。人工当前仍0新增，未发生preview/确认/提交。RESULT-business.md与NEXT-DECISION-business.md、BUDGET-STATE.json记录等待真人状态，开放的是同一次12/180000授权，不关闭后又重置。
