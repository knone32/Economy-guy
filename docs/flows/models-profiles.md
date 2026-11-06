# 4P-D 实际模型配置、会话及指标链路

- `main.main(profiles add/list/check)` → `model_config.add_profile/visible_profiles/resolve_connection`。Global需显式模拟profile.manage，User owner来自CLI上下文；无模型工具入口。模板TOML+本地JSON，编辑锁与原子替换，不写SQLite/Key。
- `resolve_connection(user,profile)`按CLI→环境Profile→文件默认→完整旧环境组选择，先校验可见性再读取选定环境变量。`ModelConnection`冻结私有Key、公开Profile元数据；service_account_ref不是已验证服务账户身份。
- `main.main(chat)`解析完整连接 → `Agent(connection)` → `ModelTransport`（唯一SDK调用点）。旧`agent.live_model`只为兼容的无会话Facade，也复用相同配置/传输模块；Agent绑定会话不逐轮重读全局环境或重复解析另一套Key。
- 生产唯一入口仍`Agent.ask`，薄活动状态guard→`Agent._ask`原有单循环。Transport使用同一个冻结connection的ThinkingProtocol，不在Registry/业务模块添加Provider分支。未配置的Python Agent可用于重启状态检查，但模型调用会明确停止，不在后续轮次偷偷采用新环境Key。
- `/provider use` → 可信`Agent.switch_model`：运行中/未确认/未知结果拒绝；先验证新Profile，再创建新Agent及Transport，重新鉴权企业年月，重新从SQLite读任务/偏好。仅带来源标记的历史用户目标与范围继续；不复制私有reasoning、assistant/tool历史、回执或确认。旧会话退休、旧许可撤销；即使同账户同模型也重建，故Key轮换/不兼容协议不共享原始历史。
- `_check_identity`清除旧业务身份的消息/目标/短期许可；私有User Profile在新用户下重新拒绝。没有账号认证、Profile管理Tool、自动fallback或跨模型摘要数据库。
- Transport真实SDK调用前后发`api.request/api.response`，仅公共元数据、usage/UNKNOWN、latency_ms、错误类别。Agent.trace为事件附可信actor/Profile元数据；Trace.redact遮蔽私有字段、凭据、敏感URL/混合文本，保留业务key与Token数。消息实际发送仍含必要原始协议字段，日志占位符不回流。
- 每轮api_counts是Transport累计计数的当轮差，`model_requests`仍来自原TurnExecution；SDK失败usage未知，原9/12/2/1预算不变。无Schedule时observe只改事件名为tool.progress，真实Schedule仍schedule.progress，进度和停止逻辑不变。
- `WriteCoordinator.commit_update`先核实审计/指纹/Readback并生成权威回执，再`_post_commit_progress`解析严格日期/调用原task_progress。此独立只读作用域的异常明确返回ERROR；不捕获或掩盖原Commit/审计/回读事务错误，也不重试写入。
- 测试：`tests.test_stage4pd`（配置权限/原子性、冻结凭据、切换/许可、Trace及提交后异常），原`test_stage4pc`及架构/全部业务回归。热切换是可信轮次边界的新对象替换，不是第二Agent并行执行。
