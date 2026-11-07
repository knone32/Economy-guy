"""Bounded, standalone SEC-A probes. Failed invariants stay outside unittest."""
import argparse
from contextlib import closing, redirect_stdout
from decimal import Decimal
import io
import json
from pathlib import Path
import socket
import sqlite3
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import BadZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent import Agent, scripted_model
from app.importer import initialize_database
from app.model_config import ProfileError, safe_url
from app.provenance import ScopeProof
from app.rules import SEED_RULES, import_rules
from app.stage2_schema import migrate
from app.tool_registry import handle_tool

FIXTURE = ROOT / 'tests/fixtures/example.xlsx'
SCOPE = {'company_id': 'C001', 'year': 2026, 'month': 9}
FINAL = {'role': 'assistant', 'content': '{"kind":"information","text":"finished"}'}
QUERY = '查询 C001 2026-09 的发票。'


def call(name, arguments, identifier='sec1'):
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments)
    return {'role': 'assistant', 'tool_calls': [dict(id=identifier, type='function', function=dict(name=name, arguments=arguments))]}


def run_agent(db, reply, text=QUERY, trace=None, user='U001'):
    agent = Agent(user, db, scripted_model([reply, FINAL]), mode='mock', trace_path=trace)
    return observe(agent, text)


def observe(agent, text):
    error = None
    try:
        agent.ask(text)
    except (AttributeError, UnicodeError, ValueError, TypeError, RecursionError) as exc:
        error = type(exc).__name__
    tools = [json.loads(m['content']) for m in agent.messages if m['role'] == 'tool']
    stop = (agent.last_response or {}).get('execution', {}).get('stop_reason')
    return dict(error=error, tools=tools, stop=stop)


def status(result):
    return [tool['status'] for tool in result['tools']]


def state(db):
    with closing(sqlite3.connect(db.as_uri()+'?mode=ro', uri=True)) as connection:
        return {table: connection.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
                for table in ('invoices', 'bank_transactions', 'invoice_audit', 'permissions', 'rules')}


def acl_pair(db, directory):
    reply = call('list_invoices', {**SCOPE, 'month': 8})
    attack = run_agent(db, reply, '查询 C001 的 2026-09 和 2025-08 发票。')
    control = run_agent(db, reply, '查询 C001 的 2026-08 发票。')
    rows = [row for tool in attack['tools'] if tool['ok'] for row in tool['data']]
    return not rows and status(control)==['SUCCESS'], not rows, dict(attack=status(attack), control=status(control), out_of_scope_rows=len(rows), month='2026-08')


def acl_compat(db, directory):
    raw = json.dumps(SCOPE)
    direct = handle_tool('list_invoices', raw, 'U001', db)
    foreign = ScopeProof('U001', {k: [v] for k, v in SCOPE.items()}, dict.fromkeys(SCOPE, 'user_current'))
    foreign_result = handle_tool('list_invoices', raw, 'U002', db, provenance=foreign)
    missing = run_agent(db, call('list_invoices', SCOPE), '查询 C001 发票。')
    forged = run_agent(db, call('list_invoices', {**SCOPE, 'provenance': None}))
    good = direct['ok'] and foreign_result['status']=='DENIED' and status(missing)==['AMBIGUOUS'] and status(forged)==['INVALID_ARGUMENTS']
    return good, good, dict(internal=direct['status'], cross_actor=foreign_result['status'], missing=status(missing), forged=status(forged))


def malformed(db, directory):
    before = state(db)
    cases = [
        ('duplicate', 'list_invoices', '{"company_id":"C001","company_id":"C002","year":2026,"month":9}', 'a'),
        ('json', 'list_invoices', '{', 'b'),
        ('array', 'manage_preference', '[]', 'c'),
        ('nested', 'list_invoices', '['*32+'0'+']'*32, 'd'),
        ('date', 'get_applicable_rules', {'company_id':'C001','rule_type':'purpose','business_date':'2026-02-30'}, 'e'),
        ('huge-year', 'list_invoices', {**SCOPE, 'year':10**100}, 'f'),
        ('blank', 'list_invoices', {**SCOPE, 'company_id':'\u3000'}, 'g'),
        ('action', 'manage_preference', {'company_id':'C001','action':'grant','key':'k','value':'v'}, 'h'),
        ('id', 'list_invoices', SCOPE, ''),
    ]
    evidence = {}
    for label, name, args, identifier in cases:
        got = run_agent(db, call(name, args, identifier))
        evidence[label] = dict(error=got['error'], statuses=status(got), stop=got['stop'])
    safe = all(not e['error'] and (e['statuses'] or e['stop']=='API_OR_RESPONSE_ERROR')
               and set(e['statuses']) <= {'INVALID_ARGUMENTS','DENIED','SCOPE_MISMATCH','AMBIGUOUS'} for e in evidence.values())
    return safe, before==state(db), evidence


def change_amounts(db, values):
    with closing(sqlite3.connect(db)) as c, c:
        c.executemany("UPDATE invoices SET amount_cents=? WHERE company_id='C001' AND invoice_no=?", values)


def overflow(db, directory):
    change_amounts(db, [(2**63-1, 'F001'), (2**63-1, 'F002')])
    before = state(db)
    got = handle_tool('get_finance_summary', json.dumps(SCOPE), 'U001', db)
    with closing(sqlite3.connect(db)) as c:
        integrity = c.execute('PRAGMA integrity_check').fetchone()[0]
    safe = not got['ok'] and got['data'] is None and integrity=='ok'
    return safe, safe and before==state(db), dict(status=got['status'], integrity=integrity, data_is_null=got['data'] is None)


def negative_amount(db, directory):
    change_amounts(db, [(-1, 'F002')])
    with closing(sqlite3.connect(db)) as c:
        cents = sum(r[0] for r in c.execute("SELECT amount_cents FROM invoices WHERE company_id='C001' AND invoice_date LIKE '2026-09%'"))
    rows = handle_tool('list_invoices', json.dumps(SCOPE), 'U001', db)
    summary = handle_tool('get_finance_summary', json.dumps(SCOPE), 'U001', db)
    actual = next(row['amount'] for row in rows['data'] if row['invoice_no']=='F002') if rows['ok'] else None
    total = summary['data']['invoice_total'] if summary['ok'] else None
    expected = format(Decimal(cents)/100, '.2f')
    good = actual in {None, '-0.01'} and total in {None, expected}
    return good, good, dict(amount=actual, expected='-0.01', total=total, expected_total=expected)


def long_context(db, directory):
    before = state(db)
    with patch.object(Agent, 'trace'):
        agent = Agent('U001', db, lambda *_: (_ for _ in ()).throw(AssertionError('model called')), mode='mock')
        outcome = observe(agent, 'x'*65536)
    return outcome['stop']=='CONTEXT_LIMIT', before==state(db), dict(stop=outcome['stop'], bytes=65536)


def excel(db, directory):
    from openpyxl import load_workbook

    original = db.read_bytes()
    outcomes = {}
    for case in ['missing-sheet','duplicate-header','bad-amount','bad-date','duplicate-row','damaged','missing-path','existing','valid']:
        with TemporaryDirectory(dir=directory) as temp:
            source = Path(temp)/'input.xlsx'
            target = Path(temp)/'new.db'
            if case in {'damaged','missing-path','existing','valid'}:
                if case=='damaged':
                    source.write_bytes(b'not an xlsx')
                elif case=='missing-path':
                    source = Path(temp)/'absent.xlsx'
                else:
                    source = FIXTURE
                    if case=='existing':
                        target = db
            else:
                with closing(load_workbook(FIXTURE)) as book:
                    sheet = book['发票']
                    row = next(i for i, cells in enumerate(sheet.values,1) if '开票日期' in cells and '发票编号' in cells)
                    headers = [cell.value for cell in sheet[row]]
                    if case=='missing-sheet':
                        del book['发票']
                    elif case=='duplicate-header':
                        column = len(headers)+1
                        sheet.cell(row,column,'用途')
                        sheet.cell(row+1,column,'SYNTHETIC_OVERRIDE')
                    elif case=='duplicate-row':
                        sheet.append([cell.value for cell in sheet[row+1]])
                    else:
                        label = '开票日期' if case=='bad-date' else '价税合计（元）'
                        sheet.cell(row+1,headers.index(label)+1,'invalid')
                    book.save(source)
            if source.exists() and source.stat().st_size>131072:
                raise AssertionError('XLSX size limit')
            try:
                initialize_database(source, target)
            except (ValueError, OSError, sqlite3.Error, OverflowError, BadZipFile) as exc:
                outcomes[case] = type(exc).__name__
            else:
                outcomes[case] = 'PUBLISHED'
                if case=='duplicate-header':
                    with closing(sqlite3.connect(target)) as c:
                        outcomes['override_count'] = c.execute("SELECT count(*) FROM invoices WHERE purpose='SYNTHETIC_OVERRIDE'").fetchone()[0]
            if list(Path(temp).glob('finance-import-*.db')):
                raise AssertionError('staging file survived')
    expected = outcomes['valid']=='PUBLISHED' and all(v!='PUBLISHED' for k,v in outcomes.items() if k!='valid')
    intact = db.read_bytes()==original
    return expected and intact, expected and intact, outcomes


def config_numeric(db, directory):
    results = {}
    for host in ['127.0.0.1','127.1']:
        try:
            safe_url('https://'+host)
        except ProfileError:
            results[host] = 'REJECTED'
        else:
            results[host] = 'ACCEPTED'
    return all(v=='REJECTED' for v in results.values()), None, dict(results=results, local_numeric_decode=socket.inet_ntoa(socket.inet_aton('127.1')))


def trace_cookie(db, directory):
    path = directory/'probe.jsonl'
    cookie, token = 'SYNTHETIC_COOKIE_SENTINEL_48', 'SYNTHETIC_JSON_TOKEN_49'
    outcome = run_agent(db, FINAL, f'Cookie: session={cookie}\n{{"access_token":"{token}"}}', path)
    saved = path.read_text('utf-8')
    events = [json.loads(line)['event'] for line in saved.splitlines()]
    evidence = dict(cookie_visible=cookie in saved, embedded_token_visible=token in saved, model_input='model_input' in events, stop=outcome['stop'])
    return not (evidence['cookie_visible'] or evidence['embedded_token_visible']), None, evidence


def trace_surrogate(db, directory):
    before = state(db)
    reply = {'role':'assistant','content':json.loads('"\\ud800"')}
    enabled = run_agent(db, reply, trace=directory/'probe.jsonl')
    disabled = run_agent(db, reply)
    return not enabled['error'] and not disabled['error'], before==state(db), dict(with_trace=enabled, without_trace=disabled)


def rule_audit(db, directory):
    from main import main

    before = state(db)
    argv = ['main.py','--db',str(db),'rules','disable','--simulate-rule-manager','--rule-id','R002','--version','2.0']
    with patch.object(sys, 'argv', argv), redirect_stdout(io.StringIO()):
        main()
    after = state(db)
    with closing(sqlite3.connect(db)) as c:
        status_value = c.execute("SELECT status FROM rules WHERE rule_id='R002' AND version='2.0'").fetchone()[0]
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%audit%'")]
    trace_files = len(list(directory.glob('*.jsonl')))
    found = any('rule' in t for t in tables) or trace_files>0
    business = status_value=='DISABLED' and all(before[k]==after[k] for k in before if k!='rules')
    return found and business, business, dict(rule_status=status_value,audit_tables=tables,trace_files=trace_files)


def excel_cached(db, directory):
    from openpyxl import load_workbook

    outcomes = {}
    for variant in ['control','duplicate','negative']:
        source = directory/(variant+'.xlsx')
        target = directory/(variant+'.db')
        with closing(load_workbook(FIXTURE, data_only=True)) as book:
            sheet = book['发票']
            header = next(i for i, cells in enumerate(sheet.values, 1) if '开票日期' in cells and '发票编号' in cells)
            if variant=='duplicate':
                column = sheet.max_column+1
                sheet.cell(header, column, '用途')
                sheet.cell(header+1, column, 'SYNTHETIC_OVERRIDE')
            elif variant=='negative':
                row = next(i for i, cells in enumerate(sheet.values, 1) if cells[:2]==('C001','F002'))
                cell = sheet.cell(row, 6)
                delta = Decimal('-0.01')-Decimal(str(cell.value))
                cell.value = -0.01
                summary = next(row for row in book['说明'].iter_rows() if row[0].value=='C001' and getattr(row[1].value, 'month', None)==9)
                summary[4].value = float(Decimal(str(summary[4].value))+delta)
            book.save(source)
        size = source.stat().st_size
        if size>131072:
            raise AssertionError('XLSX size limit')
        result = dict(bytes=size)
        try:
            initialize_database(source, target)
        except ValueError as exc:
            result['status'] = type(exc).__name__
        else:
            result['status'] = 'PUBLISHED'
            with closing(sqlite3.connect(target)) as c:
                result['override_count'] = c.execute("SELECT count(*) FROM invoices WHERE purpose='SYNTHETIC_OVERRIDE'").fetchone()[0]
                result['f002_cents'] = c.execute("SELECT amount_cents FROM invoices WHERE company_id='C001' AND invoice_no='F002'").fetchone()[0]
            if variant=='negative':
                got = handle_tool('get_invoice', json.dumps({'company_id':'C001','invoice_no':'F002'}), 'U001', target)
                result['display'] = got['data']['amount'] if got['ok'] else None
        outcomes[variant] = result
    safe = outcomes['control']['status']=='PUBLISHED' and outcomes['duplicate']['status']!='PUBLISHED' and outcomes['negative'].get('display') in {None,'-0.01'}
    return safe, safe, outcomes


PROBES = {'ACL-06':acl_pair, 'ACL-07':acl_compat, 'RES-01':malformed, 'RES-02':overflow,
          'RES-05':negative_amount, 'RES-06':long_context, 'RES-04':excel, 'CONFIG-02':config_numeric,
          'TRACE-02':trace_cookie, 'TRACE-03':trace_surrogate, 'TRACE-04':rule_audit, 'RES-07':excel_cached}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', choices=PROBES)
    args = parser.parse_args()
    with TemporaryDirectory(prefix='sec-a-') as temp, patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')), patch.object(socket, 'getaddrinfo', side_effect=AssertionError('DNS forbidden')):
        directory = Path(temp)
        db = directory/'audit.db'
        initialize_database(FIXTURE, db)
        migrate(db)
        import_rules(db, SEED_RULES, {'rule.manage'})
        d, b, evidence = PROBES[args.case](db, directory)
    labels = {True:'PASS',False:'FAIL',None:'NOT_TESTED'}
    print(json.dumps(dict(case=args.case,D=labels[d],B=labels[b],evidence=evidence),ensure_ascii=True))
    return 0 if d and b is not False else 1


if __name__=='__main__':
    raise SystemExit(main())
