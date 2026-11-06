# Stage 3B 实际上下文与引用链路

4P-C协议边界：Agent持有ThinkingProtocol，实际模型消息归一为PrivateAssistant（dict业务字段+仅进程内reasoning属性）。ContextBuilder.build通过可选measure按完整传输副本计字符，当前必要消息超限即CONTEXT_LIMIT，旧轮仍整体取舍；私有字段只随被选中的原assistant消息进入wire，不进入任务/偏好/回执。身份切换清空原消息；新Agent/进程不恢复。会话服务配置改变则PROTOCOL_ERROR，要求新会话，不跨服务导出旧私有历史。

普通Mock默认不启用厂商Thinking协议，不因本地存在live环境变量而要求模拟响应提供私有字段；test_stage4pc显式设置Agent.protocol进行协议模拟。live路径不变，不隐式关闭真实DeepSeek Thinking。

仅官方https://api.deepseek.com（根路径或/v1）及已核实模型deepseek-flash/deepseek-v4-pro启用默认Thinking工具协议；自定义DeepSeek代理不猜测，普通兼容服务不发送私有字段。实际模型回复缺字段/None/错误类型不补造，实际空字符串原样保留。带name的本地context_data/harness_history/harness_schedule/reference_data/harness_output不是模型推理，传输时显式使用空协议槽，不冒充实际模型返回内容；模型不能借此创建权限。真实模型的无tool_calls最终回复也保留其实际协议字段。

Agent发送前还原完整reasoning_content；Trace在model_input/model_reply及嵌套出口标记[PRIVATE_PROTOCOL_HIDDEN]，不把遮蔽文本回传。protocol.selected仅记录字段数量/字符数等诊断；不记录原始思考。测试test_stage4pc.py覆盖完整回传、跨轮最终回复、配对、整轮裁剪/超限、字段类型、普通/OFF/无tools、身份/进程/服务隔离及日志/数据库不泄露。OFF仅适配器离线显式测试，不暗改live默认参数，不实现Profile或CLI切换。

CLI main(chat) → Agent.ask → ContextBuilder.begin：从当前明确编号/数字年月/官方企业简称更新焦点；冲突清空旧焦点并失效旧锚点，可信/task切换及/cancel亦失效。不会暂停/取消持久任务。连续/edit仍由WriteCoordinator拥有，不由Context恢复授权。

模型请求前 Agent.model_messages → ContextBuilder.build：保留唯一system与当前轮完整消息，按唯一企业读取tasks.list_tasks、preferences.manage_preference(list)，筛选同月未完成任务；references.reference_catalog返回自己可访问的最近展示元数据。context_data、reference_data、harness_history均使用assistant命名数据消息，不变成user/system，不伪造tool_call_id。历史模型/业务数据都不是当前金额、权限或提交证明。Scope不唯一时不自动读所有企业的任务/偏好。

默认消息字符上限48000，Agent(max_context_chars=...)或CLI --max-context-chars配置。保留本轮整段；附加数据或旧轮整段超预算则记录遗漏；本轮必需数据超限直接停止，不截断当前要求/工具参数，不遗漏配对。计数是json.dumps(messages,ensure_ascii=False)的字符数，不包括工具Schema，也不等于模型token窗口。原始Trace按原有脱敏器记录实际输入；context.selected记录选择来源、范围、来源表、裁剪、字符数，context.limit记录停止原因。

正式最终回答先用responses.render_information呈现真实结果，再ContextBuilder.record_displayed → references.record_display保存实际展示顺序。来源仅list_invoices、get_invoice、check_missing_purpose、resolve_invoice_reference；没有展示的数据不建锚点。表reference_anchors持有owner/display_id/anchor_id/company/年月/source/时间/有序联合键，金额/用途/备注不存为锚点。迁移是显式migrate-stage3b；未迁移的Stage 0–3A库保留原功能，但引用无锚点时AMBIGUOUS，不自动改表。

引用入口 reference_hint只识别“第N张”（数字及百以内中文序数）、“那张/这张”（单对象），可带已显示的anchor:ID。未给anchor时仅使用最新一次实际展示；同轮多列表必须用企业/年月或anchor消歧。相对时间、多序数更正、错误序号保守追问，不按关键词决定业务工具。

ContextBuilder.resolve → references.resolve_reference：限定可信用户 → 候选展示锚点 → 唯一对象 → 当前企业权限 → queries.get_invoice重新读取联合键当前值及日期。无候选/多候选/无效序号=AMBIGUOUS；已删除=NOT_FOUND；权限=DENIED；当前日期不在原范围=SCOPE_MISMATCH；数据库故障=ERROR。不会返回旧金额/用途冒充当前值。模型可请求resolve_invoice_reference，但Handler另检本轮可信线索和已解析anchor，模型不能自由挑序号。

成功引用提供reference_data和本轮expected_scope；查询/Prepare继续走原Handler。所有写入还需可信/edit、绑定草稿确认、事务审计和回读。引用不是确认。旧锚点可跨独立进程重查，但新Agent不会加载Draft/Confirm/Commit。任意自然语言理解、昨天/上个月等历史时间筛选、复杂排序/多对象指代及“它”的语义消歧未实现；不宣称可验证所有隐含目标。底层元数据写入故障时展示告警/本会话阻断引用；故障导致未持久化的失效动作不能保证跨重启恢复。

tests/test_stage3b.py使用临时SQLite，覆盖序数、真实顺序、同号隔离、多列表、错误引用、更正/取消、权限撤销、独立子进程恢复、旧值更新/日期变更重查、范围锁定、无确认零审计、来源注入、限长和消息配对。test_architecture把references纳入业务层、context纳入运行层；无反向依赖或第二Loop。Context不承担Scheduler；Stage 3C独立单轮计划见[schedule-budget.md](schedule-budget.md)。

4P-E：ContextBuilder.record_displayed从已经展示的成功只读结果保留prior_query_tools（工具名列表，不含参数、金额或操作授权）；_data在assistant/context_data内附来源。begin更正范围仍清除旧范围及旧引用，新范围下模型可用该历史查询类型延续概览目标，不能继承旧企业金额或写入许可。Agent身份切换仍新建ContextBuilder；没有新增持久对话或自动摘要。test_stage4pe验证月份更正后的数据线索不带旧金额；任意语义理解的剩余失败仍按Live报告保留。


## S4-P0C：来源不是模型标签
ContextBuilder维护轻量ScopeProof来源：当前明确输入、仍有效用户会话、实际重解析引用、实际选定/确认任务的SQLite范围。begin更正使冲突焦点失效，单改企业可保留用户此前明确年月，但不能保留旧SQL/引用派生日期。accept_task不因list_tasks就选中年月；需本轮明确task_id或真实具体确认。scope_provenance用于解释，不给模型声明来源的权力；正式分发再检证明身份。有限中文/数字年月支持，不解释无可靠依据的相对时间，不是完整Reference/Intent系统。
