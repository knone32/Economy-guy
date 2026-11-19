# 当前意图候选与可信执行

模型在同一 assistant content JSON 可携带小型 `intent` sidecar，仍使用原 tool_calls、唯一 Agent Loop。它只描述 `read`、既有待补的 `amend` 或 `cancel`，不是通用计划语言，不新增模型理解调用，不接受 actor、authorized、confirmed 或 Commit。

`read` 的 target 为单一公司、年份、月份和可选明确票号；每槽带当前精确原文片段或实际可信锚点。模型解释未识别措辞的 canonical 公司/年月，程序检查原文存在、类型、当前可明确提取目标和可信引用冲突、企业存在及当前读取权限。票号必须有真实标识符或可信对象锚点，不能把“这张”映射成任意编号。相对日期仅支持唯一可信 period 加 -24 至24月的有界算术，不增加中文年份/别名/句式词表。该来源记作 `model_read_candidate`，只进入只读参数检查及 SQL 受限快照，不加入写入 SOURCES，也不直接成为 current_sqlite。实际工具仍重新鉴权，详情仍核实际日期。已有可信参数、年度 month=0 或其他原有查询不需要新 sidecar。

`amend` 必须引用当前 server-owned pending_request_id，给唯一公司/年月/票号、field/new_value及逐槽来源。当前修改对象来自去引号的有限原文来源；字段为已有业务字段名/标签；新值为精确原文值或明确合法承接的旧待补值。可信锚点只能提供对象，不提供新值或授权。所有槽校验后才原子替换内存 pending，保留 actor/book/request_id，不保留过期确认。来源错误不部分应用。

同一候选可由已有规范化 proposal 参数、当前原文、旧 pending 及本轮 fresh selection 编译，兼容已经正确选择工具但旧句式校验拒绝的路径；仅单票普通更正，batch/规则/显式清空等原合法路径仍使用既有验证。提案前再次核 candidate 与当前 actor/book/turn、selection 的唯一联合键和实际账期、field/new_value、可选 write_scope 完全一致，再交既有 ACL、预览、确认、事务、幂等、审计与新连接回读。字段来源由已验证的 runtime BoundIntent 承接，而非从自由正文猜测。

optional 兼容编译不能把旧 pending 字段与当前其他字段的新值拼接。仅当当前引用外已有受控字段来源为空（合法承接），或唯一且与 formal proposal 字段一致时，才继续编译；冲突或多字段不作此推断，回既有 validator 或要求模型显式 intent。检查只使用原有 purpose/remark 字段枚举标签，不增加词表、句式或正则，不宣称判断了否定、转述或多字段语义角色。显式 intent 的 target 字段与实际 proposal 不同仍直接拒绝。

`cancel` 只允许当前 pending id，撤销未提交候选和确认，不撤销历史事务。被取消消息中的 tool_calls 均配对取消结果，不进入 Handler。所有原模型消息照常进入 Trace；最终信封解析可剥 sidecar，但不改原始记录。

预算的 typed pre-HTTP 拒绝独立于网络失败。已有真实结果且仅 token 预留不足时，可在原 Loop 剩余合法槽位尝试一次 tools=[] 收尾，不增加模型/续期/重规划/全局预算上限；模型若仍调用工具，逐ID拒绝且0 Handler。再次预算不足、无槽、格式无效则交付真实结果/回执并明确未完成。收尾不能用模型正文抹去预算通知，也不会自动确认或提交。

这些是可验证的程序契约，不证明模型规范化语义或新表达必然正确。当前 span 存在及参数可执行不等于机器证明了所有自然语言含义；真实模型若选择错误语义仍应在独立 Live 的 INTENT/RESULT/RESPONSE 评分失败。合并仅在新冻结及业务验收后判断，不复用已公开题作为隐藏分数。
