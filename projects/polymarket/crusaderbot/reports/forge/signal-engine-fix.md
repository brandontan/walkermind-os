# WARP•FORGE Report — signal-engine-fix

**Branch:** WARP/CRUSADERBOT-SIGNAL-ENGINE-FIX
**Date:** 2026-05-17
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Demo path edge_finder signal generation + idempotency key dedup
**Not in Scope:** CLOB/live execution, new strategy algorithms, WebTrader UI changes, risk cap hardening, activation guard changes

---

## 1. What Was Built

Fixed three root causes causing the signal engine to publish 0 signals:

**RC-1 — Signal condition replaced (demo path)**
The original condition `yes_p < 0.15 OR no_p < 0.15` only triggered for markets priced below 15 cents. Most active Polymarket markets trade at 0.30–0.70 — neither condition ever fired. Replaced with continuous edge scoring:
- `edge = abs(yes_p - 0.5)` — deviation from fair-value baseline
- `edge_bps = int(edge * 10_000)` — basis points
- Approved if `edge_bps >= SCANNER_MIN_EDGE_BPS` (default 200 = 2%)
- Side: `YES` if yes_p < 0.5 (underpriced YES), `NO` if yes_p > 0.5 (underpriced NO)
- Price eligibility range: `0.05 <= yes_p <= 0.95` (excludes near-resolved markets)

**RC-2 — Scanner discovery liquidity floor lowered**
`SCANNER_MIN_LIQUIDITY` defaulted to 5,000 USDC (discovery) vs the execution floor of 10,000 USDC. This doubles the market pool. The execution risk gate still enforces the 10k floor before any trade is opened. Both are now env-configurable.

**RC-3 — Idempotency key date-scoped**
`_build_idempotency_key()` previously hashed `(user, market, side, publication_id)`. Each publication for the same market created a distinct key — across the 30-min TTL window, multiple publications caused multiple open positions. Fixed to hash `(user, market, side, date.today())`: same calendar day, same market, same side → same key regardless of publication_id.

**Added: per-market structured logging**
Every scan cycle now logs:
```
signal_scan_cycle_start  scanning=N
signal_scan_market  market_id=... yes_price=... edge_bps=... liquidity=... result=APPROVED/REJECTED reason=...
signal_scan_cycle_end  approved=N rejected=M errors=K published=P
```

**Live path: deviation threshold configurable**
`SCANNER_EDGE_DEVIATION_PCT` (default 0.05, was hardcoded 0.08) now read from config at runtime.

---

## 2. Current System Architecture

```
market_signal_scanner.py (60s tick)
    ↓ run_job()
    ├── Demo path (DEMO_FEED_ID)
    │   └── polymarket.get_markets(limit=200) — active=true&closed=false
    │       ├── filter: liquidity >= SCANNER_MIN_LIQUIDITY (5k)
    │       ├── filter: SCANNER_EDGE_MIN_PRICE <= yes_p <= SCANNER_EDGE_MAX_PRICE
    │       ├── edge = abs(yes_p - 0.5); edge_bps = int(edge * 10_000)
    │       ├── approved if edge_bps >= SCANNER_MIN_EDGE_BPS (200)
    │       └── publish to signal_publications (is_demo=TRUE)
    └── Live path (LIVE_FEED_ID)
        └── Heisenberg agents (candles/liquidity/social) → _check_edge_finder()
            └── deviation_pct now from SCANNER_EDGE_DEVIATION_PCT (0.05)

signal_scan_job.py (180s tick)
    ↓ run_once()
    └── SignalFollowingStrategy.scan() → evaluate_publications_for_user()
        → per candidate:
          1a. execution_queue dedup (UNIQUE user+publication_id)
          1b. open-position market dedup → log "duplicate skipped"
          2.  TradeEngine.execute() → risk gate (13 steps)
          3.  paper fill via paper.py (ON CONFLICT idempotency_key DO NOTHING)
              key = sf:{sha256(user:market:side:date.today())[:32]}
```

---

## 3. Files Created / Modified

| Action | File |
|--------|------|
| Modified | `projects/polymarket/crusaderbot/config.py` |
| Modified | `projects/polymarket/crusaderbot/jobs/market_signal_scanner.py` |
| Modified | `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` |
| Modified | `projects/polymarket/crusaderbot/tests/test_market_signal_scanner.py` |
| Modified | `projects/polymarket/crusaderbot/tests/test_signal_scan_job.py` |
| Created  | `projects/polymarket/crusaderbot/reports/forge/signal-engine-fix.md` |

New env vars in `config.py`:
- `SCANNER_EDGE_MIN_PRICE` (default 0.05)
- `SCANNER_EDGE_MAX_PRICE` (default 0.95)
- `SCANNER_MIN_EDGE_BPS` (default 200)
- `SCANNER_MIN_CONFIDENCE` (default 0.55)
- `SCANNER_EDGE_DEVIATION_PCT` (default 0.05)
- `SCANNER_MIN_LIQUIDITY` (default 5_000.0)

---

## 4. What Is Working

- **11/11 scanner tests pass** — new tests cover mid-price approval, near-resolved rejection, insufficient-edge rejection, side determination (YES/NO), and edge_bps payload field.
- **26/26 signal scan job tests pass** — updated idempotency key test asserts new invariant (same market+day+side = same key regardless of publication_id).
- **Ruff lint clean** on all modified Python files.
- **Backward compat preserved**: `EDGE_PRICE_THRESHOLD` and `MIN_LIQUIDITY` module-level constants retained for existing test mocks.

---

## 5. Known Issues

- **RF-1**: Existing `sf:` keys in `idempotency_keys` table become stale after the key format change. Self-resolves within 30-min TTL. Paper mode only — no capital at risk.
- **RF-2**: `p_fair = 0.5` is a baseline approximation. Adjust `SCANNER_MIN_EDGE_BPS` via env var to change signal aggressiveness without code change.
- **[DEFERRED from KNOWN ISSUES]**: No `asyncio.timeout` on `polymarket.get_markets()` call — scanner stall risk on hung HTTP. P2, not in scope for this fix.

---

## 6. What Is Next

- WARP🔹CMD review and merge decision.
- Monitor first scan cycle after deploy: `signal_scan_cycle_end` log should show `approved > 0` and `published > 0`.
- Verify Signals counter in WebTrader increments after first approved cycle.
- Optionally: tune `SCANNER_MIN_EDGE_BPS` via fly secret if too many/few signals generated.
- Optionally: raise `SCANNER_MIN_LIQUIDITY` if noise from low-liquidity markets is observed.

---

**Suggested Next Step:** WARP🔹CMD review → merge → monitor first scan cycle log for `approved > 0`.
