# close-sweep-dual-leg-spread-guard

**Role:** WARP•R00T
**Tier:** STANDARD (runtime behaviour change — close_sweep top-up spread gate)
**Claim Level:** NARROW INTEGRATION
**Validation Target:** `_maybe_fire_fast_topup` spread-check for `close_sweep` preset; closes finding M-2 from `pre-flip-integrity-sweep`
**Not in Scope:** M-1 (tick guard — separate merged lane); safe_close / flip_hunter top-up paths (spread gate scoped to close_sweep only)

---

## 1. What was built

Closes M-2 from the pre-flip integrity sweep: `_maybe_fire_fast_topup` for the `close_sweep` preset bypassed `CLOSE_SWEEP_MAX_LEG_SPREAD`. The close-sweep-spread-gate lane wired the spread guard into `late_entry_v3._evaluate_market` on the lead scan path only; `_maybe_fire_fast_topup` is preset-agnostic and deliberately skips every `_process_candidate` guard, so a wide-spread thin-book final-35s top-up could fire.

**Fix (52 lines inside `_maybe_fire_fast_topup`):** After the top-up price is resolved and before the TradeSignal is built, when `preset == "close_sweep"`:

1. Read `CLOSE_SWEEP_MAX_LEG_SPREAD` from config via `getattr(_cfg, ..., 0.02)` (defensive against config drift).
2. Fetch the lagging leg's CLOB book via `_polymarket.get_book(lag_token_id)`.
3. Compute `best_ask` (lowest positive ask) and `best_bid` (highest positive bid).
4. If either is absent → `fast_topup_skipped / reason=leg_spread_missing_bid` → return.
5. If `round(best_ask - best_bid, 4) > max_spread` → `fast_topup_skipped / reason=leg_spread_too_wide` → return.
6. On any exception in the check → `fast_topup_spread_check_failed` warning → return (fail closed).

`safe_close` and `flip_hunter` presets are unaffected — the guard only runs when `preset == "close_sweep"`.

**Test-file update:** `_drive` in `test_close_sweep_dual_leg.py` now mocks `ssj._polymarket.get_book` (default: tight-spread book, spread = 0.01, well under the 0.02 default limit). This prevents the existing 16 tests from reaching the real network in the guard's new code path.

---

## 2. Current system architecture

```text
_maybe_fire_fast_topup gate ordering (post M-2):

config gate           (FLIP_HUNTER / CLOSE_SWEEP flags)
preset scope gate     (eligible presets only)
cooldown gate         (per-user/market)
inventory check       (imbalance >= min_usdc)
side determination    (lagging leg)
size cap              (min(imbalance, lead_size))
price resolution      (live → DB fallback)
NEW: close_sweep spread gate
  → _polymarket.get_book(lagging_token)
  → best_ask - best_bid > CLOSE_SWEEP_MAX_LEG_SPREAD → skipped
  → missing bid → skipped
  → exception → skipped (fail closed)
signal build          (TradeSignal direct)
engine.execute        (13-step risk gate still applies)
cooldown stamp
```

---

## 3. Files created / modified

```text
projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py       (MODIFIED — 52 lines added after price resolution block)
projects/polymarket/crusaderbot/tests/test_close_sweep_dual_leg.py             (MODIFIED — _drive updated + _tight_book helper + 3 new tests)
projects/polymarket/crusaderbot/reports/forge/close-sweep-dual-leg-spread-guard.md  (NEW)
projects/polymarket/crusaderbot/state/PROJECT_STATE.md                           (sections updated)
projects/polymarket/crusaderbot/state/CHANGELOG.md                               (one-line append)
```

---

## 4. What is working

| Check | Result |
|---|---|
| Wide spread → top-up skipped | PASS — `test_close_sweep_topup_wide_spread_skipped` |
| Tight spread → top-up fires | PASS — `test_close_sweep_topup_tight_spread_fires` |
| Missing bid → top-up skipped | PASS — `test_close_sweep_topup_missing_bid_skipped` |
| All 16 prior close-sweep dual-leg tests pass | PASS — 19/19 |
| All 25 prior fast-topup tests pass (safe_close / flip_hunter unaffected) | PASS — 25/25 |
| `ruff check` | PASS |
| `py_compile` | PASS |

Guard posture:
- Only fires for `preset == "close_sweep"` — other presets bypass cleanly
- Fails closed on book-fetch error (`fast_topup_spread_check_failed` log → return)
- Fails closed on missing bid (`leg_spread_missing_bid`) — no-buyer scenario in thin book = correct rejection
- `CLOSE_SWEEP_MAX_LEG_SPREAD=0` disables the gate at runtime (mirrors lead entry path)

---

## 5. Known issues

None introduced. Both M-1 and M-2 findings from the pre-flip integrity sweep are now closed.

**Pre-LIVE hardening status:** COMPLETE — both medium findings resolved. All four flag-gated lanes (`BANKROLL_CIRCUIT_BREAKER_ENABLED`, `SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED`, `FLIP_HUNTER_FAST_TOPUP_ENABLED`, `CLOSE_SWEEP_DUAL_LEG_ENABLED`) are now cleared for LIVE flip once operator validations pass.

---

## 6. What is next

**Immediate:**
- Merge this PR — no operator action needed; spread guard activates automatically when `CLOSE_SWEEP_DUAL_LEG_ENABLED=true` is set in Fly secrets.

**Operator checklist (unchanged from integrity sweep):**
1. `BANKROLL_CIRCUIT_BREAKER_ENABLED=true` — observe 24h
2. `FLIP_HUNTER_FAST_TOPUP_ENABLED=true` — observe (M-1 tick guard now active)
3. `SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED=true`
4. `CLOSE_SWEEP_DUAL_LEG_ENABLED=true` — M-2 spread guard now active; safe for PAPER and for LIVE flip when ready

**No further hardening lanes required** before any of the four knobs flip to LIVE.

**Suggested Next Step:** WARP🔹CMD review. Tier: STANDARD — no WARP•SENTINEL run required.

---

**WARP•R00T self-validated.** 19/19 + 25/25 tests pass. `ruff` + `py_compile` clean.
