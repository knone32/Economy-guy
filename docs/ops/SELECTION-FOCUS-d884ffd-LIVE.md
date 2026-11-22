# d884ffd 待选焦点修复验收

产品受测SHA：`d884ffd7b62d5a97dfa5b8bc96f135891c3cdb3b`。本轮保留805dab7原失败，不改SQL证明器，不重跑恢复链/改口链。

程序：原805dab7七条model_reply原样本地重放，F012直接结构化澄清、零工具调用，不再成为通用焦点；F005沿原集合、月份和备注，由owner fresh读取后只预览备注，程序取消CANCELLED。集合外票号仍拒绝，主动注销引用不复活。受影响入口1项及架构2项通过，均为程序证据。

Live仅一次已知失败链回归：QUERY两项目标完整交付及展示ACK通过；NARROW独立阶段表达continue/await_selection及新备注、展示集合关系（Trace33行），但执行模型请求未暴露的query_business_sql（41行）。实际暴露的10个工具不含SQL；Runtime按原权限拒绝（44行）。首错停链，未重试。F012、F005、预览和取消均未到达，不能把程序CANCELLED算作Live，也不能据此证明焦点修复Live成功或失败。

3次物理请求全部有回执，22,951 tokens，保守费用上界0.045510元，非服务端账单。原账本前缀未变；旧未知1次及49,309 tokens／147,770 micro-CNY预留继续单列，未清账或另建账。无新未知、批准或提交，发票/审计逐行不变；真人GUI未验。

同版源码ZIP共367个文件逐个与Git blob一致，SHA256：`37bddef480a4a4773716ce1b8712f26d499f08a0c1fc25583666f99118976e9a`。本地evidence-root/pending-selection-focus-20261122含原重放日志、负例日志、FOCUSED.log、FROZEN.public.json及live-d884ffd原始证据；原件、账簿、凭据与ZIP均不入Git。后续文档提交不冒充产品受测SHA。
