# WARP•R00T FORGE REPORT — account-link-telegram

Branch: `WARP/ROOT/account-link-telegram`
Role: WARP•R00T (self-validated under WARP🔹CMD delegation)
Validation Tier: **MAJOR** (account identity / money-account merge)
Claim Level: **FULL RUNTIME INTEGRATION**
Validation Target: reverse Telegram-link so an email-first WebTrader user unifies into one account across both surfaces (one `user_id` → LIVE/PAPER + wallet + trades always in sync).
Not in Scope: merging Telegram accounts that already have trading history (deliberately BLOCKED → operator-assisted); deleting tombstoned rows (kept for traceability); changing the existing Telegram→email `link_email` direction.
Suggested Next Step: apply migration 065 to Supabase (additive), then WARP🔹CMD review + merge; optionally set `TELEGRAM_BOT_USERNAME` for the tap-to-open deep link.

---

## 1. What was built

Closed the account-unification gap surfaced after the live-activation lane: the
two surfaces share one account **only if** the same person is the same
`user_id`. Account linking was **one-directional** — Telegram→email worked
(`link_email`), but an **email-first** WebTrader user who later used the bot got
a **second, unsynced account**. This lane adds the reverse link.

Flow (one-time code):
1. Email user in WebTrader → Settings → **Link Telegram** → `POST /account/link-telegram/start` mints a short-lived one-time code.
2. User sends `/link <code>` to the bot.
3. `redeem_link_code()` attaches the Telegram identity to the canonical (email) account.

Duplicate handling (the user usually pressed `/start` first, creating a fresh
Telegram account):
- **Fresh duplicate** (paper, zero positions/orders/deposits/withdrawals): its
  `telegram_user_id` is moved to the canonical account and the duplicate is
  **tombstoned** (synthetic unreachable email + `merged_into` pointer) — NOT
  deleted, because several `users` FKs lack `ON DELETE CASCADE` (deletion is
  unsafe on this money schema). Non-destructive + traceable.
- **Duplicate with trading history / live mode**: **BLOCKED** with a clear
  message → operator-assisted merge, so no trades are ever silently orphaned.

## 2. Current system architecture

```
Email-first WebTrader account (canonical, holds the user's data)
   └─ POST /account/link-telegram/start  → one-time code (account_link_codes)
Telegram bot  /link <code>
   └─ domain/activation/account_link.redeem_link_code()
        ├─ no duplicate      → attach telegram_user_id to canonical  (OK_LINKED)
        ├─ fresh duplicate   → tombstone dup + reassign tg id        (OK_MERGED)
        └─ duplicate w/ hist → BLOCK (operator merge)                (TG_HAS_HISTORY)
```

After linking, `upsert_user(telegram_id)` resolves to the canonical account, so
both surfaces read/write the same `user_settings` row — LIVE/PAPER stays in sync
(realtime to WebTrader via the existing `cb_user_settings` SSE trigger).

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/migrations/065_account_link_telegram.sql` (users.merged_into + account_link_codes)
- `projects/polymarket/crusaderbot/domain/activation/account_link.py` (code mint + redeem/tombstone-merge)
- `projects/polymarket/crusaderbot/bot/handlers/account_link.py` (`/link` handler)
- `projects/polymarket/crusaderbot/tests/test_account_link.py` (15 tests)
- `projects/polymarket/crusaderbot/reports/forge/account-link-telegram.md`

Modified:
- `projects/polymarket/crusaderbot/bot/dispatcher.py` (import + register `/link`)
- `projects/polymarket/crusaderbot/config.py` (optional `TELEGRAM_BOT_USERNAME`)
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` (`/account/link-telegram/{status,start}`)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` (link methods + type)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/SettingsPage.tsx` ("Link Telegram" control)

## 4. What is working

- Email-first user can mint a code in WebTrader and link Telegram via `/link`.
- Fresh-duplicate absorb (tombstone + reassign) and history-block paths covered.
- `/link` with no args shows usage; rate-limited mint (5/min per user).
- Full suite **2005 passed / 0 failed** (+15 tests); ruff + py_compile clean; tsc + vite build clean.

## 5. Known issues

- **Migration 065 must be applied to Supabase** (additive; `users.merged_into` + `account_link_codes`) before the feature works in production. Not auto-applied.
- WebTrader "Link Telegram" page refreshes link state on the 30s poll (not instant) — the `users` table has no SSE NOTIFY trigger; acceptable.
- History-conflict merges are intentionally manual (operator) — no self-serve merge of accounts with trades yet.
- `TELEGRAM_BOT_USERNAME` unset → UI shows the `/link` command without a tap-to-open deep link (still fully usable).

## 6. What is next

Apply migration 065 → WARP🔹CMD review + merge → Fly auto-deploy. Optional: set
`TELEGRAM_BOT_USERNAME` secret for the deep link; design a self-serve
history-merge flow if demand warrants.
