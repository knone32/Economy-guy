# Public regression gaps — A lane, 2026-11-20

**Release conclusion: full regression is blocked.** The material/rule feature's targeted checks passed, but the repository-wide suite failed. The full failure set has not been classified against the parent revision.

| Evidence | Result |
|---|---|
| A implementation | `f974e14ea4e739bcabbe40bf1877c31c43f4bb4f` |
| Parent used for baseline comparison | `bb08824da783f211b7088392c167d5d48efcfca6` |
| Full `python -m unittest discover -s tests -q` | **820 tests**, 329.757 seconds, **179 failures, 32 errors**, exit 1 |
| Latest targeted materials + Stage2 + typed delivery + route1 evidence + architecture | **48 tests passed**, 2.138 seconds |
| Latest material-only checks | **10 tests passed**, 0.468 seconds |
| First four full-suite errors, current commit | **4 tests, 4 identical errors reproduced**, 0.243 seconds |
| Same four tests, parent archive | **4 tests, 4 identical errors reproduced**, 0.238 seconds |

The full suite started before two final material tests were added; its discovered material count was 8. The subsequent 10-test and 48-test runs include the committed final tests. No complete second full-suite run was performed.

## Original evidence locations

The full run was not redirected to a disk log. Its original evidence is the tool transcript: `exec` session **86785**, final chunk **c58a38**. The final tool output reported 65,583 original tokens and was truncated. There is **no complete raw full-suite log file**, and this report does not claim one exists.

Complete new four-case comparison logs, publicly accessible outside private acceptance directories:

- `C:/Users/Lenovo/Documents/ChatGPT/economyguy/business-20261120/a-evidence-public/current-first-four.log`
- `C:/Users/Lenovo/Documents/ChatGPT/economyguy/business-20261120/a-evidence-public/parent-first-four.log`

The baseline was exported with `git archive` to a temporary directory and executed without modifying the current working tree. Both runs used the same Python executable and dependency path:

```text
Python: C:/Users/Lenovo/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe
PYTHONPATH: C:/Users/Lenovo/Documents/ChatGPT/economyguy/reliability-v2-20261119/runtime-deps
```

## Classification

| Classification | Confirmed evidence | Scope |
|---|---|---|
| Newly introduced failure | **None confirmed** | This does not establish that every full-suite failure is pre-existing. |
| Pre-existing before A implementation | **4 errors**, same exception and first failing assertion on parent and current | Listed below. |
| Unknown attribution | **179 failure events and remaining 28 error events** | No parent comparison was performed for this remaining set. Subtests mean these counts must not be treated as unique failed test methods. |
| Passing new feature checks | **10 material tests**, included in the final **48 passing targeted tests** | Temporary SQLite and synthetic OOXML; no paid model calls or production-ledger changes. |

The four confirmed pre-existing errors are:

1. `tests.test_business_ownership.BusinessOwnershipTests.test_current_correction_conflict_cannot_reuse_old_value`: `pending_intent['change']['new_value']` raises `KeyError: 'new_value'` at test line 67.
2. `tests.test_invoice_request.InvoiceRequestTests.test_missing_business_slots_create_only_unbound_pending`: `pending_intent['scope']` raises `TypeError: 'NoneType' object is not subscriptable` at test line 100.
3. `tests.test_invoice_request.InvoiceRequestTests.test_request_schema_does_not_weaken_complete_proposals`: `validate_arguments('propose_invoice_changes', '{"action":"request"}')` raises `ValueError` for missing required arguments in `app/tool_registry.py:203`, reached from test line 83.
4. `tests.test_mixed_invoice_scope.MixedInvoiceScopeTests.test_choice_checks_current_permission_and_period`: `pending_intent['request_id']` raises `TypeError: 'NoneType' object is not subscriptable` at test line 369.

Other visible full-run failures included legacy `information.text` and write-receipt/fulfillment assertions. They remain **unknown attribution**, rather than being relabelled pre-existing based on resemblance. There were also ResourceWarning and Textual slow-task notices; those are not the failure counts above.

## Remaining feature limits

The committed A feature supplies immutable Word versions, exact paragraph lookup, explicit `rule.manage` publishing, date intervals with explicit supersession, and overlap rejection. The workbench upload/open presentation and tool registration are integration-layer work. Existing seed rules without material sources cannot be silently converted into sourced historical versions. Private source originals are not automatically shared to other users with enterprise rule access.

`import_docx` currently returns `published=False` as an upload-action marker, even when a duplicate upload refers to a previously published version. UI must not interpret that field as authoritative historical publication state; this presentation gap has been reported for integration.
