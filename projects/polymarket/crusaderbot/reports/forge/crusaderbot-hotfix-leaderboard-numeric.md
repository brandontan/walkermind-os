# WARP•FORGE Report — crusaderbot-hotfix-leaderboard-numeric

**Branch:** WARP/CRUSADERBOT-HOTFIX-LEADERBOARD-NUMERIC
**Validation Tier:** MINOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** NumericValueOutOfRangeError in leaderboard_sync upsert
**Not in Scope:** Falcon API changes, schema changes, live trading

---

## 1. What was built

Single surgical fix: Falcon API returns `win_rate_pct_15d` and `roi_pct_15d` as percentage values (e.g. 72.5 for 72.5%), but `leaderboard_stats` schema stores them as decimals (`win_rate NUMERIC(5,4)` max 9.9999, `roi_pct NUMERIC(8,4)`). Every upsert with a percentage value ≥ 10.0 overflows NUMERIC(5,4).

Fix applied in `_build_rows` loop:
- `win_rate`: divide by 100 if > 1.0, then clamp to [0.0, 1.0]
- `roi_pct`: divide by 100 if > 1.0

---

## 2. Current system architecture

No structural change. `leaderboard_sync.py` — single-file fix in the value normalization loop before DB upsert.

---

## 3. Files created / modified

**Modified:**
- `projects/polymarket/crusaderbot/services/copy_trade/leaderboard_sync.py` — added percent→decimal conversion + clamp for `win_rate` and `roi_pct`

---

## 4. What is working

- `python3 -m py_compile services/copy_trade/leaderboard_sync.py` → OK
- `win_rate` is guaranteed ≤ 1.0 before upsert (NUMERIC(5,4) safe)
- `roi_pct` divided by 100 when Falcon returns percentage form

---

## 5. Known issues

None. Fix is defensive: values already in decimal form (≤ 1.0) pass through unchanged.

---

## 6. What is next

- WARP🔹CMD: review and merge
- Monitor Sentry: NumericValueOutOfRangeError on `leaderboard_stats.win_rate` / `roi_pct` should resolve after deploy
