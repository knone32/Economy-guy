# 当前状态（仅主会话更新）

- 阶段：1，A/B 已并行调查/开发，零新增模型请求。
- 集成分支：sprint/2026-11-19-model-first；当前集成提交：0589d164223be774d254f83fddbcf25022586f5f（仅契约）；业务代码仍为8d70924a9871a0f44ec5149fb68ccf7531706546。
- 工作区：model-first-20261119/integration；用户原发布工作区与上一轮候选均干净，保持不变。
- 已确认目录差异：github-main-publish-20261119 为8d70924；E:/beside 为3111bd7；上轮candidate为4a718b9。未将目录HEAD当作用户正在运行的进程版本；新验收只从明确冻结的冲刺工作区启动。
- 可复用环境已本轮验证：Python C:/Users/Lenovo/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe，3.12.14；PYTHONPATH 指向 reliability-v2-20261119/runtime-deps，依赖openai1.109.1/httpx0.28.1/textual1.0.0/openpyxl3.1.5/sqlglot30.33.0。虚构SQLite可只读，40票/48流水/0发票审计。受审用户上下文shared-flash/U001、test/U002可用，常规sandbox无法读WindowsVault；不需用户重输密钥。
- 进行中任务：A sprint_a_semantics 在a-investigation只读调查；B sprint_b_execution 在b-execution实施。两者均从契约0589d16派生；root唯一集成。用户已明确授权本轮24物理请求/240000 total_tokens/每次输出2048，见evidence/AUTHORIZATION.json；旧轮结案不续用，当前新调用仍0。
- 已知阻断：上轮通用正文抑制导致正确终止答复/展示顺序回退；引用票号来源拒绝、冲突范围模型误选、R1 SQL证据不闭合。不得整包盲合并上轮候选。
- 初步方案：B实现有序工具事实引用/真实receipt契约，模型选工具、事实和次序，Harness绑定范围/标签/数值；A核实只读引用来源应与修改授权区分。不是最终实现或通过结论，完成后先定向验证与root审核。
- 下一步：等待A精简根因与B可运行切片；root复核兼容与安全边界后仅合并经证据支持改动。验收规则已预登记evidence/ACCEPTANCE-PROTOCOL.md，不提前出题。
- 实际进程核查：受审只读枚举未发现python.exe/pythonw.exe运行进程，未发现可确认的既存Python工作台加载路径；今后测试明确从冲刺integration/finance_agent启动，不沿用旧目录。
- 禁止提前：C未启动；冻结前零新增Live；不做GUI/文件导入；不改正式账簿；不推送main。
