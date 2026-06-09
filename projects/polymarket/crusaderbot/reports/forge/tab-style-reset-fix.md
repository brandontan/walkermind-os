# WARP•FORGE Report — tab-style-reset-fix

## 1. What was built

Two fixes in one lane:

**A — Admin paper reset 500 (root cause fix):** The `admin_paper_reset` transaction deleted `orders` before `positions`, violating `positions.order_id → orders` FK (`NO ACTION`). A second FK — `fees.order_id → orders` (`NO ACTION`) — also blocked the delete. Both caused an uncaught asyncpg `ForeignKeyViolationError` → HTTP 500 "Internal Server Error". Fixed by reordering: delete `fees` first, then `positions` (which cascades `redeem_queue` via its `CASCADE` FK), then `orders`.

**B — AUTO TRADE / COPY TRADE tab visual redesign:** PageTabs styled as underline-text tabs (low contrast, not centered). Redesigned to match the DEPOSIT / WITHDRAW button style: `flex-1 clip-btn` pair, green-tinted active/inactive states for AUTO TRADE and gold-tinted for COPY TRADE. Tabs now fill the full container width and are visually balanced with clear active/inactive contrast.

## 2. Current system architecture

No architecture change. `admin_paper_reset` is a single POST endpoint in `webtrader/backend/router.py`. `PageTabs` is a shared React component exported from `CopyTradePage.tsx` and consumed by both `AutoTradePage` and `CopyTradePage`.

**Corrected FK-safe deletion order in `admin_paper_reset`:**
```
fills       → orders (CASCADE — explicit for clarity)
fees        → orders (NO ACTION — must clear before orders)
copy_trade_events → positions (NO ACTION)
positions   → orders (NO ACTION; redeem_queue cascades from positions)
orders      → now safe (no remaining NO ACTION FKs)
portfolio_snapshots
ledger
```

## 3. Files created / modified

| Action | Path |
|--------|------|
| Modified | `projects/polymarket/crusaderbot/webtrader/backend/router.py` |
| Modified | `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/CopyTradePage.tsx` |
| Created  | `projects/polymarket/crusaderbot/reports/forge/tab-style-reset-fix.md` |

## 4. What is working

- **Reset**: FK deletion order corrected. `redeem_queue` (155 rows, CASCADE) auto-cleared when positions delete. `fees` explicitly cleared before orders. Both root causes resolved.
- **Tabs**: `PageTabs` now renders as a full-width button pair matching the DEPOSIT/WITHDRAW visual language — green clip-btn for AUTO TRADE, gold clip-btn for COPY TRADE; active state lit up, inactive state dimmed. `tsc --noEmit` clean.

## 5. Known issues

- Paper reset test suite mocks empty trade rows — the FK ordering bug was always untested. A regression test pinning the deletion order (positions before orders, fees before orders) is not in this lane (kept minimal per CLAUDE.md one-shot rules). Can be added in a follow-up MINOR lane if WARP🔹CMD wants coverage.

## 6. What is next

- Deploy to Fly.io (no migration needed — backend code change only).
- Verify reset works end-to-end via the admin drawer for user `walk3r69`.
- Monitor Weather Monitor and Copy Trade fires in Telegram over next 24–48h.

---

**Validation Tier:** MINOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** `admin_paper_reset` FK deletion order + `PageTabs` visual styling only
**Not in Scope:** reset test coverage, other admin endpoints, frontend build pipeline, strategy execution
**Suggested Next Step:** WARP🔹CMD review — no migration, no runtime execution change
