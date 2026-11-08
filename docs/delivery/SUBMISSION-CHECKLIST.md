# Economy-guy 初赛验收与提交清单

## 官方通知

| 项目 | 已核对信息 |
| --- | --- |
| 报名截止 | 2026-11-12。[主办方官网](https://aicxds.yunzhangfang.com/) |
| 初赛作品截止 | 2026-11-13。[主办方官网](https://aicxds.yunzhangfang.com/) |
| 初赛统一跑测模型 | 千问 Qwen3.8-Max。[主办方初赛冲刺公告](https://m.saikr.com/contest/notice_detail/50275) |
| 提交入口 | 赛氪已报名赛事的「报名管理」。具体时间、上传字段、格式、大小及命名以赛题资料和登录后的平台实际要求为准。[主办方提交答疑](https://m.saikr.com/contest/notice_detail/50056) |

## 已实现且有证据

| 检查点 | 证据 |
| --- | --- |
| 默认工作台、虚构账簿导入、加法升级、规则初始化、发票目录与详情、待办读取 | [工作台指南](P0-AGENT-WORKSPACE.md)、[P0 离线验收](P0-FINAL-CLOSURE.md)、[本轮清洁环境检查](#submission-r1-复核) |
| 模拟账号、明确范围、确认、事务审计和回读；任务跨进程恢复 | [P0 合成 HTTP / Pilot A/B/C](P0-FINAL-LIVE-ACCEPTANCE.md)。模型提案与确认由验收驱动提供。 |
| 历史 DeepSeek A/B/C | [SEC-B4](../verification/security/S4-SEC-B4.md)，被测 `e834bbb961030c0671d788bc629026031078f743`。A/B/C 均为 PARTIAL，分别保留追问、重复回执和任务下一步展示限制。[S4-BR](../verification/stage4/S4-BR.md)，被测 `bde7ec7bb7ca5f2a2460faade82e817b4302d6ef`，增量 B2、预置任务 C5 和偏好回读通过，A 自然收尾仍为 PARTIAL。 |
| P0.5 DeepSeek 查询焦点、连续多轮、重启和偏好 | [P0.5 真体验收](P0-5-FINAL.md)，运行于 `769a4e7cae8b91e41ba802267e78240a121bf608`，生产实现为 `b7b57ea19742c026921c42a14c337a6c9c70660d`。17 次真实请求，L1–L3 PASS，L4 PARTIAL。偏好保存、回读和恢复输入已核实，简洁表现未达该次测试阈值。 |
| Submission-R2 真实 DeepSeek | [R2 实测报告](SUBMISSION-R2.md)与[一页讲解](SUBMISSION-R2-EXPLAINED.md)。A、B（模拟确认）及 D 取得证据。C 持久化、重启与当前进度通过，C5 单轮完成情况说明仍为 PARTIAL。 |

## 已实现但待最终验收

- [ ] 复核 C5 在同一答复中说明 F002 已补齐及剩余 4 张，单独见证真人确认。R2 已用真实模型、隔离账簿和 Textual Pilot 执行 A/B/C。
- [ ] Windows Terminal 实机检查启动、中文显示、键鼠与确认弹窗。Textual Pilot 与脚本验证分别保留。
- [ ] 获取官方授权的评审环境后预检 Qwen3.8-Max 的工具调用及回复协议。现有 DeepSeek 结果仅覆盖各自的被测版本与场景。
- [ ] 录制最终演示并核对实际展示范围、运行命令、截图与证据摘要。时长及格式按最终平台说明准备。

## 需在提交平台完成

- [ ] 核实正式报名、参赛资格、队伍信息和赛题二选择。
- [ ] 按平台要求准备作品文件。确保评审可获取对应提交的源码及依赖声明，附[运行首页](../../README.md)与[设计说明](SUBMISSION-DESIGN.md)。
- [ ] 提供要求的演示材料及必要运行证据。附件仅含允许分发的文件及脱敏摘录。
- [ ] 在「报名管理」提交，重新打开页面核对版本、附件和提交状态，保存成功回执。

## Submission-R1 复核

基线 `3491eaf08d62af4198a4e1184f1092c17616ae41`。本轮真实模型 API 请求 **0**。

- 使用独立 Git 源码副本和全新 Python 3.12.14 虚拟环境。仅安装 `requirements.txt`，`pip check` 通过。实测 Textual 1.0.0、OpenAI SDK 1.109.1、openpyxl 3.1.5。
- 运行指南的显式和默认 Excel 导入均通过，各导入 2 家企业、2 个模拟账号、40 张发票、48 条银行流水。旧结构依次加法迁移并初始化 5 条种子规则。空待办返回 `NO_DATA`。
- Textual Pilot 经默认启动入口打开首次设置，完成虚构账簿导入、规则初始化、U001 登录及待办导航。全量用例另覆盖旧库备份升级、U002 权限、目录分页、发票详情、跨进程任务回读。
- `python -m unittest discover -s tests -q` 在清洁副本和开发源码目录各通过 **432 项**，零失败、零跳过。单独运行架构测试通过 **2 项**。`scripts/demo_stepper.py --mode mock --scenario all` 的 A/B/C 全部通过，退出码 0。
- 本轮工作库、测试库和演示证据均分离，开发工作库 SHA-256 前后一致。交互结果来自 Pilot 和离线演示，Windows Terminal 实机及真实模型验收按上方清单跟踪。
