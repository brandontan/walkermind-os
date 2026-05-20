# Forge Report — fix-dashboard-portfolio-routing

Branch: WARP/fix-dashboard-portfolio-routing
Date: 2026-05-20 10:46
Issue: #1192 — dashboard:portfolio routes to show_trades instead of show_portfolio

---

## 1. What was changed

`dashboard_nav_cb` in `dashboard.py` had a combined `elif sub in ("portfolio", "trades")` branch that routed both `dashboard:portfolio` and `dashboard:trades` to `show_trades()`. This meant tapping the 💼 Portfolio inline button opened Trades history instead of Portfolio overview.

Split into two separate branches:
- `sub == "portfolio"` → `positions.show_portfolio`
- `sub == "trades"` → `trades.show_trades`

Added hermetic routing tests asserting the corrected dispatch.

---

## 2. Files modified

- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py` — `dashboard_nav_cb` lines 328–332: split combined `in (...)` check into two separate `elif` branches
- `projects/polymarket/crusaderbot/tests/test_dashboard_routing.py` — new; two tests asserting `dashboard:portfolio` → `show_portfolio` and `dashboard:trades` → `show_trades`

---

## 3. Validation

Validation Tier   : MINOR
Claim Level       : NARROW INTEGRATION
Validation Target : dashboard_nav_cb routing for dashboard:portfolio and dashboard:trades callbacks
Not in Scope      : portfolio_kb layout, show_portfolio logic, show_trades logic, any other handler, DB, live trading
Suggested Next    : WARP🔹CMD review
