"""Trusted assistant configuration; shared skill versions never grant user ACLs."""
import json
import sqlite3
from contextlib import closing
from .permissions import check_permission


def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS assistant_config(kind TEXT, owner TEXT, id TEXT, revision INTEGER, enabled INTEGER, body TEXT, PRIMARY KEY(kind,owner,id))')
    db.execute('CREATE TABLE IF NOT EXISTS assistant_config_history(kind TEXT, owner TEXT, id TEXT, revision INTEGER, enabled INTEGER, body TEXT, PRIMARY KEY(kind,owner,id,revision))')
    db.commit()
    return db


def configure(path, actor, kind, identifier, body, *, enabled=True, expected_revision=0, capabilities=()):
    if 'assistant.manage' not in capabilities:
        raise PermissionError('需要独立 assistant.manage 管理许可')
    if kind not in {'assistant', 'skill', 'tool'} or not identifier.strip():
        raise ValueError('配置类型或标识无效')
    from .tool_registry import REGISTRY
    if kind == 'tool':
        if identifier not in REGISTRY or body:
            raise ValueError('只能启停开发者已注册的处理器')
    else:
        required = {'name', 'tools', 'skills'} if kind == 'assistant' else {'name', 'tools', 'steps'}
        if set(body) != required or not isinstance(body['name'], str):
            raise ValueError('配置字段无效')
        if not isinstance(body['tools'], list) or any(t not in REGISTRY for t in body['tools']):
            raise ValueError('工具依赖必须已经注册')
        extra = body['skills'] if kind == 'assistant' else body['steps']
        if not isinstance(extra, list) or any(type(x) is not str or not x.strip() for x in extra):
            raise ValueError('步骤或依赖无效')
    with closing(connect(path)) as db, db:
        if not db.execute('SELECT 1 FROM users WHERE user_id=?', (actor,)).fetchone():
            raise PermissionError('未知用户')
        row = db.execute('SELECT revision FROM assistant_config WHERE kind=? AND owner=? AND id=?', (kind,actor,identifier)).fetchone()
        revision = row['revision'] if row else 0
        if revision != expected_revision:
            raise ValueError('配置已变化，请重新读取后再修改')
        encoded = json.dumps(body, ensure_ascii=False)
        values = (kind, actor, identifier, revision+1, int(enabled), encoded)
        db.execute('INSERT OR REPLACE INTO assistant_config VALUES(?,?,?,?,?,?)', values)
        db.execute('INSERT INTO assistant_config_history VALUES(?,?,?,?,?,?)', values)
        return {'id':identifier, 'revision':revision+1, 'enabled':bool(enabled)}


def read(db, actor, kind, identifier):
    row = db.execute('SELECT * FROM assistant_config WHERE owner=? AND kind=? AND id=?', (actor,kind,identifier)).fetchone()
    return None if row is None else {**dict(row), 'body':json.loads(row['body'])}


def tool_enabled(path, actor, name):
    # No migration during ordinary dispatch on an unconfigured legacy book.
    with closing(sqlite3.connect(path)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='assistant_config'").fetchone():
            return True
        row = db.execute("SELECT enabled FROM assistant_config WHERE kind='tool' AND owner=? AND id=?", (actor,name)).fetchone()
        return row is None or bool(row[0])


def refresh_assistant(agent):
    identifier = getattr(agent, 'assistant_id', None)
    if not identifier:
        return
    with closing(connect(agent.db_path)) as db:
        config = read(db, agent.user_id, 'assistant', identifier)
        if not config or not config['enabled']:
            raise PermissionError('助手已停用或不属于当前账号')
        tools = set(config['body']['tools'])
        skills = []
        for sid in config['body']['skills']:
            skill = read(db, agent.user_id, 'skill', sid)
            if skill and skill['enabled'] and set(skill['body']['tools']) <= tools:
                skills.append({'id':sid, 'revision':skill['revision'], **skill['body']})
        agent.allowed_tools = frozenset(t for t in tools if tool_enabled(agent.db_path, agent.user_id, t))
        agent.active_skills = skills
        instruction = '\n助手当前配置：' + json.dumps({'id':identifier,'revision':config['revision'],'skills':skills}, ensure_ascii=False)
        base = agent.messages[0]['content'].split('\n助手当前配置：',1)[0]
        agent.messages[0]['content'] = base + instruction
        agent.trace('assistant_config', {'assistant_id':identifier,'revision':config['revision'],'skills':skills,'tools':sorted(agent.allowed_tools)})


def use_skill(path, actor, skill_id, company_id, permitted):
    with closing(connect(path)) as db:
        if not check_permission(db, actor, company_id, 'read').allowed:
            raise PermissionError('当前用户无企业读取权限')
        skill = read(db, actor, 'skill', skill_id)
        if not skill or not skill['enabled']:
            raise PermissionError('共享能力已停用或不可访问')
        if not set(skill['body']['tools']) <= set(permitted):
            raise PermissionError('助手缺少共享能力所需工具')
        if any(not tool_enabled(path,actor,t) for t in skill['body']['tools']):
            raise PermissionError('共享能力依赖工具已停用')
        return {'skill_id':skill_id, 'revision':skill['revision'], **skill['body']}


def dispatch_allowed(path, actor, assistant_id, tool, skill_id=None):
    if not assistant_id:
        return tool != 'use_skill'
    with closing(connect(path)) as db:
        assistant = read(db,actor,'assistant',assistant_id)
        if not assistant or not assistant['enabled'] or tool not in assistant['body']['tools']:
            return False
        return tool != 'use_skill' or skill_id in assistant['body']['skills']
