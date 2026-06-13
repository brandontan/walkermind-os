# WARP•R00T — withdrawal-request-debited-but-not-received-blocker (#1819)

Branch: `WARP/withdrawal-request-debited-but-not-received-blocker`
Issue: #1819
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Role: WARP•R00T (root-cause + minimal lifecycle visibility fix)
Date: 2026-06-13 14:54 Asia/Jakarta

Validation Target: classify the owner-reported `-$9.00 withdrawal request` debit (funds never arrived at `0x5E5b93e4…`) against code-truth, fix the user-facing + operator-facing visibility gap that hid the queued state, and pin every lifecycle invariant the issue lists.

Not in Scope: no real fund movement, no auto-retry of the owner production withdrawal, no native USDC/USDT enablement, no Bridge/pUSD changes, no live-guard flag flip, no strategy change, no historical ledger mutation, no full PII leak in repo/logs/fixtures.

---

## 1. Root-cause statement

**The withdrawal is NOT lost.** Capital safety is sound; the user-facing visibility is what failed.

Code-truth chain that reproduces the owner's symptoms:

1. `wallet/withdrawals.py:create_withdrawal_request` (l.59-118) is **correctly atomic**: it locks the wallet row `FOR UPDATE`, refuses overdraft, INSERTs the `withdrawals` row, AND debits the ledger inside the same DB transaction. The debit IS the available-balance lock; the user's spendable USDC drops by `$9.00` instantly, as designed.
2. In auto-approval mode the row immediately moves to `status='approved'` and inline-fires `_settle_withdrawal` -> `_attempt_onchain_transfer`. In manual mode an admin must approve first.
3. `_attempt_onchain_transfer` (l.153-247) gates the actual ERC-20 send behind `EXECUTION_PATH_VALIDATED`. When `False` (default per `config.py:541`, and per LIVE_READINESS the production posture at lane time) it logs `withdrawal_onchain_deferred` and returns `None` — **silent no-op**. The row stays at `status='approved'`, `tx_hash IS NULL`, `submitted_at IS NULL`. The master hot pool still owns the USDC; nothing went on-chain.
4. The only web alert the existing code emits is `alert_kind='withdrawal_confirmed'`, fired strictly inside the `RETURNING user_id, id, amount_usdc, destination_address, tx_hash` block of `_attempt_onchain_transfer` (l.222-237). That code path is unreachable when the guard is off, so **the user is never told the withdrawal was queued**.
5. The WebTrader `/wallet/ledger` endpoint surfaces the debit but not the lifecycle status, so the activity feed renders the bare note `"withdrawal request to 0x5E5b93e4…"` with `-$9.00`, which a reasonable user reads as "the transfer was initiated."

Net effect: the owner's funds are safe (the `withdraw` ledger row is a reservation; reject → automatic refund via `T_ADJUSTMENT`; preflight failure → automatic refund via the same path), but the only honest signal that the transfer was even attempted lives in server logs.

A secondary (smaller-probability) scenario produces the same UX: the transfer was submitted but never confirmed on Polygon (`status='processing'`, `tx_hash` populated or NULL). Same visibility gap.

A tertiary scenario — destination mismatch (USDC.e on Polygon vs an address managed on Ethereum/Optimism/Arbitrum) — would show `status='completed'` with a real `tx_hash` but funds at an address the user does not control. The diagnostic query in §5 catches the first two; the third can be verified by reading the persisted `tx_hash` on the Polygon explorer.

## 2. What changed (minimal, per issue §scope: do not overbuild)

Four surgical changes; nothing in the live order path, risk gate, strategy, or activation guards was touched.

### `wallet/withdrawals.py`
- **New honest pending-state web alert** at request time (l.118-156). Fires once with `alert_kind='withdrawal_requested'`, dedup `withdrawal:<id>:requested`, severity `info`, copy that explicitly distinguishes reserve from send: *"Your $X USDC withdrawal to 0x…… is pending review. Funds are reserved; they will be sent on-chain once approved and confirmed. You will get a separate notification when the on-chain transfer confirms."* Wrapped in try/except so a future failure of the alert writer NEVER undoes the committed ledger debit.
- **New `find_stuck_withdrawals(older_than_hours, limit)`** read-only helper that returns rows in `('pending', 'approved', 'processing')` with `tx_hash IS NULL` older than the window. This is the operator queue the issue demands — it covers all three scenarios above except the destination-mismatch case (which has a real tx_hash and belongs in a different operator workflow).

### `webtrader/backend/router.py`
- **`/wallet/ledger` now LEFT JOINs `withdrawals`** on `l.ref_id = w.id` for `l.type='withdraw'` rows so the activity feed carries the lifecycle status and tx_hash through to the UI. The JOIN is a no-op for non-withdrawal rows; the API shape is backwards-compatible.

### `webtrader/backend/schemas.py`
- **`LedgerEntry` gains optional `withdrawal_status` + `withdrawal_tx_hash`** fields. Existing clients ignore them.

### `webtrader/frontend/src/pages/WalletPage.tsx` + `lib/api.ts`
- **`withdrawalBadge()` maps the raw status to honest user copy**:
  - `pending` → `"Pending approval"`
  - `approved` + no `tx_hash` → `"Queued"`  (the owner's exact case)
  - `approved` + `tx_hash` / `processing` → `"Sending"`
  - `completed` → `"Confirmed"`
  - `failed` → `"Failed (manual review)"`
  - `rejected` → `"Rejected (refunded)"`
- The badge is appended to the activity card's `meta` array so the user reads the status alongside the amount and date — no more bare-debit ambiguity.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/wallet/withdrawals.py` (pending-state alert + `find_stuck_withdrawals`)
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` (`/wallet/ledger` JOIN)
- `projects/polymarket/crusaderbot/webtrader/backend/schemas.py` (LedgerEntry fields)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` (LedgerEntry TS type)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/WalletPage.tsx` (badge + mapper)
- `projects/polymarket/crusaderbot/tests/test_withdrawal_lifecycle_visibility.py` (new — 13 behaviour/safety tests)
- `projects/polymarket/crusaderbot/reports/forge/withdrawal-request-debited-but-not-received-blocker.md` (this report)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `WORKTODO.md`, `CHANGELOG.md` (repo-truth sync)

No migration touched. No live-guard flag flipped. No historical ledger row mutated. No PII (real user id / full address) in repo / logs / fixtures.

## 4. Safety invariants pinned (and unchanged)

- **Atomic debit**: ledger debit + `INSERT INTO withdrawals` remain inside the same `conn.transaction()` block. The pending-alert is emitted AFTER the transaction commits — never inside it. Test: `test_ledger_debit_remains_atomic_with_withdrawal_insert`.
- **Overdraft guard**: wallet row is still `FOR UPDATE`-locked + insufficient balance raises pre-debit. Test: `test_overdraft_guard_remains_in_request`.
- **Preflight refund**: `PreflightError` still credits the ledger back via `T_ADJUSTMENT` (`_settle_withdrawal`). Test: `test_preflight_failure_still_refunds_ledger`.
- **Confirmed-alert gating (#1808)**: `withdrawal_confirmed` alert only fires inside the `status='completed'` RETURNING block, exactly once. Test: `test_confirmed_alert_still_gated_on_completion_only` + `test_two_distinct_dedup_namespaces_for_requested_and_confirmed`.
- **`find_stuck_withdrawals` is read-only**: source-pin proves no UPDATE / INSERT / DELETE / DROP / ALTER / TRUNCATE; behaviour-test proves a hermetic invocation runs exactly one SELECT. Test: `test_find_stuck_withdrawals_scopes_to_unsent_rows` + `test_find_stuck_withdrawals_executes_select_only`.
- **No real CLOB / Bridge / Relayer / Polygon call** from CI: tests patch the pool and the alert writer; no on-chain code paths reached. The hermeticity harness mirrors the test_clob_micro_live_preflight.py pattern.

## 5. Operator runbook — classify the owner withdrawal safely

Operator-only, read-only. None of these queries mutate state. Replace `:user_id` and `:wid` with the production values; redact addresses in any external sharing.

1. **Find the most recent withdrawal row for the owner**
   ```sql
   SELECT id, status, lifecycle_state, approval_mode, tx_hash, onchain_error,
          submitted_at, processed_at, confirmed_at, created_at
     FROM withdrawals
    WHERE user_id = :user_id
    ORDER BY created_at DESC
    LIMIT 1;
   ```
2. **Interpret**
   - `status='approved'` AND `tx_hash IS NULL` AND `submitted_at IS NULL` → **deferred by `EXECUTION_PATH_VALIDATED=False`** (PRIMARY ROOT CAUSE for #1819). The funds are safe in the master hot pool. To either (a) push it through, flip the guards per `projects/polymarket/crusaderbot/reports/forge/go-live-readiness.md` GO-LIVE RUNBOOK then re-call `_settle_withdrawal`; or (b) cancel it and refund the user via `reject_withdrawal(wid, admin_notes='guard off; owner-cancelled per #1819')` — the existing rejection path refunds the ledger automatically.
   - `status='processing'` AND `tx_hash IS NOT NULL` → check the Polygon explorer for that hash. If stuck in mempool, an operator can bump gas. If reverted (`status=0`), this is a post-broadcast failure: status moves to `failed`, no auto-refund, manual reconciliation.
   - `status='completed'` AND `tx_hash IS NOT NULL` → on-chain success. If the user still says funds did not arrive, the destination address is on a chain or wallet they do not control — verify via Polygon explorer + ask the user to confirm the address belongs to them.
3. **Find the broader queue** of deferred / stuck rows for the cohort:
   ```python
   from projects.polymarket.crusaderbot.wallet.withdrawals import find_stuck_withdrawals
   rows = await find_stuck_withdrawals(older_than_hours=24)
   ```

The issue explicitly forbids auto-retry of the owner withdrawal from test code — that decision belongs to the operator after the diagnosis above.

## 6. Validation evidence

- **New `tests/test_withdrawal_lifecycle_visibility.py` — 13 passed:**
  - request-time alert source pins (kind / dedup / honest copy / atomicity);
  - confirmed-alert gating (#1808) untouched;
  - distinct `:requested` vs `:completed` dedup namespaces;
  - hermetic create-request emits exactly one pending alert in manual mode with the right body, dedup, and metadata;
  - defense-in-depth: a raising alert writer never undoes the committed debit;
  - `find_stuck_withdrawals` scope + read-only + SELECT-only;
  - `/wallet/ledger` LEFT JOIN shape pinned in router source;
  - `LedgerEntry` schema carries `withdrawal_status` + `withdrawal_tx_hash` as optional fields;
  - WalletPage maps every status the issue lists to a user-honest badge.
- **Full suite**: `pytest projects/polymarket/crusaderbot/tests/` → **3690 passed, 15 skipped**.
- **Frontend**: `npm run build` (`tsc && vite build`) green.
- `ruff check` + `py_compile` clean on every touched file. Secret / mojibake / BOM scans clean.
- Branch verified exactly `WARP/withdrawal-request-debited-but-not-received-blocker`.

## 7. Safety invariant statement

No real fund movement. No on-chain call. No live-guard flip (`USE_REAL_CLOB` / `EXECUTION_PATH_VALIDATED` / `ENABLE_LIVE_TRADING` / `CAPITAL_MODE_CONFIRMED` / `RISK_CONTROLS_VALIDATED` / `SECURITY_HARDENING_VALIDATED` untouched). Kelly 0.25; `LIVE_MIN_ORDER_SHARES=5`; per-user balance isolation; $5 live Auto-Trade start gate; kill switch — all unchanged. No strategy / preset / risk constant / migration changed. No historical ledger / withdrawals row mutated. The owner's withdrawal row was NOT auto-retried, mutated, or refunded by this lane — that is the operator's decision per §5. No PII (full user id / full address) appears in any new code / test / report / commit.

## 8. What is next

WARP🔹CMD first-pass; merge under WARP•R00T final-gate on CI green. After merge, the operator runbook in §5 classifies the owner withdrawal and decides between (a) flip-guards-and-push-through or (b) reject-and-refund. The wider lane #1817 verification + #1814 go-live runbook remain the deployment path for the on-chain leg.

---

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: lifecycle visibility (pending notification + activity-feed badge + operator queue) for the deferred / stuck / processing withdrawal cases the owner hit.
Not in Scope: real fund movement, auto-retry of the owner withdrawal, live-guard flips, strategy/preset/risk/migration changes.
Suggested Next Step: WARP🔹CMD first-pass → R00T final-gate merge on CI green → operator executes §5 runbook for the owner withdrawal.
