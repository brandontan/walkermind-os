# WARP•FORGE — fix-bot-ui-tree-constants

Last Updated : 2026-05-23 06:54 Asia/Jakarta
Branch       : WARP/fix-bot-ui-tree-constants

## 1. What was built

Fix for the deployment-blocking import error found by the system audit (F-CRIT-1,
`projects/polymarket/crusaderbot/reports/sentinel/crusaderbot-system-audit.md`).

`bot/ui/__init__.py` re-exported `BAR`, `BRANCH`, `LAST` from `bot/ui/tree.py`, but the
WARP-67/68/71/73 terminal-UI redesign intentionally removed those box-drawing constants
(`tree.py` docstring: "NO ├── └── box chars"). The stale re-export raised
`ImportError: cannot import name 'BAR'` whenever `bot.ui` was imported — which broke the
runtime boot chain `main.py → bot.dispatcher → MVP handlers → messages_mvp → ui.tree`,
so the app could not start from `main`.

Fix: removed `BAR`/`BRANCH`/`LAST` from both the `from .tree import (...)` block and
`__all__` in `bot/ui/__init__.py`. No box chars reintroduced (respects the redesign).
The status/mode constants (`STATUS_RUNNING/STOPPED/PAUSED/NOT_SET/SYNCING`, `PAPER`,
`LIVE`, `LOCKED`) already exist in `tree.py:26-33` and are untouched. No runtime or test
code referenced `BAR`/`BRANCH`/`LAST` (verified — the only grep hits were SQL `NULLS LAST`
and an unrelated `"BAR"` env-var name in test_health).

## 2. Current system architecture (relevant slice)

`bot/ui/tree.py` = Telegram HTML render helpers + status/mode label constants.
`bot/ui/__init__.py` = thin re-export of the public `tree` API. Consumed by
`bot/messages_mvp.py` and the MVP handlers (`dashboard`, `autotrade`, `copy_wallet`,
`settings`, etc.), which are registered by `bot/dispatcher.py:register()`, imported at
module load by `main.py:23`. The re-export must match `tree.py`'s actual exports or the
entire handler-registration import chain fails at startup.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/bot/ui/__init__.py` — removed `BAR`/`BRANCH`/`LAST`
  from the import block and `__all__` (6 lines removed).
- `projects/polymarket/crusaderbot/reports/forge/fix-bot-ui-tree-constants.md` — this report.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — F-CRIT-1 resolution + status.

## 4. What is working

- `python -c "import ...bot.dispatcher; import ...bot.messages_mvp"` → OK (was ImportError).
- Previously-broken tests now pass: `test_warp59_copy_wallet_bridge.py` (collected + passed)
  and `test_activation_handlers::test_dispatcher_routes_activation_confirm_before_setup`.
- Full suite: 1613 passed, 1 skipped, 0 failures, 0 collection errors (87.9s).
- `ruff check bot/ui/__init__.py`: clean.

## 5. Known issues

- F-HIGH-2 (audit) unchanged: 0 live trade data (positions/orders/fills/snapshots).
  Out of scope for this import fix; needs a separate scan→trade smoke lane.
- Post-merge: Fly.io redeploy required so the running pod imports the fixed module;
  confirm `fly status`/`fly logs` (prod heartbeat stopped 2026-05-22 22:12 UTC).

## 6. What is next

- WARP🔹CMD review + merge, then Fly.io redeploy.
- Recommend adding a CI runtime-import smoke (`python -c "import ...bot.dispatcher"`) so a
  re-export/handler-chain break fails CI instead of reaching production.

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : bot.ui import boundary + runtime boot chain (dispatcher/messages_mvp) import-clean; previously-broken tests green; full suite 0 collection errors
Not in Scope      : F-HIGH-2 zero-trade-data; box-char rendering redesign; Fly redeploy
Suggested Next    : WARP🔹CMD review
