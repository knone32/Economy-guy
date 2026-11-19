# 当前状态（仅主会话更新）

- ARCH-5 用户要求的新Live与接口职责测验已完成；暂不发人工通知、不再API，不修改产品。产品SHA c9b8948398e4e194e0e02bf226ac3d8158db43f6固定，所有旧候选/失败/账本保留，无main合并/推送。
- business-live2两新场景4输入均首执：连续办理FAIL（更正来源拒绝＋补票级联），只读语义对照PASS；全层2/4（合法待补/正确查询）。模型可观察业务槽正确，Schema参数合法；Runtime源层“同一原文业务分句”拒绝remark/季度交接待核，旧pending仍purpose/生产资料领用。后续source缺失是级联。
- root原输入/原参数/原pending只读重放ROOT-LIVE2-RESPONSIBILITY：参数validate合法，invoice_change_boundary True，invoice_value_source False；pending_transition.py:211精确SCOPE_MISMATCH。字段和值都来自原话，分句位置形式成为第二NLU控制器；UI错误又误导核企业/账期。属于职责残留，不继续加句式/Schema补丁。
- 预览/批准/提交0，所有DB业务/audit无写、无重大越权/错误事实/虚假成功放行。新runner Live没触达Mount，不能宣称旧NoMatches解决；只有零API就绪probe证据。接口职责程序14/14不算NLU。
- C正式封business-live2 REPORT/SCORES/FAILURES/FINAL-VERIFICATION/MANIFEST66文件，root ROOT-LIVE2-AUDIT独立SQL/DB/snapshot/seed/封条/连续官方ledger/tokens一致。root审计初次manifest键名差异报错仅元数据未跑业务，改兼容source_sha读取后完成，未改C原件/分数。
- 同一新架构授权12请求/180000tokens：本次新增5/42274，总9/75122，余3/104878，不追加/重置。旧C4/32848字节与ledger前4条保留，旧所有已闭账不动。
- 人工尚无登录/输入/API/预览/确认。TESTING-LEASE更新为测试已结束但人工未放行，防旧human4/32848前缀启动分叉；以后人工必须先主控同步最新business-live2 ledger9/75122再解除租约，不自动开窗口或通知。用户当前只要求先测试。
- 恢复：MISSION/STATE/EVIDENCE/ARCHITECTURE-DECISION，最新RESULT-live2.md，business-live2/FAILURES.json，evidence-business/ROOT-LIVE2-RESPONSIBILITY.json。候选不晋级；保持源码，不启动新的大型修复或其他功能。
