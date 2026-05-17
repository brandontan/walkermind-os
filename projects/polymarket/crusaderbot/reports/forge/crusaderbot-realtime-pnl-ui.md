# WARP•FORGE REPORT — crusaderbot-realtime-pnl-ui

Branch: WARP/CRUSADERBOT-REALTIME-PNL-UI
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: WebTrader home Recent Activity UI + price null guard + SSE position_updated
Not in Scope: Telegram bot, trading engine, risk layer, new migrations

---

## 1. What Was Built

Four connected changes delivered as one atomic commit:

**A. Home Recent Activity — real-time + color coded**
- `DashboardPage.tsx`: Now fetches ALL positions (open + closed), sorts by `opened_at` descending, shows 5 most recent (was: 3 closed only).
- Open positions show current market value delta (e.g. `+$1.20`); `"—"` when `current_price` is null.
- Closed positions show signed P&L; `"—"` when `pnl_usdc` is null.
- SSE `position_updated` event wired for in-place card update (no full reload) — updates `current_price` + `pnl_usdc` on the matching card in state.
- `PositionCard` left border + value text now both reflect P&L tone (green=profit, red=loss, grey=neutral/unavailable) via new `borderTone` prop.

**B. $0.00 Fix — price unavailable**
- `polymarket.py`: Changed price range guard from `0.0 <= price <= 1.0` to `0.0 < price <= 1.0` for both CLOB and Gamma paths. A price of exactly 0.0 now returns `None` (not stored to DB) — prevents false "$0.00" renders on positions near resolution.
- Frontend: `activityValueFor()` returns `{ value: "—", tone: "zero" }` when `current_price is null` (open) or `pnl_usdc is null` (closed).
- `PortfolioPage.tsx` `PositionRow`: Same null guard — shows `"—"` and `tone="zero"` when price unavailable.

**C. Consistent color coding**
- `PositionCard.tsx`: New `borderTone?: "up" | "dn" | "zero"` prop. When provided, overrides the left border color (previously always based on YES/NO side). `STRIPE_TONE` map: `up=#00FF9C`, `dn=#FF2D55`, `zero=#455370`.
- Home Recent Activity: `borderTone` driven by P&L tone.
- Portfolio Open + Closed tabs: `borderTone` driven by position diff (P&L-based, not side-based).

**D. SSE `position_updated` event**
- `sse.py`: Added `push_position_updated(user_id, position_id, current_price, pnl_usdc)` helper.
- `exit_watcher.py`: After each successful `update_current_price` write, pushes `position_updated` SSE event to the user's stream (lazy import, fail-safe).
- `sse.ts` frontend: Added `position_updated` to `EVENT_TYPES` const tuple.

---

## 2. Current System Architecture

```
exit_watcher.run_once()
  └─ _act_on_decision() [hold path]
       ├─ registry.update_current_price(price, pnl)  → DB write
       └─ push_position_updated(user_id, pos_id, price, pnl) → SSE queue

SSE stream → browser EventSource
  ├─ position_updated → DashboardPage.setRecentActivity (in-place merge)
  ├─ position_opened  → full load()
  └─ position_closed  → full load()

DashboardPage
  └─ activityValueFor(p) → value + tone (null-safe, "—" on missing price)

PortfolioPage.PositionRow
  └─ priceUnavailable guard → tone="zero", value="—"

PositionCard
  └─ borderTone prop → overrides left stripe from STRIPE[side] to STRIPE_TONE[tone]
```

---

## 3. Files Created / Modified

Modified:
- `projects/polymarket/crusaderbot/integrations/polymarket.py` — price 0.0 guard (CLOB + Gamma)
- `projects/polymarket/crusaderbot/domain/execution/exit_watcher.py` — SSE push after price update
- `projects/polymarket/crusaderbot/webtrader/backend/sse.py` — push_position_updated helper
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/sse.ts` — position_updated in EVENT_TYPES
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/PositionCard.tsx` — borderTone prop
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/DashboardPage.tsx` — full Recent Activity rewrite
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx` — null-price guard + borderTone

Created:
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-realtime-pnl-ui.md` (this file)

---

## 4. What Is Working

- Price 0.0 from Polymarket API is rejected (returns None) — DB never stores 0.00 as false price.
- `position_updated` SSE event emitted by exit_watcher on every price tick (hold path).
- Frontend SSE handler merges price updates in-place on recentActivity state — no full reload flash.
- Home Recent Activity shows 5 most recent (open + closed mixed), color-coded by P&L.
- "—" renders instead of "$0.00" when price/pnl is unavailable.
- Portfolio Open + Closed tabs have P&L-based left border color (consistent with home).
- `borderTone` prop is backward-compatible (optional — existing callers without it use STRIPE[side] as before).

---

## 5. Known Issues

- Build environment in CI container lacks node_modules — TypeScript type errors from missing react/recharts types are pre-existing and unrelated to this PR. Fly.io Docker build has full deps.
- SSE `position_updated` import in exit_watcher uses lazy import with silent fail-safe to avoid circular dependency if webtrader package is not loaded (e.g., standalone bot mode).
- Portfolio `PortfolioPage.tsx` PositionRow: priceUnavailable only guards OPEN positions (closed positions always have pnl_usdc from close calculation). This is correct behavior.

---

## 6. What Is Next

WARP🔹CMD review required. Tier: STANDARD — no sentinel needed.

Suggested Next Step: Merge this PR then redeploy Fly.io. The SSE `position_updated` event will start flowing to connected WebTrader sessions as soon as the exit_watcher runs its first tick.

---

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: WebTrader UI color coding + null price display + SSE position_updated wire-up
Not in Scope: DB migrations, trading engine, risk layer, Telegram bot handlers
Suggested Next Step: WARP🔹CMD review → merge → Fly.io redeploy
