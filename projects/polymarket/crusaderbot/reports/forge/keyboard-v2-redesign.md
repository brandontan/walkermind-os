# WARP•FORGE Report — keyboard-v2-redesign

Branch: WARP/keyboard-v2-redesign
Validation Tier: STANDARD
Claim Level: FULL RUNTIME INTEGRATION
Validation Target: Telegram keyboard layer migration — `bot/keyboards/` (legacy) → `bot/keyboards_v2/` (redesign), promoted to `bot/keyboards/`. All handler imports, dispatcher routing, and keyboard rendering for every Telegram surface.
Not in Scope: domain/, services/, integrations/, wallet/, jobs/ (untouched); risk constants; execution/trading logic; copy_trade/signal_following/market_card/referral keyboard *redesign* (copied as-is, deferred); the mvp keyboard tree *merge* into main modules (copied as-is, deferred).

## 1. What was built

Full migration of the CrusaderBot Telegram keyboard layer from the legacy 3-generation
`bot/keyboards/` module to the redesigned `keyboards_v2/`, then promotion of `keyboards_v2/`
to the active `bot/keyboards/` with the legacy module archived at `bot/_keyboards_archive/`.

Key deliverables:
- Installed the 13-file `keyboards_v2` redesign (unified `_common.py`, single `⬅ Back`
  variant, domain-scoped callback prefixes).
- Gap-filled `keyboards_v2` so it is a behavior-preserving superset of every keyboard
  function the live handlers use. Where a v2 redesign emitted the same `callback_data`,
  handlers use the v2 drop-in; where the legacy `callback_data` differed (e.g. `p5:*`,
  `auto_trade:*`, `panel:*`, `ops:refresh/pause/lock`, `start:*`, `mytrades:*`,
  `close_position:*`, `position:fc_*`), the legacy function was ported verbatim into the
  matching v2 domain file under a distinct name and aliased at the handler import — so
  no `callback_data` changed for any existing action.
- New 2-step preset flow: risk-tier picker → preset list (`preset:tiers`, `preset:tier:{tier}`),
  integrated into the existing `preset_callback` router (no new dispatcher pattern needed).
- New emergency progressive disclosure (`emergency:home` / `emergency:more` / `emergency:ask:*`
  / `emergency:status`), integrated into the existing `emergency_callback` router.
- The self-contained `mvp/` keyboard tree and the 4 kept modules (copy_trade,
  signal_following, market_card, referral) were copied as-is into the new module so their
  callbacks/signatures are preserved exactly.
- Migrated all 24 handler files + repointed affected tests; archived legacy.

## 2. Current system architecture

```
bot/keyboards/                 (was keyboards_v2 — now the active module)
  _constants.py _common.py __init__.py
  main_menu.py dashboard.py autotrade.py portfolio.py settings.py
  emergency.py customize.py onboarding.py wallet.py admin.py setup.py
  mvp/        (copied as-is — parallel surface, own _common, own callbacks)
  copy_trade.py signal_following.py market_card.py referral.py  (copied as-is)
bot/_keyboards_archive/        (legacy module, retained for reference + legacy unit tests)
```

Callback routing unchanged: `^preset:`, `^emergency:`, `^p5:*`, `^auto_trade:`, `^panel:`,
`^ops:`, `^admin:`, `^portfolio:`, `^close_position:`, `^position:fc_*`, `^mytrades:*`,
`^set_*`, `^setup:`, `^start:`, `^menu:`, `^nav:`, `^wallet:` all still resolve to the same
handlers. New `preset:tiers`/`preset:tier:` and `emergency:more`/`home`/`ask:`/`status`
route through the existing `^preset:`/`^emergency:` catch-alls.

## 3. Files created / modified (repo-root paths)

ADDED (new in keyboards_v2 → keyboards): `setup.py`; behavior-preserving ports appended to
`autotrade.py`, `portfolio.py`, `admin.py`, `onboarding.py`, `customize.py`, `_common.py`
(`nav_row`, `home_back_row`); mvp/ tree + 4 kept modules copied in.

MODIFIED handlers (import migration, aliased renames only — no call-site logic changed):
`bot/handlers/{dashboard,pnl_insights,portfolio_chart,wallet,settings,setup,autotrade,
presets,customize,emergency,positions,trades,my_trades,admin,operator_panel,onboarding,
start}.py` and `bot/handlers/mvp/{dashboard,autotrade,portfolio,settings,help,onboarding,
copy_wallet,markets}.py` + `bot/handlers/{copy_trade,signal_following,market_card}.py`.

New handler code: `bot/handlers/presets.py` (`_on_tier` + `tiers`/`tier` branches);
`bot/handlers/emergency.py` (router rewritten for v2 `emergency:*` + legacy compat).

RENAMED: `bot/keyboards` → `bot/_keyboards_archive`; `bot/keyboards_v2` → `bot/keyboards`.

TESTS repointed: `test_phase5{d,g,h,i,j}`, `test_pnl_insights`, `test_positions_handler`,
`test_preset_system`, `test_ux_overhaul` (imports to new locations / archive; 4 assertions
updated to the redesigned tier/emergency/unified-nav behavior).

## 4. What is working

- `python -c "import crusaderbot.bot.dispatcher"` imports clean.
- Full suite: 1751 passed (was 1751 at baseline; no regressions). Re-run after every chunk.
- `grep "from ..keyboards[^_]" bot/handlers/` → 0 (all handlers point to the active module).
- `grep keyboards_v2 bot/ tests/` → 0 after promotion.
- 2-step preset tier flow and emergency progressive disclosure render and route.
- Legacy `callback_data` preserved for every existing action (backward-compatible with
  in-flight messages).

## 5. Known issues

- `bot/handlers/settings.py` `settings:back` still calls `main_menu(strategy_key=...)`,
  which neither the legacy nor the v2 `main_menu` accepts — a PRE-EXISTING latent
  `TypeError` on that path, left unchanged by this migration (out of scope; flagged here).
- The `mvp/` tree and the 4 kept modules are copied as-is into the new module; their
  redesign/merge is deferred to a later lane (per WARP🔹CMD copy-as-is directive).
- Bot not driven end-to-end in a live Telegram session in this environment (no headless
  Telegram); validation is via import + the full pytest suite, which exercises handlers and
  keyboard rendering.

## 6. What is next

- Optional SENTINEL pass (tier is STANDARD → WARP🔹CMD review; reclassify to MAJOR only if
  deeper validation is wanted given the breadth of the UI surface).
- Follow-up lane: merge the `mvp/` parallel tree into the main v2 modules and unify its
  `callback_data`, then redesign copy_trade/signal_following/market_card/referral.
- Follow-up: fix the pre-existing `settings:back` `main_menu(strategy_key=...)` latent crash.

Suggested Next Step: WARP🔹CMD review the PR; merge; then schedule the mvp-tree merge lane.
