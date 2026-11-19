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
- 本轮环境、测试、修改、冻结和Live证据：主会话按阶段追加；新产物保存 model-first-20261119/evidence/，不混改历史目录。
