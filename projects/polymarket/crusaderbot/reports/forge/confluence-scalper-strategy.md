# WARP•FORGE — Confluence Scalper Strategy

**Branch:** `WARP/confluence-scalper-strategy`
**Issue:** #1267
**Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Existing `BaseStrategy` contract — `scan()` emits `SignalCandidate`s, `evaluate_exit()` returns hold, `default_tp_sl()` returns deterministic positive tuple, no order placement, no risk bypass, no live activation change.
**Not in Scope:** No changes to `copy_trade`, `momentum_reversal`, or `signal_following` behavior. No execution-engine changes. No risk-engine changes. No Telegram UX changes. No live-trading activation or guard changes.

---

## 1. What was built

A new optional `ConfluenceScalperStrategy` added to the existing CrusaderBot strategy framework. The strategy emits `SignalCandidate`s only when **all four** signals align (confluence):

- market is active, accepting orders, not blacklisted, not closed
- YES price sits inside the mid-band `[0.30, 0.70]` (no tail markets)
- 24h drift magnitude inside `[0.02, 0.08]` — shallow move, not a trend break
- liquidity ≥ `max(user_filter, 5_000 USDC)` and 24h volume ≥ `2_000 USDC`

Side is derived from drift direction (mean-reversion):

- `drift < 0` → `YES` (bet the dip bounces toward mid)
- `drift > 0` → `NO`  (bet the pop pulls back toward mid)

Confidence is a weighted sum of four sub-scores, each clamped to `[0, 1]`:

- drift sweet-spot proximity (weight 0.35)
- liquidity excess above floor (weight 0.25)
- volume excess above floor (weight 0.20)
- mid-band proximity to 0.50 (weight 0.20)

Default TP/SL: `(0.08, 0.04)` — tighter than `momentum_reversal` to match the scalp profile.

Suggested size fraction: `0.04` of allocated capital, clamped to `[1.0, 25.0]` USDC. Strictly an upstream hint — the risk gate remains authoritative on actual sizing.

---

## 2. Current system architecture

```
DATA -> [STRATEGY <-- confluence_scalper] -> INTELLIGENCE -> RISK -> EXECUTION -> MONITORING
```

- `ConfluenceScalperStrategy.scan()` calls `integrations/polymarket.get_markets(limit=100)` only.
- No DB reads, no order placement, no risk-gate touch, no guard mutation.
- `evaluate_exit()` returns `ExitDecision(should_exit=False, reason="hold")` — platform TP/SL watcher remains the exit authority.
- `bootstrap_default_strategies()` appends `ConfluenceScalperStrategy` to the existing trio (`copy_trade`, `momentum_reversal`, `signal_following`); idempotency preserved via existing `try/except KeyError` pattern.
- Risk-profile compatibility: `["balanced", "aggressive", "custom"]`. `conservative` is explicitly excluded — scalping demands frequent re-entries inappropriate for the conservative envelope.
- All `except Exception` branches log via `structlog`-compatible `logger.warning`/`logger.debug` and return `[]` so a single bad market cannot crash the scheduler scan loop.

---

## 3. Files created / modified (full repo-root paths)

Created:

- `projects/polymarket/crusaderbot/domain/strategy/strategies/confluence_scalper.py`
- `projects/polymarket/crusaderbot/tests/test_confluence_scalper.py`
- `projects/polymarket/crusaderbot/reports/forge/confluence-scalper-strategy.md`

Modified:

- `projects/polymarket/crusaderbot/domain/strategy/strategies/__init__.py` — export `ConfluenceScalperStrategy`.
- `projects/polymarket/crusaderbot/domain/strategy/registry.py` — `bootstrap_default_strategies()` now also registers `ConfluenceScalperStrategy`.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

---

## 4. What is working

- `py_compile` clean on `confluence_scalper.py`, `strategies/__init__.py`, `registry.py`, `tests/test_confluence_scalper.py`.
- Test coverage (hermetic, no network / no DB / no broker — `pm.get_markets` patched with `AsyncMock`):
  - Contract: `BaseStrategy` subclass, attributes present, `default_tp_sl()` returns positive scalp tuple, `evaluate_exit()` returns hold.
  - Risk-profile compat: `conservative` excluded; `balanced` / `aggressive` / `custom` accepted via `StrategyRegistry.get_compatible`.
  - Registry: bootstrap registers `confluence_scalper`, preserves the existing three strategies, idempotent on repeated bootstrap.
  - `scan()` failure paths: empty markets, raised exception, malformed market dicts — all return `[]` without re-raising.
  - Status filters: inactive, closed, non-accepting — all skipped.
  - Blacklist: both `condition_id` and `market_id` paths.
  - Mid-band YES price: boundary `[MIN_YES_PRICE, MAX_YES_PRICE]` accepted, just outside skipped.
  - Drift magnitude band: boundary `[MIN_ABS_DRIFT, MAX_ABS_DRIFT]` accepted, just outside skipped; missing drift skipped.
  - Liquidity floor: both internal floor (`MIN_LIQUIDITY_USDC`) and user-filter override (`min_liquidity` higher than internal) enforced.
  - Volume floor: `MIN_VOLUME_24H` enforced.
  - Side selection: `drift < 0` → `YES`; `drift > 0` → `NO`.
  - Candidate shape: `strategy_name == "confluence_scalper"`; metadata contains `score_components` (drift / liquidity / volume / midband each in `[0,1]`) and `reason`; `reasoning` populated; confidence in `[0,1]`; suggested size in `[1.0, 25.0]`; results sorted by confidence descending.

---

## 5. Known issues

- Pytest not exercised in this remote container — telegram / cryptography Rust binding chain unsatisfiable in the FORGE execution sandbox (same posture as WARP-58 / WARP-59). WARP🔹CMD or CI should run `pytest projects/polymarket/crusaderbot/tests/test_confluence_scalper.py` before merge. The test file mirrors `test_momentum_reversal.py` import surface, which is already green in CI, so the import path itself is sound.
- No production wiring (Telegram preset picker, auto-trade scheduler activation, per-user opt-in) — strategy is registered and discoverable via `StrategyRegistry.list_available()` / `get_compatible()` but **not** added to any user's active preset. Wiring is a separate WARP🔹CMD-directed lane.

---

## 6. What is next

- WARP🔹CMD review of this PR.
- If accepted: separate lane to surface `confluence_scalper` in the Telegram preset picker and the WebTrader Auto-Trade settings.
- Optional follow-up: backtest the confluence heuristic against a historical Polymarket sample once data spine permits — out of scope here.

---

## Suggested Next Step

Merge after WARP🔹CMD review + CI green; queue a separate, scoped lane for Telegram + WebTrader preset exposure (no preset-activation change is in this PR).
