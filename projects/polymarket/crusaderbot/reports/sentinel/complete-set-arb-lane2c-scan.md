# WARP•SENTINEL — Complete-Set Arb Lane 2C-2b (scan + PAPER booking)

**Branch:** `WARP/ROOT/complete-set-arb-lane2c-scan`
**PR:** #1564
**Validation Tier:** MAJOR (risk gate + execution wiring)
**Audit scope (owner-directed):** Phase B3 wiring in `signal_scan_job.py` + step-13
bypass in `gate.py`. Verify (1) `COMPLETE_SET_ARB_ENABLED` guarantees absolute
isolation (dark by default), (2) the `GateContext.complete_set` hard-reject avoids
arbitrary Kelly shrinkage.
**Default assumption:** UNSAFE until every check passes.

---

## TEST PLAN

- Phase 0 — Pre-test gate (report / state / structure / evidence)
- Phase 1 — Functional: dark-by-default isolation chain; step-13 hard-cap
- Phase 2 — Pipeline: detect → log → gate → book, no bypass caller
- Phase 4 — Async safety of concurrent fetch
- Phase 5 — Capital integrity: no silent shrink; PAPER-only

Environment: `dev` (code-truth audit).

---

## PHASE 0 — PRE-TEST

- Forge report present, correct path/naming, 6 sections + metadata — PASS
  (`reports/forge/complete-set-arb-lane2c-scan.md`)
- `state/PROJECT_STATE.md` + `CHANGELOG.md` updated — PASS
- No `phase*/` folders; domain/services structure intact — PASS
- Implementation evidence for the claimed surface — PASS

Phase 0: PASS.

---

## FINDINGS (evidence = file:line)

### 1. Dark-by-default isolation — PASS (the core ask)

The ONLY production path to a complete-set booking is flag-gated end to end:

- `signal_scan_job.py:2889` gates on cheap preconditions first
  (`active_preset in _ALL_CANDLE_PRESETS and crypto_window_markets`), THEN reads
  the flag at `:2891-2892`
  (`_cset_enabled = bool(getattr(_get_settings(), "COMPLETE_SET_ARB_ENABLED", False))`).
  Config-read error → `_cset_enabled = False` (`:2895`); precondition miss →
  `False` (`:2897`). Scan runs only under `if _cset_enabled:` (`:2898`), which is
  also the import site (`:2899`) — with the flag OFF the module is never imported,
  never called.
- **Breaker check (caller graph):** `scan_complete_set_for_user` has exactly one
  caller — `signal_scan_job.py:2910` (inside the `_cset_enabled` block).
  `book_complete_set_paper` has zero callers outside `complete_set_scan.py` (where
  it is the default `booker`). `complete_set=True` is set in exactly one place
  (`complete_set_scan.py:222`). No path reaches booking that bypasses the flag.
- **Second floor:** even with the flag ON, `complete_set_scan.py:116`
  (`if not (min_pair_margin > 0.0): return`) makes the scan a no-op while
  `MIN_COMPLETE_SET_EDGE` is 0.0 (its default) — no book fetch, no gate, no book.
  The detector also returns `None` for a non-positive margin (defence in depth).

Verdict: absolute isolation confirmed. Default config = zero behaviour change.

### 2. Step-13 hard-reject, no Kelly shrink — PASS (the second ask)

`gate.py:449-461`:
- `if ctx.complete_set:` → `final_size = ctx.proposed_size_usdc` (`:454`) — the
  combined cost is passed through unchanged; the directional
  `final_size = min(proposed, max_pos_size)` shrink (`:463`) is in the `else`
  branch only.
- Over-cap is a HARD REJECT: `if final_size > max_pos_size: return
  GateResult(False, "complete_set_size_over_cap", 13)` (`:459-461`). Zero-size
  guard preserved (`:455-457`). So a set is either approved at its exact combined
  cost or rejected — never silently resized to desync from the booked legs.
- `GateContext.complete_set` defaults `False` (`:73`), so every existing caller
  keeps the directional path byte-for-byte.

### 3. Gate-once semantics + scope — PASS

The scan builds ONE `GateContext` per set on the combined cost with
`complete_set=True` and `edge_bps=None` (`complete_set_scan.py:202,222`), so the
directional edge floor (step 12) is skipped (arb margin is validated upstream by
`fillable_complete_set`). Quote size is bounded up front by `max_shares`
(Kelly·max_pos_pct·balance, in shares) at `:172`, so the gate's hard-cap is a
backstop, not the normal sizing path. `complete_set_arb` added to
`STRATEGY_AVAILABILITY` (`constants.py:85`) so step 4 admits the set under the
flag — inert until a producer exists (the flag-gated scan).

### 4. Async safety — PASS

`asyncio.gather` fetches both leg books concurrently
(`complete_set_scan.py:160`) and gathers the `_load_market` reloads
(`signal_scan_job.py`); both are independent reads (book HTTP / PK SELECT). On a
leg fetch error `gather` propagates into the per-market `try/except` →
`res.errors += 1`, market isolated (test-proven). No shared mutable state, no new
locks/races.

### 5. Capital integrity / PAPER-only — PASS

Booking uses the paper primitive; an unexpected `chosen_mode != "paper"` is
skipped, not executed (`complete_set_scan.py:237`). LIVE remains Lane 3. Booked
sets are held to resolution by the merged Lane 2C-2a exit guards (#1563).

### 6. Tests — PASS

121 audited-area tests pass (complete_set_scan 13, signal_scan_job, gate-rescope,
concurrency, edge-gate). The 13 new tests include dark-margin no-fetch,
gate-reject-blocks-book, live-decision-skipped, per-market-error-isolation, and
the two step-13 cases (passthrough-unshrunk + reject-over-cap). ruff + py_compile
clean.

---

## CRITICAL ISSUES

None found.

---

## STABILITY SCORE

| Dimension | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20 | 20 | Single flag-gated path; one producer; clean DI |
| Functional | 20 | 20 | Isolation chain + step-13 both verified |
| Failure modes | 20 | 19 | Config-read + balance-read + per-market all fail-safe; live edge UNMEASURED (logged first, by design) |
| Risk/capital | 20 | 20 | No silent shrink; double-floor; PAPER-only; exit guards merged |
| Infra+TG | 10 | 9 | Migration 078 ledger reconciled + FK/index verified; N/A elsewhere |
| Latency | 10 | 10 | Concurrent book + row fetch |
| **Total** | **100** | **98** | |

---

## GO-LIVE STATUS

**VERDICT: APPROVED** — Score 98/100, zero critical issues.

`COMPLETE_SET_ARB_ENABLED` provides absolute isolation: the only booking path is
flag-gated and has no bypass caller, with a second dormant floor
(`MIN_COMPLETE_SET_EDGE`) and the detector's own margin guard. The
`GateContext.complete_set` step-13 path passes the combined cost through unchanged
or hard-rejects over-cap — no arbitrary Kelly shrinkage, directional sizing
untouched. PAPER-only; LIVE is the separate owner-gated Lane 3.

---

## FIX RECOMMENDATIONS

None required for merge.

- (operational) Turn the flag ON with `MIN_COMPLETE_SET_EDGE=0` first to collect
  `complete_set_quote` logs before setting a positive edge floor / booking capital.

---

## NEXT GATE

Return to WARP🔹CMD for the merge decision (owner merges; SENTINEL does not).
