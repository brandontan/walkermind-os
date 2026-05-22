# WARP-71 — Premium Terminal UI (V5 Blueprint, HTML mode)

Issue: #1291
Branch: WARP/warp71-premium-terminal-ui
Role: WARP•FORGE
Validation Tier: STANDARD
Claim Level: VISUAL/UX
Validation Target: All MVP render functions emit Telegram HTML; `pre_block` for numerical groups; `DIV` (━ × 32) section separator; `_send` parse_mode → HTML
Not in Scope: new screens, new handlers, dispatcher, DB, domain/trading logic, activation guards

## 1. What was built

Switched the MVP Telegram surface from Markdown to **HTML parse mode** ("V5
premium terminal — Bloomberg-lite in your pocket"). Numerical data now renders
in monospaced `<pre>` blocks so columns align on every client; grouped
key/value rows use the `├── / └──` tree; `<b>` headers, `<code>` inline values,
`<i>` CTAs, and a heavy 32-char `DIV` (━) separate major sections.

This is a deliberate reversal of WARP-67's "flat Markdown, no box-drawing"
decision, per WARP🔹CMD direction in #1291: box-drawing now lives alongside HTML
`<pre>` alignment, which is the explicit V5 design standard.

## 2. Current system architecture

`bot/ui/tree.py` is the single rendering vocabulary. Converting its helpers to
HTML flips every `join_blocks`-based renderer in `messages_mvp.py` (the bulk of
the 66 functions) to HTML automatically. The raw-f-string / blueprint screens
were hand-rewritten. All MVP handlers send through
`bot/handlers/mvp/_send.send_or_edit`, whose `parse_mode` default is now `HTML`,
so the switch is contained to the MVP surface (no non-MVP importer of
`ui.tree` exists; admin/notification paths are independent).

## 3. Files created / modified

- Modified: `projects/polymarket/crusaderbot/bot/ui/tree.py`
- Modified: `projects/polymarket/crusaderbot/bot/messages_mvp.py`
- Modified: `projects/polymarket/crusaderbot/bot/handlers/mvp/_send.py`
- Created: `projects/polymarket/crusaderbot/reports/forge/warp71-premium-terminal-ui.md`
- Updated: `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- Updated: `projects/polymarket/crusaderbot/state/WORKTODO.md`
- Updated: `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- `tree.py`: `html_escape` (escapes `& < >`, `&` first); `DIV = "━"×32`,
  `LIGHT_DIV = "┄"×16`; `title`→`<b>`, `leaf`/`section`→`├──/└──` tree with
  `<code>` values, `cta`→`<i>`, new `pre_block` monospaced `<pre>` builder.
  `md_escape`, `DIVIDER`, `CARD_DIVIDER` retained as back-compat aliases
  (`md_escape = html_escape`; dividers → `DIV`).
- `messages_mvp.py`: imports updated; dashboard, dashboard_new_user,
  autotrade_home, settings_home, portfolio_home, positions_list,
  copy_wallet_card, markets_trending, notif_trade_opened hand-rewritten to the
  blueprint HTML/`pre_block` layout. All other renderers HTML via helpers.
- `_send.py`: `parse_mode` default `"Markdown"` → `"HTML"`.
- `py_compile` clean on all three modules.
- Standalone render smoke test passed (dashboard / autotrade / settings /
  positions / notif): valid HTML, aligned `<pre>` columns, `&`→`&amp;` on the
  "Risk & Safety" title.

## 5. Known issues

- Full `pytest tests/` not exercised in this remote container — runtime deps
  (`asyncpg`, `python-telegram-bot`, cryptography Rust chain) unsatisfiable here,
  same posture as WARP-58/59/60/61. No existing test asserts on the MVP
  renderer / `ui.tree` output or the MVP `_send` parse_mode (verified by grep),
  so no test realignment was required. CI / WARP🔹CMD should run
  `pytest tests/ -v --tb=short` before merge.
- Box-drawing `├── / └──` is intentionally reintroduced per #1291. On-device
  render verification (Android/iOS Telegram) recommended post-deploy to confirm
  the HTML-mode tree renders as designed (this was the original WARP-67 concern;
  HTML `<pre>` alignment is the V5 mitigation, but the tree rows themselves are
  outside `<pre>`).

## 6. What is next

- WARP🔹CMD review. Tier STANDARD.
- Fly.io redeploy + on-device render check (Android/iOS).

## Suggested Next Step

WARP🔹CMD review required. Tier: STANDARD. No migration.
Source: projects/polymarket/crusaderbot/reports/forge/warp71-premium-terminal-ui.md
