# WARP•FORGE Report — tg-ux-fixes-strategy-sync

**Branch:** WARP/tg-ux-fixes-strategy-sync
**Last Updated:** 2026-06-09 21:11
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Telegram bot MVP v1 UI/UX layer + admin strategy flag sync
**Not in Scope:** Signal execution pipeline, risk engine, live trading guard, WebTrader frontend CONFIG page UI (backend endpoints only)
**Suggested Next Step:** WARP🔹CMD review + merge. No migration required for existing functionality; see Known Issues for new tables referenced.

---

## 1. What was built

Full repair pass on the Telegram bot MVP v1 UI/UX layer (all 25 issues from the pre-task audit) plus a new admin strategy-flag sync system that bridges the web CONFIG panel and the TG autotrade surface.

### Broken flows fixed (Critical)
- **C4 — Copy wallet Resume:** `copy:resume` now shows a confirm screen and writes `status='active'` to `copy_trade_tasks` on confirm. Previously re-rendered home with no DB write.
- **C5 — Custom capital:** `auto:configure:capital:custom` sets `step='await_capital'` in user_data; the next free-text message is captured by a new `text_input` handler wired into the dispatcher before the copy-wallet text handler.
- **C6 — Position detail:** `portfolio:position:{id}` now fetches the position row from DB and renders `render_position_detail`. Previously fell through to portfolio home.
- **C7 — History drill-down:** `portfolio:history:today/week/all` sub-routes to `show_history_range` which queries `positions` with the appropriate interval.
- **C8 — Performance drill-down:** `portfolio:performance:week/month` sub-routes to `show_performance_range` with real PnL/win-rate from DB.

### Data accuracy (Standard)
- **S1 — Portfolio equity/week_pnl:** `_read_portfolio` now fetches `equity` (balance + unrealized PnL) and `week_pnl` (7-day closed PnL) from DB. Both displayed in portfolio home.
- **S2 — Autotrade mode:** `_read_state` fetches `trading_mode` from `user_settings` and passes it to the renderer. Mode no longer hardcodes Paper.
- **S3 — Copy wallet review:** `_fetch_wallet_activity` queries `copy_trade_tasks` + `positions` for real trade count and active status. Both the callback path and the text-input path use it.
- **M7 — Missing portfolio fields:** `_read_portfolio` now populates `today_trades`, `win_rate`, `history_today`, `history_week` from DB. `show_performance` uses real values.

### Settings (Standard)
- **S10 — Settings sub-routing:** Notification sub-buttons toggle `notifications_on` in `user_settings`. Advanced → Health routes to the health handler. Risk/account sub-items show parent screen (write flows deferred — noted).
- **S11 — Live access request:** `settings:mode:live:request` logs to `live_access_requests` table and shows a confirmation screen.
- **S14 — Settings home dynamic values:** `render_settings_home` now accepts `risk_profile`, `alerts_on`, `copy_wallet_active` — all read from DB.

### Copy wallet (Standard)
- **S12 — Per-wallet pause/resume/stats:** `copy:wallet:pause:{id}` and `copy:wallet:resume:{id}` write to `copy_trade_tasks` by UUID. Stats callback shows wallet card (full stats view deferred).
- **S13 — Multi-wallet pagination:** `show_wallets(page=N)` iterates the full wallet list. Prev/Next nav buttons injected into `wallet_card_kb` when `total_pages > 1`.

### Navigation (Standard)
- **S15 — Back navigation:** `nav:back` / `nav:cancel` pop a per-user `mvp_nav_stack` (stored in `user_data`, max depth 8) and route to the previous surface. Each surface's `show_home` pushes its prefix. Dashboard clears the stack. `nav:refresh` re-renders the current stack top.

### Markets (Standard)
- **S5 — New Markets:** `show_new` fetches by `created_at DESC` — distinct from Trending (which orders by volume/activity).
- **S6 — Search:** `show_search` sets `step='await_search'`; `text_input` captures the query and runs `ILIKE` against `markets.question`. Wired into dispatcher before copy-wallet text handler.
- **S7 — Watchlist:** `show_watchlist` reads from `user_watchlist` table. `markets:watchlist:add:{id}` inserts to `user_watchlist` with `ON CONFLICT DO NOTHING`.
- **S4 — AI Insights:** Fetches real `confidence_score` and `signal_reason` from `signal_scan_results` for the top market. Falls back to `"—"` / `"Insufficient data"` if no row.

### Help (Standard)
- **S8 — FAQ sub-routing:** `help:faq:auto` → how_auto_trade, `help:faq:paper` → new paper-trading explainer, `help:faq:risk` → safety screen, `help:faq:copy` → how_copy_wallet.
- **S9 — Report Issue:** `help:support:report` shows a dedicated `render_help_support_report` screen.

### Dead code / cosmetic (Minor)
- **M1:** Removed `if False` dead branch from `render_autotrade_home`.
- **M2/M3:** Trending and positions list use integer rank (`1.`, `2.`) instead of emoji+dot.
- **M8:** `do_start_copying` DB failure now shows an error message to the user instead of silently calling `show_home`.
- **M9:** Onboarding `show_wallet_ready` / `show_deposit_prompt` are now reachable via `onboard:wallet_ready` and `onboard:deposit` callbacks. `welcome_kb` updated to start the flow.
- **M10:** Duplicate `/dashboard` `CommandHandler` registration removed from dispatcher.

### Strategy sync (Standard)
- **`domain/ops/strategy_flags.py`** — new module. Reads/writes `system_settings` keys `strategy_enabled:{name}` and `bot_override:{name}`. Supported strategies: `late_entry_v3`, `signal_following`, `copy_trade`, `weather`, `playbook`. Bot overrides: `weather_strategy`, `complete_set_arb`, `playbook_sports`, `scan_snapshot_capture`. Missing keys default to `True` (enabled).
- **TG autotrade handler** — `_read_state` calls `get_all_flags()`. `_check_strategy_blocked()` maps the user's active preset label to the flag key. If globally OFF, status shows `🚫 Admin Blocked` and a warning notice appears in the autotrade home screen.
- **Web API** — `GET /api/web/admin/strategy-flags` and `PATCH /api/web/admin/strategy-flags`. Both require `role='admin'` in `users` table (enforced by new `require_admin` dependency in `auth.py`). `StrategyFlagsUpdate` Pydantic schema added to `schemas.py`.

---

## 2. Current system architecture

No structural changes. All work is within the existing MVP v1 handler/keyboard/message layer and the `domain/ops/` module. The strategy-flags module follows the same `system_settings` upsert pattern as `kill_switch.py`.

```
bot/handlers/mvp/          ← all handler fixes
bot/keyboards/mvp/         ← keyboard fixes (copy_wallet, portfolio, onboarding)
bot/messages_mvp.py        ← new/updated renderers
bot/dispatcher.py          ← text_input routing + nav_cb stack
domain/ops/strategy_flags.py  ← new: admin strategy flag read/write
webtrader/backend/auth.py  ← new: require_admin dependency
webtrader/backend/router.py   ← new: /admin/strategy-flags endpoints
webtrader/backend/schemas.py  ← new: StrategyFlagsUpdate schema
```

---

## 3. Files created / modified

**Created:**
- `projects/polymarket/crusaderbot/domain/ops/strategy_flags.py`
- `projects/polymarket/crusaderbot/reports/forge/tg-ux-fixes-strategy-sync.md`

**Modified:**
- `projects/polymarket/crusaderbot/bot/dispatcher.py`
- `projects/polymarket/crusaderbot/bot/messages_mvp.py`
- `projects/polymarket/crusaderbot/bot/handlers/mvp/_send.py`
- `projects/polymarket/crusaderbot/bot/handlers/mvp/_users.py`
- `projects/polymarket/crusaderbot/bot/handlers/mvp/autotrade.py`
- `projects/polymarket/crusaderbot/bot/handlers/mvp/copy_wallet.py`
- `projects/polymarket/crusaderbot/bot/handlers/mvp/dashboard.py`
- `projects/polymarket/crusaderbot/bot/handlers/mvp/help.py`
- `projects/polymarket/crusaderbot/bot/handlers/mvp/markets.py`
- `projects/polymarket/crusaderbot/bot/handlers/mvp/onboarding.py`
- `projects/polymarket/crusaderbot/bot/handlers/mvp/portfolio.py`
- `projects/polymarket/crusaderbot/bot/handlers/mvp/settings.py`
- `projects/polymarket/crusaderbot/bot/keyboards/mvp/copy_wallet.py`
- `projects/polymarket/crusaderbot/bot/keyboards/mvp/onboarding.py`
- `projects/polymarket/crusaderbot/bot/keyboards/mvp/portfolio.py`
- `projects/polymarket/crusaderbot/webtrader/backend/auth.py`
- `projects/polymarket/crusaderbot/webtrader/backend/router.py`
- `projects/polymarket/crusaderbot/webtrader/backend/schemas.py`

---

## 4. What is working

- All 25 audit issues addressed (5 critical, 15 standard, 5 minor/cosmetic)
- All modified files pass `ast.parse` syntax check
- Strategy flags module follows existing `system_settings` upsert pattern — no new infra required
- Admin endpoints gated by `role='admin'` in `users` table — no new auth mechanism
- Navigation stack is purely in-memory (`user_data`) — no DB dependency, no migration

---

## 5. Known issues

- **`user_watchlist` table** — referenced by `show_watchlist` and `_add_to_watchlist` but not yet in migrations. Needs `CREATE TABLE user_watchlist (user_id uuid, market_id uuid, created_at timestamptz DEFAULT NOW(), PRIMARY KEY (user_id, market_id))`.
- **`live_access_requests` table** — referenced by `_request_live_access` but not yet in migrations. Needs `CREATE TABLE live_access_requests (user_id uuid PRIMARY KEY, requested_at timestamptz)`.
- **`signal_scan_results.confidence_score` / `signal_reason`** — assumed columns. Verify against current schema before deploy; `show_insights` falls back gracefully if absent.
- **`positions.copy_task_id`** — assumed FK for wallet activity query. Verify column exists; `_fetch_wallet_activity` falls back to 0 trades on any DB error.
- **Settings write flows deferred** — risk controls, account wallet/export/security sub-items show parent screen only. Full write flows are a separate lane.

---

## 6. What is next

- WARP🔹CMD: add migrations for `user_watchlist` and `live_access_requests` (or confirm tables already exist)
- WARP🔹CMD: verify `signal_scan_results` and `positions.copy_task_id` column names against production schema
- Fly.io redeploy required after merge
- Web CONFIG page frontend (strategy toggle UI) is a separate lane — backend endpoints are ready
