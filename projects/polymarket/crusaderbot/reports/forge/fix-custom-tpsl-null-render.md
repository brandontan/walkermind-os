# WARP•R00T FORGE REPORT — fix-custom-tpsl-null-render

Branch: `WARP/ROOT/fix-custom-tpsl-null-render`
Role: WARP•R00T (owner-reported: dashboard blank after setting strategy)
Validation Tier: MAJOR (user-facing crash / white screen)
Claim Level: NARROW INTEGRATION

## 1. What was fixed
Bug: user set a custom SL-only risk (tp_pct = NULL in DB — the custom TP/SL-only
feature from PR #1447) and the WebTrader dashboard went BLANK (white screen).

Root cause (two parts):
1. AutoTradePage.load() pre-filled the custom form with
   `String(Math.round(s.tp_pct * 100))`; with tp_pct null this produced "0"
   (wrong UX) and the type contract said tp_pct was always a number, hiding the
   null path. The frontend treated tp_pct/sl_pct as non-null everywhere.
2. NO ErrorBoundary existed — any render throw crashed the ENTIRE React tree to
   a blank white screen instead of an isolated, recoverable fallback.

Fixes:
- AutoTradePage: null-safe custom prefill (blank input when tp/sl null, not "0").
- Types made honest: AutoTradeState.tp_pct/sl_pct = `number | null` (frontend) /
  `Optional[float]` (backend schema). get_autotrade now returns None (not 0.0)
  when unset, so the UI can distinguish "0%" from "not set". TS then verified no
  other null-unsafe tp/sl dereference exists.
- New ErrorBoundary wraps the routed pages: a render error now shows a "Something
  broke — Reload" fallback (chrome/nav survive) instead of blanking the whole app.

## 2. Files modified
- webtrader/frontend/src/pages/AutoTradePage.tsx (null-safe custom prefill)
- webtrader/frontend/src/lib/api.ts (AutoTradeState tp/sl nullable)
- webtrader/frontend/src/components/ErrorBoundary.tsx (new)
- webtrader/frontend/src/App.tsx (wrap routes in ErrorBoundary)
- webtrader/backend/schemas.py (AutoTradeState tp/sl Optional)
- webtrader/backend/router.py (get_autotrade returns None when unset)
- tests/test_admin_console.py (+1: SL-only get_autotrade returns null tp)

## 3. What is working
SL-only / TP-only custom risk no longer blanks the dashboard; tp/sl serialize as
null; a render error is now contained by the ErrorBoundary. 17 admin tests pass;
full suite 2057; ruff + py_compile + tsc + vite build clean.

## 4. Known issues
None. ErrorBoundary is app-wide defense so a future null-deref can't white-screen.

## 5. What is next
WARP🔹CMD review + merge → deploy. User re-loads dashboard (no longer blank).
