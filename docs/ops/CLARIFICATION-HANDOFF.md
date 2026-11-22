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
