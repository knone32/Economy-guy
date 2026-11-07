"""Shared trusted chat interaction for argparse and the application home."""
import json
import os
from dataclasses import asdict
import re

from .trace import redact


def safe_text(value):
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\ud800-\udfff]", "", redact(value))


def turn_tools(messages):
    """Pair actual tool proposals and results without exposing model wire messages."""
    proposed = {}
    rows = []
    for message in messages:
        if message["role"] == "assistant":
            for call in message.get("tool_calls") or []:
                proposed[call["id"]] = call["function"]
        elif message["role"] == "tool":
            identifier = message["tool_call_id"]
            result = json.loads(message["content"])
            function = proposed.get(identifier, {})
            arguments = function.get("arguments")
            try:
                arguments = json.loads(arguments)
            except (TypeError, ValueError):
                arguments = None
            rows.append(redact(dict(id=identifier, tool=function.get("name"), arguments=arguments,
                                    status=result["status"], scope=result.get("evidence", {}).get("scope"),
                                    error=result.get("error"))))
    return rows


def run_chat(args, *, home=None):
    from .agent import Agent, live_model, _BUILTIN_LIVE_MODEL
    from .model_config import resolve_connection, load_profiles
    def serialize(value, indent=None):
        return json.dumps(redact(value) if home else value, ensure_ascii=False, indent=indent)

    profile_options={'template':args.profiles_file,'local':args.profiles_local}
    model = live_model
    if args.mode == "mock":
        print("MOCK / 固定模拟响应：每轮查询 C001 2026-09，不代表自然语言理解")
        def model(messages, tools):
            if messages[-1]["role"] == "tool":
                return {"role": "assistant", "content": json.dumps({"kind":"information", "text":"MOCK 结果：" + messages[-1]["content"]}, ensure_ascii=False)}
            return {"role": "assistant", "tool_calls": [{"id": "mock_query", "type": "function", "function": {"name": "get_finance_summary", "arguments": '{"company_id":"C001","year":2026,"month":9}'}}]}
    connection = None
    if not home or args.mode == "live":
        _, default_profile = load_profiles(**profile_options)
        selected = args.profile or os.getenv("FINANCE_MODEL_PROFILE") or default_profile
        if selected or (args.mode == "live" and model is _BUILTIN_LIVE_MODEL):
            connection = resolve_connection(args.user, args.profile, require_key=args.mode == "live",
                                            **profile_options)
    def confirm_long_term(proposal):
        """可信交互只确认本次展示的对象与内容，不让模型提供确认。"""
        if home and redact(proposal) != proposal:
            print("候选包含需脱敏的内容。请移除敏感信息并重新提出具体要求。")
            return False
        print('长期状态待确认（尚未保存）：')
        print(serialize(proposal, indent=2))
        try:
            return input('核对原始要求及实际对象/内容，输入 confirm '+proposal['request_id']+' 才保存；其他输入取消：')=='confirm '+proposal['request_id']
        except (EOFError,KeyboardInterrupt):
            return False
    agent = Agent(args.user, args.db, model, args.mode, args.trace,max_context_chars=args.max_context_chars,
                  block_requests=args.block_requests,max_requests=args.max_requests,max_tools=args.max_tools,
                  max_extensions=args.max_extensions,max_replans=args.max_replans,management_confirmation=confirm_long_term,connection=connection)
    if home:
        print(f"━━ 多轮对话 · {args.user} · {args.mode.upper()} ━━")
        print("输入问题开始查询。输入 1 后描述发票修改。任务和偏好可直接用自然语言提出。")
        print("0 或 exit 返回上一级，/home 返回主页，/cancel 撤销待确认操作，/quit 安全退出。")
        if agent.transport:
            bind_connection_status(agent, home)
    print("财税Agent（模拟身份）：普通自然语言可提出待办/偏好候选，核对具体内容并确认才保存；/task、/preference兼容。/edit准备发票草稿，仍须最终确认。exit退出。")
    return chat_loop(agent, args, profile_options, serialize, home)


def bind_connection_status(agent, home):
    trace = agent.transport.trace

    def report(event, data):
        home.observe_connection(event, data)
        trace(event, data)

    agent.transport.trace = report


def chat_loop(agent, args, profile_options, serialize, home):
    from .model_config import resolve_connection, visible_profiles, ProfileError

    try:
        while True:
            try:
                text = input("你：")
                if home and text.strip() == "1":
                    edit = input("描述修改目标和新值（/cancel 取消）：").strip()
                    if not edit or edit in {"/cancel", "0"}:
                        agent.cancel_update()
                        print("已取消。")
                        continue
                    text = edit if edit in {"/home", "/quit"} else "/edit " + edit
            except (EOFError, KeyboardInterrupt):
                break
            choice = text.strip().lower()
            if choice == "exit" or (home and choice == "0"):
                break
            if home and choice in {"/home", "/quit"}:
                return choice
            if text.strip():
                if text.strip()=='/provider list':
                    print(serialize(visible_profiles(args.user, **profile_options), indent=2))
                    continue
                if text.strip()=='/provider status':
                    print(serialize(agent.connection.metadata() if agent.connection else {'mode':'mock','profile_name':None}))
                    continue
                if text.startswith('/provider use '):
                    try:
                        new_connection=resolve_connection(args.user,text[len('/provider use '):].strip(),require_key=args.mode=='live',**profile_options)
                        agent=agent.switch_model(new_connection)
                        if home:
                            home.profile = new_connection.profile.profile_name
                            home.reset_session()
                            if agent.transport:
                                bind_connection_status(agent, home)
                        print('模型协议会话已重建：保留可重新鉴权的业务范围，任务/偏好重读SQLite；旧消息、草稿和确认不继承。')
                        print(serialize(agent.connection.metadata()))
                    except ProfileError as error:
                        print('未切换：'+str(error))
                    continue
                if text.strip() == "/cancel":
                    print(serialize(agent.cancel_update(), indent=2))
                    continue
                allow_prepare = text.startswith("/edit ")
                request = text[6:] if allow_prepare else text
                management = None
                management_action = None
                if text.startswith("/task "):
                    management,request = "task",text[6:]
                elif text.startswith("/preference "):
                    management,request = "preference",text[12:]
                if management:
                    management_action,separator,request = request.partition(" ")
                    actions = {"create","show","update","correct","wait","pause","resume","complete","cancel","list","get","delete"}
                    if management_action not in actions or not separator or not request.strip():
                        print("请用明确管理动作和要求，例如 /task create 保存C001九月用途后续待办。未执行写入。")
                        continue
                continue_edit = False
                if agent.pending_edit and not allow_prepare:
                    original = agent.pending_edit["inputs"][0]
                    print("尚有待补充修改意图：" + (safe_text(original) if home else original))
                    try:
                        continue_edit = input("本条是补充该修改？输入 continue 关联；其他输入按新主题处理：") == "continue"
                    except (EOFError, KeyboardInterrupt):
                        if home:
                            break
                        continue_edit = False
                offset = len(agent.messages)
                try:
                    answer = agent.ask(request, allow_prepare=allow_prepare, continue_edit=continue_edit,
                                       management=management, management_action=management_action)
                except KeyboardInterrupt:
                    if home:
                        print("对话已中断。若提交结果未知，请先查看审计。")
                        break
                    raise
                calls = turn_tools(agent.messages[offset:]) if home else []
                if calls:
                    print("本轮工具与结果")
                    for call in calls:
                        print(serialize(call))
                print("答复（一般说明会标明未核实；查询另附实际范围）：" + (safe_text(answer) if home else answer))
                print("Harness发票写入回执：" + serialize(agent.write_receipt))
                if home and agent.write_receipt["status"] == "UNKNOWN_OUTCOME":
                    print("请先从「历史记录与审计」核对请求编号，再决定是否继续。")
                for request_id, draft in list(agent.update_session.drafts.items()):
                    if home and redact(asdict(draft)) != asdict(draft):
                        print("草稿包含需脱敏的内容。请移除敏感信息并重新提出修改。")
                        agent.cancel_update()
                        break
                    print("本轮原始要求：" + (safe_text(draft.source_request) if home else draft.source_request))
                    print(serialize(asdict(draft), indent=2))
                    print("请核对企业/发票/字段/旧值/新值。输入完整 confirm " + request_id + " 才提交，其余输入取消。")
                    try:
                        confirmation = input("最终确认：")
                    except (EOFError, KeyboardInterrupt):
                        confirmation = ""
                    if confirmation != "confirm " + request_id:
                        print(serialize(agent.cancel_update(), indent=2))
                        continue
                    outcome = agent.commit_update(request_id, draft.fingerprint())
                    print(serialize(outcome, indent=2))
                    if home and outcome["status"] == "UNKNOWN_OUTCOME":
                        print("请先从「历史记录与审计」核对请求编号，再决定是否继续。")
                    if 'task_progress' in outcome:
                        from .responses import render_task_progress
                        progress = render_task_progress(outcome['task_progress'])
                        print(safe_text(progress) if home else progress)
                if home:
                    stop = (agent.last_response or {}).get("execution", {})
                    home.remember(request, stop, [{"tool": call["tool"], "status": call["status"]} for call in calls],
                                  agent.write_receipt["status"])
    finally:
        if home:
            agent.cancel_update()
