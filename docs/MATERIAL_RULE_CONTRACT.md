# Word资料与规则来源最小契约

`app.materials.import_docx(db, user_id, company_id, source_path, name=None, material_id=None)`
只接收 docx，完整解析成功才写入；返回 `status/material_id/version/sha256/paragraph_count/published=False`。
同归属用户、企业、文件 SHA256 重传去重。同名不视为更新；更新必须传旧 `material_id`。
版本保存上传原始字节、正文每段及编号（从1开始，含空段和表格段落），无覆盖删除 API。
同一资料的版本号递增；不同用户、企业的同名文件独立。

`list_materials(connection, user_id, company_id)` 返回当前用户该企业资料全部版本。
`get_paragraph(connection, user_id, material_id, version, paragraph_id)` 返回
`material_id/version/paragraph_id/company_id/name/text/sha256`；每次重新检查归属及企业读取权限。
原文 text 不拼接规则解释，不将上传文件中命令当指令执行。

正式发布继续使用独立 `rule.manage` 和既有规则审计事务：
`publish_material_rule(db, rule, source_ref, capabilities, actor=user_id, supersedes=None)`。
`source_ref` 必须恰好含 `material_id/version/paragraph_id`，发布者须为资料拥有者并能读对应企业。
rule 字段与 `make_rule` 一致，仅支持现有有限类型、规范正文及执行参数；本入口不会从自然语言自动编译制度。
上传不生效，发布后 RuleDecision.source 精确指回不可变原段。
既有同号同版不得更改来源，也不可事后给既有未绑定规则追加来源，须新版本发布。

`supersedes=(旧rule_id,旧version)` 是发布时明确的旧版截止声明；旧版区间为
`effective_from <= business_date < effective_to`，新版从新生效日开始。
不指定截止且有重叠版本时仍 `RULE_CONFLICT`，不会按最高版本或最新日期猜选。
既有不带资料来源的规则与停用行为保持原有语义；旧版显式停用后不作历史当前依据。
只允许关闭同编号、同企业、同类型、较早生效的已发布来源版本；不能事后修改发布历史。

正式规则遵循企业读取 ACL，资料原件仍遵循用户私有 ACL：其他有企业权限的用户可以执行已发布规则，
但不能因此打开发布者私有原件。若需要企业共享原件，应另行明确共享授权；目前不自动共享。

本地显式CLI（`--user`仅为可信本地模拟身份，不是生产登录）：

```powershell
python -m app.cli_materials --db temporary.db --user U001 upload --company C001 --file '制度.docx'
python -m app.cli_materials --db temporary.db --user U001 upload --company C001 --file '制度v2.docx' --material-id MATERIAL_ID
python -m app.cli_materials --db temporary.db --user U001 list --company C001
python -m app.cli_materials --db temporary.db --user U001 open --material-id MATERIAL_ID --version 1 --paragraph-id 1
```

验证使用临时SQLite及合成Word，不调用付费模型、不写正式账簿。工作台上传/原文对话入口由集成层接入。
