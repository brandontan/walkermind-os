# WARP•R00T FORGE REPORT — exit-label-trigger

Branch: `WARP/root-exit-label-trigger`
Role: WARP•R00T (owner follow-up — corrects #1443 / close-by-trigger-label)
Validation Tier: **MINOR** (frontend label wording only — no runtime/trading logic)
Claim Level: FOUNDATION
Validation Target: WebTrader exit pills + "Closed By" name the ACTUAL close trigger (TP / SL / TIME / STRATEGY); win/loss conveyed by PnL colour, never by mislabelling.
Not in Scope: backend close logic / `exit_reason` values (unchanged); Telegram alert wording; AlertCenter (already honest — shows "Settled").
Suggested Next Step: merged by WARP•R00T → Fly CD deploy.

---

## 1. What was built

Owner reported a resolution win (+241.7%, `resolution_win`) displaying as **"TP HIT"**.
Root cause: the prior decision (#1443 / `close-by-trigger-label`) deliberately mapped
`resolution_win → "TP · WON"` and `resolution_loss → "SL · LOST"` — treating a
time/expiry resolution as "TP-side / SL-side". Owner reversed that: the label must
name the real trigger ("klo close by TP ya tulis TP, klo close by expired time ya
harus time — sesuai triggernya").

New mapping (label = trigger; outcome = colour):

| exit_reason | pill | colour |
|---|---|---|
| `tp_hit` | TP | green (always) |
| `sl_hit` | SL | red (always) |
| `resolution_win` / `resolution_loss` / `resolution` / `market_expired` / `horizon_exceeded` | TIME | follows PnL (green win / red loss) |
| `strategy_exit` | STRATEGY | follows PnL |
| `manual` | CLOSED/MANUAL | neutral |
| `force_close` | FORCED | gold |
| `close_failed` | ERROR | red |

A TIME close that won shows a green `TIME` pill + green PnL; a TIME close that lost
shows red. No close is ever called "TP"/"SL" unless that threshold actually fired.

## 2. Current system architecture

Pure presentation. `exit_reason` values, close logic, and PnL math are unchanged.
The static `EXIT_TONE` map (which hard-coded resolution colours) was removed in favour
of a trigger-aware tone derived from the existing `tone`/PnL sign already computed per row.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx`
  (EXIT_LABEL, EXIT_FULL_LABEL rewritten; static EXIT_TONE removed; `exitToneClass`
  now derived TP→green / SL→red / else→PnL tone; "Closed By" detail uses it)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/DashboardPage.tsx`
  (RECENT_PILL_LABEL rewritten)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`
- `projects/polymarket/crusaderbot/reports/forge/exit-label-trigger.md` (this report)

## 4. What is working

- Portfolio pill + Dashboard recent-activity pill + "Closed By" detail all name the
  real trigger; resolutions read TIME (not TP/SL).
- `tsc --noEmit` clean; `vite build` clean.

## 5. Known issues

- None. AlertCenter already uses honest "Settled"/"Resolved" wording — left as-is.

## 6. What is next

Merged by WARP•R00T → Fly CD deploy picks up the new bundle on next release.
