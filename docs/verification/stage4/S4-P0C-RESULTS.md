# S4-P0C：脱敏逐轮证据索引

配合 [主报告](S4-P0C.md) 阅读。全部为 PUBLIC_REGRESSION；同题重复、首轮失败及实验脚本失败分别保留，不择优覆盖。`140bb14` 为第一补丁；`f6d9926` 为最终源码。所有任务/偏好写入都经现有可信CLI具体内容确认；C2-SEMANTIC 明确暂缓，绝不因表中其他测试夹具有任务而将它判为通过。

延迟为实际SDK请求合计ms；Token来自实际usage。工具列只列真实模型请求及回传状态，不含协调器只读核对。PROTOCOL_ERROR为本地B实验封装守卫；NO_PROGRESS是预算/去重停止，不能冒充业务提交失败。NOT_SUBMITTED专指发票本轮未提交，不等于偏好未保存。

## 文件哈希

- 官方虚构fixture: `edb13b2a52d2f875033258836e8fc23c3e1353c46d101184048bac289e52ed0f`
- 旧冻结S4-P-E-CASES: `2e4b400918a3874b076ead1e471a1347ef41ef263afb7d984bcb211ecec36fd8`
- 当前S4-P0C-CASES（含追加新诊断ID）: `2e38204511508ac49792539d8bef352bc9a3ea1c165e21d9f9477164a5001c6c`

H2只读对照两库初始逐字节SHA256：`387279fea3036cb19c7df0b35840eacd71325f0e238198a89dba54a755e7c92b`。预置ACTIVE任务/缺项4/审计0，明确不是自然语言创建或真实Commit成绩。C2暂缓库与它们独立。

## 全部实际用户轮次

| 代码 | Case ID / Profile | Trace ID | 工具顺序（真实返回状态） | Stop / 发票回执 | 模型/请求工具/实际Handler | Token / ms |
|---|---|---|---|---|---|---|
| 140bb14 | P11-AB_pref / shared-flash | `0123413d95394320990b77ebf136ea18` | manage_preference(NOT_FOUND) → manage_preference(NO_DATA) | PROTOCOL_ERROR / NOT_SUBMITTED | 1/2/2 | 3316 / 2381.272 |
| 140bb14 | P12-A1-AB_scope / shared-flash | `3032124821bf4cc2badaa46fa9ff206e` | 无 | WAITING_USER / NOT_SUBMITTED | 1/0/0 | 3161 / 1618.129 |
| 140bb14 | P12-A2-AB_scope / shared-flash | `d70d170a3a3c47038529ad34a013a447` | get_finance_summary(SUCCESS) | PROTOCOL_ERROR / NOT_SUBMITTED | 1/1/1 | 3310 / 1135.036 |
| 140bb14 | B6-COMMIT-b6_flash / shared-flash | `859280a5b91d4699a64d585d3fe30dbf` | prepare_invoice_update(WAITING_CONFIRMATION) | WAITING_CONFIRMATION / COMMITTED | 1/1/1 | 3421 / 1571.677 |
| 140bb14 | B6-MATCH-b6_flash / shared-flash | `101d4e2bcea84bf0b3e144766493dadb` | get_invoice(SUCCESS) | ANSWERED / CURRENT_VALUE_MATCHES | 2/1/1 | 9022 / 2935.516 |
| 140bb14 | B6-COMMIT-b6_pro / shared-pro | `6e49980e23b7447fab6139d267cf2115` | prepare_invoice_update(WAITING_CONFIRMATION) | WAITING_CONFIRMATION / COMMITTED | 1/1/1 | 3512 / 3070.836 |
| 140bb14 | B6-MATCH-b6_pro / shared-pro | `7e737707d1dd4938924ffef501fd3639` | 无 | ANSWERED / NOT_SUBMITTED | 1/0/0 | 4993 / 8780.001 |
| 140bb14 | C1-ORIGINAL-REPLAY / shared-flash | `3ce3db5d9d1443789414f0e9ef5e8b74` | check_missing_purpose(SUCCESS) | ANSWERED / NOT_SUBMITTED | 2/1/1 | 7485 / 3649.893 |
| 140bb14 | C2-ORIGINAL-REPLAY / shared-flash | `3f3744a5227a452d8519f9dcdece3b82` | manage_task(CANCELLED) | CANCELLED / NOT_SUBMITTED | 1/1/1 | 4724 / 2384.508 |
| 140bb14 | P11-pref_A / shared-flash | `f301d1fe3a174d539d6efb7753c89c99` | manage_preference(NOT_FOUND) → manage_preference(SUCCESS) → manage_preference(SUCCESS) | NO_LEGAL_WORK / NOT_SUBMITTED | 3/3/3 | 10479 / 4529.606 |
| 140bb14 | P11-pref_pro / shared-pro | `a471555832c84f428072c9d956aa5d18` | manage_preference(NO_DATA) → manage_preference(SUCCESS) → manage_preference(SUCCESS) | NO_LEGAL_WORK / NOT_SUBMITTED | 3/3/3 | 11205 / 8725.800 |
| 140bb14 | P12-A1-scope_A / shared-flash | `fb80f58a7f3c416fbacd032f36236a14` | 无 | WAITING_USER / NOT_SUBMITTED | 1/0/0 | 3143 / 1467.648 |
| 140bb14 | P12-A2-scope_A / shared-flash | `3e08abb3acd84d23be12caa1ecf719d4` | get_finance_summary(SUCCESS) | ANSWERED / NOT_SUBMITTED | 2/1/1 | 7000 / 2175.649 |
| 140bb14 | P12-A1-scope_pro / shared-pro | `0d49a65ce5084c9fb340c758403ef4ea` | 无 | WAITING_USER / NOT_SUBMITTED | 1/0/0 | 3231 / 2186.963 |
| 140bb14 | P12-A2-scope_pro / shared-pro | `c5716ff69b70467ba37591e07ce0e456` | get_finance_summary(SUCCESS) | ANSWERED / NOT_SUBMITTED | 2/1/1 | 7389 / 5442.019 |
| 140bb14 | C1-SEMANTIC-01 / shared-flash | `61b3b066fa2b4819b286a8b293f09b01` | check_missing_purpose(SUCCESS) → list_invoices(SUCCESS) | ANSWERED / NOT_SUBMITTED | 2/2/2 | 8787 / 3999.507 |
| 140bb14 | C2-SEMANTIC-01 / shared-flash | `9c981cdb30df40bdb16b5713fa8371a0` | manage_task(CANCELLED) | CANCELLED / NOT_SUBMITTED | 1/1/1 | 6114 / 2844.754 |
| f6d9926 | P11-AB_pref-R1 / shared-flash | `de461f8ba76a482084e84c528287343b` | manage_preference(NOT_FOUND) → manage_preference(SUCCESS) → manage_preference(SUCCESS) | NO_LEGAL_WORK / NOT_SUBMITTED | 3/3/3 | 10553 / 4674.439 |
| f6d9926 | P12-A1-AB_scope-R1 / shared-flash | `39df955f2b48434eb74fa49605c77eb4` | 无 | WAITING_USER / NOT_SUBMITTED | 1/0/0 | 3165 / 1506.417 |
| f6d9926 | P12-A2-AB_scope-R1 / shared-flash | `7dce9c83934c42fc81f13f0b1e081a39` | get_finance_summary(SUCCESS) | ANSWERED / NOT_SUBMITTED | 2/1/1 | 7196 / 2209.081 |
| f6d9926 | B6-COMMIT-b6_flash-R1 / shared-flash | `3e047c0f12bd4b5dbe3af6fc8de3fd2c` | prepare_invoice_update(WAITING_CONFIRMATION) | WAITING_CONFIRMATION / COMMITTED | 1/1/1 | 3425 / 2071.863 |
| f6d9926 | B6-MATCH-b6_flash-R1 / shared-flash | `8811a3aaa1a24109b53a2bee0c5368a9` | get_invoice(SUCCESS) | ANSWERED / CURRENT_VALUE_MATCHES | 2/1/1 | 9448 / 4591.505 |
| f6d9926 | B6-COMMIT-b6_pro-R1 / shared-pro | `6e1c33d8a0904549b9e70772201ec84f` | prepare_invoice_update(WAITING_CONFIRMATION) | WAITING_CONFIRMATION / COMMITTED | 1/1/1 | 3508 / 2988.511 |
| f6d9926 | B6-MATCH-b6_pro-R1 / shared-pro | `211c7d8f32d540ffb19342a9f8dce199` | get_invoice(SUCCESS) → get_invoice(NO_PROGRESS) | NO_PROGRESS / CURRENT_VALUE_MATCHES | 2/2/1 | 9381 / 6696.434 |
| f6d9926 | H2-SETUP-flash / shared-flash | `14aa919c269c4909a8344443545f6796` | list_tasks(SUCCESS) → check_missing_purpose(SUCCESS) | ANSWERED / NOT_SUBMITTED | 2/2/2 | 7879 / 3577.147 |
| f6d9926 | H2-FIXTURE-flash / shared-flash | `b87979e5cfbb47149c3a03956966fbb0` | list_tasks(SUCCESS) → check_missing_purpose(SUCCESS) | ANSWERED / NOT_SUBMITTED | 2/2/2 | 10887 / 2464.716 |
| f6d9926 | H2-SETUP-pro / shared-pro | `1aea12b30f4945eca97272dca57d2b8d` | list_tasks(SUCCESS) → check_missing_purpose(SUCCESS) | ANSWERED / NOT_SUBMITTED | 2/2/2 | 8078 / 6222.922 |
| f6d9926 | H2-FIXTURE-pro / shared-pro | `c219d10b74f34ee2897f969b371cadd1` | list_tasks(SUCCESS) → check_missing_purpose(SUCCESS) | ANSWERED / NOT_SUBMITTED | 2/2/2 | 11679 / 8979.874 |
| f6d9926 | H2-FIXTURE-ISOLATION-COMPANY / shared-flash | `f720b78cc902444da053a9e3b58d81ac` | list_tasks(NO_DATA) | ANSWERED / NOT_SUBMITTED | 2/1/1 | 6303 / 1944.012 |
| f6d9926 | H2-FIXTURE-ISOLATION-USER / shared-flash | `578baae1ecb24896b0f1cd20d24b8eb1` | list_tasks(NO_DATA) | ANSWERED / NOT_SUBMITTED | 2/1/1 | 6299 / 2174.254 |
| f6d9926 | P11-pref_A-R1 / shared-flash | `44634a0d367748de9c396a1cb6e513ee` | manage_preference(NOT_FOUND) → manage_preference(SUCCESS) → manage_preference(SUCCESS) | NO_LEGAL_WORK / NOT_SUBMITTED | 3/3/3 | 10452 / 3485.648 |
| f6d9926 | P11-pref_pro-R1 / shared-pro | `985f41d8fe4247bcad312fe618fe2e5a` | manage_preference(NO_DATA) → manage_preference(SUCCESS) → manage_preference(SUCCESS) | NO_LEGAL_WORK / NOT_SUBMITTED | 3/3/3 | 11498 / 11148.962 |
| f6d9926 | P12-A1-scope_A-R1 / shared-flash | `2fae109dc577415fb7e867765ae1db7d` | 无 | WAITING_USER / NOT_SUBMITTED | 1/0/0 | 3142 / 1637.959 |
| f6d9926 | P12-A2-scope_A-R1 / shared-flash | `64fe470f28cb40f88e2937dba36cca9b` | get_finance_summary(SUCCESS) | ANSWERED / NOT_SUBMITTED | 2/1/1 | 7079 / 2550.179 |
| f6d9926 | P12-A1-scope_pro-R1 / shared-pro | `17ddbcb6d5884924b25f131991a4f797` | 无 | WAITING_USER / NOT_SUBMITTED | 1/0/0 | 3247 / 3078.187 |
| f6d9926 | P12-A2-scope_pro-R1 / shared-pro | `168605b4d6104e83b6eac627e07c24f9` | get_finance_summary(SUCCESS) | ANSWERED / NOT_SUBMITTED | 2/1/1 | 7316 / 4866.047 |

## 对象、参数与SQL对照

- P12 A1不执行月度业务工具；补年月后的所有实际summary参数均 C001/2026/9，对照当前数据库10张/9622.06元、收入4条/13000.50元、支出8条/7180.74元、R001 v1.0。用户问题不包含正确工具名。
- 所有实际P11操作都是 C001/reply_format，create值逐字“简洁”；事先精确scripted confirmation仅批准这组对象/内容，写后get返回相同U001/C001/值。Pro负向读取是list NO_DATA，Flash是get NOT_FOUND；未将两种状态混称。
- 所有B6实际Prepare均 C001/F002/purpose/项目资料核对；可信确认绑定完整旧值/新值/request_id/指纹。每库第一次COMMITTED审计恰1条，重复轮不变；当前值独立SQL匹配。最终协调器 fresh readonly check另记update.target_checked，不能算Model调用。
- C1实查 C001/2026/9，check_missing_purpose返回R002 v2.0/原缺5；旧C2四句白名单拒绝的note为原始用户句“把这些还没有补完用途的发票记成一个待办，我下次继续处理。”。旧标准FAIL保留，零落库。
- C2-SEMANTIC-01候选、指纹与实际操作者暂缓决定见主报告；该库任务数0。CLI CANCELLED是未获确认，不是用户明确取消待办目标。
- H2所有实际工具为list_tasks(C001)+check_missing_purpose(C001,2026,9)，R002 v2.0/缺4/ACTIVE；未Prepare、未改发票、未加审计。两项隔离分别list_tasks(C001)由U002调用、list_tasks(C002)由U001调用，返回NO_DATA；已有任务确实属于U001/C001，不返回该对象。
- 活跃任务夹具只用于H2/隔离。没有用它替代C2自然创建/5→4/重启完整链。

## 独立核对方法与位置

本地只读审查脚本 `artifacts/s4_p0c/audit_delivery.py` 使用 sqlite3 的mode=ro连接，按业务日期直接 COUNT/SUM(amount_cents)，Decimal乘100对照真实工具data；不调用被测finance函数生成预期。逐一核对audit所有绑定字段及完整Draft排序JSON SHA256、新连接当前值、invoice全表仅目标purpose差异。46个requested ID与46个tool_result ID按(trace_id,id)多重集合相等；每轮budget均检查9/12/2/1上限。原始证据在本地忽略目录，不公开私有reasoning、DB、账户余额或配置。

第一次运行17用户轮/26 API；最终源码19用户轮/36 API。36轮不是36个业务PASS；旧C2策略FAIL、语义C2暂缓、第一补丁Pro B6缺核对以及B实验封装错误均列出。完整任务链仍未验证，不能据此推导所有官方场景通过。
