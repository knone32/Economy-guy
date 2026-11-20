# V3当前状态（总控权威；上海2026-11-20）

## D01 当前判定（92f708e 后续修复中）

证明能力与业务范围分类已分开：UNKNOWN归因返回SQL_EVIDENCE_UNSUPPORTED（不返回data），界面标题“统计核验能力受限”；已VERIFIED但实际卖方集合不一致仍SCOPE_MISMATCH。36项定向通过，B在原K01隔离fixture的两条实际Textual程序对照核实不同标题／末答、均无统计数值。证据总项目根 k01-proof-classification/run-1795168283439703700；外部harness旧文案断言false-negative原始记录保留，仅原raw另行复核，未重跑。全量检查已启动，结果另记；非Live，旧K分不改。

分类修复7914d9a全量已完成：1038项／160FAIL／31ERROR／421.907秒，无新增失败／错误标题；旧Approval挂载错误本次缺席不当已修。日志 ../evidence-root/seller-evidence-classification-full.log，对照 SELLER-CLASSIFICATION-FULL-COMPARISON.json。本轮实际API为0，统一预算仍49请求／511727tokens／445084成本微元。

语义复核隔离实现尚未整合：A报21项新程序控制通过；C2独立fresh实核输入隔离、模型槽、无槽停、工具ID配对，但发现两个仍能实际dispatch的缺陷：no_seller要求下SUM(CASE...)投影内seller条件漏检；重复decision/confidence JSON字段last-wins误接受。反例 v3-c2-acceptance/semantic-stage-interim-1795168701373588200 保留，A修复中，不能当就绪或语义证明。

非SQL工具覆盖审查：静态路径确认get_finance_summary/list_invoices未核seller要求；唯一必要当前程序对照被NO_APPLICABLE_RULE提前阻断，未到目标接受点，无卡片。不得称动态已复现或seller保护通过。总项目根 d01-nonsql-seller-audit/REVIEW.md，未补规则／重排重跑；这仍是范围覆盖限制，不混作K02第二首错。

实际分支 sprint/2026-11-20-contract-followup，保留27b024d之后提交。92f708e公开A/B/C程序对照通过：扩大查询拒绝；精确560元及分期金额张数可交付；明确模糊合计8560元仍可交付。该SHA全量1033项／159FAIL／31ERROR，非全绿。

独立同版DeepSeek K01/K02首执均FAIL，原分不可改。K01合法完整身份SQL因月份OR谓词归因UNKNOWN而误拒；K02模型把简称的全部发票解释成跨销售方contains，真实卡片展示合计且未追问。故D01尚未修复完成，不晋级main。公开证据 ../v3-c5-sealed/k01-k02-sealed/public/K-FIRST-92f708e-REPORT.json。

当前离线修复K01归因已提交764e6f6：同一目标的等值／IN析取按等价IN归因，混合目标、变换、AND分支继续UNKNOWN；35项定向通过。B按原用户、原SQL进行实际Textual脚本模型回归通过：卡片6895元／3张、8300元／2张；末答以六月减五月的scalar算式显示1405元、-1张（没有另写“增加／减少”字样）。证据位于总项目根 k01-or-repair/run-1795167617925099800，标AFTER_DISCLOSURE_SCRIPTED_NONLIVE；原首FAIL不改，全量回归另记。K02需要独立于SQL生成的用户业务关系约束，禁止用词表补丁或一律禁LIKE掩盖。

统一预算累计49请求／511727tokens／445084成本微元（峰价记账上界，非账单）；未知用量false，原46条前缀保持，原总限64／700000／2.20元不增加。真人批准／提交／重启回读仍未验；D07及整行引用相减另记。

OR修复全量：1036项／160FAIL／32ERROR／422.753秒（../evidence-root/d01-or-current-full.log）。比92f新增一条旧UNKNOWN断言FAIL：invoice_no两个等值OR现可形成IN归因；旧断言保留不改，新增真实卡片／末答正控制通过，核实筛选数不会冒称整月总数。新增Approval挂载NoMatches错误一次隔离复核通过，但原ERROR保留、归因未关闭；其余原失败仍在。此后仅补1条正控制测试与文档，不重复整套为追绿。

K02独立语义review在 d01-semantic-review-work 隔离开发，尚未集成。会覆盖自报contains和遗漏seller条件，不把生成SQL当用户要求；非SQL汇总／列表附加条件的保护仍需独立核实。N01/N02已新封存，仅零API设计，等待新候选与同账授权；不替换旧K成绩。

## R5冻结前（上海11月20日下午）

- 新程序已集成至efe39a5：9d4948e仅按本轮明确企业的真实目录唯一casefold补读取来源；5004578默认TRIM真实业务文本列，保留transform至cohort；a29caf9只补能力边界说明；b820ab7/27b024d把本轮完整、未分页、哈希一致的SQL原列唯一身份接到call-local get_invoice；efe39a5仅native合并同display下完全同jointkey/企业年月的单键等价来源，保留原anchors/global默认/ordinal。不同对象及多key来源仍拒。
- 根77核心程序通过，独立C2自造fresh37控制通过。随后发现SQL+freshget同对象双anchor被误当歧义，原失败实录保留；窄修后根66相关项含实际Textual完整查询→fresh详情→双展示→下一轮预览通过，C2另复核同对象正例/不同对象及9拒绝边界通过。数字有重叠不相加，不当Live/人验。
- R5最终SHA/独立目录/完整全量成绩以V3-FREEZE-R5.json及同版日志为准，当前没有新Live通过分。R4 f31fc88全量与两项公开回归失败均保持原分。账本仍46/476892/399792微元上界，后续无新API。
- 新陌生验收准备：C3 E版21回合超当前请求余量，零执行前保留E并另封F预算版；F在零执行适配审查发现不支持的自由执行建议规则与Word物理页前提，保持HOLD、不是产品FAIL。C4误读受限历史章节而主动INDEPENDENCE_HOLD，未造题或执行。当前有效准备为全新C5 J01–J08，12自然消息；仅按已物理截取的业务契约/实际公共能力设计，未见旧题/实现，SEAL hash6e514658d327da9ceeb2cc10ca78a49ff0ca7b84d4f18b440981aee0b97500b0。根仅读public，私题不公开。正式lab构建/模型/预算均待绑定，无外发授权或调用配额，不能保证余18次足够。

## 16:00阶段结果（实际初核16:00:52，后补独立评分）

详STAGE-20261120-1600.md。不晋级：R4 f31fc88全量992/160FAIL31ERROR；公开后D01/D07各一次均未完成，原R3分不变。用户具体外发授权后才获正常复审并付费，共新增5请求；原账46/476892/399792微元上界，全部complete，无unknown。D01首错TRIM文本SQL来源UNKNOWN，D07整月清单未落实筛选、后轮安全拒绝。继续离线通用来源/工具边界修复。

根开发HEAD已加入只读唯一目录casefold为9d4948e，55核心检查PASS；它不是R4冻结，不迁移R4成绩。R4包根核286/286一致。两个无批准的已完D07进程已按身份核对后结束，关闭前fresh终态独立留证；D03/D05/D06三个待真人批准窗保留。用户报告没看到预览或内容不一致，人工链未验，CUA观察环境故障不能证明视觉状态。C3仅离线新四对封题，无API/外发授权。

## 最新快照：15:45，R4待同版全量/公开回归

- 根集成至462a73d，新增提交包括efc18e8严格SQL日期prefix归因、656448f已有可信年复用、abd23fd当前不可读/未知对象否决、a52aa8f quoted只读恢复、45d3bad公司身份与金融表解耦、9ba36e7最终引用一次无工具补正、7b92fb4同轮明确合法目标不被其他提及误拒、462a73d实际唯一展示对象来源。
- R4独立目录/最终完整SHA以V3-FREEZE-R4.json为准。R3 2431成绩完全不变；不能把新程序修复迁移成旧Live通过。52核心、43后扩45来源/预览、31集成安全、25冻结前核心检查分别通过，均程序证据，不是相加后的唯一测试数。
- C2已独立零API核原D01四条SQL归因变VERIFIED但原整行subtract仍拒；原D07可选read_scope首阻断修复。独立审查发现两类旧展示对象错误补回后，根要求模型明确联合key选择且当前原话冲突优先；复核两个原反例均WAITING_USER无plan，D07 full-key正例可到正确预览。无数据/混合不支持SQL引用退休也通过。公开审查目录分别display-origin-review-1795160413296182100（原失败）、1795160527368366800（修复后），reference-retirement-review-1795160626689172000。
- 自动审批曾拒绝把SQL展示引用扩为多行，理由可能扩大写入目标；该扩展未实施。当前仅完整未分页单行，非唯一/截断/空结果及混合不支持结果会阻止旧引用，沿现有owner/fresh read/ACL/CAS/真人批准链，不新建提交通道。
- 当前仍无真人批准。D03/D05/D06为R3隔离虚构库，保活待确认，不代点、不关其批准窗口；D07非批准窗口已完成采集且无后台模型请求。用户明确暂不能查看。正式库未改、main未合、未推送。
- 账本仍41/421937/360821微元上界；本阶段后续全部模型仍须同账新SHA AUTH。已封题未公开D02/D04/D08保持封存。下一步同版全量、新SHA公开回归；B小写票号casefold未完成最终交付验证，明确不混本次冻结。

## 最新快照：15:04，R3正式执行中

15:09补充：用户明确“我现在无法查看和确定”，D03继续待真人，不代点、不因人验暂不可用判产品失败。D05/D06普通工作台首轮也到Approval且自动输入停止，后续依赖人工轮次NOT_RUN；D07两轮采集完成，待独立评分。C2四个headless首执已完：D02/D04五维全2；D01结果交付不完整；D08第二轮未解歧义就尝试动作，被runtime正确拒绝且零写，不能计业务成功。公开报告R3-HEADLESS-FIRST-REVIEW.public.json。

独立离线已证实两类真实回归待修：A定位完整quoted票号缺失turn-local只读proof；B四路对照证实当前用户明确无权限企业被过滤后可沿预选企业错范围交付（未证明越权泄露），按P1阻止晋级。另3条Context/未登记简称相关失败有明确契约迁移证据但原FAIL保留。新修复不回写原2431首执成绩。

- 当前唯一冻结SHA为2431b6fe07fdedc688181788372fccc75806bb56，独立目录../frozen-v3-r3；以下旧段落保留时间顺序，不是当前冻结指针。
- 同版全量951项，754通过、168FAIL、29ERROR，385.819秒；完整结果../evidence-root/V3-2431b6f-FULL-RESULT.json。新增14个失败名称正在由A/B逐项归因，不能以总失败减少宣称安全回归全关。
- C2支持范围v2正式首执进行中，D01/D02采集完成、独立评分待完成；D04/D08待依序首次执行。未将采集完成当业务通过，原5b四对0/4不变。
- D03普通工作台已出现真实逐张修改预览，request cdf5db9eec8b46afb8e1657b4741f2af；SZ-48614用途展会物料→巡检备件，备注不改。15:04独立fresh读取仍旧值、该请求审计0、进程39904存活，准确状态待真人操作。用户可见性答复不构成批准，不代点。D05/D06/D07尚未启动，避免多个确认窗混淆。
- 原账累计29请求/297951tokens/284134微元峰价保守上界；unknown_usage=false。R3内部执行器限61请求/599911tokens/2.20元，根保留3请求/100089tokens，原授权64/700000/2.20不变；全部25条旧前缀保留。授权与分配证据V3-AUTHORIZATION-2431b6f.json、V3-R3-ALLOCATION.json。
- R3交付包根独立核280/280源码hash相同、无运行DB/私有配置/Trace目录，整体包hash bcaab727cfe1432e9c6a7e04387e661a7a2078daa391ffa5a3abf7b68fb67c52；仅完整性通过，非业务验收。审查证据V3-R3-PACKAGE-ROOT-REVIEW.json。
- 15:00左右本地只读命令自动审核超时，未执行；一次重试成功，当前无持续环境阻断。未改正式库，未合main，未推送。

- 权威任务：FINAL-MISSION.md。11月20日16:00阶段门禁仍未到；21日集成、22日晚冻结准备，正式比赛提交时刻待官方通知。
- 唯一集成工作区：business-20261120/contract-followup，sprint/2026-11-20-contract-followup。开工真实HEAD718d812干净；阶段产品曾冻结到1819a5bb6cd2205ba72e95b3594cb5a876b6b8ba；只读修复已集成50d7d0cf1ba281a683cb23e226990d7123f3adae，最终重冻以../evidence-root/V3-FREEZE-R2.json记录为准。E:/beside旧main3111bd7未修改。
- 已建立独立冻结：../frozen-v3-1819a5b，detached完整SHA1819a5bb6cd2205ba72e95b3594cb5a876b6b8ba。C及最终程序均只运行它，根后续文档更新不改变冻结代码。
- 根兼D负责架构/平台/预算/唯一集成；A在../v3-a-query交付日期分组证据和预算守卫；B在../v3-b-runtime交付恢复修订号及失败归因；C在../v3-c-acceptance封题/真值/首执，保留题不向实现者披露。没有并发修改同一工作树，无下级独立额度。
- 新产品切片：严格日期分组SQL→实际企业/年月金额标量；CAS恢复页面显示真实新修订；统一不可变Word/Excel原行/文字PDF页码资料入口，上传不发布/不改账；防Excel伪小范围漏尾行、坏XML、Word UTF16 DTD绕过；预算已知usage不被日志失败覆盖。
- 程序：集成6659定向37通过；预算加入后28（含重复日期/架构）通过。6659全量884项/183FAIL/33ERROR/478.819秒；原215失败均仍在，新出现unknown_cancel回执UNKNOWN_OUTCOME断言1条，B独立诊断中，不能归为旧失败。固定1819全量正在运行，结果以../evidence-root/v3-frozen-1819a5b-full.log为准。
- 旧718的61项、866/182FAIL33ERROR是旧证据，不当1819成绩。原7a首执四对0/4继续保留：P1 FAIL、P2 NOT_TESTED、P3 INVALID、P4截断FAIL。
- C已全新封存4对8场11用户轮、独立虚构SQL真值；官方schema/资料发布适配完成；1819标准Workspace→ModelTransport/Thinking协议绑定零API自测通过。正式Live首执待统一guard胶合后一次执行，按5维独立评分，不重跑覆盖。
- 用户已明确回答“能看到工作台”：../evidence-root/V3-VISIBLE-READY.json为普通console、stdin/stdout TTY、零API，用户可见已确认；不是批准证据。真人批准/提交/审计/重启仍NOT_TESTED，需实际预览后用户亲自操作，禁止代点。
- 真实Profile：E:/beside/finance_agent/config/model_profiles.local.json，hash eed5bed981ab14da3ae9aa50fd6c5e4c8c8b1afc80794f9abc8a07727839bc54；U001 shared-flash/U002 test均官方flash且凭据可用；官方余额GET已核可用。无密钥或账户引用落日志，历史总消费仍UNKNOWN。
- 同一正式账本../c-fresh-private/runtime/LEDGER.json仍13/135275/134478微元；余51/564725/2.065522元，42元历史未知保留。新AUTH在../evidence-root/V3-AUTHORIZATION-1819a5b.json，同预算ID/13条前缀，按V3自主每次输出8192。C01–C08整场cap为8/8/4/4/8/8/4/4，合48，另3次不主动花。
- 环境：默认exec和Node内核启动失败；审批后exec可运行。电脑观察内核重试仍失败；未用UI操作终端或代批准，正常窗口通过非UI启动及用户回答确认。
- 下一步：完成C HTTP胶合零API自测→正常窗口真人预览/非批准场首执→独立5维成绩；复核固定SHA全量及新增失败；继续关闭可证产品阻断，缺真人时转离线交付工作。正式库未改，main未合，未推送。

补充（13:56前）：固定1819全量已结束901项/686通过/182FAIL/33ERROR/537.674秒，失败名称集合与718一致（并不关闭这些失败）。证据V3-1819a5b-FULL-RESULT.json。B进一步从原失败发现普通分发assistant_config.tool_enabled会创建不存在DB，属真实只读职责缺陷，正修；C收费hold，封题均未首执。当前胶合纯问候零API自测已通过（标准Workspace→ModelTransport→根HTTP守卫→SDK，仅原始传输fake），原账仍13条。1819保留阶段冻结，不作为最终晋级候选。

- 重冻决定：普通读取创建缺失DB已最小修复并保留原安全断言，根集成10项定向通过。新的独立目录固定为../frozen-v3-r2，完整SHA由V3-FREEZE-R2.json确认；C需按新SHA重新核入口/夹具/配置后才正式首执，原1819分数不迁移。所有封题尚未发费，历史账本仍13条。

## R2正式业务结果与下一步（14:30前）

- 冻结5b84b6411b3554171f3020ecd54d13e1e7a3a129正式首执完成：4对8场11用户轮，整场通过0/8、四对0/4，套件FAIL。7场首偏离在RUNTIME，C01先TOOL；不能归为模型全部不懂业务。第三对有效pending未由产品建立，孤立生命周期NOT_TESTED、端到端FAIL。公开正式矩阵../v3-c-acceptance/R2-ACCEPTANCE-RESULT.public.json；原始记录hash在该页。
- 同版全量904项/689通过/182FAIL33ERROR/622.179秒；缺失DB原安全断言已关闭，但新增错误上下文先返回ERROR而非DENIED的原SQL负例失败，不能只看总数。证据../evidence-root/V3-5b84b64-FULL-RESULT.json。
- C03公开仅用于回归：真实动态登记简称+任意票号、模型动作/参数正确，程序source_or_identity阻断预览；C08合法普通追问被强制pending内部事件打断。原5b成绩永不重算为通过。
- 新工程已集成：3e14850按实际ACL登记对象/票号来源，唯一票号fresh补账期；f89af8b先核SQL可信workspace再读能力配置；ba2f9ac普通追问不要求模型重复pending事件，真实工作台42项安全定向通过。A继续动态公司/票号只读来源与sidecar引用错企业验证，尚未冻结新版本。
- 新增实耗12请求/114636tokens/94341微元峰价上界；原账累计25请求/249911tokens/0.228819元，余39请求/450089tokens/1.971181元；42元历史总支出未知仍保留。没有预算/环境阻断此套首执。
- 普通C03/C05窗口都没到Approval，真人批准/提交/审计/重启链仍NOT_TESTED；已收尾两个无批准测试进程，原业务表全零写，未碰正式DB。
- 下一轮独立C2由干净上下文封题（D01-D08）。初v1字段status超声明范围且未模型执行，原封存保持NOT_TESTED；在零模型首执前做透明支持范围v2规格修正（非失败重抽）。v2 hash dd2ab314a308a0ede47305fec321cefdcf4aa472b5324c1a3d8c3e1f807eb868，4对8场14用户轮，正式schema/资料规则映射已完成，无API；待新代码冻结和根同账新授权才可执行。
- 待审查5b启动包../v3-delivery-5b84b64/Economy-guy-5b84b64-review-v2.zip，根逐文件核273源码hash与冻结一致，包无运行DB/私有Profile/Trace；不能把包完整性当业务通过。

## R3冻结前统一核心检查

- 通用对象/日期/追问切片及原有来源、权限、取消、草稿、CAS、未知结果、助手、文件/架构核心共95项通过（44.094秒），仅程序证据。
- 根修复Agent二次覆盖：实际登记票号先被旧F前缀框架当成“没票号”剥除，旧日期补充又把票号内部数字当账期；现在早期/分发/当前工作区冲突都用同一对象来源，新增对象只读来源不升级写SOURCES。年度只读亦接受READ_SOURCES，身份/SQL范围/正式写权限不变。
- A只读日期sidecar增加原文跨度掩码，拒绝仅在公司名/票号内部的数字作为账期（含包裹quote），保留独立外部日期与相对期既有契约。
- R3候选与独立目录以../evidence-root/V3-FREEZE-R3.json为准；正式同版全量与C2首执尚待运行。原5b0/8仍FAIL，不从程序验证推自然语言通过。
- 全部实际费用仍原账25请求/249911tokens/228819微元，余39/450089/1.971181。C2 v2四对8场14轮已在独立干净上下文封存并完成真实schema/资料规则映射；无模型首执。测试器默认Python3.15 ABI不匹配已纠正为正式3.12.14，仅synthetic错误保留，不计业务成绩。
