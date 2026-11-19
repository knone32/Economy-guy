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
- 本轮环境、测试、修改、冻结和Live证据：主会话按阶段追加；新产物保存 model-first-20261119/evidence/，不混改历史目录。
