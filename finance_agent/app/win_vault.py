"""Generic Windows credentials scoped to the current OS user and machine."""
import ctypes as c
from ctypes import wintypes as w
from hashlib import sha256
import json
import os

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
MAX_BLOB_BYTES = 2560


class CredentialError(RuntimeError):
    """The system store is unavailable or could not perform the requested operation."""


class _Credential(c.Structure):
    _fields_ = [
        ("Flags", w.DWORD), ("Type", w.DWORD), ("TargetName", w.LPWSTR),
        ("Comment", w.LPWSTR), ("LastWritten", w.FILETIME), ("CredentialBlobSize", w.DWORD),
        ("CredentialBlob", c.POINTER(c.c_ubyte)), ("Persist", w.DWORD),
        ("AttributeCount", w.DWORD), ("Attributes", c.c_void_p),
        ("TargetAlias", w.LPWSTR), ("UserName", w.LPWSTR),
    ]


def profile_target(profile):
    # Endpoint/model changes must never silently forward a saved key to a new connection.
    identity = [profile.profile_name, profile.scope, profile.owner_user_id, profile.provider,
                profile.base_url, profile.model, profile.api_key_env, profile.protocol]
    token = sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()
    return "Economy-guy/Profile/" + token


class WindowsVault:
    def __init__(self):
        if os.name != "nt":
            raise CredentialError("当前系统不支持 Windows 凭据管理器。")
        try:
            api = c.WinDLL("Advapi32.dll", use_last_error=True)
        except OSError as error:
            raise CredentialError("无法打开 Windows 凭据管理器。") from error
        ptr = c.POINTER(_Credential)
        api.CredReadW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.POINTER(ptr)]
        api.CredReadW.restype = w.BOOL
        api.CredWriteW.argtypes = [ptr, w.DWORD]
        api.CredWriteW.restype = w.BOOL
        api.CredDeleteW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD]
        api.CredDeleteW.restype = w.BOOL
        api.CredFree.argtypes = [c.c_void_p]
        api.CredFree.restype = None
        self._api = api

    def read(self, target):
        credential = c.POINTER(_Credential)()
        if not self._api.CredReadW(target, CRED_TYPE_GENERIC, 0, c.byref(credential)):
            if c.get_last_error() == ERROR_NOT_FOUND:
                return None
            raise CredentialError("无法读取 Windows 保存的凭据。")
        try:
            entry = credential.contents
            raw = c.string_at(entry.CredentialBlob, entry.CredentialBlobSize)
            return raw.decode("utf-16-le").rstrip(chr(0)) or None
        except UnicodeError:
            raise CredentialError("Windows 保存的凭据格式无法读取。") from None
        finally:
            self._api.CredFree(credential)

    def write(self, target, secret):
        raw = bytearray(secret.encode("utf-16-le"))
        if not 0 < len(raw) <= MAX_BLOB_BYTES:
            raise CredentialError("密钥长度超出 Windows 凭据限制。")
        blob = (c.c_ubyte * len(raw)).from_buffer(raw)
        try:
            entry = _Credential(Type=CRED_TYPE_GENERIC, TargetName=target,
                                CredentialBlobSize=len(raw), CredentialBlob=blob,
                                Persist=CRED_PERSIST_LOCAL_MACHINE, UserName="Economy-guy")
            if not self._api.CredWriteW(c.byref(entry), 0):
                raise CredentialError("无法将密钥保存到 Windows 凭据管理器。")
        finally:
            c.memset(blob, 0, len(raw))

    def forget(self, target):
        if not self._api.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
            if c.get_last_error() != ERROR_NOT_FOUND:
                raise CredentialError("无法移除 Windows 保存的凭据。")
