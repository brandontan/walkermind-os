# WARP•R00T FORGE REPORT — tpsl-from-risk-profile (PR 1/3 of close_sweep Kreo-parity)

Branch: `WARP/ROOT/tpsl-from-risk-profile`
Role: WARP•R00T
Validation Tier: MAJOR (touches TP/SL — capital safety)
Claim Level: NARROW INTEGRATION

## 1. What was built
DEFECT 1 fix: TP/SL now come from the user's RISK PROFILE, not the activated
preset (Kreo parity: "auto TP/SL = user risk profile"). Plus Custom Risk now
allows TP-only OR SL-only.

- New canonical source `domain/risk/constants.py::tp_sl_for_profile()` +
  `PROFILE_TP_SL` (conservative 10/5, balanced 20/15, aggressive 30/20).
- WebTrader preset activation (`router.activate_preset`) resolves TP/SL from the
  preset's risk_profile via `tp_sl_for_profile`, no longer from `_PRESET_PARAMS`
  preset tp/sl (close_sweep was 0.90/0.40 → now balanced 0.20/0.15).
- Telegram `_activate_preset` reads the user's current risk_profile and sets
  TP/SL from `tp_sl_for_profile` (not the preset cfg's 90/40).
- New-user bootstrap (`users.py`) default flipped aggressive 90/40 → balanced 20/15.
- Custom Risk: backend `set_risk_profile` requires capital + at least one of
  tp/sl; enforces tp>sl only when both set; null tp or null sl persists as NULL.
  Frontend `AutoTradePage` custom form: TP/SL inputs optional (blank = disabled),
  "at least one required" validation. Exit watcher already no-ops the unset side.

## 2. Architecture
`tp_sl_for_profile` (constants.py) is the single source of truth. Standard
profiles + preset activation route through it. Custom = user-supplied (TP-only /
SL-only supported; exit_watcher guards each side with `is not None`).

## 3. Files modified
- domain/risk/constants.py (PROFILE_TP_SL + tp_sl_for_profile)
- webtrader/backend/router.py (activate_preset TP/SL from profile; set_risk_profile custom TP/SL-only)
- bot/handlers/autotrade.py (_activate_preset TP/SL from profile)
- users.py (new-user default balanced 20/15)
- webtrader/frontend/src/pages/AutoTradePage.tsx (custom form TP/SL optional)
- tests/test_tpsl_from_profile.py (9 tests, new)

## 4. What is working
TP/SL follow risk profile; custom TP-only/SL-only saves + validates; new users
default balanced. 9 new tests; full suite 2040 pass; ruff + py_compile + tsc +
vite clean.

## 5. Known issues
None. Open positions unaffected (immutable snapshot). PR 2 (fast-exit 299s) and
PR 3 (min-edge) follow.

## 6. What is next
PR 2: dedicated ~5s fast exit loop + close_sweep force-exit at rem≈8s.
