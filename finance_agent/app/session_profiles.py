"""Existing profile lookup for trusted session adapters; no config/credential writes."""
import os
from .model_config import (DEFAULT_TEMPLATE, DEFAULT_LOCAL, ModelConnection,
                           ProfileError, resolve_connection, visible_profiles)


class ExistingProfiles:
    def __init__(self, *, template=DEFAULT_TEMPLATE, local=DEFAULT_LOCAL):
        self.options = {'template': template, 'local': local}

    def list(self, actor):
        return [{key: row[key] for key in ('profile_name','provider','model','scope')}
                for row in visible_profiles(actor, **self.options)]

    def resolve(self, actor, name=None):
        if name is not None and (type(name) is not str or not name):
            raise ProfileError('请选择已有的模型配置。')
        bound = resolve_connection(actor, name, require_key=False, **self.options)
        bound.authorize(actor)
        from .win_vault import WindowsVault, profile_target, CredentialError
        try:
            secret = WindowsVault().read(profile_target(bound.profile, actor))
        except CredentialError:
            secret = None
        secret = secret or os.environ.get(bound.profile.api_key_env, '').strip()
        if not secret:
            raise ProfileError('已有配置缺少其绑定的 API 凭据，未切换。')
        return ModelConnection(bound.profile, secret)
