# WARP•FORGE Report — mvp-cleanup

**Branch:** WARP/CRUSADERBOT-MVP-CLEANUP
**Date:** 2026-05-15
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** ParseMode HTML migration (Lane A), operator→admin terminology (Lane B), dead code removal (Lane C), tier gate audit (Lane D)
**Not in Scope:** Live trading logic, risk rules, strategy engines, database schema, Polymarket API integrations

---

## 1. What Was Built

Post-MVP hygiene pass across four lanes:

- **Lane A** — Migrated all `ParseMode.MARKDOWN` / `ParseMode.MARKDOWN_V2` → `ParseMode.HTML` across 17 production handler files + 1 service file + 1 domain file + 1 root module. Converted all Markdown format strings to HTML equivalents (`*bold*`→`<b>bold</b>`, `` `code` ``→`<code>code</code>`, `_italic_`→`<i>italic</i>`, triple-backtick→`<pre>`). Replaced all Markdown escape helpers (`_escape_md`, `_md_escape`, `_esc`) with `html.escape()`. Added `html.escape()` wrapping to all user-supplied / external-API variables in message strings.
- **Lane B** — Replaced all user-facing "Operator" / "operator" strings with "Admin" / "admin" across 5 handler files.
- **Lane C** — Deleted 24 `.bak` files. Removed 3 dead legacy keyboard functions: `_legacy_dashboard_kb()`, `_legacy_portfolio_kb()`, `_legacy_get_started_kb()`.
- **Lane D** — Tier gate audit complete (see Section 6 / PR description). No code changes.

**Security posture:** All user-supplied variables and external API strings (market questions, wallet addresses, usernames, exception messages, strategy names) are now wrapped in `html.escape()` before embedding in HTML-mode messages. ParseMode.HTML is strict — unescaped `<`/`>` in user data breaks rendering. Zero unescaped injection vectors found in final audit.

---

## 2. Current System Architecture

No architectural changes. All changes are presentation-layer only:

```
Telegram Update → Handler → [html.escape() on external data] → reply_text(parse_mode=HTML)
```

All handlers in `bot/handlers/` now use a single parse mode: `ParseMode.HTML`.
Domain and service layers emit HTML-formatted strings where they produce Telegram message text.

---

## 3. Files Created / Modified

**Modified (Lane A + security):**
- `projects/polymarket/crusaderbot/bot/handlers/activation.py`
- `projects/polymarket/crusaderbot/bot/handlers/admin.py`
- `projects/polymarket/crusaderbot/bot/handlers/copy_trade.py`
- `projects/polymarket/crusaderbot/bot/handlers/demo_polish.py`
- `projects/polymarket/crusaderbot/bot/handlers/live_gate.py`
- `projects/polymarket/crusaderbot/bot/handlers/market_card.py`
- `projects/polymarket/crusaderbot/bot/handlers/my_trades.py`
- `projects/polymarket/crusaderbot/bot/handlers/notifications.py`
- `projects/polymarket/crusaderbot/bot/handlers/portfolio_chart.py`
- `projects/polymarket/crusaderbot/bot/handlers/referral.py`
- `projects/polymarket/crusaderbot/bot/handlers/setup.py`
- `projects/polymarket/crusaderbot/bot/handlers/share_card.py`
- `projects/polymarket/crusaderbot/bot/handlers/signal_following.py`
- `projects/polymarket/crusaderbot/domain/activation/live_checklist.py`
- `projects/polymarket/crusaderbot/notifications.py`
- `projects/polymarket/crusaderbot/services/trade_notifications/notifier.py`
- `projects/polymarket/crusaderbot/tests/test_demo_polish.py`

**Modified (Lane B):**
- `projects/polymarket/crusaderbot/bot/handlers/activation.py` (shared with Lane A)
- `projects/polymarket/crusaderbot/bot/handlers/admin.py` (shared with Lane A)
- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py`
- `projects/polymarket/crusaderbot/bot/handlers/presets.py`
- `projects/polymarket/crusaderbot/bot/handlers/wallet.py` (shared with Lane A)

**Modified (Lane C — dead code removed):**
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py`
- `projects/polymarket/crusaderbot/bot/keyboards/onboarding.py`

**Deleted (Lane C — .bak files):**
- `projects/polymarket/crusaderbot/bot/dispatcher.py.bak`
- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py.bak`
- `projects/polymarket/crusaderbot/bot/handlers/emergency.py.bak`
- `projects/polymarket/crusaderbot/bot/handlers/my_trades.py.bak`
- `projects/polymarket/crusaderbot/bot/handlers/onboarding.py.bak`
- `projects/polymarket/crusaderbot/bot/handlers/pnl_insights.py.bak`
- `projects/polymarket/crusaderbot/bot/handlers/positions.py.bak`
- `projects/polymarket/crusaderbot/bot/handlers/presets.py.bak`
- `projects/polymarket/crusaderbot/bot/handlers/settings.py.bak`
- `projects/polymarket/crusaderbot/bot/handlers/setup.py.bak`
- `projects/polymarket/crusaderbot/bot/handlers/wallet.py.bak`
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py.bak`
- `projects/polymarket/crusaderbot/bot/keyboards/presets.py.bak`
- `projects/polymarket/crusaderbot/bot/keyboards/settings.py.bak`
- `projects/polymarket/crusaderbot/bot/menus/main.py.bak`
- `projects/polymarket/crusaderbot/bot/middleware/access_tier.py.bak`
- `projects/polymarket/crusaderbot/bot/middleware/tier_gate.py.bak`
- `projects/polymarket/crusaderbot/bot/tier.py.bak`
- `projects/polymarket/crusaderbot/domain/preset/presets.py.bak`
- `projects/polymarket/crusaderbot/jobs/market_signal_scanner.py.bak`
- `projects/polymarket/crusaderbot/services/copy_trade/monitor.py.bak`
- `projects/polymarket/crusaderbot/services/copy_trade/scaler.py.bak`
- `projects/polymarket/crusaderbot/services/signal_feed/signal_evaluator.py.bak`
- `projects/polymarket/crusaderbot/services/trade_notifications/notifier.py.bak`

**Created:**
- `projects/polymarket/crusaderbot/reports/forge/mvp-cleanup.md` (this file)

---

## 4. What Is Working

- `python3 -m compileall projects/polymarket/crusaderbot` — zero errors
- `ruff check projects/polymarket/crusaderbot` — All checks passed
- `grep -r "ParseMode.MARKDOWN"` — zero production hits (excluding .bak)
- `grep -rn "Contact an operator|contact the operator"` — zero hits in bot/handlers/
- `find . -name "*.bak"` — zero remaining .bak files
- `grep -r "_legacy_" bot/keyboards/` — zero remaining dead functions
- All escape helpers (`_escape_md`, `_md_escape`, `_esc`) deleted; replaced by `html.escape()` at call sites
- All user-facing "operator" / "Operator" strings (excluding `OPERATOR_CHAT_ID` env var and internal role variables) replaced with "admin" / "Admin"
- `tests/test_demo_polish.py` updated: `_escape_md` tests removed, HTML assertion tests added

---

## 5. Known Issues

**WARP🔹CMD decision required:**

- `mode_select_kb()` and `paper_complete_kb()` in `projects/polymarket/crusaderbot/bot/keyboards/onboarding.py` are called in `projects/polymarket/crusaderbot/tests/test_phase5h_onboarding.py` (lines 35, 36, 134, 142). Task spec lists them for deletion but that would break tests. Both functions are preserved and flagged here. WARP🔹CMD to decide: delete tests and functions together, or retain both.

---

## 6. What Is Next

**Lane D Tier Gate Audit:**

```
require_tier() — defined in bot/middleware/tier_gate.py — ZERO active handler decorators
require_access_tier() — defined in bot/middleware/access_tier.py — ZERO active handler decorators
Both decorator functions are test-only; never wired to production handlers.

services/allowlist.py — imported only by bot/middleware/tier_gate.py
services/tiers.py — imported by: admin.py (production), access_tier.py, jobs/hourly_report.py

users.py:39 — access_tier=2 set on every upsert_user() call
Purpose: legacy migration — promotes tier-1 users to tier-2 (TIER_ALLOWLISTED) on login
New users also created at access_tier=2

Two parallel tier systems exist:
  - Integer-based: services/allowlist.py (TIER_ALLOWLISTED=2)
  - String-based: services/tiers.py (TIER_ADMIN, TIER_PREMIUM etc.)
Neither system actively gates handlers.

Recommendation: tier gate middleware is fully implemented and tested but not wired.
WARP🔹CMD to decide: remove tier system entirely or wire in a follow-up lane.
```

**Suggested Next Step:** WARP🔹CMD review. If tier gating is to be wired, that is a MAJOR validation tier task requiring WARP•SENTINEL.

---

**Suggested Next Step:** WARP🔹CMD review required.
Source: `projects/polymarket/crusaderbot/reports/forge/mvp-cleanup.md`
Tier: STANDARD
