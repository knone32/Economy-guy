# 当前状态（仅主会话更新）

- 阶段：4终审，C已按可信错误事实停止本轮评分，正在封存DB/权限/原始文案证据。候选不改、不恢复原评分。
- 当前唯一冻结候选SHA：838569ef36b3d1352a3b9ffb5c696edc1663a704，detached frozen-runtime工作树，clean，完整tracked文件哈希在evidence/CODE-FREEZE.json。业务内容等同已独立验证的1e1e977；相差仅本轮状态文档。集成分支sprint/2026-11-19-model-first可继续提交STATE/EVIDENCE，不得修改冻结快照。当前控制HEAD用git rev-parse HEAD查，不与冻结验收SHA混淆。
- 工作区：model-first-20261119/integration；用户原发布工作区与上一轮候选均干净，保持不变。
- 已确认目录差异：github-main-publish-20261119 为8d70924；E:/beside 为3111bd7；上轮candidate为4a718b9。未将目录HEAD当作用户正在运行的进程版本；新验收只从明确冻结的冲刺工作区启动。
- 可复用环境已本轮验证：Python C:/Users/Lenovo/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe，3.12.14；PYTHONPATH 指向 reliability-v2-20261119/runtime-deps，依赖openai1.109.1/httpx0.28.1/textual1.0.0/openpyxl3.1.5/sqlglot30.33.0。虚构SQLite可只读，40票/48流水/0发票审计。受审用户上下文shared-flash/U001、test/U002可用，常规sandbox无法读WindowsVault；不需用户重输密钥。
- 已完成A：evidence/A/REPORT.md、findings.json及原始摘录/窄探针；生产代码未改、工作树干净、零API。D03/D05精确SQL在当前已VERIFIED，R1仍UNKNOWN，G5只读源误拒已复现；D02属模型擅加条件；D08/D10留门控/日期来源风险，不再扩审计。
- B候选已集成：c3a3bb79a08504f467453e5b9b12d65d6c771da0（父1f035545fb6e5b1568788149d353eb2b08f22f34）对应集成4df8369、1e1e977；finance_agent内容与B最终相同。新事实引用模块/有序事实回执、只读引用票号、typed stop、原生票号排序。未推送或合main，尚无新Live能力结论。
- 复核中阻断与修复：1f原稿把引用票号覆盖既有明确目标，A同输入wrong-target探针证实基线SCOPE_MISMATCH、初稿SUCCESS。c3改成仅proof和scope均缺票号时补引用；先红后绿日志保留，A正做最终复核，不隐藏初稿回归。
- 程序验证已完成：B最终核心27/27、来源交叉小子集6/6；A原scope负例修正后SCOPE_MISMATCH、fresh引用正例1/1。root在集成1e1独立33/33（核心/架构/SQL证据/引用安全/三轮待补），diff --check通过、工作树干净。相关旧77项初稿9fail3error vs基线6fail3error，新增3旧正文echo断言仍保留。未跑无目的全量。
- C首轮状态（待最终报告核实）：14请求/124400 total_tokens，8输入首执；另3轮因非PTY stdin EOF未执行，末1独立提交case因停止未测。不重跑/不补题，EOF不算模型失败或成功。程序scope阻断和交付缺项已保留。
- 当前停止原因：可信拒绝文案与独立当前权限/本轮成功读取矛盾；C保守按错误事实触发停测，尚未披露题面。没有报告越权/未确认写入或虚报保存；root待正式报告后核首节点与严重性，不把文案错误夸成权限绕过。
- 用户全冲刺授权24物理请求/240000 total_tokens/每次输出2048；已知消耗14/124400，余额最多10请求/115600tokens，未知usage必须停。原评分不延长、不补测，不自动刷新预算；任何新迭代需先结束原评分、公开旧题、最小修复、重新冻结与新题，仍受全局剩余额度约束。
- 已知阻断：上轮通用正文抑制导致正确终止答复/展示顺序回退；引用票号来源拒绝、冲突范围模型误选、R1 SQL证据不闭合。不得整包盲合并上轮候选。
- 初步方案：B实现有序工具事实引用/真实receipt契约，模型选工具、事实和次序，Harness绑定范围/标签/数值；A核实只读引用来源应与修改授权区分。不是最终实现或通过结论，完成后先定向验证与root审核。
- 下一步：等待C正式终审结束/可披露通知，root独立核权限事实与冻结/真值/账本；先按MISSION停止门禁判断是否是有限可修机制，或记录明日阻断。此时不改代码，不向开发披露新题，不执行原末case。
- 实际进程核查：受审只读枚举未发现python.exe/pythonw.exe运行进程，未发现可确认的既存Python工作台加载路径；今后测试明确从冲刺integration/finance_agent启动，不沿用旧目录。
- 禁止事项：评分中不改候选代码；不做GUI/文件导入；不改正式账簿；不推送main。C新题评分结束后才公开，自动转回归；失败不得本轮边看题边修。
