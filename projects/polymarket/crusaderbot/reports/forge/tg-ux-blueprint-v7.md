# WARP•FORGE Report — tg-ux-blueprint-v7

**Validation Tier:** STANDARD
**Claim Level:** BROAD INTEGRATION
**Validation Target:** Dashboard inline KB removal; Close button labels per-position; Settings hub TP/SL entry; Help Home button; Trades(N) routing fix
**Not in Scope:** Onboarding wizard flow, auto mode routing, WebTrader, DB migrations, force_close_confirm_kb
**Suggested Next Step:** WARP🔹CMD review → merge → bot redeploy on Fly.io

---

## 1. What was built

Five UX fixes covering WARP-41 (#1188) and WARP-42 (#1189), merged into one PR.

- **FIX 1** Dashboard inline keyboard fully removed from `show_dashboard_for_cb` and `autotrade_toggle_cb`. No more floating `p5_dashboard_kb` above Dashboard screen.
- **FIX 2** `positions_list_kb` signature changed to accept `Iterable[dict]`. Each Close button now labelled `🔴 Close — {id[:8]} {SIDE} · {question[:28]}…` so users can identify which position they are closing.
- **FIX 3** Settings hub keyboard gains `🎚️ TP/SL` → `settings:tpsl`. The handler already existed; it was unreachable from the UI.
- **FIX 4** `/help` output now includes an inline `🏠 Home` button routing to `dashboard:main`.
- **FIX 5** Dispatcher split: `💼 Trades (N)` → `show_positions` (live monitor). Previously both `💼 Portfolio` and `💼 Trades (N)` routed to `show_portfolio`, making the dynamic label meaningless.

---

## 2. Current system architecture

```
Telegram Update
  → dispatcher.py (group=-1 handlers)
      ├─ 💼 Portfolio  → positions.show_portfolio  (unchanged)
      └─ 💼 Trades(N)  → positions.show_positions  (FIXED)
  → bot/handlers/dashboard.py
      └─ show_dashboard_for_cb → edit text only, no inline KB (FIXED)
  → bot/handlers/positions.py
      └─ show_positions → positions_list_kb(positions) (FIXED)
  → bot/keyboards/positions.py
      └─ positions_list_kb(positions: Iterable[dict])  (FIXED)
  → bot/keyboards/settings.py
      └─ settings_hub_kb() → row 2 now includes TP/SL (FIXED)
  → bot/handlers/onboarding.py
      └─ help_handler → InlineKeyboardMarkup Home button (FIXED)
```

---

## 3. Files created / modified

| Path | Change |
|------|--------|
| `projects/polymarket/crusaderbot/bot/keyboards/positions.py` | `positions_list_kb` signature + label format |
| `projects/polymarket/crusaderbot/bot/handlers/positions.py` | Call site: pass full dicts |
| `projects/polymarket/crusaderbot/bot/handlers/dashboard.py` | Remove `p5_dashboard_kb` import + usage |
| `projects/polymarket/crusaderbot/bot/keyboards/settings.py` | Add TP/SL row; move admin to own row |
| `projects/polymarket/crusaderbot/bot/handlers/onboarding.py` | `help_handler` → InlineKeyboardMarkup Home |
| `projects/polymarket/crusaderbot/bot/dispatcher.py` | Split Portfolio/Trades(N) handler |
| `projects/polymarket/crusaderbot/docs/ux-blueprint-v7.md` | Blueprint committed |
| `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` | IN PROGRESS + NEXT PRIORITY updated |
| `projects/polymarket/crusaderbot/state/CHANGELOG.md` | Append-only lane entry |

---

## 4. What is working

- `python -m py_compile` clean on all 6 Python files
- Close buttons now carry position identity: `🔴 Close — 3fc9d950 NO · New Rihanna Album…`
- Dashboard renders text-only from callback path; no inline KB surface
- TP/SL reachable from settings hub without knowing the `settings:tpsl` callback
- `/help` command provides a one-tap path back to Dashboard
- `💼 Trades (N)` taps now go to the live position monitor directly

---

## 5. Known issues

- No migration required; no new endpoints.
- `p5_dashboard_kb` function still defined in `keyboards/__init__.py` — unused now in dashboard but not deleted (safe; left for any other callers).
- `main_menu()` import in `onboarding.py` still needed for line 438; not removed.

---

## 6. What is next

WARP🔹CMD review required.
Source: `projects/polymarket/crusaderbot/reports/forge/tg-ux-blueprint-v7.md`
Tier: STANDARD
After merge: bot redeploy on Fly.io only. No migration.
