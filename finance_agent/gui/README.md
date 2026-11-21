# 最小本机 GUI

## 运行

在 `finance_agent/` 目录：

```powershell
python run_gui.py --db <已有工作库.sqlite3> --user U001 --open
```

默认使用本机 `conversations.sqlite3`（与 TUI 相同），绑定 `127.0.0.1:8765`。
需要已有本地模型 Profile 才能发消息；可用 `--profile <名称>` 指定。
如果 Profile 不在默认 `config/`，可加 `--profiles-local <路径>`；密钥从 Windows
凭据管理器或 Profile 指定的环境变量读取，不打印、不写入页面，也不启动第二个
Agent Loop。

## 当前接通范围

- 工作台导航：**对话 / 待办 / 设置**；保留原三栏对话页。
- 对话：会话列表、新建/切换、聊天、真实工具结果卡、当前待补/暂缓、可恢复候选。
- 待办：分开显示业务缺项与 PAUSED 修改；业务缺项可去对话补充/暂缓/取消，
  暂缓修改可恢复/取消暂缓；其他持久待办只读，不放假办结按钮。
- 设置：当前账号、账簿、模型连接状态和原配置目录的已有 Profile 清单；
  选择 Profile 只生成下一次启动命令，不热切换账号/账簿/模型（Sol 宿主缺口）。
- 发送消息：只调用 `SessionHost.send_message`；内部唯一 `Agent.ask`，结果和
  卡片来自本轮真实 Handler 证据。
- 单票预览：`change_invoice` 形成候选后，`SessionHost` 的确认回调交给原
  `WriteCoordinator`/`prepare_invoice_update`；GUI 只展示，不自行 Prepare。
- 真人确认：浏览器只提交 `preview_id` 和绑定上下文；草稿/指纹在宿主，
  确认由 `SessionHost` 交回原 `Agent.commit_update`。客户端不传
  `approved`/`confirmed`。
- 查询后续办：页面真实渲染结果后自动调用 `SessionHost.acknowledge_display`；
  未登记前宿主拒绝下一轮；GUI 不另存引用。
- 确认超时：宿主回调句柄失效即清空；页面轮询/刷新关闭可操作弹窗、解除忙碌，
  显示“未批准/未提交”；旧按钮只触发失效冲突并刷新，回调句柄不持久化。
- 提交回执与聊天历史保存分开显示；未知结果只提供只读核查。
- 会话切换、新建、暂缓、取消、恢复候选：只调用 `SessionHost`，由原
  `SessionStore` 和原候选修订持有。

## 明确未接入

- 批量/规则/复杂多票预览：当前界面只支持单票预览；多票会拒绝生成预览，
  不伪造批量审批。原批量入口仍由后端持有。
- 远程访问、生产登录、外网身份认证：没有；仅本机受信宿主。
- 聊天历史保存失败/提交结果未知的自然故障：只有程序路径，未做真实服务故障验收。
- 真实模型 Live、真人完整 GUI 可读性、重启恢复的最终签收：未执行。

## 边界

界面没有修改 Agent、SessionHost、SessionStore、候选修订、ACL、Prepare/Commit/
审计或业务判定；只增加 `SessionHost` 投影、异步确认桥和本地 HTTP/HTML 适配。
浏览器不能把模型正文、`approved=true` 或客户端保存状态当作业务事实。当前
`session_host.py`/`session_store.py` 的 display-ack 与超时契约由 Sol 保持不变；
GUI 只消费该接口，最终冻结 SHA 见仓库当前提交。
