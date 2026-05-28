# Forge Report — notif-followups
Branch: WARP/ROOT-notif-followups
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: notification dedup, low_balance monitor, auth_events decision
Not in Scope: LIVE-flag flip, UI changes, per-user CLOB balance fetch

---

## 1. What was built

Three open follow-ups from the 2026-05-29 handoff brief closed:

**A. Duplicate notification dedup**
Added in-process idempotency cache to `route_outgoing_alert()` in `notification_prefs.py`. Key: `(user_id, alert_key, dedup_key)` with a 30 s TTL. Second call within window returns `False` (suppress TG) and skips the web insert. Three surfaces that independently wrapped the same lifecycle now pass `dedup_key=market_id` — suppressing duplicate web rows and duplicate TG messages for the same (user, market, alert_key) within the window.

**B. `low_balance` monitor**
Added `LOW_BALANCE_THRESHOLD_USDC: float = 50.0` (config.py). Added `alert_user_low_balance()` (monitoring/alerts.py) with a 1-hour per-user cooldown. Added `check_balance_alerts()` job (scheduler.py) that queries `users JOIN wallets WHERE telegram_user_id IS NOT NULL AND paused = FALSE`, compares each user's `balance_usdc` against threshold, and fires the alert. Registered as an hourly `AsyncIOScheduler` job.

**C. `auth_events` decision**
DROP. Not present in `ALERT_KEYS`, not in UI, not wired anywhere. Wiring would be scope expansion without identified user value. Removed from open follow-up list; no code change.

---

## 2. Current system architecture

Notification routing (after this change):

```
trade event
    ├── notification_service._send_safe(market_id=market_id)
    ├── trade_notifications/notifier._send(market_id=market_id)
    └── monitoring/alerts._send_user_exit_alert(market_id=market_id)
            ↓
        route_outgoing_alert(dedup_key=market_id)
            ├── dedup check → if hit within 30s: return False (suppress both web+TG)
            ├── persist_user_alert() → system_alerts INSERT (web mirror)
            └── should_notify(user, alert_key, "tg") → TG send decision

balance monitor (hourly):
    check_balance_alerts()
        → wallets JOIN users WHERE paused=FALSE
        → alert_user_low_balance() per user
            → route_outgoing_alert(alert_key="low_balance", dedup_key=None)
            → 1h per-user cooldown in _last_alert_at
```

---

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/webtrader/backend/notification_prefs.py` — `_DEDUP_CACHE` + `_DEDUP_LOCK` + `_DEDUP_TTL_SEC`; `route_outgoing_alert` gains `dedup_key` param + dedup logic; `_evict_stale_dedup()` + `_clear_dedup_cache()` helpers
- `projects/polymarket/crusaderbot/services/notification_service.py` — `_send_safe` gains `market_id: str | None`; 3 callers (`_on_position_opened`, `_on_position_closed`, `_on_copy_trade_executed`) pass `market_id` to `_send_safe`; `route_outgoing_alert` call passes `dedup_key=market_id`
- `projects/polymarket/crusaderbot/services/trade_notifications/notifier.py` — `_send` passes `dedup_key=market_id` to `route_outgoing_alert`
- `projects/polymarket/crusaderbot/monitoring/alerts.py` — `_alert_user` passes `dedup_key=market_id`; `alert_user_low_balance()` added with `_LOW_BALANCE_COOLDOWN_SEC=3600`
- `projects/polymarket/crusaderbot/config.py` — `LOW_BALANCE_THRESHOLD_USDC: float = 50.0` added
- `projects/polymarket/crusaderbot/scheduler.py` — `from .monitoring import alerts as monitoring_alerts` import; `check_balance_alerts()` job; `sched.add_job(check_balance_alerts, "interval", hours=1, ...)`
- `projects/polymarket/crusaderbot/tests/test_notification_prefs.py` — 3 new dedup tests (dup suppressed / different keys not suppressed / None key not suppressed)

---

## 4. What is working

- `test_notification_prefs.py`: 14/14 pass (was 11/11; +3 dedup tests)
- Syntax: `py_compile` clean on all 7 files
- Dedup semantics verified: second call with same (user, alert_key, dedup_key) within TTL returns `False`; different dedup_key or `None` key not affected
- `low_balance` monitor wired into APScheduler hourly slot; skips when `LOW_BALANCE_THRESHOLD_USDC=0` or balance ≥ threshold; 1h cooldown prevents spam
- `auth_events` decision recorded: DROP (no code change needed)

---

## 5. Known issues

- `check_balance_alerts` uses DB-tracked `wallets.balance_usdc` (paper credit balance), not live CLOB collateral. In PAPER mode this is intentional — the paper balance is what matters. In LIVE mode, `wallets.balance_usdc` will reflect real deposited capital once the deposit sweep path (#1403) keeps it reconciled.
- Dedup window is in-process only. Multi-instance Fly deployments (if scaled beyond 1) would each have an independent cache. Current Fly config runs 1 machine — acceptable. Multi-instance hardening (Redis-backed dedup) is deferred.
- `test_warp53_reliability_hardening.py` collection fails in this container (cffi/cryptography native deps not installed). Not a code regression — the test file itself is unchanged; failure is environment-only.

---

## 6. What is next

- Axis #5 — `WARP/ROOT-observability-ops` (structlog M-3 for top-8 stdlib logging files, Sentry coverage, healthcheck)
- Axis #4 — `WARP/ROOT-onboarding-ux`
- WARP🔹CMD review required.
  Source: projects/polymarket/crusaderbot/reports/forge/notif-followups.md
  Tier: STANDARD

---

Suggested Next Step: WARP🔹CMD review → merge → start Axis #5 WARP/ROOT-observability-ops
