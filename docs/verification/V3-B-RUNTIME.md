# V3 B：单票恢复与原全量失败调查

起点 `718d8121ba0327c8ccf5b105046f1294eb8c7bdf`；B独立工作区 `business-20261120/v3-b-runtime`。以下均为零API程序证据，非自然语言、Live或真人批准成绩。

## 已复现并修复

工作台恢复单票候选会通过CAS认领新修订，旧修订和批准立即失效；但 `resume_invoice_selection` 原来显示用户提供的旧修订。真实Textual测试观测SQLite token为修订3而页面为修订2。页面现在读取会话存储返回的真实token，不重复计算修订，也不改变CAS或批准逻辑。

新增测试同时验证页面显示新修订、旧修订恢复失败、尚无Agent批准和成功审计为0。修复前失败证据和修复后程序日志保留在本工作区 `artifacts/v3-b/`。定向38项通过（39.232秒），包含单票业务来源、改口、取消、跨进程恢复、权限、未知提交结果核实、幂等和架构测试。集成后完整回归由根总控在唯一候选执行；这不关闭原全量失败。

## 原215条失败的调查边界

原日志 `../evidence-root/final-718d812-full.log` SHA256：`cac4379f409af47e1ee86ecb2ceca93d4d74fdf4f0a78b7ea6df70e8b5b7d8f8`。182 FAIL、33 ERROR原成绩保持不变。

逐条表、原日志行号、调查族、归因等级及理由：`artifacts/v3-b/regression-triage.md` / `regression-triage.json`；可用同目录 `triage.py`重建。1条完成独立诊断复现，56条仅静态推断，158条仍未归因。调查族仅分配排查方向，不能作为失败已关闭的证据。

- 终端机制独立对照：110列登录弹出 `TerminalWidthNotice`；未处理告知窗时Enter产生0条记录/0次模拟调用，明确继续紧凑模式后产生1条记录/2次模拟调用；150列直接正常发送。旧110列用例的helper仅检查登录用户，未处理这层告知。45条布局/模态候选仍需逐例确认，不能全部改判环境。
- SDK替身独立对照：旧MagicMock响应未设置 `response.model`，非字符串Mock进入脱敏序列化并导致 `ModelRequestError`；仅为替身补上真实字符串后成功。此诊断不调用网络、不修改原测试；其他协议错误仍需逐例检查。
- 旧 `propose_invoice_changes(action=request)` 与当前 `change_invoice`增量契约有明确冲突；当前契约明确拒绝旧Schema。旧值echo与显式 `value_ref=previous` 的差异同样不能以恢复废弃行为刷绿。

未放宽或删除任何旧断言；未触碰正式库、原成绩、C保留题、main或远端。当前来源/取消/恢复专测没有发现可复现的越权或未确认写入，但不能外推任意自然语言或真人链已通过。
