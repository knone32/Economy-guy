"""Thin UI commands over the original task/material/profile services.

No business state lives here. Commands use SessionHost's revision lock and
the same blocking human confirmation callback as the original interface.
"""
from pathlib import Path
from contextlib import closing
import base64
import json
import uuid


class WorkspaceActions:
    def task_change(self, value, context=None):
        def change(expected):
            from .tasks import manage_task, ACTIONS
            from .persistence import ManagementIntent, ManagementTurn, confirm_management
            action=value.get('action')
            if action not in ACTIONS-{'show'}:raise ValueError('请选择有效的任务操作。')
            with self.host._command(expected):
                self.host._transition_ready()
                actor=self.store.actor
                args={k:value[k] for k in ('task_id','year','month','note') if k in value}
                text='任务操作：'+json.dumps({**args,'company_id':value.get('company_id'),'action':action},ensure_ascii=False)
                intent=ManagementIntent(actor,'task',text,action,turn=ManagementTurn(actor))
                try:
                    def service(witness):
                        return manage_task(self.db_path,actor,value.get('company_id'),action,intent=witness,**args)
                    result=service(intent)
                    if result['status']=='WAITING_CONFIRMATION':
                        if self.host._approval('确认任务更改',text+'\n仅管理任务；不会自动修改发票。','task') is True:
                            result=service(confirm_management(intent,result['data']))
                        else:result={'status':'CANCELLED','error':'已取消任务更改，未保存。'}
                    if not result.get('ok') and result['status']!='CANCELLED':
                        raise ValueError(result.get('error') or result['status'])
                    self._workspace_notice=result.get('error') or '任务已保存；请查看待办详情。'
                finally:intent.turn.active=False
            return self.host.snapshot()
        return self._start_action(change,context)

    def material_upload(self, value, context=None):
        from .materials import import_material
        def change(expected):
            with self.host._command(expected):
                self.host._transition_ready()
                name=Path(str(value.get('name',''))).name
                if Path(name).suffix.lower() not in {'.docx','.xlsx','.pdf'}:
                    raise ValueError('请选择docx、xlsx或文字PDF。')
                data=base64.b64decode(value.get('content',''),validate=True)
                if not 0<len(data)<=10_000_000:raise ValueError('资料为空或超过10MB。')
                root=self.session_path.parent/'uploads'/uuid.uuid4().hex;root.mkdir(parents=True)
                source=root/name
                try:
                    source.write_bytes(data)
                    result=import_material(self.db_path,self.user_id,value.get('company_id'),source,
                        material_id=value.get('material_id') or None)
                finally:source.unlink(missing_ok=True);root.rmdir()
                self._workspace_notice='资料已保存，未发布为规则。资料编号 '+result['material_id']+'；版本 '+str(result['version'])+'；来源单元 '+str(result['paragraph_count'])
            return self.host.snapshot()
        return self._command(change,context)

    def material_source(self, value, context=None):
        from .materials import get_paragraph,source_label
        from .stage2_schema import open_existing
        def change(expected):
            with self.host._command(expected):
                self.host._transition_ready()
                with closing(open_existing(self.db_path,readonly=True)) as db:
                    source=get_paragraph(db,self.user_id,str(value.get('material_id','')),int(value.get('version',0)),int(value.get('paragraph_id',0)))
                self._workspace_notice=source_label(source)+'\n'+source['text']
            return self.host.snapshot()
        return self._command(change,context)

    def profile_action(self, value, context=None):
        def change(expected):
            from .model_config import resolve_connection
            from .win_vault import WindowsVault,profile_target
            from .model_transport import ModelTransport
            with self.host._command(expected):
                self.host._transition_ready()
                name=value.get('profile_name')
                profile=resolve_connection(self.user_id,name,require_key=False,**self.profiles.options).profile
                if value.get('action')=='forget':
                    if self.host._approval('忘记已保存密钥',f'配置 {profile.profile_name}，模型 {profile.model}。仅移除该Windows用户保存的密钥；环境变量若仍存在，仍可使用。','profile') is True:
                        WindowsVault().forget(profile_target(profile,self.user_id))
                        # Retire any in-memory connection using the forgotten key.
                        if self.profile==name:self._refresh_model()
                        message='已忘记本机保存的密钥。'
                    else:message='已取消，密钥未移除。'
                elif value.get('action')=='probe':
                    connection=self.profiles.resolve(self.user_id,name)
                    from .trace import write_trace
                    trace_id=uuid.uuid4().hex
                    def trace(event,data):
                        if self.trace_path:write_trace(self.trace_path,'profile-diagnostic',trace_id,event,data,metadata={'actor':self.user_id})
                    message=ModelTransport(connection,trace).probe(lambda:True)
                else:raise ValueError('请选择检查连接或忘记密钥。')
                self._workspace_notice=message
            return self.host.snapshot()
        return self._start_action(change,context)

    def _refresh_model(self):
        old=self.host.agent
        replacement=self.host._hydrate(self._factory(self.user_id,self.db_path))
        old.retire_session();self.host._agent=replacement

    def local_mode(self, action, context=None):
        def change(expected):
            with self.host._command(expected):
                self.host._transition_ready()
                if action=='mock':
                    from .tui import offline_model
                    self.mode='mock';self._model=offline_model
                elif action=='live':self.mode='live'
                else:raise ValueError('请选择真实模型或固定脚本诊断。')
                self._refresh_model()
                self._workspace_notice='已启用固定脚本诊断；不能理解任意中文，不计为Live。' if action=='mock' else '已切回真实模型配置。'
            return self.host.snapshot()
        return self._command(change,context)

    def native_workbook(self, path, context=None):
        """Called only by the native picker with a separate, non-page token."""
        from .cli_workspaces import missing_migrations,workspace_users,upgrade_workspace
        def change(expected):
            with self.host._command(expected):
                self.host._transition_ready()
                book=Path(path).resolve(strict=True);workspace_users(book)
                if book==self.db_path:raise ValueError('该账簿已经打开。')
                pending=missing_migrations(book)
                if pending:
                    body='账簿 '+str(book)+'\n所需升级：'+', '.join(sorted(pending))+'\n确认后先创建备份，再由原升级器核对业务行不变。'
                    if self.host._approval('备份并升级所选账簿',body,'workspace') is not True:
                        self._workspace_notice='已取消账簿升级，未打开。';return self.host.snapshot()
                    backup=upgrade_workspace(book,backup=True)
                    self._workspace_notice='升级完成，备份：'+str(backup)
                else:self._workspace_notice='已登记本机所选账簿；请从受信绑定列表选择账号进入。'
                self._register_book(book)
            return self.host.snapshot()
        return self._start_action(change,context)
