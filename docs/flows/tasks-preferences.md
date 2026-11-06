# Stage 3A 实际持久化链路

4P-B组合目标：Registry._set_schedule及remaining_work_allowed可验证当前有效ManagementProposals派生的无权限候选预览步骤；有显式领域/动作时仍不回退。Schedule只约束依赖与路线，实际manage_task/manage_preference继续返回具体提案，经可信CLI确认后才建立一次性许可，不改变Scheduler硬限/停止逻辑。task_progress仅只读计算现有任务当前剩余用途，不建立第二持久进度状态。对应test_stage4pb.py组合场景分别验证确认、取消及无确认回调零写入。

迁移：main.main(migrate-stage3) → app.stage3_schema.migrate → SQLite新增tasks/preferences和部分唯一索引。无业务重导，Stage 2规则与审计不覆盖。

CLI：main.main(tasks/preferences)用可信模拟--user和显式action创建ManagementIntent → tasks.list_tasks/manage_task或preferences.manage_preference。user×company隔离；U002可管理自己在C001的任务/偏好，但不能访问C002或修改发票。

自然语言：chat → Agent.ask创建仅本轮有效、无管理权限的ManagementProposals → 模型manage_task/manage_preference → Registry.handle_tool严格字段/企业权限/范围预检 → ManagementCandidate（不是ManagementIntent/Approval）→ 释放预检事务 → tasks/preferences借can_propose仅预览具体对象/参数/当前值，require_management_confirmation必定返回WAITING_CONFIRMATION，未保存。CLI展示original_request/proposal/current/request_id → 用户完整输入confirm request_id → persistence.confirm_management此时才创建ManagementTurn/ManagementIntent及内容指纹绑定的ManagementApproval → 业务服务新BEGIN IMMEDIATE重新鉴权、核对参数及旧值、消费一次性许可后写SQLite。

显式chat(`/task action ...`或`/preference action ...`)继续由Agent.ask(management,management_action)创建受动作约束的ManagementTurn，走同一预览/确认/事务路径；错误动作或领域不会退回自然语言候选而绕过约束。Context/Scheduler及唯一模型Loop未重构，计划本身不能创建管理授权。

所有模型任务写操作（包括新增、说明/年月更正、暂停、恢复、完成、取消）及偏好create/update/delete均需确认；任务show、偏好get/list不需确认。未配置可信management_confirmation回调只返回待确认提案，不保存。取消/EOF/非True回调结果不保存。回调收到原始提案的副本，不能通过模型confirmed/user_id字段获得许可。Registry拒绝无本轮预览生命周期的裸调用；候选不能通过can_manage，即使直接重调业务服务也只会再次预览。

ManagementTurn及ManagementProposals生命周期由Agent拥有，仅本轮有效；自然路径确认后的Turn绑定候选来源，新ask、/cancel或身份变化使旧许可失效。确认期间身份变化先撤销许可并配齐原tool_call_id，下一入口再清理旧身份上下文。指纹绑定actor/domain/action/source_request/turn_id/request_id、全部业务参数和旧对象；许可只用一次，内容或目标不同为DENIED，确认期间对象变化为CONFLICT，权限撤销仍DENIED。确认结果在工具evidence.management_confirmation记录为可信来源数据，不伪装成user消息。此短期许可不写长期任务表、不授予发票修改权，也不继承到新进程。

直接argparse tasks/preferences入口仍把用户明确参数直接传给业务服务，不经过模型；因此保留无turn的可信内部ManagementIntent兼容接口。它只能用于可信Python/CLI，不是面向不可信客户端的认证机制。确认解决模型提案未获具体授权的问题，不声称自动判断任意自然语言内容语义一致；用户必须核对实际展示的对象和内容。

任务仅2026-09 missing_purpose，create需明确note及真实缺失项；无后续工作为NO_CHANGE。TaskPolicy检查名额，部分唯一索引防并发。ACTIVE/WAITING_USER/PAUSED占用名额，COMPLETED/CANCELLED不占。冲突不替换旧任务。

complete重查规则与当前发票，必须缺失为0且有发票；context记录历史完成证据，但不是当前规则权威。resume重查归属、访问权、规则和缺失项；不会创建旧UpdateSession草稿/确认。发票修改仍走新/edit→Prepare→可信确认→原事务审计与回读。任务取消只改变任务状态。

偏好主键user_id/company_id/preference_key；create同名冲突、update不存在NOT_FOUND，get/list只读，delete需明确意图。没有全局偏好，不自动保存闲聊或自动注入全部Prompt。偏好值是数据，不是权限或确认。

SQLite是唯一持久状态。提交结果未知返回UNKNOWN_OUTCOME并要求重新查询，不盲重写；JSONL不能代替业务记录。CLI仍不是生产认证。测试：test_stage3a.py（状态、并发、隔离、完成证据、CRUD、独立子进程、授权不继承），test_architecture.py（新业务模块不得反向导入运行层）。

补丁测试test_management_confirmation.py：简洁→省略审核、任务note错配均无确认零写入；正确确认、取消、更新/删除/错目标、一次性/跨轮/身份变化、旧值冲突、撤权及真实main交互路径。原Stage3A/3C三处合法模型写入测试增加具体提案的可信确认，原数据/权限/状态断言保留。

4P-A测试test_stage4pa.py补充普通自然语言候选/确认、任务更正取消、偏好CRUD与真实子进程读取删除结果、候选无管理权限、错误对象展示拒绝、确认时取消/身份切换、旧ID不可复用和追问异常处理。responses.parse_final对合法字符串型未知missing_fields仅保留为追问，render_clarification生成通用补充问题，不展示模型任意text/未知标签，不映射成业务字段或写入权限；错误JSON/字段类型仍安全停止。

4P-E：只有已鉴权manage_preference(action=get)的NOT_FOUND可作为负向读取证据让TurnExecution.observe有限继续，仍保持ok=false/status=NOT_FOUND及真实范围；其他NOT_FOUND/拒绝不改成成功。具体确认后的偏好SUCCESS写入仅使同企业/对象旧get（及该企业list）的去重记录过期，写调用去重和9/12/2/1计数不重置。因而可get不存在→候选→可信具体确认→create→重新get；无确认不写。responses.render_information单独展示偏好不存在，不能冒充0.00或已保存。test_stage4pe验证该链路；P11保留OPEN，真实模型及停止提示限制见S4-P-E报告。
