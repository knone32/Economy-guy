# P1-Qwen-Max 兼容性验收

- Base SHA `f532f83c0926acf277ac599b8c3b4e3cfcaea5c2`
- Tested Code SHA `a492e902d3296adcfa116babe7506c3ad2bc5e67`
- Report SHA 为本文件的独立提交，可用 `git log -1 --format=%H -- docs/delivery/P1-QWEN.md` 核对。

## 协议

`qwen3.8-max-0902` 使用现有 OpenAI 兼容 Profile、SDK 和单 Agent Loop。仅准确匹配该快照、Provider、百炼官方 HTTPS 主机及 `/compatible-mode/v1` 路径时启用 Qwen 参数。禁止跟随重定向。标准协议和识别后的 auto 均发送 `enable_thinking=false`。可选 `qwen-thinking-preflight` 发送 `enable_thinking=true`、`reasoning_effort=low`、`preserve_thinking=false`。两种模式均不传 `thinking_budget`。私有推理在进入 Agent 前丢弃，SDK 响应回显当前凭据时安全停止。请求保持零自动重试。 [百炼 Chat Completions 接口](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)

Trace 记录实际 HTTP 状态、返回模型、协议模式和 usage。缺失用量记 UNKNOWN。DeepSeek Thinking 的历史传输协议与通用 OpenAI 的请求参数保持既有行为。

## 证据

- 红灯复现标准协议缺少 `enable_thinking`，随后合成 HTTP 回归通过。新增 7 项覆盖正式 SDK 请求序列、工具 ID 配对、非法回复、超时、重定向、权限、未确认写入保护与工作台历史隐私。
- 定向 46 项通过，含 DeepSeek、标准 OpenAI 兼容链路及原工作台会话回归。架构 2 项通过。全量 `python -m unittest discover -s tests -q`，479 项通过，0 失败。
- 验收命令已离线创建四份隔离虚构账簿，L1 预期金额和记录数经独立读取核对。真实 Qwen HTTP 尝试 **0**。L0–L5 均 **NOT_TESTED**。

## 未验证项与下一步

当前业务空间实际快照可用性、免费额度计费、线上工具选择、非流式低力度思考、用量返回以及评审环境的区域、代理、配额与模型部署均待实测。若低力度预检要求历史推理传输，先记录证据并评估隔离、脱敏和预算风险。

确认百炼业务空间与额度后，按 [真人验收 L0–L5](P1-QWEN-LIVE.md) 手动启动标准协议 L0，逐轮核对请求数和用量后再继续。
