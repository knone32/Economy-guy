# Economy-guy 2026 初赛 v2.0.2

**双击 START.bat，选 1 运行真实系统，选 2 运行离线流程演示。**

1. 将 ZIP 完整解压到可写目录。需要 Windows 和 Python 3.11 或更新版本。首次缺依赖时，在菜单选 **3**，它会创建项目内虚拟环境并按 requirements.txt 安装依赖。
2. **真实工作台**需要可联网的模型与自己的凭据。首次进入「选择或导入工作库」→「从 Excel 创建新账簿」，使用 `tests/fixtures/example.xlsx`，保存为新的 `data/contest-demo.sqlite3`。以 U001 登录，在「配置 AI 模型」填写服务商、HTTPS SDK Base URL、模型 ID 和 API Key。发送业务消息或主动检测连接可能消耗 API 额度。
3. 建议最大化终端至至少 137 列。紧凑模式可点「查看业务历史」。
4. **离线 Mock**打开原生双栏工作台。以 U001 登录后复制屏幕上的固定示例。发票和待办写入需要在弹窗中由你确认。每次打开可继续上次的专用账簿。关闭 Mock 后，在 CMD 运行 RUN-MOCK.bat --reset 可从官方样例新建演示，旧记录保留在 finance_agent/data/mock-demo/。

- [五分钟真实工作台操作稿](docs/delivery/DEMO-SCRIPT.md)
- [设计说明](docs/delivery/SUBMISSION-DESIGN.md)
- [运行证据与录屏状态](docs/delivery/CONTEST-EVIDENCE.md)
- [技术启动参考](finance_agent/README.md)

参赛说明版本为 1.1.0。样例企业、规则和账号均为比赛模拟。发票和银行流水不能用于真实记账、付款或申报。
