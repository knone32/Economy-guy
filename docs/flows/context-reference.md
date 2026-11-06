# Stage 3B 实际上下文与引用链路

CLI main(chat) → Agent.ask → ContextBuilder.begin：从当前明确编号/数字年月/官方企业简称更新焦点；冲突清空旧焦点并失效旧锚点，可信/task切换及/cancel亦失效。不会暂停/取消持久任务。连续/edit仍由WriteCoordinator拥有，不由Context恢复授权。

模型请求前 Agent.model_messages → ContextBuilder.build：保留唯一system与当前轮完整消息，按唯一企业读取tasks.list_tasks、preferences.manage_preference(list)，筛选同月未完成任务；references.reference_catalog返回自己可访问的最近展示元数据。context_data、reference_data、harness_history均使用assistant命名数据消息，不变成user/system，不伪造tool_call_id。历史模型/业务数据都不是当前金额、权限或提交证明。Scope不唯一时不自动读所有企业的任务/偏好。

默认消息字符上限48000，Agent(max_context_chars=...)或CLI --max-context-chars配置。保留本轮整段；附加数据或旧轮整段超预算则记录遗漏；本轮必需数据超限直接停止，不截断当前要求/工具参数，不遗漏配对。计数是json.dumps(messages,ensure_ascii=False)的字符数，不包括工具Schema，也不等于模型token窗口。原始Trace按原有脱敏器记录实际输入；context.selected记录选择来源、范围、来源表、裁剪、字符数，context.limit记录停止原因。

正式最终回答先用responses.render_information呈现真实结果，再ContextBuilder.record_displayed → references.record_display保存实际展示顺序。来源仅list_invoices、get_invoice、check_missing_purpose、resolve_invoice_reference；没有展示的数据不建锚点。表reference_anchors持有owner/display_id/anchor_id/company/年月/source/时间/有序联合键，金额/用途/备注不存为锚点。迁移是显式migrate-stage3b；未迁移的Stage 0–3A库保留原功能，但引用无锚点时AMBIGUOUS，不自动改表。

引用入口 reference_hint只识别“第N张”（数字及百以内中文序数）、“那张/这张”（单对象），可带已显示的anchor:ID。未给anchor时仅使用最新一次实际展示；同轮多列表必须用企业/年月或anchor消歧。相对时间、多序数更正、错误序号保守追问，不按关键词决定业务工具。

ContextBuilder.resolve → references.resolve_reference：限定可信用户 → 候选展示锚点 → 唯一对象 → 当前企业权限 → queries.get_invoice重新读取联合键当前值及日期。无候选/多候选/无效序号=AMBIGUOUS；已删除=NOT_FOUND；权限=DENIED；当前日期不在原范围=SCOPE_MISMATCH；数据库故障=ERROR。不会返回旧金额/用途冒充当前值。模型可请求resolve_invoice_reference，但Handler另检本轮可信线索和已解析anchor，模型不能自由挑序号。

成功引用提供reference_data和本轮expected_scope；查询/Prepare继续走原Handler。所有写入还需可信/edit、绑定草稿确认、事务审计和回读。引用不是确认。旧锚点可跨独立进程重查，但新Agent不会加载Draft/Confirm/Commit。任意自然语言理解、昨天/上个月等历史时间筛选、复杂排序/多对象指代及“它”的语义消歧未实现；不宣称可验证所有隐含目标。底层元数据写入故障时展示告警/本会话阻断引用；故障导致未持久化的失效动作不能保证跨重启恢复。

tests/test_stage3b.py使用临时SQLite，覆盖序数、真实顺序、同号隔离、多列表、错误引用、更正/取消、权限撤销、独立子进程恢复、旧值更新/日期变更重查、范围锁定、无确认零审计、来源注入、限长和消息配对。test_architecture把references纳入业务层、context纳入运行层；无反向依赖或第二Loop。Context不承担Scheduler；Stage 3C独立单轮计划见[schedule-budget.md](schedule-budget.md)。
