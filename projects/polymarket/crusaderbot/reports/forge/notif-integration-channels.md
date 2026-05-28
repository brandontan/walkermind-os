# WARP•FORGE Report — notif-integration-channels

**Branch:** WARP/ROOT-notif-integration-channels
**Validation Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Per-user × per-alert × per-channel notification routing (Web AlertCenter + Telegram), backed by `user_settings.notification_prefs` JSONB
**Not in Scope:** operator broadcasts (`system_alerts.user_id IS NULL` path), `low_balance` (no backend trigger exists yet)
**Suggested Next Step:** WARP🔹CMD review → merge → Fly redeploy

---

## 1. What Was Built

End-to-end realisation of the user's request: "Pastikan setting notifikasi berfungsi, notifikasi ke web dan telegram. Tambahkan di setting notifikasi, bisa set web/telegram only atau notif both web & tg (default)."

Three lanes:

**A. Storage** — `user_settings.notification_prefs JSONB` stores the user's preference matrix shape:
```json
{
  "trade_opened":   {"web": true, "tg": true},
  "trade_closed":   {"web": true, "tg": false},
  "kill_switch":    {"web": false, "tg": true},
  …
}
```
Missing keys / channels default to `true` (both ON). Shape is application-validated — no DB schema for JSON contents, so new alert keys never require a migration.

**B. Gate** — `webtrader/backend/notification_prefs.py` is the single source of truth:
- `should_notify(user_id, alert_key, channel) -> bool` — used by every TG sender
- `persist_user_alert(user_id, alert_key, title, body, severity)` — writes the per-user `system_alerts` row that surfaces in the WebTrader AlertCenter
- `resolve_user_id_for_telegram(tg_id) -> str | None` — TTL-cached resolver (60s) used by `route_outgoing_alert(...)` so each notification needs at most one DB roundtrip per cache window
- `route_outgoing_alert(...)` — the convenience wrapper every inner-send helper calls: resolves user_id, writes web mirror, returns whether to fire TG

Fail-open everywhere — unknown user / unknown key / DB error all return `True` for TG. A missing pref row never silently drops a notification.

**C. UI** — `NotificationPrefsCard.tsx` is now server-backed (no more localStorage). Each row has two chips (📡 WEB · 💬 TG) the user can tap to toggle each channel independently. All On / All Off bulk actions write both channels at once. Saves on every change with a "SAVING…" status indicator.

**Per-user web alerts** — the existing `system_alerts` table previously only stored operator broadcasts (no `user_id`). Migration 063 adds `user_id UUID NULL`; new per-user rows are routed by the updated `cb_alerts` NOTIFY payload (includes `user_id` for SSE per-user fan-out). `GET /api/web/alerts` is now `user: _CurrentUser`-scoped: `WHERE user_id IS NULL OR user_id = $1`.

---

## 2. Current System Architecture

```
Trade event fires
  │
  ├─ paper.execute() / engine.py → _notifier.notify_entry(...)
  │     └─ TradeNotifier._send()
  │         └─ route_outgoing_alert(tg_id, alert_key="trade_opened", ...)
  │             ├─ persist_user_alert → INSERT system_alerts (gated by web pref)
  │             └─ should_notify(.., "tg") → bool
  │         └─ if tg pref ON → notifications.send(tg_id, text)
  │
  ├─ exit_watcher → monitoring_alerts.alert_user_tp_hit(...)
  │     └─ _send_user_exit_alert(alert_kind="tp_hit", ...)
  │         └─ route_outgoing_alert(.., alert_key="trade_closed", ..)
  │         └─ notifications.send(...) when tg ON
  │
  ├─ event_bus.emit("position.opened") → _on_position_opened
  │     └─ _send_safe(text, "position.opened")
  │         └─ route_outgoing_alert(.., alert_key="trade_opened", ..)
  │
  └─ jobs/daily_pnl_summary.run_once
        └─ route_outgoing_alert(.., alert_key="daily_report", ..)

WebTrader AlertCenter
  │
  └─ GET /api/web/alerts (user-scoped)
        └─ SELECT FROM system_alerts WHERE user_id IS NULL OR user_id = $1
```

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/migrations/063_notification_prefs_user_alerts.sql` (applied to prod via MCP)
- `projects/polymarket/crusaderbot/webtrader/backend/notification_prefs.py`
- `projects/polymarket/crusaderbot/tests/test_notification_prefs.py`

**Modified:**
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — `/alerts` scoped per-user; new `GET / PATCH /settings/notification-prefs`
- `projects/polymarket/crusaderbot/monitoring/alerts.py` — `_send_user_exit_alert` routed via `route_outgoing_alert`; exit_kind → pref_key map
- `projects/polymarket/crusaderbot/services/notification_service.py` — `_send_safe` gated; event_name → pref_key map
- `projects/polymarket/crusaderbot/services/trade_notifications/notifier.py` — `_send` gated; `NotificationEvent` → pref_key map
- `projects/polymarket/crusaderbot/jobs/daily_pnl_summary.py` — `daily_report` gated via `route_outgoing_alert`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` — `NotificationPrefs` type + `getNotificationPrefs / updateNotificationPrefs` client methods
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/NotificationPrefsCard.tsx` — server-backed + Web/TG chips

---

## 4. What Is Working

- Migration 063 applied to Supabase production (`apply_migration` confirmed)
- `pytest projects/polymarket/crusaderbot/tests/` — **1909 passed**, 5 skipped (+10 new for `notification_prefs`)
- `npx tsc --noEmit` — clean
- 14 inventoried Telegram call sites now route through the gate (via 4 inner-send helpers: `_send_user_exit_alert`, `_send_safe`, `_send`, `daily_pnl_summary.send`)
- Web AlertCenter sees the new per-user rows (the SELECT change + `system_alerts.user_id` column landed together)
- TTL cache (60s) on `telegram_user_id → user_id` resolver — at most one DB roundtrip per user per minute even under heavy notification load
- Fail-open semantics tested: unknown user, unknown alert key, DB error all return True for TG

---

## 5. Known Issues

- `low_balance` UI key has no backend trigger (the inventory found no call site that emits it). The toggle persists but currently has no effect. Wiring it is a separate lane (needs balance-threshold monitor).
- `auth_events` from the original spec is not in the UI — intentional, no backend emit site for it either.
- Operator broadcasts (`system_alerts` rows with `user_id IS NULL`) are still subject to the user's web channel pref? **No** — they go straight through; `persist_user_alert` is only called from the per-user path. Broadcasts are unaffected.
- Existing positions / users created before this PR have `notification_prefs = '{}'` — they get the default (all channels ON) automatically. No backfill needed.

---

## 6. What Is Next

- WARP🔹CMD review → merge → Fly redeploy
- Post-deploy smoke: (1) toggle `trade_opened.tg` OFF → next paper trade only appears in WebTrader AlertCenter, NOT in Telegram. (2) Toggle `trade_opened.web` OFF → next paper trade goes to Telegram only, no AlertCenter row.
- Future lane: wire the `low_balance` monitor + emit
