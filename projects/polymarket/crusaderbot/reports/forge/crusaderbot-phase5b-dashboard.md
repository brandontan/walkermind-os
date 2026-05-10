# WARP•FORGE REPORT — crusaderbot-phase5b-dashboard

Validation Tier: STANDARD
Claim Level: Dashboard display redesign — presentation only
Validation Target: Dashboard handler, keyboard helper, dispatcher wiring, /start routing
Not in Scope: Trading logic, risk gate, execution, database schema, onboarding flow (5E), preset system (5C), activation guards
Suggested Next Step: WARP🔹CMD review — Tier STANDARD, no SENTINEL required

---

## 1. What Was Built

Replaced the flat single-line dashboard with a rich single-message hierarchy model
using section headers and tree-indent characters (├─ └─). The new dashboard surfaces
four sections — Portfolio, Profit & Loss, Trading Stats, and Auto-Trade — in one
clean message.

- `dashboard()` handler rewritten with hierarchy text + bottom navigation buttons.
- `_fetch_stats()` fetches supplementary data (positions value, win/loss counts,
  multi-period PnL, trading stats, user settings) in a single DB connection.
- `_build_text()` assembles the hierarchy string from live data.
- `_pnl_line()` formats P&L values with sign and optional percent-of-balance.
- Empty state: users with no trades or positions see $0.00 values and a
  [🤖 Get Started] button.
- `dashboard_nav_cb()` handles [🤖 Auto-Trade] [📈 Trades] [💰 Wallet] inline buttons.
- `dashboard_nav()` keyboard added to `bot/keyboards/__init__.py`.
- `dispatcher.py` registers `dashboard:*` callback pattern → `dashboard_nav_cb`.
- `/start` for existing allowlisted users now routes to the dashboard instead of
  re-showing the onboarding welcome. New users and Tier 1 users still see onboarding.

Branch note: session harness assigned `claude/dashboard-hierarchy-redesign-TwPJB`;
declared WARP branch is `WARP/CRUSADERBOT-PHASE5B-DASHBOARD`. Mismatch noted —
WARP🔹CMD to resolve branch posture at review.

---

## 2. Current System Architecture

```
Telegram /start or 📊 Dashboard button
  │
  ├─ onboarding.start_handler
  │    ├─ get_user_by_telegram_id  (existing accessor)
  │    ├─ upsert_user              (existing accessor)
  │    ├─ create_wallet_for_user   (if new wallet)
  │    ├─ audit.write              (always)
  │    └─ if existing + Tier 2+ → dashboard()
  │         else → onboarding welcome text
  │
  └─ dashboard.dashboard           (direct command / menu button)
       ├─ get_balance              (existing accessor)
       ├─ daily_pnl                (existing accessor)
       ├─ _fetch_stats             (one pool.acquire: positions, trades, pnl, settings)
       ├─ _build_text              → hierarchy string
       └─ reply_text + dashboard_nav keyboard

dashboard_nav_cb   (callback_data: dashboard:autotrade / dashboard:trades / dashboard:wallet)
  ├─ :autotrade → get_settings_for + reply with setup_menu keyboard
  ├─ :trades    → pool.acquire: recent positions → reply list
  └─ :wallet    → get_balance + get_wallet + reply with wallet_menu keyboard
```

---

## 3. Files Created / Modified

Modified:
- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py`
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py`
- `projects/polymarket/crusaderbot/bot/dispatcher.py`
- `projects/polymarket/crusaderbot/bot/handlers/onboarding.py`

Created:
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-phase5b-dashboard.md` (this file)

---

## 4. What Is Working

- Dashboard renders hierarchy format with four sections.
- All data sourced from existing DB accessors (`get_balance`, `daily_pnl`) and
  direct pool queries — no new tables or migrations required.
- Empty state (no trades/positions) shows $0.00 values and [🤖 Get Started] button.
- Three bottom navigation buttons route to Auto-Trade, Trades, and Wallet surfaces.
- `/start` routes existing Tier 2+ users directly to dashboard, preserving onboarding
  for new users and Tier 1 browse users.
- `autotrade_toggle_cb`, `close_position_cb`, `positions()`, and `activity()` handlers
  are preserved unchanged.
- All changed files pass Python 3 syntax check (`py_compile`).

---

## 5. Known Issues

- Branch is `claude/dashboard-hierarchy-redesign-TwPJB` (harness-assigned) instead
  of the declared `WARP/CRUSADERBOT-PHASE5B-DASHBOARD`. WARP🔹CMD must resolve.
- `dashboard.positions()` in dashboard.py remains dead code (no dispatcher entry);
  out of scope to remove.
- Percent-of-balance in P&L lines omitted when balance is $0.00 (intentional —
  division by zero guard).
- Win/Lose counts for open positions use `current_price` vs `entry_price`; positions
  with NULL `current_price` are excluded from both counts (correct — no price = unknown).
- 5C preset system not built: "Preset" row shows active `strategy_types` from
  `user_settings` as a proxy until 5C lands.

---

## 6. What Is Next

WARP🔹CMD review (Tier: STANDARD — no SENTINEL required).
After merge: Phase 5C preset system can reuse the Preset row in the dashboard
without further handler changes (data source will change, text assembly is the
same slot).
