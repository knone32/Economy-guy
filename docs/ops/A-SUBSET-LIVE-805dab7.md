# 805dab7 同版 A_SUBSET Live 回归

业务受测版本：`805dab7b1460b037ab8f7e94260882b5cac0c6ff`。本轮不改 `finance_agent/`；后续提交只归档计量工具和本记录。原始失败均保留，不重跑恢复或改口链。

|步骤|结果|
|---|---|
|两票分别交付、展示ACK|通过；两项完整，正式事实末答，无旧矛盾限制语|
|缩到2026年9月、等待选择|通过；原候选集合和备注“业务资料核验完毕”保留，无猜票和预览|
|仅发F012|未预览，要求核对；9月、备注和原集合保留|
|仅发F005|失败；模型调用change_invoice只有invoice_no=F005，Runtime返回NOT_FOUND：“原展示集合已失效，请重新查询。”|
|取消|未到达；不伪造CANCELLED|

首个可见工具拒绝在 `live-805dab7/A_SUBSET/trace.jsonl:87`；当前只确认引用集合失效，没有把它归为模型不懂票号，也未继续改业务代码或重复Live。正确选择前的Context日志和待补引用留在原件中，集合失效的具体触发点需后续独立定位。

本次7个物理请求均有回执，58,507 tokens，保守价格上界0.141564元（不是服务端账单）。无重抽、无批准、无提交；发票和修改审计逐行不变。程序ACK及预览观察不能代替真人GUI验收。

## 计量续行

新增薄适配 `tools/v3_shared_budget_unknown.py`：只对用户明确登记、摘要吻合的历史pending/unknown请求允许继续无累计上限执行。历史记录不改、不清账、不补造usage/receipt；已知部分继续使用原校验器逐笔核验。未知1次单列预留49,309 tokens／147,770 micro-CNY，这不是实际用量或已知费用。新失败或未登记未知仍停止，需要单独核对，不能静默升级成已知成功。

`tools/v3_live_guard_unknown.py`保留原模型、地址、源码/配置哈希、重试禁止和单轮限制；适配器本身也受哈希校验。真实账本、凭据、原始Trace、SQLite及ZIP不入Git。

本地原件：`business-20261120/evidence-root/paired-target-6ea-20261122/live-805dab7/`；摘要：`LIVE-805dab7-SUMMARY.public.json`；计量检查：`ACCOUNTING-CHECK.public.json`。历史源码ZIP仍对应805dab7，未替换字节。
