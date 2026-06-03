# WARP•FORGE — WARP-54 WARP•R00T Audit Follow-up Lanes

Branch: claude/lucid-davinci-uxOGn
Tracker: WARP-54 — [TRACKER] WARP•R00T Audit — CrusaderBot Follow-up Lanes
Source audit: projects/polymarket/crusaderbot/reports/forge/no-side-pnl-frame.md §5
Date: 2026-06-03 22:50 Asia/Jakarta

WARP🔹CMD directed "kerjakan semua" — forge all open child lanes of the tracker
in one branch. Lane #4 (late_entry_v3 OOS validation) was already closed by
WARP-58 (WARP/late-entry-oos-validation, merged #1587 — edge UNPROVEN on empty
snapshot substrate), so five lanes remain and are delivered here. Because the
execution environment provides a single branch, the lanes ship as one batched
PR with this consolidated report; each lane keeps its own validation tier, and
the MAJOR lanes still require WARP•SENTINEL before merge.

---

## 1. What was built

Five audit findings reconciled:

- Lane 1 (HIGH / MAJOR) — Edge floor wired. `edge_bps=None` was hardcoded in
  `signal_scan_job._build_trade_signal`, leaving risk gate step 12 (the
  directional `MIN_EDGE_BPS` floor) structurally inert. A new pure helper
  `_edge_bps_from_metadata` derives a measured edge from candidate metadata
  (`edge_bps` passthrough, or `edge` fraction ×10_000 → bps) so strategies that
  actually compute an edge (playbook closing-edge module stamps
  `metadata["edge"]`) now get gated. Heuristic strategies that do NOT measure EV
  (late_entry_v3's `ask_diff`) return None and stay honestly ungated — no
  fabricated EV is injected (consistent with WARP-58's UNPROVEN OOS finding).

- Lane 2 (HIGH / MAJOR) — Max-concurrent invariant reconciled to 5. The
  blueprint §6 + AGENTS.md RISK CONSTANTS fix the cap at 5, but profiles set
  balanced=12 / aggressive=20 and `MAX_OPEN_POSITIONS=20`. Restored a
  non-overridable system ceiling `MAX_CONCURRENT_TRADES = 5` and folded it into
  `effective_max_concurrent` (mirrors how `DAILY_LOSS_HARD_STOP` bounds
  `effective_daily_loss`), so every effective cap is `min(5, profile, override)`.
  Gate Cap 4 (global open-position count) is likewise clamped to
  `min(MAX_OPEN_POSITIONS, 5)`. Profile `max_concurrent` *intents* (5/12/20) are
  preserved (still pass the `hardening` 1..50 audit) but can never loosen a user
  past 5.

- Lane 3 (MEDIUM → treated MAJOR, arb/capital path) — Complete-set 2% floor
  hard-wired. `MIN_COMPLETE_SET_EDGE` (config default 0.0 = dormant) was the only
  floor. Added `COMPLETE_SET_MIN_NET_EDGE = 0.02` +
  `COMPLETE_SET_FEE_SLIPPAGE_ALLOWANCE = 0.0` constants; `complete_set_scan`
  clamps the operator floor UP to `2% + fee/slippage` once the path is activated.
  The dormant escape hatch (0.0 → no scan) is unchanged; the AGENTS.md arbitrage
  invariant ("net_edge > fees + slippage AND > 2%") can no longer be undercut by
  a small positive operator value.

- Lane 5 (MEDIUM / MINOR, observability) — Audit destinations unified.
  `kill_switch_exec._write_audit_log` now mirrors every kill-switch event into
  the canonical `audit.log` schema table (via `audit.write`, never-raises) in
  addition to the legacy public `audit_log` row. Forensic queries against the
  canonical destination (used by scheduler/redeem/user_service/live-gate) now see
  kill events too; the legacy table is retained for backward-compatible
  dashboards.

- Lane 6 (LOW / MINOR) — Two unlogged silent excepts fixed.
  `users._emit_settings_changed` (`users.py:254`) and the `position.closed` emit
  in `bot/handlers/trades.py:277` were bare `except: pass`. Both now log at DEBUG
  with `exc_info` — fire-and-forget semantics preserved, zero silent failures.

Accepted / no action (per tracker): `resume_safety_check` crash-recovery resume
skipping liquidity/market-status/impact is documented + intentional.

## 2. Current system architecture (relevant slice)

```
DATA -> STRATEGY -> INTELLIGENCE -> RISK (gate) -> EXECUTION -> MONITORING

RISK gate (domain/risk/gate.py):
  Cap 4  : open_count >= min(MAX_OPEN_POSITIONS, MAX_CONCURRENT_TRADES=5)  [Lane 2]
  step 7 : open_count >= effective_max_concurrent(profile, override)        [Lane 2]
           = min(5, profile_cap, override)
  step 12: edge_bps (from candidate metadata) < max(profile, MIN_EDGE_BPS)  [Lane 1]

Complete-set arb (services/signal_scan/complete_set_scan.py):
  min_pair_margin = max(MIN_COMPLETE_SET_EDGE,
                        COMPLETE_SET_MIN_NET_EDGE + FEE_SLIPPAGE_ALLOWANCE)    [Lane 3]
  (dormant when MIN_COMPLETE_SET_EDGE == 0.0)

Kill switch (domain/risk/kill_switch_exec.py):
  _write_audit_log -> public audit_log (legacy) + audit.write -> audit.log    [Lane 5]
```

Risk constants (FIXED, unchanged): Kelly α=0.25, max position ≤10%, daily loss
−$2,000, drawdown >8%, liquidity $10k, dedup, kill switch. Lane 2 brings the
in-code concurrent-trades ceiling back into agreement with the fixed `5`.

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/domain/risk/constants.py (Lanes 2, 3)
- projects/polymarket/crusaderbot/domain/risk/gate.py (Lane 2)
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py (Lane 1)
- projects/polymarket/crusaderbot/services/signal_scan/complete_set_scan.py (Lane 3)
- projects/polymarket/crusaderbot/domain/risk/kill_switch_exec.py (Lane 5)
- projects/polymarket/crusaderbot/users.py (Lane 6)
- projects/polymarket/crusaderbot/bot/handlers/trades.py (Lane 6)
- projects/polymarket/crusaderbot/tests/test_concurrency_policy.py (Lane 2 — 10
  tests corrected to the 5-ceiling truth + docstring)

Created:
- projects/polymarket/crusaderbot/tests/test_warp54_audit_lanes.py (Lanes 1/3/5/6)
- projects/polymarket/crusaderbot/reports/forge/warp54-audit-followups.md (this report)

## 4. What is working

- 267 tests pass across the touched subsystems (concurrency policy, complete-set
  scan/edge/gate, kill switch + paths, process-candidate gates, signal-scan job,
  users, live-gate hardening, pipeline-runtime hardening, robustness gate, and
  the 10 new WARP-54 lane tests). ruff + py_compile clean on all touched files.
- Lane 1: helper unit-tested (fraction→bps, bps passthrough+precedence, None for
  heuristic/empty/non-dict, non-finite/unparseable rejection).
- Lane 2: every effective cap clamps to ≤5; Cap 4 rejects at the hard ceiling for
  no-override users; tighter overrides still honored at step 7.
- Lane 3: a 0.5% operator floor with a 1.5%-margin pair books nothing (clamped to
  2%); a 3%-margin pair still books; dormant 0.0 unchanged.
- Lane 5: kill-switch audit writes the legacy row AND mirrors to canonical
  `audit.log` with normalized action + payload.
- Lane 6: emit failures log instead of silently passing; regression guard asserts
  the bare-pass blocks are gone.

## 5. Known issues

- Lane 1 is NARROW: only strategies that stamp a measured edge into metadata are
  gated by step 12. late_entry_v3 (the dominant candle strategy) carries a
  book-imbalance heuristic, not EV, so it remains ungated by step 12 by design.
  A future lane could derive a defensible EV once the snapshot substrate accrues
  (depends on SCAN_SNAPSHOT_ENABLED + retained data — same blocker as WARP-58).
- Lane 2 reverses a prior tested decision (the removed `MAX_CONCURRENT_TRADES`
  constant + 5/12/20 enforcement in `test_concurrency_policy.py`). This is the
  intended reconciliation per the AGENTS.md hard rule and the tracker, but it IS
  a user-visible risk-limit tightening (balanced/aggressive users drop from
  12/20 to 5 concurrent). Flagged here for explicit WARP🔹CMD / WARP•SENTINEL
  sign-off in case the 12/20 product tiering was deliberate.
- Lane 5 is a dual-write (legacy + canonical), not a removal of the legacy
  `audit_log` table; a later migration could retire the legacy table once no
  dashboard reads it.

## 6. What is next

- WARP•SENTINEL validation for the MAJOR lanes (1, 2, 3) before merge — risk /
  capital / arb paths.
- WARP🔹CMD review for the MINOR lanes (5, 6).
- After merge: Fly.io redeploy (Lane 2 changes live gating behavior; Lanes 1/3
  change scan/gate behavior).
- Update the WARP-54 Linear tracker checkboxes (done in this lane).

---

Validation Tier   : MAJOR (lanes 1/2/3 risk-capital-arb) + MINOR (lanes 5/6)
Claim Level       : NARROW INTEGRATION (Lane 1 edge floor scoped to
                    edge-stamping strategies; Lanes 2/3 fully wired into the
                    live gate/scan; Lanes 5/6 observability/logging)
Validation Target : gate step 12 edge plumbing; max-concurrent ceiling at 5
                    (effective_max_concurrent + Cap 4); complete-set 2% margin
                    clamp; kill-switch audit mirror; two silent-except logs
Not in Scope      : late_entry_v3 EV derivation; legacy audit_log table removal;
                    Lane #4 (already closed by WARP-58); any change to FIXED risk
                    constants other than restoring the concurrent-trades 5 ceiling
Suggested Next    : WARP•SENTINEL (MAJOR lanes), then WARP🔹CMD merge decision
```
