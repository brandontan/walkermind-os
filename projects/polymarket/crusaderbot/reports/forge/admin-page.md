# WARP•R00T FORGE REPORT — admin-page

Branch: `WARP/ROOT/admin-page`
Role: WARP•R00T (owner-requested)
Validation Tier: **MAJOR** (adds a global strategy on/off gate into the live scanner)
Claim Level: FULL RUNTIME INTEGRATION
Validation Target: WebTrader Admin console (Overview + Users + Strategy on/off) for role='admin'; global strategy toggle wired fail-safe into the scanner.
Not in Scope: per-user admin actions (ban/credit/force-mode) — view-only roster for now; Telegram-side admin parity.
Suggested Next Step: migration 067 applied to Supabase already → WARP🔹CMD review + merge → Fly deploy.

---

## 1. What was built

A full **WebTrader Admin console** (`/admin`, role='admin' only) so the operator
can run the bot from their phone:

- **Overview**: master hot-pool **address + on-chain USDC/MATIC balance** (the
  funding target for go-live), 6 live activation guards state, kill-switch
  state, and system counts (users / auto-trade-on / live users / admins /
  open positions paper+live / total wallet USDC) + last scan summary.
- **Strategies — global on/off**: toggle any of the 12 strategies system-wide.
- **Users**: roster table (username/email, role, mode, balance, auto/paused,
  open positions, preset).

Strategy on/off is wired into the live scanner **fail-safe**: a strategy runs
UNLESS a `strategies` row marks it `enabled=FALSE`. Two gate points: the shared
`_preset_allows()` gatekeeper (lib + domain strategies, via a per-tick-refreshed
cache) and the `signal_following` loader query (`NOT EXISTS` on the table). A DB
error never changes the set → no silent enable/disable.

## 2. Current system architecture

```
WebTrader (role=admin) → GET /api/web/admin/{overview,users,strategies}
                       → POST /api/web/admin/strategies/toggle
  guard: _require_admin (users.role='admin' → else 403)

strategy toggle → strategies table (migration 067, deny-by-default RLS)
  scanner consults:
    • signal_scan_job._preset_allows()  ← _GLOBALLY_DISABLED_STRATEGIES cache
      (refreshed once per tick via _refresh_disabled_strategies)
    • signal_following loader query: AND NOT EXISTS (strategies disabled)
  FAIL-SAFE: missing row / DB error = strategy ON (no behaviour change)
```

`/me` now returns `role` + `is_admin` so the UI shows the "🛡 Open Ops Console"
entry (Settings) only to admins.

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/migrations/067_strategies_global_toggle.sql` (strategies table + seed + RLS) — APPLIED to Supabase.
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AdminPage.tsx`
- `projects/polymarket/crusaderbot/tests/test_admin_console.py` (11 tests)
- `projects/polymarket/crusaderbot/reports/forge/admin-page.md`

Modified:
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` (global disable cache + refresh + `_preset_allows` gate + signal_following loader gate)
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` (/me role; `_require_admin`; /admin/overview, /admin/users, /admin/strategies, /admin/strategies/toggle)
- `projects/polymarket/crusaderbot/webtrader/backend/schemas.py` (StrategyToggleRequest)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` (admin types + methods; MeResponse role/is_admin)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/SettingsPage.tsx` (admin Ops-Console entry)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/App.tsx` (/admin route)
- `projects/polymarket/crusaderbot/tests/test_account_link.py` (get_me fakes +role)

## 4. What is working

- Admin-only endpoints (403 for non-admin); admin sees Overview/Users/Strategies.
- Strategy toggle persists + gates the scanner next tick; fail-safe verified by test.
- Migration 067 applied to Supabase (12 seeded, all ON, RLS on, advisor clean).
- Full suite **2018/2018 pass**; ruff + py_compile clean; tsc + vite build clean.

## 5. Known issues

- Admin nav entry lives in Settings ("🛡 Open Ops Console"); not added to the 5-slot mobile BottomNav (kept uncluttered). Desktop sidebar entry could be added later.
- Strategy toggle is global (all users). Per-user strategy control not exposed.
- Users roster is view-only (no admin mutations yet).

## 6. What is next

WARP🔹CMD review + merge → Fly deploy. Set a user to admin via Telegram
`/allowlist` (set_role 'admin') so they see the Ops Console.
