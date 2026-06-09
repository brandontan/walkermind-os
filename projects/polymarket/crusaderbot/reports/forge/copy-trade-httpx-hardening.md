# WARP•FORGE Report — copy-trade-httpx-hardening

**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** copy_trade HTTP client consistency + scanner stall protection
**Not in Scope:** structlog migration, live execution paths, WebTrader, Telegram handlers
**Suggested Next Step:** WARP🔹CMD review → merge → Fly.io redeploy

---

## 1. What Was Built

**M-1 — aiohttp → httpx migration (copy_trade services)**

Removed `aiohttp` from the three copy_trade HTTP service files and replaced with `httpx.AsyncClient`, bringing them in line with the rest of the codebase (all other HTTP calls already use httpx).

**M-2 — Scanner stall protection**

Wrapped `polymarket.get_markets()` in `jobs/market_signal_scanner.py` with `asyncio.timeout(30)` to prevent the scanner loop from stalling indefinitely on a slow Gamma API response. A `TimeoutError` now logs `polymarket_fetch_timeout` and falls through to `markets = []` — same recovery path as other network errors.

---

## 2. Current System Architecture

HTTP client layer is now fully unified:
- All external HTTP calls use `httpx.AsyncClient` with explicit `httpx.Timeout`
- Exception hierarchy: `(httpx.HTTPError, httpx.TimeoutException)` in retry loops
- Retry + backoff pattern preserved in `wallet_stats.py` (3 retries, 1s/2s/4s)
- `aiohttp` dependency removed from `pyproject.toml`

Scanner loop:
- `market_signal_scanner.run_job` → `asyncio.timeout(30)` guard around `get_markets`
- Timeout produces warning log `polymarket_fetch_timeout`, sets `markets = []`
- No stall risk on hung Gamma API TCP connection

---

## 3. Files Created / Modified

| Path | Change |
|---|---|
| `projects/polymarket/crusaderbot/services/copy_trade/wallet_stats.py` | aiohttp → httpx; `ClientTimeout` → `httpx.Timeout`; session pattern → `AsyncClient` |
| `projects/polymarket/crusaderbot/services/copy_trade/wallet_360.py` | aiohttp → httpx; same pattern |
| `projects/polymarket/crusaderbot/services/copy_trade/leaderboard_sync.py` | aiohttp → httpx; `await resp.text()` → `resp.text` (sync) |
| `projects/polymarket/crusaderbot/jobs/market_signal_scanner.py` | add `import asyncio`; wrap `get_markets` in `asyncio.timeout(30)` |
| `projects/polymarket/crusaderbot/pyproject.toml` | remove `"aiohttp>=3.9"` dependency |
| `projects/polymarket/crusaderbot/tests/test_phase5e_copy_trade.py` | replace `import aiohttp` → `import httpx`; rewrite two wallet_stats mock tests to use `httpx.AsyncClient` pattern and `httpx.ConnectError` |

---

## 4. What Is Working

- `ruff check` passes on all 5 modified source files — zero lint errors
- Zero remaining `aiohttp` references in the entire crusaderbot tree (`.py`, `.toml`)
- Mock patch targets updated to `projects.polymarket.crusaderbot.services.copy_trade.wallet_stats.httpx.AsyncClient`
- Test assertions unchanged: `result.available is False`, `mock_client.get.call_count == 4`
- `asyncio` import added to scanner; `asyncio.timeout` is stdlib (Python 3.11+) — no new dependency

---

## 5. Known Issues

None. The `wallet_stats.py` `asyncio` import was already present before this change (used for `asyncio.sleep` in retry backoff).

---

## 6. What Is Next

- WARP🔹CMD review → merge `WARP/ROOT/copy-trade-httpx-hardening`
- Fly.io redeploy to pick up: H3 MarkdownV2 (PR #1386 already merged) + this hardening
- Apply migration 058 (DROP copy_targets, backfill → copy_trade_tasks) to Supabase before deploy
- Post-deploy smoke: verify no `aiohttp` import errors at startup, no `BadRequest: can't parse entities` in Sentry
- WARP•R00T M-3 (deferred): structlog migration for top-8 stdlib logging files — separate lane
