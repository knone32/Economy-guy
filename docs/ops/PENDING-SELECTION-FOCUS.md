# 待选对象与上下文焦点交接

基线0c56bea（业务805dab7）；保留原Live CHOOSE失败。805dab7原Trace第47/56行把仅提及的F012放入通用焦点，第63行owner却仍缺票号；下轮F005在Context.begin触发票号冲突并注销集合，第87行仅是原集合失效的后果。本轮只修此处交接，不改SQL证明器、不重跑恢复/改口链。

## 窄修边界

Agent仅在当前账号/账簿的原单票owner持有集合、缺票号、没有已选票号、没有暂缓/阻塞且引用未被禁止时，要求Context暂不登记票号焦点。候选原话仍交原owner；企业/月份冲突及reset原样处理，不复活失效引用，不增加状态owner。

原回包进一步揭示：F005的独立动作只声明继续事项，没有value_relation；在集合恢复有效后，原bind_request要求重述内容关系而拒绝。现仅对原待选集合的裸票号补充、可信展示已解析该联合身份、无字段/值/关系改动提案、原内容仍有效的情况，沿原verified_pending继承；含其他正文、新值、换字段、替换/清空/撤销仍需独立语义及来源。不是把continue当成保留全部条件的授权。

## 有限证据

本地evidence-root/pending-selection-focus-20261122：BEFORE.log保留原复现；AFTER-original/diagnostic保留中间拒绝；AFTER-owner.log原七条model_reply未改重放通过。原F012轮是结构化澄清、零工具调用，不能称作fresh读票后拒绝。最终F005确有原owner fresh读取，只预览备注，程序取消CANCELLED；发票/审计未变。

NEGATIVE-outside、NEGATIVE-invalidated记录集合外选择拒绝、注销集合不复活。FOCUSED.log为受影响入口1项及架构2项通过。原回复重放及反例均为程序证据，不改原Live首分。冻结后仅一条同版A_SUBSET Live，首错停止；真人批准不代点，当前仅预览后取消。
