# WARP•SENTINEL — WARP-54 WARP•R00T Audit Follow-up Lanes (POST-MERGE)

Branch: WARP/ROOT/warp54-sentinel-closeout
Tracker: WARP-54 — [TRACKER] WARP•R00T Audit — CrusaderBot Follow-up Lanes
Validates: PR #1589 (squash f146233) — MERGED 2026-06-03 16:03 UTC
Source forge report: projects/polymarket/crusaderbot/reports/forge/warp54-audit-followups.md
Validator: WARP•R00T acting as WARP•SENTINEL (repo precedent; owner-directed)
Environment: dev (no DATABASE_URL / Redis / Telegram — infra checks warn-only per matrix)
Date: 2026-06-03 23:45 Asia/Jakarta

> POST-MERGE NOTE. The three MAJOR lanes (1/2/3) were merged in #1589 WITHOUT the
> mandatory WARP•SENTINEL gate. This report is the after-the-fact validation
> WARP🔹CMD directed. Verdict scope = "is the merged code safe / does it match
> audit intent, or must it be rolled back?" — not a pre-merge block.

---

## TEST PLAN

Phases run (relevant to the merged surface):

- Phase 0 — Pre-test gating (report, state, structure, evidence)
- Phase 1 — Functional, per merged lane (1/2/3 MAJOR; 5/6 MINOR sanity)
- Phase 3 — Failure modes (malformed metadata, balance-read failure, audit-write failure)
- Phase 4 — Async safety (no new shared-state mutation / race on the changed paths)
- Phase 5 — Risk rules in code (the core SENTINEL mandate)

Phases 2/6/7/8 (live pipeline e2e, latency wall-clock, infra, Telegram) are
warn-only in `dev` (no DATABASE_URL) and the merged changes are pure in-process
logic with no new hot-path I/O — assessed by code inspection, not live runtime.

---

## PHASE 0 — PRE-TEST (gate)

- Forge report present, correct path + naming, all 6 sections + metadata — PASS
  (projects/polymarket/crusaderbot/reports/forge/warp54-audit-followups.md)
- PROJECT_STATE.md carried the lanes (KNOWN ISSUES 233–235) — PASS (drift: still
  said "PR open" — corrected by this close-out lane)
- Zero `phase*/` folders in crusaderbot tree — PASS (`find` returned none)
- Hard-delete policy / no shims — PASS (changes are in-place edits, no re-export files)
- Implementation evidence exists for all MAJOR layers — PASS (file:line below)

Phase 0 result: PASS — proceed to functional testing.

---

## FINDINGS (per phase, with evidence)

### Phase 1 — Functional

Lane 1 — Edge floor (MAJOR). Evidence:
- `services/signal_scan/signal_scan_job.py:1711` `_edge_bps_from_metadata` — pure
  helper; `edge_bps` passthrough OR `edge` fraction ×10_000.
- `services/signal_scan/signal_scan_job.py:1851`
  `edge_bps=_edge_bps_from_metadata(cand.metadata)` — wired into TradeSignal
  (replaces the prior `edge_bps=None` hardcode).
- `domain/risk/gate.py:469-473` step 12 consumes it:
  `if ctx.edge_bps is not None: min_edge = max(profile["min_edge_bps"], K.MIN_EDGE_BPS); if ctx.edge_bps < min_edge: reject`.
- Behaviour: edge-stamping strategies (playbook closing-edge) are now gated; the
  heuristic `late_entry_v3` (`ask_diff`, no EV) returns None → still bypasses step
  12 BY DESIGN — no fabricated EV (consistent with WARP-58 OOS UNPROVEN). PASS.

Lane 2 — Max-concurrent ceiling = 5 (MAJOR). Evidence:
- `domain/risk/constants.py:18` `MAX_CONCURRENT_TRADES = 5`.
- `domain/risk/constants.py:189` `caps = [MAX_CONCURRENT_TRADES, profile_cap]`
  (+ override if ≥1) → `return min(caps)`. Effective cap ≤ 5 always; user may only
  tighten. Mirrors the `DAILY_LOSS_HARD_STOP`/`effective_daily_loss` pattern.
- `domain/risk/gate.py:299` Cap 4:
  `open_cap = min(int(settings.MAX_OPEN_POSITIONS), K.MAX_CONCURRENT_TRADES)`.
- `domain/risk/gate.py:410,665` step 7 uses `effective_max_concurrent(...)`.
- Ceiling enforced at BOTH the open-count cap (Cap 4) and the concurrent gate
  (step 7). Profile intents 5/12/20 preserved (still pass `hardening` 1..50) but
  can never loosen past 5. PASS.

Lane 3 — Complete-set 2% net-edge floor (MAJOR). Evidence:
- `domain/risk/constants.py:41` `COMPLETE_SET_MIN_NET_EDGE = 0.02`;
  `:45` `COMPLETE_SET_FEE_SLIPPAGE_ALLOWANCE = 0.0`.
- `services/signal_scan/complete_set_scan.py:120-125` dormant escape hatch intact:
  `MIN_COMPLETE_SET_EDGE == 0.0` → early return, no quote/booking.
- `services/signal_scan/complete_set_scan.py:133-140` once activated, the operator
  floor is CLAMPED UP: `min_pair_margin = max(operator, 0.02 + fee/slippage)`. A
  0.5% operator value cannot book a sub-2% set. PASS.

Lane 5 — Audit destination unified (MINOR, sanity only). Evidence:
- `domain/risk/kill_switch_exec.py:40` legacy `INSERT INTO audit_log ...` retained;
  `:51` `await _audit.write(...)` mirrors into the canonical `audit.log` schema
  table. `audit.write` never-raises → cannot break the kill path. PASS.

Lane 6 — Silent excepts logged (MINOR, sanity only). Evidence:
- `users.py:258` `_emit_settings_changed` now `log(..., exc_info=True)`.
- `bot/handlers/trades.py:281-284` `position.closed` emit now
  `logger.debug(..., exc_info=True)`. Fire-and-forget preserved, zero silent
  failures. PASS.

### Phase 3 — Failure modes

- Lane 1 malformed metadata: `_edge_bps_from_metadata` returns None for non-dict,
  None for non-finite (NaN/inf via `_math.isfinite`), None for unparseable
  (`TypeError`/`ValueError` caught). Unit-pinned in `test_warp54_audit_lanes.py`.
  Fail-honest (ungated) rather than fail-open with a fabricated edge. PASS.
- Lane 3 balance read failure: `complete_set_scan.py:151-153` catches and returns
  an empty result — fail-CLOSED (no scan, no booking) on balance error. PASS.
- Lane 5 audit-write failure: `_audit.write` is documented never-raises; the kill
  path's legacy row is written first, so an audit-mirror fault cannot abort a kill.
  PASS.

### Phase 4 — Async safety

- All four changed computations (`_edge_bps_from_metadata`, `effective_max_concurrent`,
  Cap-4 clamp, complete-set floor clamp) are pure / stateless `min`/`max`/parse
  operations — no shared mutable state, no new locks, no `threading`. The Lane 5
  mirror adds one awaited `audit.write` AFTER the existing insert on an already-async
  path (no new concurrency surface). No race / state-corruption introduced. PASS.

### Phase 5 — Risk rules in code (core mandate)

- Kelly α: `gate.py:489` `min(profile.kelly, K.KELLY_FRACTION)` — still 0.25-capped,
  untouched. PASS.
- Max position ≤10% — untouched. PASS.
- Daily loss −$2k hard stop / drawdown >8% halt — untouched (`gate.py:146`). PASS.
- Max-concurrent = 5 — RECONCILED by Lane 2 (was the in-code drift to 12/20). This
  is the lane's whole point and it now matches the AGENTS.md RISK CONSTANTS +
  blueprint §6 invariant. PASS (improvement).
- Complete-set arb: `net_edge > fees+slippage AND > 2%` — now hard-wired (Lane 3).
  PASS (improvement).
- Kill switch — intact + now better observed (Lane 5). PASS.
- `ENABLE_LIVE_TRADING` guard — untouched; paper-only. PASS.

### Test execution evidence

- `test_warp54_audit_lanes.py` + `test_concurrency_policy.py`: 27 passed.
- Broad touched-subsystem sweep (warp54 lanes + concurrency + complete_set
  scan/edge-gate/edge-metric/arb + kill_switch + kill_switch_paths +
  process_candidate_gates + signal_scan_job + users + live_gate_hardening):
  **262 passed** in 6.34s.
- `ruff check` on all 7 touched production files: All checks passed.

---

## CRITICAL ISSUES

None found.

---

## STABILITY SCORE

- Architecture (20): 18 — surgical, additive, folds into existing
  most-restrictive-min selection patterns; pipeline order preserved. (−2: Lane 1
  is NARROW — only edge-stamping strategies gated; the dominant `late_entry_v3`
  remains ungated by step 12, by design but a real coverage gap.)
- Functional (20): 19 — 262 touched-subsystem tests pass + 10 new lane tests +
  10 corrected concurrency tests; every lane unit-verified.
- Failure modes (20): 18 — fail-honest / fail-closed / never-raises across the
  changed paths; all malformed-input branches unit-pinned.
- Risk rules (20): 20 — Kelly/position/loss/drawdown/kill untouched;
  max-concurrent + complete-set floor reconciled toward the fixed invariants.
- Infra + Telegram (10): 8 — Lane 5 improves forensic observability; no infra
  regression. (−2: live Redis/PG/TG not exercised in dev — env-agnostic logic.)
- Latency (10): 9 — all changes O(1) pure compute; the one added I/O
  (`audit.write`) is off the kill-critical path and never-raises.

TOTAL: **92 / 100**

---

## GO-LIVE STATUS

Verdict: **APPROVED** (score 92 ≥ 85, zero critical issues).

Reasoning: the merged code matches the audit intent at every cited site, tests
are green, lint is clean, and the FIXED risk constants are untouched except for
the two deliberate tightenings the tracker asked for (max-concurrent → 5,
complete-set → 2%+fees). No rollback required; the post-merge state is safe.

The Lane 2 decision point (balanced/aggressive effective concurrent cap
12/20 → 5, reversing a prior tested tiering) was escalated to WARP🔹CMD and
RESOLVED: keep the 5-ceiling (it is the AGENTS.md hard rule + blueprint §6
invariant). No longer an open question.

---

## FIX RECOMMENDATIONS (priority ordered)

- P2 (follow-up lane, not blocking) — Lane 1 coverage: `late_entry_v3` (the
  dominant candle strategy) stays ungated by step 12 because it carries a
  book-imbalance heuristic, not EV. Derive a defensible `edge_bps` once the
  snapshot substrate accrues (depends on SCAN_SNAPSHOT_ENABLED + retained data —
  same blocker as WARP-58). Until then, ungated is the honest state.
- P3 (docs reconcile) — Blueprint §6 + config `MAX_OPEN_POSITIONS` default (20)
  doc text should be annotated to reflect the hard 5 ceiling so a future reader
  does not re-introduce the drift.
- P3 (cleanup, later migration) — Lane 5 is a dual-write; retire the legacy
  public `audit_log` table once no dashboard reads it.

---

## TELEGRAM PREVIEW

N/A — no Telegram surface changed in this lane. Lane 5 affects only the
kill-switch audit destination (DB), not any alert/command. The 7 alert events
and kill-switch command remain as previously validated.

---

Validation Tier   : MAJOR (lanes 1/2/3) — post-merge
Claim Level       : NARROW INTEGRATION (Lane 1 scoped to edge-stamping strategies;
                    Lanes 2/3 fully wired into the live gate/scan)
Validation Target : gate step 12 edge plumbing; max-concurrent 5-ceiling
                    (effective_max_concurrent + Cap 4); complete-set 2%+fees clamp
Not in Scope      : late_entry_v3 EV derivation; legacy audit_log removal; blueprint
                    doc reconcile; any FIXED risk constant other than the two
                    deliberate tightenings
Suggested Next    : WARP🔹CMD final merge-of-record acknowledgement (already merged)
                    + Fly redeploy (Lane 2 changes live gating) + WARP-54 tracker close
