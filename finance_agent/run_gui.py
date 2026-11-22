"""Run the minimal local Economy-guy GUI from finance_agent."""
from __future__ import annotations

import sys

from app.gui_delivery import main


if __name__ == "__main__":
    if getattr(sys,'frozen',False):
        from pathlib import Path
        log=Path(sys.executable).resolve().parent/'logs'
        log.mkdir(exist_ok=True)
        if sys.stdout is None:sys.stdout=(log/'startup.log').open('a',encoding='utf-8',buffering=1)
        if sys.stderr is None:sys.stderr=sys.stdout
    code=main(sys.argv[1:])
    if code and getattr(sys,'frozen',False):
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,'工作台未成功启动。请查看程序旁 logs/startup.log 中的具体原因。',
            'Economy-guy 启动失败',0x10)
    raise SystemExit(code)
