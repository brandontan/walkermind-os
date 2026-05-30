# bnb-monitor-only

## 1. What was built

Removes BNB from the tradable crypto-short asset universe and moves it to **monitor-only** status per Polybot directive Part 4 Tier 3. The directive's reasoning: Polymarket BNB candle markets are too thin (wider spreads, lower CLOB depth) for the current `MAX_SPREAD=0.02` + `MIN_COMPLETE_SET_EDGE=0.005` + `MIN_LIQUIDITY=500` thresholds to identify edges that survive slippage. Recommended cooling-off period: 30 days of edge-stat collection before re-evaluating.

This mirrors the same playbook already applied to XRP/DOGE/HYPE in `WARP/R00T/candle-preset-asset-config` (MERGED PR #1480) — same removal sites, same defensive scan-job filter, same forward path to re-enabling.

## 2. Current system architecture

```text
Frontend selectors            Backend validator              Scan-job runtime
─────────────────             ──────────────────             ────────────────
AutoTradePage.CRYPTO_ASSETS   _CRYPTO_SHORT_ASSETS           _filter_monitor_only_assets
AdminUserDrawer.CRYPTO_ASSETS _VALID_ASSETS (derived)        _MONITOR_ONLY_ASSETS
        │                            │                              │
        └─ ["BTC","ETH","SOL"] ──────┴── frozenset of above ────────┤
                                                                    │
   user picks BTC/ETH/SOL          activator                  on EVERY scan tick,
   from UI ─────────────────►      rejects BNB ─────────────► drop BNB from any
                                   at preset                  user's persisted
                                   activation                 selected_assets array

domain.strategy.eligibility.ASSET_ALIASES — UNCHANGED
    BNB stays whitelisted for asset-text matching so market_data can
    continue observing BNB markets for the 30-day stats collection
    (directive Part 4 Phase 2 entry criterion).
```

The monitor-only filter is a defensive belt-and-braces — the router validator already rejects BNB at preset-activation time once it's out of `_VALID_ASSETS`, but existing user rows persisted before this lane shipped can still carry BNB in their JSONB `selected_assets` array. The scan-job filter strips those entries on every tick so the scanner never queues a BNB market for any user. The next preset re-activation through the router normalises the DB column permanently.

## 3. Files created / modified

```text
projects/polymarket/crusaderbot/webtrader/backend/router.py
projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx
projects/polymarket/crusaderbot/webtrader/frontend/src/components/AdminUserDrawer.tsx
projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py
projects/polymarket/crusaderbot/tests/test_bnb_monitor_only.py
projects/polymarket/crusaderbot/reports/forge/bnb-monitor-only.md
projects/polymarket/crusaderbot/state/PROJECT_STATE.md
projects/polymarket/crusaderbot/state/CHANGELOG.md
```

### `webtrader/backend/router.py`
- `_CRYPTO_SHORT_ASSETS: tuple[str, ...] = ("BTC", "ETH", "SOL")` (was `("BTC", "ETH", "SOL", "BNB")`)
- `_VALID_ASSETS` is derived → frozenset shrinks automatically
- Updated docstring to spell out monitor-only status + cooling-off rationale

### `webtrader/frontend/src/pages/AutoTradePage.tsx`
- `CRYPTO_ASSETS = ["BTC", "ETH", "SOL"]` (was 4 items)
- Close Sweep preset signal text: "Final 35s entry on **BTC/ETH/SOL** candles" (was "BTC/ETH/SOL/BNB")
- Comment block explains the directive Part 4 reasoning so a future editor knows why BNB is missing

### `webtrader/frontend/src/components/AdminUserDrawer.tsx`
- `CRYPTO_ASSETS = ["BTC", "ETH", "SOL"]` (was 4 items)

### `services/signal_scan/signal_scan_job.py`
- New module-level constant `_MONITOR_ONLY_ASSETS: frozenset[str] = frozenset({"BNB"})`
- New helper `_filter_monitor_only_assets(assets) -> list[str]`:
  - Case-insensitive (DB rows may pre-date the router's uppercase normalisation)
  - Returns a list (not generator) so call sites' `tuple(...)` / `len(...)` keep working
  - Drops blanks (corruption / partial writes don't bleed into the matcher)
- Wired at all 3 sites that read `row["selected_assets"]`:
  - `_build_user_context` (main path, used by late_entry_v3 scan)
  - Two extra scan loops at lines ~1901 and ~2251

### `tests/test_bnb_monitor_only.py`
12 tests covering:
- 4 tradable-set assertions (BNB absent, defaults unchanged, exact-equals lock to BTC/ETH/SOL)
- 1 monitor-only set membership
- 6 filter-behaviour tests (drops BNB, preserves tradables, case-insensitive, empty/None/falsy inputs, drops blanks, returns list type)
- 1 source-level pin (`_build_user_context` must call the filter)

## 4. What is working

- `ruff check` + `py_compile` clean on all modified Python files.
- Backend `_CRYPTO_SHORT_ASSETS` shrinks → router validator rejects BNB on any new `/autotrade/preset` activation.
- Frontend selectors no longer offer BNB → user can't pick it.
- Scan-job filter strips BNB from any legacy user row, so stale DB data never reaches the strategy layer.
- `domain.strategy.eligibility.ASSET_ALIASES` deliberately untouched → market_data continues observing BNB markets for the 30-day stats collection.
- No migration required — the `selected_assets` JSONB array re-normalises naturally on the next preset re-activation.

## 5. Known issues

- Tests cannot run in this remote container (no `fastapi / structlog` in the local env); CI is the authoritative runner. Patterns mirror existing asset-hygiene + filter tests so no new test infrastructure is introduced.
- The 30-day stats collection itself is NOT implemented in this lane — it's the existing market_data observation that already records every candle that matches an `ASSET_ALIASES` ticker. The operator will read fill-rate / edge / spread stats from existing logs when deciding whether to re-enable BNB.

## 6. What is next

- 30-day soak: continue observing BNB candles in market_data; tally `complete_set_edge` distributions + spread / liquidity stats. Re-enable only if median edge >= 50 bps AND median spread <= 0.02 (mirrors the existing per-leg thresholds).
- Lane D (architectural, biggest delta from current pipeline) — inventory tracker + dual-leg fast top-up (directive §5 + #8). Will need `MarketInventory` per-market UP/DOWN tracking, the `positions` table is currently single-side.
- Live-mode lane — active order cancellation half of circuit-breaker (directive #6); migration to live API surface.

---

**Validation Tier**: STANDARD
**Claim Level**: NARROW INTEGRATION
**Validation Target**: tradable-asset universe (router + frontend), defensive scan-job filter, source pin on `_build_user_context`.
**Not in Scope**: 30-day stats collection (uses existing market_data telemetry), market_data observation pipeline (untouched), `ASSET_ALIASES` market-text matching (untouched so BNB stays observable).
**Suggested Next Step**: WARP🔹CMD review + merge → Fly.io auto-deploy → operator monitors next 30 days of BNB market stats from existing logs before considering re-enable.
