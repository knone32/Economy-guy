"""Local transcript and unapproved candidate store; business facts stay in SQLite."""
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
from .ticket_candidates import TicketCandidates, initialize as initialize_candidates


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


def _reference_state_json(state):
    """Validate server metadata only; it never contains values or approvals."""
    if (type(state) is not dict or set(state) != {'version', 'retired', 'invoice_query'}
            or type(state['version']) is not int or state['version'] != 1
            or type(state['retired']) is not bool):
        raise ValueError('Invalid reference state')
    key = state['invoice_query']
    if key is not None and (type(key) is not dict or set(key) != {'company_id', 'invoice_no'}
                            or any(type(v) is not str or not v or len(v) > 80 for v in key.values())):
        raise ValueError('Invalid reference query key')
    if state['retired'] and key is not None:
        raise ValueError('Retired reference cannot retain a query key')
    return json.dumps(state, ensure_ascii=False)


class SessionStore(TicketCandidates):
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
                  focus TEXT, task TEXT, boundary INTEGER NOT NULL DEFAULT 0, reference_state TEXT,
                  invoice_pending TEXT);
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
            """)
            # The old v1 store is upgraded additively in this same transaction.
            if 'reference_state' not in {r['name'] for r in db.execute('PRAGMA table_info(chats)')}:
                db.execute('ALTER TABLE chats ADD COLUMN reference_state TEXT')
            if 'invoice_pending' not in {r['name'] for r in db.execute('PRAGMA table_info(chats)')}:
                db.execute('ALTER TABLE chats ADD COLUMN invoice_pending TEXT')
            initialize_candidates(db)
            self.chat = self._active(db)
            self.invoice_token = self._candidate_token(db)
            self._turn_invoice_tokens = {}
            self._turn_invoice_states = {}
            db.execute("UPDATE turns SET state='INTERRUPTED' WHERE chat=? AND state='RUNNING'", (self.chat,))

    def _active(self, db):
        row = db.execute("SELECT id FROM chats WHERE workbook=? AND actor=? AND state='ACTIVE'",
                         (self.identity, self.actor)).fetchone()
        if row:
            return row[0]
        chat = uuid4().hex
        db.execute("INSERT INTO chats(id,workbook,actor) VALUES (?,?,?)", (chat,self.identity,self.actor))
        return chat

    def list_chats(self):
        """Recent conversations for the locked actor and workbook."""
        self.validate()
        with self.connection() as db:
            rows = db.execute("""SELECT c.id, c.updated, c.state, substr(t.request,1,120) AS first_request, t.calls
                FROM chats c LEFT JOIN turns t ON t.seq=(SELECT seq FROM turns
                    WHERE chat=c.id AND request<>'' ORDER BY seq LIMIT 1)
                WHERE c.workbook=? AND c.actor=?
                ORDER BY (c.state='ACTIVE') DESC, c.updated DESC, c.rowid DESC LIMIT 20""",
                (self.identity, self.actor)).fetchall()
        chats = []
        for row in rows:
            chat = dict(row)
            title = " ".join((chat.pop("first_request") or "").split())
            calls = json.loads(chat.pop("calls") or "[]")
            if isinstance(calls, dict):
                calls = calls["tools"]
            chat["company_ids"] = sorted({c["scope"]["company_id"] for c in calls
                                          if (c.get("scope") or {}).get("company_id")})
            chat["title"] = (title[:36] + "…" if len(title) > 36 else title) or "空白对话"
            chats.append(chat)
        return chats

    def _archive_current(self, db):
        if db.execute("SELECT 1 FROM turns WHERE chat=? AND state='RUNNING'", (self.chat,)).fetchone():
            raise SessionBusyError("Conversation has a running turn")
        changed = db.execute("""UPDATE chats SET state='ARCHIVED',updated=CURRENT_TIMESTAMP
                              WHERE id=? AND workbook=? AND actor=? AND state='ACTIVE'""",
                             (self.chat, self.identity, self.actor)).rowcount
        if changed != 1:
            raise ValueError("Active conversation changed")

    def switch_chat(self, chat):
        self.validate()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            target = db.execute("SELECT state FROM chats WHERE id=? AND workbook=? AND actor=?",
                                (chat, self.identity, self.actor)).fetchone()
            if target is None:
                raise ValueError("Conversation is outside the current actor/workbook")
            if chat == self.chat and target["state"] == "ACTIVE":
                return
            if target["state"] != "ARCHIVED":
                raise ValueError("Conversation is not archived")
            self._archive_current(db)
            db.execute("UPDATE chats SET state='ACTIVE',updated=CURRENT_TIMESTAMP WHERE id=?", (chat,))
            # A previously interrupted process never transfers running tool work.
            db.execute("UPDATE turns SET state='INTERRUPTED' WHERE chat=? AND state='RUNNING'", (chat,))
        self.chat = chat
        with self.connection() as db:
            self.invoice_token = self._candidate_token(db)

    def new_chat(self, focus):
        self.validate()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._archive_current(db)
            new = self._active(db)
            db.execute("UPDATE chats SET focus=? WHERE id=?", (json.dumps(focus), new))
        self.chat = new
        self.invoice_token = None

    def select_focus(self, focus, task):
        self.validate()
        with self.connection() as db:
            db.execute("UPDATE chats SET focus=?,task=?,updated=CURRENT_TIMESTAMP WHERE id=?",
                       (json.dumps(focus),json.dumps(task),self.chat))

    def boundary(self, message):
        self.validate()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute("SELECT 1 FROM chats WHERE id=? AND workbook=? AND actor=? AND state='ACTIVE'",
                              (self.chat,self.identity,self.actor)).fetchone():
                raise ValueError('Conversation is outside the active actor/workbook')
            seq = db.execute("INSERT INTO turns(chat,state,request,display) VALUES (?,'COMPLETED','',?)",
                             (self.chat, json.dumps([["会话分界",message]], ensure_ascii=False))).lastrowid
            retired = _reference_state_json({'version':1,'retired':True,'invoice_query':None})
            token = self._persist_candidate(db,None,'CANCELLED',self.invoice_token)
            db.execute("UPDATE chats SET boundary=?,task=NULL,reference_state=?,invoice_pending=NULL,updated=CURRENT_TIMESTAMP WHERE id=?",
                       (seq,retired,self.chat))
        self.invoice_token = token

    def begin(self, request, mode):
        self.validate()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            # Beginning a turn retires implicit restart activation, but keeps
            # unfinished work in the explicit list. Capture its revision now.
            original_state = None
            if self.invoice_token:
                row = db.execute('SELECT state FROM invoice_candidates WHERE id=? AND revision=?',self.invoice_token).fetchone()
                original_state = row['state'] if row else None
                if row and row['state'] in {'CANCELLED','COMPLETED'}:
                    db.execute('UPDATE chats SET candidate_id=NULL,candidate_revision=NULL WHERE id=?',(self.chat,))
                    self.invoice_token = None
                else:
                    self.invoice_token = self._persist_candidate(db,None,'PAUSED',self.invoice_token)
            seq = db.execute("INSERT INTO turns(chat,state,request,mode) VALUES (?,'RUNNING',?,?)",
                             (self.chat,redact(request),mode)).lastrowid
            self._turn_invoice_tokens[seq] = self.invoice_token
            self._turn_invoice_states[seq] = original_state
            # An interrupted new turn must not resurrect a superseded/cancelled
            # older candidate. A completed turn atomically saves its new state.
            db.execute("UPDATE chats SET invoice_pending=NULL,updated=CURRENT_TIMESTAMP WHERE id=?", (self.chat,))
            return seq

    def _invoice_pending_json(self, pending):
        if pending is None:
            return None
        pending = json.loads(json.dumps(pending,ensure_ascii=False))
        if (type(pending) is not dict or pending.get('business_action') != 'single_invoice'
                or (pending.get('actor'),pending.get('workbook')) != (self.actor,str(self.workbook))
                or redact(pending) != pending):
            raise ValueError('Invalid runtime invoice candidate')
        return json.dumps({'version':1,'actor':self.actor,'workbook':self.identity,
                           'chat':self.chat,'pending':pending}, ensure_ascii=False)

    def set_invoice_pending(self, pending, *, state=None):
        """Trusted runtime/idle-cancel setter; never exposed as a model tool."""
        self.validate()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute("SELECT 1 FROM chats WHERE id=? AND workbook=? AND actor=? AND state='ACTIVE'",
                              (self.chat,self.identity,self.actor)).fetchone():
                raise ValueError('Invoice candidate is outside the active chat')
            token = self._persist_candidate(db,pending,state or ('ACTIVE' if pending is not None else 'CANCELLED'),self.invoice_token)
        self.invoice_token = token

    def set_reference_state(self, state):
        """Trusted UI/backend setter, including idle cancellation with no turn.

        This is not exposed as a model tool. The locked actor, actual workbook
        identity and active chat must still match at the point of persistence.
        """
        self.validate()
        encoded = _reference_state_json(state)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("""UPDATE chats SET reference_state=?,updated=CURRENT_TIMESTAMP
                WHERE id=? AND workbook=? AND actor=? AND state='ACTIVE'""",
                (encoded,self.chat,self.identity,self.actor)).rowcount
            if changed != 1:
                raise ValueError('Reference state is outside the active actor/workbook/chat')

    def checkpoint(self, seq, lookup=None):
        self.validate()
        with self.connection() as db:
            changed = db.execute("""UPDATE turns SET state='UNKNOWN_OUTCOME',lookup=?
                                  WHERE chat=? AND seq=? AND state IN ('RUNNING','UNKNOWN_OUTCOME')""",
                                 (lookup,self.chat,seq)).rowcount
            if changed != 1:
                raise ValueError("Turn is no longer active")

    def finish(self, seq, display, calls, trace, hint, state="COMPLETED", *, operation=None, invoice_pending=None, candidate_state=None):
        self.validate()
        if state not in {"COMPLETED","INTERRUPTED","UNKNOWN_OUTCOME"}:
            raise ValueError("Invalid terminal turn state")
        evidence = [{k: c.get(k) for k in ("id", "tool", "status", "scope", "rule")}
                    | {k: c[k] for k in ("source", "error") if k in c} for c in calls]
        if any(c["tool"] in {"manage_task","manage_preference","manage_display_preference","prepare_invoice_update"} for c in evidence):
            # Management/prepare history never restores work or approvals, but
            # must not erase the server-owned reference retirement snapshot.
            hint = ({'reference_state': hint['reference_state']}
                    if type(hint) is dict and type(hint.get('reference_state')) is dict else None)
        if operation is not None:
            evidence = {"tools": evidence, "operation": operation}
        reference_state = (_reference_state_json(hint['reference_state'])
                           if type(hint) is dict and 'reference_state' in hint else None)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute("SELECT 1 FROM chats WHERE id=? AND workbook=? AND actor=? AND state='ACTIVE'",
                              (self.chat,self.identity,self.actor)).fetchone():
                raise ValueError('Conversation is outside the active actor/workbook')
            changed = db.execute("""UPDATE turns SET display=?,calls=?,trace=?,hint=?,state=?
                          WHERE chat=? AND seq=? AND state IN ('RUNNING','UNKNOWN_OUTCOME')""",
                       (json.dumps(redact(display),ensure_ascii=False),json.dumps(redact(evidence)),trace,
                        json.dumps(hint),state,self.chat,seq)).rowcount
            if changed != 1:
                raise ValueError('Turn is no longer active')
            if reference_state is not None:
                db.execute('UPDATE chats SET reference_state=? WHERE id=?', (reference_state,self.chat))
            expected = self._turn_invoice_tokens.get(seq)
            token = self._persist_candidate(db,invoice_pending if state == 'COMPLETED' else None,
                candidate_state or ('ACTIVE' if state == 'COMPLETED' and invoice_pending is not None
                    else 'COMPLETED' if state == 'UNKNOWN_OUTCOME'
                    else 'PAUSED' if state == 'INTERRUPTED' or self._turn_invoice_states.get(seq) == 'PAUSED'
                    else 'CANCELLED'),expected)
        self.invoice_token = token
        self._turn_invoice_tokens.pop(seq,None)
        self._turn_invoice_states.pop(seq,None)

    def history(self):
        self.validate()
        with self.connection() as db:
            chat = db.execute("SELECT focus,task,boundary,reference_state,invoice_pending,candidate_id,candidate_revision FROM chats WHERE id=? AND workbook=? AND actor=? AND state='ACTIVE'",
                              (self.chat,self.identity,self.actor)).fetchone()
            if chat is None:
                raise ValueError('Conversation is outside the active actor/workbook')
            # A transcript envelope is never the authority after a revision.
            current_candidate = db.execute('''SELECT state FROM invoice_candidates WHERE id=? AND revision=?
                AND workbook=? AND actor=?''',
                (chat['candidate_id'],chat['candidate_revision'],self.identity,self.actor)).fetchone()
            rows = []
            for entry in db.execute("SELECT * FROM turns WHERE chat=? ORDER BY seq", (self.chat,)):
                row = dict(entry)
                for key in ("display","calls","hint"):
                    row[key] = json.loads(row[key]) if row[key] else None
                stored = row["calls"]
                row["operation"] = stored["operation"] if isinstance(stored, dict) else {}
                if isinstance(stored, dict):
                    row["calls"] = stored["tools"]
                rows.append(row)
        reference_state = json.loads(chat['reference_state']) if chat['reference_state'] else None
        if reference_state is not None:
            _reference_state_json(reference_state)
        candidate = (json.loads(chat['invoice_pending']) if chat['invoice_pending'] and current_candidate
                     and current_candidate['state'] == 'ACTIVE' else None)
        if candidate is not None:
            if (type(candidate) is not dict or candidate.get('version') != 1
                    or (candidate.get('actor'),candidate.get('workbook'),candidate.get('chat'))
                    != (self.actor,self.identity,self.chat)):
                raise ValueError('Saved invoice candidate identity changed')
            candidate = candidate.get('pending')
        return {key: json.loads(chat[key]) if chat[key] else None for key in ("focus","task")} | {
            'reference_state': reference_state, 'invoice_pending':candidate,
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
