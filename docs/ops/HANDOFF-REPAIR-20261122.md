# 五类交接缺口的有限修复（2026-11-22，未发布）

基线 76a9a75／产品 f28d88f；本轮仅在 sprint/2026-11-20-contract-followup 修复，不改 main、不覆盖正式库、不批准、不自动推送或发布。旧交付包仍是旧冻结版。本地修复候选在代码提交后冻结，再做必要 Live；源码／程序／Live／真人分别记账。

## 原始证据

用户上传 ZIP SHA256：b30b8c695b6d4026da92bdcd7dec907a314358b69d6a5f7dbf9421226636e5e9。解包后 66 个 SHA256SUMS 项全部匹配；14 份应用 Trace 是脱敏原件副本，不称为供应商完整 HTTP 包。原首分、原网络 usage、离线对照及原 ZIP 未修改。原件在本地 evidence-root/f28-review-originals-20261122。

## 最小改动

| 断点 | 改动 | 保留的核验 |
| --- | --- | --- |
| 解释器 | 显式路径优先且错误即停；自动逐项验证 venv／py／python 的版本与原 requirements 依赖，失败继续下一项 | 全不可用只报部署缺失，不创建正式库或切 Mock |
| 凭据 | ExistingProfiles 分别返回 CONFIG_UNAVAILABLE／CREDENTIAL_NOT_FOUND／CREDENTIAL_STORE_UNAVAILABLE，GUI 复用原 Profile／Vault 绑定；只记录配置绝对路径、安全身份、OS 用户与存在性 | 不打印密钥，不借其他 Profile 的 Vault 目标；当前本机 Lenovo 用户的同 Profile 实测 FOUND，不推断旧失败环境原因 |
| 启动身份 | 宿主提供完整 PowerShell argv／命令，含实际解释器、原会话库、账簿、模拟账号、Profile、配置绝对路径与端口；单引号正确引用 | 浏览器不猜默认值、不自报授权、不带密钥；重绑定后使用实际 Store.path |
| 来源冲突 | 错误调用仍拒绝，返回精确冲突槽；同一来源 owner 单独校验其余候选并保留未批准待补；复用原 Loop 一次补正窗口 | 未确认年月不继承；明确日期不删除；同错重复停止，无新循环、无批准 |
| 多候选 | 原完整 SQL 展示登记真实多行联合键；原待补只保存 display／anchor 引用；明确选票需属于当前仍有效集合，再核权、fresh 读 | 不凭模型正文选票；集合不授权写入；无唯一联合对象不选、失效重新查询 |
| 银行子集 | 执行前允许请求方向中的合法子集；原行集合程序合计形成实际方向 proof／标量，复用全轮覆盖与事实收尾 | 只一个方向不完整；旧月份 facts 不能完成新月份；金额-only 不假造数量 |
| 日期来源 | 共享 request_scope／explicit_scope 记录省略年份与唯一显式年份关系；多个显式年份仍有省略月份即 AMBIGUOUS | 不做年月笛卡尔积；不让生成器通过遗漏歧义月份规避追问 |
| 比较 | ReadComparison 可引用两侧已绑定 target／company／period；旧单企业跨月默认不变；算术仍来自原标量 derive | 指标、单位、basis、期间、分组和企业身份全部匹配后才交付；不接模型金额真值 |
| 状态／提示 | 恢复后旧暂缓正文退役为历史；透传并显示原 task_focus；预览回执用“正式确认界面”；保留语义阶段具体未决项 | 过期 revision 不恢复；无读权由既有内部负约束给出 DENIED，不暴露不可读目录；E 只读不可改原 DENIED 直接复用 |

## 程序证据（不是 Live）

仅运行受影响的有限正反控制与一项旧比较保护，没有全量。原 replay_offline.py 不改内容，用 UTF-8 进程参数执行；第一次 GBK 读取失败保留。另核对来源冲突的部分状态、改口和仅补 F009；集合内 F004 与集合外拒绝；银行双方向完整／单方向部分／旧月份失效；跨企业已核实标量比较及错误单位拒绝；多年份省略拒绝；实际待办焦点／恢复／过期恢复；原 L 语义回包的具体票号未决提示；原跨月比较断言。

中间失败分开保留：初版控制夹具漏关 SQLite 导致 Windows 清理错误、tuple/list 的无语义断言差异、未初始化 SessionHost display_ids；一次补正控制最初漏独立语义阶段；恢复投影最初使用空正文。仅修夹具，不迁移原分。实际新发现的多行 SQL 展示锚点拒绝与银行金额-only 缺计数字段渲染错误修在原入口。后续只重跑相应失败项，已通过者不重复。

原件在 evidence-root/handoff-repair-20261122：ORIGINAL-SCRIPT-UTF8-REPLAY、CONTROLS-01/02、AFFECTED-03、STATE-04、DATE-05、ENTRY-REPAIR-06、BOUNDED-07 及 controls.py。按机制和后续日志判断，不能把各日志累计测试数当业务通过率。

## 消耗与待验

云端包的 50 次／370,287 tokens 以 external_supplied_usage_evidence 来源追加原共享账。没有供应商请求 ID，使用明确标记的本地 evidence receipt，不伪造 provider ID。原 201 条前缀不变；并账后 251 次／2,050,981 tokens／3,366,973 微元峰价上界（不是账单），三限 null。导入属于历史消耗，不是本轮重放模型。原账备份、导入报告和本机无秘密配置诊断保留在本地证据目录。

当前程序控制通过不等于陌生自然语言或人工 GUI 通过。候选冻结后仅做少量必要新说法 Live；不重跑旧完整批准保存链，不自动作出确认／拒绝，不发布新的本地交付包或推送 GitHub。缺凭据的原 Windows 失败环境尚未对照，仍需其启动诊断，不能宣称已修好具体机器的 Vault。
