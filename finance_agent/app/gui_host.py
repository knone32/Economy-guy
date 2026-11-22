"""Minimal GUI adapter over the accepted SessionHost.

Business state and commands stay in ``SessionHost`` / ``SessionStore`` /
``WriteCoordinator``. This module only projects their snapshot to the local
page and bridges the host's blocking human-confirmation callback to a
two-phase browser dialog. It does not own pending, draft, approval, commit or
recovery state.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
import sys
from contextlib import closing
from pathlib import Path

from .agent import Agent, live_model
from .cli_chat import safe_text
from .cli_workspaces import company_access
from .invoice_action import public_state as invoice_business_state
from .model_config import (DEFAULT_LOCAL, DEFAULT_TEMPLATE, ModelConnection, ProfileError,
                           resolve_connection, safe_url, visible_profiles)
from .responses import render_information, render_invoice_pending
from .session_host import SessionConflict, SessionHost
from .session_profiles import ExistingProfiles
from .session_store import SessionStore
from .tasks import list_tasks
from .tui_local import session_path as default_session_path
from .gui_workspace_actions import WorkspaceActions


class GuiError(ValueError):
    """A local GUI error; never a business success."""


def _as_text(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    return safe_text(value)


def _field_label(field):
    return {"purpose": "用途", "remark": "备注"}.get(field, str(field))


class GuiHost(WorkspaceActions):
    """HTTP-facing adapter; ``SessionHost`` is the only command/business owner."""

    # A callback handle is ephemeral. On expiry the browser dialog is closed;
    # this is an interruption, never an approval or a rejection.
    CONFIRMATION_TIMEOUT = 900

    def __init__(self, db_path, user_id="U001", *, session_path=None, mode="live",
                 profile=None, model=None, trace_path=None, max_context_chars=48000,
                 profiles_file=None, profiles_local=None):
        self.db_path = Path(db_path).resolve()
        self.user_id = str(user_id)
        self.mode = mode
        self.profile = profile
        self.trace_path = Path(trace_path) if trace_path else None
        self.session_path = Path(session_path) if session_path else default_session_path()
        self._model = model
        self._max_context_chars = max_context_chars
        self.profiles_file = profiles_file
        self.profiles_local = profiles_local
        self.profiles = ExistingProfiles(template=profiles_file or DEFAULT_TEMPLATE,
                                         local=profiles_local or DEFAULT_LOCAL)

        self._cond = threading.Condition()
        self._busy = False
        self._done = threading.Event()
        self._worker = None
        self._error = None
        self._last = None
        self._last_context = None
        self._confirmation = None
        self._confirmation_expired = False
        self._closing=False
        self._connection_info = {
            "mode": self.mode,
            "connected": False,
            "profile": None,
            "model": None,
            "base_url": None,
            "provider": None,
        }

        self.store = SessionStore(self.session_path, self.db_path, self.user_id)
        self.host = SessionHost(self.store, self._factory, confirm=self._confirm,
                                require_display_ack=True, profiles=self.profiles)
        self._last = self.host.snapshot()
        self._last_context = self._last.get("context")
        self._bindings={}
        self._register_book(self.db_path)

    # ------------------------------------------------------------------ agent factory
    def _factory(self, actor, workbook):
        if self.mode == "live":
            options = {}
            if self.profiles_file is not None:
                options["template"] = self.profiles_file
            if self.profiles_local is not None:
                options["local"] = self.profiles_local
            try:
                connection, self.startup_diagnostics = self.profiles.resolve_with_diagnostics(actor,self.profile)
            except (ProfileError,PermissionError) as error:
                self.startup_diagnostics=getattr(error,'diagnostic',{'status':'CONFIG_UNAVAILABLE'})
                self._connection_info={'mode':'live','connected':False,'profile':self.profile,
                    'model':None,'base_url':None,'provider':None,'message':'请先在设置中配置模型和本机密钥。'}
                def unavailable(*args):raise GuiError('模型尚未配置，未发送API请求。')
                return Agent(actor,workbook,model=unavailable,mode='mock',trace_path=self.trace_path,
                    max_context_chars=self._max_context_chars)
            bound = connection
            self.profile = bound.profile.profile_name
            self._connection_info = {
                "mode": "live",
                "connected": True,
                "profile": bound.profile.profile_name,
                "model": bound.profile.model,
                "base_url": safe_url(bound.profile.base_url),
                "provider": bound.profile.provider,
            }
            return Agent(actor, workbook, model=live_model, mode="live",
                         trace_path=self.trace_path, connection=connection,
                         max_context_chars=self._max_context_chars)
        if self._model is None:
            raise GuiError("mock 模式需要显式注入本地模型。")
        self._connection_info = {
            "mode": "mock",
            "connected": True,
            "profile": None,
            "model": "scripted-local-model",
            "base_url": None,
            "provider": "local-script",
        }
        return Agent(actor, workbook, model=self._model, mode="mock",
                     trace_path=self.trace_path, max_context_chars=self._max_context_chars)

    def _settings(self):
        """Presentation of host-owned connection config; no secrets, no switch."""
        info = dict(self._connection_info)
        live = self.mode == "live"
        if live and info.get("connected"):
            status, label = "CONFIGURED", "已有配置已绑定；服务调用另行验证"
        elif live:
            status, label = "UNAVAILABLE", "真实模型未连接"
        else:
            status, label = "MOCK", "脚本模型（非 Live）"
        template = self.profiles.options['template']
        local = self.profiles.options['local']
        profiles = []
        try:
            for profile in visible_profiles(self.user_id, template, local):
                profiles.append({
                    "profile_name": profile.get("profile_name"),
                    "scope": profile.get("scope"),
                    "owner_user_id": profile.get("owner_user_id"),
                    "provider": profile.get("provider"),
                    "model": profile.get("model"),
                    "base_url": safe_url(profile.get("base_url")),
                    "protocol": profile.get("protocol"),
                    "is_current": profile.get("profile_name") == info.get("profile"),
                })
        except (OSError, ValueError, ProfileError):
            profiles = []
        return {
            "account": {"user_id": self.user_id, "workbook": str(self.db_path)},
            "model": {
                "mode": info.get("mode") or self.mode,
                "status": status,
                "label": label,
                "configured": bool(info.get("connected")),
                "connected": None,
                "profile": info.get("profile"),
                "model": info.get("model"),
                "provider": info.get("provider"),
                "base_url": info.get("base_url"),
            },
            "profiles": profiles,
            "bindings":[{'id':key,'label':value['label'],'current':value['actor']==self.user_id and value['book']==self.db_path}
                        for key,value in getattr(self,'_bindings',{}).items()],
            "companies":self.workspace_catalog(),
            "assistants":self.assistant_choices(),
            "assistant_id":self.host.agent.assistant_id,
            "personal_detail":self.store.personal_detail(),
            "launch": self.launch_description(),
            "switching": {
                "account": "可选择宿主登记的模拟账号；切换会重新核权，不是登录认证。",
                "workbook": "可选择已登记账簿或将xlsx导入为新库；原库不覆盖，待补和批准不跨绑定继承。",
                "model": "已有 Profile 可通过原宿主切换；待补、预览和未知提交须先处理。",
            },
        }

    def _register_book(self, book):
        """Host-owned options; browser receives opaque selectors, never authority."""
        book=Path(book).resolve()
        with closing(sqlite3.connect(book.as_uri()+'?mode=ro',uri=True)) as db:
            users=db.execute('SELECT user_id,name FROM users').fetchall()
        for actor,name in users:
            if not any(b['actor']==actor and b['book']==book for b in self._bindings.values()):
                self._bindings[uuid.uuid4().hex]={'actor':actor,'book':book,'label':f'{name}（{actor}） · {book.name}'}

    def workspace_catalog(self):
        from .queries import available_periods
        rows=[]
        try:
            with closing(sqlite3.connect(self.db_path.as_uri()+'?mode=ro',uri=True)) as db:
                db.row_factory=sqlite3.Row
                for company in company_access(self.db_path,self.user_id):
                    if company['read']:
                        rows.append({**company,'periods':[r[0] for r in available_periods(db,self.user_id,company['company_id'])]})
        except (OSError,ValueError,sqlite3.Error):pass
        return rows

    def assistant_choices(self):
        try:
            with closing(sqlite3.connect(self.db_path.as_uri()+'?mode=ro',uri=True)) as db:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE name='assistant_config'").fetchone():return []
                return [{'id':key,'name':json.loads(body)['name']} for key,body in db.execute(
                    "SELECT id,body FROM assistant_config WHERE owner=? AND kind='assistant' AND enabled=1",(self.user_id,))]
        except (OSError,ValueError,sqlite3.Error):return []

    def select_assistant(self, identifier, context=None):
        from .assistant_config import refresh_assistant
        def change(expected):
            with self.host._command(expected):
                self.host._transition_ready()
                if identifier not in {item['id'] for item in self.assistant_choices()}:
                    raise GuiError('当前账号没有这个已启用的业务助手。')
                agent=self.host.agent;old=agent.assistant_id;tools=agent.allowed_tools
                agent.assistant_id=identifier
                try:refresh_assistant(agent)
                except Exception:agent.assistant_id=old;agent.allowed_tools=tools;raise
            return self.host.snapshot()
        return self._command(change,context)

    def preference_change(self, value, context=None):
        return self._start_action(lambda expected:self.host.manage_preference(None if value.get('scope')=='personal' else value.get('company_id'),
            value.get('action'),value.get('key'),value.get('value',''),expected=expected),context)

    def read_business(self, name, arguments, context=None):
        return self._command(lambda expected:self.host.read_business(name,arguments,expected=expected),context)

    def select_binding(self, selector, context=None):
        choice=self._bindings.get(selector)
        if choice is None:raise GuiError('该账号或账簿未由宿主登记，请刷新。')
        if choice['book']==self.db_path and choice['actor']==self.user_id:
            return self._command(lambda expected:self._same_binding(expected),context)
        def factory():
            book=choice['book'];actor=choice['actor']
            session=self.session_path if book==self.db_path else book.parent/'sessions.sqlite3'
            return SessionStore(session,book,actor),self._factory,self.profiles
        return self.rebind_from_host(factory,context=context)

    def _same_binding(self, expected):
        with self.host._command(expected):
            self.host._transition_ready()
        return self.host.snapshot()

    def import_workbook(self, name, content, context=None, files=None):
        """Create an independent workbook from the original xlsx, one fixed-
        template docx, or the four fixed CSV files.  The xlsx request shape is
        unchanged; conversion only produces the same four-sheet workbook that
        the original import_workspace validates and publishes."""
        if files is not None:
            if name is not None or content is not None:
                raise GuiError('导入请求不能同时提交单文件和CSV文件列表。')
            return self._import_csv_workbook(files, context)
        if not isinstance(name, str) or not name.strip():
            raise GuiError('缺少导入文件名，未创建新账簿。')
        suffix = name.lower()
        if suffix.endswith('.xlsx'):
            return self._import_excel_workbook(name, content, context)
        if suffix.endswith('.docx'):
            return self._import_word_workbook(name, content, context)
        if suffix.endswith('.csv'):
            raise GuiError('CSV 必须一次选择四份固定文件：企业与用户.csv、发票.csv、银行流水.csv、说明.csv。')
        raise GuiError('只接受 .xlsx、.docx 或四份固定名称的 .csv，导入为新库，不覆盖当前库。')

    def _import_excel_workbook(self, name, content, context=None):
        import base64
        from .cli_workspaces import import_workspace
        with self.host._command(context or self._last_context):
            self.host._transition_ready()
            data=base64.b64decode(content,validate=True)
            if not 0<len(data)<=5_000_000:raise GuiError('账簿文件为空或超过5MB。')
            root=self.session_path.parent/'imports'/uuid.uuid4().hex;root.mkdir(parents=True)
            original=root/'source.xlsx';original.write_bytes(data)
            book=root/'workbook.sqlite3'
            import_workspace(original,book)
            self._register_book(book)
        return self.snapshot(notice='已导入为独立账簿，请在设置中选择新绑定；原账簿未覆盖。')

    def _import_word_workbook(self, name, content, context=None):
        from .import_formats import ImportFormatError, convert_docx
        with self.host._command(context or self._last_context):
            self.host._transition_ready()
            self._error=None;self._workspace_notice=None
            data=self._decode_import_content(content,'Word')
            if not 0<len(data)<=5_000_000:raise GuiError('Word 文件为空或超过5MB。')
            try:converted=convert_docx(data,name)
            except ImportFormatError as error:
                raise GuiError('导入失败（未创建新账簿，原账簿未变更）：Word 文件 '+
                               Path(str(name)).name+'：'+str(error)) from None
            self._publish_converted(converted)
        return self.snapshot(notice='已导入为独立账簿，请在设置中选择新绑定；原账簿未覆盖。')

    def _import_csv_workbook(self, files, context=None):
        from .import_formats import ImportFormatError, convert_csv_files
        with self.host._command(context or self._last_context):
            self.host._transition_ready()
            self._error=None;self._workspace_notice=None
            try:converted=convert_csv_files(files)
            except ImportFormatError as error:
                raise GuiError('导入失败（未创建新账簿，原账簿未变更）：'+str(error)) from None
            self._publish_converted(converted)
        return self.snapshot(notice='已导入为独立账簿，请在设置中选择新绑定；原账簿未覆盖。')

    @staticmethod
    def _decode_import_content(content, label):
        import base64,binascii
        if not isinstance(content,str):raise GuiError(label+'文件内容缺失。')
        try:return base64.b64decode(content,validate=True)
        except (binascii.Error,ValueError):
            raise GuiError(label+'文件内容不是合法Base64。') from None

    def _publish_converted(self, converted):
        """Private staging only; a failure removes it and never registers a book."""
        import shutil
        from .cli_workspaces import import_workspace
        root=self.session_path.parent/'imports'/uuid.uuid4().hex;root.mkdir(parents=True)
        try:
            converted_file=root/'converted.xlsx';converted_file.write_bytes(converted.payload)
            book=root/'workbook.sqlite3'
            try:
                import_workspace(converted_file,book)
            except Exception as error:
                detail=converted.explain(error)
                message='导入失败（未创建新账簿，原账簿未变更）：'+converted.source+' 未通过原导入器校验：'
                message+=(detail or str(error))
                if detail:message+='（原核对错误：'+str(error)+'）'
                raise GuiError(message) from None
            self._register_book(book)
        except BaseException:
            shutil.rmtree(root,ignore_errors=True)
            raise


    def save_profile(self, value, context=None):
        from .model_config import add_profile,resolve_connection,update_user_profile
        from .win_vault import WindowsVault,profile_target
        from dataclasses import asdict
        with self.host._command(context or self._last_context):
            self.host._transition_ready()
            name=str(value.get('profile_name','')).strip()
            existing=[p for p in visible_profiles(self.user_id,**self.profiles.options) if p['profile_name']==name]
            if existing:
                profile=resolve_connection(self.user_id,name,require_key=False,**self.profiles.options).profile
                if any(value.get(k) and value[k]!=getattr(profile,k) for k in ('provider','model','base_url')):
                    public=asdict(profile)
                    public.update({k:value[k] for k in ('provider','model','base_url') if value.get(k)})
                    public['api_key_env']='ECONOMYGUY_'+uuid.uuid4().hex.upper()
                    update_user_profile(profile,public,self.user_id,**self.profiles.options)
                    profile=resolve_connection(self.user_id,name,require_key=False,**self.profiles.options).profile
            else:
                public={'profile_name':name,'scope':'user','owner_user_id':self.user_id,
                    'provider':value.get('provider'),'model':value.get('model'),'base_url':value.get('base_url'),
                    'api_key_env':'ECONOMYGUY_'+uuid.uuid4().hex.upper(),'protocol':'auto'}
                add_profile(public,user_id=self.user_id,**self.profiles.options)
                profile=resolve_connection(self.user_id,name,require_key=False,**self.profiles.options).profile
            secret=value.get('api_key','')
            if secret:
                if type(secret) is not str:raise GuiError('密钥格式无效。')
                WindowsVault().write(profile_target(profile,self.user_id),secret)
            if self.mode=='live' and self.profile==name:self._refresh_model()
        return self.snapshot(notice='配置已保存；密钥仅保存在本机Windows凭据库。请选择该Profile并使用。')

    def launch_description(self):
        """Only non-secret, host-bound arguments; never reconstruct identity in JS."""
        argv=[sys.executable]+([] if getattr(sys,'frozen',False) else [str(Path(__file__).resolve().parents[1]/'run_gui.py')])+[
            '--db',str(self.db_path.resolve()),'--session',str(self.store.path.resolve()),'--user',self.user_id,
            '--profiles-file',str(Path(self.profiles.options['template']).resolve()),
            '--profiles-local',str(Path(self.profiles.options['local']).resolve())]
        if self.profile:argv += ['--profile',self.profile]
        # A copied launch starts a new instance, not a collision on the old port.
        argv += ['--port','0','--embedded']
        return {'shell':'PowerShell','argv':argv,'command':"& "+' '.join("'"+arg.replace("'","''")+"'" for arg in argv)}

    # ------------------------------------------------------------------ confirmation bridge
    def _confirm(self, payload):
        """Block the original host worker while the browser owns the dialog."""
        item = {
            "id": uuid.uuid4().hex,
            "payload": payload,
            "answer": None,
            "event": threading.Event(),
        }
        with self._cond:
            self._confirmation = item
            self._confirmation_expired = False
            bound = payload.get("snapshot") if isinstance(payload, dict) else None
            if isinstance(bound, dict):
                self._last = bound
                self._last_context = bound.get("context")
            self._cond.notify_all()
        if not item["event"].wait(timeout=self.CONFIRMATION_TIMEOUT):
            message = "等待真人确认已超时；未产生批准，未提交。请刷新或重新提出修改。"
            with self._cond:
                if self._confirmation is item:
                    self._confirmation = None
                self._confirmation_expired = True
                self._error = message
                self._cond.notify_all()
            raise GuiError(message)
        return item["answer"] is True

    def _confirmation_view(self):
        item = self._confirmation
        if not item:
            return None
        payload = item.get("payload") or {}
        snapshot = payload.get("snapshot") or {}
        drafts = snapshot.get("preview") or []
        items = []
        for draft in drafts:
            if not isinstance(draft, dict):
                continue
            company = draft.get("company_id")
            invoice = draft.get("invoice_no")
            items.append({
                "company_id": company,
                "company_name": self._company_name(company),
                "invoice_no": invoice,
                "invoice_date": self._invoice_date(company, invoice),
                "field": draft.get("field"),
                "field_label": _field_label(draft.get("field")),
                "old_value": draft.get("old_value"),
                "new_value": draft.get("new_value"),
            })
        body = str(payload.get("body") or "原业务预览")
        text = body + "\n\n尚未保存。确认后保存，并核对保存结果。"
        return {"id": item["id"], "text": text, "items": items,
                "count": len(items), "kind": payload.get("kind") or "single",
                "title": payload.get("title") or "原业务预览"}

    def confirm_preview(self, preview_id, context=None):
        with self._cond:
            item = self._confirmation
            if not item or item.get("id") != preview_id:
                if self._confirmation_expired:
                    raise GuiError("确认已超时失效；未批准、未提交，请刷新后重新提出修改。")
                raise GuiError("预览已失效，请刷新后重新提出修改。")
            if context != (item['payload'].get('snapshot') or {}).get('context'):
                raise GuiError('预览所属会话或修订不一致，请刷新。')
            self._confirmation = None
            item["answer"] = True
            item["event"].set()
            while not self._done.is_set():
                if self._confirmation is not None:
                    break
                self._cond.wait(0.25)
            raw = self._last
            error = self._error
        return self._project(raw, error=error)

    def cancel_preview(self, preview_id=None, context=None):
        with self._cond:
            item = self._confirmation
            if not item:
                if self._confirmation_expired:
                    raise GuiError("确认已超时失效；未批准、未提交，请刷新。")
                raise GuiError("没有待确认的预览。")
            if preview_id != item['id'] or context != (item['payload'].get('snapshot') or {}).get('context'):
                raise GuiError('取消指向旧预览，请刷新。')
            self._confirmation = None
            item["answer"] = False
            item["event"].set()
            while not self._done.is_set():
                if self._confirmation is not None:
                    break
                self._cond.wait(0.25)
            raw = self._last
            error = self._error
        return self._project(raw, error=error)

    # ------------------------------------------------------------------ send worker
    def _worker_run(self, text, expected):
        try:
            raw = text(expected) if callable(text) else self.host.send_message(text, expected=expected)
            self._last = raw
            self._last_context = raw.get("context")
            self._error = None
        except Exception as error:
            self._error = str(error)
            try:
                raw = self.host.snapshot()
                self._last = raw
                self._last_context = raw.get("context")
            except Exception:
                pass
        finally:
            with self._cond:
                self._busy = False
                self._done.set()
                self._cond.notify_all()

    def send(self, text, context=None, diagnose=False):
        if self._closing:raise GuiError('工作台正在关闭，请重新启动。')
        if self.mode=='live' and not self._connection_info.get('connected'):
            raise GuiError('请先在设置中保存模型密钥并选用Profile；本轮未发送API请求。')
        text = str(text or "").strip()
        if not text:
            raise GuiError("消息不能为空。")
        if len(text) > 4000:
            raise GuiError("本轮消息过长，请缩小范围。")
        if diagnose:
            def send_diagnostic(expected):
                transport=self.host.agent.transport
                if transport is None:raise GuiError('当前没有真实模型传输，无法记录请求结构。')
                transport.diagnose_next_request=True
                try:return self.host.send_message(text,expected=expected)
                finally:transport.diagnose_next_request=False
            return self._start_action(send_diagnostic,context)
        return self._start_action(text,context)

    def _start_action(self, text, context=None):
        """Reuse the original worker/confirmation bridge for a trusted command."""
        if self._closing:raise GuiError('工作台正在关闭，请重新启动。')
        with self._cond:
            if self._busy or self._confirmation:
                raise GuiError("当前受理尚未结束，请先完成预览、暂缓或取消。")
            expected = context or self._last_context
            if not isinstance(expected, dict):
                raise GuiError("缺少当前会话上下文，请刷新页面。")
            self._error = None
            self._workspace_notice=None
            self._busy = True
            self._done.clear()
            self._confirmation = None
            self._confirmation_expired = False
            self._worker = threading.Thread(target=self._worker_run, args=(text, expected), daemon=True)
            self._worker.start()
            while True:
                if self._confirmation is not None:
                    bound = self._confirmation.get("payload", {}).get("snapshot")
                    return self._project(bound or self._last)
                if self._done.is_set():
                    return self._project(self._last, error=self._error)
                self._cond.wait(0.25)

    # ------------------------------------------------------------------ projection
    def _company_name(self, company_id):
        if not company_id:
            return ""
        try:
            with closing(sqlite3.connect(str(self.db_path))) as db:
                row = db.execute("SELECT name FROM companies WHERE company_id=?", (company_id,)).fetchone()
                return row[0] if row else ""
        except sqlite3.Error:
            return ""

    def _invoice_date(self, company_id, invoice_no):
        if not company_id or not invoice_no:
            return ""
        try:
            with closing(sqlite3.connect(str(self.db_path))) as db:
                row = db.execute("SELECT invoice_date FROM invoices WHERE company_id=? AND invoice_no=?",
                                 (company_id, invoice_no)).fetchone()
                return row[0] if row else ""
        except sqlite3.Error:
            return ""

    def _history(self, conversation_turns=None):
        if conversation_turns is not None:
            source_turns = conversation_turns
        else:
            try:
                source_turns = self.store.history().get("turns") or []
            except (OSError, ValueError, sqlite3.Error):
                return []
        turns = []
        for turn in source_turns:
            request = turn.get("request") or ""
            display = turn.get("display") or []
            messages = []
            if request:
                messages.append({"role": "user", "text": _as_text(request)})
            for item in display:
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    continue
                role, body = item
                role, body = str(role), _as_text(body)
                if not body:
                    continue
                card = role.startswith("业务记录 / ")
                if card:
                    role = role[len("业务记录 / "):]
                messages.append({"role": role, "text": body, "card": card})
            if turn.get("state") in {"INTERRUPTED", "UNKNOWN_OUTCOME"}:
                messages.append({
                    "role": "状态",
                    "text": "上次处理被中断；请重新提出查询。" if turn.get("state") == "INTERRUPTED"
                            else "上次提交结果待核实；请先核查，不能自动重提。",
                    "warning": True,
                })
            turns.append({
                "seq": turn.get("seq"),
                "state": turn.get("state"),
                "request": _as_text(request),
                "messages": messages,
                "lookup": turn.get("lookup"),
                "operation": turn.get("operation") or {},
            })
        return turns[-60:]

    def _pending(self, raw):
        pending = raw.get("pending") if isinstance(raw, dict) else None
        if not isinstance(pending, dict):
            return None
        status = raw.get("business_status")
        state = "PAUSED" if status == "PAUSED" else "ACTIVE"
        known = pending.get("known") or {}
        text = render_invoice_pending(
            pending,
            company_name=self._company_name(known.get("company_id")) or None,
            paused=state == "PAUSED",
            actions=False,
        )
        return {
            "state": state,
            "known": known,
            "missing_fields": list(pending.get("missing_fields") or ()),
            "text": text,
            "can_pause": state == "ACTIVE" and not self._busy and status not in {"UNKNOWN_OUTCOME", "CANCELLED"},
            "can_cancel": True,
        }

    def _candidates(self, raw):
        rows = raw.get("candidates") if isinstance(raw, dict) else None
        context = raw.get("context") if isinstance(raw, dict) else {}
        current_token = tuple(context.get("candidate") or ()) if isinstance(context, dict) else ()
        found = []
        # A restored/active pending is the current action, not a resume choice.
        # Only after a real PAUSED persistence receipt is a resume control shown.
        if isinstance(raw, dict) and raw.get("pending") and raw.get("business_status") != "PAUSED":
            return found
        for row in rows or []:
            # Only an actually persisted PAUSED row is a recoverable choice.
            # An ACTIVE row is the current pending item, not a resume action;
            # in particular a failed pause must not appear here.
            if not isinstance(row, dict) or row.get("state") != "PAUSED":
                continue
            pending = row.get("pending")
            if not isinstance(pending, dict):
                continue
            try:
                business = invoice_business_state(pending)
            except (ValueError, TypeError):
                continue
            known = business.get("known") or {}
            found.append({
                "id": row.get("id"),
                "revision": row.get("revision"),
                "state": row.get("state"),
                "text": render_invoice_pending(
                    business,
                    company_name=self._company_name(known.get("company_id")) or None,
                    paused=row.get("state") == "PAUSED",
                    actions=True,
                ),
                "can_resume": row.get("state") in {"ACTIVE", "PAUSED"} and not self._busy,
                "can_cancel": bool(current_token) and current_token == (
                    row.get("id"), row.get("revision")) and not self._busy,
            })
        return found

    def _tasks(self, raw):
        found = []
        for outcome in raw.get('tasks') or []:
            for task in outcome.get("data") or []:
                if not isinstance(task, dict):
                    continue
                context = task.get("context") if isinstance(task.get("context"), dict) else {}
                found.append({
                    "task_id": task.get("task_id"),
                    "company_id": task.get("company_id"),
                    "company_name": self._company_name(task.get("company_id")),
                    "year": task.get("year"),
                    "month": task.get("month"),
                    "status": task.get("status"),
                    "note": _as_text(context.get("note") or ""),
                })
        return found

    def _receipt_view(self, raw):
        if not isinstance(raw, dict):
            return None
        status = raw.get("status")
        # Agent's default no-action receipt is not a submission result; don't
        # put a "提交回执" card on a pure query or a pre-confirmation screen.
        if status in {None, "", "NOT_SUBMITTED", "NO_RECEIPT"}:
            return None
        nested = raw.get("data")
        if isinstance(nested, dict):
            nested = nested.get("data") if isinstance(nested.get("data"), dict) else nested
        else:
            nested = {}
        historical = nested.get("historical_commit") if isinstance(nested, dict) else None
        return {
            "status": raw.get("status"),
            "message": raw.get("message"),
            "readback_verified": raw.get("readback_verified"),
            "request_ref": (historical or {}).get("request_id") if isinstance(historical, dict) else None,
        }

    def _persistence(self, raw):
        state = raw.get("persistence") if isinstance(raw, dict) else None
        status = state.get("status") if isinstance(state, dict) else None
        if status == "FAILED":
            return {"send": "failed", "commit": "not_attempted",
                    "message": (state.get("message") if isinstance(state, dict) else None)
                    or "宿主持久化失败；业务回执以原结果为准，不能据此重复提交。"}
        if status == "SAVED":
            return {"send": "saved", "commit": "not_attempted", "message": None}
        return {"send": "not_attempted", "commit": "not_attempted", "message": None}

    def _project(self, raw, *, error=None):
        if not isinstance(raw, dict):
            raw = {}
        context = raw.get("context") or self._last_context
        if isinstance(context, dict):
            self._last_context = context
        status = raw.get("business_status")
        result = raw.get("result") if isinstance(raw.get("result"), dict) else None
        historical = raw.get("historical_result") if isinstance(raw.get("historical_result"), dict) else None
        if historical and not result:
            current = {"text": historical.get("text") or "",
                       "cards": historical.get("cards") or "",
                       "coverage": historical.get("coverage"),
                       "historical": True}
        elif result:
            current = {"text": result.get("text") or "",
                       "cards": result.get("cards") or "",
                       "coverage": result.get("coverage"),
                       "historical": False}
        else:
            current = None
        conversation = raw.get("conversation") if isinstance(raw.get("conversation"), dict) else {}
        if conversation:
            # Same-frame Store/Agent projection from the host; never join
            # live chats/turns to a different Agent revision.
            chats = conversation.get("chats") or []
            turns = self._history(conversation.get("turns") or [])
        else:
            try:
                chats = self.store.list_chats()
            except (OSError, ValueError, sqlite3.Error):
                chats = []
            turns = self._history()
        display = raw.get("display") if isinstance(raw.get("display"), dict) else None
        confirmation_state = ("ACTIVE" if self._confirmation else
                              "EXPIRED" if self._confirmation_expired else "NONE")
        receipt = self._receipt_view(raw.get("receipt"))
        if self._confirmation_expired:
            # A timeout interrupts the confirmation wait; there is no current
            # submission receipt to show. Never turn that interruption into a
            # business "ERROR/UNKNOWN_OUTCOME" claim.
            receipt = None
        return {
            "context": context,
            "display": display,
            "confirmation": {
                "state": confirmation_state,
                "message": ("等待真人确认。" if confirmation_state == "ACTIVE" else
                            "确认已超时失效；未批准、未提交。" if confirmation_state == "EXPIRED" else None),
            },
            "session": {
                "user": self.user_id,
                "workbook": str(self.db_path),
                "mode": self.mode,
                "active_chat": (context or {}).get("chat"),
                "chats": chats,
            },
            "turns": turns,
            "pending": self._pending(raw),
            "candidates": self._candidates(raw),
            "tasks": self._tasks(raw),
            "task_focus": raw.get('task_focus'),
            "settings": self._settings(),
            "preview": self._confirmation_view(),
            "receipt": receipt,
            "persistence": self._persistence(raw),
            "current_result": current,
            "workspace": raw.get('workspace'),
            "busy": bool(self._busy),
            "business_status": status,
            "notice": getattr(self,'_workspace_notice',None),
            "error": error,
        }

    def snapshot(self, *, notice=None, error=None):
        with self._cond:
            if notice is not None:self._workspace_notice=notice
            if self._confirmation is not None:
                raw = (self._confirmation.get("payload") or {}).get("snapshot") or self._last
            elif self._busy:
                raw = self._last
            else:
                try:
                    raw = self.host.snapshot()
                    self._last = raw
                    self._last_context = raw.get("context")
                except SessionConflict:
                    raw = self._last
                except (OSError, ValueError, sqlite3.Error) as exc:
                    self._error = str(exc)
                    raw = self._last
            return self._project(raw, error=error if error is not None else self._error)

    # ------------------------------------------------------------------ session commands
    def _command(self, action, context=None):
        if self._closing:raise GuiError('工作台正在关闭，请重新启动。')
        expected = context or self._last_context
        if not isinstance(expected, dict):
            raise GuiError("缺少当前会话上下文，请刷新页面。")
        with self._cond:
            self._error = None
            self._workspace_notice=None
        try:
            raw = action(expected)
            with self._cond:
                self._last = raw
                self._last_context = raw.get("context")
                self._confirmation_expired = False
                self._confirmation = None
                self._error = None
            return self._project(raw)
        except Exception as exc:
            with self._cond:
                self._error = str(exc)
                try:
                    raw = self.host.snapshot()
                except Exception:
                    raw = self._last
                self._last = raw
                if isinstance(raw, dict):
                    self._last_context = raw.get("context")
            return self._project(raw, error=str(exc))

    def switch(self, chat_id, context=None):
        return self._command(lambda expected: self.host.switch_conversation(str(chat_id), expected=expected),
                             context)

    def new(self, context=None):
        return self._command(lambda expected: self.host.new_conversation(expected=expected), context)

    def resume(self, candidate_id, revision, context=None):
        return self._command(lambda expected: self.host.resume_candidate(
            str(candidate_id), int(revision), expected=expected), context)

    def pause(self, context=None):
        return self._command(lambda expected: self.host.pause_current(expected=expected), context)

    def cancel(self, context=None):
        return self._command(lambda expected: self.host.cancel_current(expected=expected), context)

    def inspect(self, context=None):
        return self._command(lambda expected: self.host.inspect_submission(expected=expected), context)

    def acknowledge_display(self, trace, context=None):
        """Mark the actual rendered result as seen; enables same-chat references."""
        return self._command(
            lambda expected: self.host.acknowledge_display(str(trace), expected=expected), context)

    def task_details(self, company_id, task_id, context=None, include_filled=False):
        if context != self.host.snapshot()['context']:
            raise GuiError('待办详情所属会话已变化，请刷新。')
        view = self.snapshot()
        view['task_details'] = self.host.task_details(company_id,task_id,include_filled=include_filled)
        return view

    def open_task(self, company_id, task_id, context=None):
        return self._command(lambda expected:self.host.open_task(company_id,task_id,expected=expected),context)

    def switch_profile(self, name, context=None):
        view = self._command(lambda expected:self.host.switch_profile(name,expected=expected),context)
        if not view.get('error'):
            connection = self.host.agent.connection
            self.mode='live'
            self.profile = connection.profile.profile_name
            self._connection_info.update(mode='live',profile=self.profile,model=connection.profile.model,
                provider=connection.profile.provider,base_url=safe_url(connection.profile.base_url),connected=True)
            view = self._project(self._last)
        return view

    def rebind_from_host(self, binding_factory, context=None):
        """Trusted Python host only. No browser actor/path authorization endpoint."""
        with self._cond:
            if self._busy or self._confirmation:
                raise GuiError('请先处理运行中的请求或预览，未重新绑定。')
            try:
                replacement = self.host.rebind(binding_factory,expected=context)
            except Exception as error:
                self._error = str(error)
                self._last = self.host.snapshot()
                self._last_context = self._last['context']
                return self._project(self._last,error=self._error)
            self.host = replacement
            self.store = replacement.store
            self.db_path = self.store.workbook.resolve()
            self.user_id = self.store.actor
            self.profiles = replacement.profiles
            connection = replacement.agent.connection
            self.profile = connection.profile.profile_name if connection else None
            self._connection_info = {'mode':replacement.agent.mode,'connected':connection is not None,
                'profile':self.profile,'model':connection.profile.model if connection else None,
                'provider':connection.profile.provider if connection else None,
                'base_url':safe_url(connection.profile.base_url) if connection else None}
            self._error = None
            self._confirmation_expired = False
            self._workspace_notice=None
            self._last = replacement.snapshot()
            self._last_context = self._last['context']
            return self._project(self._last)

    def close(self):
        self.store.close()

    def request_close(self, context):
        with self._cond:
            if self._busy or self._confirmation:raise GuiError('请先处理运行请求或当前预览。')
            with self.host._command(context):
                self.host._transition_ready()
                self._closing=True
        return {'window_close_allowed':True}
