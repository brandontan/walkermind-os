# Forge Report — WARP/R00T/safe-close-direction-limit

**Date:** 2026-05-30 16:31 Asia/Jakarta
**Role:** WARP•R00T
**Branch:** WARP/R00T/safe-close-direction-limit
**Lane:** 4 of 5 (Polybot directive — defensive guardrails campaign)
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** _process_candidate gates safe_close entries against per-(user, side) rolling 1h count; records on accepted non-duplicate entries
**Not in Scope:** close_sweep / flip_hunter / signal_following / copy_trade (no-op); cross-user aggregate caps; persistent storage of the window
**Suggested Next:** WARP🔹CMD review → merge → proceed to Lane 5 (`WARP/R00T/bankroll-dynamic-sizing`)

---

## 1. What was built

Per-user, per-side rolling 1h counter for accepted `safe_close` entries with a hard cap. When a user has hit `config.SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR` entries on a given side within the last hour, the next entry on that same side is rejected with `outcome="skipped_safe_close_direction_concentration"`. Entries on the opposite side, other presets, and other users are unaffected.

**Why:** `late_entry_v3` chooses side dynamically per scan (`fav_side = "YES" if yes_ask > no_ask else "NO"`), so there is no per-candle bias. But in a trending market — Polybot research caught the BTC downtrend Dec 14-18 2025 producing a 55.9% NO win-rate that *looked* like edge — the same side ends up favoured candle after candle, aggregating directional risk that the per-candle filter never sees. This gate caps that aggregate without re-introducing any per-candle bias.

**No change to:**
- `late_entry_v3` scan logic (still emits per-candle fav-side candidates)
- Risk gate (engine still runs all 13+ steps before any fill)
- Other presets — `close_sweep`, `flip_hunter`, `signal_following`, `copy_trade` bypass cleanly
- Per-user kill switch, multi-tenant isolation, paper-default invariant
- Lane 1/2/3 gates — they compose ahead of this one in `_process_candidate`

**Operator escape hatch:** `SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR=0` disables without redeploy (runtime branches on `> 0`). Negative values rejected at config load with `ValidationError`.

---

## 2. Current system architecture (relevant slice)

```text
services.signal_scan.signal_scan_job (module level)
    ├─ NEW: _SAFE_CLOSE_DIRECTION_WINDOW_SEC = 3600
    ├─ NEW: _safe_close_direction_log: dict[(user_id, side), list[timestamp]]
    ├─ NEW: _safe_close_recent_count(user, side, now) → prune in-place + return len
    ├─ NEW: _safe_close_record_entry(user, side, now) → append timestamp
    └─ NEW: _safe_close_reset_for_tests() → clear (test isolation hook)

services.signal_scan.signal_scan_job._process_candidate
    ├─ step 3a:  dedup / open-position / liquidity gates
    ├─ step 3b:  resolve _live_fill_price + Lane 1 (TOB freshness) + sub-cent
    ├─ step 3c:  fill-time price-band re-check
    ├─ NEW step 3d: safe-close direction concentration
    │       ├─ scoped: only when row["active_preset"] == "safe_close"
    │       ├─ reads config.SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR
    │       ├─ if limit > 0 AND recent_count >= limit:
    │       │       outcome="skipped_safe_close_direction_concentration"
    │       │       telemetry.record_skip(...)
    │       │       return
    │       └─ else: pass through
    ├─ step 4:  _build_trade_signal + engine.execute (risk gate inside engine)
    └─ step 5:  on accepted non-duplicate result, record entry for safe_close
                via _safe_close_record_entry
```

**State lifecycle:**
- Window is in-process memory (dict keyed on `(user_id, side.upper())`).
- Eviction is O(n_entries_for_key) on each read — n is small (≤ a few dozen).
- A crash drops the counter — worst case: one extra entry on restart before the user accumulates back to the limit. Much smaller failure mode than a DB hit on every scan tick (15s cadence × many users × multiple candidates).

---

## 3. Files created / modified (full repo-root paths)

| Action | File | Lines | Purpose |
|---|---|---|---|
| Modified | `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` | +85 | Module-level window state + 3 helpers (count / record / reset), step 3d gate inside `_process_candidate`, record call inside the accept branch |
| Modified | `projects/polymarket/crusaderbot/config.py` | +30 | `SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR: int = 8` knob + `validate_safe_close_direction_limit` field_validator (negative rejection) |
| Created | `projects/polymarket/crusaderbot/tests/test_safe_close_direction_limit.py` | +346 | 16 hermetic tests — window helpers (count / record / case / prune / boundary), config knob (default / env / disable / negative), 7 behavioural integration tests |
| Created | `projects/polymarket/crusaderbot/reports/forge/safe-close-direction-limit.md` | this report | WARP•R00T evidence trail |

---

## 4. What is working

**Verified locally:**
- `python -m py_compile` clean on both modified production files.
- `pytest projects/polymarket/crusaderbot/tests/test_safe_close_direction_limit.py` — **16/16 pass** (0.62s).
- Lane 1 + Lane 2 + Lane 3 + Lane 4 + neighbor regression — **204/204 pass** (2.66s).
- Coverage:
  - Window helpers: empty count = 0, record + count = 1, case-insensitive side normalization, 90-min-old entries evicted, exact 1h boundary kept.
  - Config knob: default 8, env override accepted, disable sentinel 0, negative rejected with `ValidationError` carrying field name.
  - Gate behaviour: blocks at limit, allows under limit, per-side isolation (YES limit doesn't block NO), bypasses non-safe_close presets (close_sweep + flip_hunter explicitly), disable sentinel passes at any count.
  - Record path: accepted non-duplicate increments counter; duplicate results do NOT increment (no broker exposure → no concentration).

**Behaviour in production (expected):**
- Light users (a few entries/hour): zero behavioural change — counter never approaches 8.
- Trending-market users (8+ same-side entries/hour): subsequent entries on the saturated side surface as `skipped_safe_close_direction_concentration` in scan_outcome logs. Operator gains visibility into directional concentration AND the system stops auto-deploying capital into the trend.
- Other presets: zero behavioural change.

---

## 5. Known issues

- **In-memory state.** Fly restart / scheduler restart resets the window. The first 8 entries after restart bypass the gate even if the user was at-cap before. Acceptable: 8 entries × ~$10-$50 size = bounded extra exposure; alternative (DB-backed window) adds per-scan-tick DB load to every safe_close user. Future lane can promote to Redis-backed if production data shows the soft-reset is meaningful.
- **No alert on cap hit.** The gate logs `scan_outcome=skipped_safe_close_direction_concentration` at INFO; operator must dashboard for the count. A future small lane could pipe this to the existing Telegram alert system if Mr. Walker wants explicit notifications.
- **Window is hard-coded 1h.** Not config-tunable; if production data suggests 30m or 2h is better, that's a one-line follow-up.

---

## 6. What is next

Per WARP🔹CMD-approved 5-lane plan:

| # | Lane | Tier | Status |
|---|---|---|---|
| 1 | `WARP/R00T/tob-freshness-gate` | MAJOR-NARROW | ✅ MERGED #1475 + DEPLOYED |
| 2 | `WARP/R00T/close-sweep-spread-gate` | STANDARD-NARROW | ✅ MERGED #1476 + DEPLOYED |
| 3 | `WARP/R00T/complete-set-edge-metric` | MINOR-FOUNDATION | ✅ MERGED #1477 + DEPLOYED |
| 4 | `WARP/R00T/safe-close-direction-limit` | STANDARD-NARROW | **THIS PR** — pending review |
| 5 | `WARP/R00T/bankroll-dynamic-sizing` | MAJOR-NARROW | queued |

---

## Validation declaration

```text
Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : _process_candidate step 3d safe_close direction gate + module-level window helpers + record on accepted non-duplicate + SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR config knob
Not in Scope      : close_sweep / flip_hunter / signal_following / copy_trade (no-op); cross-user aggregate caps; persistent storage
Suggested Next    : WARP🔹CMD review
```
