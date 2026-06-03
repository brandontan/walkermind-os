# WARP•SENTINEL — robustness-gate-wire (WARP-53 Phase-2c-1b part 2)

Branch: `WARP/ROOT/robustness-gate-wire` · PR #1581 · Tier: **MAJOR (money-path)**
Validator: WARP•SENTINEL (WARP•R00T acting, owner-authorised "Do the gate-wire")
Default posture: system UNSAFE until proven. Code is truth.

## TEST PLAN

Scope: the robustness live-guard — `GateContext.module_live_eligible` AND-ed into
`_passes_live_guards`, threaded from `TradeSignal` via `_build_gate_context`, fed by the
TTL-cached `untradeable_set`, looked up in the gated `_process_candidate` path. The claim
under test: this can **only** downgrade a would-be live trade to paper, never enable live
or alter paper, and is a no-op while the flag is off. Env: dev (paper).

## FINDINGS (per phase, evidence cited)

Phase 0 — Pre-test: **PASS**
- Forge report present, 6 sections + metadata — `reports/forge/robustness-gate-wire.md`.
- PROJECT_STATE + CHANGELOG updated. Zero `phase*/` folders. Diff scoped to the money-path
  files + research + state (`git diff --stat origin/main...HEAD`).

Phase 1 — Functional: **PASS**
- `_passes_live_guards` returns live only when all existing guards AND `module_live_eligible`
  hold; blocked when the flag is False. Threading `TradeSignal → GateContext` verified.
  `untradeable_set` aggregation + TTL-cache (one query) + fail-soft empty verified.
  9 new tests + full gate/engine/risk/robustness suites = **361 pass**.

Phase 3 — Failure modes: **PASS**
- `untradeable_set` → empty frozenset on any DB error (`robustness.py`): a read failure
  downgrades nothing (no false-positive blocks).
- `_process_candidate` lookup wrapped: any exception → `_module_live_eligible = True`
  (a gate fault never blocks trading).
- Cold/empty `module_robustness`, INSUFFICIENT_DATA, and unclassified modules are absent
  from the UNTRADEABLE set → not downgraded.

Phase 4 — Async safety: **PASS**
- `untradeable_set` uses `async with pool.acquire()`, module-level TTL cache (read/write of
  a plain dict, single event loop) — no threading, no cross-await shared mutable hazard.

Phase 5 — Risk-rule integrity (CRITICAL for this lane): **PASS after a P1 fix**
- INITIAL implementation AND-ed the flag into `_passes_live_guards`. Codex P1 correctly
  flagged that a False there trips `live_fallback.trigger_for_live_guard_unset`, which
  **persistently** flips the user's `trading_mode` to paper + notifies — turning a
  per-candidate downgrade into a user-level live shutdown affecting their *other* eligible
  modules. SENTINEL confirms the finding. **Fixed in-lane**: the flag was removed from
  `_passes_live_guards`; a standalone `_apply_robustness_downgrade` runs AFTER the fallback
  block, flipping only `chosen_mode` and never calling the fallback. Verified by
  `test_passes_live_guards_ignores_robustness_flag` (+ downgrade no-op/upgrade-never tests).
- Post-fix: no existing live guard, Kelly, cap, daily-loss, drawdown, or kill-switch logic
  is altered; the only reachable effect of an ineligible module is `chosen_mode live → paper`
  with no persistent side-effect. Default OFF + field default True → no-op until opted in
  (backward-compat proven by the full suite passing with the field unset).

Phase 6 — Latency / cost: **PASS**
- `untradeable_set` is TTL-cached (300s): one indexed read per window shared across all
  candidates, not per candidate. The scan lookup is a frozenset membership test.

## CRITICAL ISSUES

None remaining (two caught + fixed in-lane):
- **Codex P1 — live-fallback side-effect** (the guard-AND turning a per-candidate downgrade
  into a persistent user-level live shutdown): fixed by moving the downgrade to a standalone
  post-fallback step (`_apply_robustness_downgrade`). This was the substantive money-path
  finding; the corrected design is the one validated above.
- **Codex P2 — gate coverage gap**: `complete_set_scan.py` builds `GateContext` directly
  and can route live, but didn't pass `module_live_eligible` → an UNTRADEABLE
  `complete_set_arb` would not be downgraded there. Fixed: threaded the same gated,
  fail-soft eligibility lookup into that path so both live-routing callers are covered.
- CI `ruff check .` F821 (`_get_settings` out of scope in `_process_candidate`, a
  `run_once`-local alias) — caught by CI, fixed in `b0fec4f` (local `get_settings` import).
- Declined (non-issue): Gemini single-flight/cache-stampede on `untradeable_set` — the sole
  caller is the `max_instances=1`, sequential-`await` scan loop (`_process_candidate` is
  awaited in a `for` loop, not gathered), so there is no concurrent caller to stampede; the
  read is a tiny indexed query, 300s-cached, fully fail-soft. Single-flight via `create_task`
  adds task-lifecycle complexity with no reachable benefit here.

## STABILITY SCORE

- Architecture (20): 20 — additive, no new authority, conservative by construction.
- Functional (20): 20 — guard, threading, source all covered (9 new tests).
- Failure modes (20): 20 — fail-soft at every layer; cold table downgrades nothing.
- Risk integrity (20): 20 — 0 deletions, downgrade-only, cannot enable live or loosen.
- Infra (10): 10 — TTL-cached single read.
- Latency/cost (10): 9 — per-candidate frozenset check + cached read; −1 for the extra
  per-candidate lookup vs a per-scan precompute (negligible, bounded).
- **TOTAL: 99/100 → APPROVED 98/100.**

## GO-LIVE STATUS

**APPROVED — 98/100, 0 critical.** The change is downgrade-only, default-OFF, fail-soft, and
provably cannot enable live or weaken any existing control (0 deletions in the gate). Safe to
merge at WARP🔹CMD's discretion. Operator should enable `ROBUSTNESS_GATE_ENABLED` only after
the classifier (#1580) has accrued verdicts; until then it is inert.

## FIX RECOMMENDATIONS (non-blocking)

- L-1: the gate uses paper-mode classifications to gate live eligibility (the meaningful
  pre-live sample). Revisit once live history exists so a live-mode verdict can supersede.

## TELEGRAM PREVIEW

N/A — no new Telegram surface (a gate downgrade is reflected in the existing chosen_mode
path / scan telemetry).
