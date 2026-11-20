# 资料与规则来源契约

V3增加 `import_material`，正式CLI upload和工作台 `/material-upload`、`/material-update` 共同调用，
支持 docx、xlsx、文字PDF。保留原 `import_docx` 的仅Word兼容契约。所有格式均完整解析后才写入资料表，
不修改发票、银行数据或自动发布规则；同一归属的内容SHA去重，显式资料ID更新版本。

来源单元继续以 `material_id/version/paragraph_id` 唯一定位；`paragraph_id` 是通用内部单元编号，
Excel不能把物理行号直接当编号。读取回执增加 `source_type` 与 `location`，工作台显示真实来源位置：

- Word：原段编号，含空段及表格中的段落；旧版本没有location表时仍按Word原段读取。
- Excel：工作表名与原始行号，每个非空行一个单元；单元内保留单元格地址、类型与值。公式保留原文，不计算，不宣称其结果已核实。空行不入单元但不重编号物理行。
- 文字PDF：每页一个单元，页码从1开始（含空页）；不支持扫描件OCR、加密PDF或版式/表格结构还原。

文件原始字节仍保存在不可变版本中；位置通过加法新表material_locations保存，旧数据不重导。
全格式文件限10MB；Excel限制解压内容、工作表行列与累计文本；PDF限制页数与累计提取文本。
读取每次核当前用户私有归属和企业ACL。资料不共享给其他企业用户，发布规则也不授予原件访问权。

运行依赖增加pypdf（6.x）；Excel复用openpyxl。针对来源与重复/版本/权限的程序测试不等于Live或真人验收。

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

管理员可用同一CLI显式发布，`publish-rule --help` 查看完整参数。`--simulate-manager` 只在该子命令中
显式授予独立 `rule.manage`，沿用可信本地模拟管理风格，不是生产认证。模型没有发布Tool。

```powershell
python -m app.cli_materials --db temporary.db --user U001 publish-rule --rule-file rule-v1.json --material-id MATERIAL_ID --version 1 --paragraph-id 1 --simulate-manager
python -m app.cli_materials --db temporary.db --user U001 publish-rule --rule-file rule-v2.json --material-id MATERIAL_ID --version 2 --paragraph-id 1 --supersedes DOC01 1.0 --simulate-manager
```

`--version` 是资料整数版本；规则版本来自JSON。`--supersedes` 后依次传旧规则编号、旧规则版本，
明确截止旧版；省略时不会自动挑最新或停用旧版，重叠适用仍报冲突。规则JSON为UTF-8（可带BOM）：

```json
{
  "rule_id": "DOC01",
  "version": "1.0",
  "name": "甲企业用途制度",
  "company_scope": "C001",
  "effective_from": "2026-01-01",
  "rule_type": "purpose",
  "params": {"mode": "all", "threshold_cents": 0}
}
```

以上七字段必填；可附 `status`（默认 `ACTIVE`，发布必须启用）与 `content`（必须与有限参数生成的
规范正文完全一致），不接受未知字段。v2 JSON须用新规则版本及新生效日，例如 `version="2.0"`、
`effective_from="2026-09-01"`。CLI通过 `make_rule` 生成正文，复用 `publish_material_rule` 的原段归属、
企业ACL、独立管理权限、同版冲突、截止区间及原子审计；不会从Word推导公式。成功JSON回执含
`status/changed/unchanged/rule_id/rule_version/source`，source为绑定的三元原段引用；拒绝退出码为2。
重复发布同内容返回 `NO_CHANGE`，不追加成功变更审计。上传命令和上传默认不生效的行为不变。

程序验证：`python -m unittest tests.test_cli_material_publish tests.test_materials -v`，13项通过。
其中3项CLI测试实际启动独立Python子进程，验证无管理flag拒绝、显式发布与截止换版、上传不激活、
旧原段读取、幂等发布和管理flag不能绕过资料归属/正文校验；其余10项为现有资料服务测试。

验证使用临时SQLite及合成Word，不调用付费模型、不写正式账簿。工作台上传/原文对话入口由集成层接入。
