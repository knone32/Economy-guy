# 等待补选与结构化澄清交接（未发布）

基线 67dfc8a；本地分支 fix/2026-11-22-pending-relationships。第一项动作契约已单独提交 684e60c；第二项候选交接另行提交，不新增 Loop、owner、状态机或中文关键词分流。

## 原始失败的两个数据边界

原 one-live-chain/trace.jsonl 第45行：独立动作将等待选票/禁止保存解释为 pause；第53行执行澄清仅在正文提及新值，未给结构化候选。旧 bind_clarification 只带字段，故第54行待补只剩 remark。集合在 change_invoice 中因 matter=new 跳过显示集合继承；缺少独立的展示引用关系。原首错与5次物理请求原样保留，不改分。

## 契约和 owner

独立 action_reason 将 await_selection、await_value、continue_matter 对应 continue，defer_matter 对应 pause，cancel_matter 对应 stop；pause/stop 必须有对应原因与当前动作原话，冲突拒绝。它仍是模型解释，不是程序语义证明或提交许可。

独立 reference_relation/displayed + reference_quote 表达本轮明确引用真实展示。新发起修改也可引用先前读取集合；事项新旧与引用关系分开。none/unclear 不会自动套旧展示；失效引用不能猜对象。引用集合和身份从原 Runtime 记录取得，模型不提供集合键。

直接 clarification 复用 pending_change={field,new_value,source:{kind:current,quote:当前连续原话}}。解析器只接结构，bind_clarification 核对当前 quote、精确值及字段一致，再交原 change_invoice。正文永不反抽成值、身份或批准；无来源或冲突候选拒绝，旧状态不变。工具参数路径仍由同一 owner 核验。原 Loop 对 WAITING_USER 工具直接生成澄清，故“先工具后澄清”无需为了复述再请求模型；之后的直接澄清仍保留已存内容。

## 有限程序证据

tests.test_clarification_handoff 覆盖直接澄清和工具后澄清：未选定保留新值及可信集合，等待输入而非暂停；零单票读取、零预览。后续结构化澄清不清值，集合内选择 fresh 读取后预览正确新值，集合外拒绝。无来源文字与无关对象反例仍不绑定。明确暂缓另经原 SessionHost/SessionStore 得到真实 PAUSED 行及可恢复列表。全部临时账簿及审计逐行不变，无批准。

CLARIFICATION-01.log 的暂缓断言错误读取被退役为历史的 result；数据库 PAUSED 已成立。修正测试读取 business_status/pending，唯一重跑见 CLARIFICATION-PAUSE-02.log。保护日志 CLARIFICATION-PROTECTION.log 含原 F009/F008 关键断言及架构检查，无全量、无旧完整提交链。

## 冻结后的必要 Live

只回归原失败的“真实查询→等待补选→集合内选择→原预览并取消”。用于区分独立动作是否仍误判，以及带来源候选/集合在真实模型路径中是否保留；首错后停止，不加同类矩阵。程序双路径不冒充真实模型选用两种协议。结果及实际消耗按同一冻结源码写本地包外回执 clarification-live/RESULT.public.json 或 FIRST-FAILURE.public.json；原累计账不清零、不另开预算。没有真人GUI验收，不推送、发布或替换旧包。

## 1fa501d 的新首错及后续修复

第一次有限 Live 回归新增5次请求/43147 tokens（共享累计284次/2327038 tokens）。动作正确变为 continue/await_selection，展示集合也保留；但执行回复仍只有正文、无 pending_change，原 owner 因此无可接受的新值来源。首错后未走选择、预览、取消，原 FIRST-FAILURE.public.json 保持。不能把这个结果计为通过。

针对这份新证据，同一 pending_change 候选也在独立阶段表达当前已给新值。它按当前来源校验，临时绑定在原 BoundIntent（不新增持久状态）；原 change_invoice 将它合并到待补，执行方可以省略，冲突则拒绝。最终直接澄清也用同一 checked_change 来源检查；不依赖正文搬运或新模型调用。未给值时明确显示“修改内容尚待补充”，不能显示内容已保留。

CLARIFICATION-CARRIER-BEFORE.log 保留实现前反例，CLARIFICATION-CARRIER-AFTER.log 及 CLARIFICATION-CARRIER-PROTECTION.log 证明同一个候选在执行方省略时，两条路径均保留，集合内 fresh 预览、集合外拒绝和真实 PAUSED 不退化。后续只对这一新增机制继续同范围原题回归，不追加场景；结果另存 clarification-live-followup，不覆盖1fa501d失败或67dfc8a原失败。自然语言泛化及真人GUI仍未签收。

## 207e283 的共同范围来源阻断

该版 Live 已保住当前值、原可信集合和活动等待关系，但执行方提供集合共有的企业/年月时，被只接受唯一单票来源的绑定器拒绝。原 scope conflict 与后续不可用工具原样留存，不能因待补有值而判通过。验收器漏查 DENIED，额外发送了1条依赖消息（1物理请求/6570 tokens），计入真实消耗；FIRST-DEVIATION-ADJUDICATION.public.json 单独定位较早首错，不改原件。之后停止，不将选票阶段算成功或独立场景。

修复只让原 display_collection 返回所有可信锚点共同的 company/year/month 范围，由原 owner 构造部分 target_origin；共同范围没有 invoice_no，不授予唯一身份，选定后仍逐项 fresh 核验。用户显式限制冲突、集合外或失效集合继续拒绝；未引用集合的新事项不套旧范围。CLARIFICATION-COMMON-BEFORE/AFTER.log 保留正反与原 F009/F008 保护。独立动作说明改为真实枚举结构，解析继续精确校验，不按中文前缀放宽。

下一同范围回归使用 clarification-live-final；验收器要求执行 stop_reason=WAITING_USER 且无 blocked_reason，否则不再发选票消息。所有历史原分、真实消耗、未到预览结果保留；不追加矩阵、不重跑旧提交链。
