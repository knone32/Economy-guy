# P1-B controlled read binding follow-up

Independent branch from frozen `7a1fdf4fb5f22cc114b75950f896897e8cbbc90e`. The original public first execution and C scores are unchanged. No product Live or paid API calls.

## Root cause and scope

The public exact replay has the actual model SQL selecting C001 and 2026-08/09, but its runtime scope proof contains only `month=[8,9] / user_current`. `responses.explicit_scope` recognizes canonical C-number IDs, a fixed legacy company-name mapping, and four-digit years; it does not bind the colloquial company or two-digit year. The model actually saw a SYSTEM starting with a static fixture mapping, a SQL schema accepting only `sql`, and a SQL workspace announcing missing company/year. Canonical SQL literals are candidates, not an independent source of user scope. `companies.short_name` is the registered full short name, not the single-character colloquial abbreviation in the public request.

The original `COUNT(*)` chooses invoice quantity where the public target asks for money. That is a separate model metric error; this patch neither changes the SQL nor attributes it to the runtime.

## Native interface

`query_business_sql` still requires only `sql` when a legitimate scope already exists. It now accepts optional `read_scope` in that same native tool call:

```json
{"company_id":"ZX-83","periods":[{"year":2037,"month":8},{"year":2037,"month":9}],"company_quote":"澄曜","period_quote":"37年先八月再九月"}
```

This illustrative company is an isolated fictional test fixture. The runtime requires both quotes in the current request; the company quote must equal an ID, full name, or short name uniquely registered in the current actor's readable workbook catalog. It rejects unregistered abbreviations, competing registered matches, and identifiers selected as prefixes of longer unknown IDs. Two-digit years use no default century: the suffix must uniquely match a current company year covering all requested months. The selected periods must match the date quote and current catalog exactly.

The model receives current readable enterprise names/IDs and available periods in `context_data.read_catalog`; the static SYSTEM fixture mapping is removed. The optional candidate updates only that turn's SQL workspace proof using `controlled_read_scope` in `READ_SOURCES`, never shared context, `SOURCES`, pending writes, approval, or commit. The existing snapshot, SQL restrictions, and fresh ACL checks remain in force. Successful results include the binding source in tool evidence.

The old `intent.action=read` sidecar remains available to other read interfaces. It no longer supplies missing SQL scope via `model_read_candidate`; SQL has one explicit controlled binding interface. SYSTEM and SQL descriptions document this boundary. Existing SQL-only calls with independently trusted scope remain valid.

## Evidence and limitations

- New `tests.test_controlled_read_scope_20261120`: 7 tests pass, using unfamiliar fictional ID/name/year, schema+handler+Agent paths, alias/century/source collisions, unregistered prefixes, write-source denial, old sidecar SQL bypass rejection, and existing trusted SQL-only success. No HTTP.
- Final narrow regression: `test_controlled_read_scope_20261120`, `test_business_contract_guidance`, `test_sql_invoice_selection`, `test_architecture`: 17 pass.
- Earlier broader run: 62 tests, 12 failures, all in Stage3B. Independently running Stage3B on unchanged frozen 7a1fdf4 reproduced the exact same 12 failing test names out of 28; no baseline assertion was edited.
- The deliberately tightened old SQL-sidecar contract conflicts with the preexisting `ModelIntentTests.test_read_candidate_can_supply_sql_snapshot_without_becoming_write_source`, which expects unregistered colloquial sources to create a SQL snapshot. That assertion is retained, and its resulting failure must be reported separately from the 12 reproduced baseline failures.
- Full discovery was started during development and is diagnostic, not a precise final-SHA green result. Broad legacy regressions are not claimed fixed.

The original public `sql`-only arguments remain AMBIGUOUS: the patch does not turn the SQL's C001/2026 literals into scope, register a special colloquial alias, or claim the first execution passed. It provides a safe general same-call path for registered controlled identities; arbitrary natural-language shorthand and absent catalog periods still require clarification. No new classifier, preliminary model call, dictionary of colloquialisms, nearest-ID lookup, or write-source relaxation is added.
