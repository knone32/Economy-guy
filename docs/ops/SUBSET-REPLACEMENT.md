# 完整账期子集与撤旧换新：两条失败链窄修

基线493876b，原恢复链通过保留，不重跑、不迁移为新版本成绩。证据来自用户页面page_8fc8a44a468481919d95997237aa4257的原脚本及完整35行withdraw_and_switch Trace；Trace SHA256为609e5a7609f7d1a0fba112dec428a13a5967598f4ccedd4280081b2345124b65。原ZIP校验值仅为页面声明，未下载ZIP；不能声称本地验证了ZIP字节。

## 第一项

原context-scope-probe.py在493876b复现same_scope SUCCESS、narrow_scope NOT_FOUND。ContextBuilder.begin的额外periods整表相等判断将合法完整年月对的子集判为冲突。现以完整(year,month)对作子集比较，列表/元组同义；不按年份和月份各自做笛卡尔积。子集保留原锚点，新增月份仍进入当前要求，不授予选择/写入许可。

有限正反：保留原两月展示后缩到9月，待补保留备注及月份；选8月F015拒绝且待补不丢，选9月F003 fresh后可预览。仅年月边际值相符但年月对不在原范围中，仍注销旧引用。原来源校验、成员、权限、fresh读取和确认不变。

## 原脚本运行记录

两份原脚本均已运行，原文未改。Windows下TemporaryDirectory清理时遇到未回收SQLite连接；首轮原日志保留。辅助runner只在清理前gc.collect，原业务和回包不变，完成了全部原脚本对照：拼接引文仍拒绝；只修引文的withdraw丢掉新备注；exact_and_replace保留新备注。日志位于本地evidence-root/subset-replace-493-20261122。程序重放不改原首分，不冒充Live或自然语言泛化。

第二项关系契约与语义失败后的原待补状态另行提交。冻结后仅做这两条失败链的新说法Live，不重复恢复链或结账完整链。
