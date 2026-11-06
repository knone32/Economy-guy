# Stage 3C 实际计划与预算链路

入口：main.main(chat) → Agent.ask → 新建TurnExecution(BudgetPolicy)。每条用户消息独立计数，只有原Agent.ask模型循环。Task Manager的SQLite任务、Context焦点、WriteCoordinator授权/草稿、业务审计仍各有所有者。没有新增数据库表、Planner Agent或后台调度。

Fast Path：直接调用业务工具并自然结束，不调用set_schedule、不预先增加模型请求。真正有多步依赖时，同一模型可用set_schedule(goal,steps,stop_condition)提出粗计划。step只有step_id/action/arguments/depends_on；action必须为已授权业务工具，依赖只能是前序ID，arguments为已知参数约束，可以留待真实前序结果补全。Registry._set_schedule使用validate_arguments复用严格JSON/类型/枚举检查，独立查真实企业权限、用户范围和本轮管理/Prepare意图。简单无依赖查询拒绝建计划。

任务恢复：实际manage_task(resume)处创建一个粗恢复步骤，Task Manager仍负责重查规则和发票。工具实际返回后该恢复步骤可DONE；原持久任务通常仍ACTIVE，不称为业务任务已完成。内部SQL/事务/审计不是单独计划步骤。

执行：Agent → TurnExecution.dispatch去重/预算记数 → Registry.handle_tool解析/鉴权/范围检查 → execution.guard匹配就绪步骤 → 原业务服务。实际结果经observe更新步骤；只有SUCCESS/NO_DATA可形成进展，NO_CHANGE不算新进展，模型文字/计划安装/重规划不算进展。Prepare结果只进入WAITING_USER，保留既有最终确认与提交链路。

预算：默认初始3次模型调用；软限处必须本块真实进展增加、存在未完成就绪步骤、当前Handler能力/企业权限/意图仍合法、尚有工具额度，才续3次。至多2次续期，硬限9次模型/12次实际Handler调用。配置入口为Agent构造参数及chat的--block-requests/--max-requests/--max-tools/--max-extensions/--max-replans；硬限只能降低，块长可配置。API失败也计一次实际模型调用，Context超限未发送不计模型调用。每次set_schedule亦计一次实际工具调用。

同一个模型至多一次显式再次set_schedule重规划；既有执行证据不抹除，可据此恢复匹配步骤DONE，不能冒充新进展或复活已停止调用。重复规范化工具参数不再执行；必要的重复读取请开启新用户轮次。明确拒绝、等待用户/确认、API/参数/规则/范围错误、无进展、已完成及硬限均停止。一次assistant提出多calls时，无论何时停止，全部对应原tool_call_id返回结果，后续项DENIED且不执行；保留第一个停止原因。最后一个模型请求包含工具也按相同规则处理。

收尾：执行已停止 → Agent.finish提供真实工具结果/独立写回执及last_response.execution。模型自行结束但计划未完成，标MODEL_FINISHED_WITH_PENDING_WORK，步骤不被口头标DONE。计划COMPLETED只证明所列工具步骤，不证明任意自然语言目标，也不证明发票提交；发票提交只认WriteCoordinator核对审计和回读后的回执。

Trace保持mode=mock/live：budget记录计数，budget.extended记录真实续期理由/计划，schedule.created/replanned/progress记录观察进度，execution.stopped记录停止原因，turn.finished保存最终完整快照。actual_tool_calls是实际进入Handler的调用（包括校验失败/计划控制），requested_tool_calls还包含拒绝和跳过项。harness_schedule仅为ContextBuilder投影的assistant数据，不提升权限。Trace故障沿用既有隔离，不改变SQLite提交事实。

对应tests/test_stage3c.py：Fast Path、两次续期/9次硬限、无进展/重复、12次多call及配对、依赖顺序、拒绝/未知目标、确认等待、合法重规划保留证据、伪造完成、真实任务恢复、撤权后不续期、配置硬限、API故障、跨轮预算归零及Trace。tests/test_agent.py原预算用例改为不同真实发票查询，避免与新重复保护混淆，原成功数量/配对断言保留并增加预算状态断言。
