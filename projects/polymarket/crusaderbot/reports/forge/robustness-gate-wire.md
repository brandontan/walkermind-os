# WARP•FORGE — robustness-gate-wire (WARP-53 Phase-2c-1b, part 2)

Role: WARP•FORGE (under the WARP•R00T PLAYBOOK epic, WARP-53)
Validation Tier: **MAJOR** (money-path — touches the gate's live/paper decision)
Claim Level: **NARROW INTEGRATION** (downgrade-only, default OFF, paper unaffected)
Validation Target: the robustness live-guard (`module_live_eligible`) end-to-end —
GateContext → `_passes_live_guards`, TradeSignal threading, and the cached source.
Not in Scope: enabling the gate (operator flag); the scheduled classifier (PR #1580);
the replay engine (2c-3). LIVE trading remains behind all existing activation guards.
Suggested Next Step: WARP•SENTINEL MAJOR validation (this report) → WARP🔹CMD merge.

---

## 1. What was built

The deferred half of Phase-2c-1b: wires the Monte Carlo robustness verdict into the live
decision so an **UNTRADEABLE** module can be held to paper. Strictly **downgrade-only** and
default-OFF — it can make a would-be live trade paper, never enable live.

- **`domain/risk/gate.py`** — `GateContext.module_live_eligible: bool = True` + a standalone
  `_apply_robustness_downgrade(chosen_mode, ctx)` applied in `evaluate` **after** the
  live-guard fallback block. It flips `live → paper` for an ineligible module WITHOUT
  tripping `live_fallback.trigger_for_live_guard_unset` (which would persistently flip the
  user's `trading_mode` and disable live for their *other* eligible modules — Codex P1).
  The flag is deliberately NOT inside `_passes_live_guards` for exactly that reason. Default
  True → identical behaviour to today.
- **`services/trade_engine/engine.py`** — `TradeSignal.module_live_eligible: bool = True`
  threaded through the single `_build_gate_context` into the GateContext.
- **`domain/research/robustness.py`** — `untradeable_set(mode)`: TTL-cached (300s) read of
  the `(module, risk_profile)` pairs classified UNTRADEABLE, so the gate costs one DB read
  per cache window, not per candidate. Fail-soft → empty set (never over-blocks).
- **`services/signal_scan/signal_scan_job.py`** — in `_process_candidate`, when
  `ROBUSTNESS_GATE_ENABLED` is on, looks up the candidate's module
  (`metadata.selected_module` or `strategy_name`) + profile against `untradeable_set` and
  passes `module_live_eligible` into `_build_trade_signal`. Gated + fail-soft: any error →
  eligible (a gate fault never blocks trading).
- **`services/signal_scan/complete_set_scan.py`** — the other direct `GateContext` money
  path threads `module_live_eligible` too (module `complete_set_arb`), so the gate's
  coverage is consistent across both live-routing callers (Codex P2). Same gated + fail-soft
  pattern.
- **`config.py`** — `ROBUSTNESS_GATE_ENABLED: bool = False`.

## 2. Why this is safe (the money-path argument)

- **Downgrade-only, no side-effects.** `_apply_robustness_downgrade` runs *after* the
  live-guard fallback and only flips `chosen_mode` `live → paper`. It does NOT call the
  user-level `live_fallback` (Codex P1 fix), so it never persistently changes a user's
  `trading_mode` or affects their other modules. No path enables live or alters paper.
- **Default OFF + default True.** With the flag off the scan never computes it; the field
  defaults True, so the AND is a no-op. Zero behaviour change until an operator opts in.
- **Fail-soft at every layer.** `untradeable_set` → empty on error (nothing downgraded);
  the scan-loop lookup → eligible on any exception; INSUFFICIENT_DATA/unclassified modules
  are never in the UNTRADEABLE set, so a cold table downgrades nothing.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/domain/risk/gate.py` — GateContext field + guard AND
- `projects/polymarket/crusaderbot/services/trade_engine/engine.py` — TradeSignal field + mapping
- `projects/polymarket/crusaderbot/domain/research/robustness.py` — `untradeable_set` (cached)
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — gated lookup + thread-through
- `projects/polymarket/crusaderbot/config.py` — `ROBUSTNESS_GATE_ENABLED`
- `projects/polymarket/crusaderbot/tests/test_robustness_gate.py` — NEW (9 tests)
- `projects/polymarket/crusaderbot/reports/forge/robustness-gate-wire.md` — this report
- State: `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` · `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- **361 gate/engine/risk/robustness tests pass** (9 new + full existing suites green) —
  proves the field additions are backward-compatible (default True → no change).
- New tests pin: live guards pass when eligible, blocked when UNTRADEABLE, still blocked
  when another guard fails; TradeSignal→GateContext threading; `untradeable_set` aggregation,
  TTL cache (one query), and fail-soft empty.

## 5. Known issues

- Effective only once a module reaches ≥30 closed paper positions AND the classifier job
  (PR #1580) has populated `module_robustness` AND the operator sets both flags. Until then
  the UNTRADEABLE set is empty and nothing downgrades.
- Stacks on #1580 (config flag) + #1578 (migration 079 / `module_robustness`): config.py and
  robustness.py will need a trivial merge alongside #1580.
- The gate uses paper-mode classifications to gate live eligibility (intentional — paper is
  the meaningful pre-live sample); revisit once live history exists.

## 6. What is next

- WARP•SENTINEL MAJOR validation → merge → operator enables `ROBUSTNESS_GATE_ENABLED` only
  after `ROBUSTNESS_CLASSIFY_ENABLED` has accrued verdicts.
- 2c-3 walk-forward replay over `market_snapshots`.

---

- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION (downgrade-only, default OFF)
- Validation Target: robustness live-guard end-to-end
- Not in Scope: flag enablement, classifier job, replay engine, LIVE activation
- Suggested Next Step: WARP•SENTINEL MAJOR validation → WARP🔹CMD merge
