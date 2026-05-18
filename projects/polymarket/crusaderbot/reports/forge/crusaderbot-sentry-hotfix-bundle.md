# WARP•FORGE Report — crusaderbot-sentry-hotfix-bundle

**Branch:** WARP/CRUSADERBOT-SENTRY-HOTFIX-BUNDLE
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** 6 active Sentry production errors (scheduler, keyboards, SQL, slippage, DB pool)
**Not in Scope:** live trading, UI changes, guard changes, migration runner changes

---

## 1. What was built

Six targeted fixes for active Sentry production errors:

- **FIX 1** (-5, 5383 events): `job_runs.metadata` crash — dict passed as str to TEXT column. Serialized with `json.dumps()`.
- **FIX 2** (-12): `preset_picker_kb` ImportError — function renamed `preset_picker_kb → preset_picker` in `bot/keyboards/__init__.py`; all call sites updated.
- **FIX 3** (-1A, -19): `column "market_question" does not exist` — covered by migration 041 (idempotent, adds column to positions if absent).
- **FIX 4** (-Z, -10): `column "strategy_type" does not exist` — `COALESCE(p.strategy_type, 'unknown')` in portfolio analytics query fails when positions lacks the column. Migration 041 adds both columns.
- **FIX 5** (-1M, active): `NumericValueOutOfRange` slippage — backend clamp `min(max(...), 0.9999)` added before INSERT to prevent NUMERIC(5,4) overflow.
- **FIX 6** (-1C, -1D, -1B, active): `TooManyConnections` — `DB_POOL_MAX` reduced from 5 → 4 (Supabase free tier ceiling ~15 connections).

---

## 2. Current system architecture

No structural changes. All fixes are surgical edits to:
- Scheduler listener serialization
- Keyboard function naming
- DB migration (column add)
- WebTrader backend clamp
- Pool size config

---

## 3. Files created / modified

**Modified:**
- `projects/polymarket/crusaderbot/scheduler.py` — FIX 1: added `import json` + `json.dumps(retval)` on line 515
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py` — FIX 2: `def preset_picker_kb()` → `def preset_picker()`
- `projects/polymarket/crusaderbot/bot/handlers/start.py` — FIX 2: import + call updated
- `projects/polymarket/crusaderbot/bot/handlers/autotrade.py` — FIX 2: import + two call sites updated
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — FIX 5: slippage clamp before param append
- `projects/polymarket/crusaderbot/config.py` — FIX 6: `DB_POOL_MAX: int = 5` → `4`

**Created:**
- `projects/polymarket/crusaderbot/migrations/041_positions_strategy_type.sql` — FIX 3+4: `ADD COLUMN IF NOT EXISTS strategy_type VARCHAR(50)` + `ADD COLUMN IF NOT EXISTS market_question TEXT` on positions

---

## 4. What is working

- `python3 -m py_compile scheduler.py` → OK
- `python3 -m py_compile bot/handlers/dashboard.py` → OK
- `python3 -m py_compile bot/handlers/trades.py` → OK
- `python3 -m py_compile bot/keyboards/__init__.py` → OK
- `python3 -m py_compile bot/handlers/autotrade.py` → OK
- `python3 -m py_compile bot/handlers/start.py` → OK
- `grep "preset_picker_kb" . --include="*.py" -r` → 0 results
- `grep "json.dumps(retval)" scheduler.py` → 1 result (line 515)
- Migration 041 is idempotent (`IF NOT EXISTS`); safe to apply at any time

**FIX 3 audit note:** Queries in `bot/handlers/trades.py`, `bot/handlers/share_card.py`, and `bot/handlers/dashboard.py` all use `LEFT JOIN markets m ON m.id = p.market_id` with `m.question AS market_question` — the SQL alias form is correct. The Sentry error is attributed to the `positions` table lacking a `market_question` column when some code path reads `p.market_question` directly (confirmed by migration 034 comment). Migration 041 adds the column idempotently to close the error permanently.

---

## 5. Known issues

- Migration 041 must be applied to production Supabase before the error disappears from Sentry (-Z, -10, -1A, -19). Until applied, the portfolio analytics endpoint (`GET /portfolio/analytics`) will continue to fail for FIX 4.
- FIX 6 pool reduction is temporary — full fix tracked under WARP/ASYNCPG-SUPABASE-FIX.
- `preset_picker()` in `bot/keyboards/__init__.py` (FIX 2 renamed) still uses `p5:preset:` callback data. The `preset_picker()` in `bot/keyboards/presets.py` uses `preset:pick:` callbacks. They are separate functions for separate handler systems — no conflict.

---

## 6. What is next

- WARP🔹CMD: apply migration 041 to production Supabase
- WARP🔹CMD: review and merge this PR
- WARP/ASYNCPG-SUPABASE-FIX: permanent pool size fix (scheduled)

---

**Suggested Next Step:** Apply migration 041 to Supabase, then merge PR. Monitor Sentry for resolution of -5, -12, -1A, -19, -Z, -10, -1M, -1C/-1D/-1B events.
