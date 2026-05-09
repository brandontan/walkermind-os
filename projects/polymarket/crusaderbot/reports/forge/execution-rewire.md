# WARP•FORGE REPORT — execution-rewire

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: domain/execution/live.py — CLOB client migration off legacy py-clob-client path
Not in Scope: router.py caller changes; order_type surface in Telegram commands; Phase 4C on-chain schema reimplementation
Suggested Next Step: WARP•SENTINEL validation required before merge

---

## 1. What Was Built

Phase 4B live execution rewire: `domain/execution/live.py` migrated from the
legacy `integrations.polymarket._build_clob_client()` / `py-clob-client` SDK path
onto the Phase 4A `get_clob_client()` factory and `ClobClientProtocol` interface
introduced in WARP/CRUSADERBOT-PHASE4A-CLOB-ADAPTER.

Changes:
- `from ...integrations import polymarket` removed — legacy path gone
- `get_clob_client`, `ClobClientProtocol`, `ClobAuthError`, `ClobConfigError`,
  `MockClobClient` imported from `...integrations.clob`
- `execute()` gains `order_type: str = "GTC"` and `clob_client: ClobClientProtocol | None = None`
- Dry-run intercept: `USE_REAL_CLOB=True` + `ENABLE_LIVE_TRADING=False` →
  logs order intent, returns `{"status": "dry_run", "_mock": True}` without DB write or broker call
- Pre/post submit classification: `ClobAuthError` → `LivePreSubmitError` (safe fallback);
  all other exceptions from `post_order()` → `LivePostSubmitError` (ambiguous, no fallback)
- `ClobConfigError` from `get_clob_client()` → `LivePreSubmitError` in execute()
  (Codex P2); claim rollback + `RuntimeError` in close_position()
- `assert_live_guards()` gains USE_REAL_CLOB check: blocks MockClobClient phantom
  live exposure when all three env guards are set (Codex P1 round 1)
- `close_position()` gains USE_REAL_CLOB=False guard at function entry, before
  pool.acquire or atomic claim: blocks MockClobClient phantom close (Codex P1 round 2)
- `close_position()` gains `clob_client: ClobClientProtocol | None = None`;
  `polymarket.submit_live_order()` replaced with `client.post_order(side="SELL", order_type="GTC")`
- 27 unit tests covering all above paths (hermetic — no DB, no network, no Telegram)

---

## 2. Current System Architecture

```
Signal → router.execute()
           │
           ├── assert_live_guards()  ← 3 env guards + tier + trading_mode
           │     ENABLE_LIVE_TRADING
           │     EXECUTION_PATH_VALIDATED
           │     CAPITAL_MODE_CONFIRMED
           │
           ├── live.execute()
           │     ├── dry-run intercept  [USE_REAL_CLOB=True, ENABLE_LIVE_TRADING=False]
           │     │     → log intent, return mock fill (no DB, no broker)
           │     ├── assert_live_guards()  [defense-in-depth repeat inside execute()]
           │     ├── DB idempotency claim (INSERT ON CONFLICT DO NOTHING)
           │     │     duplicate key → {"status": "duplicate"} (no submit)
           │     └── client.post_order(token_id, side, price, size, order_type)
           │           ├── USE_REAL_CLOB=False → MockClobClient (paper-safe default)
           │           └── USE_REAL_CLOB=True  → ClobAdapter (EIP-712 + HMAC-SHA256)
           │                 ClobAuthError → LivePreSubmitError (router fallback safe)
           │                 other exc    → LivePostSubmitError (NO fallback)
           │
           └── close_position()
                 ├── atomic DB claim (UPDATE positions SET status='closing')
                 │     None returned → early exit (already_closed)
                 └── client.post_order(side="SELL", order_type="GTC")
                       failure → DB rollback to 'open' + re-raise
```

Pipeline: DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION (this layer) → MONITORING

---

## 3. Files Created / Modified

Modified:
- `projects/polymarket/crusaderbot/domain/execution/live.py`
  Full replacement: legacy polymarket SDK path removed; ClobClientProtocol wired in;
  dry-run mode added; order_type + clob_client params added to execute() and
  close_position(); ClobAuthError pre-submit classification added.

Created:
- `projects/polymarket/crusaderbot/tests/test_live_execution_rewire.py`
  27 hermetic unit tests (no DB, no network, no Telegram).
  Tests: TestAssertLiveGuards (7), TestDryRunMode (3), TestGuardRouting (2),
  TestOrderTypeDispatch (3), TestIdempotencyKey (2), TestExceptionClassification (3),
  TestClosePosition (7).

Created:
- `projects/polymarket/crusaderbot/reports/forge/execution-rewire.md` (this file)

Not modified (preserved):
- `domain/execution/router.py` — router still calls `live_engine.execute(...)` without `order_type`;
  this is intentional; `order_type` defaults to "GTC" and the router's API surface
  is a Phase 4C concern.
- `integrations/polymarket.py` — `_build_clob_client()` / legacy functions remain intact;
  they are no longer called by live.py but may be referenced elsewhere (e.g. redemption path).

---

## 4. What Is Working

- `execute()` uses `get_clob_client(s)` factory (no direct py-clob-client instantiation)
- All 3 activation guards (ENABLE_LIVE_TRADING, EXECUTION_PATH_VALIDATED,
  CAPITAL_MODE_CONFIRMED) still block real submissions in `assert_live_guards()`
- USE_REAL_CLOB guard in `assert_live_guards()`: prevents MockClobClient from
  inserting mode='live' DB rows + debiting ledger without a real Polymarket order
  (Codex P1 round 1, fixed)
- Dry-run: `USE_REAL_CLOB=True` + `ENABLE_LIVE_TRADING=False` → logs intent,
  returns mock fill, zero DB writes, zero broker calls
- Idempotency: `ON CONFLICT (idempotency_key) DO NOTHING` prevents duplicate submits on retry
- GTC and FOK: `order_type` param passes through to `client.post_order(order_type=...)`
- `ClobAuthError` → `LivePreSubmitError` (signing failure before network → router may fallback)
- Non-auth exceptions → `LivePostSubmitError` (post-submit ambiguous → NO fallback)
- `ClobConfigError` from `get_clob_client()` → `LivePreSubmitError` in execute(),
  `RuntimeError` (with claim rollback) in close_position() (Codex P2, fixed)
- `close_position()` USE_REAL_CLOB=False guard fires BEFORE atomic DB claim:
  prevents MockClobClient from phantom-closing a live position (Codex P1 round 2, fixed)
- `close_position()` uses `client.post_order(side="SELL", order_type="GTC")`
- Rollback on close failure: positions reverted to `status='open'` on broker error
- `clob_client` injection on both `execute()` and `close_position()` enables hermetic testing
- Ruff passes on all changed files; 27 hermetic unit tests total

---

## 5. Known Issues

- `integrations/polymarket.py` `_build_clob_client()` function is now dead code in the
  live execution path (live.py no longer calls it). It is still referenced by
  `submit_live_redemption()` indirectly and kept intact. A dedicated cleanup lane
  WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP can remove it post-Phase-4B merge.
- `router.py` does not forward `order_type` — callers always get GTC. Exposing
  `order_type` through the full signal→router→execute chain is Phase 4C scope.
- Full CI test count: 624+27 = 651 expected (environment in this session lacked
  system-level cryptography deps; CI environment has all deps installed).

---

## 6. What Is Next

WARP•SENTINEL validation required:
- Source: `projects/polymarket/crusaderbot/reports/forge/execution-rewire.md`
- Tier: MAJOR
- Scope: guard routing correctness, dry-run safety, idempotency, exception classification,
  activation guard posture (PAPER ONLY — ENABLE_LIVE_TRADING must remain NOT SET)

After SENTINEL APPROVED: WARP🔹CMD merge decision on this PR.
Post-merge: WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP (MINOR) to remove
`_build_clob_client` dead code from `integrations/polymarket.py`.
