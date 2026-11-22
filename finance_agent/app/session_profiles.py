"""Existing profile lookup for trusted session adapters; no config/credential writes."""
import os
import getpass
from pathlib import Path
from .model_config import (DEFAULT_TEMPLATE, DEFAULT_LOCAL, ModelConnection,
                           ProfileError, resolve_connection, visible_profiles)


class ProfileStartupError(ProfileError):
    def __init__(self, message, diagnostic):
        super().__init__(message)
        self.diagnostic = diagnostic


class ExistingProfiles:
    def __init__(self, *, template=DEFAULT_TEMPLATE, local=DEFAULT_LOCAL):
        self.options = {'template': template, 'local': local}

    def list(self, actor):
        return [{key: row[key] for key in ('profile_name','provider','model','scope')}
                for row in visible_profiles(actor, **self.options)]

    def resolve(self, actor, name=None):
        return self.resolve_with_diagnostics(actor,name)[0]

    def resolve_with_diagnostics(self, actor, name=None):
        if name is not None and (type(name) is not str or not name):
            raise ProfileError('请选择已有的模型配置。')
        try:windows_user=os.getlogin()
        except OSError:windows_user=getpass.getuser()
        diagnostic = {'status':'CONFIG_UNAVAILABLE','actor':actor,'windows_user':windows_user,
            'template_path':str(Path(self.options['template']).resolve()),
            'local_path':str(Path(self.options['local']).resolve()),'requested_profile_supplied':name is not None}
        try:
            bound = resolve_connection(actor, name, require_key=False, **self.options)
        except ProfileError as error:
            raise ProfileStartupError(str(error),diagnostic) from None
        bound.authorize(actor)
        from .win_vault import WindowsVault, profile_target, CredentialError
        diagnostic.update(profile=bound.metadata(),credential_identity=profile_target(bound.profile,actor),
            environment_name=bound.profile.api_key_env,environment_present=bool(os.environ.get(bound.profile.api_key_env,'').strip()))
        try:
            secret = WindowsVault().read(profile_target(bound.profile, actor))
            diagnostic['vault_status'] = 'FOUND' if secret else 'NOT_FOUND'
        except CredentialError:
            secret = None
            diagnostic['vault_status'] = 'UNAVAILABLE'
        diagnostic['credential_source'] = 'windows_vault' if secret else 'profile_environment' if diagnostic['environment_present'] else None
        secret = secret or os.environ.get(bound.profile.api_key_env, '').strip()
        if not secret:
            diagnostic['status'] = 'CREDENTIAL_STORE_UNAVAILABLE' if diagnostic['vault_status']=='UNAVAILABLE' else 'CREDENTIAL_NOT_FOUND'
            message = '凭据存储不可访问，且当前进程没有该 Profile 指定的密钥环境变量。' if diagnostic['vault_status']=='UNAVAILABLE' else '该 Profile 凭据未找到；请在同一 Windows 用户环境使用原配置入口补齐。'
            raise ProfileStartupError(message,diagnostic)
        diagnostic['status'] = 'CONFIGURED'
        return ModelConnection(bound.profile, secret), diagnostic
