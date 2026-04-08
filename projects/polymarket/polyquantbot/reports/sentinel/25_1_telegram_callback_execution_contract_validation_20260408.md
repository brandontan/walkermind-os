# SENTINEL VALIDATION REPORT — telegram_callback_execution_contract_fix_20260408

## Environment
- dev (inferred from local container-only validation context; external Telegram delivery checks treated as warning-only)

## Validation Context
- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Validation Mode: NARROW_INTEGRATION_CHECK
- Validation Target: Telegram callback → execution pipeline (`CallbackRouter` → `action:trade_paper_execute` → shared execution contract → risk layer → execution pipeline)
- Not in Scope: strategy redesign; pricing model redesign; observability system redesign; UI redesign; unrelated handlers.

## 0. Phase 0 Checks
- Forge report: **FAIL** — expected task-specific forge artifact for `telegram_callback_execution_contract_fix_20260408` not found in `projects/polymarket/polyquantbot/reports/forge/`; only older trade-menu routing report exists.
- PROJECT_STATE: **PASS (stale for this target)** — file exists with valid timestamp format and prior task history.
- Domain structure: **PASS** — no `phase*/` directories detected in repository scan.
- Hard delete: **PASS** — no migration/shim evidence observed in validated scope.
- Implementation evidence pre-check: **FAIL** — callback path evidence does not show execution contract invocation.

## Findings

### Architecture (16/20)
- `projects/polymarket/polyquantbot/telegram/ui/keyboard.py:74-79`
  - `trade_paper_execute` is exposed as a callback action from Trade menu.
- `projects/polymarket/polyquantbot/telegram/handlers/callback_router.py:460-505`
  - action alias normalizes `trade_paper_execute` to `trade` and immediately renders view payload.
- Result: callback action is wired for UI navigation, but architecture does not include execution-contract handoff in this path.

### Functional (4/20)
- `projects/polymarket/polyquantbot/telegram/handlers/callback_router.py:491-505`
  - for `trade_paper_execute`, router sets informational payload text and calls `render_view`, with no call to `CommandHandler._handle_trade_test` or equivalent execution primitive.
- `projects/polymarket/polyquantbot/telegram/command_handler.py:337-386`
  - `/trade test` executes runtime flow (`StrategyTrigger.evaluate`, mark-to-market update, export payload). This is a distinct command path.
- Runtime proof command (local harness) showed:
  - `CALLBACK_EXEC_TRIGGERED 1`
  - `SHARED_CONTRACT_CALLS 0`
- Result: critical contract mismatch (callback does not trigger real execution and does not use the `/trade test` shared path).

### Failure Modes (11/20)
- Malformed callback payload rejected at router gate:
  - `projects/polymarket/polyquantbot/telegram/handlers/callback_router.py:264-266`
- Dispatch exception handling returns explicit error-screen fallback (no silent failure):
  - `projects/polymarket/polyquantbot/telegram/handlers/callback_router.py:283-291`
- Break attempts executed:
  - spam clicks: repeated callback dispatch triggers repeated edit path with no dedup proof (`SPAM_EXEC_EDIT_CALLS 6`, `SPAM_SHARED_CONTRACT_CALLS 0`)
  - malformed payload: blocked (`MALFORMED_BLOCKED True`)
  - direct invalid invocation: unknown action returns warning path (`DIRECT_INVALID_DISPATCH_TEXT_PREFIX ⚠️ *SYSTEM NOTICE*`)
- Result: input validation/failure surfacing exist, but no execution-side duplicate guard can be validated for callback path because callback never reaches execution.

### Risk Compliance (3/20)
- Required target path `Callback → RISK → EXECUTION` is not evidenced.
- Since callback path does not enter execution contract, risk enforcement on callback execution path cannot be demonstrated.
- Result: critical failure for requested validation target.

### Infra + Telegram (5/10)
- Local runtime logs repeatedly show `market_context_api_failed ... clob.polymarket.com ... Network is unreachable` during callback rendering attempts.
- In dev mode this is warning-only, but it prevents end-to-end external Telegram confirmation.

### Latency (0/10)
- No measured callback→execution latency could be produced because callback path did not execute trade pipeline.

## Score Breakdown
- Architecture: 16/20
- Functional: 4/20
- Failure modes: 11/20
- Risk compliance: 3/20
- Infra + Telegram: 5/10
- Latency: 0/10
- Total: **39/100**

## Critical Issues
1. Callback execution trigger missing for `action:trade_paper_execute` (UI render only, no trade execution contract call).
   - Evidence: `projects/polymarket/polyquantbot/telegram/handlers/callback_router.py:491-505`
2. Shared execution contract violation: callback path does not use `/trade test` execution path.
   - Evidence: `projects/polymarket/polyquantbot/telegram/handlers/callback_router.py:491-505` vs `projects/polymarket/polyquantbot/telegram/command_handler.py:337-386`
3. Required path `Callback → RISK → EXECUTION` not demonstrated on target action.
   - Evidence: no execution invocation in callback dispatch segment.

## Status
**BLOCKED**

## PR Gate Result
**BLOCKED**

## Broader Audit Finding
**FOLLOW-UP REQUIRED**

## Reasoning
Validation target and claim require narrow execution integration for callback-triggered paper execute. Code and runtime evidence show callback performs screen rendering only and does not invoke shared execution contract. Because execution is never triggered, risk and duplicate protections in execution path cannot be validated on callback route, creating a direct contradiction to required contract.

## Fix Recommendations
1. Route `action:trade_paper_execute` to the same callable used by `/trade test` (single shared execution function, not duplicated logic).
2. Add callback payload schema validation that maps selected market/side/size into shared execution contract input and rejects malformed fields before execution.
3. Add callback idempotency key (per callback query id + selected trade signature) to prevent repeated click duplicate execution.
4. Add focused SENTINEL regression tests for:
   - callback executes trade path,
   - callback duplicate blocked,
   - malformed callback blocked,
   - execution failure returns explicit user-facing error.
5. Add latency instrumentation for callback execution path and assert under target.

## Out-of-scope Advisory
- Existing forge report `projects/polymarket/polyquantbot/reports/forge/telegram_trade_menu_mvp_20260407.md` is STANDARD-tier menu-routing focused and does not claim MAJOR execution-contract integration.

## Telegram Visual Preview
- N/A — this validation focused on callback execution contract behavior and local runtime harness evidence; external device screenshot unavailable in this container.
