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
    def detach_inactive_for_new_matter(self,seq):
        """Keep paused rows/tombstones; only detach this chat's inactive pointer."""
        self.validate()
        if self.invoice_token is None:return
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            token=self.invoice_token
            if self._candidate_token(db)!=token or self._turn_invoice_tokens.get(seq)!=token:
                raise ValueError('事项归属修订已变化，请刷新。')
            row=db.execute('SELECT state FROM invoice_candidates WHERE id=? AND revision=? AND workbook=? AND actor=?',
                (*token,self.identity,self.actor)).fetchone()
            if row is None or row['state'] not in {'PAUSED','CANCELLED','COMPLETED'}:
                raise ValueError('旧事项尚未处置，不能开启新事项。')
            changed=db.execute("UPDATE chats SET candidate_id=NULL,candidate_revision=NULL,invoice_pending=NULL WHERE id=? AND workbook=? AND actor=? AND state='ACTIVE'",
                (self.chat,self.identity,self.actor)).rowcount
            if changed!=1:raise ValueError('会话归属已变化。')
        self.invoice_token=None
        self._turn_invoice_tokens[seq]=None

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
        """Revalidate this matter and claim a new revision, never old approval."""
        from contextlib import closing
        from .business_sources import recover_candidate
        from .references import rebind_candidate_collection
        from .stage2_schema import open_existing
        self.validate()
        # One attached SQLite transaction updates both identity-only anchors
        # and the original Store row. Any validation/persistence error rolls
        # back both, leaving the paused candidate and its revision unchanged.
        with closing(open_existing(self.workbook)) as db,db:
            db.execute('ATTACH DATABASE ? AS candidate_store',(self.path.resolve().as_uri()+'?mode=rw',))
            db.execute('BEGIN IMMEDIATE')
            chat=db.execute("SELECT candidate_id,candidate_revision FROM candidate_store.chats WHERE id=? AND workbook=? AND actor=? AND state='ACTIVE'",
                (self.chat,self.identity,self.actor)).fetchone()
            actual=(chat['candidate_id'],chat['candidate_revision']) if chat and chat['candidate_id'] else None
            if chat is None or actual!=self.invoice_token:raise ValueError('当前会话或事项修订已变化。')
            row=db.execute("""SELECT pending FROM candidate_store.invoice_candidates WHERE id=? AND revision=?
                AND workbook=? AND actor=? AND state IN ('ACTIVE','PAUSED')""",
                (candidate_id,revision,self.identity,self.actor)).fetchone()
            if row is None:raise ValueError('单票候选已更新或结束，请重新查看待续单票。')
            pending=recover_candidate(json.loads(row['pending']),actor=self.actor,book=self.workbook)
            claimed=revision+1
            if pending.get('reference_collection'):
                previous=pending['reference_collection']
                pending['reference_collection']=rebind_candidate_collection(db,self.actor,previous,
                    'candidate:'+candidate_id+':'+str(claimed)+':'+uuid4().hex)
                pending['provenance']['reference_collection']={'kind':'revalidated_matter_collection',
                    'candidate_id':candidate_id,'revision':claimed,'previous_collection':previous}
            changed=db.execute("""UPDATE candidate_store.invoice_candidates
                SET pending=?,revision=revision+1,state='ACTIVE',updated=CURRENT_TIMESTAMP
                WHERE id=? AND revision=? AND workbook=? AND actor=? AND state IN ('ACTIVE','PAUSED')""",
                (json.dumps(pending,ensure_ascii=False),candidate_id,revision,self.identity,self.actor)).rowcount
            if changed!=1:raise ValueError('单票候选修订冲突，请重新查看。')
            changed=db.execute("""UPDATE candidate_store.chats SET candidate_id=?,candidate_revision=?,invoice_pending=?
                WHERE id=? AND workbook=? AND actor=? AND state='ACTIVE'""",
                (candidate_id,claimed,self._invoice_pending_json(pending),self.chat,self.identity,self.actor)).rowcount
            if changed!=1:raise ValueError('Invoice candidate is outside the active chat')
        self.invoice_token=candidate_id,claimed
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
