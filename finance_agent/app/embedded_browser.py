"""Native WebView2 window; startup acknowledgement is separate from exit code."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def start_window(url, token):
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
    host=root/'webview_host'
    if not (host/'GuiWindow.exe').is_file():
        raise FileNotFoundError('内嵌窗口组件缺失：'+str(host))
    writable=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]/'data'
    logs=writable/'logs';logs.mkdir(parents=True,exist_ok=True)
    status=logs/('window-'+uuid.uuid4().hex+'.json')
    env=os.environ.copy();kernel=None;old_directory=None
    if getattr(sys,'frozen',False) and sys.platform=='win32':
        # PyInstaller documents this inherited DLL search path for external
        # programs. Restore the Python parent's directory immediately after spawn.
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetDllDirectoryW.argtypes=[ctypes.c_uint,ctypes.c_wchar_p]
        kernel.SetDllDirectoryW.argtypes=[ctypes.c_wchar_p]
        buffer=ctypes.create_unicode_buffer(32768)
        kernel.GetDllDirectoryW(len(buffer),buffer);old_directory=buffer.value or None
        env['PATH']=os.pathsep.join(part for part in env.get('PATH','').split(os.pathsep)
            if not part.lower().startswith(str(root).lower()+os.sep))
        kernel.SetDllDirectoryW(None)
    try:
        process=subprocess.Popen([str(host/'GuiWindow.exe'),url,str(status),token],cwd=host,env=env,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True)
    finally:
        if kernel is not None:kernel.SetDllDirectoryW(old_directory)
    print('Native window PID:',process.pid,'status:',status,flush=True)
    deadline=time.monotonic()+30;ready=False
    while process.poll() is None:
        if not ready:
            try:state=json.loads(status.read_text(encoding='utf-8-sig'))
            except (OSError,ValueError):state={}
            ready=state.get('ready') is True and state.get('ui_ready') is True
            if state.get('error') or time.monotonic()>deadline:
                process.terminate();process.wait(timeout=5)
                raise RuntimeError(state.get('error') or '内嵌窗口30秒内未就绪，日志：'+str(status))
            if ready:print('Native window ready',flush=True)
        time.sleep(.1)
    if not ready:
        try:
            state=json.loads(status.read_text(encoding='utf-8-sig'))
            ready=state.get('ready') is True and state.get('ui_ready') is True
        except (OSError,ValueError):pass
    if process.returncode!=0 or not ready:
        raise RuntimeError('内嵌窗口未正常显示或异常退出，代码%s；日志：%s'%(process.returncode,status))
