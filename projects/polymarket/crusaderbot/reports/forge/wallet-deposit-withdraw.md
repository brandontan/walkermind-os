# WARP•FORGE — Wallet Deposit Polish + Withdraw Flow

**Branch:** WARP/R00T-wallet-deposit-withdraw
**Date:** 2026-05-26 19:30 WIB
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION

---

## 1. What was built

Complete deposit UX improvement and a paper-only withdraw flow with master hot pool
+ admin approval architecture. No on-chain transfer is implemented (paper mode);
the full request/approval/ledger/notification infrastructure is in place and ready
for live activation when EXECUTION_PATH_VALIDATED is flipped.

**Deposit improvements:**
- New dedicated deposit screen (`wallet:deposit` callback) showing step-by-step
  Polygon USDC instructions, full deposit address (copyable), current balance, and
  network warning (Polygon only, no exchange).
- `wallet_deposit_text()` message + `wallet_deposit_kb()` keyboard (Copy + Refresh + Back).

**Withdraw flow (paper mode, full request/approval path):**
- `wallet/withdrawals.py` — DB layer: `create_withdrawal_request`, `get_pending_withdrawals`,
  `get_user_withdrawals`, `approve_withdrawal` (status update), `reject_withdrawal`
  (status update + ledger refund credit).
- Ledger debit is atomic with the withdrawal row INSERT in a single transaction.
  Reject refunds via `credit_in_conn(T_ADJUSTMENT)` in the same transaction.
- `get_approval_mode` / `set_approval_mode` — read/write `system_settings` key
  `withdrawal_approval_mode` (default: `'manual'`).
- Telegram UX: amount input → Polygon address input → confirmation screen →
  submit (debit ledger) → operator notification if manual mode.
- Withdraw text state stored in `ctx.user_data["_wd"]`; no ConversationHandler
  dependency — cleared on confirm or cancel.
- `wallet_callback_history` — shows last 8 withdrawals with status icons.

**Admin approval panel (`/admin withdrawals`):**
- Lists all pending withdrawal requests with user info and amount.
- Per-item ✅ Approve / ❌ Reject buttons; rejection triggers automatic ledger refund.
- AUTO/MANUAL toggle stored in `system_settings.withdrawal_approval_mode`.
- Operator notified on new manual-mode withdrawal request; user notified on approve/reject.

## 2. Current system architecture

```
User: 📤 Withdraw → wallet:withdraw callback
  → _start_withdraw(): check balance ≥ MIN ($5) → set _wd draft
  → handle_withdraw_text(): amount → address → confirm screen
  → wallet:withdraw_confirm:{amount}:{addr} callback
  → create_withdrawal_request()
      ├── INSERT withdrawals (status=pending|approved)
      └── debit_in_conn(T_WITHDRAW) — atomic transaction
  → withdraw_submitted_text (auto-approved or pending)
  → [manual mode] notify_operator()

Admin: /admin withdrawals → _admin_withdrawals_text
  → admin_withdrawals_kb (pending count)
  → admin:withdrawals:list → get_pending_withdrawals → per-item approve/reject KB
  → admin:withdrawals:approve:{uuid} → approve_withdrawal (status=approved)
  → admin:withdrawals:reject:{uuid}  → reject_withdrawal (status=rejected)
      └── credit_in_conn(T_ADJUSTMENT) — refund, atomic

Admin: admin:withdrawals:mode → admin_approval_mode_kb
  → admin:withdrawals:set_mode:auto|manual → set_approval_mode
```

## 3. Files created / modified

- Created: `projects/polymarket/crusaderbot/migrations/057_withdrawals.sql`
- Created: `projects/polymarket/crusaderbot/wallet/withdrawals.py`
- Modified: `projects/polymarket/crusaderbot/bot/keyboards/wallet.py`
  (added: wallet_deposit_kb, withdraw_cancel_kb, withdraw_confirm_kb, withdraw_history_kb,
   admin_withdrawals_kb, admin_approval_mode_kb, admin_approve_reject_kb)
- Modified: `projects/polymarket/crusaderbot/bot/messages.py`
  (added: wallet_deposit_text, withdraw_ask_amount_text, withdraw_ask_address_text,
   withdraw_confirm_text, withdraw_submitted_text, withdraw_history_text,
   admin_withdrawal_item_text)
- Modified: `projects/polymarket/crusaderbot/bot/handlers/wallet.py`
  (full rewrite: deposit screen, withdraw state machine, history screen)
- Modified: `projects/polymarket/crusaderbot/bot/handlers/admin.py`
  (added: _admin_withdrawals_text, _admin_withdrawals_callback, BadRequest import,
   /admin withdrawals sub-command routing)
- Modified: `projects/polymarket/crusaderbot/bot/dispatcher.py`
  (import handle_withdraw_text; wire into _text_router)
- Created: `projects/polymarket/crusaderbot/tests/test_wallet_withdraw_flow.py` (18 tests)
- Modified: `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- Modified: `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- 18 new hermetic tests pass (message text, address regex, approval mode validation,
  keyboard callback data format, history rendering, admin item rendering)
- Full suite: 1792 passed, 1 skipped
- ruff clean on all modified files
- Ledger atomicity: withdrawal row + debit in one transaction; refund on rejection
  in one transaction — no partial states possible
- AUTO mode: request immediately gets status='approved', no admin action required
- MANUAL mode: request gets status='pending', operator Telegram notification sent
- Address validation: strict 0x + 40 hex chars regex; rejects exchange addresses

## 5. Known issues

- On-chain transfer not implemented (paper only) — `completed` status requires
  live activation (EXECUTION_PATH_VALIDATED guard + on-chain signing logic)
- Migration 057 must be applied to the Supabase DB before deploy
- Operator Telegram notification on new withdrawal requires the bot to be running
  (notification is best-effort, failure is logged but not fatal)
- `_admin_withdrawals_callback` "withdrawals" panel home uses `edit_text` + BadRequest
  fallback; if message has no editable content the fallback `reply_text` fires

## 6. What is next

- Apply migration 057 to Supabase: `fly deploy` will not auto-run migrations;
  apply via Supabase dashboard SQL editor or MCP tool
- WARP🔹CMD review + merge + deploy
- Post-deploy: test withdraw flow end-to-end in paper mode, verify operator
  notification, verify admin approve/reject + refund
- Future: add on-chain signing to `approve_withdrawal` behind EXECUTION_PATH_VALIDATED
  guard for live withdrawal activation

---

**Validation Target:** Wallet deposit UX + paper withdraw flow + admin approval
**Not in Scope:** On-chain USDC transfer, live withdrawal signing, multi-sig
**Suggested Next Step:** WARP🔹CMD review + merge; apply migration 057; fly deploy
