"""Launch preparation only; business execution remains in the original GUI host."""
import json
import os
from pathlib import Path
import sqlite3
import sys


def demo_paths(root=None):
    """Initialize a new official fictional fixture, never reset an existing book."""
    from .cli_workspaces import import_workspace
    root = Path(root or Path(__file__).resolve().parents[1] / 'data' / 'gui-demo')
    root.mkdir(parents=True, exist_ok=True)
    book, sessions = root / 'demo.sqlite3', root / 'sessions.sqlite3'
    if not book.exists():
        import_workspace(Path(__file__).resolve().parents[1] / 'tests/fixtures/example.xlsx', book)
        # Preexisting demo task, not a user task creation or an accepted write.
        with sqlite3.connect(book) as db:
            db.execute("""INSERT INTO tasks
                (task_id,user_id,company_id,task_type,year,month,context_json,status,created_at,updated_at)
                VALUES ('GUI-DEMO-C001','U001','C001','missing_purpose',2026,9,?,'ACTIVE',datetime('now'),datetime('now'))""",
                (json.dumps({'note':'官方虚构账簿演示待办：核对2026年9月用途缺项。'}, ensure_ascii=False),))
        print('已创建官方虚构演示账簿；不会重置已有演示或正式工作库。')
    return book.resolve(), sessions.resolve()


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        from .gui_server import main as serve
        if '--db' not in args and not any(arg.startswith('--db=') for arg in args):
            book, sessions = demo_paths(os.environ.get('ECONOMYGUY_DEMO_DIR'))
            args += ['--db', str(book)]
            if '--session' not in args and not any(arg.startswith('--session=') for arg in args):
                args += ['--session', str(sessions)]
        for option, variable in (('--profile','ECONOMYGUY_PROFILE'),('--profiles-local','ECONOMYGUY_PROFILES_LOCAL')):
            if option not in args and not any(arg.startswith(option+'=') for arg in args) and os.environ.get(variable):
                args += [option, os.environ[variable]]
        if '--open' not in args:
            args.append('--open')
        print('本机工作台；U001/U002 为比赛模拟身份，不是登录认证。')
        print('缺配置请使用原工作台配置入口；本启动器不会索取、保存或打印密钥。')
        return serve(args)
    except (ImportError, OSError, ValueError, sqlite3.Error) as error:
        print('启动准备失败（%s）。请检查 Python 3.11+、requirements.txt、可写目录及已有 Profile。' % type(error).__name__, file=sys.stderr)
        return 2
