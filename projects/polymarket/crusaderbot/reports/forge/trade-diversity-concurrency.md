# WARP•FORGE — trade-diversity-concurrency

Branch: claude/crusaderbot-signal-scan-debug-Xnckj
Role: WARP•FORGE
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION (code + hermetic unit validation; live behaviour confirmed post-deploy)
Validation Target: per-user selection diversity + per-profile concurrency caps.
Not in Scope: category mapping (Lane 1 — blocked on Gamma tag taxonomy / network allowlist) and the edge-model rework (Lane 3). The fixed risk fences (Kelly 0.25, max 10%/pos, daily -$2k, 8% drawdown, 40% correlated exposure) are untouched.

---

## 1. What was built

Fixes the #1 closed-beta complaint — "the bot only ever trades the same ~5
markets and can't find others" — which decomposed into two root causes, both
addressed here:

ROOT CAUSE A — every subscriber received feed publications in identical
``published_at ASC`` order and entered that same prefix until the concurrency
cap stopped them. With 5 users all reading the same order and the same cap,
all 5 converged on the *same* handful of markets. FIX: `signal_evaluator`
now orders each user's candidates by a stable per-user key
``sha1(user_id:market_id)`` (`_diversify_order`). Every candidate has already
cleared the edge / liquidity / resolution-horizon filters, so any is an
acceptable entry; the per-user ordering spreads the eligible set across users
(distinct holdings) while staying deterministic per (user, market) so a user
does not churn positions between ticks. Single injection point — covers both
live callers (`signal_scan_job.run_once` and `SignalFollowingStrategy.scan`).

ROOT CAUSE B — the per-profile open-position cap was only 3/5/5, so even with
hundreds of candidates per tick a user could hold at most 5 positions. FIX:
raised `PROFILES[*].max_concurrent` to conservative 5 / balanced 12 /
aggressive 20 (custom follows balanced = 12). The gate's correlated-exposure
fence (40% of balance) still bounds total exposure, so the raise yields more,
smaller, diverse positions rather than over-leverage.

---

## 2. Current system architecture

```
signal_scan_job.run_once  /  SignalFollowingStrategy.scan
        -> evaluate_publications_for_user(user_ctx, filters)
             load active publications (published_at ASC, horizon-filtered)
             build SignalCandidates (edge/liquidity/horizon already enforced)
             _diversify_order(candidates, user_id)   <-- NEW per-user ordering
        -> for cand in candidates: _process_candidate -> risk gate
             gate step 7: open_count >= PROFILES[profile].max_concurrent  (5/12/20)
             gate step 8: open_exposure <= 40% balance  (unchanged fence)
```

---

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/domain/risk/constants.py — PROFILES max_concurrent 3/5/5 -> 5/12/20 (custom 5 -> 12).
- projects/polymarket/crusaderbot/services/signal_feed/signal_evaluator.py — `_diversify_order` per-user candidate ordering + `import hashlib`; applied at the end of `evaluate_publications_for_user`.

Created:
- projects/polymarket/crusaderbot/tests/test_signal_diversity.py — 6 hermetic tests (diversity differs per user, stable per user, set-preserving, empty-safe, caps raised, fixed fences unchanged).

State:
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md / WORKTODO.md / CHANGELOG.md — surgical lane entries.

No schema migration.

## 4. What is working

- `_diversify_order`: two users get different orderings (and different cap-limited prefixes) of the same candidate set; same user is stable across calls; set is preserved; empty-safe.
- Caps raised; fixed risk fences asserted unchanged.
- Full affected suites green: test_signal_following (72) + test_runtime_trade_smoke (37) + test_signal_scan_job + test_copy_trade + test_confluence_scalper + test_pipeline_runtime_hardening (195) + test_warp56_sentry_fix + test_live_gate_hardening (50) + test_signal_diversity (6). Guards untouched (ENABLE_LIVE_TRADING=false, paper-only).

## 5. Known issues

- Diversity emerges only when eligible candidates per tick exceed the cap (true in prod: ~hundreds/tick). If a tick yields fewer candidates than the cap, users still overlap — expected.
- Lane 1 (category mapping) still outstanding: doing it correctly needs Polymarket's Gamma tag taxonomy. A keyword classifier over question text only covers ~29% (71% "Other"), so it is a weak substitute. Blocked until gamma-api.polymarket.com is added to the environment network allowlist (owner action), after which a proper tag->category mapping can be built.
- Lane 3 (edge-model rework — the "0 profit / longshot bias" cause) not started.

## 6. What is next

- WARP•SENTINEL MAJOR validation (diversity determinism, cap change vs. fixed fences, guards).
- Post-merge: Fly redeploy; confirm distinct per-user holdings across the 6 users and that users hold more than 5 positions.
- Lane 1 once Gamma is allowlisted; then Lane 3 (edge model).

---

Suggested Next Step: WARP•SENTINEL audit (MAJOR); then allowlist Gamma to unblock Lane 1.
