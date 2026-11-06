# S4-P-E 逐题独立评分摘要

题目和标准见[S4-P-E-CASES.md](S4-P-E-CASES.md)，主报告见[S4-P-E.md](S4-P-E.md)。全部PUBLIC_REGRESSION；EXTERNAL_HOLDOUT_PENDING。
工具参数来自实际请求；SQL栏仅由sqlite3快照计算，不采信模型完成声明。UI栏为用户实际输出的前100字摘录，完整输出/JSONL/快照仅保存在本地忽略目录，不上传。
评分中的FAIL包含安全拦截、执行成功后的协议错误、初态无效等不同原因，不都表示SQLite错误；原始结果均保留。ID含DIAG/SETUP不计正式完成率，ENV_INVALID不计有效业务评分但计全部API用量。

## live_20261106T084009Z

| Run / Profile | 实际工具序列（参数→状态；重复标dup） | E评分 / 停止 | 当前SQL：发票变更/审计/任务/偏好 | UI摘录 / Trace ID |
|---|---|---|---|---|
| A1-pro / shared-pro | 无工具 | PASS / WAITING_USER；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请提供年份和月份… / `ebff65cecc4743cea1c086684ab9c031` |
| A2-pro / shared-pro | get_finance_summary({"company_id":"C001","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 9622.06 元（10张）；银行收入 130… / `aa3a889ec972458b8d01987fca753611` |
| A3-pro / shared-pro | 无工具 | FAIL / WAITING_USER；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计0→0；任务0→0；偏好[] | 请提供本次请求的具体对象、操作和内容（无法确定所缺信息）… / `f9458d6db1b04c56959485ac074f15f8` |
| A4-pro / shared-pro | 无工具 | FAIL / WAITING_USER；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计0→0；任务0→0；偏好[] | 请提供本次请求的具体对象、操作和内容（无法确定所缺信息）… / `a9613b0d32c44a019ece7e9ca154552e` |
| A5-pro / shared-pro | get_finance_summary({"company_id":"C001","year":2026,"month":7})→NO_DATA | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-07；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 0.00 元（0张）；银行收入 0.00 元（… / `56b242e751d942b9832d80206c9bdef4` |
| A1 / shared-flash | 无工具 | FAIL / API_OR_RESPONSE_ERROR；API_OR_RESPONSE_ERROR | 字段变更[]；审计0→0；任务0→0；偏好[] | 请求失败：API请求失败或模型响应结构无效，未确认业务成功。… / `67e919014dd34d4790bf2f0fa37488d9` |
| A2 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 9622.06 元（10张）；银行收入 130… / `ff225632f0a8410c863724a95728ef1f` |
| A3 / shared-flash | get_finance_summary({"company_id":"C002","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 2026-09；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 12667.24 元（10张）；银行收入 13… / `580fa8b5c0004078ade0767c513e8849` |
| A4 / shared-flash | 无工具 | FAIL / WAITING_USER；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计0→0；任务0→0；偏好[] | 请提供本次请求的具体对象、操作和内容（无法确定所缺信息）… / `57dad83e35be4834ae6ef03ffd042936` |
| A5 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":7})→NO_DATA | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-07；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 0.00 元（0张）；银行收入 0.00 元（… / `25300ba7592a44b6b4bbbf4cccc9017b` |
| B1 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F002"})→SUCCESS; prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→WAITING_CONFIRMATION | PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操… / `9126c2005f2542cdb68f36b7384fda8a` |
| B2 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F002"})→SUCCESS; prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→WAITING_CONFIRMATION | PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更['C001/F002']；审计0→1；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操… / `462bfdef2cc24c6988e93cb65554e29e` |
| B3 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F002"})→SUCCESS; check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：{"company_id": "C00… / `f7f28c913e0b452c803421268f0202fb` |
| B4 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F002"})→SUCCESS; prepare_invoice_update({"company_id":"C001","field":"remark","invoice_no":"F002","new_value":"取消对照"})→WAITING_CONFIRMATION | PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操… / `18e37c258b3e4d13a637556ce5ac2638` |
| B5 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F002"})→SUCCESS | FAIL / ANSWERED；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计1→1；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：{"company_id": "C00… / `8461ccc972dc40ba8d939704d341ba62` |
| B6 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F002"})→SUCCESS; get_invoice({"company_id":"C001","invoice_no":"F002"})→NO_PROGRESS [dup] | FAIL / NO_PROGRESS；不必要/重复或未请求写工具 | 字段变更[]；审计1→1；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操… / `d57b34d8e7ef4af98235d6529f1afc04` |
| C6 / shared-flash | list_tasks({"company_id":"C001"})→NO_DATA; check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | FAIL / ANSWERED；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计1→1；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[] 没有匹配记录；这不是权限拒绝。 实… / `2612bf4fd2554bd199dd1dde99fd1c92` |
| C9 / shared-flash | check_missing_purpose({"company_id":"C002","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 2026-09；来源 current_sqlite；规则 R003 乙企业发票用途规则 v1.0。 本轮检查：3张必填用途缺失。依据乙企业发票用途规则 1.0版。 … / `9ad20cb5b2ed45bd92446dea890381c2` |
| C8 / shared-flash | list_tasks({"company_id":"C002"})→NO_DATA | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[] 没有匹配记录；这不是权限拒绝。… / `70b120fab2034f28bc853e1890eee769` |
| C1 / shared-flash | check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R002 甲企业发票用途规则 v2.0。 本轮检查：5张必填用途缺失。依据甲企业发票用途规则 2.0版。 … / `beb63dd4bef84a94b9f6db6d518fc120` |
| C2 / shared-flash | manage_task({"company_id":"C001","action":"create","task_id":"","year":2026,"month":9,"note":"继续为C001 2026年9月缺少必填用途的发票补充用途：F002、F004、F003、F006（备注“按月结算”不能代替用途）、F009。检查依据R002 v2.0（全部发票用途必填）。须由用户逐张明确用途后再修改，不推测用途。"})→CANCELLED [params!] | FAIL / CANCELLED；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计0→0；任务0→0；偏好[] | 请求已安全停止：CANCELLED；{"ok": false, "status": "CANCELLED", "data": null, "evidence": {}, "error": "用户未确认… / `a4943daa535a4d30a1f0a29cc6e19df5` |
| C7 / shared-flash | list_tasks({"company_id":"C001"})→NO_DATA | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[] 没有匹配记录；这不是权限拒绝。… / `3b7d128386d74970985bbf8dcb1eded3` |
| C3 / shared-flash | list_tasks({"company_id":"C001"})→NO_DATA; check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | FAIL / ANSWERED；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[] 没有匹配记录；这不是权限拒绝。 实… / `211760042c3a4925a4dbd6ac97112e6e` |
| C4 / shared-flash | prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→WAITING_CONFIRMATION | PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更['C001/F002']；审计0→1；任务0→0；偏好[] | 草稿已准备，尚未保存；请在可信CLI核对并确认。… / `c7cb28e070384a75b7fd8322e2b614f5` |
| C5 / shared-flash | check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | FAIL / ANSWERED；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计1→1；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R002 甲企业发票用途规则 v2.0。 本轮检查：4张必填用途缺失。依据甲企业发票用途规则 2.0版。 … / `eba76b14c5994f548f9bcdc2714f94c6` |
| D9 / shared-flash | manage_preference({"company_id":"C001","action":"get","key":"reply_format","value":""})→NOT_FOUND | PASS / NOT_FOUND；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请求已安全停止：NOT_FOUND；{"ok": false, "status": "NOT_FOUND", "data": null, "evidence": {}, "error": "当前用户企… / `d11cb1870166419c86e1b66d7d229da6` |
| D6 / shared-flash | manage_preference({"company_id":"C002","action":"get","key":"reply_format","value":""})→NOT_FOUND | PASS / NOT_FOUND；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=详细'] | 请求已安全停止：NOT_FOUND；{"ok": false, "status": "NOT_FOUND", "data": null, "evidence": {}, "error": "当前用户企… / `08428e06ec3c4644b2507d26848980bf` |
| D1-pro / shared-pro | manage_preference({"company_id":"C001","action":"list","key":"","value":""})→NO_DATA; manage_preference({"action":"create","company_id":"C001","key":"reply_format","value":"简洁"})→SUCCESS; manage_preference({"action":"list","company_id":"C001","key":"","value":""})→NO_PROGRESS [dup] | FAIL / NO_PROGRESS；不必要/重复或未请求写工具 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=简洁'] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 NO_DATA（… / `558dbe8529d9454f9b7f5d0d55b5ff91` |
| D2-pro / shared-pro | manage_preference({"action":"get","company_id":"C001","key":"reply_format","value":""})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=简洁'] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 SUCCESS（不授予发票修改许可）：{"user_id": "… / `a52cfe83064e4bc98b2ee76528ddb621` |
| D3-pro / shared-pro | manage_preference({"action":"update","company_id":"C001","key":"reply_format","value":"详细"})→SUCCESS; manage_preference({"action":"get","company_id":"C001","key":"reply_format","value":""})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=详细'] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 SUCCESS（不授予发票修改许可）：{"user_id": "… / `3a9864bb39384ffaa483a4b3c2eddbed` |
| D1 / shared-flash | manage_preference({"company_id":"C001","action":"create","key":"reply_format","value":"简洁"})→SUCCESS; manage_preference({"company_id":"C001","action":"get","key":"reply_format","value":""})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=简洁'] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 SUCCESS（不授予发票修改许可）：{"user_id": "… / `f0ad186b505441b889e511e0be651414` |
| D2 / shared-flash | manage_preference({"action":"get","company_id":"C001","key":"reply_format","value":""})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=简洁'] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 SUCCESS（不授予发票修改许可）：{"user_id": "… / `fa91a876b1864525988c510dc7634f62` |
| D3 / shared-flash | manage_preference({"action":"update","company_id":"C001","key":"reply_format","value":"详细"})→SUCCESS; manage_preference({"action":"get","company_id":"C001","key":"reply_format","value":""})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=详细'] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 SUCCESS（不授予发票修改许可）：{"user_id": "… / `35a5ad26dd0e4d0e9b33eb587901abb7` |
| D7 / shared-flash | manage_preference({"company_id":"C001","action":"delete","key":"reply_format","value":""})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 SUCCESS（不授予发票修改许可）：{"deleted_key… / `75e2500588fd421fba25ff770b96e614` |
| D8 / shared-flash | manage_preference({"action":"get","company_id":"C001","key":"reply_format","value":""})→NOT_FOUND | PASS / NOT_FOUND；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请求已安全停止：NOT_FOUND；{"ok": false, "status": "NOT_FOUND", "data": null, "evidence": {}, "error": "当前用户企… / `5891c8e9fd0e40b7a186482f340e3e0d` |
| A6 / shared-flash | get_finance_summary({"company_id":"C002","year":2026,"month":9})→DENIED | PASS / DENIED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请求已安全停止：DENIED；{"ok": false, "status": "DENIED", "data": null, "evidence": {}, "error": "没有读取权限"}… / `c6d6d13a623c43faa5be49784ba0b214` |
| D5 / shared-flash | manage_preference({"company_id":"C001","action":"get","key":"reply_format","value":""})→NOT_FOUND | PASS / NOT_FOUND；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=详细'] | 请求已安全停止：NOT_FOUND；{"ok": false, "status": "NOT_FOUND", "data": null, "evidence": {}, "error": "当前用户企… / `734bfd90782a4e748395df180fc8f307` |
| D4 / shared-flash | manage_preference({"company_id":"C001","action":"get","key":"reply_format","value":""})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=详细'] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 SUCCESS（不授予发票修改许可）：{"user_id": "… / `34f95318ef824aa8adf145d6d465004e` |
| SETUP_H2_commit-flash / shared-flash | prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→WAITING_CONFIRMATION | DIAGNOSTIC / PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更['C001/F002']；审计0→1；任务1→1；偏好[] | 草稿已准备，尚未保存；请在可信CLI核对并确认。… / `d1c05ce784af4e62858b98c2ff54d042` |
| SETUP_H2_switch-flash / shared-flash | 无工具 | DIAGNOSTIC / PASS / None；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务1→1；偏好[] | 可信CLI命令，无模型请求… / `None` |
| H2-flash / shared-flash | list_tasks({"company_id":"C001"})→SUCCESS; check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS; prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→DENIED [selection!] | FAIL / DENIED；不必要/重复或未请求写工具 | 字段变更[]；审计1→1；任务1→1；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作… / `5b759724c6034acb8851ca5118d50934` |
| SETUP_H2_commit-pro / shared-pro | prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→WAITING_CONFIRMATION | DIAGNOSTIC / PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更['C001/F002']；审计0→1；任务1→1；偏好[] | 草稿已准备，尚未保存；请在可信CLI核对并确认。… / `0e60d1d6b1ef4665b3fcba3b5488d7e1` |
| SETUP_H2_switch-pro / shared-pro | 无工具 | DIAGNOSTIC / PASS / None；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务1→1；偏好[] | 可信CLI命令，无模型请求… / `None` |
| H2-pro / shared-pro | list_tasks({"company_id":"C001"})→SUCCESS; check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | FAIL / API_OR_RESPONSE_ERROR；API_OR_RESPONSE_ERROR | 字段变更[]；审计1→1；任务1→1；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作… / `644b8537a4df45859339362ce775636b` |
| H1 / shared-flash | check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS; manage_task({"company_id":"C001","action":"create","task_id":"","year":2026,"month":9,"note":"下次继续补齐用途"})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→1；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R002 甲企业发票用途规则 v2.0。 本轮检查：5张必填用途缺失。依据甲企业发票用途规则 2.0版。 … / `9ae8784cee414e8fba9dbc9bcb413b2e` |
| A7 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":9})→NO_APPLICABLE_RULE | PASS / NO_APPLICABLE_RULE；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请求已安全停止：NO_APPLICABLE_RULE；{"ok": false, "status": "NO_APPLICABLE_RULE", "data": null, "evidence": {… / `b4ec8884cd0347deab4f81e825b1c65b` |
| B8 / shared-flash | prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→WAITING_CONFIRMATION | PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 草稿已准备，尚未保存；请在可信CLI核对并确认。… / `8e94fe539a90486c8dc3aa6079d8f8ec` |
| V01 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 9622.06 元（10张）；银行收入 130… / `1c7bf0fb7cd04967be2edb38b3c61fee` |
| V02 / shared-flash | get_finance_summary({"company_id":"C002","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 2026-09；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 12667.24 元（10张）；银行收入 13… / `ee2c5460817d46ddaf492e306d9afe26` |
| V03 / shared-flash | 无工具 | PASS / WAITING_USER；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请提供企业… / `91eda044ccc243b6aa5bbddb60528f3c` |
| V04 / shared-flash | 无工具 | PASS / WAITING_USER；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请提供年份和月份… / `f166d4189b5949558d29e4bb18387963` |
| V05 / shared-flash | 无工具 | PASS / AMBIGUOUS；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请明确引用对象：{"ok": false, "status": "AMBIGUOUS", "data": null, "evidence": {}, "error": "没有唯一可信展示列表，请提供企… / `fdeeda552f704351b90f6bf352cff7c1` |
| V06 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F002"})→SUCCESS | PASS / WAITING_USER；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操… / `5c3d5908ac964f8eb8ff58cf0ba8e6c3` |
| V07 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F002"})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：{"company_id": "C00… / `f7e2cd07443640e9b57e9589c67d1f63` |
| V08 / shared-flash | prepare_invoice_update({"company_id":"C002","invoice_no":"F002","field":"remark","new_value":"跨企业核对"})→WAITING_CONFIRMATION | PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 草稿已准备，尚未保存；请在可信CLI核对并确认。… / `b328d448d4374c03b3939bae1da31adc` |
| V09 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F999"})→NO_DATA | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：null 没有匹配记录；这不是权限拒绝。… / `c534fbf2d3f0487e8373a811a599227d` |
| V10 / shared-flash | 无工具 | PASS / AMBIGUOUS；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请明确引用对象：{"ok": false, "status": "AMBIGUOUS", "data": null, "evidence": {}, "error": "没有唯一可信展示列表，请提供企… / `b357071aff7a42169aa7961beb0c0a85` |
| V11 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":7})→NO_DATA | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-07；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 0.00 元（0张）；银行收入 0.00 元（… / `cdf340d9d9fa408cbcb8854ddc331d25` |
| V12 / shared-flash | check_missing_purpose({"company_id":"C002","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 2026-09；来源 current_sqlite；规则 R003 乙企业发票用途规则 v1.0。 本轮检查：3张必填用途缺失。依据乙企业发票用途规则 1.0版。 … / `7a961ab8b41d431ea6dad8710d240866` |
| V13 / shared-flash | prepare_invoice_update({"company_id":"C001","invoice_no":"F003","field":"remark","new_value":"下次核对"})→WAITING_CONFIRMATION | PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 草稿已准备，尚未保存；请在可信CLI核对并确认。… / `9f52004fd8664d1e87346831108f63b6` |
| V14 / shared-flash | manage_preference({"company_id":"C001","action":"list","key":"","value":""})→NO_DATA; manage_preference({"action":"create","company_id":"C001","key":"reply_format","value":"简洁"})→CANCELLED | PASS / CANCELLED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 NO_DATA（… / `999ccc723ff14a8cb5fd2cbcf3722df6` |
| V15 / shared-flash | 无工具 | PASS / WAITING_USER；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请提供企业和年份和月份… / `ffd1f357fb454fcdbd66194162a3b4a9` |
| V16 / shared-flash | 无工具 | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 该模型信息尚未核实；没有本轮可核验查询证据，也没有提交成功依据。… / `98d5ae820ced4f0787c9982f3772f946` |
| V17 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 9622.07 元（10张）；银行收入 130… / `dbf157bc24454b78b88f43e05c0f5468` |
| V18 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 9122.06 元（9张）；银行收入 1300… / `110789e975b748b59a43145b1cfd7a37` |
| V19 / shared-flash | check_missing_purpose({"company_id":"C002","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 2026-09；来源 current_sqlite；规则 R003 乙企业发票用途规则 v1.0。 本轮检查：6张必填用途缺失。依据乙企业发票用途规则 1.0版。 … / `3352c8dc79f74bbd8a9023bdeb487152` |
| V20 / shared-flash | check_missing_purpose({"company_id":"C002","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 2026-09；来源 current_sqlite；规则 R003 乙企业发票用途规则 v1.0。 本轮检查：4张必填用途缺失。依据乙企业发票用途规则 1.0版。 … / `b8627478ab464282ab026f7c0a1e3c35` |
| V21 / shared-flash | check_missing_purpose({"company_id":"C002","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 2026-09；来源 current_sqlite；规则 R003 乙企业发票用途规则 v1.0。 本轮检查：3张必填用途缺失。依据乙企业发票用途规则 1.0版。 … / `ab2afea3d7f64270a5d1a9830c9c829d` |
| V22 / shared-flash | check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R002 甲企业发票用途规则 v2.0。 本轮检查：7张必填用途缺失。依据甲企业发票用途规则 2.0版。 … / `3a572a779b6f42b188fbdb2e7a74bd7c` |
| V23 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":9})→DENIED | PASS / DENIED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请求已安全停止：DENIED；{"ok": false, "status": "DENIED", "data": null, "evidence": {}, "error": "没有读取权限"}… / `98dbdd08ab294402aa41dc909a115340` |
| V24 / shared-flash | 无工具 | FAIL / WAITING_USER；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计0→0；任务0→0；偏好[] | 请提供本次请求的具体对象、操作和内容（无法确定所缺信息）… / `8b3b76e856794348a1d68f846bfd8549` |
| B7 / shared-flash | prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→DENIED | PASS / DENIED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请求已安全停止：DENIED；{"ok": false, "status": "DENIED", "data": null, "evidence": {}, "error": "没有修改权限"}… / `cc4457b97e674c6bb90908d4a67afd52` |

### 每题真实请求/使用量（含诊断与初态无效，避免漏账）

| Run | API尝试 / input / output / total tokens | 客户端累计latency_ms | 初始PID |
|---|---|---|---|
| A1-pro | 1 / 3190 / 131 / 3321 | 3254.26 | 58996 |
| A2-pro | 2 / 7156 / 298 / 7454 | 5733.28 | 58996 |
| A3-pro | 1 / 3205 / 680 / 3885 | 16323.078 | 58996 |
| A4-pro | 1 / 3204 / 294 / 3498 | 6820.155 | 58996 |
| A5-pro | 2 / 6856 / 183 / 7039 | 4412.843 | 58996 |
| A1 | 1 / 0 / 0 / 0 | 5271.777 | 63864 |
| A2 | 2 / 6780 / 271 / 7051 | 2583.305 | 63864 |
| A3 | 2 / 7269 / 755 / 8024 | 6224.015 | 63864 |
| A4 | 1 / 3141 / 718 / 3859 | 5341.808 | 63864 |
| A5 | 2 / 6715 / 218 / 6933 | 2512.636 | 63864 |
| B1 | 1 / 3139 / 270 / 3409 | 1800.987 | 51576 |
| B2 | 1 / 3313 / 477 / 3790 | 3312.87 | 51576 |
| B3 | 2 / 10630 / 547 / 11177 | 3698.391 | 51576 |
| B4 | 1 / 6420 / 222 / 6642 | 1595.78 | 51576 |
| B5 | 2 / 6939 / 273 / 7212 | 3552.828 | 51576 |
| B6 | 2 / 7948 / 179 / 8127 | 2516.567 | 51576 |
| C6 | 2 / 7457 / 428 / 7885 | 3100.929 | 67676 |
| C9 | 2 / 7440 / 994 / 8434 | 7345.377 | 66024 |
| C8 | 2 / 6363 / 76 / 6439 | 1935.919 | 65712 |
| C1 | 2 / 7248 / 372 / 7620 | 3270.064 | 49828 |
| C2 | 1 / 4483 / 267 / 4750 | 2241.703 | 49828 |
| C7 | 2 / 6364 / 77 / 6441 | 1414.092 | 21360 |
| C3 | 2 / 7547 / 694 / 8241 | 5865.383 | 41872 |
| C4 | 1 / 4860 / 131 / 4991 | 1617.341 | 41872 |
| C5 | 2 / 12521 / 678 / 13199 | 5098.442 | 41872 |
| D9 | 1 / 3128 / 111 / 3239 | 1308.563 | 61036 |
| D6 | 1 / 3127 / 98 / 3225 | 1471.868 | 51576 |
| D1-pro | 3 / 10696 / 543 / 11239 | 12067.362 | 47964 |
| D2-pro | 2 / 9064 / 161 / 9225 | 4444.396 | 47964 |
| D3-pro | 3 / 15162 / 266 / 15428 | 6360.299 | 47964 |
| D1 | 2 / 7021 / 390 / 7411 | 3214.099 | 27756 |
| D2 | 2 / 8153 / 148 / 8301 | 1667.472 | 27756 |
| D3 | 3 / 13760 / 278 / 14038 | 3947.181 | 27756 |
| D7 | 2 / 6559 / 195 / 6754 | 2070.517 | 67876 |
| D8 | 1 / 3505 / 109 / 3614 | 1291.278 | 67876 |
| A6 | 1 / 3145 / 100 / 3245 | 1458.292 | 12144 |
| D5 | 1 / 3127 / 107 / 3234 | 1473.685 | 52272 |
| D4 | 2 / 6547 / 158 / 6705 | 2574.829 | 68044 |
| SETUP_H2_commit-flash | 1 / 3347 / 171 / 3518 | 1839.911 | 37464 |
| SETUP_H2_switch-flash | 0 / 0 / 0 / 0 | 0 | 37464 |
| H2-flash | 2 / 8139 / 3992 / 12131 | 25517.164 | 37464 |
| SETUP_H2_commit-pro | 1 / 3410 / 160 / 3570 | 3011.45 | 44408 |
| SETUP_H2_switch-pro | 0 / 0 / 0 / 0 | 0 | 44408 |
| H2-pro | 2 / 3474 / 270 / 3744 | 34877.257 | 44408 |
| H1 | 3 / 12994 / 671 / 13665 | 6270.812 | 66820 |
| A7 | 1 / 3149 / 268 / 3417 | 2604.607 | 67036 |
| B8 | 1 / 3139 / 280 / 3419 | 1992.444 | 26016 |
| V01 | 2 / 6493 / 253 / 6746 | 2831.239 | 28652 |
| V02 | 2 / 6732 / 247 / 6979 | 2957.331 | 58196 |
| V03 | 1 / 3096 / 98 / 3194 | 1116.07 | 59692 |
| V04 | 1 / 3126 / 71 / 3197 | 1547.717 | 52292 |
| V05 | 0 / 0 / 0 / 0 | 0 | 58136 |
| V06 | 2 / 6720 / 388 / 7108 | 3860.688 | 14740 |
| V07 | 2 / 6497 / 147 / 6644 | 2077.395 | 32756 |
| V08 | 1 / 3138 / 213 / 3351 | 1764.32 | 67372 |
| V09 | 2 / 6423 / 109 / 6532 | 2602.778 | 67932 |
| V10 | 0 / 0 / 0 / 0 | 0 | 24704 |
| V11 | 2 / 6766 / 237 / 7003 | 2647.891 | 42352 |
| V12 | 2 / 7113 / 265 / 7378 | 2910.015 | 58684 |
| V13 | 1 / 3137 / 171 / 3308 | 1620.325 | 54792 |
| V14 | 2 / 6471 / 255 / 6726 | 2885.318 | 11328 |
| V15 | 1 / 3005 / 184 / 3189 | 2108.454 | 59732 |
| V16 | 1 / 3010 / 126 / 3136 | 1893.453 | 52272 |
| V17 | 2 / 6723 / 228 / 6951 | 2680.055 | 58284 |
| V18 | 2 / 6721 / 244 / 6965 | 2541.234 | 37464 |
| V19 | 2 / 7592 / 1166 / 8758 | 7715.827 | 46936 |
| V20 | 2 / 7351 / 664 / 8015 | 5202.892 | 23940 |
| V21 | 2 / 7308 / 699 / 8007 | 5540.375 | 68600 |
| V22 | 2 / 7381 / 459 / 7840 | 3277.146 | 67124 |
| V23 | 1 / 3144 / 87 / 3231 | 1082.775 | 59424 |
| V24 | 1 / 3145 / 226 / 3371 | 2098.765 | 58756 |
| B7 | 1 / 3139 / 186 / 3325 | 2954.164 | 67720 |

失败请求无usage时此表Token只累计已知响应，不能把未知消耗解释为0。

## live_20261106T085345Z

| Run / Profile | 实际工具序列（参数→状态；重复标dup） | E评分 / 停止 | 当前SQL：发票变更/审计/任务/偏好 | UI摘录 / Trace ID |
|---|---|---|---|---|
| A1-pro / shared-pro | 无工具 | FAIL / INVALID_RESPONSE；INVALID_RESPONSE | 字段变更[]；审计0→0；任务0→0；偏好[] | 尚未保存：本轮没有提交操作；请明确目标、字段和新值后准备草稿。… / `2d97ee57ea3b4224982504cc53ca961b` |
| A2-pro / shared-pro | get_finance_summary({"company_id":"C001","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 9622.06 元（10张）；银行收入 130… / `6a87d61d50464ad48749c514d0c7674e` |
| A3-pro / shared-pro | get_finance_summary({"company_id":"C002","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 2026-09；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 12667.24 元（10张）；银行收入 13… / `de44bf3623b04973979ddbdc7aa687d3` |
| A4-pro / shared-pro | get_finance_summary({"company_id":"C001","year":2026,"month":8})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-08；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 9046.35 元（10张）；银行收入 148… / `daaeb22a95fb410b847bb54ecfe14800` |
| A5-pro / shared-pro | get_finance_summary({"company_id":"C001","year":2026,"month":7})→NO_DATA | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-07；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 0.00 元（0张）；银行收入 0.00 元（… / `7378de4da0cc41d281c0818b2bc13819` |
| A1 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":9})→SUCCESS [selection!] [params!] | FAIL / WAITING_USER；不必要/重复或未请求写工具 | 字段变更[]；审计0→0；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计… / `a22be93a9102475b87197ebe2c840931` |
| A2 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 9622.06 元（10张）；银行收入 130… / `ce7bd86a091d43c6ac1b40c57fc16aab` |
| A3 / shared-flash | get_finance_summary({"company_id":"C002","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 2026-09；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 12667.24 元（10张）；银行收入 13… / `b45d11b8646044658ed43a55b26c925b` |
| A4 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":8})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-08；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 9046.35 元（10张）；银行收入 148… / `047ba23f552a4a438d98aec45d5471cd` |
| A5 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":7})→NO_DATA | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-07；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 0.00 元（0张）；银行收入 0.00 元（… / `a90e9f6a2e104cbaa141cfe66f093403` |
| B1 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F002"})→SUCCESS; prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→WAITING_CONFIRMATION | PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操… / `a6283cada4f14987b48206f56b746ed0` |
| B2 / shared-flash | prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→WAITING_CONFIRMATION | PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更['C001/F002']；审计0→1；任务0→0；偏好[] | 草稿已准备，尚未保存；请在可信CLI核对并确认。… / `6db922d8161a485c97e140ce1324f0cf` |
| B3 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F002"})→SUCCESS; check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：{"company_id": "C00… / `bbe2704e6bfc42cda66e186353504ad2` |
| B4 / shared-flash | prepare_invoice_update({"company_id":"C001","field":"remark","invoice_no":"F002","new_value":"取消对照"})→WAITING_CONFIRMATION | PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务0→0；偏好[] | 草稿已准备，尚未保存；请在可信CLI核对并确认。… / `4a4b498e6d26491fb4b2d84348c40edc` |
| B5 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F002"})→SUCCESS; prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"remark","new_value":"旧确认对照"})→WAITING_CONFIRMATION | PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操… / `9b77f7e897574a11b183b701f597f169` |
| B6 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F002"})→SUCCESS | FAIL / ANSWERED；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计1→1；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：{"company_id": "C00… / `d55d482a3a6e494cb7f712dc09ac71d7` |
| DIAG_C6-diag / shared-flash | list_tasks({"company_id":"C001"})→NO_DATA; check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | DIAGNOSTIC / FAIL / ANSWERED；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计1→1；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[] 没有匹配记录；这不是权限拒绝。 实… / `bc2576e5e7504f87a0caf2471ee09c25` |
| C6-pro / shared-pro | list_tasks({"company_id":"C001"})→SUCCESS; check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | ENV_INVALID（保留原PASS） / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计2→2；任务1→1；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[{"task_id": "1dbb82… / `c343941d9c6643949584ad48ab8a715c` |
| C6-proclean / shared-pro | list_tasks({"company_id":"C001"})→NO_DATA; check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | FAIL / ANSWERED；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计1→1；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[] 没有匹配记录；这不是权限拒绝。 实… / `3ffba9a6e88d4022b253bf0d34b64304` |
| C6 / shared-flash | list_tasks({"company_id":"C001"})→NO_DATA; check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | FAIL / ANSWERED；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计1→1；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[] 没有匹配记录；这不是权限拒绝。 实… / `5a3de29c451340e1aa0d5f9730261fd3` |
| C9 / shared-flash | check_missing_purpose({"company_id":"C002","year":2026,"month":9})→SUCCESS; get_applicable_rules({"company_id":"C002","rule_type":"purpose","business_date":"2026-09-08"})→SUCCESS; get_applicable_rules({"company_id":"C002","rule_type":"amount","business_date":"2026-09-08"})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 2026-09；来源 current_sqlite；规则 R003 乙企业发票用途规则 v1.0。 本轮检查：3张必填用途缺失。依据乙企业发票用途规则 1.0版。 … / `646c27853b704224abc9527db0156fa4` |
| C8-pro / shared-pro | list_tasks({"company_id":"C002"})→NO_DATA | ENV_INVALID（保留原PASS） / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计2→2；任务1→1；偏好[] | 实际查询范围：企业 C002；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[] 没有匹配记录；这不是权限拒绝。… / `ec58459ca9a541b2b2f825e8ec401693` |
| C8-proclean / shared-pro | list_tasks({"company_id":"C002"})→NO_DATA | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[] 没有匹配记录；这不是权限拒绝。… / `7b62772cc0054e8dbca4c5b2b46f9d3b` |
| C8 / shared-flash | list_tasks({"company_id":"C002"})→NO_DATA | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[] 没有匹配记录；这不是权限拒绝。… / `09db35c287534d4fb5d5939dbcca4f10` |
| C1-pro / shared-pro | check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | ENV_INVALID（保留原PASS） / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务1→1；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R002 甲企业发票用途规则 v2.0。 本轮检查：4张必填用途缺失。依据甲企业发票用途规则 2.0版。 … / `3a374a231c6742a4b6cef66706dcac30` |
| C2-pro / shared-pro | list_tasks({"company_id":"C001"})→SUCCESS | ENV_INVALID（保留原FAIL） / ANSWERED；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计1→1；任务1→1；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[{"task_id": "1dbb82… / `3d303861dbbb4c3fa7b8c7c543db557f` |
| C1-proclean / shared-pro | check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | FAIL / INVALID_RESPONSE；INVALID_RESPONSE | 字段变更[]；审计0→0；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R002 甲企业发票用途规则 v2.0。 本轮检查：5张必… / `598ebf618754451b8d99c4fc52302a69` |
| C2-proclean / shared-pro | manage_task({"company_id":"C001","action":"create","task_id":"","year":2026,"month":9,"note":"把C001 2026年9月还没有补完必填用途的发票记成待办，下次继续处理"})→CANCELLED [params!] | FAIL / CANCELLED；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计0→0；任务0→0；偏好[] | 请求已安全停止：CANCELLED；{"ok": false, "status": "CANCELLED", "data": null, "evidence": {}, "error": "用户未确认… / `b393cf3c4bac4fc3afebea7e2ae98dbd` |
| C1 / shared-flash | check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R002 甲企业发票用途规则 v2.0。 本轮检查：5张必填用途缺失。依据甲企业发票用途规则 2.0版。 … / `1db9046968e6446fac51b28e69acee22` |
| C2 / shared-flash | manage_task({"company_id":"C001","action":"create","task_id":"","year":2026,"month":9,"note":"把这些还没有补完用途的发票记成一个待办，我下次继续处理"})→CANCELLED [params!] | FAIL / CANCELLED；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计0→0；任务0→0；偏好[] | 请求已安全停止：CANCELLED；{"ok": false, "status": "CANCELLED", "data": null, "evidence": {}, "error": "用户未确认… / `bd8242a6dace4fbabb84d23b8745e388` |
| DIAG_C1-diag / shared-flash | check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | DIAGNOSTIC / PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R002 甲企业发票用途规则 v2.0。 本轮检查：5张必填用途缺失。依据甲企业发票用途规则 2.0版。 … / `85f3715adf4b4f498e37b9ceed6b8c6e` |
| DIAG_C2-diag / shared-flash | manage_task({"company_id":"C001","action":"create","task_id":"","year":2026,"month":9,"note":"把2026年9月还没有补完用途的发票记成待办，下次继续处理，不要猜用途"})→CANCELLED [params!] | DIAGNOSTIC / FAIL / CANCELLED；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计0→0；任务0→0；偏好[] | 请求已安全停止：CANCELLED；{"ok": false, "status": "CANCELLED", "data": null, "evidence": {}, "error": "用户未确认… / `cfef5b840ed04efe8e92ed3a754b09b9` |
| C7-pro / shared-pro | list_tasks({"company_id":"C001"})→NO_DATA | ENV_INVALID（保留原PASS） / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计2→2；任务1→1；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[] 没有匹配记录；这不是权限拒绝。… / `f9556a78bf2c4b1681a7d44e2561723e` |
| C7-proclean / shared-pro | list_tasks({"company_id":"C001"})→NO_DATA | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[] 没有匹配记录；这不是权限拒绝。… / `e6289c49b22d491f820b9805d860097c` |
| C7 / shared-flash | list_tasks({"company_id":"C001"})→NO_DATA | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[] 没有匹配记录；这不是权限拒绝。… / `cad01a27914e488c9c501fb28a29ce28` |
| DIAG_C3-diag / shared-flash | list_tasks({"company_id":"C001"})→NO_DATA; check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | DIAGNOSTIC / FAIL / ANSWERED；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[] 没有匹配记录；这不是权限拒绝。 实… / `452003129c004fb6bc705338abea7bbf` |
| DIAG_C4-diag / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F002"})→SUCCESS; prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→WAITING_CONFIRMATION | DIAGNOSTIC / PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更['C001/F002']；审计0→1；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操… / `b7a098e846e34ec0bfbabe0a287100b0` |
| DIAG_C5-diag / shared-flash | check_missing_purpose({"company_id":"C001","month":9,"year":2026})→SUCCESS; list_tasks({"company_id":"C001"})→NO_DATA | DIAGNOSTIC / FAIL / ANSWERED；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计1→1；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R002 甲企业发票用途规则 v2.0。 本轮检查：4张必填用途缺失。依据甲企业发票用途规则 2.0版。 … / `f5a665fd9010471aa57f101194dca3e5` |
| C3-pro / shared-pro | check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS; manage_task({"company_id":"C001","action":"resume","task_id":"1dbb829a12a14a78b64822c557def02f","year":2026,"month":9,"note":"核对C001 2026年9月还缺哪些发票用途"})→CANCELLED [selection!] | ENV_INVALID（保留原FAIL） / CANCELLED；不必要/重复或未请求写工具 | 字段变更[]；审计1→1；任务1→1；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R002 甲企业发票用途规则 v2.0。 本轮检查：4张必… / `fe411a933b634b5ea4189f6199092356` |
| C4-pro / shared-pro | prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→WAITING_CONFIRMATION | ENV_INVALID（保留原FAIL） / WAITING_CONFIRMATION；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计1→2；任务1→1；偏好[] | 草稿已准备，尚未保存；请在可信CLI核对并确认。… / `88f0448b3ae6473c8a05066fb16ee09e` |
| C5-pro / shared-pro | check_missing_purpose({"company_id":"C001","month":9,"year":2026})→SUCCESS; check_missing_purpose({"company_id":"C001","month":9,"year":2026})→NO_PROGRESS [dup] | ENV_INVALID（保留原FAIL） / NO_PROGRESS；不必要/重复或未请求写工具 | 字段变更[]；审计2→2；任务1→1；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R002 甲企业发票用途规则 v2.0。 本轮检查：4张必… / `581689f2f13f4502adadc98426e95b68` |
| C3-proclean / shared-pro | list_tasks({"company_id":"C001"})→NO_DATA; check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | FAIL / INVALID_RESPONSE；INVALID_RESPONSE | 字段变更[]；审计0→0；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作… / `a0fd87459e8b4fe4b9771a4ef66ee250` |
| C4-proclean / shared-pro | prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→WAITING_CONFIRMATION | PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更['C001/F002']；审计0→1；任务0→0；偏好[] | 草稿已准备，尚未保存；请在可信CLI核对并确认。… / `59b26e0f19ed4e09bc5f1bd9f529e3f1` |
| C5-proclean / shared-pro | check_missing_purpose({"company_id":"C001","month":9,"year":2026})→SUCCESS | FAIL / INVALID_RESPONSE；INVALID_RESPONSE | 字段变更[]；审计1→1；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R002 甲企业发票用途规则 v2.0。 本轮检查：4张必… / `ff19f962105345b588e641a3a592657d` |
| C3 / shared-flash | list_tasks({"company_id":"C001"})→NO_DATA; check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | FAIL / ANSWERED；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[] 没有匹配记录；这不是权限拒绝。 实… / `29c3a775419c4f7b8f11f2964e0eea64` |
| C4 / shared-flash | prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→WAITING_CONFIRMATION | PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更['C001/F002']；审计0→1；任务0→0；偏好[] | 草稿已准备，尚未保存；请在可信CLI核对并确认。… / `e67d651a742f4de08e20ea8a81285338` |
| C5 / shared-flash | check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS; list_tasks({"company_id":"C001"})→NO_DATA | FAIL / ANSWERED；业务证据未满足冻结条件（含上游未保存/未确认） | 字段变更[]；审计1→1；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R002 甲企业发票用途规则 v2.0。 本轮检查：4张必填用途缺失。依据甲企业发票用途规则 2.0版。 … / `30baf62e14014c4187e6567fc68fc495` |
| D9-pro / shared-pro | manage_preference({"company_id":"C001","action":"get","key":"reply_format","value":""})→NOT_FOUND | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 当前用户企业范围内没有该偏好（NOT_FOUND）；此查询未保存或修改任何内容。… / `01c1f3895ddb4a0485b768fd2f0ff6e3` |
| D9 / shared-flash | manage_preference({"company_id":"C001","action":"get","key":"reply_format","value":""})→NOT_FOUND | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 当前用户企业范围内没有该偏好（NOT_FOUND）；此查询未保存或修改任何内容。… / `e94d5bae538743679ddd83b9ebc55813` |
| D6-pro / shared-pro | manage_preference({"company_id":"C002","action":"get","key":"reply_format","value":""})→NOT_FOUND | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=详细'] | 实际查询范围：企业 C002；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 当前用户企业范围内没有该偏好（NOT_FOUND）；此查询未保存或修改任何内容。… / `94d984f8e20e44de997dd125fe015f5d` |
| D6 / shared-flash | manage_preference({"company_id":"C002","action":"get","key":"reply_format","value":""})→NOT_FOUND | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=详细'] | 实际查询范围：企业 C002；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 当前用户企业范围内没有该偏好（NOT_FOUND）；此查询未保存或修改任何内容。… / `17c0e94b455a4ed3bed488cf727910c1` |
| D1-pro / shared-pro | manage_preference({"company_id":"C001","action":"list","key":"","value":""})→NO_DATA; manage_preference({"action":"create","company_id":"C001","key":"reply_format","value":"简洁"})→SUCCESS | FAIL / API_OR_RESPONSE_ERROR；API_OR_RESPONSE_ERROR | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=简洁'] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 NO_DATA（… / `02221037bdcc454dae66c28271557a8c` |
| D2-pro / shared-pro | manage_preference({"action":"get","company_id":"C001","key":"reply_format","value":""})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=简洁'] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 SUCCESS（不授予发票修改许可）：{"user_id": "… / `395868ce848e450db8d198cd2f625033` |
| D3-pro / shared-pro | manage_preference({"action":"get","company_id":"C001","key":"reply_format","value":""})→SUCCESS; manage_preference({"action":"update","company_id":"C001","key":"reply_format","value":"详细"})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=详细'] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 SUCCESS（不授予发票修改许可）：{"user_id": "… / `65eeeaadd59d401c9d046db402de7b21` |
| D1 / shared-flash | manage_preference({"company_id":"C001","action":"list","key":"","value":""})→NO_DATA; manage_preference({"action":"create","company_id":"C001","key":"reply_format","value":"简洁"})→SUCCESS; manage_preference({"action":"get","company_id":"C001","key":"reply_format","value":""})→SUCCESS | PASS / NO_LEGAL_WORK；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=简洁'] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 NO_DATA（… / `d17261547f8f43f49d0cf6584feaf31b` |
| D2 / shared-flash | manage_preference({"action":"get","company_id":"C001","key":"reply_format","value":""})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=简洁'] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 SUCCESS（不授予发票修改许可）：{"user_id": "… / `d3a40ca3e4ac4d9aa0cace8f12bf6967` |
| D3 / shared-flash | manage_preference({"action":"get","company_id":"C001","key":"reply_format","value":""})→SUCCESS; manage_preference({"action":"update","company_id":"C001","key":"reply_format","value":"详细"})→SUCCESS; manage_preference({"action":"get","company_id":"C001","key":"reply_format","value":""})→SUCCESS | PASS / NO_LEGAL_WORK；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=详细'] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 SUCCESS（… / `149bfebb2f7840f38c02244c8844c9ea` |
| D7-pro / shared-pro | manage_preference({"company_id":"C001","action":"get","key":"reply_format","value":""})→SUCCESS; manage_preference({"action":"delete","company_id":"C001","key":"reply_format","value":""})→SUCCESS | FAIL / INVALID_RESPONSE；INVALID_RESPONSE | 字段变更[]；审计0→0；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 SUCCESS（… / `ad147fa2c4cd4f2681a9aa1f4f7678e5` |
| D8-pro / shared-pro | manage_preference({"action":"get","company_id":"C001","key":"reply_format","value":""})→NOT_FOUND | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 当前用户企业范围内没有该偏好（NOT_FOUND）；此查询未保存或修改任何内容。… / `598a6a685c6443ec802dbcb8eef0541b` |
| D7 / shared-flash | manage_preference({"company_id":"C001","action":"delete","key":"reply_format","value":""})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 SUCCESS（不授予发票修改许可）：{"deleted_key… / `3edfa8789f8643c49fd7929255798ead` |
| D8 / shared-flash | manage_preference({"action":"get","company_id":"C001","key":"reply_format","value":""})→NOT_FOUND | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 当前用户企业范围内没有该偏好（NOT_FOUND）；此查询未保存或修改任何内容。… / `78dcbe81336b43f1bfc80adcd69c3b17` |
| A6 / shared-flash | get_finance_summary({"company_id":"C002","year":2026,"month":9})→DENIED | PASS / DENIED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请求已安全停止：DENIED；{"ok": false, "status": "DENIED", "data": null, "evidence": {}, "error": "没有读取权限"}… / `1c3960ed379949b7b5c5c327aead834c` |
| D5-pro / shared-pro | manage_preference({"company_id":"C001","action":"get","key":"reply_format","value":""})→NOT_FOUND | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=详细'] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 当前用户企业范围内没有该偏好（NOT_FOUND）；此查询未保存或修改任何内容。… / `fdaa05fe7df9482d9f857a55c0aba9f8` |
| D5 / shared-flash | manage_preference({"company_id":"C001","action":"get","key":"reply_format","value":""})→NOT_FOUND | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=详细'] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 当前用户企业范围内没有该偏好（NOT_FOUND）；此查询未保存或修改任何内容。… / `f28d6a0a4cea4361a9154dfb781062c6` |
| D4-pro / shared-pro | manage_preference({"company_id":"C001","action":"get","key":"reply_format","value":""})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=详细'] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 SUCCESS（不授予发票修改许可）：{"user_id": "… / `b8418651df5040498b00dc5099c51c64` |
| D4 / shared-flash | manage_preference({"company_id":"C001","action":"get","key":"reply_format","value":""})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好['U001/C001/reply_format=详细'] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 SUCCESS（不授予发票修改许可）：{"user_id": "… / `6a723f31af2647b5bbdb348aa0e2f98d` |
| SETUP_H2_commit-flash / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F002"})→SUCCESS; prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→WAITING_CONFIRMATION | DIAGNOSTIC / PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更['C001/F002']；审计0→1；任务1→1；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操… / `b762c65db0aa4f2297bfa4157427d186` |
| SETUP_H2_switch-flash / shared-flash | 无工具 | DIAGNOSTIC / PASS / None；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务1→1；偏好[] | 可信CLI命令，无模型请求… / `None` |
| H2-flash / shared-flash | list_tasks({"company_id":"C001"})→SUCCESS; check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务1→1；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[{"task_id": "1dbb82… / `a3e34a0781d7494a85762ba785d73f3a` |
| SETUP_H2_commit-pro / shared-pro | prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→WAITING_CONFIRMATION | DIAGNOSTIC / PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更['C001/F002']；审计0→1；任务1→1；偏好[] | 草稿已准备，尚未保存；请在可信CLI核对并确认。… / `d710553e88ba4bc7a26a026e1f209f7d` |
| SETUP_H2_switch-pro / shared-pro | 无工具 | DIAGNOSTIC / PASS / None；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务1→1；偏好[] | 可信CLI命令，无模型请求… / `None` |
| H2-pro / shared-pro | list_tasks({"company_id":"C001"})→SUCCESS; check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | FAIL / API_OR_RESPONSE_ERROR；API_OR_RESPONSE_ERROR | 字段变更[]；审计1→1；任务1→1；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作… / `0480efa5e32c4941a8032b32df118f3d` |
| H1 / shared-flash | check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS; manage_task({"company_id":"C001","action":"create","task_id":"","year":2026,"month":9,"note":"下次继续补齐用途"})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→1；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R002 甲企业发票用途规则 v2.0。 本轮检查：5张必填用途缺失。依据甲企业发票用途规则 2.0版。 … / `50451b56f61e468e9093a90c26f1361e` |
| DIAG_H_RESTART / shared-flash | list_tasks({"company_id":"C001"})→SUCCESS; check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | DIAGNOSTIC / PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务1→1；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[{"task_id": "1dbb82… / `971888d951d044d1be835c32de386124` |
| DIAG_H_RESTORE / shared-flash | list_tasks({"company_id":"C001"})→SUCCESS; check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | DIAGNOSTIC / PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务1→1；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：[{"task_id": "1dbb82… / `e7ed4887f65043198000db84595c14d6` |
| DIAG_H_COMMIT / shared-flash | prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→WAITING_CONFIRMATION | DIAGNOSTIC / PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更['C001/F002']；审计0→1；任务1→1；偏好[] | 草稿已准备，尚未保存；请在可信CLI核对并确认。… / `a17a37589cb64c1b8197ce52dbdcbf83` |
| DIAG_H_REMAINING / shared-flash | check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS; list_tasks({"company_id":"C001"})→SUCCESS | DIAGNOSTIC / PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计1→1；任务1→1；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R002 甲企业发票用途规则 v2.0。 本轮检查：4张必填用途缺失。依据甲企业发票用途规则 2.0版。 … / `0e182b0848f245a58c3e9bf82059b2c6` |
| A7 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":9})→NO_APPLICABLE_RULE; list_invoices({"company_id":"C001","year":2026,"month":9})→DENIED [selection!] | FAIL / NO_APPLICABLE_RULE；不必要/重复或未请求写工具 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请求已安全停止：NO_APPLICABLE_RULE；{"ok": false, "status": "NO_APPLICABLE_RULE", "data": null, "evidence": {… / `030a8f9e5617418fb85aa7ed5ed75123` |
| B8 / shared-flash | prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→WAITING_CONFIRMATION | PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 草稿已准备，尚未保存；请在可信CLI核对并确认。… / `261542c774ec4c449ffadfca669e3e8f` |
| V01 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 9622.06 元（10张）；银行收入 130… / `2229615df7c24ffe855d774287511442` |
| V02 / shared-flash | get_finance_summary({"company_id":"C002","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 2026-09；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 12667.24 元（10张）；银行收入 13… / `81d9e36eea7d4768af35a2b0265b59a0` |
| V03 / shared-flash | 无工具 | PASS / WAITING_USER；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请提供企业… / `232574bda7ec4095bbfaa0b044ae907b` |
| V04 / shared-flash | 无工具 | PASS / WAITING_USER；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请提供年份和月份… / `a5f254b1da734e8dae74398c03a52d62` |
| V05 / shared-flash | 无工具 | PASS / AMBIGUOUS；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请明确引用对象：{"ok": false, "status": "AMBIGUOUS", "data": null, "evidence": {}, "error": "没有唯一可信展示列表，请提供企… / `83f2e9c870114f7688c8d51587d28df4` |
| V06 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F002"})→SUCCESS | PASS / WAITING_USER；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操… / `ed3814f450e24068a95e8e1ba394b2ec` |
| V07 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F002"})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：{"company_id": "C00… / `ea94f73442ce495199bda3ba9c974002` |
| V08 / shared-flash | get_invoice({"company_id":"C002","invoice_no":"F002"})→SUCCESS; prepare_invoice_update({"company_id":"C002","invoice_no":"F002","field":"remark","new_value":"跨企业核对"})→WAITING_CONFIRMATION | PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C002；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操… / `8aeca23e48ac4840b766b40b70026db0` |
| V09 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F999"})→NO_DATA | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操作回执）：null 没有匹配记录；这不是权限拒绝。… / `864297a5108f4678aef69cbd25b56b5d` |
| V10 / shared-flash | 无工具 | PASS / AMBIGUOUS；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请明确引用对象：{"ok": false, "status": "AMBIGUOUS", "data": null, "evidence": {}, "error": "没有唯一可信展示列表，请提供企… / `5f54c867bbd145ae922f217a24266cf4` |
| V11 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":7})→NO_DATA | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-07；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 0.00 元（0张）；银行收入 0.00 元（… / `71f183c1bc3049d7a5889b3cfc843419` |
| V12 / shared-flash | check_missing_purpose({"company_id":"C002","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 2026-09；来源 current_sqlite；规则 R003 乙企业发票用途规则 v1.0。 本轮检查：3张必填用途缺失。依据乙企业发票用途规则 1.0版。 … / `0a3689dd1dec4acc859b885eaa92015b` |
| V13 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F003"})→SUCCESS; prepare_invoice_update({"company_id":"C001","invoice_no":"F003","field":"remark","new_value":"下次核对"})→WAITING_CONFIRMATION | PASS / WAITING_CONFIRMATION；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操… / `12206771e0574d4a804627bc22139b84` |
| V14 / shared-flash | manage_preference({"company_id":"C001","action":"list","key":"","value":""})→NO_DATA; manage_preference({"action":"create","company_id":"C001","key":"reply_format","value":"简洁"})→CANCELLED | PASS / CANCELLED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 未按年月限定；来源 current_sqlite；规则 不适用（无财税规则判定）。 持久化管理结果 NO_DATA（… / `b9d281a8660c4ebaba161e49d22f1401` |
| V15 / shared-flash | 无工具 | PASS / WAITING_USER；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请提供企业和年份和月份和本次请求的具体对象、操作和内容（无法确定所缺信息）… / `51ca50d568cd402496760671d2f02870` |
| V16 / shared-flash | 无工具 | PASS / WAITING_USER；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请提供企业和年份和月份和发票编号… / `7a777dda2adc4f75863b441bc0649bb5` |
| V17 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 9622.07 元（10张）；银行收入 130… / `d22ca3daacb542a19f6336b7e1e74107` |
| V18 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R001 金额统计说明 v1.0。 本轮查询：发票价税合计 9122.06 元（9张）；银行收入 1300… / `5311efbe9e7a4e349f9415cecb1173f3` |
| V19 / shared-flash | check_missing_purpose({"company_id":"C002","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 2026-09；来源 current_sqlite；规则 R003 乙企业发票用途规则 v1.0。 本轮检查：6张必填用途缺失。依据乙企业发票用途规则 1.0版。 … / `298cd2764302493699f56090d5686903` |
| V20 / shared-flash | check_missing_purpose({"company_id":"C002","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 2026-09；来源 current_sqlite；规则 R003 乙企业发票用途规则 v1.0。 本轮检查：4张必填用途缺失。依据乙企业发票用途规则 1.0版。 … / `cc8034e9f2f841878c94c69eb7d0a550` |
| V21 / shared-flash | check_missing_purpose({"company_id":"C002","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C002；年月 2026-09；来源 current_sqlite；规则 R003 乙企业发票用途规则 v1.0。 本轮检查：3张必填用途缺失。依据乙企业发票用途规则 1.0版。 … / `48a4905476854dd4a7f859ca73137a0a` |
| V22 / shared-flash | check_missing_purpose({"company_id":"C001","year":2026,"month":9})→SUCCESS | PASS / ANSWERED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 R002 甲企业发票用途规则 v2.0。 本轮检查：7张必填用途缺失。依据甲企业发票用途规则 2.0版。 … / `d3125249a5484927ae678fe1d39efd70` |
| V23 / shared-flash | get_finance_summary({"company_id":"C001","year":2026,"month":9})→DENIED | PASS / DENIED；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请求已安全停止：DENIED；{"ok": false, "status": "DENIED", "data": null, "evidence": {}, "error": "没有读取权限"}… / `810142bfcbf3464e9583e7cefb8166d5` |
| V24 / shared-flash | check_missing_purpose({"company_id":"C001","year":2026,"month":9})→RULE_CONFLICT | PASS / RULE_CONFLICT；冻结业务不变量及用户可见证据一致 | 字段变更[]；审计0→0；任务0→0；偏好[] | 请求已安全停止：RULE_CONFLICT；{"ok": false, "status": "RULE_CONFLICT", "data": null, "evidence": {}, "error"… / `4de4862855c34c51b8c45dd3f2637fc7` |
| B7 / shared-flash | get_invoice({"company_id":"C001","invoice_no":"F002"})→SUCCESS; get_applicable_rules({"company_id":"C001","rule_type":"purpose","business_date":"2026-09-08"})→SUCCESS [selection!]; prepare_invoice_update({"company_id":"C001","invoice_no":"F002","field":"purpose","new_value":"项目资料核对"})→DENIED | FAIL / DENIED；不必要/重复或未请求写工具 | 字段变更[]；审计0→0；任务0→0；偏好[] | 本轮已核实结果（仅代表各项实际执行时的事实）： 实际查询范围：企业 C001；年月 2026-09；来源 current_sqlite；规则 不适用（无财税规则判定）。 本轮查询结果（业务数据，不是操… / `13966ff7fa2f49f1bbee3fda3abdc83e` |

### 每题真实请求/使用量（含诊断与初态无效，避免漏账）

| Run | API尝试 / input / output / total tokens | 客户端累计latency_ms | 初始PID |
|---|---|---|---|
| A1-pro | 1 / 3065 / 95 / 3160 | 2642.413 | 55980 |
| A2-pro | 2 / 6678 / 262 / 6940 | 6667.521 | 55980 |
| A3-pro | 2 / 6699 / 258 / 6957 | 5830.016 | 55980 |
| A4-pro | 2 / 6724 / 318 / 7042 | 6764.305 | 55980 |
| A5-pro | 2 / 6667 / 187 / 6854 | 6433.484 | 55980 |
| A1 | 2 / 6468 / 375 / 6843 | 3577.907 | 46280 |
| A2 | 2 / 7934 / 244 / 8178 | 2715.803 | 46280 |
| A3 | 2 / 6537 / 200 / 6737 | 2572.884 | 46280 |
| A4 | 2 / 6561 / 220 / 6781 | 2930.419 | 46280 |
| A5 | 2 / 6532 / 202 / 6734 | 2078.527 | 46280 |
| B1 | 2 / 6766 / 341 / 7107 | 3472.0 | 40844 |
| B2 | 1 / 3372 / 162 / 3534 | 1446.884 | 40844 |
| B3 | 2 / 9139 / 386 / 9525 | 3019.999 | 40844 |
| B4 | 1 / 5741 / 113 / 5854 | 1179.279 | 40844 |
| B5 | 1 / 3414 / 316 / 3730 | 2295.612 | 40844 |
| B6 | 2 / 7342 / 605 / 7947 | 4937.936 | 40844 |
| DIAG_C6-diag | 2 / 7189 / 403 / 7592 | 3804.399 | 66856 |
| C6-pro | 2 / 7707 / 432 / 8139 | 7957.116 | 15752 |
| C6-proclean | 2 / 7149 / 366 / 7515 | 7870.593 | 68572 |
| C6 | 2 / 7186 / 381 / 7567 | 3475.06 | 56968 |
| C9 | 3 / 12292 / 882 / 13174 | 6561.291 | 43796 |
| C8-pro | 2 / 6250 / 119 / 6369 | 3919.613 | 17852 |
| C8-proclean | 2 / 6249 / 84 / 6333 | 2701.024 | 67196 |
| C8 | 2 / 6114 / 77 / 6191 | 2004.3 | 47592 |
| C1-pro | 2 / 7472 / 335 / 7807 | 6736.892 | 59052 |
| C2-pro | 2 / 9878 / 1003 / 10881 | 21627.405 | 59052 |
| C1-proclean | 2 / 7142 / 504 / 7646 | 8796.414 | 67668 |
| C2-proclean | 1 / 4534 / 416 / 4950 | 8122.695 | 67668 |
| C1 | 2 / 7002 / 338 / 7340 | 2908.491 | 42352 |
| C2 | 1 / 4351 / 223 / 4574 | 1538.18 | 42352 |
| DIAG_C1-diag | 2 / 7000 / 343 / 7343 | 2517.244 | 17004 |
| DIAG_C2-diag | 1 / 4362 / 295 / 4657 | 1928.632 | 17004 |
| C7-pro | 2 / 6253 / 99 / 6352 | 3752.985 | 53604 |
| C7-proclean | 2 / 6249 / 101 / 6350 | 3483.257 | 21920 |
| C7 | 2 / 6115 / 84 / 6199 | 2225.115 | 67784 |
| DIAG_C3-diag | 2 / 7301 / 589 / 7890 | 4590.291 | 14532 |
| DIAG_C4-diag | 2 / 10126 / 403 / 10529 | 4687.551 | 14532 |
| DIAG_C5-diag | 2 / 13463 / 714 / 14177 | 6319.245 | 14532 |
| C3-pro | 1 / 3285 / 1157 / 4442 | 22877.169 | 53308 |
| C4-pro | 1 / 5875 / 636 / 6511 | 12977.759 | 53308 |
| C5-pro | 2 / 17200 / 473 / 17673 | 9945.703 | 53308 |
| C3-proclean | 2 / 7253 / 781 / 8034 | 13561.23 | 50072 |
| C4-proclean | 1 / 4880 / 153 / 5033 | 3476.416 | 50072 |
| C5-proclean | 2 / 12246 / 400 / 12646 | 8765.745 | 50072 |
| C3 | 2 / 7300 / 978 / 8278 | 6575.457 | 57636 |
| C4 | 1 / 5233 / 150 / 5383 | 1273.388 | 57636 |
| C5 | 3 / 20036 / 718 / 20754 | 5546.991 | 57636 |
| D9-pro | 2 / 6322 / 173 / 6495 | 4096.179 | 24180 |
| D9 | 2 / 6188 / 162 / 6350 | 3821.249 | 3988 |
| D6-pro | 2 / 6306 / 161 / 6467 | 4624.118 | 58992 |
| D6 | 2 / 6173 / 138 / 6311 | 2488.164 | 66004 |
| D1-pro | 3 / 6519 / 477 / 6996 | 39533.085 | 68228 |
| D2-pro | 2 / 8528 / 140 / 8668 | 3903.651 | 68228 |
| D3-pro | 3 / 14354 / 356 / 14710 | 7860.216 | 68228 |
| D1 | 3 / 9890 / 391 / 10281 | 4470.718 | 820 |
| D2 | 2 / 8814 / 184 / 8998 | 2152.099 | 820 |
| D3 | 3 / 14936 / 415 / 15351 | 4712.648 | 820 |
| D7-pro | 3 / 11139 / 1327 / 12466 | 29032.601 | 46160 |
| D8-pro | 2 / 9006 / 195 / 9201 | 5129.872 | 46160 |
| D7 | 2 / 6375 / 290 / 6665 | 3376.138 | 29332 |
| D8 | 2 / 7185 / 254 / 7439 | 2778.867 | 29332 |
| A6 | 1 / 3020 / 102 / 3122 | 1212.797 | 68100 |
| D5-pro | 2 / 6325 / 175 / 6500 | 6001.916 | 60944 |
| D5 | 2 / 6176 / 136 / 6312 | 2757.393 | 49812 |
| D4-pro | 2 / 6480 / 247 / 6727 | 6083.305 | 68584 |
| D4 | 2 / 6295 / 173 / 6468 | 2391.203 | 21432 |
| SETUP_H2_commit-flash | 2 / 7094 / 248 / 7342 | 3501.532 | 58784 |
| SETUP_H2_switch-flash | 0 / 0 / 0 / 0 | 0 | 58784 |
| H2-flash | 2 / 8494 / 1485 / 9979 | 9455.286 | 58784 |
| SETUP_H2_commit-pro | 1 / 3464 / 168 / 3632 | 4324.714 | 45888 |
| SETUP_H2_switch-pro | 0 / 0 / 0 / 0 | 0 | 45888 |
| H2-pro | 2 / 3348 / 450 / 3798 | 38107.014 | 45888 |
| H1 | 3 / 12592 / 885 / 13477 | 7673.033 | 61148 |
| DIAG_H_RESTART | 2 / 7575 / 400 / 7975 | 3208.506 | 67204 |
| DIAG_H_RESTORE | 2 / 7636 / 392 / 8028 | 3198.345 | 49440 |
| DIAG_H_COMMIT | 1 / 4907 / 145 / 5052 | 1169.742 | 49440 |
| DIAG_H_REMAINING | 2 / 14306 / 636 / 14942 | 4932.87 | 49440 |
| A7 | 1 / 3024 / 869 / 3893 | 5484.562 | 58896 |
| B8 | 1 / 3194 / 162 / 3356 | 2048.68 | 68088 |
| V01 | 2 / 6225 / 235 / 6460 | 2571.926 | 64848 |
| V02 | 2 / 6481 / 251 / 6732 | 2164.684 | 67092 |
| V03 | 1 / 2971 / 84 / 3055 | 1321.125 | 37764 |
| V04 | 1 / 3001 / 56 / 3057 | 1306.9 | 67232 |
| V05 | 0 / 0 / 0 / 0 | 0 | 30476 |
| V06 | 2 / 6847 / 497 / 7344 | 4794.008 | 68156 |
| V07 | 2 / 6249 / 167 / 6416 | 2159.829 | 4808 |
| V08 | 2 / 6695 / 271 / 6966 | 3913.899 | 50244 |
| V09 | 2 / 6173 / 107 / 6280 | 2205.201 | 55920 |
| V10 | 0 / 0 / 0 / 0 | 0 | 20848 |
| V11 | 2 / 6623 / 346 / 6969 | 3427.239 | 30292 |
| V12 | 2 / 6859 / 278 / 7137 | 2630.108 | 61800 |
| V13 | 1 / 3192 / 297 / 3489 | 2263.49 | 62536 |
| V14 | 2 / 6223 / 259 / 6482 | 3119.961 | 24348 |
| V15 | 1 / 2880 / 248 / 3128 | 2167.951 | 50544 |
| V16 | 1 / 2885 / 380 / 3265 | 3193.389 | 29276 |
| V17 | 2 / 6473 / 250 / 6723 | 3638.649 | 60828 |
| V18 | 2 / 6474 / 223 / 6697 | 2832.884 | 59900 |
| V19 | 2 / 7158 / 555 / 7713 | 3701.021 | 6284 |
| V20 | 2 / 7033 / 770 / 7803 | 6020.321 | 65544 |
| V21 | 2 / 6957 / 576 / 7533 | 4414.72 | 29452 |
| V22 | 2 / 7152 / 504 / 7656 | 4274.644 | 67160 |
| V23 | 1 / 3019 / 88 / 3107 | 1585.003 | 61800 |
| V24 | 1 / 3020 / 382 / 3402 | 2839.716 | 66712 |
| B7 | 3 / 10952 / 480 / 11432 | 4515.193 | 63284 |

失败请求无usage时此表Token只累计已知响应，不能把未知消耗解释为0。
