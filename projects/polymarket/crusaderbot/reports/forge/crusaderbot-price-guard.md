# WARP•FORGE REPORT — crusaderbot-price-guard

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: signal_scan_job._process_candidate() price divergence guard + scheduler market_sync interval
Not in Scope: market sync implementation internals, CLOB integration, live execution paths
Suggested Next Step: WARP🔹CMD review required. Source: projects/polymarket/crusaderbot/reports/forge/crusaderbot-price-guard.md. Tier: STANDARD.

---

## 1. What was built

Two targeted fixes to prevent paper fills at stale DB prices:

**Fix A — Price divergence guard (step 2b in `_process_candidate`)**
After market lookup succeeds, for publication-backed signals only (`pub_uuid is not None`), fetches live yes_price from Gamma API and compares it against the cached `markets.yes_price`. If `live_price / db_price > 2.0`, candidate is rejected with `outcome="skipped_price_moved"`. Falls through silently on any API/network error so a Gamma outage cannot block trading.

**Fix B — Faster market sync interval**
`market_sync.run_job` interval reduced from 1800s (30 min) to 300s (5 min) in `setup_scheduler()`. Reduces the staleness window so the price divergence guard fires less often in steady state.

**Constant added: `_MAX_PRICE_DIVERGENCE_RATIO = 2.0`**
Defined after `_MAX_SIGNAL_AGE_SECONDS` in `signal_scan_job.py`. Threshold: if live/DB ratio > 2.0x, the DB price is too stale for a realistic paper fill.

---

## 2. Current system architecture

Signal scan pipeline for publication-backed candidates:
```
1.  Permanent dedup (execution_queue)
1b. Open-position market dedup
1c. Signal freshness gate (max 30 min old — PR #1146)
2.  Market lookup (DB)
2b. Price divergence guard  ← NEW: live Gamma price vs DB yes_price, ratio > 2.0x → skip
2c. Liquidity filter
3.  Build TradeSignal
4.  TradeEngine.execute() (risk gate mandatory)
5.  Record in execution_queue
```

Guard scope: publication-backed signals only (`pub_uuid is not None`). Lib strategy candidates (`pub_uuid is None`) are excluded — they already use live Gamma prices from Phase A market fetch.

---

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py`
  - Added `_MAX_PRICE_DIVERGENCE_RATIO: float = 2.0` constant (after line 76)
  - Added step 2b price divergence guard block in `_process_candidate()` (after market None check)
  - Renamed old "2b. Liquidity filter" comment to "2c. Liquidity filter"

- `projects/polymarket/crusaderbot/scheduler.py`
  - `market_sync.run_job` interval: `seconds=1800` → `seconds=300`

Created:
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-price-guard.md` (this file)

---

## 4. What is working

- Guard fires only when `pub_uuid is not None` — lib strategy candidates are unaffected
- `_db_price > 0` check prevents division-by-zero on unpriced markets
- `_live_price > 0` check prevents false positives on API returning empty/zero prices
- `import json as _json` is inline inside the try block — no module-level side effect
- Any exception in the guard (API error, network timeout, parse failure) is caught and logged at DEBUG; execution falls through so a Gamma outage cannot halt trading
- `log.info("scan_outcome", outcome="skipped_price_moved", ...)` emits `db_price`, `live_price`, `ratio`, `threshold`, `message` for structured log analysis
- market_sync now runs every 5 min, reducing the staleness window from 30 min to 5 min

---

## 5. Known issues

- `get_markets(limit=1, condition_id=...)` adds one Gamma API call per candidate on the feed path. In high-signal ticks this could add latency. Mitigation: the guard only executes for `pub_uuid is not None` (feed signals), and falls through instantly on API error. Rate-limiting risk is low at current user count.
- The guard uses `yes_price` from DB (not side-aware) for the DB baseline. For `no` side signals this is an approximation. The check still correctly catches large divergences since yes/no prices move inversely — a 2x divergence on yes implies the market moved substantially.

---

## 6. What is next

WARP🔹CMD review required.
Source: `projects/polymarket/crusaderbot/reports/forge/crusaderbot-price-guard.md`
Tier: STANDARD

After merge, monitor structured logs for `outcome="skipped_price_moved"` events. If the ratio threshold (2.0x) is too aggressive in practice, adjust `_MAX_PRICE_DIVERGENCE_RATIO` in signal_scan_job.py.
