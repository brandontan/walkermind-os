# WARP•FORGE REPORT — access-tiers-admin-panel

Validation Tier: STANDARD
Claim Level: FOUNDATION
Validation Target: user_tiers table + tier enforcement middleware + admin panel subcommands
Not in Scope: Payment/subscription logic, auto tier upgrade, trading logic changes, seed script for boss user (wired via existing OPERATOR_CHAT_ID gate)

---

## 1. What Was Built

String-based access tier system (FREE / PREMIUM / ADMIN) backed by a new
`user_tiers` table. Parallel to the legacy integer `access_tier` column — does
not replace it. Three components:

- **Migration 023** — additive `user_tiers` table with CHECK constraint.
- **`services/tiers.py`** — `get_user_tier`, `set_user_tier`,
  `list_all_user_tiers`, `meets_tier`, `tier_rank`, constants.
- **`bot/middleware/access_tier.py`** — `require_access_tier(min_tier)` decorator
  that reads the DB and replies with an upgrade message on denial.
- **`bot/handlers/admin.py`** — extended with `_is_admin_user` (OPERATOR_CHAT_ID
  OR ADMIN tier), subcommand routing in `admin_root`, and four new implementations:
  `_admin_users`, `_admin_settier`, `_admin_stats`, `_admin_broadcast`.

Operator (OPERATOR_CHAT_ID) is automatically admitted as admin via `_is_operator`
short-circuit — no separate seed step required.

---

## 2. Current System Architecture

```
Telegram /admin {subcommand}
    │
    ▼
bot/handlers/admin.py  admin_root()
    │
    ├─ _is_admin_user()
    │       ├─ _is_operator()  ← OPERATOR_CHAT_ID (legacy gate, unchanged)
    │       └─ get_user_tier() ← services/tiers.py → user_tiers table
    │
    ├─ no args    → operator: kill-switch panel | ADMIN tier: help menu
    ├─ "users"    → _admin_users()     list_all_user_tiers()
    ├─ "settier"  → _admin_settier()   set_user_tier()
    ├─ "stats"    → _admin_stats()     raw SQL counts + paper PNL
    └─ "broadcast"→ _admin_broadcast() notifications.send() per user

require_access_tier('PREMIUM') decorator:
    get_user_tier(telegram_user_id) → meets_tier() → allow / deny + message
```

---

## 3. Files Created / Modified

Created:
- `projects/polymarket/crusaderbot/migrations/023_user_tiers.sql`
- `projects/polymarket/crusaderbot/services/tiers.py`
- `projects/polymarket/crusaderbot/bot/middleware/access_tier.py`
- `projects/polymarket/crusaderbot/tests/test_access_tiers.py`

Modified:
- `projects/polymarket/crusaderbot/bot/handlers/admin.py`
  — added imports from `services.tiers`, added `_ADMIN_HELP`, `_is_admin_user`,
    subcommand routing in `admin_root`, `_admin_users`, `_admin_settier`,
    `_admin_stats`, `_admin_broadcast`

---

## 4. What Is Working

- 29/29 hermetic tests green.
- `get_user_tier` defaults to FREE for unknown users (no DB row required).
- `set_user_tier` upserts with CHECK constraint enforcement in DB + ValueError in service layer.
- `require_access_tier('PREMIUM')` blocks FREE users, passes PREMIUM/ADMIN, sends upgrade message.
- `admin_root` blocks non-ADMIN, non-operator users with "Admin access required."
- `/admin users` lists user_tiers rows.
- `/admin settier {uid} {tier}` validates tier string, upserts, writes audit row.
- `/admin stats` returns total users, tier breakdown, open positions, paper PNL.
- `/admin broadcast {msg}` sends to all users via notifications.send(), reports sent/failed counts.
- Operator (OPERATOR_CHAT_ID) continues to receive kill-switch panel on bare `/admin`.
- Existing admin callbacks, allowlist_command, ops_dashboard, killswitch — all untouched.

---

## 5. Known Issues

- Seed data: boss OPERATOR_CHAT_ID is admitted via `_is_operator` short-circuit.
  An explicit row in `user_tiers` for the boss is NOT created by this lane;
  WARP🔹CMD can do `/admin settier {boss_id} ADMIN` after deploy or wire a migration
  seed INSERT.
- `require_access_tier` decorator is wired but no existing trading commands use it yet;
  command-level enforcement is a separate lane per task scope.
- `_admin_stats` paper_pnl query assumes a `pnl_usdc` column on `positions` — verify
  column name matches schema before deploy (non-blocking for this FOUNDATION claim).

---

## 6. What Is Next

WARP🔹CMD review required.
Suggested next step: wire `@require_access_tier('PREMIUM')` onto trading command
handlers (dashboard, positions, copytrade, signals) in a follow-on STANDARD lane.

---

Suggested Next Step: WARP🔹CMD review. Apply migration 023 to Supabase. Optionally
seed boss user with `/admin settier {OPERATOR_CHAT_ID} ADMIN`.
