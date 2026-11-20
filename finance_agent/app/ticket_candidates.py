"""Trusted unapproved business candidates, independent of transcript lifetime.

Revisions are optimistic concurrency tokens, never approval credentials. Terminal
rows remain tombstones so delayed windows cannot resurrect cancelled work.
"""
import json
from uuid import uuid4


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS invoice_candidates(
        id TEXT PRIMARY KEY, workbook TEXT NOT NULL, actor TEXT NOT NULL,
        revision INTEGER NOT NULL, state TEXT NOT NULL
          CHECK(state IN ('ACTIVE','PAUSED','CANCELLED','COMPLETED')),
        pending TEXT NOT NULL, updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    columns = {row['name'] for row in db.execute('PRAGMA table_info(chats)')}
    for column, kind in (('candidate_id','TEXT'), ('candidate_revision','INTEGER')):
        if column not in columns:
            db.execute(f'ALTER TABLE chats ADD COLUMN {column} {kind}')
    # Additive migration preserves server-owned origin data from the v1 patch.
    for row in db.execute('SELECT id,workbook,actor,invoice_pending FROM chats WHERE invoice_pending IS NOT NULL AND candidate_id IS NULL').fetchall():
        payload = json.loads(row['invoice_pending'])
        candidate_id = uuid4().hex
        db.execute('INSERT INTO invoice_candidates(id,workbook,actor,revision,state,pending) VALUES (?,?,?,1,?,?)',
                   (candidate_id,row['workbook'],row['actor'],'ACTIVE',json.dumps(payload['pending'],ensure_ascii=False)))
        db.execute('UPDATE chats SET candidate_id=?,candidate_revision=1 WHERE id=?', (candidate_id,row['id']))


class TicketCandidates:
    def validate_invoice_revision(self):
        self.validate()
        with self.connection() as db:
            if self._candidate_token(db) != self.invoice_token:
                raise ValueError('单票候选修订已变化，请重新查看待续单票。')
            if self.invoice_token and not db.execute('''SELECT 1 FROM invoice_candidates
                WHERE id=? AND revision=? AND workbook=? AND actor=?''',
                (*self.invoice_token,self.identity,self.actor)).fetchone():
                raise ValueError('单票候选修订已变化，请重新查看待续单票。')

    def _candidate_token(self, db):
        row = db.execute('SELECT candidate_id,candidate_revision FROM chats WHERE id=? AND workbook=? AND actor=?',
                         (self.chat,self.identity,self.actor)).fetchone()
        return (row['candidate_id'],row['candidate_revision']) if row and row['candidate_id'] else None

    def _persist_candidate(self, db, pending, state, expected):
        if state not in {'ACTIVE','PAUSED','CANCELLED','COMPLETED'}:
            raise ValueError('Invalid invoice candidate state')
        if self._candidate_token(db) != expected:
            raise ValueError('单票候选修订已变化，请重新查看待续单票。')
        encoded = self._invoice_pending_json(pending) if pending is not None else None
        payload = json.loads(encoded)['pending'] if encoded else None
        if expected:
            candidate_id, revision = expected
            row = db.execute('SELECT pending,state FROM invoice_candidates WHERE id=? AND workbook=? AND actor=? AND revision=?',
                             (candidate_id,self.identity,self.actor,revision)).fetchone()
            if row is not None and row['state'] == state and payload is None:
                return expected
            if row is None or row['state'] not in {'ACTIVE','PAUSED'}:
                raise ValueError('单票候选已更新或结束，请重新查看待续单票。')
            serialized = json.dumps(payload,ensure_ascii=False) if payload is not None else row['pending']
            # A read-only insertion does not manufacture a new business revision.
            if serialized == row['pending'] and state == row['state']:
                token = expected
            else:
                changed = db.execute('''UPDATE invoice_candidates SET pending=?,state=?,revision=revision+1,updated=CURRENT_TIMESTAMP
                    WHERE id=? AND revision=? AND workbook=? AND actor=? AND state IN ('ACTIVE','PAUSED')''',
                    (serialized,state,candidate_id,revision,self.identity,self.actor)).rowcount
                if changed != 1:
                    raise ValueError('单票候选修订冲突，请重新查看。')
                token = candidate_id, revision + 1
        elif payload is not None:
            candidate_id = uuid4().hex
            db.execute('INSERT INTO invoice_candidates(id,workbook,actor,revision,state,pending) VALUES (?,?,?,1,?,?)',
                       (candidate_id,self.identity,self.actor,state,json.dumps(payload,ensure_ascii=False)))
            token = candidate_id, 1
        else:
            token = None
        visible = encoded if state == 'ACTIVE' else None
        db.execute('''UPDATE chats SET candidate_id=?,candidate_revision=?,invoice_pending=?,updated=CURRENT_TIMESTAMP WHERE id=?''',
                   (*(token or (None,None)),visible,self.chat))
        return token

    def list_invoice_candidates(self):
        from .business_sources import recover_candidate
        self.validate()
        with self.connection() as db:
            rows = db.execute('''SELECT id,revision,state,pending FROM invoice_candidates
                WHERE workbook=? AND actor=? AND state IN ('ACTIVE','PAUSED') ORDER BY updated DESC,rowid DESC''',
                (self.identity,self.actor)).fetchall()
        found = []
        for row in rows:
            pending = json.loads(row['pending'])
            try:
                recover_candidate(pending,actor=self.actor,book=self.workbook)
            except (ValueError,PermissionError):
                continue
            found.append(dict(row) | {'pending':pending})
        return found

    def resume_invoice_candidate(self, candidate_id, revision):
        """Claim a fresh revision; restoring identical data retires old approvals."""
        from .business_sources import recover_candidate
        self.validate()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('''SELECT pending FROM invoice_candidates WHERE id=? AND revision=?
                AND workbook=? AND actor=? AND state IN ('ACTIVE','PAUSED')''',
                (candidate_id,revision,self.identity,self.actor)).fetchone()
            if row is None:
                raise ValueError('单票候选已更新或结束，请重新查看待续单票。')
            pending = json.loads(row['pending'])
            recover_candidate(pending,actor=self.actor,book=self.workbook)
            changed = db.execute('''UPDATE invoice_candidates SET revision=revision+1,state='PAUSED',updated=CURRENT_TIMESTAMP
                WHERE id=? AND revision=? AND workbook=? AND actor=? AND state IN ('ACTIVE','PAUSED')''',
                (candidate_id,revision,self.identity,self.actor)).rowcount
            if changed != 1:
                raise ValueError('单票候选已更新或结束，请重新查看待续单票。')
            claimed = revision+1
            changed = db.execute('''UPDATE chats SET candidate_id=?,candidate_revision=?,invoice_pending=?
                WHERE id=? AND workbook=? AND actor=? AND state='ACTIVE' ''',
                (candidate_id,claimed,self._invoice_pending_json(pending),self.chat,self.identity,self.actor)).rowcount
            if changed != 1:
                raise ValueError('Invoice candidate is outside the active chat')
        self.invoice_token = candidate_id,claimed
        return pending

    def pause_invoice_candidate(self):
        self.validate()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            token = self._persist_candidate(db,None,'PAUSED',self.invoice_token)
        self.invoice_token = token

    def checkpoint_invoice_candidate(self, seq, pending):
        """Persist business data before displaying approval, without its tokens."""
        self.validate()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute("SELECT 1 FROM turns WHERE chat=? AND seq=? AND state='RUNNING'",
                              (self.chat,seq)).fetchone():
                raise ValueError('Turn is no longer active')
            token = self._persist_candidate(db,pending,'PAUSED',self._turn_invoice_tokens.get(seq))
        self.invoice_token = token
        self._turn_invoice_tokens[seq] = token
