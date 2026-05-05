# WARP•SENTINEL REPORT — r12e-auto-redeem
Date: 2026-05-05 19:45 Asia/Jakarta
Branch: WARP/CRUSADERBOT-R12E-AUTO-REDEEM
PR: #869 (MERGED 2026-05-05T07:51:36Z)
Score: 64/100
Verdict: CONDITIONAL

## Summary
R12e auto-redeem system is architecturally sound — asyncio-clean, guard-correct,
queue-atomic, well-tested against 14 hermetic scenarios — but two undeclared files
were included in the forge PR scope and one production function is missing a
required type annotation. Additionally, a preliminary sentinel report was committed
inside the forge PR before SENTINEL ran, and PROJECT_STATE.md was pre-updated to
claim “SENTINEL APPROVED 92/100” before the official audit; this is a process
integrity violation CMD must acknowledge before marking the lane fully closed.
This report supersedes the pre-filed document at the same path.

## Findings

### Critical (0)
None.

### Major (3)
- [MAJ-01] Sentinel artifact committed inside FORGE PR scope —
  `projects/polymarket/crusaderbot/reports/sentinel/r12e-auto-redeem.md` was
  added in PR #869 by FORGE/CMD, not by SENTINEL. The pre-filed report references
  intermediate SHA `c124aa843815` (not the final merged head `50877a11...`),
  meaning the self-review predates at least some PR commits. Consequently
  `state/PROJECT_STATE.md` was updated within the same PR to read
  “SENTINEL APPROVED 92/100” before the official SENTINEL audit ran. This
  violates SENTINEL process independence and misrepresents audit status in the
  project state. The present report supersedes the pre-filed document.

- [MAJ-02] `.github/workflows/gate-pr.yml` modified — the forge report declares
  scope as `services/redeem/`, migration, Settings UI, scheduler, and bot
  dispatcher. The workflow file is absent from the declared scope. The change
  (adding a WARP•GATE webhook trigger on PR events) is additive and low-risk
  but constitutes undeclared scope expansion per AGENTS.md §SCOPE GATE.
  — `.github/workflows/gate-pr.yml`

- [MAJ-03] Missing type annotation on production function —
  `hourly_worker._process(queue_id)` declares `queue_id` without a type
  annotation; should be `UUID`. Every other production function in the three
  new modules carries full type hints per AGENTS.md mandate.
  — `projects/polymarket/crusaderbot/services/redeem/hourly_worker.py:72`

### Minor (2)
- [MIN-01] `alerts._dispatch` called with underscore-prefix directly from
  `hourly_worker._page_operator` (line 91-93). The exit-watcher surface exposes
  a public `alert_operator_close_failed_persistent` wrapper; a symmetric
  `alert_operator_redeem_failed_persistent` helper would centralise the
  cooldown-key contract and remove underscore-prefix leakage into the caller.

- [MIN-02] `ensure_live_redemption` exceptions are caught and suppressed in
  `settle_winning_position` (redeem_router.py:198-202) by design — internal
  credit is decoupled from chain dispatch — but the intent is documented only
  via the inline comment. A one-line docstring addition would prevent a future
  maintainer from inadvertently closing the `except` block.

## Claim Verification
Declared: NARROW INTEGRATION (workers + queue wired end-to-end; on-chain CTF
          redemption tip gated by `EXECUTION_PATH_VALIDATED=false`)
Evidence: `ensure_live_redemption` short-circuits at line 375 when
          `EXECUTION_PATH_VALIDATED=False`. Both workers call
          `settle_winning_position` which credits internally regardless of
          on-chain outcome. All three AUTO_REDEEM_ENABLED entry points verified.
Verdict: MATCH

## Trading Safety
N/A — module is settlement-only (no Kelly sizing, no order placement, no direct
exchange API calls without circuit breaker). The sole capital-risk surface is
`ensure_live_redemption`; gated by `EXECUTION_PATH_VALIDATED=False` in current
state. No risk constants or trading safety constants touched.

AUTO_REDEEM_ENABLED guard: PASS — all three entry points short-circuit on
`if not s.AUTO_REDEEM_ENABLED: logger.info(...); return`. No raise, no crash.

Note (pre-existing, out of scope for this PR): `config.py` shows
`ENABLE_LIVE_TRADING: bool = True` and `AUTO_REDEEM_ENABLED: bool = True` as
Python-level defaults. Neither was changed in this PR. ROADMAP guard table lists
both as ○ OFF. CMD should verify `.env` / Fly.io secrets carry the correct
overrides before live deployment. Not a deduction; flagged for CMD awareness.

## Scope Verification
Declared scope (forge report §3):
  services/redeem/{__init__,redeem_router,instant_worker,hourly_worker}.py
  migrations/006_redeem_queue.sql
  bot/handlers/settings.py, bot/keyboards/settings.py
  bot/dispatcher.py, bot/menus/main.py
  scheduler.py, tests/test_redeem_workers.py
  reports/forge/r12e-auto-redeem.md, state files

Actual files changed (17):
  .github/workflows/gate-pr.yml          <- NOT IN SCOPE [MAJ-02]
  bot/dispatcher.py                       <- in scope
  bot/handlers/settings.py               <- in scope
  bot/keyboards/settings.py              <- in scope
  bot/menus/main.py                      <- in scope
  migrations/006_redeem_queue.sql        <- in scope
  reports/forge/r12e-auto-redeem.md      <- in scope
  reports/sentinel/r12e-auto-redeem.md   <- NOT IN SCOPE [MAJ-01]
  scheduler.py                           <- in scope
  services/redeem/__init__.py            <- in scope
  services/redeem/hourly_worker.py       <- in scope
  services/redeem/instant_worker.py      <- in scope
  services/redeem/redeem_router.py       <- in scope
  state/CHANGELOG.md                     <- accepted (state sync)
  state/PROJECT_STATE.md                 <- accepted (state sync)
  state/WORKTODO.md                      <- accepted (state sync)
  tests/test_redeem_workers.py           <- in scope

Verdict: EXCEEDED — 2 out-of-scope files

## Recommendation
PR #869 is already merged. CMD must:

1. [REQUIRED] Acknowledge MAJ-01: a sentinel report was committed inside the
   forge PR and PROJECT_STATE.md was pre-updated to claim SENTINEL status
   before this audit. This report is the official verdict and supersedes the
   pre-filed document. PROJECT_STATE.md should be corrected to read
   `SENTINEL CONDITIONAL 64/100` until MAJ-03 is resolved.

2. [REQUIRED before next lane] Fix `hourly_worker._process(queue_id)` missing
   UUID type annotation (MAJ-03). One-line fix; add to next lane PR or a
   dedicated patch commit.

3. [RECOMMENDED] Formally include `.github/workflows/gate-pr.yml` in a CI/CD
   scope (R12a) or acknowledge it as gate-infrastructure housekeeping (MAJ-02).

4. [LOW] Apply MIN-01 and MIN-02 as operational improvements in a follow-up lane.

The R12e auto-redeem system code is sound and safe to run in paper-default mode.
Conditional status lifts to GO-LIVE once MAJ-03 is resolved and CMD acknowledges
MAJ-01. No blocking capital-safety or runtime-safety findings.
