# WARP•FORGE Report — fix-duplicate-menu-handlers

Validation Tier: MINOR
Claim Level: FOUNDATION
Validation Target: bot/menus/main.py MAIN_MENU_ROUTES
Not in Scope: dispatcher.py group=-1 handler logic, any trading/risk/execution path

---

## 1. What was built

Removed `"📊 Dashboard"` from `MAIN_MENU_ROUTES` in
`projects/polymarket/crusaderbot/bot/menus/main.py`.

This key was the sole duplicate — the group=-1 `MessageHandler` registered in
`dispatcher.py` (line 141) matches `filters.Regex(r"^📊 Dashboard$")` and fires
**before** group=0. PTB does not stop propagation between groups automatically,
so both the group=-1 handler (`dashboard`) **and** the group=0 `_text_router →
get_menu_route("📊 Dashboard") → dashboard` fired on every tap, producing a
duplicate bot message.

### Overlap audit — all MAIN_MENU_ROUTES keys vs group=-1 handlers

| Key | group=-1 handler | Duplicate? |
|---|---|---|
| `"📊 Dashboard"` | `filters.Regex(r"^📊 Dashboard$")` | **YES — removed** |
| `"💼 Portfolio"` | — | no |
| `"🤖 Auto Mode"` | `filters.Regex(r"^🤖 Auto-Trade$")` (different label) | no |
| `"⚙️ Settings"` | — | no |
| `"❓ Help"` | — | no |
| `"📊 Active Monitor"` | — | no |
| `"🚀 Start Autobot"` | — | no |
| `"⚙️ Configure Strategy"` | — | no |

---

## 2. Current system architecture

Unchanged. PTB handler priority:

```
group=-1  MessageHandlers (persistent nav — fire first, interrupt wizards)
group=0   ConversationHandlers + _text_router (general routing)
```

`"📊 Dashboard"` is now exclusively owned by group=-1. All other menu buttons
route through `_text_router → get_menu_route()` as before.

---

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/bot/menus/main.py` — removed `"📊 Dashboard"` entry from `MAIN_MENU_ROUTES`

No files created. No files deleted.

---

## 4. What is working

- Dashboard button no longer triggers duplicate bot messages.
- All other MAIN_MENU_ROUTES keys (`"💼 Portfolio"`, `"🤖 Auto Mode"`, `"⚙️ Settings"`,
  `"❓ Help"`, `"📊 Active Monitor"`, `"🚀 Start Autobot"`, `"⚙️ Configure Strategy"`)
  route correctly through `_text_router` as before — none are affected.
- The `dashboard` import is still needed (used by `"📊 Active Monitor"`) and is retained.

---

## 5. Known issues

None introduced by this change.

---

## 6. What is next

WARP🔹CMD review — this is a MINOR fix, no WARP•SENTINEL run required.

If future menu buttons are added to group=-1, they must also be removed from
`MAIN_MENU_ROUTES` to prevent the same duplicate-fire pattern.

---

Suggested Next Step: WARP🔹CMD review → merge decision.
