# 架构职责决定

## 收敛同一来源与默认值入口（2026-11-21）

8b61首错说明显式默认update被当成需要新原话的关系变更；同帧seller.current Source对象也与旧context-only解析不一致。仅复用同一声明解析器覆盖scope/seller/filter/metric，当前quote两个载体一致且仍核原话，context先固定同对象／企业的前owner，再核同类同值字段与引用／谱系。默认update无quote不新增替换权；非默认关系原来源检查保留。旧scope顶层quote兼容行为不扩，比较、SQL、Loop、草稿owner均未改。有限检查结束后冻结，仅一次统计Live，不据程序绿扩大业务范围。

## 单一入口规范化来源表示（2026-11-21）

df68496 真实选择全名回合的业务解释正确，Source对象却被字符串比较误当current，随后空quote被报成用户歧义。前文metadata本来就展示Source对象，继续追加问法提示不能解决这处接口差异。仅在原bind将current/context token与受控Source对象规范化；quote当前来源、key字段／目标／修订／hash及谱系仍核对，实际Source由Runtime重建，声明不创建权限。无key只是旧context token的同义表示；错形态为INVALID_ARGUMENTS，真实范围冲突与证明能力限制仍分开。沿用原Loop、一次结构重述上限、草稿和确认owner。

## 只读澄清复用已核要求（2026-11-21）

native 修改暂挂时应清掉旧票的临时 scope；这不应清掉已经独立绑定的新查询要求。原 native→歧义→全名对照表明，要求仍在，绑定器却只看空 trusted_scope，首先丢失企业来源。复用现有 `company_source=context`／`period_source=context`：可信槽空时，可精确引用已核 actor、账簿、原话 hash、目录及同对象的唯一前目标，记前修订与字段来源。已有可信值冲突不回退，多目标不猜，账期集合必须完整相等，ACL、旧 seller／filter 保留规则照旧。局部 ScopeProof 只供既有校验，不写回全局 Context，不恢复旧票范围、不提供批准。

这次不新增 Schema、Loop、草稿 owner 或自然语言关键词。恢复修改继续由原 SessionStore／WriteCoordinator 的候选认领、fresh 预览和真人确认承担；先闭合业务再做泛化。

## R5 当前只读证据与重复展示
get_invoice可以在同ask中借本轮实际SQL原列身份补缺槽，但必须当前runtime-owned结果、同SQL哈希、VERIFIED、完整未分页未截断、invoices原列，全部合格身份联合键并集唯一且与模型完整目标相等。保持已有字面/期范围/现权冲突；仅call-local controlled_read_scope，不写Context/不入写SOURCES。真实get_invoice仍fresh鉴权读取。默认TRIM只归因业务文本列并将ASCII空格变换保留在条件/口径，不归一化身份/日期/金额。

SQL和freshget可以真实显示同一发票两次，不能因此把一个业务对象变成两个候选。native内部可按同企业/年月/联合键且每来源只有1key判等价；记录全部equivalent_anchor_ids并fresh读最后等价源。global resolver默认和显式ordinal协议不变，不合并不同key/period、多key或坏元数据，也不扩大多行SQL可选集。这不构成人批或提交许可。

## V3-R4 事实来源修复（15:45）
SQL只对实际日期字段substr(date,1,4/7)的严格ISO前缀等值/IN补证，按已有授权月份取交集；不支持表达式继续UNKNOWN，别名不定义金额。可选read_scope缺年份只能复用同企业已有合法ScopeProof的唯一当前年份，目录不能单独补年。当前不可读/未知对象是内部否决约束，不能退回旧工作区；同轮独立明确的合法目标仍按真实来源逐项核实，不做否定词路由。

最终answer错误沿既有read_finish一次额度、for循环和TurnExecution预算给模型真实结构诊断，无工具/无新值/无父ref自动替换；原select/derive不放宽。展示对象来源只来自实际UI回调、受限单行原始身份及本聊天owner，native action必须明确选联合key再fresh resolve；它是对象数据来源，不是写许可。当前原话矛盾、缺目标、旧聊天/取消、非唯一/分页/空SQL结果都不得默认补旧票。新值仍当前原话，实际提交仍由原权限/预览/CAS/真人链负责。

## V3-001 独立工作树与唯一集成（2026-11-20）
A/B独立克隆718d812；根独占contract-followup并集成。C独立封题不改产品，避免工作树竞争及答案污染。保留正式AgentWorkspace→Agent.ask、现有SQLite/事务/审计底座，不新建生产Loop。

## V3-002 故障归因先于修复
182FAIL/33ERROR先按真实堆栈与当前接口分组，区分产品缺陷、过期契约断言、夹具/测试器错误和环境。保留原始全量成绩；不能统称历史失败或以放宽断言制造通过。

## V3-003 预算与人工确认
所有付费走原共享账本和根调度，未知消费保留；无新额度池。测试代理不得取得真人批准能力；程序故障注入证据与真人完成分别记录。

## V3-004 可信查询投影与范围
模型选择业务指标；SQL AST只证明实际投影/单位。仅受限ISO日期年/月前缀可成为分组维度，标量按实际行细化企业和期间，下游程序复用已有父事实计算差额。COUNT不因题面或别名被改成SUM，不支持形态继续UNKNOWN。减少正确分组结果被证据层误拒，同时保留语义错误独立责任。

## V3-005 多格式资料复用不可变底座
Excel行和PDF页复用material_versions/material_paragraphs的原始字节、版本、去重、私有ACL和既有原文工具，仅增加location表及格式读取器。上传完整解析后再落资料事务，不改业务表、不自动编译或发布规则。Excel实际解析行列限制独立于不可信dimension，PDF仅文字抽取不宣称OCR/表格还原。Word解析层拒DTD不依赖原字节编码。去掉三套重复资料状态和权限逻辑。

## V3-006 预算与日志分责
已知供应商usage先持久记账；本地证据日志故障只追加local_log_status，不能把已知消费改成未知或触发重发。沿用原OS锁/账本/13条不可变前缀，物理发送前预留，未知usage持久停止。按V3自主分配8192输出，不扩大总2.20元/64/700000；峰价核算标为保守费用上界，不冒充账单。

## V3-007 冻结执行与协议
C正式Live只用标准AgentWorkspace→Profile/WindowsVault→Agent.ask→ModelTransport；统一预算位于HTTP层，不替换语义Loop或禁用Thinking协议。冻结源码独立克隆，根运营文档可继续更新；实际成绩只绑定冻结完整SHA。正常窗口可见由用户确认，批准仍必须真人逐笔操作。


## V3-008 配置读取不得创建业务账簿
assistant_config各普通读取使用既有库只读连接；未配置legacy库返回无配置而不迁移。显式管理初始化仍可在既有业务库增表，但不能因路径错误创建空业务库。复用open_existing和原配置/ACL/revision机制，消除所有普通能力检查的路径副作用；未放宽任何原断言。

## V3-009 原话对象来源与业务关系分责
当前ACL目录中的登记全名/short_name/ID及实际票号字面证据，由同一business_object_sources核实，不再要求模型把已唯一指出的对象翻译回固定甲乙/F前缀。模型仍决定业务动作与关系；元数据匹配不创建动作许可。唯一企业+发票后复用fresh get_invoice核ACL与真实日期，补齐缺失年月，再复用既有BoundIntent/plan/正式preview/真人批准。已明确日期冲突、实际重名、值内引用反向造目标仍拒绝。对应5b的C03通用失败，非该简称/票号特判。

## V3-010 普通追问不等于持久办理事件
SYSTEM已允许kind=clarification+missing_fields，但pending_contract曾要求额外pending事件，导致有效问题被拒/额外模型补正。普通只读问题现在不需要模型生成内部请求ID；Harness可保存只读待补历史（不含change/批准），跨轮继续问。显式旧pending/change提案保留严格校验，业务单票继续用change_invoice增量。缺失字段由可信渲染器形成问题，不让任意正文自称保存或取消。先前部分synthetic“结构不完整”不能全部归测试器：有效普通追问的拒绝经新原入口测试确认是产品接口冲突；原日志不改。

## V3-011 可信调用上下文早于配置读取
SQL actor/path/no-workspace属于调用身份绑定，应在读取任何目标库能力配置前拒绝。否则合法来源拒绝被错误路径ERROR掩盖，甚至过去会创建空库。复用原有DENIED检查并只前移，不改变SQL sandbox或允许范围。

## V3-012 Agent对象框架不得覆盖已核来源
只读早期对象判断、UI所选企业冲突判断、get_invoice来源补充，复用同一当前ACL对象解析。完整登记票号的数字不再二次解释为年份月份；不因旧F前缀正则丢弃已核的明确票号。Context来源按真实原话而非caller已补全的explicit参数确定，防止caller把controlled_read_scope升为写来源。invoice handler仍每次fresh核事实/ACL；年度读取使用READ_SOURCES，写入继续SOURCES。仅对象数据起源归程序，不增自然语言关键词判断。
