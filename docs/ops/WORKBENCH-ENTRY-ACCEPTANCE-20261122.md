# 工作台薄入口限定验收

业务入口受测冻结 SHA：`c16228bf2d9999a223497fd92c19464e15c35d33`。最终交付源码 `394441c` 仅将设置页两句“宿主接口未提供”修正为受信绑定和本机模拟账号说明，未重跑已通过 Live，不迁移其 SHA。其后的状态／交接文档提交不改变产品代码。

复用 DSH `c0de7a1` 的页面导航／待办操作及原 SessionHost、SessionStore、任务服务、Profile 配置／Windows 凭据。没有新增登录认证、业务状态 owner、Loop、模型提示词或业务范围。接口及归属见 [DSH-WORKBENCH-INTERFACE](DSH-WORKBENCH-INTERFACE.md)。

## 新增入口与结果

| 节点 | 实际结果 | 证据类型 |
| --- | --- | --- |
| 待办详情与办理 | HTTP task_details 返回当前规则、缺项、可办理性；task_open 持久化原企业／月份／任务焦点 | 实际 GUI HTTP／原 owner 程序证据 |
| 办理焦点保存失败 | 原 Store.select_focus 受控失败，旧 Agent 未退休，对象和范围未被替换；随后合法保存成功 | 程序故障证据 |
| 已有 Profile | 不存在的 Profile 保留旧实例；已有另一配置可构造并切回 shared-flash；没有向其他服务发送题目 | 原配置／凭据构造证据，不等于其他服务 Live |
| 选待办后查统计 | DeepSeek 原话“按刚选待办的企业和账期……”交付 C001／2026-09，卡片和末答均 1,460.00 元、2 张，独立 SQLite 146000 分／2，coverage complete | 有限 Live，非陌生盲测 |
| 缺值且不提交 | Live 建立 WB-014 备注待补，WAITING_USER；Profile／待办／重绑定均拒绝，原可信对象仍在，未调用目标工厂 | Live 前置＋实际接口边界 |
| 正常账簿重绑定 | 原 owner 取消未批准工作后，由受信 Python 工厂打开另一账簿的独立 Store；新 generation，无旧要求、草稿和批准 | 实际宿主程序证据 |
| 运行中／预览 | Live 到达原 GUI 预览；三种切换均拒绝，新绑定工厂零调用 | 实际 Live 预览＋并发程序证据 |
| 预览传输中断 | 原确认回调的受控超时，没有返回批准或拒绝；原 owner 为 operation.ERROR，原备注不变、该票审计为零 | 程序故障证据，不是人工拒绝 |
| 未知提交 | 复用已有真人请求 e589676257ab440d88008529fb76828f；只读核查受控不可用时，恢复 UNKNOWN_OUTCOME，三种切换拒绝且保留原请求 | 旧真实提交＋新只读恢复程序证据，零重提 |
| 账号重绑定 | U002 使用自身已有 test Profile 构造目标原 SessionStore；不带 U001 对象／要求／批准，U001 任务不可读取；U002 使用 U001 Profile 失败保留旧绑定 | 本机模拟账号程序证据，不是登录认证；该账号无新增远程调用 |
| 浏览器自报身份 | 不存在 rebind JSON 路由，返回 404；浏览器不能指定 user_id/db_path/role 获得绑定权限 | 实际 HTTP 边界 |

## 原失败与记账

第二段运行在预览切换阻断通过后，验收器错误要求超时必须使用顶层 `error`，触发断言。保留 `remaining-switch-boundaries/FIRST-FAILURE.public.json`，没有改分／重发预览。后续读取同一原 Store／trace，确认 owner 已存 ERROR 与明确停止摘要、财务未变；诊断与独立未知／账号边界在 readonly-continuation，程序结果不冒充 Live。

本轮新增 **6 个物理请求、38,203 tokens、56,968 微元峰价上界**。原共享账累计 **201 次、1,680,694 tokens、2,676,020 微元峰价上界**，不是供应商账单；累计上限均 null，历史未清零、不另建账。全部请求仍为原 deepseek-flash／https://api.deepseek.com。新增财务写入、自动批准、自动拒绝均零。旧完整提交链、会话切换、历史裁剪证据按各自原 SHA 复用，没有重跑全量或旧完整链。

原件目录（本地、未上传含模型输入的完整日志）：`business-20261120/evidence-root/recovery-boundary-20261121/workbench-entry-20261122/`：FROZEN、AUTH、逐节点快照、http 原始记录、RESULT；其下 remaining-switch-boundaries 和 readonly-continuation 保留各自分类与首次结果。收集器位于同级 recovery-boundary-20261121/workbench_entry.py、workbench_switch_boundaries.py、workbench_remaining_readonly.py。

## 交付边界

本轮实现与有限 Live 已完成；**真人对新增按钮、布局和切换提示的独立 GUI 可用性尚未验收**。现有账号仅本机模拟，未实现生产认证。账号／账簿的浏览器选择器需要 DSH 宿主提供受准选择目录和策略；当前不接受浏览器任意 actor/path，也未伪造一个登录入口。原真人提交证据只证明原操作，不迁移为本轮新增按钮的人眼签收。完成即冻结，不继续扩展能力或叠加同类检查。
