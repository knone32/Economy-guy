# 跨月范围与事项候选恢复（有限离线验收）

基线3a5a3f7；当前修复分支fix/2026-11-22-pending-relationships。不调用模型，不重跑F014或结账完整链；保留3a5a3f7的Live原成绩和所有失败原件。

## 第一项：跨月共同范围

同次真实展示包含8月F011与9月F001，锚点仅证明共同企业和年份。当前原话明确9月及备注时，旧绑定器访问不存在的reference_scope.month而异常。修复按共同存在的槽位核对，不清空无冲突来源；独立的唯一共同年份可与当前唯一月份配对，不能把整个跨月集合当成修改月份。

程序回归test_scope_candidate_restore.CrossMonthScopeTests：未选票保留2026-09、备注与原集合，零单票读取/预览；随后选择8月F011返回SCOPE_MISMATCH且月份/备注不丢；再选9月F001 fresh读取后预览原备注要求。发票/审计逐行不变。CROSS-MONTH-BASELINE.log保留KeyError原失败，AFTER通过。最早BEFORE日志为夹具使用多月SQL快照而无法登记单月锚点，修正为两次真实单月读取同次展示，不计产品首错。

本地原始日志位于evidence-root/scope-resume-3a5-20261122。事项恢复另行收口；最终源码SHA、同版回归记录与新ZIP由冻结清单绑定。仅程序证据，不迁移Live或真人成绩。
