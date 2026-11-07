"""Local TUI preferences. This file holds only recent workbook paths."""
import json
import os
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile

from .cli_workspaces import missing_migrations, workspace_users


def settings_path():
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".config")
    return base / "Economy-guy" / "recent-workbooks.json"


def recent_workbooks(path):
    if path is None:
        return []
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(entries, list):
            return [Path(x) for x in entries[:8] if isinstance(x, str) and x]
    except (OSError, ValueError):
        pass
    return []


def remember_workbook(settings, workbook):
    if settings is None:
        return
    settings.parent.mkdir(parents=True, exist_ok=True)
    paths = [workbook, *(p for p in recent_workbooks(settings) if p != workbook)]
    temporary = None
    try:
        with NamedTemporaryFile(dir=settings.parent, encoding="utf-8", mode="w", delete=False) as f:
            temporary = Path(f.name)
            json.dump([str(p) for p in paths[:8]], f, ensure_ascii=False)
        temporary.replace(settings)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def startup_workbook(default, settings, *, restore):
    recent = recent_workbooks(settings)
    if restore and recent:
        # Keep an unavailable last path visible, so the picker can explain what failed.
        candidate = recent[0]
    else:
        candidate = default
    try:
        workspace_users(candidate)
        return candidate, bool(missing_migrations(candidate))
    except (OSError, ValueError, sqlite3.Error):
        return candidate, True
