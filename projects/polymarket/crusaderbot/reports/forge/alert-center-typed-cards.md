# WARP•FORGE Report — alert-center-typed-cards

## 1. What Was Built

End-to-end redesign of the WebTrader AlertCenter so trade-lifecycle notifications render as **typed React cards** with proper visual hierarchy, instead of dumping the Telegram HTML+ASCII text body verbatim.

Owner-reported symptom (screenshot): "Trade opened" card showed `📋 TRADE OPENED` followed by an ASCII box of `Market │ Bitcoin Up or Down - May 30,` / `Side │ NO` / `Size │ $4.01` / etc. — the raw Telegram message text rendered in a web panel that doesn't have a fixed-width font. Same trade emitted 3 separate cards (Trade Opened + Strategy Exit + Trade Closed).

Root cause: `services/trade_notifications/notifier.py` builds a single string for Telegram (HTML `<b>`, `<pre>` ASCII box, `│` pipes) and `persist_user_alert` writes that same string into `system_alerts.title/body`. The web AlertCenter only stripped HTML tags — the pipes and indentation survived.

Fix: add `alert_kind TEXT` + `metadata JSONB` columns to `system_alerts`; refactor every trade notification call site to ALSO emit a structured `{market_label, side, size_usdc, entry_price, exit_price, tp_pct, sl_pct, pnl_usdc, strategy, mode, ...}` dict; AlertCenter dispatches by `alert_kind` to typed renderers (`EntryBody`, `ExitBody`, `ExpiredBody`, `FailedBody`) with proper colors (YES green / NO red, P&L green/red/muted), price/money formatters, market title truncation+tooltip, mode badge for non-paper.

Plus 3 UX bugs fixed:
- **Dedup redundant strategy_exit cards**: when a `strategy_exit` and a more-specific exit (tp_hit/sl_hit/resolution_*/manual/force/emergency) fire for the same `market_id` within 60s, the strategy_exit is hidden client-side (DB row preserved for audit).
- **Header layout collision**: "10 NEW" badge and "Mark all read" link competed for horizontal space at mobile widths → split into two-row layout (title+badge+×, then Mark-all-read on its own line right-aligned).
- **`"$+0.00"` formatting**: now renders as `Even` for zero P&L, `+$1.84` / `−$2.50` for non-zero (with proper minus glyph, not hyphen).

Backward compat: legacy rows (pre-072 migration) have `alert_kind=NULL` + `metadata={}` → AlertCenter falls back to the `FallbackBody` plain-text path. Telegram delivery path is **untouched** — every Telegram message still ships the HTML+`<pre>` box exactly as before.

## 2. Current System Architecture

```
   ┌─────────────────────────────────────────────────┐
   │  Trade lifecycle event (exit_watcher / engine)   │
   └──────────────┬──────────────────────────────────┘
                  │
       ┌──────────┴──────────┐
       │                     │
       ▼                     ▼
TradeNotifier.notify_*   alert_user_* (monitoring/alerts.py)
       │                     │
       └──────────┬──────────┘
                  │
                  ▼
      route_outgoing_alert(
        web_title, web_body,        ← Telegram text (HTML+<pre>)
        alert_kind="tp_hit",         ← NEW: typed discriminator
        metadata={market_label,      ← NEW: structured fields
                  side, exit_price,
                  pnl_usdc, mode, ...}
      )
                  │
       ┌──────────┴──────────┐
       │                     │
       ▼                     ▼
  persist_user_alert     Telegram send
  (INSERT system_alerts) (unchanged: HTML+<pre>)
       │
       ▼
  GET /api/web/alerts
  → AlertItem{alert_kind, metadata}
       │
       ▼
  AlertCenter.tsx
   dispatch by alert_kind →
     EntryBody | ExitBody | ExpiredBody | FailedBody | FallbackBody
```

`alert_kind` discriminators (matches `NotificationEvent` + `monitoring/alerts.py` naming):
`trade_opened | copy_trade_opened | tp_hit | sl_hit | resolution_win | resolution_loss | force_close | strategy_exit | manual_close | emergency_close | market_expired | close_failed`.

## 3. Files Created / Modified

| Path | Change |
|---|---|
| `projects/polymarket/crusaderbot/migrations/072_system_alerts_metadata.sql` | NEW — additive ADD COLUMN alert_kind TEXT + metadata JSONB NOT NULL DEFAULT '{}'::jsonb + partial index on alert_kind |
| `projects/polymarket/crusaderbot/webtrader/backend/notification_prefs.py` | `persist_user_alert(...)` + `route_outgoing_alert(...)` accept new `alert_kind` + `metadata` kwargs; INSERT writes JSONB via `json.dumps` |
| `projects/polymarket/crusaderbot/services/trade_notifications/notifier.py` | `_send(...)` forwards `alert_kind` + `metadata`; 5 callers (notify_entry / notify_tp_hit / notify_sl_hit / notify_manual_close / notify_emergency_close) build structured dicts |
| `projects/polymarket/crusaderbot/monitoring/alerts.py` | New `_exit_metadata(...)` helper; `_send_user_exit_alert(...)` forwards metadata; all 9 `alert_user_*` call sites pass it (tp_hit, sl_hit, resolution_win, resolution_loss, force_close, strategy_exit, manual_close, market_expired, close_failed) |
| `projects/polymarket/crusaderbot/webtrader/backend/schemas.py` | `AlertItem` schema extended with `alert_kind: Optional[str]` + `metadata: dict = {}` |
| `projects/polymarket/crusaderbot/webtrader/backend/router.py` | `/alerts` SELECT extended with `alert_kind, metadata`; new `_coerce_alert_metadata(...)` helper handles asyncpg JSONB-as-str codec quirk |
| `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` | NEW `AlertKind` union type + `AlertMetadata` interface + `AlertItem` extended |
| `projects/polymarket/crusaderbot/webtrader/frontend/src/components/AlertCenter.tsx` | Rewritten — typed card renderers per alert_kind, KIND_ICON map, P&L coloring, side coloring, market title truncate+tooltip, mode badge for non-paper, two-row header layout, client-side dedup (60s window) |

## 4. What Is Working

- Migration `072_system_alerts_metadata.sql` applied to Supabase prod (`apply_migration` verified). `system_alerts` now has `alert_kind`, `metadata` columns + partial index.
- `persist_user_alert` writes structured rows when called with the new kwargs; legacy callers (no kwargs) write rows with `alert_kind=NULL` + `metadata={}` (no behaviour change).
- 30 hermetic regression tests pass (test_notification_prefs.py + test_trade_notifications.py).
- py_compile clean on all 5 modified Python files.
- Frontend: AlertCenter dispatches by `alert_kind`. Each typed renderer (Entry, Exit, Expired, Failed) renders structured fields. Legacy rows fall back to plain-text body. Dedup removes strategy_exit when a sibling exit fires for the same market within 60s.
- Telegram delivery: unchanged. Every existing TG notification still ships the HTML+`<pre>` ASCII box exactly as it did before.
- Operator escape: setting `alert_kind=None` on any call falls back to legacy rendering; deleting the partial index is a one-line revert.

## 5. Known Issues

- **Pre-072 alert rows**: 30 existing rows in production have `alert_kind=NULL` → they render via the `FallbackBody` plain-text path (no typed card). They will roll off naturally as new trades fire (the panel only shows last 50 alerts after the `alerts_ack_at` watermark).
- **No new test for the typed renderers**: the frontend has no test framework wired in this repo. The dedup helper is exported from `AlertCenter.tsx` so a future test suite can pin it without rewriting the panel.
- **Mode badge is paper-only suppress**: if a user is in LIVE mode the badge renders "LIVE" in amber on every trade card. Acceptable — operator wants explicit LIVE attribution. Switch to a smaller pill in a follow-up if it crowds the title.

## 6. What Is Next

WARP🔹CMD review + merge + Fly.io redeploy (frontend rebuild ships the typed cards; backend writer ships the new schema writes). After deploy:
- Verify next trade-open / TP-hit / SL-hit alerts render as typed cards (open AlertCenter, look for ⚡ entry card + 🎯 TP card + colored P&L line).
- Verify dedup: a `strategy_exit` event paired with a `tp_hit` for the same market should show ONE card (the tp_hit), not two.
- After ≥10 new typed alerts arrive, sample `SELECT alert_kind, COUNT(*) FROM system_alerts GROUP BY alert_kind` to confirm coverage.

Sibling lane (`WARP/R00T/admin-drawer-complete`) remains queued — adds the gap fields (timeframe, selected_assets, per-user paused toggle, TP% label fix, read-only context block) to the admin user-detail drawer.

---

**Validation Tier**: MAJOR
**Claim Level**: NARROW INTEGRATION
**Validation Target**: trade-lifecycle alert rendering surface (DB schema + writer path + frontend); Telegram delivery path explicitly unchanged
**Not in Scope**: AdminUserDrawer gap fields (separate lane), backend notification preferences UI, push notifications, alert sound, alert archive/export
**Suggested Next Step**: WARP🔹CMD review + merge + Fly.io redeploy; then queue the AdminUserDrawer completion lane.
