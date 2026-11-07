# 财税 Agent 命令行主页

在 PowerShell 进入 `finance_agent`，使用 Python 3.11 或更新版本。首次安装依赖后直接启动。

```powershell
python -m pip install -r requirements.txt
python main.py home
```

输入数字打开菜单。输入 `0` 返回上一级，在主页输入 `0` 退出。`/home` 返回主页，`/cancel` 取消当前操作，`/quit` 退出。Ctrl+C 可中止当前输入。最终确认提示中，只有完整确认语句会提交。

1. **Excel 导入与工作库**（主页 4）。选择已有工作库，或填写官方结构的 `.xlsx` 和一个全新库路径。导入检查企业与用户、发票、银行流水及说明表，展示行数，完成迁移和规则初始化后才发布。按提示输入 `switch` 切换。默认新库进入 `data/workspaces/`。旧库可在这里明确确认加法升级。
2. **用户与权限**（主页 2）。选择标有 `SIMULATED_IDENTITY` 的模拟用户，查看企业读取和修改权限。任务、偏好按当前用户和有读取权限的企业查看。
3. **Profile 设置**（主页 5）。查看可见 Profile、HTTPS 端点、Provider、模型和 Key 就绪状态。可新增当前用户的 User Profile，选择当前会话 Profile，或跟随环境和配置的默认项。配置文件只保存环境变量名。交互终端可隐藏输入尚未设置的 `API_KEY` 或 `*_API_KEY`，只保存在当前进程。配置检查和 Key 就绪都可离线完成。实际联网结果在 Live 对话后可查看。
4. **Agent 智能对话**（主页 1）。默认 Mock 使用固定的 C001 2026-09 查询响应。选择 Live 并配置可见 Profile 及 Key 后，发送消息才调用真实模型。输入自然语言查询，或输入 `1` 后描述发票修改目标及新值。任务和偏好可直接用自然语言提出。核对实际草稿和候选后，按界面要求输入完整确认语句。
5. **历史记录与审计**（主页 3）。查看当前会话的脱敏交互摘要、本人且仍有企业读权的成功发票审计，以及持久任务和偏好。规则操作审计需要独立模拟管理员入口。旧 Trace 仅作为执行日志保存，持久会话摘要和检索留待 S4-UX-B。
6. **规则与管理**（主页 8 和 6）。普通模拟用户可按可读企业、类型和业务日期查看适用规则。高级管理员入口需明确输入 `admin`，显示 `SIMULATED_ADMIN`。规则导入、停用及 Global Profile 新增均须核对预览后确认。模拟用户新增、禁用和 ACL 修改留待 S4-UX-B。
7. **交互演示**（主页 7）。选择 Mock 或 Live 和场景后进入独立演示器。Live 需选择对演示身份可用的 DeepSeek Flash Profile。演示使用独立虚构库，确认标记 `SIMULATED_TEST_USER`。

原 `python main.py --help` 和 `chat`、`summary`、`init`、`profiles` 等子命令仍可使用。
