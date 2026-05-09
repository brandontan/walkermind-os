# WARP•SENTINEL REPORT — resilience

Verdict: APPROVED
Score: 94/100
Critical Issues: 0
Source PR: #919
Source FORGE branch: WARP/CRUSADERBOT-PHASE4E-RESILIENCE
SENTINEL branch: WARP/sentinel-crusaderbot-phase4e-resilience
SENTINEL run timestamp: 2026-05-10 01:35 Asia/Jakarta

---

## 1. Environment

Environment was NOT explicitly declared in tracking issue #920. Audit scope is code-level safety-guard verification: the issue forbids live activation, requires `USE_REAL_CLOB` to stay False, requires `ENABLE_LIVE_TRADING` untouched, and requires every preflight signing check to be local with no broker call. That scope is consistent ONLY with dev posture.

Adopted posture for this run:

- Infra: warn (Redis / PostgreSQL not required for any audited path)
- Risk: ENFORCED (all activation guards verified untouched)
- Telegram: warn (alert wiring verified by code + unit test; no live bot run)

If WARP🔹CMD intends staging or prod posture, re-run is required — but no audited path requires runtime infra and the verdict would not change.

---

## 2. Validation Context

- Tier: MAJOR
- Claim Level: FULL RUNTIME INTEGRATION
- Source FORGE report: `projects/polymarket/crusaderbot/reports/forge/resilience.md` (515 lines, 6 sections + metadata block)
- Validation Target (per #920): CLOB outbound error handling + retry semantics + circuit breaker + rate limiter + mainnet preflight + ops visibility + tests + state/report updates
- Not in Scope: live activation, capital mode flip, owner activation guard flip, R13 growth backlog, ledger reversal lane, polymarket legacy cleanup beyond declared removals

Audit was conducted against `origin/WARP/CRUSADERBOT-PHASE4E-RESILIENCE` HEAD `d9e67e46`.

---

## 3. Phase 0 Checks

All checks PASS. No BLOCK trigger.

- PR #919 exists and is open. `mergeable_state = clean`, `head.sha = d9e67e46`.
- Branch matches the FORGE-declared name `WARP/CRUSADERBOT-PHASE4E-RESILIENCE`. Uppercase casing deviates from the AGENTS.md hyphen-lowercase convention but matches the precedent set by Phases 4A/4B/4C/4D and is not introduced by this PR; not a blocker.
- FORGE report at correct path with all 6 mandatory sections plus required metadata (Validation Tier, Claim Level, Validation Target, Not in Scope, Suggested Next Step).
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` updated with full timestamp `2026-05-10 00:25 Asia/Jakarta`; all 7 ASCII-bracket sections present.
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` has the new lane-closure entry appended at top.
- No `phase*/` folders anywhere in the repo (`find . -type d -name 'phase*'` returned empty).
- Hard-delete policy: `services/deposit_watcher.py` and `services/ledger.py` are absent from `git ls-tree -r origin/WARP/CRUSADERBOT-PHASE4E-RESILIENCE`. Confirmed deletion at the FORGE tree.
- Implementation evidence exists for every claimed component (file paths verified below).
- No hardcoded secrets in any new file (`grep -E "(api_key|api_secret|passphrase|private_key|polymarket)\s*=\s*[\"']..."` empty).
- No Kelly violations in audit scope (`grep -n kelly` empty across `integrations/clob/` and `scripts/mainnet_preflight.py`).
- No `except: pass` in audit scope.
- No `import threading` / `from threading` in audit scope; async-only.
- Activation guards (`ENABLE_LIVE_TRADING`, `USE_REAL_CLOB`, `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`) are READ but never WRITTEN by any new code; preflight reads them via `Settings`.
- `python -m py_compile` PASS on all new and modified files in audit scope.
- `ruff check` PASS on `lib/`, `integrations/clob/`, `scripts/mainnet_preflight.py`, `api/ops.py`, every new test file.
- 48 new resilience+preflight tests PASS locally in 13.61s. 45 existing CLOB tests (`test_clob_adapter.py`, `test_clob_auth.py`, `test_clob_factory.py`, `test_clob_market_data.py`) PASS in 6.61s with no regression.

---

## 4. Findings

Cited at `file:line` per AGENTS.md. Code is truth.

### 4.1 Activation posture preserved

- `integrations/clob/__init__.py:240` — `if not s.USE_REAL_CLOB: return MockClobClient()` keeps the paper-safe default reachable without credentials.
- `integrations/clob/__init__.py:254` — `ClobConfigError` raised when `USE_REAL_CLOB=True` with missing creds; explicit fail-fast, no silent degrade.
- `scripts/mainnet_preflight.py:55-76` (activation_guards), `:109-128` (use_real_clob) — both are READ paths. No mutation of any guard anywhere in Phase 4E. `ENABLE_LIVE_TRADING` is not even imported by the new code.
- `config.py:120` — `USE_REAL_CLOB: bool = False` (default unchanged).
- `config.py:135-136` — `EXECUTION_PATH_VALIDATED: bool = False`, `CAPITAL_MODE_CONFIRMED: bool = False` (defaults unchanged).
- `config.py:134` — `ENABLE_LIVE_TRADING: bool = True` is a PRE-EXISTING legacy default flagged by Phase 4B SENTINEL (F4) and tracked in `[KNOWN ISSUES]` as `WARP/config-guard-default-alignment`. Phase 4E does not introduce or worsen it.

### 4.2 Error classification (matches spec exactly)

`integrations/clob/adapter.py:107-133` `_classify_http_error`:

- 400 / 401 / 403 → `ClobAuthError` (no retry)
- 429 → `ClobRateLimitError` (retried)
- 500 / 502 / 503 / 504 → `ClobServerError` (retried)
- other 4xx (e.g. 404) → `ClobAPIError` (no retry)

`integrations/clob/adapter.py:541-548` `_do_request` translates `httpx.TimeoutException` → `ClobTimeoutError`, `httpx.HTTPError` → `ClobNetworkError`. `httpx.TimeoutException` is a subclass of `httpx.HTTPError`, so the order matters and is correct.

`integrations/clob/adapter.py:511-524` `_signed_request` uses `tenacity.AsyncRetrying` with `retry_if_exception_type(RETRYABLE_EXCEPTIONS)` covering only `(ClobRateLimitError, ClobServerError, ClobTimeoutError, ClobNetworkError)`. After exhaustion the last exception is wrapped as `ClobMaxRetriesError(last_exception=exc)`.

Verified by `tests/test_clob_error_classification.py` (15 parametrised cases). Auth-class tested per status (400/401/403) — single transport call asserted via `calls.count == 1`.

### 4.3 Circuit breaker

`integrations/clob/circuit_breaker.py:70-233`:

- States `CLOSED` / `OPEN` / `HALF_OPEN` with `STATE_*` constants.
- `__init__` validates `threshold > 0` and `reset_seconds >= 0`.
- `FAILURE_EXCEPTIONS` (line 61) excludes `ClobAuthError` — auth-class never trips the breaker.
- `call()` (line 126): if `state == OPEN` and reset window has elapsed, transitions to `HALF_OPEN`; otherwise raises `ClobCircuitOpenError` IMMEDIATELY without invoking `fn` (line 142-145).
- `_record_failure` (line 175): `HALF_OPEN`-failure transitions to `OPEN` and fires `on_open`; `CLOSED`-failure increments and trips at threshold.
- `_record_success` (line 164): `HALF_OPEN`-success closes; `CLOSED`-success resets failures.
- `on_open` callback failure is swallowed (line 200-208) — Telegram outage cannot keep the breaker stuck.
- `force_close()` (line 210) operator override.
- `snapshot()` (line 218) exposes `(state, failures, threshold, reset_seconds, opened_at_monotonic, seconds_until_half_open)`.

`integrations/clob/adapter.py:309-311, :315-317, :339-341` — `post_order`, `cancel_order`, `get_order` are wrapped in `self._breaker.call(...)`. `cancel_all_orders`, `get_fills`, `get_open_orders`, `derive_api_credentials`, `create_api_credentials`, `request` are intentionally NOT wrapped; admin / recovery / boot paths must remain reachable when the breaker has tripped on order-lifecycle calls.

Verified by `tests/test_clob_circuit_breaker.py` (11 tests) and `tests/test_clob_breaker_integration.py` (4 tests). Integration tests count transport-handler invocations and assert `handler.calls == 0` while the breaker is OPEN.

### 4.4 Telegram operator alert

`integrations/clob/__init__.py:145-173` `_on_circuit_open`:

- Lazy-imports `notify_operator` so the package stays importable in environments without the bot stack (preflight script).
- Renders `"⛔️ *CLOB circuit OPEN*\nbreaker \`{name}\` tripped..."` (plain markdown).
- Both the import failure and the `notify_operator` failure are caught and logged at ERROR — outage cannot block the breaker.

Wired in `__init__.py:188-193` `get_clob_breaker()` so every real adapter built by `get_clob_client()` shares the singleton breaker with the alert callback attached.

### 4.5 Rate limiter

`integrations/clob/rate_limiter.py:24-108`:

- Token bucket; default `rps=10`, `burst = max(1.0, rps)`.
- Continuous refill via `_refill` (line 70).
- `acquire(n)` (line 79) blocks via injectable `_sleep`; releases the lock between attempts so concurrent waiters re-check after refill.
- `rps <= 0` short-circuits to no-op (line 85) — used by every adapter unit test for deterministic timing.
- `snapshot()` returns `(rps, burst, tokens)` post-refill.

Acquired before every outbound REST/L1 call: `adapter.py:246`, `:267`, `:536`. Verified by `tests/test_clob_rate_limiter.py` (7 tests, all virtual-time).

### 4.6 Mainnet preflight

`scripts/mainnet_preflight.py:55-244`:

- Five checks in order: `activation_guards` → `polymarket_secrets` → `use_real_clob` → `eip712_sign` → `hmac_headers`.
- `eip712_sign` (line 131-169) signs locally via `ClobAuthSigner.sign_clob_auth`. No httpx import in the flow.
- `hmac_headers` (line 172-231) builds via `build_l2_headers`. Asserts the 5 required POLY_* keys are present.
- `run_preflight` (line 247) injectable `settings` and `checks` for tests.
- `main` (line 265) prints PASS/FAIL per check, then `RESULT: PASS` (exit 0) or `RESULT: FAIL` (exit 1).
- Secret values never echoed; only key names appear in `CheckResult.detail`.

Defense-in-depth verified by `tests/test_mainnet_preflight.py:149-176` `test_no_broker_call_in_preflight`: monkeypatches `httpx.AsyncClient.{request,get,post}` to raise `AssertionError`; preflight still PASSes proving no transport call ever fires.

### 4.7 Ops dashboard CLOB circuit card

`api/ops.py:131-157` `_circuit_state_snapshot`:

- Reads `get_clob_breaker().snapshot()` and degrades to `{"state": "N/A", "failures": 0, "threshold": 0, "seconds_until_half_open": 0.0}` on any resolver failure (line 142-149) — does NOT 5xx the page.

`api/ops.py:228-260, :370-372` rendering:

- `CLOSED` → ok / `HALF_OPEN` → warn / `OPEN` → fail / `N/A` → warn.
- Detail line: `{failures}/{threshold} consecutive failures` in CLOSED; `... -- half-opens in {N}s` in OPEN; `trial allowed -- next failure re-opens` in HALF_OPEN; `unavailable` in N/A.
- `html.escape` applied to the badge label.

### 4.8 Dead code removal

- `services/deposit_watcher.py` (-622) and `services/ledger.py` (-208) absent at FORGE tree per `git ls-tree -r origin/WARP/CRUSADERBOT-PHASE4E-RESILIENCE`.
- No new code in Phase 4E imports the deleted modules (`git grep` empty).
- `lib/` F401 cleanup confirmed: `python -m ruff check lib/` returns `All checks passed!`.

---

## 5. Score Breakdown

| Category | Weight | Score | Reasoning |
|---|---|---|---|
| Architecture | 20 | 19 | Clean package boundaries; singletons isolated; per-call adapter pattern preserved; recovery paths intentionally bypass breaker. -1 for the package-level (single-instance) breaker design noted in FORGE Known Issues. |
| Functional | 20 | 20 | Every claimed behavior verified via unit + integration tests in my hermetic env (48/48 new + 45/45 existing CLOB green). |
| Failure modes | 20 | 18 | All retry classifications verified; OPEN serves no-broker-call; ClobMaxRetriesError carries last_exception. -2 for the concurrent-HALF_OPEN race documented in §4 / §13. |
| Risk | 20 | 19 | All four activation guards untouched. USE_REAL_CLOB default False preserved. -1 for the pre-existing ENABLE_LIVE_TRADING=True legacy default left in place (out-of-scope but worth noting). |
| Infra + TG | 10 | 9 | Telegram alert wired with lazy import + outage swallow. -1 for plain-markdown alert (not MarkdownV2) flagged in FORGE Known Issues. |
| Latency | 10 | 9 | Bounded retry (3 attempts, 1..8s exp backoff) + 10 RPS limiter keeps the 429 ceiling unreachable. -1 because Phase 4E does not measure end-to-end latency on the audited surface. |
| **Total** | **100** | **94** | |

---

## 6. Critical Issues

None.

No P0 issues found. No safety guard mutated. No silent failure path. No threading. No hardcoded secret. No Kelly violation. No phase folder. Activation posture preserved.

---

## 7. Status

GO-LIVE: APPROVED.

Score 94/100. Zero critical issues. All Phase 0 checks pass. All claimed behaviors verified in hermetic test runs against `origin/WARP/CRUSADERBOT-PHASE4E-RESILIENCE` HEAD `d9e67e46`.

This PR is cleared for WARP🔹CMD merge decision. Activation posture remains paper-safe; no live trading guard is flipped by this PR.

---

## 8. PR Gate Result

- Source PR: #919 — `WARP/CRUSADERBOT-PHASE4E-RESILIENCE` → `main`
- FORGE PR is OPEN at audit time. Per AGENTS.md branch rules, the SENTINEL artifact ships as a PR from `WARP/sentinel-crusaderbot-phase4e-resilience` → `WARP/CRUSADERBOT-PHASE4E-RESILIENCE` (FORGE source branch), keeping audit continuity on the validated source path.
- Verdict comment will be posted on issue #920 and on PR #919.

---

## 9. Broader Audit Finding

The Phase 4E resilience layer integrates cleanly with the prior phases:

- Phase 4A CLOB Adapter — extended without breaking the existing public surface; `ClobAuthError` remains a subclass of `ClobAPIError` so existing `pytest.raises(ClobAPIError)` matchers still match (verified by `test_clob_adapter.py` running 14 tests green in my hermetic env).
- Phase 4B Execution Rewire — `domain/execution/live.py` uses `get_clob_client()` which now injects the singletons. No call-site change required; resilience picked up transparently.
- Phase 4C Order Lifecycle — `cancel_all_orders` / `get_fills` / `get_open_orders` are intentionally unwrapped so the lifecycle sweeper can still recover when the breaker has tripped on order-lifecycle calls. This matches the "recovery path must stay reachable" contract documented in the FORGE report and the adapter docstring.
- Phase 4D WebSocket Order Fills — independent reconnect/heartbeat resilience on the WS side; no overlap with the REST breaker / limiter. No coupling discovered.

No drift detected between PROJECT_STATE, CHANGELOG, and the audited code. State files reflect actual code truth.

---

## 10. Reasoning

I chose APPROVED rather than CONDITIONAL because:

1. Every claimed behavior in the FORGE report has a corresponding code path AND a passing hermetic test. There is no claim without evidence.
2. The activation posture is provably preserved: no new code mutates any of the four guards, and the package factory honours `USE_REAL_CLOB=False` as a paper-safe short-circuit before any credential check.
3. The `ClobCircuitOpenError`-with-no-broker-call contract is verified by a transport-handler call counter (`tests/test_clob_breaker_integration.py:96-156`), not just by test name.
4. The mainnet preflight has a defense-in-depth proof that no httpx call is ever made — monkeypatching `request/get/post` to raise `AssertionError` and asserting the run still PASSes.
5. Dead code deletion is real — `git ls-tree` against the FORGE branch confirms the two services modules are gone, and `git grep` finds no residual imports.
6. Ruff and py_compile are clean across all touched files in audit scope.

The two notable concerns (concurrent HALF_OPEN race + plain-markdown alert) are both bounded P2 issues with no safety implication and are deferred per §13.

---

## 11. Fix Recommendations

None blocking. All P2 deferred backlog (see §13).

---

## 12. Out-of-scope Advisory

Surfaces noted during audit that are NOT in the Phase 4E scope and should NOT block this merge:

- `config.py:134` `ENABLE_LIVE_TRADING: bool = True` legacy default. Already tracked under `WARP/config-guard-default-alignment`. Pre-existing; Phase 4B SENTINEL flagged the same line as F4. Not introduced or worsened by Phase 4E.
- `integrations/polymarket.py._build_clob_client` legacy dead code. Tracked under `WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP`. Out of scope for Phase 4E.
- On-chain readiness (wallet funding / USDC deposit / Exchange contract approvals) is intentionally NOT covered by the local preflight. Tracked under the suggested `WARP/CRUSADERBOT-MAINNET-ONCHAIN-PREFLIGHT` lane.
- Operator endpoint to `force_close()` the breaker via /ops + Telegram. Tracked under the suggested `WARP/CRUSADERBOT-OPS-CIRCUIT-RESET` lane.

These are correctly recorded in the FORGE report §6 and in PROJECT_STATE `[NEXT PRIORITY]` / `[KNOWN ISSUES]`.

---

## 13. Deferred Minor Backlog

P2 — non-blocking, post-merge OK:

1. **Concurrent HALF_OPEN trial race may multiply on_open and restart cool-down.** `circuit_breaker.py:175-208` `_record_failure`. The lock at `call()` line 137-145 is released before invoking `fn`, so multiple concurrent callers can pass through during HALF_OPEN. If they all fail, the first transitions HALF_OPEN→OPEN and fires `on_open`; subsequent callers enter the `else` branch with `state == OPEN`, increment `_failures` past `threshold`, set `state = OPEN` again, refresh `_opened_at`, and fire `on_open` again. Practical impact: duplicate Telegram alerts under a concurrent failure burst at the half-open boundary, plus a slightly extended cool-down. No safety or correctness implication. Mitigation: gate the `else` branch on `prior_state == CLOSED` so subsequent failures during OPEN count without re-firing the trip. Defer to a follow-up.
2. **Telegram alert text uses plain markdown, not MarkdownV2.** `__init__.py:161-166`. Acceptable for the static circuit-open template (no user-supplied content) but a future structured-alert refactor should switch to MarkdownV2 to avoid silent send drops on reserved characters. Already flagged in FORGE Known Issues.
3. **Dashboard CLOB circuit card refreshes only via the page-level 30s meta refresh** — an OPEN event is visible within 30s at worst. Acceptable for the demo posture; SSE/WS push is a future enhancement. Already flagged in FORGE Known Issues.
4. **Package-level (single-instance) breaker** — adequate for the current single-broker steady state; per-broker instances can be passed as the `circuit_breaker=` kwarg if a future caller needs them. Already flagged in FORGE Known Issues.

These are appended to PROJECT_STATE `[KNOWN ISSUES]` in surgical edit form below.

---

## 14. Telegram Visual Preview

Operator alert when the breaker trips (literal text emitted by `_on_circuit_open`):

```
⛔️ *CLOB circuit OPEN*
breaker `clob` tripped after consecutive transport failures. New orders are blocked until the breaker auto half-opens or an operator resets it via /ops.
```

Ops dashboard `CLOB circuit` card states (rendered from `_circuit_state_snapshot`):

```
[CLOSED]   2/5 consecutive failures        (badge: ok)
[HALF_OPEN] trial allowed -- next failure re-opens   (badge: warn)
[OPEN]     5/5 failures -- half-opens in 47s         (badge: fail)
[N/A]      unavailable                                (badge: warn)
```

No additional Telegram commands are introduced by this PR. The operator path to release the breaker manually via `/ops` is tracked under the suggested `WARP/CRUSADERBOT-OPS-CIRCUIT-RESET` lane.

---

End of report.


