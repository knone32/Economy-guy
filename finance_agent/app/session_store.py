"""Independent local transcript store. Business authority stays in the workbook."""
from contextlib import closing, contextmanager
from hashlib import sha256
import json
from pathlib import Path
import os
import sqlite3
from uuid import uuid4

from .persistence import can_manage, can_propose, require_management_confirmation, result
from .stage2_schema import open_existing
from .trace import redact


def workbook_identity(path, *, create=False):
    path = Path(path)
    before = path.stat()
    if not before.st_ino:
        raise ValueError("No stable workbook file identity")
    with closing(open_existing(path, readonly=not create)) as db, db:
        if create:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS workspace_identity
                          (singleton INTEGER PRIMARY KEY CHECK(singleton=1), id TEXT NOT NULL)""")
            db.execute("INSERT OR IGNORE INTO workspace_identity VALUES (1,?)", (uuid4().hex,))
        row = db.execute("SELECT id FROM workspace_identity WHERE singleton=1").fetchone()
    after = path.stat()
    def identity(st):
        return st.st_dev, st.st_ino, getattr(st, "st_birthtime", None)
    if not row or identity(before) != identity(after):
        raise ValueError("Workbook identity changed")
    return sha256(repr((row[0], identity(after))).encode()).hexdigest()


class SessionBusyError(OSError):
    """Another process owns this actor and workbook conversation."""


class SessionStore:
    """One active transcript per trusted actor/workbook, with an OS-held lock."""

    def __init__(self, path, workbook, actor):
        self.path, self.workbook, self.actor = Path(path), Path(workbook), actor
        self.identity = workbook_identity(self.workbook, create=True)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_id = sha256(f"{self.identity}/{actor}".encode()).hexdigest()
        self.lock = (self.path.parent / (lock_id + ".lock")).open("a+b")
        try:
            self.lock.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.close()
            raise SessionBusyError("Conversation is already open") from error
        try:
            if os.name != "nt":
                try:
                    fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError:
                    os.chmod(self.path, 0o600)
                else:
                    os.close(fd)
            self._initialize()
        except BaseException:
            self.close()
            raise

    def close(self):
        self.lock.close()

    def validate(self):
        if self.lock.closed or workbook_identity(self.workbook) != self.identity:
            raise ValueError("Workbook identity changed")

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            yield db

    def _initialize(self):
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("Unsupported session storage version")
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS chats(
                  id TEXT PRIMARY KEY, workbook TEXT NOT NULL, actor TEXT NOT NULL,
                  created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  state TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(state IN ('ACTIVE','ARCHIVED')),
                  focus TEXT, task TEXT, boundary INTEGER NOT NULL DEFAULT 0);
                CREATE UNIQUE INDEX IF NOT EXISTS active_chat
                  ON chats(workbook,actor) WHERE state='ACTIVE';
                CREATE TABLE IF NOT EXISTS turns(
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, chat TEXT NOT NULL REFERENCES chats(id),
                  state TEXT NOT NULL CHECK(state IN ('RUNNING','COMPLETED','INTERRUPTED','UNKNOWN_OUTCOME')),
                  request TEXT NOT NULL, display TEXT NOT NULL DEFAULT '[]',
                  calls TEXT NOT NULL DEFAULT '[]', trace TEXT, lookup TEXT,
                  hint TEXT, mode TEXT);
                CREATE INDEX IF NOT EXISTS turns_by_chat ON turns(chat,seq);
                CREATE TABLE IF NOT EXISTS display_preferences(
                  workbook TEXT NOT NULL, actor TEXT NOT NULL, detail TEXT NOT NULL,
                  PRIMARY KEY(workbook,actor));
                PRAGMA user_version=1;
                COMMIT;
            """)
            self.chat = self._active(db)
            db.execute("UPDATE turns SET state='INTERRUPTED' WHERE chat=? AND state='RUNNING'", (self.chat,))

    def _active(self, db):
        row = db.execute("SELECT id FROM chats WHERE workbook=? AND actor=? AND state='ACTIVE'",
                         (self.identity, self.actor)).fetchone()
        if row:
            return row[0]
        chat = uuid4().hex
        db.execute("INSERT INTO chats(id,workbook,actor) VALUES (?,?,?)", (chat,self.identity,self.actor))
        return chat

    def new_chat(self, focus):
        self.validate()
        with self.connection() as db:
            db.execute("UPDATE chats SET state='ARCHIVED',updated=CURRENT_TIMESTAMP WHERE id=?", (self.chat,))
            new = self._active(db)
            db.execute("UPDATE chats SET focus=? WHERE id=?", (json.dumps(focus), new))
        self.chat = new

    def select_focus(self, focus, task):
        self.validate()
        with self.connection() as db:
            db.execute("UPDATE chats SET focus=?,task=?,updated=CURRENT_TIMESTAMP WHERE id=?",
                       (json.dumps(focus),json.dumps(task),self.chat))

    def boundary(self, message):
        self.validate()
        with self.connection() as db:
            seq = db.execute("INSERT INTO turns(chat,state,request,display) VALUES (?,'COMPLETED','',?)",
                             (self.chat, json.dumps([["会话分界",message]], ensure_ascii=False))).lastrowid
            db.execute("UPDATE chats SET boundary=?,task=NULL,updated=CURRENT_TIMESTAMP WHERE id=?", (seq,self.chat))

    def begin(self, request, mode):
        self.validate()
        with self.connection() as db:
            seq = db.execute("INSERT INTO turns(chat,state,request,mode) VALUES (?,'RUNNING',?,?)",
                             (self.chat,redact(request),mode)).lastrowid
            db.execute("UPDATE chats SET updated=CURRENT_TIMESTAMP WHERE id=?", (self.chat,))
            return seq

    def checkpoint(self, seq, lookup=None):
        self.validate()
        with self.connection() as db:
            changed = db.execute("""UPDATE turns SET state='UNKNOWN_OUTCOME',lookup=?
                                  WHERE chat=? AND seq=? AND state IN ('RUNNING','UNKNOWN_OUTCOME')""",
                                 (lookup,self.chat,seq)).rowcount
            if changed != 1:
                raise ValueError("Turn is no longer active")

    def finish(self, seq, display, calls, trace, hint, state="COMPLETED"):
        self.validate()
        if state not in {"COMPLETED","INTERRUPTED","UNKNOWN_OUTCOME"}:
            raise ValueError("Invalid terminal turn state")
        evidence = [{k:c.get(k) for k in ("id","tool","status","scope","rule")} for c in calls]
        if any(c["tool"] in {"manage_task","manage_preference","manage_display_preference","prepare_invoice_update"} for c in evidence):
            hint = None
        with self.connection() as db:
            db.execute("""UPDATE turns SET display=?,calls=?,trace=?,hint=?,state=?
                          WHERE chat=? AND seq=? AND state IN ('RUNNING','UNKNOWN_OUTCOME')""",
                       (json.dumps(redact(display),ensure_ascii=False),json.dumps(redact(evidence)),trace,
                        json.dumps(hint),state,self.chat,seq))
            db.execute("UPDATE chats SET updated=CURRENT_TIMESTAMP WHERE id=?", (self.chat,))

    def history(self):
        self.validate()
        with self.connection() as db:
            chat = db.execute("SELECT focus,task,boundary FROM chats WHERE id=?", (self.chat,)).fetchone()
            rows = []
            for entry in db.execute("SELECT * FROM turns WHERE chat=? ORDER BY seq", (self.chat,)):
                row = dict(entry)
                for key in ("display","calls","hint"):
                    row[key] = json.loads(row[key]) if row[key] else None
                rows.append(row)
        return {key: json.loads(chat[key]) if chat[key] else None for key in ("focus","task")} | {
            "boundary":chat["boundary"],"turns":rows}

    def _read_detail(self, db):
        row = db.execute("SELECT detail FROM display_preferences WHERE workbook=? AND actor=?",
                         (self.identity,self.actor)).fetchone()
        return row[0] if row else "普通"

    def personal_detail(self):
        self.validate()
        with self.connection() as db:
            return self._read_detail(db)

    def manage_detail(self, action, value, intent=None, *, actor=None):
        if actor is not None and actor != self.actor:
            return result("DENIED",error="个人偏好身份不一致")
        self.validate()
        if action not in {"get","set","delete"} or (action == "set" and value not in {"简洁","详细","普通"}) or (action != "set" and value != ""):
            return result("INVALID_ARGUMENTS",error="请选择有效的回复详细度")
        with self.connection() as db:
            if action == "get":
                return result("SUCCESS", {"reply_detail":self._read_detail(db)})
            if not (can_manage(intent,self.actor,"display_preference",action) or
                    can_propose(intent,self.actor,"display_preference",action)):
                return result("DENIED",error="缺少可信个人偏好确认")
            db.execute("BEGIN IMMEDIATE")
            current = {"value":self._read_detail(db)}
            pending = require_management_confirmation(intent, {"action":action,"value":value}, current)
            if pending:
                return pending
            if action == "delete" or value == "普通":
                db.execute("DELETE FROM display_preferences WHERE workbook=? AND actor=?",(self.identity,self.actor))
            else:
                db.execute("""INSERT INTO display_preferences VALUES (?,?,?) ON CONFLICT(workbook,actor)
                              DO UPDATE SET detail=excluded.detail""",(self.identity,self.actor,value))
        saved = self.personal_detail()
        return result("SUCCESS",{"reply_detail":saved},{"source":"local_display_preference",
                      "preference_readback_verified": saved == (value if action == "set" else "普通")})
