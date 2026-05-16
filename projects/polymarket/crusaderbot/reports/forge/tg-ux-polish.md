# WARP•FORGE Report — tg-ux-polish

**Branch:** WARP/CRUSADERBOT-TG-UX-POLISH
**Validation Tier:** MINOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Telegram message formatting — parse_mode + separator width + bold headers + pre blocks + keyboard anchor
**Not in Scope:** Logic changes, DB migrations, live trading paths, frontend
**Suggested Next Step:** WARP🔹CMD review → merge decision

---

## 1. What Was Built

Telegram UX polish pass — three formatting techniques applied consistently
across all user-facing message handlers:

- **BUG FIX**: `settings.py` hub, capital, risk, notifications, health, and
  referrals handlers were sending HTML-tagged text without `parse_mode=ParseMode.HTML`,
  causing raw `<b>`, `<i>`, `<code>` tags to render as literal text.
- **Technique 1**: Separator width standardised to exactly 26 ━ characters across
  every handler and template. Previously mixed between 24 chars (in
  trades.py, portfolio_chart.py, and legacy constants) and other counts.
- **Technique 2**: `<pre>` blocks confirmed on all financial/status data sections.
  `_capital_text()` upgraded from plain text to `<pre>` monospace block.
- **Technique 3**: `preset_active_kb()` keyboard gained a `[🏠 Home]` anchor row —
  the only main keyboard missing a navigation anchor. All other keyboards
  already had single-column anchor rows.

---

## 2. Current System Architecture

No architectural changes. All changes are presentation-layer only (message
text templates + inline keyboard layouts). Runtime pipeline, DB, and
trading logic unchanged.

---

## 3. Files Created / Modified

| File | Change |
|---|---|
| `projects/polymarket/crusaderbot/bot/messages.py` | `DIV` constant 24→26 ━; all 12 hardcoded 24-char separators replaced with 26-char |
| `projects/polymarket/crusaderbot/bot/handlers/settings.py` | `_hub_text()` — added bold header + 26-char sep + bold section labels + `parse_mode`; `_tp_step_text()` / `_sl_step_text()` — added sep + `<code>` current value; `_capital_text()` — bold header + sep + `<pre>` data block; `_render_hub()` — added `parse_mode=ParseMode.HTML`; settings:capital / risk / referrals / health / notifications sections — added bold header, 26-char sep, and `parse_mode=ParseMode.HTML` |
| `projects/polymarket/crusaderbot/bot/handlers/trades.py` | 24-char sep → 26-char in Full History header |
| `projects/polymarket/crusaderbot/bot/handlers/portfolio_chart.py` | 24-char sep → 26-char in fallback message |
| `projects/polymarket/crusaderbot/bot/keyboards/__init__.py` | `preset_active_kb()` — added `[🏠 Home]` anchor row as last row |

---

## 4. What Is Working

- All 26-char ━ separators consistent across every user-facing message
- `settings.py` hub, capital, risk, health, notifications, referrals — HTML now renders correctly with `parse_mode=ParseMode.HTML`
- `_hub_text()` now produces bold `<b>⚙️ Settings</b>` header + tree-format sections
- `_capital_text()` now shows `<pre>` aligned balance block
- `preset_active_kb()` now has `[🏠 Home]` anchor as final keyboard row
- `compileall` passes clean on all modified files
- Zero 24-char separators remaining in bot/ tree (verified by regex scan)

---

## 5. Known Issues

- `emergency.py`, `dashboard.py`, and `autotrade.py` handlers confirmed clean — no changes needed (parse_mode already set on all calls).
- `strategy.py` and `portfolio.py` referenced in task do not exist under those names; the relevant logic lives in `setup.py` (already had parse_mode set from mvp-cleanup pass) and `wallet.py` (already had parse_mode set).
- Keyboard anchor audit: `p5_dashboard_kb` does not have a `[🏠 Home]` button — the dashboard IS the home screen, so this is correct by design.

---

## 6. What Is Next

WARP🔹CMD review required.
Source: `projects/polymarket/crusaderbot/reports/forge/tg-ux-polish.md`
Tier: MINOR
