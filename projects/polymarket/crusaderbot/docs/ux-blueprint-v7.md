# UX Blueprint v7 — CrusaderBot Telegram

Source: WARP-41 (#1188) + WARP-42 (#1189) — merged into single PR.
Date: 2026-05-20
Branch: claude/add-close-button-labels-1PhGZ

---

## Screens covered

| Screen | File | Status |
|--------|------|--------|
| Dashboard | `bot/handlers/dashboard.py` | Inline KB removed |
| Positions | `bot/keyboards/positions.py` + `bot/handlers/positions.py` | Close buttons labelled per-position |
| Settings Hub | `bot/keyboards/settings.py` | TP/SL entry point added |
| Help | `bot/handlers/onboarding.py` | Home inline button added |
| Dispatcher | `bot/dispatcher.py` | Trades(N) routes to live position monitor |

---

## FIX 1 — Dashboard: inline keyboard removed

`show_dashboard_for_cb` and `autotrade_toggle_cb` no longer pass `reply_markup=p5_dashboard_kb(...)`.
Dashboard text is now rendered with no inline keyboard. Navigation via persistent ReplyKeyboard (bottom bar) only.
`p5_dashboard_kb` import removed from `dashboard.py`.

---

## FIX 2 — Positions: Close buttons labelled per-position

`positions_list_kb` signature changed:

```
# Before
def positions_list_kb(position_ids: Iterable[UUID | str]) -> InlineKeyboardMarkup

# After
def positions_list_kb(positions: Iterable[dict]) -> InlineKeyboardMarkup
```

Button label format: `🔴 Close — {id[:8]} {SIDE} · {question[:28]}…`

Call site in `handlers/positions.py`:
```
# Before
kb = positions_list_kb([p["id"] for p in positions])

# After
kb = positions_list_kb(positions)
```

Empty-positions path passes `[]` — iterates zero items, nav row appended, safe.

---

## FIX 3 — Settings Hub: TP/SL entry point

`settings_hub_kb()` now includes `🎚️ TP/SL` → `settings:tpsl` in row 2.
Handler (`settings:tpsl`) already registered in `handlers/settings.py` at line 255.
Admin row moved to `rows.append(...)` instead of `rows[-1].append(...)` to avoid clobbering
the Health button when `is_admin=True`.

---

## FIX 4 — Help screen: Home inline button

`help_handler()` now sends `reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="dashboard:main")]])`.
Replaces the previous `reply_markup=main_menu()` (ReplyKeyboard) — persistent bottom bar remains visible from prior messages.

---

## FIX 5 — Trades(N) routing

Dispatcher split from one combined handler to two:

```
# Before (both labels → show_portfolio)
MessageHandler(Regex(r"^💼 (Portfolio|Trades \(\d+\))$"), positions.show_portfolio)

# After
MessageHandler(Regex(r"^💼 Portfolio$"),        positions.show_portfolio)
MessageHandler(Regex(r"^💼 Trades \(\d+\)$"),   positions.show_positions)
```

`💼 Trades (N)` now routes directly to `show_positions` (live position monitor with mark prices and Close buttons).
`_DYNAMIC_TRADES_RE` early-return in `_text_router` unchanged — still short-circuits wizard text handlers.

---

## NOT in scope

- Onboarding wizard logic (8 steps correct, no change)
- Auto Mode routing (fixed in WARP-40)
- Dashboard text / P&L calculation
- WebTrader frontend
- Database migrations (none required)
- `force_close_confirm_kb` (internal admin path, not touched)
