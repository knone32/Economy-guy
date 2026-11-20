# 当前工程状态（V3总控权威；2026-11-20 上海）

- 用户契约：FINAL-MISSION.md。当前13:30左右，11月20日16:00节点未过；21日集成、22日晚冻结准备，正式提交时刻仍须官方通知。
- 唯一集成工作区：business-20261120/contract-followup；分支sprint/2026-11-20-contract-followup；核实HEAD 718d8121ba0327c8ccf5b105046f1294eb8c7bdf，开工工作区干净。E:/beside为旧main 3111bd7，不覆盖候选。
- 根负责集成、架构、D平台与唯一预算；A独占../v3-a-query（查询/事实/传输），B独占../v3-b-runtime（多轮/执行/失败归因），C独占../v3-c-acceptance（封存全新陌生题/独立真值/正式成绩），起点同718d812。禁止代理交叉修改与付费。
- agent.py和共享Schema修改须根分配；新产品代码仅根集成，C不改产品；C题不透露实现者。
- 开工已核旧证据：../evidence-root/FINAL-718d812-VALIDATION.json及final-718d812-{targeted,full}.log。61相关通过；866全量182FAIL/33ERROR未归因关闭。718d812无自身Live/真人签收。
- 旧四对原首执属于7a1fdf4：P1 FAIL、P2 NOT_TESTED、P3 INVALID、P4截断/交付FAIL，0/4；不改分、不迁移新SHA，公开P1/P4仅回归。
- 正式业务DB不修改；本轮只临时虚构DB。运行入口finance_agent/main.py→AgentWorkspace→Agent.ask；实际Profile/DB位置继续核对，旧离线Profile报告不能当当前事实。
- 预算沿用../c-fresh-private/runtime/LEDGER.json，已用13请求/135275tokens/0.134478元；余额2.065522元/51请求/564725tokens。42元历史累计未知保留；新调用先核对，不能重置账本。见BUDGET-LEDGER.md。
- 环境：默认exec与Node内核启动失败；经审批require_escalated只读/工程命令可执行。Git旧目录所有者不同，按命令-c safe.directory精确绑定，不改全局安全配置。
- 下一步：A/B通用根因与定向复现；根核预算/真实配置并推进平台缺口；C封新题→接口适配→冻结后首执。正常可见工作台和真人批准缺口仍未解决，不可自动代点。
