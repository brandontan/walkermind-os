# WARP•R00T FORGE REPORT — dashboard-global-pause-badge

Branch: `WARP/ROOT/dashboard-global-pause-badge`
Role: WARP•R00T (owner-reported UX gap, follow-up to #1450)
Validation Tier: STANDARD (user-facing status display)
Claim Level: NARROW INTEGRATION

## 1. What was built
After #1450 fixed the functional global-gate (a globally-disabled strategy no
longer trades), the user dashboard still showed the preset as "ACTIVE" — the
badge only reflected the user's selected preset, not the operator's global
on/off. Owner found this confusing ("set copy_trade on but strategy still off").

Fix: the dashboard now shows "PAUSED (ADMIN)" instead of "ACTIVE" when the
active preset's underlying strategy is globally disabled.

- Backend GET /api/web/autotrade now resolves the active preset → strategy
  (_PRESET_TO_STRATEGY, mirrors signal_scan_job._PRESET_ALLOWED) and reads
  strategies.enabled, returning active_preset_globally_enabled (default True;
  missing row = enabled).
- AutoTradeState schema + frontend AutoTradeState type gain the field.
- AutoTradePage badge: ACTIVE (gold) when enabled, "PAUSED (ADMIN)" (muted) when
  the strategy is globally off.

No trading-logic change — purely reflects the existing global gate in the UI.

## 2. Files modified
- webtrader/backend/router.py (_PRESET_TO_STRATEGY + get_autotrade global lookup)
- webtrader/backend/schemas.py (AutoTradeState.active_preset_globally_enabled)
- webtrader/frontend/src/lib/api.ts (type field)
- webtrader/frontend/src/pages/AutoTradePage.tsx (PAUSED (ADMIN) badge)
- tests/test_admin_console.py (+4: globally disabled/enabled/missing-row + mapping)

## 3. What is working
Dashboard shows PAUSED (ADMIN) when the active preset's strategy is globally off;
ACTIVE otherwise. 16 admin-console tests pass; full suite 2056; ruff + tsc + vite clean.

## 4. Known issues
None.

## 5. What is next
WARP🔹CMD review + merge → deploy. Completes the global on/off UX (functional gate #1450 + this display).
