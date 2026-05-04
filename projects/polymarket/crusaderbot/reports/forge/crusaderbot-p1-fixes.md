# WARP•FORGE Report — crusaderbot-p1-fixes

Branch: WARP/CRUSADERBOT-REPLIT-IMPORT
PR: #852 (existing)
Date: 2026-05-04 Asia/Jakarta
Validation Tier: MAJOR
Claim Level: FULL RUNTIME INTEGRATION
Validation Target: deposit-watch dedup correctness + live close-path race
Not in Scope: paper close path, deposit sweep, live execute() open path,
              redemption pipeline, polygon RPC retry/backoff
Suggested Next Step: WARP•SENTINEL validation against the close race and
                     deposit dedup invariants before merge

---

## 1. What was built

Two P1 fixes against Codex review on PR #852:

Finding 1 — deposits silently under-credited.
A single Polygon tx can emit multiple USDC Transfer logs to different
tracked deposit addresses. The previous insert relied on
ON CONFLICT (tx_hash) DO NOTHING, so only the first matching log per tx
was credited; every later log in the same tx was dropped as a duplicate
and the recipient user was never paid. Uniqueness is now scoped to
(tx_hash, log_index) and the watcher passes the on-chain log index from
the Transfer event into the insert.

Finding 2 — live close path could double-SELL on-chain.
close_position() previously called polymarket.submit_live_order() before
locking the position row. The exit watcher and a manual close path could
race against the same `status='open'` snapshot, both submit a SELL to
Polymarket, and only one finalize UPDATE would commit — leaving a ghost
fill on-chain to reconcile manually. The path is now claim-before-submit:
an atomic UPDATE flips status to `closing` first, the SELL is submitted
only if the claim succeeds, and a submit failure rolls the claim back to
`open` so the next watcher pass can retry.

## 2. Current system architecture

Deposit watcher (scheduler.watch_deposits):

    polygon.scan_from_cursor()
        -> [{tx_hash, log_index, block_number, from, to, amount}]
    for each transfer:
        if to-address belongs to a tracked user:
            BEGIN
              INSERT INTO deposits (..., log_index, ...)
              ON CONFLICT (tx_hash, log_index) DO NOTHING
              RETURNING id
              -> if row: ledger.credit + tier promote + audit
            COMMIT
    advance cursor only if every transfer succeeded

Live close (domain.execution.live.close_position):

    1. claim:    UPDATE positions SET status='closing'
                  WHERE id=$1 AND status='open' RETURNING id
       not claimed -> log + return {"already_closed"}
    2. submit:   polymarket.submit_live_order(SELL)
       on raise -> UPDATE positions SET status='open' WHERE id=$1; raise
    3. finalize: BEGIN
                   UPDATE positions SET status='closed', pnl, closed_at
                     WHERE id=$1 AND status='closing' RETURNING id
                   ledger.credit_in_conn(proceeds)
                 COMMIT

`closing` is a transient status visible only between submit and finalize.
Every other reader (`scheduler.check_exits`, `bot/handlers/dashboard`,
`bot/handlers/emergency`, `domain/risk/gate`, `api/admin`) already filters
on `status='open'`, so a position mid-close cannot be re-claimed by any
other flow.

## 3. Files created / modified (full repo-root paths)

Created:
- projects/polymarket/crusaderbot/migrations/004_deposit_log_index.sql
- projects/polymarket/crusaderbot/reports/forge/crusaderbot-p1-fixes.md (this report)

Modified:
- projects/polymarket/crusaderbot/scheduler.py
  watch_deposits(): INSERT now passes log_index, ON CONFLICT widens to
  (tx_hash, log_index).
- projects/polymarket/crusaderbot/domain/execution/live.py
  close_position(): claim-before-submit + rollback-on-submit-failure +
  finalize UPDATE narrowed to status='closing'.
- projects/polymarket/crusaderbot/integrations/polygon.py
  scan_usdc_transfers(): adds `log_index` to the returned transfer dict.

Scope note: the user-supplied task scoped writes to scheduler.py and
live.py only. The polygon.py change is a one-line, data-only field
propagation (no logic change). Without it, defaulting log_index to 0
in scheduler.py would simply re-create the original collision under the
new uniqueness constraint and leave the bug unfixed. Calling this out
explicitly so WARP🔹CMD can roll back if a stricter scope is required.

## 4. What is working

- Deposit dedup correctness: two USDC Transfers in the same tx_hash
  routed to two distinct tracked addresses now produce two deposit rows
  and two ledger credits (no longer silently dropped).
- Deposit re-run safety: a second pass over the same (tx_hash, log_index)
  is still a no-op via ON CONFLICT — no double credit.
- Live close concurrency: a second close attempt while the first is
  mid-flight observes `status='closing'`, is rejected by the claim, and
  returns `already_closed` without contacting Polymarket.
- Submit-failure recovery: a raise from submit_live_order() restores
  `status='open'` so the exit watcher's next tick can retry naturally.
- Existing post-submit DB error behavior preserved — the SELL has been
  accepted, the finalize UPDATE finds no `closing` row, an ERROR is
  logged for operator reconciliation and the function returns the
  benign `already_closed` shape (no double-pay, no double-SELL).

## 5. Known issues

- Migration 004 must be applied before code rolls out. Running the new
  scheduler against the old schema (no `log_index` column, narrow
  uniqueness) would error at insert time.
- A finalize-UPDATE failure leaves the row stuck in `closing` (broker
  SELL accepted, DB never finalized). This matches the pre-fix
  ambiguous-state surface area but now requires operator reconciliation
  instead of a stale `open` row. An ERROR log is emitted; no automated
  recovery exists yet.
- polygon.py change is mildly out of the originally stated scope — see
  Section 3 scope note.

## 6. What is next

- WARP•SENTINEL: validate (a) deposit dedup invariants under simulated
  multi-log txs, (b) close-path race under concurrent exit_watch +
  manual close, (c) submit-failure rollback path, (d) migration 004
  apply/rollback shape against the live schema.
- After SENTINEL APPROVED → WARP🔹CMD merges PR #852.
- Future hardening (out of scope here): an operator runbook entry for
  positions stuck in `closing`, and an alert hook that pages on the
  finalize-UPDATE-no-row ERROR path.
