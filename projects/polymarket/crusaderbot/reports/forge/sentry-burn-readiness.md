# WARP•FORGE Report — sentry-burn-readiness

**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** WARP-29 — Sentry burn verification, Signal Freshness Gate confirmation, Telegram Power Mode inline keyboards
**Not in Scope:** Merging open PRs, live trading path, schema migrations, new strategy logic

---

## 1. What was built

Three tasks from WARP-29:

**Task 1 — Sentry Cleanup (verified on main)**
All 4 Sentry fixes from `claude/fix-sentry-issues-2g0es` (PR #1170) confirmed already present on `main`:
- `monitor.py` `date.today()` fix: SHA `5b35f4c3` on main — matches post-PR state
- `job_tracker.py` `$6::jsonb` cast: SHA `238ca05c` on main — matches post-PR state
- migration 032 `user_id` guard: confirmed in repo
- `preset_picker_kb` alias: no Python file references it — resolved upstream

No code change required for Task 1 — already on main.

**Task 2 — Signal Freshness Gate (verified on main)**
`signal_scan_job.py` on main already contains the full step 1c implementation:
- `_MAX_SIGNAL_AGE_SECONDS = 1800`
- Freshness gate at step 1c in `_process_candidate()` — rejects `pub_uuid`-backed signals older than 30 min with `outcome="skipped_signal_stale"`
- Guarded: gate is skipped for lib-strategy candidates (`pub_uuid is None`)

No code change required for Task 2 — already on main.

**Task 3 — Telegram Power Mode inline keyboards (implemented)**
Updated both notification paths to inject `[ 📈 View Position ]`, `[ 🛑 Close Position ]`, `[ ⏸️ Pause Copy ]` inline buttons onto trade notifications. V5 branding aligned with CRU-15 callback_data conventions.

---

## 2. Current system architecture

No structural changes. Notification pipeline unchanged:

```text
TradeEngine.execute()
  → paper.execute()          ← notify_entry(position_id=str(position_id)) [UPDATED]
  → event_bus.emit(position.opened / copy_trade.executed)
       → notification_service._on_position_opened()  ← _auto_trade_kb() [UPDATED]
       → notification_service._on_copy_trade_executed() ← _copy_trade_kb() [UPDATED]
  → TradeNotifier.notify_copy_trade_entry()  [UPDATED — new params + keyboard]
```

Callback routing (unchanged, already wired in dispatcher):
- `mytrades:open:{id}` → `trade_detail_cb`
- `close_position:{id}` → `close_ask_cb`
- `tgnotif:pause_copy:{id}` → `tg_power_mode_cb` → `pause_copy_cb`

---

## 3. Files created / modified

| Path | Change |
|------|--------|
| `projects/polymarket/crusaderbot/services/notification_service.py` | `_auto_trade_kb`: "📊 View Position"→"📈 View Position", "❌ Close Position"→"🛑 Close Position"; 2-row layout. `_copy_trade_kb`: "📊 View Position"→"📈 View Position", "⏸"→"⏸️", added "🛑 Close Position" row |
| `projects/polymarket/crusaderbot/services/trade_notifications/notifier.py` | `notify_entry`: "📋 View Trade"→"📈 View Position", added "🛑 Close Position" button; 2-row layout. `notify_copy_trade_entry`: added `position_id` + `copy_task_id` params, added inline keyboard |
| `projects/polymarket/crusaderbot/domain/execution/paper.py` | `notify_entry` call: added `position_id=str(position_id)` so buttons have the position reference |
| `projects/polymarket/crusaderbot/reports/forge/sentry-burn-readiness.md` | This report |
| `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` | Updated [IN PROGRESS], [NEXT PRIORITY] |
| `projects/polymarket/crusaderbot/state/CHANGELOG.md` | Appended lane entry |

---

## 4. What is working

- `notify_entry` emits `[ 📈 View Position ] [ 🛑 Close Position ]` + `[ 📊 Dashboard ]` (2 rows) when `position_id` is available; `[ 📊 Dashboard ]` only row when not
- `notify_copy_trade_entry` emits `[ 📈 View Position ] [ 🛑 Close Position ]` row + `[ ⏸️ Pause Copy ]` row (when respective IDs present)
- `_auto_trade_kb` (event-bus path) uses updated labels in 2-row layout
- `_copy_trade_kb` (event-bus path) adds `[ 🛑 Close Position ]` to copy trade notifications
- `paper.execute()` now passes `position_id` → inline buttons are functional immediately on paper trade open
- All 3 callback_data patterns route to existing registered handlers — no new dispatcher wiring needed
- compileall clean on all modified files

---

## 5. Known issues

- `paper.py` `notify_entry` call does not pass `signal_reason`, `copy_wallet`, `copy_win_rate` — these remain None (pre-existing; not introduced by this PR)
- `notify_copy_trade_entry` in `notifier.py` now accepts `position_id` + `copy_task_id` but the copy_trade event-bus path (`notification_service._on_copy_trade_executed`) is the primary production path; `TradeNotifier.notify_copy_trade_entry` has no production call sites yet

---

## 6. What is next

```text
WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/sentry-burn-readiness.md
Tier: STANDARD
```

- WARP🔹CMD to review and merge WARP/sentry-burn-readiness PR
- Deploy to Fly.io to clear production Sentry issues and activate inline keyboards
- CRU-15 (`claude/crusaderbot-telegram-phase4-A9FvW`) may be superseded by this PR for keyboard logic — WARP🔹CMD to decide
