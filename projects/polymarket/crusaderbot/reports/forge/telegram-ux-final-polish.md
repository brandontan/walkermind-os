# Forge Report — telegram-ux-final-polish

**Branch:** `WARP/telegram-ux-final-polish`
**Date:** 2026-05-17 10:00 Asia/Jakarta
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Telegram UX / callback routing and user-facing copy only
**Not in Scope:** WebTrader, live-trading activation, execution/risk/capital logic, DB schema teardown

---

## 1. What was built

Five targeted UX fixes across Telegram bot callback routing, keyboard labels, and dead code removal.

**Fix 1 — wallet_callback sub-parsing bug (critical)**
`p5:wallet:copy` callback was silently falling through to re-render the wallet screen instead of copying the address. Root cause: `split(":", 1)[-1]` on `"p5:wallet:copy"` yields `"wallet:copy"`, not `"copy"`, so the `if sub == "copy":` branch never matched. Fixed with `rsplit(":", 1)[-1]` which correctly yields `"copy"` regardless of prefix depth.

**Fix 2 — portfolio_chart.py dead tier gate removed**
`chart_command` and `chart_callback` still contained `has_tier(user["access_tier"], Tier.ALLOWLISTED)` checks from the legacy integer-tier system. Since `upsert_user` seeds all users at `access_tier=3` (>= `Tier.ALLOWLISTED=2`), the gate was permanently open but imported dead modules. Removed both checks and the `Tier, has_tier, tier_block_message` import.

**Fix 3 — wallet_p5_kb home button label**
"📊 Dashboard" label on the wallet screen's home button was inconsistent with every other screen that uses "🏠 Home". Updated label to "🏠 Home"; `callback_data="menu:dashboard"` unchanged.

**Fix 4 — emergency_done_p5_kb Auto-Trade label**
Post-emergency confirmation screen showed "🤖 Auto-Trade" which no longer matches the current menu label "🤖 Auto Mode". Updated label for consistency; `callback_data="menu:autotrade"` unchanged.

**Fix 5 — settings.py _hub_text unused tier parameter**
`_hub_text(mode, tier, risk_profile)` accepted `tier: int` but the function body never used it. Removed the parameter and its local variable `tier = user.get("access_tier", 2)` from `_render_hub`.

---

## 2. Current system architecture

No architectural changes. Pipeline unchanged:

```
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
```

Telegram bot layer: `dispatcher.py` → `handlers/` → `keyboards/` → `messages.py`
All five fixes are confined to the bot surface layer. No database, scheduler, or risk layer changes.

---

## 3. Files created / modified (full repo-root paths)

**Modified:**

- `projects/polymarket/crusaderbot/bot/handlers/wallet.py`
  — `wallet_callback`: `split(":", 1)[-1]` → `rsplit(":", 1)[-1]`

- `projects/polymarket/crusaderbot/bot/handlers/portfolio_chart.py`
  — Removed `from ..tier import Tier, has_tier, tier_block_message`
  — Removed `has_tier` gate blocks in `chart_command` and `chart_callback`

- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py`
  — `wallet_p5_kb`: "📊 Dashboard" → "🏠 Home"
  — `emergency_done_p5_kb`: "🤖 Auto-Trade" → "🤖 Auto Mode"

- `projects/polymarket/crusaderbot/bot/handlers/settings.py`
  — `_hub_text`: removed `tier: int` parameter
  — `_render_hub`: removed `tier = user.get("access_tier", 2)` and updated call site

**Created:**

- `projects/polymarket/crusaderbot/reports/forge/telegram-ux-final-polish.md` (this file)

---

## 4. What is working

- `python3 -m compileall projects/polymarket/crusaderbot/bot/` passes — zero syntax errors
- Wallet "📋 Copy Address" button now correctly calls `q.answer(..., show_alert=True)` with the deposit address for both `p5:wallet:copy` and `wallet:copy` callback patterns
- Portfolio chart accessible to all users (no tier gate)
- Back/home navigation labels consistent across wallet, emergency, and settings screens
- `_hub_text` signature cleaned up — no unused parameter
- All activation guards (`ENABLE_LIVE_TRADING`, etc.) untouched
- PAPER ONLY posture preserved — no execution path changes

---

## 5. Known issues

- Dead group=-1 MessageHandlers in `dispatcher.py` for old button labels ("🤖 Auto-Trade", "💰 Wallet", "📈 My Trades", "🚨 Emergency") remain as intentional backward compatibility for users who may still hold old persistent reply keyboards. These do not cause any UX bug and are out of scope per task definition.
- `emergency_feedback()` and `dashboard_kb()` in `keyboards/__init__.py` remain as unused functions — no caller exists, deletion deferred to separate cleanup lane.
- `pnl_insights.py` and `portfolio_chart.py` docstrings still reference "ALLOWLISTED (Tier 2+)" — docstring-only, not user-visible, deferred.

---

## 6. What is next

WARP🔹CMD review required.
Source: `projects/polymarket/crusaderbot/reports/forge/telegram-ux-final-polish.md`
Tier: STANDARD
