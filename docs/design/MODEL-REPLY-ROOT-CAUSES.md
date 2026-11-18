# 财税模型回复与范围绑定根因

2026 年 11 月 18 日，根因核查源码固定为 `26344f08e03dc6d4391def028774bc29fdaa7f4f`。本轮按收窄方案分段实施，问题状态以定向、Live 和真人证据分别判定。

现有实现同时使用模型输出、整句字面范围和特定句式适配器决定业务含义。这三种结果会发生冲突。随机专项中，普通查询查对了数据但模型正文被替换，两项正确的单票修改提案被范围校验拒绝。需要统一模型语义记录、可信来源校验、会话接续和正文出口。

## 问题台账

下列优先级用于本轮修复排序。P1 表示业务功能或模型回复受阻，P2 表示验收方法存在缺口。六项均为 OPEN。

| 编号 | 优先级 | 功能障碍 | 根因及代码位置 |
|---|---|---|---|
| NL-01 | P1 | 普通查询和追问的模型正文被模板替代 | `Agent._ask` 在普通查询出口使用 `render_information`；通用追问调用 `render_clarification`；`finish` 再生成 `chat_notice`，工作台优先显示该字段。见 `agent.py` 1976、1961、1206，`responses.py` 986，`tui.py` 1411。 |
| NL-02 | P1 | 模型正文在追问，响应类型却是信息回答，待补状态未建立 | `parse_final` 只检查当前信封结构。模型缺少统一的未完成业务描述，运行时无法按结构化业务字段发现这类错配。见 `responses.py` 13，R02 首轮 Trace。 |
| NL-03 | P1 | 查两张只改一张时，正确提案被拒绝 | 句式适配器未命中后，`plan_invoice_change` 从整句提取所有票号，要求其与修改选集完全相等。读取对象被合并成修改对象，保留对象又与 `excluded_invoice_ids` 混合。见 `tui_intent.py` 407，`invoice_batch.py` 152、156、162–165。 |
| NL-04 | P1 | 补了票号仍丢失企业、字段或原修改内容 | 保存 `pending_intent` 同时依赖 `category=clarification` 和句式判断得到的 `invoice_write`。未被判为修改时，待补字段被缩减为企业与年月。后续提案又重新解析当前短句，未使用统一的原始意图及来源。见 `agent.py` 670、1007、1008、1016，`invoice_batch.py` 151、152、166、249。 |
| NL-05 | P1 | 部分补票查询由程序直接执行并回复 | `invoice_followup_action` 先解释自然语言，`Agent._ask` 调用 Handler 后直接返回 `finish_invoice_chain`，绕过模型循环。见 `agent.py` 486、1323、1367、1375，`tui_intent.py` 214。 |
| NL-06 | P2 | 原句回归和 API 次数容易掩盖实际语言障碍 | 固定句子可以命中适配器，业务结果正确或 API 有调用仍不足以证明模型正文进入界面、模型提案实际控制预览。需保留随机变形和逐段执行证据。 |

[Agent](../../finance_agent/app/agent.py) · [意图适配器](../../finance_agent/app/tui_intent.py) · [提案校验](../../finance_agent/app/invoice_batch.py) · [响应处理](../../finance_agent/app/responses.py) · [工作台输出](../../finance_agent/app/tui.py)

## 随机专项的实际调用链

专项种子为 `5853697061089240829`，共三组、四条实际输入。先冻结业务含义，再在发送前随机重排分句、选择等价表达并替换一个非关键值字符。企业、年月、票号和新值保持原样。此前 Live 共 8 次 DeepSeek 请求，业务通过 1/3，端到端通过 0/3。

### R01 查询正确但正文丢失

Trace `d4db62edeb294c0fafece10b2d4a5347`。

`get_invoice` 正确返回 C002 九月 F001、F009 的备注。模型随后返回合法的 `information` 信封，包含当前备注和只读说明。普通查询出口把正文换成 `render_information(read_results)`，`finish` 生成结果摘要，`TUI.finish_turn` 显示摘要。

这里的第一次丢失发生在 Agent 的输出选择，界面通过 `chat_notice` 延续了这次替换。改界面的显示字段无法恢复已经被上游丢掉的正文，需要同时修正 Agent 出口与界面消费方式。

### R02 追问状态与跨轮来源断开

首轮 Trace `4a2cf5e6617a4f4c9014c35481c4a0b0`，补充轮 Trace `c4fc39e74b2344f89a9a10a689c83f4f`。

模型查到了 F017、F018，并在正文中询问要改哪张，但把响应标为 `information`。运行时的 `scoped_edit` 未命中，`invoice_write=False`，最终按数据库查询处理，正文中的问题没有显示，`pending_intent` 也没有保存。

仅把记录中的响应类型修正为 `clarification`、补上 `missing_fields=[invoice_no]` 后，离线回放能显示追问，但 `pending_intent` 仍为空。原因是 `finish` 在 `invoice_write=False` 时，只保留企业、年份和月份等待补字段，票号被过滤掉。修正模型信封类型后仍有状态保存这一层阻断。

补充轮的模型通过历史消息理解了要求，重查 F018，并提出正确的备注新值。运行时却用当前短句重新构造修改范围。实际局部变量为 `requested.invoice_no=[F017,F018]`、`excluded=[]`、可信修改选集为 `{F018}`，模型声明保留的 F017 位于 `excluded_invoice_ids`。范围比较返回 `SCOPE_MISMATCH`。

模型能从历史读懂原要求，与运行时拥有一份可核验的待补记录，是两个不同的实现条件。当前缺少后者。

### R03 读取集合被当作修改集合

Trace `4956d4f8ec4647f98c9e194aff5d1e79`。

模型正确查询 F012、F015，并使用 F015 本轮查询返回的 `selection_id`，提出只改其备注的候选。重排后的表达未命中特定查改句式，`scoped_edit=None`。提案校验使用整句提取结果，把 `{F012,F015}` 当作应修改的集合，与候选 `{F015}` 比较后拒绝。

本次最先触发的错误是读写范围混合。错字本身没有使模型选错票号、字段或新值。

## 离线控制实验

使用冻结的生产 `Agent.ask` 回放已记录的模型响应，并按本轮真实查询重映射 `selection_id`。模型调用为录制响应回放，新增 API 请求为 0。控制实验由验收端构造正确语义范围，用于检查现有校验接口的行为。

| 控制条件 | R02 补票 | R03 查改 |
|---|---|---|
| 原始调用参数 | SCOPE_MISMATCH | SCOPE_MISMATCH |
| 仅清除非修改对象的排除参数，继续用整句范围 | SCOPE_MISMATCH | SCOPE_MISMATCH |
| 绑定正确的独立写入目标，证据只保留当前输入 | AMBIGUOUS，缺字段与新值来源 | WAITING_CONFIRMATION |
| 绑定正确写入目标，保留原请求及本轮补充 | WAITING_CONFIRMATION | WAITING_CONFIRMATION |
| 在完整范围上改成错误字段 | AMBIGUOUS | AMBIGUOUS |
| 提案月份越过已核验账期 | SCOPE_MISMATCH | SCOPE_MISMATCH |
| 使用只读或无权账号 | DENIED | DENIED |

这些结果表明，读取范围、独立写入目标和跨轮原文来源全部接通后，现有后端可以生成等待确认的候选，并继续拒绝越权和账期冲突。全部实验使用虚构临时账簿，发票与业务审计在实验前后相同，未生成实际草稿或执行提交。

## 统一解决方法

采用已收窄的[实施方案](NATURAL-LANGUAGE-REFACTOR.md)。普通查询直接使用现有工具；在既有最终信封和发票提案上按需保存待补来源、独立写入目标，保留模型正文及独立系统回执。不增加强制意图声明工具。

历史控制实验说明正确范围与原要求来源能接通现有后端，不代表新模型协议已经通过真实验证。NL-01 至 NL-06 按定向、Live、真人证据分别结算，不能因文档或局部代码完成全部关闭。

## 本地证据

- [随机专项与实际输入](C:/Users/Lenovo/Documents/ChatGPT/economyguy/randomized-language-baseline-26344f0-20261118/summary.json)
- [发送前随机变形记录](C:/Users/Lenovo/Documents/ChatGPT/economyguy/randomized-language-baseline-26344f0-20261118/mutations.jsonl)
- [生产 Agent 离线回放及控制实验](C:/Users/Lenovo/Documents/ChatGPT/economyguy/reply-root-cause-analysis-26344f0/probe-results.json)
- [历史真人 Trace 核查](C:/Users/Lenovo/Documents/ChatGPT/economyguy/historical-human-trace-audit/summary.json)
