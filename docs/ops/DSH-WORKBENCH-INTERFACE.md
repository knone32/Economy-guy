# DSH 工作台入口：一次接口与文件归属对齐

DSH 页面基线 `c0de7a1`，业务入口受测冻结 `c16228b`；交付源码 `394441c` 仅修正两条设置说明。现有页面和业务范围保持；不创建登录系统、第二 Loop 或新业务状态 owner。限定结果见 [本轮验收](WORKBENCH-ENTRY-ACCEPTANCE-20261122.md)，程序、Live、真人分别记录。

## 归属

- 后端（Sol）：`session_host.py`、`session_profiles.py`；必要的原 `Agent`／`SessionStore` 薄改动。任务事实、权限、规则继续归 `tasks.py`／现有服务。
- DSH：`gui_host.py`、`gui_server.py`、`gui/index.html` 的按钮、HTTP、展示及宿主配置接线。只调用以下原宿主入口，不自行更换 Agent、保存任务状态或拷贝批准。
- 模型配置文件、Windows 凭据与消耗原账保持原来源。本次只切已有 Profile，不创建／改写 Profile 或凭据，不新开消耗账。

## 确定接口

```python
from app.session_profiles import ExistingProfiles
profiles = ExistingProfiles(template=existing_template, local=existing_local)
host = SessionHost(store, agent_factory, confirm=human_callback,
                   require_display_ack=True, profiles=profiles)
```

| 方法 | 返回／约束 |
| --- | --- |
| `list_tasks()` | 当前实际账号所有可读企业的原 `list_tasks` 回包列表；不是浏览器指定企业集合，无四企业截断 |
| `task_details(company_id, task_id)` | 原 `task_details` 回包，包含当前规则、发票、problem、may_modify、can_execute；失败如实显示 |
| `open_task(company_id, task_id, expected=...)` | 返回统一 snapshot；重新核权／规则；只建立原任务办理焦点，不修改发票、不宣称完成、不批准 |
| `list_profiles()` | 原配置对当前账号可见的 profile_name/provider/model/scope；不含密钥、凭据引用或可由模型自报的权限 |
| `switch_profile(name, expected=...)` | 只解析已有 Profile，原 `Agent.switch_model` 构造新协议实例并核权；出错不退休旧 Agent；成功无旧草稿／批准。只改变本次宿主使用，不改配置文件 |
| `rebind(binding_factory, expected=...)` | **Python 受信宿主专用**，返回新的 SessionHost 对象；不是 JSON RPC。成功后适配器替换 host/store 句柄和展示缓存，旧对象不可再用 |

`binding_factory()` 由宿主策略提供，返回 `(new_store, new_agent_factory, new_profiles)`；new_store 已使用真实选择的账号／账簿／会话重新构造。浏览器只能提交宿主预先列出的选择 ID；宿主按本机受信策略独立解析及核准，不能把 browser.user_id、db_path、role 或 approved 当授权。未配置这种策略时不提供账号／账簿切换按钮。当前本机 U001/U002 选择属于模拟，不能显示为生产登录认证。

原宿主统一拒绝运行中、待补、草稿／预览、未知提交状态的切换。明确暂缓且确已保存的候选可保留在原 Store 列表，不自动带到另一个绑定。未知提交先只读 inspect，不能以切换绕过核查。失败返回原真实状态；不要在浏览器端手动清空 pending/preview 伪造已完成。

snapshot 新增 `model`（当前连接的安全 metadata）、`task_focus`（原 Store 当前任务引用）、`binding_mode=trusted_local_simulation_not_login_authentication`。仍使用 context generation/revision/chat/candidate 做并发检查；重新绑定生成新 generation，不复制旧账号／账簿的原话、引用、要求、草稿或批准，只允许目标原 Store 恢复其自己的有效状态。

Profile 切换解析复用 `ExistingProfiles.resolve(actor, name)`；初次 GUI factory 保留原 resolve_connection／WindowsVault 路径和同一配置文件，不创建另一套凭据。切换成功以返回的实际 connection 更新 GUI 自身配置选择，使下一次新会话仍构造该 Profile。禁止根据按钮文字或模型正文宣布切换成功；配置构造成功也不代表服务已调用成功。

## GUI 已接委托路由

现有本机 token 和精确 `context` 门禁不变。POST `/api/task_details`、`/api/task_open` 接收 `company_id, task_id, context`；POST `/api/profile` 接收 `profile_name, context`。均由 `GuiHost` 委托上表原入口，返回统一 `{ok, snapshot}`；详情在 snapshot.task_details 中保留原服务回包。页面已有“详情／进入办理／使用此 Profile”接线，界面布局保持。

受信宿主调用 `GuiHost.rebind_from_host(binding_factory, context)`，成功才替换原 host/store、账号／账簿／Profile 元数据和缓存；失败返回旧真实状态。没有 `/api/rebind` 或浏览器提交 actor/path 的授权入口。运行中和真人预览时拒绝重新绑定，结果未知时必须先走原 inspect；不能先清空 UI 再宣称成功。DSH 后续若配置宿主选择目录，只传目录中的选择 ID，由受信宿主解析后构造工厂，不把这个入口改成浏览器自报身份。

## 本轮验收边界

只覆盖新任务办理焦点、已有 Profile 选择、切换阻断与受信重新绑定。旧 GUI 提交、checkpoint、只读核查及长上下文证据复用，不重新运行完整链。程序边界、真实模型调用和真人操作分别记账；源码存在或 Profile 构造成功不等于 Live 可用。共同冻结一个实际集成 SHA 后执行。
