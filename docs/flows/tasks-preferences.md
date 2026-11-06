# Stage 3A 实际持久化链路

迁移：main.main(migrate-stage3) → app.stage3_schema.migrate → SQLite新增tasks/preferences和部分唯一索引。无业务重导，Stage 2规则与审计不覆盖。

CLI：main.main(tasks/preferences)用可信模拟--user和显式action创建ManagementIntent → tasks.list_tasks/manage_task或preferences.manage_preference。user×company隔离；U002可管理自己在C001的任务/偏好，但不能访问C002或修改发票。

模型：chat(`/task action ...`或`/preference action ...`) → 原Agent.ask(management,management_action)建立ManagementTurn → 同一Registry字段校验、企业鉴权/范围预检 → 释放预检事务 → 业务服务预览具体对象/参数/当前值，返回WAITING_CONFIRMATION（未保存）→ CLI展示original_request/proposal/current/request_id → 用户完整输入confirm request_id → persistence.confirm_management绑定内容指纹 → 业务服务新BEGIN IMMEDIATE重新鉴权、核对参数及旧值、消费一次性许可后写SQLite。原模型Loop、Context与Scheduler没有重构。

所有模型任务写操作（包括新增、说明/年月更正、暂停、恢复、完成、取消）及偏好create/update/delete均需确认；任务show、偏好get/list不需确认。未配置可信management_confirmation回调只返回待确认提案，不保存。取消/EOF/非True回调结果不保存。回调收到原始提案的副本，不能通过模型confirmed/user_id字段获得许可。Registry拒绝把无ManagementTurn的动作意图当模型写入授权。

ManagementTurn由Agent拥有，仅本轮有效；新ask、/cancel或身份变化使旧许可失效。指纹绑定actor/domain/action/source_request/turn_id/request_id、全部业务参数和旧对象；许可只用一次，内容或目标不同为DENIED，确认期间对象变化为CONFLICT，权限撤销仍DENIED。确认结果在工具evidence.management_confirmation记录为可信来源数据，不伪装成user消息。此短期许可不写长期任务表、不授予发票修改权，也不继承到新进程。

直接argparse tasks/preferences入口仍把用户明确参数直接传给业务服务，不经过模型；因此保留无turn的可信内部ManagementIntent兼容接口。它只能用于可信Python/CLI，不是面向不可信客户端的认证机制。确认解决模型提案未获具体授权的问题，不声称自动判断任意自然语言内容语义一致；用户必须核对实际展示的对象和内容。

任务仅2026-09 missing_purpose，create需明确note及真实缺失项；无后续工作为NO_CHANGE。TaskPolicy检查名额，部分唯一索引防并发。ACTIVE/WAITING_USER/PAUSED占用名额，COMPLETED/CANCELLED不占。冲突不替换旧任务。

complete重查规则与当前发票，必须缺失为0且有发票；context记录历史完成证据，但不是当前规则权威。resume重查归属、访问权、规则和缺失项；不会创建旧UpdateSession草稿/确认。发票修改仍走新/edit→Prepare→可信确认→原事务审计与回读。任务取消只改变任务状态。

偏好主键user_id/company_id/preference_key；create同名冲突、update不存在NOT_FOUND，get/list只读，delete需明确意图。没有全局偏好，不自动保存闲聊或自动注入全部Prompt。偏好值是数据，不是权限或确认。

SQLite是唯一持久状态。提交结果未知返回UNKNOWN_OUTCOME并要求重新查询，不盲重写；JSONL不能代替业务记录。CLI仍不是生产认证。测试：test_stage3a.py（状态、并发、隔离、完成证据、CRUD、独立子进程、授权不继承），test_architecture.py（新业务模块不得反向导入运行层）。

补丁测试test_management_confirmation.py：简洁→省略审核、任务note错配均无确认零写入；正确确认、取消、更新/删除/错目标、一次性/跨轮/身份变化、旧值冲突、撤权及真实main交互路径。原Stage3A/3C三处合法模型写入测试增加具体提案的可信确认，原数据/权限/状态断言保留。
