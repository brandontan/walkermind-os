# WARP•SENTINEL — complete-set-arb-lane3c-live-wire

Validator: WARP•R00T acting as WARP•SENTINEL (owner-authorised).
Branch: `WARP/ROOT/complete-set-arb-lane3c-live-wire`
**Reviewed commit:** `0ecfa9e` (post Gemini paper-accounting + Codex P2 fixes).
Tier: MAJOR (makes a LIVE order path reachable from the scan loop).
Environment: `dev` (Risk ENFORCED, infra/telegram warn-only).
Default posture: system UNSAFE until proven. Code is truth — forge report not trusted blindly.

---

## TEST PLAN

Scope = the scan→booker wiring in `services/signal_scan/complete_set_scan.py` only.
Phases run: 0 (pre-test), 1 (functional dispatch), 3 (failure modes), 4 (async
safety), 5 (risk-rule preservation), reachability/dormancy. Phases 2/6/7/8
(pipeline e2e / latency / infra / telegram) are owned by Lane 3B (`book_complete_set_live`,
SENTINEL-approved 97/100 in #1568) and are out of this lane's scope.

## FINDINGS (evidence — file:line)

**Phase 0 — Pre-test (all PASS):**
- Forge report at correct path + naming + all 6 sections + metadata:
  `reports/forge/complete-set-arb-lane3c-live-wire.md`. PASS.
- `PROJECT_STATE.md` updated (Status + [COMPLETED] + [NEXT PRIORITY] +
  Last Updated 2026-06-03 00:45 WIB); CHANGELOG appended. PASS.
- Zero `phase*/` folders (find). No shims. Hard-delete N/A (no migration). PASS.
- Implementation evidence present (dispatch read directly). PASS.

**Phase 1 — Functional (PASS):** dispatch at `complete_set_scan.py:245-300` branches
on `gate_res.chosen_mode`: `"paper"`→`book_complete_set_paper`; `"live"`→
`book_complete_set_live` threading `role`/`trading_mode`/`yes_book`/`no_book`
(the four args the paper primitive omits, all in scope); else → skip
(`complete_set_unknown_mode_skipping`, rejected). `booked` counts only persisted
outcomes on BOTH paths (paper: `status=="open"`; live: `open`/`naked_halt`). 18
hermetic tests pin every branch (routing / paper-duplicate / no_fill / naked_halt /
persist_failed / unknown / raise-isolated / unknown-mode). PASS.

**Phase 3 — Failure modes (PASS):**
- Ambiguous live post-submit raises → caught by the per-market `except Exception`
  (`:301`) → `res.errors += 1`, batch continues; booker already halted + paged.
  `test_live_booker_raise_isolated_to_market`. PASS.
- `naked_halt_persist_failed` (UNTRACKED live exposure) → `res.errors` +
  `complete_set_live_unreconciled` error log (was masked as clean no-op — Codex P2,
  FIXED in-lane). `test_live_naked_halt_persist_failed_is_error`. PASS.
- Unrecognised status → error (safe-by-default).
  `test_live_unknown_status_is_error_safe_by_default`. PASS.
- Per-market try/except isolates one bad market from the batch (`:301`). PASS.

**Phase 4 — Async safety (PASS):** no shared mutable state; `res` is per-call;
books fetched via `asyncio.gather` (`:160`); no threading; booker calls awaited
sequentially per market. No race introduced by the wiring. PASS.

**Phase 5 — Risk-rule preservation (PASS):** the wiring changes NO risk logic. The
gate runs unchanged BEFORE dispatch (`:224`), preserving RISK→EXECUTION order;
complete_set step-13 hard-cap path untouched; the live booker re-asserts all 5
LIVE activation guards (`assert_live_guards`, `complete_set_exec.py:448`). PASS.

**Reachability / dormancy (PASS — 4 independent OFF layers):**
1. `COMPLETE_SET_ARB_ENABLED` gates the whole scan (`signal_scan_job.py:2905`,
   default False, fail-closed at `:2902`/`:2904`).
2. `MIN_COMPLETE_SET_EDGE` default 0.0 → detector returns None (dormant).
3. gate `chosen_mode=="live"` requires user `trading_mode=="live"`.
4. `assert_live_guards` (5 guards) inside the booker.
Wiring alone does NOT make the path live. Runtime reach today = zero.

## CRITICAL ISSUES

**None reachable in this lane.** One known LIVE-capital gap exists but is NOT
introduced here and is provably unreachable: **stale scan-time books → recorded
weighted cost can understate actual FOK spend** (Codex P1 on this PR). It is the
same H-2/M-2 exact-fill reconciliation the prior SENTINEL ruled a MANDATORY Lane
3C-2 pre-condition; overspend is bounded above by the FOK limit; the path is behind
4 OFF layers. Tracked in PROJECT_STATE 3C-2 scope + forge Known-issues. This is a
**GO-LIVE gate, not a merge blocker** for the (dormant) wiring.

## STABILITY SCORE

| Dimension | Weight | Score | Evidence |
| --- | --- | --- | --- |
| Architecture | 20 | 19 | clean chosen_mode dispatch; DI testability; 4-layer dormancy |
| Functional | 20 | 19 | 18 hermetic tests, every branch + status pinned |
| Failure modes | 20 | 19 | raise-isolation + persist-failed/unknown → error (safe-by-default) |
| Risk rules | 20 | 18 | gate/guards/step-13 unchanged; stale-book overspend deferred to 3C-2 (unreachable) |
| Infra + TG | 10 | 10 | N/A here (halt/page path = 3B, validated) |
| Latency | 10 | 10 | concurrent book fetch; no new latency surface |
| **Total** | **100** | **95** | **zero reachable critical** |

## GO-LIVE STATUS

**VERDICT: APPROVED (95/100, 0 reachable critical) — as of `0ecfa9e`.**
Safe to MERGE: the wiring is correct and the complete-set path remains fully dormant
behind 4 independent OFF layers. **NOT cleared for the LIVE flip:** Lane 3C-2
(crash-recovery reconciler + `delayed`→terminal poll + exact-fill parsing, which
subsumes the Codex P1 stale-book overspend) is the mandatory pre-condition before
the operator may flip `COMPLETE_SET_ARB_ENABLED` + the 5 guards.

## FIX RECOMMENDATIONS (priority order)

1. **(Lane 3C-2, MANDATORY pre-LIVE)** exact-fill reconciliation: persist from the
   broker's actual fill (cost/proceeds) and/or refetch+recompute books immediately
   before submit — closes the stale-book overspend (Codex P1) + the deferred M-2.
2. **(Lane 3C-2)** crash-recovery reconciler for stuck `pending`/`unknown` rows +
   `delayed`→terminal poll instead of halt (H-2).
3. None for this lane — Gemini paper-accounting + Codex P2 already fixed in-lane.

## TELEGRAM PREVIEW

No new Telegram surface in this lane. The reachable operator page is the 3B naked-leg
halt alert (`🛑 COMPLETE-SET NAKED LEG — TRADING HALTED` / `🚨 HALT DID NOT ENGAGE`),
unchanged. The scan now additionally emits `complete_set_live_unreconciled` (error)
+ `complete_set_live_naked_halt` (warning) structured logs for runtime telemetry.

---

Done -- GO-LIVE: APPROVED. Score: 95/100. Critical: 0 reachable.
PR: WARP/ROOT/complete-set-arb-lane3c-live-wire (#1569)
Report: projects/polymarket/crusaderbot/reports/sentinel/complete-set-arb-lane3c-live-wire.md
State: PROJECT_STATE.md updated
NEXT GATE: Return to WARP🔹CMD for final merge decision; Lane 3C-2 mandatory before LIVE flip.
