# WARP•FORGE — fix-pnl-current-price

Issue: #1182 (WARP-38) — Open positions P&L showing wrong current price
Branch: WARP/fix-pnl-current-price
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: `get_live_market_price()` price-source guard in
`integrations/polymarket.py` — the single source of the live mark used to
compute unrealised P&L for open positions (exit_watcher tick → positions
table → Telegram Portfolio + WebTrader Dashboard/Portfolio).
Not in Scope: TP/SL exit logic, redemption pipeline, position-open path,
WebTrader/Telegram rendering code, market sync job. No DB migration.

---

## 1. What was built

Root-cause fix for inflated open-position P&L (e.g. +927.5% on a
Buffalo Sabres position bought at 5.5¢).

Root cause: `get_live_market_price()` accepted the CLOB `/price`
empty-book sentinel as a valid live mark. Polymarket CLOB
`GET /price?token_id=...&side=buy` returns exactly `1.0` when the ask
side of the book is empty (`0.0` when the bid side is empty) — common on
thin longshot markets. The old guard `0.0 <= clob_price <= 1.0` accepted
that `1.0`, so an open YES position entered at 0.055 was marked at 1.00,
yielding `(1.0 - 0.055) / 0.055` ≈ +1700%-class P&L on an unresolved
market. The Gamma `outcomePrices` fallback had the same weakness
(`0.0 <= price <= 1.0` accepted the settled `1`/`0` values).

Fix: require a strictly-interior price `0.0 < p < 1.0` on both the CLOB
primary path and the Gamma fallback. A degenerate CLOB sentinel now
falls through to the Gamma last-trade price (the real ~0.055 mark); an
all-invalid lookup returns `None`, so callers fall back to `entry_price`
(unrealised P&L == 0 / "N/A") instead of a 1.0-inflated figure — exactly
the acceptance criteria in #1182.

## 2. Current system architecture

```text
exit_watcher.run_once (30s tick)
  └─ get_live_market_price(market_id, side)        ← FIX HERE
       ├─ CLOB /price (primary)  accept iff 0<p<1  ← was 0<=p<=1
       ├─ Gamma outcomePrices (fallback) iff 0<p<1 ← was 0<=p<=1
       └─ None  → caller marks at entry_price (ret 0)
  └─ registry.update_current_price → positions.current_price / pnl_usdc
        ├─ Telegram Portfolio  (bot/handlers/positions.py)
        └─ WebTrader /positions, /portfolio (webtrader/backend/router.py)
```

No behavioural change to any caller — the fix only narrows what counts
as a valid live price. Paper and live paths share `get_live_market_price`
so both are covered by the single change.

## 3. Files created / modified

- Modified: `projects/polymarket/crusaderbot/integrations/polymarket.py`
  (CLOB guard → strict interior + sentinel log; Gamma fallback guard →
  strict interior)
- Created: `projects/polymarket/crusaderbot/tests/test_live_market_price.py`
  (4 regression cases)
- Modified: `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- Modified: `projects/polymarket/crusaderbot/state/CHANGELOG.md`
- Created: `projects/polymarket/crusaderbot/reports/forge/fix-pnl-current-price.md`

## 4. What is working

- `test_live_market_price.py` — 4/4 pass:
  - CLOB `1.0` sentinel → falls back to Gamma `0.055`
  - CLOB `0.0` sentinel → falls back to Gamma `0.055`
  - CLOB interior `0.061` → returned as-is (no behaviour change for real
    prices)
  - CLOB sentinel + Gamma `1`/`0` → `None` (caller marks at entry → P&L
    0 / N/A, never inflated)
- `python -m compileall` clean on the modified module + new test.
- Self-correcting: the next exit_watcher tick (≤30s) recomputes and
  overwrites the bad `positions.pnl_usdc` / `current_price` for every
  affected open position — no data backfill required.

## 5. Known issues

- Full `pytest` suite (e.g. `test_exit_watcher.py`) not runnable in this
  cloud env — `asyncpg`/DB-bound deps absent. The fix is isolated to
  `integrations/polymarket.py` (no asyncpg import); targeted regression
  suite + compileall are green. CI runs the full suite.
- Positions whose `pnl_usdc` was already persisted at the inflated value
  display stale until the next watcher tick refreshes them (≤30s). No
  manual cleanup required.

## 6. What is next

- WARP🔹CMD review required (STANDARD).
- Optional follow-up (separate lane): the CLOB primary uses
  `side=buy` (ask) to mark a held position; a `side=sell`/mid mark would
  value an exit more precisely. Out of scope for #1182.

Suggested Next Step: WARP🔹CMD review + merge to main; redeploy so the
exit_watcher self-heals affected open positions on the next tick.
