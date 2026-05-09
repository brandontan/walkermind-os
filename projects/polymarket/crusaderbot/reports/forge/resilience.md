# WARP•FORGE REPORT — resilience

Validation Tier: MAJOR
Claim Level: FULL RUNTIME INTEGRATION
Validation Target: CLOB outbound error handling + retry semantics + circuit breaker + rate limiter + mainnet preflight + ops visibility + tests + state/report updates
Not in Scope: live activation, capital mode flip, owner activation guard flip, USE_REAL_CLOB owner flip, R13 growth backlog, ledger reversal lane, polymarket legacy cleanup
Suggested Next Step: WARP•SENTINEL validation required before merge

---

## 1. What Was Built

Phase 4E hardens the Polymarket CLOB outbound surface with typed error
classification, a circuit breaker, a local rate limiter, and a mainnet
readiness preflight script. Activation posture stays paper-only --
nothing in this PR flips a guard or sends a real order.

Concrete additions:

- New `integrations/clob/circuit_breaker.py` — `CircuitBreaker`:
  - Async-only, instance-scoped, concurrency-safe via `asyncio.Lock`.
  - States: `CLOSED` -> `OPEN` -> `HALF_OPEN` -> `CLOSED` (or back to
    `OPEN` on failed trial).
  - Trips after `CIRCUIT_BREAKER_THRESHOLD=5` consecutive transport
    failures (rate limit / 5xx / timeout / network / max-retries).
  - Auth-class errors do NOT count -- a stale signature is operator-
    actionable, not a transport incident.
  - Auto half-opens after `CIRCUIT_BREAKER_RESET_SECONDS=60`. Trial
    success closes; failure re-opens and restarts the cool-down.
  - `on_open` callback fires once per OPEN transition. Wired in the
    package factory to `notify_operator(...)` so the Telegram alert is
    fire-and-forget. Callback failures are logged + swallowed -- a
    Telegram outage must not keep the breaker stuck.
  - `snapshot()` exposes `(state, failures, threshold, reset_seconds,
    seconds_until_half_open)` for the ops dashboard.
  - `force_close()` operator override for tests / future
    `/ops/circuit-reset`.
  - Test seam: injectable `clock` lets reset-window tests fast-forward.

- New `integrations/clob/rate_limiter.py` — `RateLimiter`:
  - Token-bucket, configurable `rps` (default 10) and `burst` (default
    `max(1, rps)`).
  - Continuous refill (1 token per `1/rps` seconds, capped at `burst`).
  - `await acquire(n=1.0)` blocks until enough tokens are available.
  - `rps <= 0` short-circuits to no-op (used by unit tests that exercise
    downstream behavior without sleeping).
  - Test seams: injectable `clock` and `sleep` so the suite runs in
    virtual time -- no real `asyncio.sleep` ever fires.
  - `snapshot()` exposes `(rps, burst, tokens)` for diagnostics.

- New `integrations/clob/exceptions.py` (extended typed hierarchy):
  - `ClobError` (base, unchanged)
  - `ClobConfigError` (unchanged)
  - `ClobAPIError` (kw-only constructor, unchanged contract)
  - `ClobAuthError(ClobAPIError)` -- 400 / 401 / 403, never retried;
    flexible constructor preserves `ClobAuthError("string")` calls in
    `auth.py`.
  - `ClobRateLimitError(ClobAPIError)` -- 429, retried.
  - `ClobServerError(ClobAPIError)` -- 500/502/503/504, retried.
  - `ClobTimeoutError(ClobError)` -- transport timeout, retried.
  - `ClobNetworkError(ClobError)` -- transport network failure,
    retried.
  - `ClobMaxRetriesError(ClobError)` -- carries `last_exception`; raised
    once retries are exhausted on a retryable class.
  - `ClobCircuitOpenError(ClobError)` -- breaker OPEN, no broker call.

- Updated `integrations/clob/adapter.py`:
  - `_classify_http_error` maps every non-2xx status to the new typed
    exception. 4xx that aren't `auth` / 429 fall through as
    `ClobAPIError` (no retry) -- preserves the no-retry contract for
    things like 404.
  - `_signed_request` wraps the request in tenacity that retries ONLY
    on `(ClobRateLimitError, ClobServerError, ClobTimeoutError,
    ClobNetworkError)`. After max retries, the last retryable
    exception is wrapped as `ClobMaxRetriesError`.
  - `_do_request` translates `httpx.TimeoutException` ->
    `ClobTimeoutError` and other `httpx.HTTPError` -> `ClobNetworkError`
    so the retry filter only sees typed exceptions.
  - `post_order`, `cancel_order`, and `get_order` now flow through
    `self._breaker.call(...)` -- the three surfaces the task spec
    mandates. `cancel_all_orders` and bulk `get_*` paths intentionally
    NOT wrapped (recovery / admin paths must remain reachable when the
    breaker has tripped on order lifecycle calls).
  - `_limiter.acquire()` runs before every outbound call (REST + L1
    auth) so the broker's per-account ceiling is unreachable in steady
    state.
  - Adapter accepts optional `circuit_breaker` and `rate_limiter`
    constructor kwargs; defaults to a fresh in-instance breaker and a
    no-op limiter so unit tests build adapters without touching the
    package singletons.

- Updated `integrations/clob/__init__.py`:
  - Module-level `_breaker` / `_limiter` singletons survive the per-call
    adapter construction pattern in `domain/execution/live.py`.
  - `get_clob_breaker()` / `get_clob_rate_limiter()` lazy accessors.
  - `reset_clob_resilience()` test seam (production never calls).
  - `_on_circuit_open(name)` lazy-imports `notify_operator` and pages
    the operator on Telegram with one bold "⛔️ CLOB circuit OPEN"
    message including the breaker name. Lazy import avoids dragging
    the bot stack into the preflight script.
  - `get_clob_client()` injects both singletons into every real
    `ClobAdapter` it builds.

- New `scripts/mainnet_preflight.py`:
  - Five checks, ordered: `activation_guards`, `polymarket_secrets`,
    `use_real_clob`, `eip712_sign`, `hmac_headers`.
  - `eip712_sign` signs one ClobAuth payload locally via
    `ClobAuthSigner.sign_clob_auth`. NO broker call.
  - `hmac_headers` builds one `build_l2_headers(...)` tuple locally.
    NO broker call.
  - Each check returns a `CheckResult(name, passed, detail)`. Detail
    never echoes secret values -- only key names and shape facts.
  - `run_preflight(*, settings, checks)` is injectable so tests
    construct synthetic Settings without poking `os.environ`.
  - `main()` prints one PASS/FAIL line per check, then a final
    "RESULT: PASS / FAIL" footer; exits 0 / 1 accordingly.
  - Confirmed via test that no httpx call ever fires in any check.

- Updated `api/ops.py` — new "CLOB circuit" card on the dashboard:
  - Reads `get_clob_breaker().snapshot()`.
  - State badge: `CLOSED` ok / `HALF_OPEN` warn / `OPEN` fail / N/A
    warn.
  - Detail line shows `failures/threshold` and (when OPEN) the seconds
    remaining until the auto half-open window.
  - DB / breaker resolution failures degrade to N/A rather than 5xx-ing
    the page.

- Updated `config.py` — three new settings, all with safe defaults:
  - `CIRCUIT_BREAKER_THRESHOLD: int = 5`
  - `CIRCUIT_BREAKER_RESET_SECONDS: int = 60`
  - `CLOB_RATE_LIMIT_RPS: int = 10`

- Tests (5 new files, 48 new unit tests):
  - `tests/test_clob_circuit_breaker.py` (11 tests) -- full state-
    machine coverage, threshold tripping, half-open trial,
    reopen-on-failure, auth-class non-counting, on_open swallow,
    snapshot, force_close.
  - `tests/test_clob_rate_limiter.py` (7 tests) -- under-limit no
    sleep, at-limit sleep math, burst then steady state, zero/negative
    rps disables, snapshot, zero-token acquire.
  - `tests/test_clob_error_classification.py` (15 tests) -- pure
    classifier per status, end-to-end `post_order` against the live
    adapter for each of {auth-class, 429, 5xx, timeout, network,
    eventual success}, parametrised across status codes.
  - `tests/test_clob_breaker_integration.py` (4 tests) -- integration
    contract: breaker wraps `post_order` / `cancel_order` /
    `get_order`; OPEN raises `ClobCircuitOpenError` with NO broker
    call (verified by counting transport handler invocations).
  - `tests/test_mainnet_preflight.py` (11 tests) -- happy path,
    each check's failure mode, legacy passphrase alias, aggregate
    failure, and a defense-in-depth "no httpx call in preflight"
    assertion.

- Existing `tests/test_clob_adapter.py` updated:
  - `test_post_order_5xx_retries_then_raises` now expects
    `ClobMaxRetriesError` carrying a `ClobServerError` `last_exception`
    (previously expected raw `httpx.HTTPStatusError`). Retry count
    behavior preserved (3 transport calls).
  - All other adapter tests unchanged -- `ClobAuthError` is a subclass
    of `ClobAPIError`, so `pytest.raises(ClobAPIError)` on the 400
    test still matches.

- Dead code removal:
  - Deleted `services/deposit_watcher.py` (622 lines). Replaced by the
    canonical deposit watcher in `scheduler.watch_deposits`. Confirmed
    no production / test file imports the dead module.
  - Deleted `services/ledger.py` (208 lines). Replaced by
    `wallet/ledger.py`. Confirmed no consumers.
  - Cleared the 5 `lib/` F401 leakages flagged in PROJECT_STATE:
    `lib/strategies/logic_arb.py:42`, `lib/strategies/value_investor.py:30`,
    `lib/strategies/weather_arb.py:25,29`, `lib/strategy_base.py:34`.
  - `ruff check lib/` is clean post-change.

---

## 2. Current System Architecture

```
domain/execution/live.execute()
        |
        v
get_clob_client(settings)
   |   USE_REAL_CLOB=False -> MockClobClient (paper, no resilience needed)
   |   USE_REAL_CLOB=True  -> ClobAdapter(
   |                              circuit_breaker=get_clob_breaker(),
   |                              rate_limiter=get_clob_rate_limiter(),
   |                              max_retries=3, ...)
   v
ClobAdapter.post_order / cancel_order / get_order
        |
        v  (1) breaker gate
CircuitBreaker.call(fn)
   |   state == OPEN          -> raise ClobCircuitOpenError (no fn call)
   |   state == HALF_OPEN     -> trial run; success closes, failure re-opens
   |   state == CLOSED        -> run fn; record success/failure
        |
        v  (2) retry loop -- tenacity, 3 attempts, exponential 1..8s
_signed_request
        |
        v  (3) rate limiter
RateLimiter.acquire()
        |
        v  (4) HTTP request via httpx + classify
_do_request
   |   2xx                    -> return JSON
   |   400/401/403            -> raise ClobAuthError      (NOT retried)
   |   404 / other 4xx        -> raise ClobAPIError       (NOT retried)
   |   429                    -> raise ClobRateLimitError (RETRIED)
   |   500/502/503/504        -> raise ClobServerError    (RETRIED)
   |   httpx.TimeoutException -> raise ClobTimeoutError   (RETRIED)
   |   httpx.HTTPError        -> raise ClobNetworkError   (RETRIED)
        |
        v
After max retries on retryable exception:
   raise ClobMaxRetriesError(last_exception=...)
        |
        v
Breaker counts the failure. After CIRCUIT_BREAKER_THRESHOLD=5
consecutive transport failures (auth-class is excluded) -> OPEN
   -> on_open -> notify_operator("⛔️ CLOB circuit OPEN ...")
        |
        v
Auto HALF_OPEN after CIRCUIT_BREAKER_RESET_SECONDS=60
   -> next call is the trial; one success closes it, one failure
      re-opens and restarts the timer.

ops dashboard (api/ops.py)
        |
        v
get_clob_breaker().snapshot()
   -> "CLOB circuit" card: state badge + failures/threshold + ETA.
```

Pipeline placement (the locked stage list never changes):

```
DATA -> STRATEGY -> INTELLIGENCE -> RISK -> EXECUTION (live.execute) ->
LIFECYCLE (Phase 4C polling + Phase 4D WS push + Phase 4E resilience) ->
MONITORING (ops dashboard + Telegram operator alerts)
```

`mainnet_preflight.py` lives outside this pipeline -- it is an
operator-run script that validates the runtime env BEFORE any guard is
flipped. Five local checks (no broker call) gate activation safely.

---

## 3. Files Created / Modified

Created:

- `projects/polymarket/crusaderbot/integrations/clob/circuit_breaker.py`
  `CircuitBreaker` + `STATE_CLOSED` / `STATE_OPEN` / `STATE_HALF_OPEN`
  + `FAILURE_EXCEPTIONS` tuple.
- `projects/polymarket/crusaderbot/integrations/clob/rate_limiter.py`
  `RateLimiter` token-bucket.
- `projects/polymarket/crusaderbot/scripts/mainnet_preflight.py`
  Five-check preflight with no-broker-call signing tests.
- `projects/polymarket/crusaderbot/tests/test_clob_circuit_breaker.py`
  11 tests covering the state machine.
- `projects/polymarket/crusaderbot/tests/test_clob_rate_limiter.py`
  7 tests covering the token bucket.
- `projects/polymarket/crusaderbot/tests/test_clob_error_classification.py`
  15 tests covering classifier + retry semantics.
- `projects/polymarket/crusaderbot/tests/test_clob_breaker_integration.py`
  4 tests covering breaker-wraps-adapter contract.
- `projects/polymarket/crusaderbot/tests/test_mainnet_preflight.py`
  11 tests covering preflight checks.
- `projects/polymarket/crusaderbot/reports/forge/resilience.md`
  This report.

Modified:

- `projects/polymarket/crusaderbot/integrations/clob/exceptions.py`
  Widened hierarchy: ClobAuthError now subclasses ClobAPIError;
  added ClobRateLimitError, ClobServerError, ClobTimeoutError,
  ClobNetworkError, ClobMaxRetriesError, ClobCircuitOpenError.
- `projects/polymarket/crusaderbot/integrations/clob/adapter.py`
  `_classify_http_error`, breaker / limiter wiring on
  post_order / cancel_order / get_order, retry-on-typed-exceptions,
  ClobMaxRetriesError wrapping, httpx exception translation.
- `projects/polymarket/crusaderbot/integrations/clob/__init__.py`
  `_breaker` / `_limiter` singletons + accessors +
  `reset_clob_resilience` test seam + `_on_circuit_open` Telegram
  alert callback wired into `get_clob_client`.
- `projects/polymarket/crusaderbot/api/ops.py`
  `_circuit_state_snapshot()` + new "CLOB circuit" card on the ops
  dashboard.
- `projects/polymarket/crusaderbot/config.py`
  `CIRCUIT_BREAKER_THRESHOLD = 5`, `CIRCUIT_BREAKER_RESET_SECONDS = 60`,
  `CLOB_RATE_LIMIT_RPS = 10`.
- `projects/polymarket/crusaderbot/tests/test_clob_adapter.py`
  Updated 5xx retry test to expect `ClobMaxRetriesError` carrying a
  `ClobServerError` last_exception (count-of-3 retry behavior
  preserved).

Deleted (dead code, no consumers):

- `projects/polymarket/crusaderbot/services/deposit_watcher.py`
  (legacy Alchemy-WS deposit watcher; replaced by
  `scheduler.watch_deposits`)
- `projects/polymarket/crusaderbot/services/ledger.py`
  (legacy sub-account ledger; replaced by `wallet/ledger.py`)

Cleared (lib F401 leakage):

- `lib/strategy_base.py` -- removed unused `field` import.
- `lib/strategies/logic_arb.py` -- removed unused `get_no_price`.
- `lib/strategies/value_investor.py` -- removed unused `get_no_price`.
- `lib/strategies/weather_arb.py` -- removed unused `json` and
  `urllib.request` imports.

State / changelog:

- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` -- the seven
  ASCII-bracket sections are updated to reflect Phase 4E status and the
  cleared known issues. Activation posture statements unchanged.
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` -- one new lane-
  closure entry appended.

Not modified (preserved):

- `domain/execution/live.py` and `domain/execution/lifecycle.py` -- the
  callers continue to use `get_clob_client()` and pick up the new
  resilience automatically. No call-site change needed.
- `integrations/clob/auth.py` and `integrations/clob/ws.py` -- no
  resilience-layer changes; existing test coverage is sufficient.
- `migrations/*.sql` -- no schema changes.
- All Phase 4D WebSocket files -- the WS lane has its own reconnect /
  heartbeat resilience; the REST breaker / limiter is independent.

---

## 4. What Is Working

- Error classification (verified by 15 tests in
  `test_clob_error_classification.py`):
  - 400 / 401 / 403 -> `ClobAuthError`, no retry, single transport call.
  - 429 -> `ClobRateLimitError`, retried 3 times, then
    `ClobMaxRetriesError` with `last_exception` = `ClobRateLimitError`.
  - 500 / 502 / 503 / 504 -> `ClobServerError`, retried, then
    `ClobMaxRetriesError`.
  - `httpx.TimeoutException` (incl. `ConnectTimeout`) -> retried as
    `ClobTimeoutError`, then `ClobMaxRetriesError`.
  - `httpx.HTTPError` (incl. `ConnectError`) -> retried as
    `ClobNetworkError`, then `ClobMaxRetriesError`.
  - 404 (other 4xx) -> `ClobAPIError`, no retry.
  - Eventual-success path: 503 once then 200 returns the JSON after one
    retry (`calls = 2`).

- Circuit breaker (verified by 11 tests in
  `test_clob_circuit_breaker.py` + 4 integration tests):
  - CLOSED -> OPEN after threshold consecutive failures (excluding
    auth-class).
  - OPEN raises `ClobCircuitOpenError` with NO underlying call --
    explicitly asserted via call-counter on the inner function.
  - Reset window auto-transitions OPEN -> HALF_OPEN.
  - HALF_OPEN trial success -> CLOSED + counter reset.
  - HALF_OPEN trial failure -> OPEN + restart cool-down + on_open
    fires AGAIN.
  - `on_open` callback fires exactly once per OPEN transition; failures
    inside the callback are swallowed.
  - `force_close()` resets state for tests / future ops endpoint.
  - `snapshot()` returns the state, failure count, and seconds-until-
    half-open for the dashboard.

- Rate limiter (verified by 7 tests in `test_clob_rate_limiter.py`):
  - Steady-state under-limit acquisitions never sleep.
  - At-limit acquisition sleeps for the deficit / rps deadline.
  - Burst absorbs up to `burst` tokens; refills continuously.
  - `rps <= 0` short-circuits (no-op), used by every adapter unit
    test that wants deterministic timing.
  - Snapshot reflects current bucket level after refill.

- Mainnet preflight (verified by 11 tests in
  `test_mainnet_preflight.py`):
  - All five checks PASS with a fully-configured Settings; exit 0.
  - Activation guard FAIL detail names the missing flag.
  - Missing Polymarket secret FAIL detail names the missing key.
  - Legacy `POLYMARKET_PASSPHRASE` accepted as fallback.
  - `USE_REAL_CLOB=False` FAIL.
  - Bad private key FAIL with descriptive detail.
  - Unset private key FAIL with descriptive detail.
  - Bad base64 secret FAIL on hmac check.
  - Aggregate path: any single failure produces overall FAIL.
  - Defense-in-depth: monkeypatching httpx.AsyncClient.{request,get,post}
    to raise AssertionError still allows preflight to PASS (proof that
    no broker call is made).

- Ops dashboard:
  - `_circuit_state_snapshot()` reads `get_clob_breaker().snapshot()`
    and degrades to N/A on any resolution failure.
  - The new card renders: state badge, failure count / threshold, and
    (when OPEN) the seconds remaining until the auto half-open window.
  - The kill switch / health / audit cards continue to render
    independently -- a broken breaker accessor never 5xx-es the page.

- Operator Telegram alert:
  - `_on_circuit_open(name)` lazy-imports `notify_operator` and sends
    `"⛔️ CLOB circuit OPEN ..."`. Wired into `get_clob_client()` so
    every real adapter shares it.
  - Telegram outage on alert delivery is logged at ERROR and swallowed
    -- the breaker still trips and serves `ClobCircuitOpenError`.

- Activation posture preserved:
  - `USE_REAL_CLOB` default remains `False` -- CI never connects.
  - `ENABLE_LIVE_TRADING` is NOT mutated, NOT read by the new code.
  - `EXECUTION_PATH_VALIDATED` / `CAPITAL_MODE_CONFIRMED` are NOT
    mutated.
  - No real Polymarket secret is required for any test in this PR.
  - `mainnet_preflight.py` is operator-invoked and never run in CI;
    the `USE_REAL_CLOB` check FAILS in the default CI env, which is
    the intended posture.

- Test posture:
  - Full crusaderbot suite: 812 / 812 passing locally.
  - 100 / 100 existing CLOB-related tests still passing.
  - 48 / 48 new resilience + preflight tests passing.
  - Ruff clean on every touched file
    (`lib/`, `integrations/clob/`, `scripts/mainnet_preflight.py`,
    `api/ops.py`, every new test file).

---

## 5. Known Issues

- The breaker is package-level (one instance) -- if a future caller
  needs per-broker breakers (e.g. a separate L1 endpoint with its own
  health), they should pass an explicit `circuit_breaker=` kwarg into
  `ClobAdapter`. The current design is correct for the single-broker
  steady state.

- The rate limiter is a pure token bucket with no per-endpoint
  weighting. Polymarket may enforce different per-route ceilings (e.g.
  /order vs /data/orders). Phase 4F can split the bucket if telemetry
  indicates head-of-line blocking; the current 10 RPS sits well below
  the broker's documented per-account ceiling.

- `cancel_all_orders` and the bulk `get_*` paths are intentionally NOT
  wrapped by the breaker. Rationale: when the breaker has already
  tripped on a stuck order surface, the operator MUST still be able to
  bulk-cancel via the existing /admin path. Wrapping those would
  produce a deadlock. Documented in the adapter docstring.

- Operator alert text is plain-Markdown; Telegram's MarkdownV2 escape
  rules are NOT applied. Acceptable for the static circuit-open
  template (no user-supplied content) but a future structured-alert
  refactor should switch to MarkdownV2 to avoid silent send drops on
  reserved characters.

- The dashboard "CLOB circuit" card auto-refreshes via the existing
  page-level `<meta http-equiv="refresh" content="30">`. There is no
  WebSocket push; an OPEN event is visible within 30 seconds at
  worst. Acceptable for the demo posture; a follow-up could push via
  Server-Sent Events.

- `mainnet_preflight.py` does NOT validate that the operator has
  funded the wallet, deposited USDC, or pre-approved the Exchange
  contracts. Those are on-chain state checks that require a Polygon
  RPC round-trip; the script's design intentionally avoids any network
  call. A separate `WARP/CRUSADERBOT-MAINNET-ONCHAIN-PREFLIGHT` lane
  would cover that surface.

- `pytest-asyncio` warns on a handful of sync helper tests that share
  the module-level `pytestmark = pytest.mark.asyncio` convention --
  matches the existing project posture (Phase 4C / 4D had identical
  warnings on `_backoff_delay` math + scheduler-registration helpers).
  Cosmetic only; suite still 812 / 812.

---

## 6. What Is Next

WARP•SENTINEL validation required:

- Source: `projects/polymarket/crusaderbot/reports/forge/resilience.md`
- Tier: MAJOR
- Claim: FULL RUNTIME INTEGRATION
- Validation focus:
  - Activation posture: `ENABLE_LIVE_TRADING`, `EXECUTION_PATH_VALIDATED`,
    `CAPITAL_MODE_CONFIRMED`, `USE_REAL_CLOB` defaults are all unchanged
    by this PR; preflight FAILs in default CI env.
  - Error classification: every retry / no-retry mapping in the task
    spec lands on the right typed exception. 4xx auth class is NEVER
    retried.
  - Circuit breaker: state machine matches spec; OPEN does not call
    underlying; `on_open` Telegram alert fires; auth-class never trips
    the breaker.
  - Rate limiter: throttles at limit; passes under limit; configurable
    via `CLOB_RATE_LIMIT_RPS`.
  - Wraps required surfaces: `post_order`, `cancel_order`, `get_order`
    only; bulk paths intentionally excluded (rationale documented).
  - Mainnet preflight: PASS / FAIL exit codes correct; no broker call
    in any branch (proven by the `_explode` monkeypatch test).
  - Ops dashboard exposes circuit state and degrades to N/A on resolver
    failure.
  - Dead code removal does NOT regress the suite (812 / 812).
  - Lib F401 leakage cleared (`ruff check lib/` is clean).

After SENTINEL APPROVED: WARP🔹CMD merge decision on this PR.

Post-merge candidates (NOT in scope for Phase 4E):

- `WARP/CRUSADERBOT-MAINNET-ONCHAIN-PREFLIGHT` -- on-chain wallet /
  approval / balance checks for the mainnet readiness checklist.
- `WARP/CRUSADERBOT-OPS-CIRCUIT-RESET` -- operator endpoint to
  `force_close()` the breaker via /ops + Telegram.
- `WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP` (still pending from
  Phase 4B) -- remove `_build_clob_client` from
  `integrations/polymarket.py`.
- `WARP/CRUSADERBOT-LIFECYCLE-LEDGER-REVERSAL` (still pending from
  Phase 4C) -- ledger credit on cancel/expiry.

Activation posture stays paper-only. No live activation, no capital
mode flip, no `USE_REAL_CLOB` owner flip in this PR.
