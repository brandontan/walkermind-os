# WARP•R00T FORGE REPORT — close-by-trigger-label

Branch: `WARP/ROOT/close-by-trigger-label`
Role: WARP•R00T (owner follow-up to #1443)
Validation Tier: **MINOR** (frontend label wording only — no runtime/trading logic)
Claim Level: FOUNDATION
Validation Target: WebTrader "Closed By" + status pills name the trigger bucket TP/SL/TIME on every close, including resolutions.
Not in Scope: backend close logic (unchanged); Telegram alert wording.
Suggested Next Step: WARP🔹CMD review + merge.

---

## 1. What was built

Follow-up to the resolution-relabel (#1443). Owner wants every close to keep a
TP / SL / TIME trigger annotation while still showing Won/Lost for resolutions.
No backend change needed — the stored reason already encodes it:
`resolution_win` is TP-side (profit threshold crossed at settlement),
`resolution_loss` is SL-side, and strategy/horizon/expired/`resolution` are TIME.

Updated the WebTrader label maps:

- Portfolio "Closed By" (`EXIT_FULL_LABEL`): `resolution_win` → "Take Profit
  (TP) — Resolved Won"; `resolution_loss` → "Stop Loss (SL) — Resolved Lost";
  `strategy_exit`/`horizon_exceeded`/`market_expired`/`resolution` → "Time Exit (TIME)".
- Portfolio list pill (`EXIT_LABEL` + `EXIT_TONE`): `resolution_win` → "TP · WON"
  (green); `resolution_loss` → "SL · LOST" (red); TIME group → "TIME" (cyan).
- Dashboard recent-trades pill (`RECENT_PILL_LABEL`): same TP·WON / SL·LOST / TIME.

## 2. Current system architecture

Pure presentation. `exit_reason` values and close logic are unchanged from #1443.

## 3. Files modified (full repo-root paths)

- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/DashboardPage.tsx`

## 4. What is working

- Closes show TP/SL/TIME on the pill and in "Closed By"; resolutions add Won/Lost.
- tsc --noEmit + vite build clean.

## 5. Known issues

- None. Telegram alert wording ("Market resolved — Won/Lost") left as-is; can
  align to the same TP/SL/TIME phrasing later if wanted.

## 6. What is next

WARP🔹CMD review + merge → Fly deploy.
