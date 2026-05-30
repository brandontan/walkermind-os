# fast-topup-tick-guard

**Role:** WARP•R00T
**Validation Tier:** STANDARD (runtime behaviour change — candle-market top-up guard)
**Claim Level:** NARROW INTEGRATION
**Validation Target:** `_maybe_fire_fast_topup` fallback-price path for candle markets (`signal_scan_job.py:892-897`); closes finding M-1 from `pre-flip-integrity-sweep`
**Not in Scope:** live-price path; non-candle markets; M-2 (close-sweep spread guard — separate lane)

---

## 1. What was built

Closes M-1 from the pre-flip integrity sweep: the DB-fallback price path inside `_maybe_fire_fast_topup` lacked the 0.01-tick guard that step 3b-i enforces on the lead entry path.

**Root cause (from audit):** When `get_live_market_price` returns `None` (lagging leg has no CLOB bid at top-up time), the helper falls back to `market.get("yes_price")` / `market.get("no_price")` from the DB row. These are Gamma-synced `outcomePrices` seed values that can be sub-cent (e.g. `0.505`) in early-session candle markets — the same class of stale data fixed by the flip-hunter-stale-price-fix lane on the lead entry path.

**Fix (5 lines inside the fallback block):** After the DB fallback price is resolved, if the market slug contains `"updown"` (candle market) and the price is not on the 0.01 CLOB tick (`abs(price * 100 - round(price * 100)) > 1e-6`), emit `scan_outcome / fast_topup_skipped / reason=stale_fallback_price` and return without firing. Exact mirror of the step 3b-i guard.

**Scope:** fallback branch only (`_topup_price` was `None` or out of `(0, 1)`). Live-price path is unaffected. Non-candle markets (`"updown"` not in slug) are unaffected — thin longshot markets legitimately produce sub-cent prices.

---

## 2. Current system architecture

No architectural change. `_maybe_fire_fast_topup` structure is unchanged:

```text
config gate           (FLIP_HUNTER / CLOSE_SWEEP flags)
preset scope gate     (eligible presets only)
cooldown gate         (per-user/market)
inventory check       (imbalance >= min_usdc)
side determination    (lagging leg)
size cap              (min(imbalance, lead_size))
price resolution:
  try  → get_live_market_price(market_id, side)
  fail → DB fallback (yes_price / no_price)
         ↳ NEW: candle tick guard — skip if "updown" + sub-cent
signal build          (TradeSignal direct, no scan gates)
engine.execute        (13-step risk gate still applies)
cooldown stamp
```

---

## 3. Files created/modified

```text
projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py   (MODIFIED — 14 lines added inside fallback block)
projects/polymarket/crusaderbot/tests/test_flip_hunter_fast_topup.py       (MODIFIED — 3 new tests + _drive market kwarg + _candle_market helper)
projects/polymarket/crusaderbot/reports/forge/fast-topup-tick-guard.md    (NEW)
projects/polymarket/crusaderbot/state/PROJECT_STATE.md                      (sections updated)
projects/polymarket/crusaderbot/state/CHANGELOG.md                          (one-line append)
```

---

## 4. What is working

| Check | Result |
|---|---|
| Guard fires on candle market + sub-cent fallback | PASS — `test_candle_stale_fallback_price_skipped` |
| Guard passes on candle market + tick-aligned fallback | PASS — `test_candle_tick_aligned_fallback_fires` |
| Guard does NOT fire on non-candle market + sub-cent fallback | PASS — `test_non_candle_sub_cent_not_blocked` |
| All 25 prior fast-topup tests still pass | PASS — 28/28 |
| All 16 close-sweep dual-leg tests still pass | PASS — 16/16 |
| `ruff check` | PASS |
| `py_compile` | PASS |

Guard is scoped correctly:
- Only activates when live price was unavailable (fallback path taken)
- Only activates for `"updown"` slug markets
- Returns `fast_topup_skipped` with structured log fields for observability
- Cooldown is NOT stamped on this path (same rationale as the "below threshold" skip — no engine attempt was made)

---

## 5. Known issues

None introduced. M-2 (close_sweep spread gate) remains as the next hardening lane (`WARP/R00T/close-sweep-dual-leg-spread-guard`).

---

## 6. What is next

**Immediate:**
- Merge this PR — no operator action needed; guard activates automatically when `FLIP_HUNTER_FAST_TOPUP_ENABLED=true` or `CLOSE_SWEEP_DUAL_LEG_ENABLED=true` is set in Fly secrets.

**Follow-up hardening (pre-LIVE requirement):**
- `WARP/R00T/close-sweep-dual-leg-spread-guard` — close M-2: per-leg spread check inside `_maybe_fire_fast_topup` for `close_sweep` preset.

**Operator checklist (unchanged from integrity sweep):**
1. `BANKROLL_CIRCUIT_BREAKER_ENABLED=true` — observe 24h
2. `FLIP_HUNTER_FAST_TOPUP_ENABLED=true` — observe; this lane's guard is now active
3. `SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED=true`
4. `CLOSE_SWEEP_DUAL_LEG_ENABLED=true` (PAPER only; harden M-2 before LIVE)

**Suggested Next Step:** WARP🔹CMD review. Tier: STANDARD — no WARP•SENTINEL run required.

---

**WARP•R00T self-validated.** 28/28 tests pass. `ruff` + `py_compile` clean.
