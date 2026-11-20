# Received output truncation: separate candidate after 7a1fdf4

Scope: the publicly released `c-public-regressions/P4/CF-P4-A` pair only. No other private acceptance questions were read. Frozen `7a1fdf4`, its bundle, first execution and scores remain unchanged. This candidate used no product API calls.

## Observed causal chain

The last public HTTP response, `http-1795146592984302400-response.json`, reports HTTP 200, `finish_reason=length`, zero content characters, no tool calls, 2,048 completion tokens, and 2,048 reasoning tokens (token counts only). The original transport extracted the message and three aggregate usage counters, ignored `finish_reason`, accepted empty string content as a string, and emitted `success=True/SDK_SUCCESS`. Agent subsequently parsed the empty content as a final envelope, failed, and displayed `模型最终回复格式无效` with `INVALID_RESPONSE`. Output truncation was therefore incorrectly presented as a malformed final envelope.

## Minimal change

`ModelTransport` now recognizes `length` before reading or normalizing the message body and raises typed `ModelOutputTruncated`. Its `api.response` preserves known usage, safe response model, finish reason, latency, and `physical_request_sent=True`; HTTP category remains `SDK_SUCCESS` to distinguish receipt from usable completion. `success=False` and `error_category=OUTPUT_TRUNCATED` describe the unusable completion. Unknown HTTP status and unknown usage remain unknown. Only numeric reasoning-token usage is retained, never private reasoning text.

Agent changes are one import and one catch immediately before `BudgetExceeded`: stop as `OUTPUT_TRUNCATED`, preserve actual prior read results and canonical operation receipt, state that the truncated reply formed no usable response and caused no tool execution or saving, and suggest reducing request scope before a user-triggered retry. No automatic retry, output-limit increase, semantic interpretation or authorization change was added. Complete-looking tool calls from a truncated completion are rejected too. Non-truncated bad JSON retains `INVALID_RESPONSE`.

## Deterministic evidence

Tests use the installed SDK with synthetic `httpx.HTTPTransport` responses and temporary official fictional SQLite fixtures. No network model request or production ledger write occurs.

- New regression on archived original `7a1fdf4`: first failure is exactly `截断 not found in 模型最终回复格式无效`.
- Final dedicated module: five test methods (with protocol/content subcases) cover empty content and known usage; partial JSON and complete-looking modification calls; ordinary bad JSON; preserving prior successful current-SQLite reads without writes; raw HTTP 200 and missing usage under thinking/standard protocols. Architecture adds two tests.
- Focused final result: **7 tests passed**. Public full logs: `business-20261120/a-output-truncation-evidence/final-focused.log`.
- Wider related run: **44 tests**, **2 failures / 4 errors**. Every one of those six existing failures was reproduced with the same first error on archived original `7a1fdf4`, in the same environment. Baseline log: `business-20261120/a-output-truncation-evidence/baseline-first-errors.log`. The wider current run's original evidence is tool chunk `4628c8`, not a claimed complete disk log.

The six baseline failures are `test_qwen.QwenTests.test_one_and_many_tools_pair_in_consecutive_sdk_requests` (tool_call_id KeyError), `test_qwen.QwenTests.test_allowlist_keeps_unofficial_and_other_model_payloads_generic` (thinking flag), `test_qwen.QwenPilotTests.test_official_transport_keeps_credential_and_private_text_out_of_saved_history` (TUI state timeout), plus `test_stage4pd.SessionTests.test_credentials_are_frozen_and_rotation_requires_new_connection`, `test_stage4pd.SessionTests.test_trace_failure_does_not_change_actual_sdk_result`, and `test_stage4pd.TraceTests.test_native_usage_known_unknown_and_failure_are_not_estimated` (all existing mocked-response protocol errors). They were not edited or reclassified as passing.

The first new-test harness run had a tuple/list empty-result assertion mismatch and queried invoice_audit before the fixture's Stage2 migration. Only the new test fixture/assertion was corrected; product failures were not masked. No repository-wide rerun or product Live verification is claimed. Real-model usefulness after an explicit retry and human visual acceptance remain untested.
