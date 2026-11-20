# 助手与共享能力入口

工作台 F5 选择当前账号的助手。每轮读取当前配置；分发工具时再读配置和Tool停用状态。
助手范围只缩小能力，不扩大用户企业ACL，不绕过正式发票确认。助手与Skill配置按账号隔离。
`use_skill`记录模型所选共享流程版本，随后仍需实际业务工具读取；其结果不提供金额或提交证明。
停用Skill不取消独立业务Tool，停用Tool则拒绝旧调用。

本地管理命令（可信模拟管理入口，无模型请求）：

```powershell
python -m app.assistant_cli --db 隔离.db --actor U001
python -m app.assistant_cli --db 隔离.db --actor U001 --simulate-manager --kind skill --id missing --body-file skill.json
python -m app.assistant_cli --db 隔离.db --actor U001 --simulate-manager --kind assistant --id query --body-file query.json
```

skill.json：
```json
{"name":"查发票缺项","tools":["check_missing_purpose"],"steps":["按企业和业务日期查适用制度","列缺项并给制度版本和出处"]}
```

query.json：
```json
{"name":"查询助手","tools":["use_skill","get_invoice","check_missing_purpose","get_applicable_rules","list_materials","open_material_reference"],"skills":["missing"]}
```

补录助手用新ID `edit`，相同Skill，tools另加 `change_invoice`。修改配置传上次revision；例如更新Skill v2加 `--revision 1`，停用v2传相同body加 `--revision 2 --disable`。两个既有会话下一轮刷新。Tool配置以注册Tool名为ID、body为 `{}`，不可上传任意代码或自报处理器。

资料操作在工作台输入（路径用正斜线并加引号）：

```text
/material-upload C001 "C:/资料/制度.docx"
/material-update C001 资料ID "C:/资料/制度v2.docx"
/materials C001
/source 资料ID 1 3
```

上传不发布制度。正式发布需 rule.manage 的既有可信入口，详见 MATERIAL_RULE_CONTRACT.md。
当前只承诺Word原段。Excel首次建账沿用；Excel资料原行、PDF页码、企业共享原件未完成。

程序证据：tests.test_assistant_config、tests.test_materials；尚不代表陌生自然语言或真人确认已验。

暂缓单票与新聊天续办：

```text
/pause
/pending
/resume 候选ID 修订号
```

列表只显示当前账号、当前账簿重新核权后的有效事项；有多个候选需显式选择。
恢复的是未保存业务要求，旧预览与旧批准不会恢复；继续给出用户补充后重新读票、正式预览。
取消退出可续列表，提交后转为回执。较旧窗口修订不能覆盖新修订或取消。
