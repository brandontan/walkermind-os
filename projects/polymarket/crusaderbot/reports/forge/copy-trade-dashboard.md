# WARP•FORGE Report — Copy Trade Dashboard (Phase 5E)

Branch: WARP/CRUSADERBOT-PHASE5E-COPY-TRADE
Date: 2026-05-10 09:30 Asia/Jakarta

---

## 1. What Was Built

Phase 5E Copy Trade surface: full dashboard, two-path wallet discovery, wallet stats
service, and DB migration. Replaces the Phase 5D placeholder handler with a functional
UI connected to real DB state and Polymarket Gamma API.

- **Dashboard:** Shows empty state ("No wallets followed yet") or task list with per-task
  status badge, name, wallet (truncated), copy amount, and [Pause/Resume][Edit] 2-col buttons.
  Total copy PnL row rendered at the bottom. PnL/positions fields show "—" until Phase 5F
  execution wiring.

- **Add Wallet — Path A (Paste):** [Paste Address] button sets `ctx.user_data['awaiting']
  = 'copytrade_paste'`. `text_input()` in dispatcher validates the address, fetches stats
  from Polymarket Gamma API, and shows the wallet stats card with [Copy This Wallet][Back].

- **Add Wallet — Path B (Discover):** [Discover] button fetches top 10 wallets by 30d PnL
  from `GET /leaderboard`. Six filter buttons (2-col): Crypto, Sports, Politics, World,
  Top PnL, Top WR. Match score hardcoded to 0% per spec.

- **Wallet Stats Service:** `services/copy_trade/wallet_stats.py` — async fetch from
  Polymarket Gamma API, 5-min in-memory TTL cache, graceful `available=False` on any
  API failure. Used by both paste and discover flows.

- **DB Migration:** `017_copy_trade_tasks.sql` — `copy_trade_tasks` table with all
  specified columns. Idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`).

- **Dispatcher:** `text_input` wired into `_text_router` between `activation.text_input`
  and `setup.text_input` so the paste-address awaiting flow is consumed before the
  legacy setup flow sees the message.

---

## 2. Current System Architecture (Relevant Slice)

```
🐋 Copy Trade (menu button)
    └── menu_copytrade_handler()
            ├── [no tasks]  → empty state + copy_trade_empty_kb()
            └── [has tasks] → task list text + copy_trade_task_list_kb()

copytrade: callbacks → copy_trade_callback()
    ├── copytrade:dashboard     → re-render dashboard
    ├── copytrade:add           → show add wallet screen
    ├── copytrade:paste         → set awaiting + show prompt
    ├── copytrade:discover[:<f>]→ leaderboard via fetch_top_wallets(category)
    ├── copytrade:stats:<addr>  → wallet stats card via fetch_wallet_stats()
    ├── copytrade:copy:<addr>   → Phase 5F placeholder (alert)
    ├── copytrade:pause:<id>    → toggle pause/active in copy_trade_tasks
    ├── copytrade:edit:<id>     → Phase 5F placeholder (alert)
    └── copytrade:remove:<addr> → legacy copy_targets deactivate

text_input() [awaiting=copytrade_paste]
    └── validate → fetch_wallet_stats() → show stats card

wallet_stats.py
    ├── fetch_wallet_stats(address)  → GET /profiles/{address} + 5-min cache
    └── fetch_top_wallets(category)  → GET /leaderboard + params

copy_trade_tasks (DB table, migration 017)
    └── queried by: _list_copy_tasks() / _toggle_task_pause()
```

---

## 3. Files Created / Modified

**New files:**
- `projects/polymarket/crusaderbot/domain/copy_trade/__init__.py`
- `projects/polymarket/crusaderbot/domain/copy_trade/models.py`
- `projects/polymarket/crusaderbot/services/copy_trade/wallet_stats.py`
- `projects/polymarket/crusaderbot/migrations/017_copy_trade_tasks.sql`
- `projects/polymarket/crusaderbot/reports/forge/copy-trade-dashboard.md`

**Rewritten files:**
- `projects/polymarket/crusaderbot/bot/keyboards/copy_trade.py`
- `projects/polymarket/crusaderbot/bot/handlers/copy_trade.py`

**Modified files:**
- `projects/polymarket/crusaderbot/bot/dispatcher.py`
  (added `copy_trade.text_input` call in `_text_router`)

---

## 4. What Is Working

- `menu_copytrade_handler` renders dashboard with empty-state or task-list text.
- All `copytrade:` callbacks route correctly through the expanded `copy_trade_callback`.
- `text_input` detects `copytrade_paste` awaiting, validates address format, fetches
  stats, and renders the wallet stats card.
- Wallet stats service fetches from Gamma API with 5-min TTL cache and graceful
  `available=False` fallback — no blocking on API errors.
- Leaderboard renders with filter toggle buttons (2-col grid via `discover_filter_kb`).
- DB migration is idempotent (CREATE IF NOT EXISTS on both table and index).
- `CopyTradeTask` dataclass is full-typed with `status_badge` property.
- All new files pass `python -m py_compile`.
- Existing `copytrade:remove:<addr>` (legacy copy_targets) preserved in callback handler.
- All buttons use `grid_rows()` helper for 2-column layout per spec.

---

## 5. Known Issues

- `fetch_top_wallets` and `fetch_wallet_stats` depend on Polymarket Gamma API endpoints
  (`/leaderboard`, `/profiles/{address}`) whose exact response schema is documented in
  the KNOWLEDGE_BASE but may drift — `_parse()` uses defensive field lookups with both
  camelCase and snake_case keys to cover likely response shapes.
- "Your PnL", "Trader 30d PnL", and "active positions" on the task list card show "—"
  until Phase 5F execution wiring is complete. This is per spec.
- `copytrade:copy:<addr>` and `copytrade:edit:<task_id>` show Phase 5F placeholder alert.
  Setup wizard is out of scope for this lane.

---

## 6. What Is Next

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : Dashboard render (empty + task list), paste-address flow, discover
                    leaderboard, wallet stats card, DB migration idempotency, callback routing.
Not in Scope      : Phase 5F copy task setup wizard, per-task edit wizard, execution
                    engine integration, live PnL data, any live-trading guard changes.
Suggested Next    : WARP•SENTINEL MAJOR audit before merge.

```
NEXT PRIORITY (PROJECT_STATE.md):
WARP•SENTINEL validation required for Phase 5E Copy Trade dashboard before merge.
Source: projects/polymarket/crusaderbot/reports/forge/copy-trade-dashboard.md
Tier: MAJOR
```
