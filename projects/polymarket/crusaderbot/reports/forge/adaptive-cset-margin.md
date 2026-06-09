# Adaptive Complete-Set Margin + Admin Knob

Role: WARP•R00T
Branch: WARP/adaptive-cset-margin
Validation Tier: STANDARD (strategy/data behavior; arb booking margin — bounded by the 2% hard floor; PAPER-only)
Claim Level: NARROW INTEGRATION
Validation Target: (1) `MIN_COMPLETE_SET_EDGE` becomes a no-redeploy admin runtime
  setting; (2) the per-pair required margin becomes adaptive to live order-book
  conditions (heuristic), strictly on top of the 2% hard floor.
Not in Scope: trading/exit/TP-SL logic, slippage gate, ENABLE_LIVE_TRADING /
  SCORER_ACTIVE / ORCHESTRATOR_ACTIVE / kill_switch, the LIVE booking path
  (re-asserts the 5 guards), migrations, a trained ML model (data-gated follow-up).
Suggested Next Step: WARP🔹CMD review + merge. Then operator sets
  `MIN_COMPLETE_SET_EDGE` (>0, e.g. 0.02) and optionally flips
  `COMPLETE_SET_ADAPTIVE_MARGIN_ENABLED` ON — both from the admin panel.

---

## 1. What was built

Owner request: move `MIN_COMPLETE_SET_EDGE` to admin settings, and make the
complete-set arb margin **dynamic to market conditions** ("ML-style"). Chosen
approach (confirmed): **heuristic adaptive** now, with a calibrated/ML model as a
data-gated follow-up. Hard invariant kept: the 2% net-edge floor
(`COMPLETE_SET_MIN_NET_EDGE`) is absolute — adaptive can only RAISE the required
margin above `max(operator_base, 2%)`, never relax below it.

1. **Pure heuristic module** `domain/strategy/complete_set_margin.py` —
   `adaptive_required_margin(base_floor, yes_book, no_book, intended_shares)`.
   The premium = the **execution slippage** of filling the intended size above
   top-of-book on each leg (walk the asks, `avg_fill - best_ask`), summed over
   both legs (same $/pair units as the margin), clamped to a cap
   (`ADAPTIVE_PREMIUM_CAP_USDC=0.10`). `required = base_floor + premium`. A deep,
   tight book → premium ≈ 0 → behaves like the static base; a thin/steep book →
   higher required edge → fragile "arbs" are skipped. Pure / IO-free / never
   raises (malformed book → 0 premium, never lowers the bar). Emits a feature
   vector per evaluation — the shadow-log substrate a future trained model reuses.

2. **Admin runtime knobs** (`domain/ops/runtime_config.py`):
   - `MIN_COMPLETE_SET_EDGE` (float, bounds [0, 0.5]) — the base floor, now a
     no-redeploy DB overlay (admin numeric input). 0 = dormant; any positive
     value is still clamped UP to the 2% hard floor by the scan.
   - `COMPLETE_SET_ADAPTIVE_MARGIN_ENABLED` (bool, default OFF) — turns the
     per-market premium on/off (safe rollout; OFF = static base, today's behavior).
   `config.py` gains `COMPLETE_SET_ADAPTIVE_MARGIN_ENABLED=False` as the env
   default (MIN_COMPLETE_SET_EDGE already existed).

3. **Scan wiring** (`services/signal_scan/complete_set_scan.py`): the base margin
   is now resolved through the admin overlay (`resolve_float`, DB override wins
   over env, fail-safe to env default), and when adaptive is ON the per-market
   `required_margin` is computed from that market's books at the user's intended
   size and passed to `fillable_complete_set`; the feature vector + decision are
   logged (`complete_set_adaptive_margin`) every evaluation regardless of outcome.

4. **Frontend** (`AdminPage.tsx`): the Bot Settings panel now renders `kind=="float"`
   runtime settings as a bounded numeric input + Save (optimistic update with
   rollback on a 400), alongside the existing bool toggles. Backend write path
   (`PATCH /admin/settings/{key}` → `set_override` → `_canonicalize`) already
   validated floats with bounds — no backend endpoint change needed.

## 2. Current system architecture

DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING (unchanged). The
complete-set arb scan (per-user, in the orchestrator loop) now:
base = overlay(`MIN_COMPLETE_SET_EDGE`) → clamp to ≥ 2% hard floor → (if adaptive
ON) `+ per-market slippage premium` → `fillable_complete_set` → RISK gate
(`complete_set=True`) → PAPER booking. The margin only ever tightens; everything
downstream (gate, paper-only, held-to-resolution, idempotency) is unchanged.

## 3. Files created / modified (full repo-root paths)

Created:
- projects/polymarket/crusaderbot/domain/strategy/complete_set_margin.py
- projects/polymarket/crusaderbot/tests/test_complete_set_margin.py (10 tests)
- projects/polymarket/crusaderbot/reports/forge/adaptive-cset-margin.md (this report)

Modified:
- projects/polymarket/crusaderbot/domain/ops/runtime_config.py — +2 SettingSpecs (float + bool)
- projects/polymarket/crusaderbot/config.py — +COMPLETE_SET_ADAPTIVE_MARGIN_ENABLED default
- projects/polymarket/crusaderbot/services/signal_scan/complete_set_scan.py — overlay base + adaptive per-market + feature log
- projects/polymarket/crusaderbot/tests/test_complete_set_scan.py — +3 wiring tests
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AdminPage.tsx — numeric control for float settings

## 4. What is working

- `test_complete_set_margin.py` (10): floor invariant, deep-book → 0 premium,
  steep-book → premium, both-legs sum, cap, intended-size sensitivity,
  empty/malformed-book fall-back, feature-vector shape.
- `test_complete_set_scan.py` (21 = 18 existing + 3 new): overlay base wins over
  env; adaptive OFF books the marginal arb; adaptive ON rejects it on a steep book.
- runtime_config (+admin_console) suites green (78); warp54 audit lanes green (10);
  frontend `tsc --noEmit` clean; ruff clean on all touched files.

## 5. Known issues / notes

- Heuristic v1 prices only **book-walk slippage**. `seconds_to_resolution` is
  logged in the feature vector but NOT yet priced into the premium — reserved for
  the calibrated/ML follow-up (which consumes the logged features).
- The premium cap (0.10 $/pair) and the slippage formula are fixed constants in
  the module (documented), not operator-tunable — intentional for v1 to keep the
  knob surface small; the ML phase replaces the formula.
- Still requires the operator to (a) set `MIN_COMPLETE_SET_EDGE > 0` and (b) flip
  `COMPLETE_SET_ARB_ENABLED` ON for any booking; adaptive is an additional opt-in.

## 6. What is next

- WARP🔹CMD review + merge.
- Operator: set `MIN_COMPLETE_SET_EDGE` (admin) and optionally enable adaptive.
- Follow-up lane (data-gated): a calibrated/ML margin model trained on the logged
  `complete_set_adaptive_margin` feature vectors (mirrors the WARP-70 adaptive-sigma
  shadow-first pattern) — shadow vs heuristic, then gated cutover.
