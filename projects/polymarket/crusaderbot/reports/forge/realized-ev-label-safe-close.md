# WARP-78 — realized-EV label fix (safe_close horizon)

- Role: WARP•R00T
- Validation Tier: MAJOR (migration + settlement-backfill path) — additive,
  SHADOW-only (no selection/sizing/gate/runtime change; `SCORER_ACTIVE` stays False).
- Claim Level: NARROW INTEGRATION
- Validation Target: persist the safe_close-horizon realized label
  (open→close−30s) alongside open→close, so the EV trainer/A/B can judge safe_close
  at its real force-exit and stop sharing close_sweep's identical label.
- Not in Scope: trainer/A/B *consumption* of the new label (follow-up, needs accrued
  `paper_real` data), close_sweep's exact horizon (ambiguous in code — kept on
  open→close, ~8s slack), and the true binary-mid exit price (Option B, deferred).
- Branch: `WARP/root-realized-ev-label`

---

## 1. What was built

Implements the confident slice of the label-fix scope
(`reports/forge/smart-strike-label-fix-scope.md`). Phase 0 found the open→close
label is biased for force-exit rules. Grounded against `exit_watcher`: `safe_close`
force-exits ~30s before close, `close_sweep` ~8s (≈ close), `flip_hunter` holds to
settlement. The materially-biased case is **safe_close** — judged 30s late and given
the *same* label as close_sweep (a structural reason `close_sweep ≡ safe_close`).

- **`migrations/085_factor_vectors_safe_close_label.sql`** (+ rollback) — additive,
  nullable `realized_outcome_safe_close VARCHAR(8)` + `realized_delta_safe_close NUMERIC`.
  Idempotent → auto-applies via `run_migrations` on deploy.
- **`domain/research/factor_dataset.py`** — the settlement backfill now also resolves
  the underlying outcome at `close_epoch − SAFE_CLOSE_EXIT_LEAD_SEC` (30s) from the
  SAME oracle ring, and `_write_settled` persists it (COALESCE-guarded; NULL when the
  close−30s tick isn't in the ring — honest, like open→close).

Design choice: **settlement-side only**, no strategy/entry-path change. The authoritative
alternative (stamp each row's live `force_exit_at_rem_sec` at scan time) needs threading
through `evaluate → _evaluate_market → _observe_factor_vector` and close_sweep's horizon
is ambiguous in code — deferred to avoid entry-path risk + a guessed horizon. The 30s
safe_close lead is well-documented and the highest-value correction.

## 2. Current system architecture

Unchanged selection/risk/execution. The factor-vector settlement backfill writes one
more label per settled row. The precedence router still controls selection; nothing
consumes `realized_outcome_safe_close` yet (that is the trainer/A/B follow-up).

## 3. Files created / modified

- `migrations/085_factor_vectors_safe_close_label.sql` (+ `migrations/rollback/085_*`)
- `domain/research/factor_dataset.py` (`SAFE_CLOSE_EXIT_LEAD_SEC`; backfill + `_write_settled`)
- `tests/test_warp78_safe_close_label.py` (3 tests)
- `reports/forge/realized-ev-label-safe-close.md` (this) + state sync

## 4. What is working

- Settlement computes the safe_close-horizon outcome and it correctly **differs** from
  open→close when the underlying moved in the final 30s (validated: open→close `UP`,
  open→close−30s `DOWN`, sc_delta −0.01) — the bias correction + degeneracy break.
- NULL-safe when the close−30s tick isn't in the ring; `py_compile` clean; full pytest
  in CI (deps unavailable in sandbox; core formula validated by harness).

## 5. Known issues

- `close_sweep`'s exact force-exit horizon is ambiguous in code (test says rem≤8s;
  `exit_watcher` says "no fixed-time exit rule") → kept on open→close (≤8s slack,
  negligible). A precise close_sweep label is a follow-up once its exit mechanism is
  pinned.
- `SAFE_CLOSE_EXIT_LEAD_SEC=30.0` is a documented local constant mirroring the
  strategy's safe_close force_exit_at_rem_sec — centralizing it is a follow-up.
- The EV-impact conclusion needs the trainer/A/B to consume this label on accrued
  `paper_real` rows (next lane).

## 6. What is next

- After deploy, settled rows accrue `realized_outcome_safe_close`. Once enough
  `paper_real` rows settle, update `scorer_trainer.rule_won` / `scorer_ab` to use the
  safe_close horizon label for safe_close, then re-run the EV A/B and report whether the
  favorite/underdog EV picture changes — the input to the Phase-2 EV-comparator.

- Suggested Next Step: trainer/A/B consumption of the safe_close label (CMD-gated lane),
  then the Phase-2 EV-comparator per the Phase 0 sequence.
