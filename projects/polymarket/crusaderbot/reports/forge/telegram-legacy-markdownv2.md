# WARP•FORGE Report — telegram-legacy-markdownv2

Branch: WARP/telegram-legacy-markdownv2
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: Legacy wallet + emergency Telegram screens migrated from HTML to MarkdownV2; rendering parity with the MVP layer (#1382)
Not in Scope: Other legacy handlers (autotrade.py, admin.py broad, copy_trade.py, settings.py, etc.); notification service (`services/`); `admin_withdrawal_item_text` (intentionally kept HTML — operator path)

---

## 1. What was built

Follow-up to telegram-ux-v2 (#1382). Migrated the two remaining user-facing legacy handler surfaces — the **wallet/withdraw flow** and the **emergency controls menu** — from `parse_mode=HTML` to `parse_mode=MarkdownV2`, matching the MVP layer's format.

Migrated message renderers in `bot/messages.py` (10 functions):
- Wallet/withdraw (user-facing): `wallet_text`, `wallet_deposit_text`, `withdraw_ask_amount_text`, `withdraw_ask_address_text`, `withdraw_confirm_text`, `withdraw_submitted_text`, `withdraw_history_text`
- Emergency: `EMERGENCY_TEXT`, `emergency_confirm_text`, `emergency_feedback_text`, `emergency_system_status_text`

Handler `parse_mode` + inline strings migrated in `bot/handlers/wallet.py` and `bot/handlers/emergency.py`.

**Deliberately kept HTML** — `admin_withdrawal_item_text`: it is operator-facing and rendered through two HTML send paths (`notifications.notify_operator`, which hardcodes HTML, and the `admin.py` withdrawals panel). Converting it would require touching `notifications.py` + `admin.py` (40 HTML usages) — out of scope and unnecessary. Leaving it HTML keeps `admin.py` and `notifications.py` untouched and the operator notification path correct.

---

## 2. Current system architecture

```
bot/messages.py  (HTML + MarkdownV2 coexist — piecewise migration by design)
  ├─ MarkdownV2: wallet/withdraw (user) + emergency renderers  → _md = ui.tree.md_v2_escape
  └─ HTML (unchanged): signal/position/daily/onboard/dashboard/preset/trades/admin_withdrawal_item_text

bot/handlers/wallet.py     → _edit_or_reply(parse_mode=MARKDOWN_V2); op_text notification stays HTML
bot/handlers/emergency.py  → all sends parse_mode=MARKDOWN_V2
bot/handlers/admin.py       → UNCHANGED (admin_withdrawal_item_text still HTML)
notifications.py            → UNCHANGED
```

Escaping discipline:
- Values inside ``` ` ``` code spans / ` ``` ` blocks → raw (no escape; backslash is literal there)
- Dynamic values in raw text / `*bold*` / `_italic_` → `_md()` (= `ui.tree.md_v2_escape`)
- Static special chars (`.`, `-`, `!`, `+`, `(`, `)`, `=`) escaped inline with `\\`

---

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/bot/messages.py` — 10 wallet/emergency renderers → MarkdownV2; `_md` import added; `admin_withdrawal_item_text` kept HTML
- `projects/polymarket/crusaderbot/bot/handlers/wallet.py` — `_edit_or_reply` + 6 inline reply paths → MarkdownV2; unused `html` import removed; `_md` import added
- `projects/polymarket/crusaderbot/bot/handlers/emergency.py` — all 11 sends → MarkdownV2; 3 inline strings escaped
- `projects/polymarket/crusaderbot/tests/test_wallet_withdraw_flow.py` — `test_withdraw_submitted_text_auto` assertion updated to escaped `Auto\\-approved`

Created:
- `projects/polymarket/crusaderbot/reports/forge/telegram-legacy-markdownv2.md` (this file)

---

## 4. What is working

- `py_compile` + `ruff check` clean on all 3 production files
- Render tests: wallet_text, wallet_deposit_text, withdraw_* , EMERGENCY_TEXT, emergency_* all produce valid MarkdownV2; `admin_withdrawal_item_text` confirmed still HTML
- Code-span values render without stray backslashes (escape-in-code-span bug caught + fixed during build)
- 1792 tests pass, 1 skipped, 0 regressions (was 1787 before; +5 from prior CI-mock fix carried on main)
- No circular import from `messages.py → ui.tree`

---

## 5. Known issues

- `admin_withdrawal_item_text` is intentionally HTML — so the operator withdrawal-request notification + admin panel stay HTML. This is correct (their send paths are HTML), but it means messages.py now mixes HTML and MarkdownV2 functions (documented in the module; piecewise migration was always the design).
- Remaining legacy handlers (autotrade.py, copy_trade.py, settings.py, start.py, trades.py, admin.py, etc.) still use HTML — separate future lanes if desired. Most are partially superseded by the MVP layer.

---

## 6. What is next

- WARP🔹CMD review + merge + fly deploy (STANDARD — display-only, no trading logic, no schema change).
- Post-deploy verify in Telegram: `/wallet` deposit + withdraw 3-step flow; `/emergency` menu + confirm dialogs + system status.
- Optional: migrate remaining legacy handlers in follow-up lanes (per-handler, same escaping discipline).

Suggested Next Step: WARP🔹CMD review + merge. STANDARD tier.
