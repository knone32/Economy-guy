"""Current literal object sources, reusable by read and change adapters.

Registered names and identifier occurrences are evidence of data origins only.
The caller/model chooses business relationships; this module grants no action,
permission, invoice existence, period default, or confirmation.
"""
from contextlib import closing
import re
from unicodedata import category

from .permissions import check_permission
from .responses import _QUOTED_DATA, _without_quoted_data, request_scope
from .stage2_schema import open_existing


_IDENTIFIER_CHAR = re.compile(r'[A-Za-z0-9_./-]')


def _registered_companies(db):
    return [dict(row) for row in db.execute('SELECT company_id,name,short_name FROM companies ORDER BY company_id')]


def readable_companies(book, actor):
    """Current identity catalog only; unrelated financial-table faults propagate at query time."""
    with closing(open_existing(book, readonly=True)) as db:
        db.execute('BEGIN')
        return [row for row in _registered_companies(db)
                if check_permission(db, actor, row['company_id'], 'read').allowed]


def literal_spans(text, value, *, joint_companies=(), company_component=False, cased_tokens=False):
    """Exact complete identifiers; a canonical company/invoice joint key is valid."""
    if not value:
        return []
    def identifier_char(char):
        return bool(_IDENTIFIER_CHAR.fullmatch(char)) or (cased_tokens and category(char) in {'Lu', 'Ll', 'Lt'})
    spans = []
    for match in re.finditer(re.escape(value), text):
        start, end = match.span()
        left = start and identifier_char(value[0]) and identifier_char(text[start - 1])
        right = end < len(text) and identifier_char(value[-1]) and identifier_char(text[end])
        if right and company_component and text[end] == '/':
            right = False
        if left and text[start - 1] == '/':
            # The slash is a known joint-key separator, not part of an invented
            # invoice prefix. Verify the whole canonical company component.
            left = not any(text[:start].endswith(company + '/') and
                (start == len(company) + 1 or not identifier_char(
                    text[start - len(company) - 2])) for company in joint_companies)
        if not left and not right:
            spans.append((start, end))
    return spans


def registered_company_mentions(text, companies):
    """Prefer a complete registered name over aliases contained inside it.

    Equal spans matching different companies remain genuinely ambiguous.
    The catalog supplied by the caller must already be restricted by read ACL.
    """
    found = []
    for row in companies:
        for quote in dict.fromkeys(row[key] for key in ('company_id', 'name', 'short_name')):
            for start, end in literal_spans(text, quote, company_component=quote == row['company_id']):
                found.append({'company_id': row['company_id'], 'quote': quote, 'span': [start, end]})
    return [item for item in found if not any(
        other['span'][0] <= item['span'][0] and other['span'][1] >= item['span'][1]
        and other['span'] != item['span'] for other in found)]


def unreadable_company_mentions(request, *, actor, book, include_quoted=False):
    """Internal negative constraints, never a public catalog or scope grant.

    Dropping an unreadable current object must not reactivate an old selected
    object. An invisible namesake does not veto an otherwise readable unique
    name: a literal span is a denial only when all its registered matches are
    unreadable. Callers must keep this result outside model context/authority.
    """
    text = (_QUOTED_DATA.sub(lambda match: ' ' + match[0][1:-1] + ' ', request)
            if include_quoted else _without_quoted_data(request))
    with closing(open_existing(book, readonly=True)) as db:
        companies = _registered_companies(db)
        matches = registered_company_mentions(text, companies)
        readable = {item['company_id'] for item in matches
                    if check_permission(db, actor, item['company_id'], 'read').allowed}
    readable_spans = {tuple(item['span']) for item in matches if item['company_id'] in readable}
    constraints = [{**item, 'constraint': 'read_denied'} for item in matches
                   if item['company_id'] not in readable and tuple(item['span']) not in readable_spans]
    registered_ids = {row['company_id'] for row in companies}
    registered_spans = {tuple(item['span']) for item in matches}
    # Keep the existing canonical-ID grammar as a negative constraint, even
    # when no catalog row exists. It supplies no company scope or permission.
    for identifier in request_scope(text, True).get('company_id', ()):
        if identifier not in registered_ids:
            for span in literal_spans(text, identifier, company_component=True):
                if span not in registered_spans:
                    constraints.append({'company_id': identifier, 'quote': identifier,
                        'span': list(span), 'constraint': 'unregistered_company'})
    return constraints


def amendment_sources(request, current_value, *, actor, book, invoice_candidates=(), metadata=None):
    """Return current scope, value-only scope and unresolved literal overlap.

    A model candidate may prove a nonexisting invoice's literal source, never
    its existence. Only fresh authorized get_invoice can establish that fact.
    Quoted data and the uniquely located supplied value cannot supply targets.
    """
    companies = readable_companies(book, actor)
    ids = tuple(row['company_id'] for row in companies)
    numbers = {value for value in invoice_candidates if type(value) is str and value}
    if ids:
        with closing(open_existing(book, readonly=True)) as db:
            placeholders = ','.join('?' for _ in ids)
            numbers.update(row[0] for row in db.execute(
                f'SELECT DISTINCT invoice_no FROM invoices WHERE company_id IN ({placeholders}) AND instr(?,invoice_no)>0',
                (*ids, request)))

    def scope(text, source_metadata=None):
        matches = registered_company_mentions(text, companies)
        owners = sorted({item['company_id'] for item in matches})
        invoices = {number: literal_spans(text, number, joint_companies=ids) for number in numbers}
        invoices = {number: spans for number, spans in invoices.items() if spans}
        # Digits and date-shaped fragments inside literal identifiers are data,
        # never an independent business-period constraint.
        date_text = list(text)
        spans = [item['span'] for item in matches]
        spans.extend(span for occurrences in invoices.values() for span in occurrences)
        for start, end in spans:
            date_text[start:end] = ' ' * (end - start)
        values = {key: value for key, value in request_scope(''.join(date_text), True).items()
                  if key not in {'company_id', 'invoice_no'}}
        if owners:
            values['company_id'] = owners
        if invoices:
            values['invoice_no'] = sorted(invoices)
        if source_metadata is not None:
            source_metadata.update({'company_mentions': matches, 'invoice_mentions': invoices,
                                    'source': 'current_authorized_catalog_and_literal'})
        return values

    unquoted = _without_quoted_data(request)
    value_scope, ambiguous = {}, False
    if (current_value and current_value in unquoted
            and not any(match[0][1:-1] == current_value for match in _QUOTED_DATA.finditer(request))):
        value_scope = scope(current_value)
        if value_scope:
            if unquoted.count(current_value) > 1:
                ambiguous = True
            else:
                start = unquoted.index(current_value)
                unquoted = unquoted[:start] + ' ' * len(current_value) + unquoted[start + len(current_value):]
    return scope(unquoted, metadata), value_scope, ambiguous


class ReadInvoiceAmbiguity(ValueError):
    """A read spelling has multiple real invoice keys; no key may be selected."""


def _casefold_spans(text, value, *, joint_companies=()):
    if not value:
        return set()
    folded, positions = [], []
    for index, char in enumerate(text):
        part = char.casefold()
        folded.append(part)
        positions.extend([index] * len(part))
    folded_text = ''.join(folded)
    found = set()
    for match in re.finditer(re.escape(value.casefold()), folded_text):
        start, end = positions[match.start()], positions[match.end() - 1] + 1
        spelling = text[start:end]
        if spelling.casefold() == value.casefold() and (start, end) in literal_spans(
                text, spelling, joint_companies=joint_companies, cased_tokens=True):
            found.add((start, end))
    return found


def read_invoice_sources(request, current_value=None, *, actor, book, invoice_candidates=()):
    """Only a read adapter may normalize a unique real key within a current company.

    Exact spelling wins when it identifies a real key. Otherwise casefold may
    establish a read-only canonical source, never existence from an invented
    token or any write permission. Default amendment_sources stays exact.
    """
    if current_value is not None:
        raise ValueError('只读票号归一化不能绑定修改内容')
    current, carried, ambiguous = amendment_sources(request, None, actor=actor, book=book,
                                                   invoice_candidates=invoice_candidates)
    companies = current.get('company_id', ())
    if len(companies) != 1:
        return current, carried, ambiguous
    with closing(open_existing(book, readonly=True)) as db:
        numbers = [row[0] for row in db.execute('SELECT invoice_no FROM invoices WHERE company_id=?', (companies[0],))]
    occurrences = {}
    plain = _without_quoted_data(request)
    folded_request = plain.casefold()
    for number in numbers:
        if number.casefold() not in folded_request:
            continue
        for span in _casefold_spans(plain, number, joint_companies=companies):
            occurrences.setdefault(span, set()).add(number)
    canonical = set()
    for (start, end), matches in occurrences.items():
        spelling = request[start:end]
        if spelling in matches:
            canonical.add(spelling)
        elif len(matches) == 1:
            canonical.update(matches)
        else:
            raise ReadInvoiceAmbiguity('票号大小写在当前企业对应多个实际编号，请提供完整精确票号。')
    if canonical:
        current['invoice_no'] = sorted(canonical)
    return current, carried, ambiguous
