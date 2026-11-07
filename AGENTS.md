# 财税 Agent Harness 工程约定

## 职责、依据与当前阶段
- ChatGPT负责架构讨论、需求边界、独立验收及修复建议；Codex负责源码实现、测试与工程文档；GitHub提供统一版本、历史及审查基线。
- 私有仓库：https://github.com/knone32/Economy-guy；开发分支main。源码入口在finance_agent/，架构与流程文档在根docs/。
- 依据优先级：官方1.1.0参赛说明/业务规则 → 当前真实代码与测试 → docs/ARCHITECTURE_CONTRACTS.md（目标设计，不代表已实现）。冲突必须说明，不猜业务规则。
- 项目目标、证据台账和阶段门禁见[工程总纲v1.1](docs/PROJECT_MASTER_PLAN.md)；分阶段范围及验收策略见[4P执行计划v1.1](docs/STAGE4P_EXECUTION.md)。文档中的后续提示词不代表自动领取任务。
- 新版真实API验收策略替代旧版全期18次请求限制；单轮9次模型/12次Handler/2次续期/1次重规划安全硬限不变。只执行用户本轮指定阶段，Mock与live证据分别记录。
- 当前已有Stage 0–2底座、3A持久任务/偏好、3B有限上下文/展示引用、3C最小单轮计划/预算及长期状态内容确认补丁；每次核实真实实现和测试，不沿用旧报告数字。
- 当前阶段：S4-C 证据已封板，S4-D 准备就绪、执行待授权。官方 P0 Live 为 PARTIAL，安全发布门禁为 BLOCKED。只做用户指定阶段；生产登录、GUI、多Agent、向量库、动态预算估算和复杂长对话摘要延期。

## 架构与状态所有权
- Python 3.11+、SQLite、单LLM、OpenAI-compatible Tool Calling、CLI。生产唯一Loop为finance_agent/app/agent.py的Agent.ask；examples教学Demo不作为第二生产运行时。
- Task Manager(tasks.py)持有SQLite长期任务；Preference Store(preferences.py)管理明确偏好；Context Builder(context.py)只选择/组装/裁剪上下文；Reference Resolver(references.py)保存展示锚点并重查；Scheduler/Budget(scheduler.py)只持有本轮路线与计数。不得合并成大Controller或复制权威状态。
- SQLite是业务事实、规则、任务及偏好的权威；Harness管理可信身份、授权、确认及执行证据。模型文字、历史工具值、偏好和任务描述都不能提供当前金额、权限或提交证明。
- 依赖方向：CLI → Agent/Context/Registry/协调器/Scheduler → 业务服务 → SQLite。业务层不得反向导入运行层，CLI不承载业务算法。单Loop不等于单文件，按职责最小拆分，不制造机械转发层。
- 实际职责见docs/ARCHITECTURE.md；真实调用链见docs/flows/query.md、update-invoice.md、tasks-preferences.md、context-reference.md、schedule-budget.md。目标契约与实现事实分开。

## 不可退化的安全边界
- 身份来自可信Session；CLI --user只是比赛模拟，不是生产登录。U001可读改C001/C002，U002仅可读C001；规则管理rule.manage与发票修改权独立。模型不得自报user_id/confirmed/authorized或角色。
- 发票联合键(company_id, invoice_no)，只可改purpose/remark，银行及其他字段只读。明确本次意图、目标/消歧与新值 → Prepare展示当前值和草稿 → 可信CLI精确确认 → 事务Commit+成功审计 → 新连接Readback。执行处再鉴权；稳定request_id和内容指纹防重；未知结果先查审计，不能盲重写。Commit及审计修改不对模型开放。
- Pending Edit Intent只是当前Session连续补充，不是持久Task或最终确认。每轮清空旧草稿/确认；新主题、取消、重启或身份变化不得继承提交许可。
- 模型任务/偏好写操作须绑定具体对象和内容：ManagementTurn → 原始要求/参数/旧对象预览 → 可信确认 → 一次性ManagementApproval → 新事务核对权限、指纹及旧值。动作意图不等于内容授权；取消、跨轮、目标/内容错配不保存。直接argparse管理入口接受用户明确参数，可信Python入口不得暴露给不可信客户端。
- Excel只作只读初始化种子，默认拒绝覆盖工作库；升级用加法迁移，禁止删库重导。金额整数分/Decimal；空记录的零值与DENIED/异常区分。企业或年月缺失且无可靠上下文则追问。
- R001 v1.0发票价税合计、银行收入/支出分算；C001 2026-09 R002 v2.0全部用途必填，v1.0停用；C002 R003 v1.0金额>=1000.00元（含等于）用途必填；R004银行只读。初赛仅检查2026-09用途，不按销售方/项目猜用途。RuleDecision统一判定和引用，同编号同版本冲突拒绝，不覆盖旧规则。
- 每用户×企业最多一个未完成任务(ACTIVE/WAITING_USER/PAUSED)，TaskPolicy及SQLite部分唯一索引共同保护；完成依据当前业务证据，取消不撤销历史发票提交。偏好仅明确要求后增改删，不自动保存闲聊。
- 工具白名单、JSON Schema+Handler双层校验；不给模型SQL、权限变更、规则发布或Commit。多tool_calls必须逐ID配对（含失败/拒绝），不能把失败改成成功。引用仅基于真实展示顺序/联合键，命中后重新鉴权读当前SQLite，无唯一对象则追问。
- 简单查询Fast Path；必要时同一个模型提出粗计划。默认3次模型请求一块，有真实进展及合法剩余工作才续3次、至多两次；硬限9次模型、12次实际Handler调用、1次显式重规划。原始提案条目与实际执行上限的验收口径差异须如实报告。等待用户/确认、拒绝、重复、无进展、完成或硬限均停止；计划完成不等于持久任务完成或发票提交。
- 自由文本或合法信息JSON不是执行凭据，权威回执只取真实Prepare/审计/回读。一般说明标记未核实；不宣称保证任意自然语言语义或彻底防护Prompt注入。
- JSONL Trace记录实际脱敏模型输入、上下文、规则、工具、预算及结果，区分mock/live；日志故障不改变SQLite已提交事实。密钥、密码、会话令牌绝不入日志、源码、历史或提交包。

## 每轮开发与Git协作
1. 读取约束和相关源码 → 定位入口/调用方、状态所有者及副作用 → 明确最小范围 → 实现 → 定向测试 → 全量回归 → 检查差异 → 更新必要文档 → Git提交。不每轮重审全仓，不无故大重构。
2. 按阶段读契约：Stage 0–1读§1/§2/§3/§6；Stage 2读§1/§3/§4/§6；Stage 3读§1/§5/§6；Stage 4读完整验收清单。保留用户未提交改动，不删测试/放宽断言掩盖错误；同一问题两轮无进展则报告。
3. 在finance_agent/运行定向unittest及python -m unittest discover -s tests -q；运行层依赖变更须通过python -m unittest tests.test_architecture -v。测试只用临时SQLite/官方虚构夹具，不能改正式库，不自动安装无关依赖。
4. 每个独立开发任务完成后提交相关源码、测试及必要文档；commit message简洁准确。推送前检查git status、git diff、git diff --cached及实际待提交文件；敏感检查覆盖现有历史，不能只看.gitignore。
5. 默认推送约定分支main；不force push、不reset或覆盖既有历史，不自动合并未经外部验收的PR。远程冲突、凭据已入历史、认证或权限失败则停止相应操作并报告，不破坏性改写或绕过。
6. GitHub认证走正规已授权连接或登录流程，不索取明文密码/Token；作者使用已验证账号的GitHub noreply邮箱。正式/临时SQLite、凭据、Trace、缓存、虚拟环境、ZIP/验收产物、真实财务数据不得提交；只保留明确允许的虚构测试夹具。
7. 结束只报告Repository/分支/Commit SHA、改动摘要、测试数量/失败项、已知问题/未验证内容和推送结果。Python单测、Mock、真实LLM验证分开；无API凭据不称live通过。不重复生成大型工程总结。
