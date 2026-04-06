# telegram_menu_scope_hardening_20260407

## 1. What was built
- **Live-path blocker fix for `/start` + menu parity (FORGE-X addendum):**
  - Traced the live `/start` command path from polling loop -> `CommandRouter.route_update()` -> `CommandHandler.handle()` -> `CommandHandler._dispatch("start")` -> `CommandHandler._build_home_payload()` -> `render_view("home", payload)` -> `render_dashboard()` -> `sendMessage`.
  - Traced callback/menu path from callback query -> `CallbackRouter.route()` -> `CallbackRouter._dispatch()` -> `CallbackRouter._render_normalized_callback()` -> `_build_normalized_payload()` -> `render_view(...)` -> `editMessageText` fallback `sendMessage`.
  - Identified legacy divergence in bottom reply keyboard: it still exposed `Trade/Wallet/Performance/Exposure/Strategy/Home` and bypassed the 5-item root menu contract used by inline callbacks.
  - Normalized `/start` payload building so telemetry placeholders (`"N/A"`, `None`, `""`, malformed numerics) are coerced before render and no longer depend on downstream formatter rescue.
  - Ensured `/start` and callback Home responses both attach a main inline keyboard payload (`build_main_menu`) for a single authoritative root navigation surface.
- **Exact root-cause location capable of `float("N/A")`:**
  - `projects/polymarket/polyquantbot/telegram/handlers/portfolio_service.py::_normalize_positions()` previously used direct `float(...)` coercion for `entry_price/size/pnl` without placeholder guards.
  - This remained a live-shared payload ingestion path for Telegram menu views and could throw `ValueError: could not convert string to float: 'N/A'` when shared execution payloads included placeholders.
- **Hardening patch applied to true shared numeric source:**
  - Added `_safe_float` in `PortfolioService` and replaced direct `float(...)` coercion in both `_normalize_positions()` and `get_state()` position/wallet/pnl normalization paths.
- **Menu functionality repair (live-aligned):**
  - Updated reply keyboard root actions to exactly: `📊 Dashboard`, `💼 Portfolio`, `🎯 Markets`, `⚙️ Settings`, `❓ Help`.
  - Mapped reply-keyboard actions to normalized callback-router routes (`dashboard/portfolio/markets/settings/help`) so Home + root navigation now converge with inline flow.
- **Runtime-proof tests added on actual handler entry paths (not formatter-only):**
  - Added test coverage for `/start` through `CommandRouter.route_update()` with placeholder metrics.
  - Added callback runtime test via `CallbackRouter.route()` + synthetic callback query + stub Telegram session to validate `editMessageText` path and Home rendering.

## 2. Current system architecture
- **Authoritative `/start` path (post-fix):**
  - Entry: `main.py` polling text command
  - Handler: `telegram/command_router.py::route_update`
  - Command: `telegram/command_handler.py::handle` / `_dispatch("start")`
  - Payload builder: `CommandHandler._build_home_payload` (safe coercion)
  - Normalization layer: `interface/telegram/view_handler.py` (`safe_number`/`safe_count` + `_base_payload`)
  - Renderer: `interface/ui_formatter.py::render_dashboard`
  - Keyboard/menu builder: `telegram/ui/keyboard.py::build_main_menu`
  - Response path: `main.py::_send_result -> sendMessage`
- **Authoritative Home callback path (post-fix):**
  - Entry: callback query (`action:home`, `action:dashboard_*`, `action:back_main`)
  - Handler: `telegram/handlers/callback_router.py::route`
  - Dispatcher: `_dispatch` -> `_render_normalized_callback`
  - Payload builder: `_build_normalized_payload` (safe-number hydration from portfolio state)
  - Normalization layer + renderer: `render_view` -> `render_dashboard`
  - Keyboard/menu builder: `build_main_menu` / `build_dashboard_menu` / `build_portfolio_menu` / `build_markets_menu` / `build_settings_menu` / `build_help_menu`
  - Response path: `editMessageText` (fallback `sendMessage`)
- **Path parity map (live-aligned):**
  - `/start`: `CommandRouter` -> `CommandHandler` -> `render_view(home)` -> `build_main_menu` -> `sendMessage`
  - Home: `CallbackRouter(action:home/back_main)` -> `_render_normalized_callback(home)` -> `build_main_menu` -> `editMessageText`
  - Dashboard root: `CallbackRouter(action:dashboard)` -> alias `dashboard_home` -> `build_dashboard_menu`
  - Portfolio root: `CallbackRouter(action:portfolio)` -> alias `portfolio_wallet` -> `build_portfolio_menu`
  - Markets root: `CallbackRouter(action:markets)` -> alias `markets_overview` -> `build_markets_menu`
  - Settings root: `CallbackRouter(action:settings)` -> normalized settings view -> `build_settings_menu`
  - Help root: `CallbackRouter(action:help)` -> normalized help view -> `build_help_menu`

## 3. Files created / modified (full paths)
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/command_handler.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/handlers/portfolio_service.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/ui/reply_keyboard.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_telegram_start_numeric_safety.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/telegram_menu_scope_hardening_20260407.md`
- `/workspace/walker-ai-team/PROJECT_STATE.md`

## 4. What is working
- `/start` live-aligned command path now handles placeholder-heavy metrics payloads safely and renders Home without CRITICAL ERROR.
- Shared portfolio normalization no longer allows `float("N/A")` crash from malformed execution/position payloads in Telegram live-path hydration.
- Reply-keyboard and inline root menus now use the same 5-item navigation contract, removing legacy root-action divergence.
- Callback Home route (`CallbackRouter.route`) successfully renders and edits inline message through the real dispatch path.
- Root menu routes confirmed in tests: Dashboard, Portfolio, Markets, Settings, Help.
- Scope controls + Markets actions remain under normalized callback router flow (no change to strategy/risk/capital/order logic).

## 5. Known issues
- External live Telegram device screenshot proof is still unavailable in this container environment.
- External network/API availability (e.g., market-context endpoint) may still emit warning logs and is outside this targeted Telegram path fix.
- This pass validates live-aligned handler execution in local runtime tests; final on-device operator verification is still recommended before merge.

## 6. What is next
- SENTINEL validation required for telegram-menu-scope-hardening-20260407 before merge.
Source: projects/polymarket/polyquantbot/reports/forge/telegram_menu_scope_hardening_20260407.md
- SENTINEL should explicitly validate `/start` + callback-root parity on live Telegram path (`command_handler:/start`, Home, root menu actions, edit-message fallback) and confirm no residual legacy divergence.
