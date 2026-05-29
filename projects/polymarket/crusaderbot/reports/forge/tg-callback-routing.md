# WARP•R00T FORGE REPORT — tg-callback-routing

Branch: WARP/ROOT/tg-callback-routing
Date: 2026-05-30 01:23 Asia/Jakarta
Lane: 4/5 of the WARP•R00T full-system pre-public-ready audit fix campaign

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : legacy dashboard:* and settings:* sub-routes reach their intended screens instead of being swallowed to the MVP home
Not in Scope      : the legacy handlers' internal behavior (unchanged); Lane 5
Suggested Next    : WARP🔹CMD review, then Lane 5 (live-path-hardening)

## 1. What was built
Closes audit finding B6 (Telegram callback collisions). The MVP UX handlers are
attached FIRST (`dispatcher.register` → `mvp_dashboard.attach` / `mvp_settings.attach`,
group 0), so for `^dashboard:` and `^settings:` they win over the legacy
`dashboard_nav_cb` / `settings_callback` registered later in the same group — and
the legacy handlers never fired. The MVP callbacks only handled their own screens
and bounced everything else to the MVP home, so these were silently dead:
- `settings:tpsl` (TP/SL config), `settings:wallet`, `settings:health`,
  `settings:admin`, `settings:redeem_set:*`, `settings:profile`,
  `settings:referrals`, `settings:capital`, `settings:live_gate`, `settings:back`
- `dashboard:insights`, `dashboard:portfolio`, `dashboard:trades`,
  `dashboard:wallet`, `dashboard:auto`, `dashboard:stop`, `dashboard:monitor`

Fix — delegate-unknowns (no handler re-ordering, lowest regression risk):
- `bot/handlers/mvp/settings.py _settings_cb`: the final unknown-screen branch
  now calls the legacy `settings.settings_callback` instead of `show_home()`.
  MVP keeps the screens it owns (home/mode/risk/notifications/account/advanced/
  copy_wallet).
- `bot/handlers/mvp/dashboard.py _dashboard_cb`: keeps `dashboard:main`/`refresh`
  on the MVP home; every other sub-route delegates to the legacy
  `dashboard.dashboard_nav_cb` (routes insights/portfolio/trades/wallet/settings/
  auto/stop/monitor).

Lazy imports inside the callbacks avoid circular-import risk; the delegate path
runs before `send_or_edit`, so the legacy handler answers the callback once
(no double-answer).

## 2. Current system architecture (relevant slice)
PTB processes one handler per group; within group 0 the first-registered match
wins. MVP (registered first) intercepts `^dashboard:` / `^settings:`, handles its
own screens, and forwards the remainder to the legacy router — so both the MVP
reply-keyboard surface and the legacy inline `/settings` + dashboard keyboards
now work without changing handler registration order.

## 3. Files created / modified (full repo-root paths)
Modified:
- projects/polymarket/crusaderbot/bot/handlers/mvp/settings.py (_settings_cb delegates unknown sub-routes to legacy settings_callback)
- projects/polymarket/crusaderbot/bot/handlers/mvp/dashboard.py (_dashboard_cb keeps main/refresh, delegates the rest to dashboard_nav_cb)
Created:
- projects/polymarket/crusaderbot/tests/test_tg_callback_routing.py (6 functional routing tests)

## 4. What is working
- py_compile + ruff clean.
- 6/6 new routing tests pass: dashboard:main→MVP home; dashboard:insights/portfolio
  →legacy; settings:tpsl/wallet→legacy; settings:risk→stays MVP.
- 61 existing dashboard/settings/routing/ux tests pass (no regression).

## 5. Known issues
- Routing verified via hermetic monkeypatched dispatch (no live bot in CI). The
  legacy handlers' own screens are unchanged and pre-existing.
- Behaviour note: tapping a screen MVP owns (e.g. settings:risk) shows the MVP
  screen even from a legacy keyboard — intended (MVP is the canonical surface).

## 6. What is next
- WARP🔹CMD review.
- Lane 5: WARP/ROOT/live-path-hardening (pre-LIVE money-path).

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
