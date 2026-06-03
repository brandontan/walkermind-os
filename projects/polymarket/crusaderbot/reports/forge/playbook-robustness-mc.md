# WARP•FORGE — playbook-robustness-mc (WARP-53 Phase-2c-1)

Role: WARP•FORGE (under the WARP•R00T PLAYBOOK epic, WARP-53)
Validation Tier: **MAJOR** (capital-eligibility gate + new migration; risk/capital domain)
Claim Level: **FOUNDATION** (engine + classifier + gate API + persistence; NOT yet wired
into the live execution gate — that is a deliberate, separately-reviewable follow-up)
Validation Target: the Monte Carlo simulator, the robustness classifier, module grouping +
persistence, and the `live_eligible` gate semantics.
Not in Scope: wiring `live_eligible` into the runtime risk/activation gate (2c-1b follow-up,
flag-gated); the walk-forward replay engine (needs 2c-2 snapshot data); applying migration
079 to Supabase (operator action); Monte Carlo for non-PLAYBOOK modules beyond what
`positions.strategy_type` already groups.
Suggested Next Step: WARP•SENTINEL review (MAJOR) or WARP🔹CMD merge; then Lane 2c-2.

---

## 1. What was built

Phase-2c-1 — the first half of the backtest/validation framework the WARP-51 alpha audit
flagged as the #1 gap (F-1: no OOS validation exists). It is the **Monte Carlo robustness
track**, buildable now because realized trade outcomes are already persisted in `positions`:

- **`domain/research/monte_carlo.py`** — dependency-free (stdlib `random`/`statistics`)
  bootstrap simulator. Resamples a module's realized per-trade return fractions
  (`pnl_usdc / size_usdc`) into equity paths at a profile's per-trade sizing
  (`max_pos_pct`) and returns tail risk: **risk-of-ruin**, **P95 / median max drawdown**,
  **P95 losing streak**, plus EV per trade. Pure + seedable (deterministic tests).
- **`domain/research/robustness.py`** — `classify(mc)` → **ROBUST / FRAGILE / UNTRADEABLE
  / INSUFFICIENT_DATA** (blueprint §12.2 thresholds: EV≤0 or ruin>5% → UNTRADEABLE; P95
  drawdown ≥ 8% halt or P95 streak ≥ 8 → FRAGILE; <30 trades → INSUFFICIENT_DATA).
  `classify_modules()` reads closed positions grouped by module (PLAYBOOK's per-module
  `strategy_metadata.selected_module`, else `strategy_type`), classifies, and upserts the
  latest verdict. `live_eligible(module)` is the gate: **only UNTRADEABLE withholds live
  capital** — ROBUST/FRAGILE/INSUFFICIENT/unclassified all allow, so it can never silently
  disable an existing live flow. Fail-soft on every DB touch.
- **`migrations/079_module_robustness.sql`** — `module_robustness` table (verdict + metrics
  per module/profile/mode), unique on `(module, risk_profile, mode)`.

## 2. Current system architecture

No change to the live trading path. The research plane is a pure read-side consumer of
`positions`; nothing calls `live_eligible` in the runtime gate yet (FOUNDATION). When wired
(2c-1b, behind a flag), the activation/risk layer will consult `live_eligible(module)` before
permitting live capital, and a scheduled job will refresh classifications. The simulator
reuses the *realized* outcomes — no parallel signal logic, no sim/live drift.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/migrations/079_module_robustness.sql` — NEW
- `projects/polymarket/crusaderbot/domain/research/__init__.py` — NEW
- `projects/polymarket/crusaderbot/domain/research/monte_carlo.py` — NEW
- `projects/polymarket/crusaderbot/domain/research/robustness.py` — NEW
- `projects/polymarket/crusaderbot/tests/test_research_robustness.py` — NEW (19 tests)
- `projects/polymarket/crusaderbot/reports/forge/playbook-robustness-mc.md` — this report
- State: `state/PROJECT_STATE.md` · `state/WORKTODO.md` · `state/CHANGELOG.md`

## 4. What is working

- **19 tests pass**; ruff + py_compile clean. Simulator extremes verified (all-wins → 0
  ruin/0 DD; all-losses → ruin 1.0; empty → zeroed; seed-deterministic). Classifier covers
  all five verdict paths. `classify_modules` grouping + persistence and `live_eligible`
  block/allow/unclassified/fail-soft paths all pinned.
- Gate is conservative by construction: unclassified and INSUFFICIENT_DATA never block, so
  bolting it into the live path cannot disable the existing LIVE candle/weather/copy flows.

## 5. Known issues

- Sizing model uses `max_pos_pct` as the per-trade equity fraction (conservative upper
  bound on path volatility); it does not re-derive Kelly from per-trade edge (the realized
  return already embeds the outcome). Documented; refine if needed once sample sizes grow.
- Verdicts are only meaningful once a module has ≥30 closed positions; paper trading must
  accrue history first. Until then everything is INSUFFICIENT_DATA (allow).
- Migration 079 must be applied to Supabase by the operator before `classify_modules`/
  `live_eligible` can persist/read (until then both fail-soft to empty/allow).

## 6. What is next

- Lane 2c-1b: wire `live_eligible` into the activation/risk gate behind `ROBUSTNESS_GATE_ENABLED`
  (default OFF) + a scheduled `classify_modules` refresh job + Telegram/dashboard surface.
- Lane 2c-2: per-scan book/price snapshot persistence (substrate for walk-forward).
- Lane 2c-3: walk-forward replay engine (consumes 2c-2 data) — full §12.1.

---

- Validation Tier: MAJOR
- Claim Level: FOUNDATION (analytics + gate API; no runtime wiring yet)
- Validation Target: simulator + classifier + grouping/persistence + gate semantics
- Not in Scope: live-gate wiring, replay engine, Supabase migration apply
- Suggested Next Step: WARP•SENTINEL review (MAJOR) or WARP🔹CMD merge → Lane 2c-2
