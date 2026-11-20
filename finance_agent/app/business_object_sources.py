"""Current literal object sources, reusable by read and change adapters.

Registered names and identifier occurrences are evidence of data origins only.
The caller/model chooses business relationships; this module grants no action,
permission, invoice existence, period default, or confirmation.
"""
from contextlib import closing
import re

from .controlled_read_scope import catalog
from .responses import _QUOTED_DATA, _without_quoted_data, request_scope
from .stage2_schema import open_existing


_IDENTIFIER_CHAR = re.compile(r'[A-Za-z0-9_./-]')


def literal_spans(text, value, *, joint_companies=(), company_component=False):
    """Exact complete identifiers; a canonical company/invoice joint key is valid."""
    if not value:
        return []
    spans = []
    for match in re.finditer(re.escape(value), text):
        start, end = match.span()
        left = (start and _IDENTIFIER_CHAR.fullmatch(value[0])
                and _IDENTIFIER_CHAR.fullmatch(text[start - 1]))
        right = (end < len(text) and _IDENTIFIER_CHAR.fullmatch(value[-1])
                 and _IDENTIFIER_CHAR.fullmatch(text[end]))
        if right and company_component and text[end] == '/':
            right = False
        if left and text[start - 1] == '/':
            # The slash is a known joint-key separator, not part of an invented
            # invoice prefix. Verify the whole canonical company component.
            left = not any(text[:start].endswith(company + '/') and
                (start == len(company) + 1 or not _IDENTIFIER_CHAR.fullmatch(
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


def amendment_sources(request, current_value, *, actor, book, invoice_candidates=(), metadata=None):
    """Return current scope, value-only scope and unresolved literal overlap.

    A model candidate may prove a nonexisting invoice's literal source, never
    its existence. Only fresh authorized get_invoice can establish that fact.
    Quoted data and the uniquely located supplied value cannot supply targets.
    """
    companies = catalog(book, actor)['companies']
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
