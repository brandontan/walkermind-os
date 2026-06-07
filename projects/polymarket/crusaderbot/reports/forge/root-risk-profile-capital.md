# WARP•R00T FORGE REPORT — root-risk-profile-capital

Branch: `WARP/root-risk-profile-capital`
Role: WARP•R00T (owner directive 2026-06-08 — "pastikan risk profil setting berfungsi")
Validation Tier: **MAJOR** (capital sizing + risk gate core)
Claim Level: NARROW INTEGRATION
Validation Target: The risk-profile capital % (Conservative 20 / Balanced 40 / Aggressive 60 / Custom) actually governs (a) per-trade size and (b) total capital deployment.
Not in Scope: enabling live trading; `ENABLE_LIVE_TRADING`; TP/SL semantics (uniform 150/50, unchanged); Kelly fraction (0.25, unchanged).
Suggested Next Step: merged by WARP•R00T → Fly CD deploy (runs migration 090).

---

## 1. What was built

Owner + a user (Vitalix) observed the risk profiles were "all same, just different
cap%". Investigation proved the cap% itself did **nothing**:

ROOT CAUSE (two disconnects):
1. **Per-trade sizing read the wrong field.** The `late_entry_v3` engine already
   sizes `per-trade = equity × capital_allocation_pct × fraction` and its own
   comment calls that input "the risk-profile CAP%". But the scan plumbing
   (`signal_scan_job` user query) aliased `user_strategies.weight` (≈0.10 for
   EVERY user) as `capital_allocation_pct` — NOT `user_settings.capital_alloc_pct`
   (the 20/40/60 the UI writes). So changing profile never changed size. DB proof:
   all 6 users had `weight=0.10` while `capital_alloc_pct` varied 0.20–0.50.
2. **No total-deployment cap.** The gate step 8 enforced a system-wide
   correlated-exposure ceiling (`MAX_CORRELATED_EXPOSURE` 0.40), not the per-user
   profile cap, so the profile never bounded how much capital was deployed.

Plus: **preset activation silently reset the profile** — `activate_preset`
force-wrote `risk_profile='balanced'` + the preset's own `capital_alloc_pct` on
every toggle, clobbering a user's chosen profile (e.g. Aggressive 60% → balanced).

FIX (owner chose "Both: cap + scale" and "let cap% override the 0.40 ceiling"):
- **Scale** — scan query now sources `capital_allocation_pct` from
  `COALESCE(s.capital_alloc_pct, us.weight, 0.10)`. Per-trade size now scales with
  the risk profile (the engine was already built for it).
- **Cap** — gate step 8 (main + resume paths) now enforces
  `(open_cost + proposed) / equity ≤ capital_alloc_pct`, read per-user via the new
  `_capital_alloc_pct()` helper. Conservative caps deployment at 20% of equity,
  Balanced 40%, Aggressive 60%, Custom ≤80%.
- **Override** — this per-user cap supersedes the legacy 0.40 system ceiling so
  Aggressive can deploy beyond 40% (owner directive; informed acceptance that this
  relaxes the correlated-exposure invariant). A hard `_MAX_DEPLOYMENT_PCT = 0.80`
  absolute ceiling remains so nothing can deploy past 80%.
- **Preset no longer clobbers profile** — `activate_preset` writes only
  strategy/timeframe/category/assets; risk_profile, capital_alloc_pct, tp_pct,
  sl_pct are left to the risk-profile setter / custom override.
- **Data** — migration 090 (+ applied to prod now) normalizes every non-custom
  profile's stored `capital_alloc_pct` to its canonical default (all 6 prod users
  → balanced 0.40); custom rows untouched.

## 2. Current system architecture

`capital_alloc_pct` (user_settings) is now the single source of truth for the
risk-profile capital control, consumed in TWO places: the sizing engine (per-trade
scale, via the scan query) and the risk gate (total-deployment cap, step 8).
Profiles still also differ in Kelly / max-position / concurrency / daily-loss /
min-edge / liquidity (unchanged PROFILES dict). TP/SL remain uniform 150/50.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/domain/risk/gate.py` (new `_capital_alloc_pct` +
  `_MAX_DEPLOYMENT_PCT`; step 8 rewritten in main + resume paths)
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` (scan
  query sources capital_allocation_pct from `s.capital_alloc_pct`)
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` (`activate_preset`
  no longer writes risk_profile/capital_alloc_pct/tp_pct/sl_pct)
- `projects/polymarket/crusaderbot/migrations/090_normalize_profile_capital_alloc.sql` (new)
- `projects/polymarket/crusaderbot/migrations/rollback/090_normalize_profile_capital_alloc_rollback.sql` (new)
- `projects/polymarket/crusaderbot/tests/test_risk_limit_reconciliation.py` (step-8 tests → deployment-cap semantics + aggressive-override test)
- `projects/polymarket/crusaderbot/tests/test_resume_safety_check.py` (resume step-8 → equity denominator + new reason)
- state: PROJECT_STATE.md, CHANGELOG.md

## 4. What is working

- Per-trade size now scales by profile (equity × 20/40/60% × fraction).
- Gate caps total deployment at the per-user profile %; Aggressive may exceed 40%.
- Preset toggles no longer reset the user's profile/capital.
- Prod data normalized (6 users balanced @ 0.40).
- 291 affected tests pass (gate, resume, sizing, preset, customize); ruff clean.

## 5. Known issues

- The 0.40 correlated-exposure invariant is intentionally superseded per owner
  directive (bounded by the 0.80 absolute ceiling). Documented for SENTINEL/audit.
- `_PRESET_PARAMS` still lists per-preset capital/TP-SL numbers that are now inert
  (no longer written). Left for a later cosmetic cleanup; harmless.
- Sizing-wiring change is SQL-alias level (covered by engine tests, not a new DB
  integration test).

## 6. What is next

Merged by WARP•R00T → Fly CD deploy applies migration 090 and the new sizing/gate.
Post-deploy: confirm a profile switch visibly changes trade size + deployment.
