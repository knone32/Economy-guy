# A 查询与事实交付

分支 `sprint/2026-11-20-query`，起点 `b002eeaa93e3d13e7c0f669a417ebb12fcd86452`。未推送，未调用付费模型，未读取 C 封存题。

## 首错与第一切片

用户报告的“数字正确但漏交易日期依据”尚未定位到新 Dot 原始 Trace；本次仅将其作为问题线索，**不声称已找到该真实 NLU 首错**。

正式 `Agent.ask` 的程序复现保留在 `finance_agent/artifacts/a-query/basis-before-utf8.log`：3 项首红分别为模型选中银行收入/发票合计、选中完整汇总时均丢失日期归属，以及选中适用规则时丢失生效日期和官方出处。SQLite 数字及版本正确。首次偏离在 `answer_evidence.catalog` 的 summary scalar 和 `responses.render_information`：已有 `render_summary_basis` 未被这两条事实交付路径使用；`render_scope` 又以年月遮掉工具返回的精确 `business_date`。

最小修复：汇总指标绑定当前结果生成的 `basis_ref`，最终选择及有限比较/求差携带父事实依据，同一依据只附加一次；整份汇总复用原日期口径说明。适用规则/缺项结果保留当前 RuleDecision 返回的生效日期与 explanation；精确规则业务日期不再被年月遮掉。模型继续选择指标、顺序和比较操作；没有新增意图调用、关键词/同义词/固定句式或金额票号特判，没有改变 ACL/确认/提交。

## 程序检查

环境：`C:/Users/Lenovo/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`；`PYTHONPATH=C:/Users/Lenovo/Documents/ChatGPT/economyguy/reliability-v2-20261119/runtime-deps`，`PYTHONIOENCODING=utf-8`。以下命令均从 `finance_agent/` 运行。

`python -m unittest tests.test_answer_evidence tests.test_typed_delivery tests.test_route1_evidence_contract tests.test_architecture -v`：**37/37 PASS**。证据 `artifacts/a-query/basis-related-final.log`。覆盖正式 Agent、当前引用/伪标签/跨轮/未知 SQL 拒绝、相同指标比较与异指标差额、规则日期/来源、以及 Textual 工作台实际输入到 chat-log 的日期依据交付（140×34；审计仍 0）。均为脚本/Mock 机制证据，不算 NLU 或 Live。

保留的初始工作台测试失败：`basis-related.log`、`workbench-after.log`。100 列下新起点会显示 137 列宽度提示框，输入没有进入对话；改为正常 140 列并等待实际记录后通过，未改产品或屏蔽提示。`basis-before.log` 为首次控制台编码损失记录，UTF-8 重复首红另存未覆盖。

`python -m unittest discover -s tests -q` 已启动后按总控收窄回归要求中止；`artifacts/a-query/full-before-commit.log` 保留中间输出，无完整全仓结果，不宣称全量通过。其 LIVE 字样来自 `test_demo_stepper.test_live_transport_records_http_and_usage_without_network` 的合成密钥、HTTPTransport 替身，无真实网络模型调用。`git diff --check` 通过。

## 已知比较失败与未验

公开旧证据 `model-first-20261119/round2-acceptance/REPORT.md` 的 R2Q.1（45 行起）、`FAILURES.json`：模型正确 SQL 使用金额 BETWEEN，SQLite 返回空集符合独立真值；归属器返回 UNKNOWN/unsupported_predicate，随后扩大读取与预算截断，未完整交付每企业 0 笔/0.00 及相同结论。本切片尚未修改 SQL AST 归属器；此项继续保留失败。

未验：本轮真实模型自然语言、新 Dot 原 Trace、真实人类 GUI 接受、全量回归完成。规则历史版本仍按旧路径展示，不将停用版本升为当前依据。
