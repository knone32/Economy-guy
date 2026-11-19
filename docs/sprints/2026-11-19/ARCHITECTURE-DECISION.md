# 架构职责决策（主会话负责）

目标：真实DeepSeek自然语言单票修改→缺目标待补→用户补目标→fresh事实→可信绑定→正式预览，确认/拒绝仍由真人界面；只有预览Live通过才验证后续写链。用户现授权架构职责纠偏，取代第四阶段停止开发状态；历史候选/证据/账本保持。

## 已确认的冲突与分类

A：R3A真实Trace行5/18仅有完整selection提案，行21最终正文识别未选对象但无pending事件，行22 ANSWERED。部分语义正确、动作选择/输出协议遗漏；Runtime窄门接受回答且交付抹掉待补说明，非合规提案被拒。
B：R2P.1 explicit_invoice_candidates_required使pending未建，R2P.2原company在首轮明确但后续AMBIGUOUS；缺可信来源为状态链级联，不可通过信模型ID解决。
C：R2Q初始BETWEEN查询与独立真值相同但scope UNKNOWN/unsupported_predicate，扩大读取后预算拒绝导致缺比较。属于范围证明/结果交付/预算，不把未知末回复算NLU失败。已实现typed事实不删除；本切片不虚称修完任意SQL分析。
D：S4A request→合法pending成功；补目标fresh正确，propose多company_id被实际anyOf拒。业务槽正确但工具参数非法，Runtime按协议拒绝；该合同让同一企业在一分支必需/可用、另一分支禁止，并让模型搬运selection/pending引用。

## 方案比较

|方案|内部字段/重复状态|能力与安全|时间成本/同类风险|
|---|---|---|---|
|A 保留双模式，仅容许并校验company或拆名字|仍要求LLM维护action切换、selection、pending_id、mode、excluded以及跨工具读取|可保原底座；不能静默删字段|改动小，但只是多放一字段，未消除引用搬运和状态协议遗漏|
|B 单票业务动作一致参数，Runtime组织内部读取/提案|LLM只给已知company/年月/票/field/new_value，后轮可仅补票；不传生命周期、selection、确认、mode|Runtime校原话/已验证pending、身份/范围/ACL，fresh读取后调用原plan和preview/事务底座；复杂集合/规则接口保留|局部调用链改动较A多，移除一类参数切换和重复状态责任，今晚可小切片验证|

选择B。不重写Agent Loop/权限/DB/事务/审计。新增单票业务入口change_invoice，旧集合/规则提案仍供该能力使用；Runtime拥有该入口建立的pending时只向模型展示一致单票接口，避免切回旧内部协议。旧API保留兼容和已有批量能力，不伪装为新接口成绩。最终JSON旧状态协议不再用于该入口；只展示已知业务槽，不要求返回内部request_id。必要内部proof为服务端创建，不能由模型提供。

## 各边界职责

自然语言/业务动作由模型决定；Tool Registry严格校声明的业务参数，未知/授权参数拒绝，不删键；来源绑定从当前明确原文与同actor/book的已验证pending获得，不从任意readset建写对象；Runtime生命周期/actor/book/执行引用服务端持有；SQLite和现有plan负责权限/实际对象/日期/现值；UpdateSession/正式preview/真人确认/事务幂等审计回读不改；结果证据仍绑定指标/范围/真实回执，不能模型自报保存。

补目标只在已存在此业务动作的可信pending中接纳当前唯一明确标识符，缺对象不猜；初始完整对象仍需现有写角色来源证明。完整参数由Runtimefresh读取再调用原plan，不要求模型先get再复述ID；内部调用独立标记runtime，不伪造model toolcall。

## 安全门禁与进度

权限/企业隔离/当前actor/book/原文field-value来源/明确对象/正式preview/人工确认/事务/审计/幂等/回读不得变；模型没有提交入口。冲突先拒或追问，不按问句添词表。

当前起点业务SHA5253deea95fbc8090fb4253d6f5ffce8318f7fb3，控制f1a97b0，独立business-ownership主会话直接实现，尚未冻结/无新Live。预算用户新授权12请求/180000total/输出2048，旧封账不动。先公开Trace机制及必要正反例，再冻结、C两个独立新表达；只有真preview通过且真人实际操作确认才能验写，不允许自动批准。若再次出现职责冲突先停定位，不自动全仓重构或大型下一轮。
