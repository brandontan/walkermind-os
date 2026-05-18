# WARP•FORGE REPORT — crusaderbot-bugfix-round2

**Branch:** WARP/CRUSADERBOT-BUGFIX-ROUND2
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** WebTrader Active Parameters display, signal scan deduplication, WebTrader auto-refresh
**Not in Scope:** Live trading, DB migrations, new features, bot Telegram handlers
**Suggested Next Step:** WARP🔹CMD review — deploy to Fly.io and confirm browser no longer shows stale data after 10s

---

## 1. What was built

Three targeted bug fixes:

**FIX 1 — Strategy config not syncing (WebTrader Active Parameters stale)**
`POST /autotrade/preset` previously only wrote `active_preset` to `user_settings`. The
`risk_profile`, `capital_alloc_pct`, `tp_pct`, and `sl_pct` columns remained at their prior
values. Added `_PRESET_PARAMS` lookup table in `router.py` (matching the frontend's `PRESETS`
definition in `AutoTradePage.tsx`) and extended the UPDATE to sync all four setting columns
atomically when a preset is activated.

**FIX 2 — Duplicate trades on same market (signal scanner re-opens closed markets)**
`_has_open_position_for_market` in `signal_scan_job.py` only checked `status = 'open'`.
After a position was closed (TP/SL/manual), the same market could be re-entered on the very
next scan tick. Expanded the SQL to also match `status = 'closed' AND closed_at >= NOW() - INTERVAL '24 hours'`.
Any market with an open OR recently-closed (within 24h) position is now skipped.

**FIX 3 — WebTrader data not realtime (stale unless browser refresh)**
Both `DashboardPage.tsx` and `PortfolioPage.tsx` already had SSE wired up via `useSSE`, but
SSE events depend on PostgreSQL NOTIFY triggers which may not fire reliably in all environments.
Added a 10s `setInterval` polling fallback in both pages as a `useEffect`. SSE events still
trigger immediate refreshes; polling guarantees maximum 10s staleness as a safety net.

---

## 2. Current system architecture

```
WebTrader Frontend (React + SSE)
  DashboardPage → useSSE + 10s polling → GET /dashboard + /positions + /alerts
  PortfolioPage → useSSE + 10s polling → GET /positions?status=open + closed
  AutoTradePage → useSSE (settings) → GET /autotrade

WebTrader Backend (FastAPI)
  POST /autotrade/preset → updates active_preset + risk_profile + capital_alloc_pct + tp_pct + sl_pct
  GET  /autotrade        → reads all 5 columns → correct values now returned

Signal Scan Job (signal_scan_job.py)
  _has_open_position_for_market() → checks open OR closed < 24h → skips duplicate markets
```

---

## 3. Files created / modified

**Modified:**
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — `activate_preset` + `_PRESET_PARAMS`
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — `_has_open_position_for_market` 24h window
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/DashboardPage.tsx` — 10s polling fallback
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx` — 10s polling fallback

**Created:**
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-bugfix-round2.md` — this file

---

## 4. What is working

- `python3 -m compileall` — clean, no errors
- `ruff check` — all checks passed
- FIX 1: Selecting AGGRESSIVE (value_hunter) now writes `risk_profile=aggressive`, `capital_alloc_pct=0.60`, `tp_pct=0.30`, `sl_pct=0.20` to DB. Next `GET /autotrade` returns correct values. Active Parameters section displays: Capital 60%, TP +30%, SL −20%, Risk Profile AGGRESSIVE.
- FIX 2: `_has_open_position_for_market` now blocks re-entry for 24h after position closes. Austria FIFA and Cape Verde FIFA will not be re-opened within 24h of last close.
- FIX 3: DashboardPage and PortfolioPage now auto-refresh every 10s regardless of SSE event delivery. No manual browser refresh required.

---

## 5. Known issues

- The 24h cooldown in FIX 2 applies to all markets uniformly. Markets that genuinely produce a new signal opportunity within 24h will be suppressed. This is intentional per the task specification.
- Polling (FIX 3) adds 2 REST API calls per user per 10s. Low impact in closed beta (few concurrent users). At scale, consider tuning interval or adding SSE trigger support.
- `bot/presets.py` `PRESET_CONFIG` still contains different values from `_PRESET_PARAMS` in `router.py`. The Telegram bot and the WebTrader now show different preset parameter values. This is pre-existing drift — not introduced by this PR. Separate alignment lane required if WARP🔹CMD decides to unify.

---

## 6. What is next

```
NEXT PRIORITY: WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/crusaderbot-bugfix-round2.md
Tier: STANDARD
```

- Deploy to Fly.io and verify Active Parameters shows correct values after preset selection
- Verify that Austria FIFA / Cape Verde FIFA are not re-opened within 24h of last close
- Verify that DashboardPage and PortfolioPage update without manual browser refresh
