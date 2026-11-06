"""仅用于获准的虚构库验收：有限词法准则，未知语义拒绝，不是生产自动授权。"""
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from contextlib import closing

C2_REQUEST = '把这些还没有补完用途的发票记成一个待办，我下次继续处理。'
OLD_REQUEST_ID = '8d3d28e13426473a9a6e4a5b918a8e13'
OLD_FINGERPRINT = '03644e25daf0a7a1ee948e8101d6e09c082fc7f03c8f3102facc9a5c6d257c72'
# 逐字符覆盖、最长词优先；不能删掉未知文本或把模型“语义一致”当批准。
WORDS = set('把 这些 这 些 还 还没有 尚未 未完成 未填写 没有 未填 未 填写 填 补完 补充 补齐 补全 完善 用途 的 发票 '
            '记成 记录 保存 记下 一个 一项 待办 任务 我 下次 以后 后续 稍后 继续 接着 处理 跟进 核对 '
            '为 给 将 需要 需 必填 全部 所有 剩余 缺失 缺少 当前 待处理 待补充 待补齐 '
            '甲企业 在 年 月 中 及 和 并 按 根据 规则 要求 进行 再 时 未补完 尚未补齐 '
            '不要猜用途 不猜用途 不要推断用途 不推断用途 不要猜测用途 不自动修改发票'.split())
PUNCTUATION = set('，。；：、（）()【】[]“”‘’"\'：:,.!！?？-—_ /\t\r\n')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def facts(path):
    """独立只读SQL真值，不调用被测规则/统计业务函数。"""
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)) as c:
        c.row_factory = sqlite3.Row
        missing = [r[0] for r in c.execute("SELECT invoice_no FROM invoices WHERE company_id='C001' AND invoice_date>='2026-09-01' AND invoice_date<'2026-10-01' AND trim(coalesce(purpose,''))='' ORDER BY invoice_date,invoice_no")]
        rules = [dict(r) for r in c.execute("SELECT * FROM rules WHERE company_scope IN ('C001','*') AND rule_type='purpose' AND status='ACTIVE' AND effective_from<='2026-09-01'")]
        permission = c.execute("SELECT can_read FROM permissions WHERE user_id='U001' AND company_id='C001'").fetchone()
        tasks = c.execute("SELECT count(*) FROM tasks WHERE user_id='U001' AND company_id='C001' AND status IN ('ACTIVE','WAITING_USER','PAUSED')").fetchone()[0]
        return dict(missing=missing, rules=rules, can_read=bool(permission and permission[0]), unfinished=tasks)


def note_allowed(note, current):
    """只接受可完全分词的中性待办说明；事实字面量须匹配独立SQL。"""
    if not isinstance(note, str) or not note.strip() or len(note)>500:
        return False
    text=note
    # 特定否定句整体匹配；不把一般“不/别/无需”丢弃后误批反向指令。
    literals={'C001','2026年9月','2026年09月','2026-09','2026/09','R002 v2.0','R002v2.0','R002','v2.0', '2026', '9', '09'}
    literals |= {f'{len(current["missing"])}张', f'{len(current["missing"])}张发票'}
    literals |= set(current['missing'])
    # 数字年月仅以完整字面量匹配；独立数字不能掩盖额外未知数量。
    literals -= {'2026','9','09'}
    tokens=sorted(WORDS | literals, key=len, reverse=True)
    while text:
        token=next((t for t in tokens if text.startswith(t)), None)
        if token:
            text=text[len(token):]
        elif text[0] in PUNCTUATION:
            text=text[1:]
        else:
            return False
    # 待办不必逐字复述旧四句，但必须包含未完/未来继续的明确线索。
    return any(x in note for x in ['下次','以后','后续','继续','待办','未完成','未填写','缺失','待补齐'])


class SimulatedApproval:
    """测试操作者策略，只有review通过才向真实CLI输入一次性nonce。"""
    def __init__(self):
        self.used=set()

    def review(self, proposal, path, actor, turn_id, accept=True):
        p=proposal.get('proposal', {})
        current=facts(path)
        expected=dict(company_id='C001',action='create',task_id='',year=2026,month=9)
        reason=[]
        if actor!='U001' or proposal.get('domain')!='task' or proposal.get('original_request')!=C2_REQUEST:
            reason.append('actor/domain/original_request')
        if set(p)!=set(expected)|{'note'} or any(type(p.get(k)) is not type(v) or p.get(k)!=v for k,v in expected.items()):
            reason.append('scope/action/fields')
        if proposal.get('current') is not None or not current['can_read'] or current['unfinished']:
            reason.append('permission/old_object/uniqueness')
        rules=current['rules']
        if len(rules)!=1 or rules[0]['rule_id']!='R002' or rules[0]['version']!='2.0' or json.loads(rules[0]['params_json'])!={'mode':'all','threshold_cents':0} or len(current['missing'])!=5:
            reason.append('current_sqlite/rule')
        if not note_allowed(p.get('note'),current):
            reason.append('unknown_note_or_fact')
        rid=proposal.get('request_id',''); fp=proposal.get('fingerprint','')
        expected_fp=digest([actor,'task','create',C2_REQUEST,turn_id,rid,p,proposal.get('current')])
        if not re.fullmatch('[0-9a-f]{32}',rid) or fp!=expected_fp or rid==OLD_REQUEST_ID or fp==OLD_FINGERPRINT or rid in self.used:
            reason.append('nonce/fingerprint/replay')
        if not accept:
            reason.append('simulated_user_cancelled')
        approved=not reason
        if approved:
            self.used.add(rid)
        return dict(approved=approved, confirmation_source='SIMULATED_TEST_USER', reasons=reason,
                    request_id=rid, fingerprint=fp, proposal_digest=digest(proposal), facts=current)
