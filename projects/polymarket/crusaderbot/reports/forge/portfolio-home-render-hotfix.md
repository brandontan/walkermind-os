# WARP•FORGE Report — portfolio-home-render-hotfix

Branch: WARP/portfolio-home-render-hotfix
Validation Tier: MINOR
Claim Level: NARROW INTEGRATION
Validation Target: `bot/handlers/mvp/portfolio.py` `show_home` — reconcile the `render_portfolio_home()` call with the renderer signature in `bot/messages_mvp.py`.
Not in Scope: any rendering logic, message text, keyboard layout, domain/strategy code.

## 1. What was built

Signature-alignment hotfix for a runtime `TypeError` hit on the MVP Portfolio home screen:

```
TypeError: render_portfolio_home() got an unexpected keyword argument 'today_trades'
```

`bot/messages_mvp.py:render_portfolio_home(*, balance, equity, open_positions, today_pnl, week_pnl)`
is keyword-only and never accepted `today_trades` / `today_win_rate`, but `show_home`
passed both. The two extra kwargs are not used by the renderer (it shows Balance / Equity /
Positions / Today PnL / 7-Day PnL), so the caller was trimmed to the accepted kwargs. No
rendering logic changed.

Root cause is PRE-EXISTING (introduced by commit `9caaabc`, 2026-05-23 — verified via
`git blame` on both the caller and the signature); it was NOT introduced by the keyboard-v2
migration (PR #1334), which only changed the import line in this handler. The runtime crash
surfaced when the MVP Portfolio home screen was opened.

An AST scan of every `bot/handlers/mvp/*.py` against the `render_*` signatures in
`messages_mvp.py` found this as the ONLY keyword-argument mismatch — no others.

## 2. Current system architecture

Unchanged. One caller line edited; `render_portfolio_home` untouched.

## 3. Files created / modified

MODIFIED: `projects/polymarket/crusaderbot/bot/handlers/mvp/portfolio.py` (drop unsupported
`today_trades` / `today_win_rate` kwargs from the `render_portfolio_home` call).
`projects/polymarket/crusaderbot/state/CHANGELOG.md` (append).

## 4. What is working

- `show_home` renders without `TypeError` (exercised directly via the empty-user path).
- AST scan: 0 remaining `render_*` kwarg mismatches across `handlers/mvp/`.
- pytest portfolio/mvp subset green; full suite unaffected.

## 5. Known issues

- None for this fix. (Separately tracked: the pre-existing `settings:back`
  `main_menu(strategy_key=...)` latent bug noted in the keyboard-v2 report.)

## 6. What is next

Suggested Next Step: WARP🔹CMD review + merge the hotfix.
