# WARP•FORGE Report — warp68-structured-card-ui

**Branch:** WARP/warp68-structured-card-ui
**Issue:** #1286
**Date:** 2026-05-23 01:46 Asia/Jakarta

---

## 1. What Was Built

WARP-68 upgrades the Telegram MVP UX from flat plain-text messages to a
"Structured Card" visual hierarchy format using Telegram-safe Unicode characters
only (`·`, `┄`, `━`). Positions now support 3-per-page pagination with
Prev / page-counter / Next navigation.

Changes are in four files:

- `bot/ui/tree.py` — new constants + updated helpers
- `bot/messages_mvp.py` — dashboard rewrite, autotrade CTA italic, positions card format
- `bot/keyboards/mvp/portfolio.py` — paginated positions keyboard
- `bot/handlers/mvp/portfolio.py` — pagination logic + new callback handler

---

## 2. Current System Architecture (Relevant Slice)

```
Telegram callback → handler → renderer → keyboard
                              (messages_mvp.py)
                                    ↑
                              ui/tree.py helpers
                              (leaf · section · cta · divider)
```

`leaf()` and `section()` are the base formatting primitives used by all
MVP screens. Changing them propagates the `·` separator format globally
without touching any screen logic.

Positions pagination:

```
portfolio:positions           → show_positions(page=1)
portfolio:positions:page:{n}  → show_positions_page() → show_positions(page=n)
```

Handler slices `p["positions"]` into `_PAGE_SIZE = 3` chunks and passes
`page`, `total_pages`, `total` to the renderer and keyboard.

---

## 3. Files Modified

```
projects/polymarket/crusaderbot/bot/ui/tree.py
projects/polymarket/crusaderbot/bot/messages_mvp.py
projects/polymarket/crusaderbot/bot/keyboards/mvp/portfolio.py
projects/polymarket/crusaderbot/bot/handlers/mvp/portfolio.py
```

No new files created. No migrations. No dispatcher.py change.

### Key diffs

**tree.py:**
- Added `DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"` and `CARD_DIVIDER = "━━━━━━━━━━━━━━━━"`
- `leaf()`: `"Label  ·  Value"` (was `"Label: Value"`)
- `section()`: sub-rows now `"  Sub  ·  Value"` (indented, was `"Sub: Value"`)
- Added `divider()` → returns `DIVIDER`
- Added `cta(text)` → returns `f"_{md_escape(text)}_"`

**messages_mvp.py:**
- `render_dashboard_default()`: raw f-string with DIVIDER sections, `»` for summary rows
- `render_autotrade_home()`: CTA → `cta("Choose an action:")` (italic), sections separated by blank lines
- `render_positions_list()`: new signature `(items, *, page, total_pages, total)`, CARD_DIVIDER between cards, italic page footer

**keyboards/mvp/portfolio.py:**
- `_PAGE_SIZE = 3` exported at module level
- `positions_list_kb(items, *, page, total_pages)`: ⬅ Prev / page counter / Next ➡ nav row

**handlers/mvp/portfolio.py:**
- `_PAGE_SIZE = 3` at handler level
- `show_positions(update, ctx, page=1)`: pagination logic, slices positions, stores page in `ctx.user_data`
- `show_positions_page(update, ctx)`: parses `portfolio:positions:page:{n}` callback, delegates to `show_positions`
- `attach()`: registers `show_positions_page` before the generic `^portfolio:` handler

---

## 4. What Is Working

- `bot/ui/tree.py` — py_compile clean; `leaf()` / `section()` / `divider()` / `cta()` / constants all exported
- `bot/messages_mvp.py` — py_compile clean; `render_dashboard_default()` raw f-string format matches spec; `render_positions_list()` new signature with card + page footer
- `bot/keyboards/mvp/portfolio.py` — py_compile clean; pagination row with conditional Prev/Next; `_PAGE_SIZE = 3` exported
- `bot/handlers/mvp/portfolio.py` — py_compile clean; `show_positions_page` registered before generic handler to avoid routing conflict
- No dispatcher.py changes; no DB query changes; no activation guard touches

---

## 5. Known Issues

- `[IN PROGRESS]` section in PROJECT_STATE.md was already over the 10-item cap before this task — pre-existing, not introduced here. WARP🔹CMD cleanup required.
- `render_autotrade_home()` now uses `"\n\n".join()` directly instead of `join_blocks()`. Behavior is equivalent (blank line between each block) but semantically cleaner for the spec format.
- Live Telegram on-device render verification (Android / iOS) is required after Fly.io redeploy to confirm `┄` and `━` characters render correctly. Not verifiable in this container environment.
- `nav:noop` callback on page counter button is not registered as a handler — pressing it does nothing (by design: it is a display-only label, not an action).

---

## 6. What Is Next

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : Structured card format on all MVP screens via tree.py helpers; 3-per-page pagination with Prev/Next on positions; page state stored in ctx.user_data
Not in Scope      : Live trading, DB migrations, strategy changes, dispatcher.py, domain logic, other handler screens
Suggested Next    : WARP🔹CMD review → merge → Fly.io redeploy → on-device render check (Android/iOS Telegram)
