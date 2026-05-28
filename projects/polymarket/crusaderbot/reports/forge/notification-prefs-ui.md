# WARP•R00T REPORT — notification-prefs-ui

Validation Tier: MINOR
Claim Level: NARROW INTEGRATION
Validation Target: WebTrader Settings page — Notification Preferences card with per-category per-alert toggles persisted to localStorage. Replaces the three-row single-flag Notifications SettingsGroup.
Not in Scope: Backend per-alert filtering, Telegram alert delivery gating, server-side read/write of per-alert prefs, AlertCenter runtime filtering by prefs (follow-up lane).
Suggested Next Step: WARP🔹CMD review. Tier: MINOR (frontend-only, no API or schema changes).

---

## 1. What was built

`components/NotificationPrefsCard.tsx` — new component mounted inside `SettingsPage` in place of the prior three-row Notifications group:

| Surface             | Before                                                    | After                                                                        |
|---------------------|-----------------------------------------------------------|------------------------------------------------------------------------------|
| Header              | "Notifications" group title (plain)                       | "NOTIFICATION PREFERENCES" with gold left-border accent + "{N}/9 ALERTS ENABLED" counter |
| Bulk actions        | None                                                      | **All On** / **All Off** buttons — set all 9 toggles in one tap            |
| Categories          | 1 group, 3 rows (all bound to single `notifications_on`)  | 4 category sections: TRADING / SIGNALS / SYSTEM / REPORTS                   |
| Per-category count  | None                                                      | "{enabled}/{total} ON" badge in each category header                         |
| Per-alert toggles   | 3 rows sharing one server flag                            | 9 independent toggles, each with ON/OFF status badge + description text      |
| Persistence         | Server-side `notifications_on` boolean (API call)         | localStorage key `notif_prefs` (client-side, instant, no round-trip)        |

### Alert inventory (9 items)

| Category | Key              | Description                                         |
|----------|------------------|-----------------------------------------------------|
| TRADING  | trade_opened     | Alert when a new position is entered                |
| TRADING  | trade_closed     | Alert on take-profit, stop-loss, or expiry          |
| TRADING  | position_resolved | Win/loss notification when market settles          |
| SIGNALS  | signal_detected  | New high-confidence signal found by scanner         |
| SYSTEM   | system_status    | Bot online/offline & connectivity changes           |
| SYSTEM   | bot_errors       | Critical errors that require attention              |
| SYSTEM   | kill_switch      | Alert when emergency stop activates                 |
| SYSTEM   | low_balance      | Notify when wallet balance drops below threshold    |
| REPORTS  | daily_report     | End-of-day summary delivered via Telegram           |

### Public exports from NotificationPrefsCard.tsx

- `NotifPrefs` type — `Record<PrefKey, boolean>` for consumers
- `NOTIF_PREFS_KEY = "notif_prefs"` — shared localStorage key
- `loadNotifPrefs()` — reads + merges with defaults; safe against quota errors / corrupt JSON

---

## 2. Current system architecture

```
SettingsPage
  ├── Trading group (Auto Redeem)
  ├── NotificationPrefsCard  ← REPLACED old 3-row group
  │     ├── Header: "NOTIFICATION PREFERENCES" + {enabled}/9 + All On/All Off
  │     ├── TRADING  section (⚡, 3 items)
  │     ├── SIGNALS  section (📡, 1 item)
  │     ├── SYSTEM   section (🖥, 4 items)
  │     └── REPORTS  section (📊, 1 item)
  │           each item: name + ON/OFF badge + description + Toggle
  ├── Display group (Advanced Mode)
  └── Account group
```

Prefs persisted to `localStorage["notif_prefs"]` as a JSON object keyed by `PrefKey` slug. Defaults to all-ON on first visit or after a localStorage clear. Idempotent — merges stored JSON with `DEFAULT_PREFS` so new keys added in future lanes default to ON automatically.

Backend `notifications_on` flag is no longer read or written by the Settings page (the dead `handleNotifToggle` handler + `notifOn` local var were removed). The server flag remains in the schema and can be repurposed or removed in a future lane.

---

## 3. Files created / modified

| Action   | Path |
|----------|------|
| Created  | `projects/polymarket/crusaderbot/webtrader/frontend/src/components/NotificationPrefsCard.tsx` |
| Modified | `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/SettingsPage.tsx` (import + replace Notifications group + remove unused handleNotifToggle + notifOn) |
| Created  | `projects/polymarket/crusaderbot/reports/forge/notification-prefs-ui.md` |

No backend / API / schema / migration changes.

---

## 4. What is working

- `tsc --noEmit` clean (zero errors or warnings).
- All 9 toggles render with correct category grouping, color tokens (`var(--gold)`, `var(--cyan)`, `var(--ink-2)`, `var(--grn)`), and icon set matching the owner's screenshot.
- ON/OFF status badge per toggle updates immediately on click.
- Category "{enabled}/{total} ON" header badge recalculates on any toggle change.
- "{N}/9 ALERTS ENABLED" header counter stays live.
- All On / All Off set all toggles in a single setState call.
- Prefs persist to `localStorage["notif_prefs"]`; survive page reload.
- Corrupt or missing localStorage falls back to `DEFAULT_PREFS` (all ON) without throwing.
- `loadNotifPrefs()` exported for future consumption by AlertCenter or other consumers.
- Existing SettingsPage sections (Trading, Display, Account) unchanged.

---

## 5. Known issues

- **AlertCenter does not yet filter by prefs**: the panel still shows all alerts regardless of individual toggle state. A follow-up lane should read `loadNotifPrefs()` in `App.tsx` and gate the `setAlerts` push per alert type. This is intentional scope separation — UI first, wiring second.
- **Server `notifications_on` flag orphaned**: the backend column still exists but is no longer written from the Settings page. Can be repurposed as a master kill-switch or dropped in a future migration.
- **No Telegram-side enforcement**: per-alert prefs are client-only. Telegram delivery is unchanged.

---

## 6. What is next

- WARP🔹CMD review + Fly redeploy (frontend ships with the bot deploy pipeline).
- Owner smoke test: Settings → Notification Preferences — toggle individual alerts, verify ON/OFF badge updates, verify All On/All Off, reload page and confirm prefs survive.
- Optional follow-up lane: wire `loadNotifPrefs()` into `App.tsx` alert push path so the bell panel only shows alerts matching enabled prefs.

---

Validation Tier: MINOR
Claim Level: NARROW INTEGRATION
