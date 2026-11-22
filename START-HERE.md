> 本包为 pending-relationships 独立修复候选，未发布。程序、冷启动和 Live 不混算；同 SHA 冷启动回执随包外附。新模型验收尚待另行授权。修复与接口见 [记录](docs/ops/PENDING-RELATIONSHIP-REPAIR.md)。

# 从这里启动当前 GUI 工作台

Windows、Python **3.11+**。这是本机演示系统，U001/U002 是受信宿主绑定的模拟账号，不是登录认证。发票、规则和银行流水均为官方虚构样例，不用于真实记账。当前入口是根目录 **START-GUI.bat**；旧 START.bat 保留原 Textual 配置／历史演示用途。

## 首次准备

在解压后的根目录运行：

```powershell
py -3 -m venv finance_agent/.venv
finance_agent/.venv/Scripts/python.exe -m pip install -r finance_agent/requirements.txt
```

依赖清单沿用 requirements.txt：openpyxl 3.1–3.x、openai 1.x、textual 1.0.0、pypdf 6.x。启动脚本优先使用 finance_agent/.venv，再检查根 .venv、py、python；可以用本机环境变量 ECONOMYGUY_PYTHON 指定已安装依赖的 Python。不会自动联网安装，也不会自动换模型。

需要**已有 Profile** 及其 Windows 凭据／原 Profile 指定的密钥环境变量。首次配置可沿原 START.bat 真实工作台的“配置 AI 模型”入口保存；不要把密钥写进命令、源码、交付包或截图。原配置文件在 finance_agent/config/model_profiles.local.json，默认不入库／不进包。已有配置在其他位置可设置 ECONOMYGUY_PROFILES_LOCAL 或使用下列参数；ECONOMYGUY_PROFILE 指定已有名称。

## 启动

双击 **START-GUI.bat**。首次从 tests/fixtures/example.xlsx 导入 data/gui-demo/demo.sqlite3，沿原初始化器建立规则，并初始化一个明确标记的 C001／2026-09 演示待办。这个待办是演示初始数据，不代表真实用户已创建任务。原会话库为 data/gui-demo/sessions.sqlite3；再次启动保留原账簿、会话和回执，不重置、不自动提交。

启动后自动打开 http://127.0.0.1:8765/。窗口保持运行，Ctrl+C 正常关闭。缺 Python／依赖／配置／密钥、目录不可写或端口被占用时保留可读提示；修好后重新启动，不要删除原账簿。若自动打开失败，复制控制台 URL 到浏览器。

```powershell
./START-GUI.bat --profile shared-flash --profiles-local "本机已有配置文件路径"
# 或绑定一个已有合法工作库；不导入、不覆盖：
./START-GUI.bat --db "已有工作库.sqlite3" --session "其会话库.sqlite3" --user U001 --profile "已有Profile"
# 端口已占用可加 --port 8766；不要并发打开同一账号／账簿会话。
```

shared-flash 是当前本机实际受测 Profile 名，不随包分发其配置或密钥；评委机器需自行配置已有 Profile。Profile 构造成功只表示配置已绑定，是否可调用以实际请求结果为准。

## 当前可演示与恢复

“待办”中点“详情”核对企业、2026 年 9 月规则与缺项，再“进入办理”。在对话中自行提出查询、选择明确发票并申请修改预览。先看清对象、期间、票号、旧值／新值和影响范围；**进入办理、待补、预览都不等于已保存**。可明确补值、暂缓、恢复或取消；保存必须本人在当前预览确认。

设置可切换已有 Profile；待补、预览、运行请求及未知提交须先处理。账号／账簿由受信宿主绑定，当前页面无登录／任意身份或账簿选择器。切换不能带入旧批准。

历史对话标为历史，不是当前账簿事实；要确认当前值请重新查询。结果未知只点“核查”，按原请求只读核实，禁止盲目重提。重启使用同一账簿与会话库恢复原状态；确认回调不跨重启恢复批准。不要以聊天保存失败推断财务提交失败。演示需新起点时自行另设 ECONOMYGUY_DEMO_DIR；不要删除或覆盖需要保留的原演示。

有限支持范围、真实受测 SHA 和程序／Live／真人证据见 [最终冻结清单](docs/delivery/FINAL-FREEZE.md)。未完成的真人验收保持待验，不迁移旧成绩。
