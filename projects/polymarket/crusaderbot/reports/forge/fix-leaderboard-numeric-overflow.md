# WARP•FORGE REPORT — fix-leaderboard-numeric-overflow

**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** leaderboard_sync.py numeric overflow guard
**Not in Scope:** leaderboard_stats schema migration, other services
**Suggested Next Step:** WARP🔹CMD review → merge

---

## 1. What was built

Fixed `NumericValueOutOfRangeError` in `services/copy_trade/leaderboard_sync.py` — two-layer defence:

**Layer 1 — `_safe_float` NaN/infinity filter:**
`_safe_float` now calls `math.isfinite(f)` before returning. Any non-finite value (NaN from `"NaN"` strings, Infinity from `"Infinity"` strings) is converted to `None` instead of being passed to asyncpg. Previously NaN bypassed `max()`/`min()` clamps entirely.

**Layer 2 — `_clamp` helper:**
Extracted the repeated `max(-X, min(X, val))` pattern into a reusable `_clamp(val, lo, hi)` that is None-safe and reads clearly against the column bounds. Schema bounds enforced:
- `roi_pct` → `NUMERIC(8,4)` → `[-9999.9999, 9999.9999]`
- `total_pnl` → `NUMERIC(18,6)` → `[-999999999999, 999999999999]`
- `volume_usdc` → `NUMERIC(18,6)` → `[0, 999999999999]`

---

## 2. Current system architecture

Unchanged. `leaderboard_sync.run_job` → `sync_leaderboard(pool)` → Falcon API → DB upsert. The fix is in the data-transformation stage before the DB write.

---

## 3. Files created / modified

- `projects/polymarket/crusaderbot/services/copy_trade/leaderboard_sync.py` — added `import math`, `_safe_float` isfinite guard, `_clamp` helper, replaced manual clamp block

---

## 4. What is working

- NaN values from Falcon API are now converted to `None` before DB insert
- Infinity values were already clamped by `min`/`max` but `_safe_float` now rejects them earlier
- Large finite values are still clamped to column bounds
- Warning log fires when any value was clamped or filtered
- compileall: clean

---

## 5. Known issues

None. Column widening (migration option) is not required — current `NUMERIC(18,6)` handles legitimate PnL/volume values. The root cause was NaN propagation through `min`/`max`.

---

## 6. What is next

WARP🔹CMD review required. Tier: STANDARD.
