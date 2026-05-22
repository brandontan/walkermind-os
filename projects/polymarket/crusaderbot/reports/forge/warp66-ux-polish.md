# WARP-66 — Telegram UX full polish: nav, keyboard routing, status labels

Validation Tier: STANDARD
Claim Level: FUNCTIONAL
Validation Target: All persistent-keyboard auto-mode buttons respond via MVP surfaces; autotrade/copy-wallet status labels reflect configured state; dashboard tree free of duplicate 🤖; returning user always re-armed with persistent keyboard.
Not in Scope: New screens, new features, risk-gate changes, _common.py / dashboard.py / _send.py (already correct from WARP-65).

## 1. What was built

Six UX correctness fixes across the Telegram MVP surface (issue #1282):

- Problem 1 — Persistent-keyboard auto-mode taps (`🤖 Auto Mode`, `🤖 Setup Auto`, `▶️ Resume`) now route to the MVP autotrade surface. The existing group=-1 `MessageHandler` regex only matched legacy `Auto-Trade`/`Auto Trade` labels; the current `main_menu_kb()` emits `Auto Mode`/`Setup Auto`/`Resume`, which previously fell through to legacy preset-picker handlers via the group=0 text router. The regex was widened and a `▶️ Resume` handler added; the corresponding `menus/main.py` routes were converted to `_group0_noop` to prevent double responses.
- Problem 2 — `autotrade.py` `show_home()` now resolves `STATUS_STOPPED` when a preset is configured but the bot is idle (was always `STATUS_NOT_SET`). `_read_state()` gained a `configured` field.
- Problem 3 — `copy_wallet.py` `show_home()` now resolves `STATUS_STOPPED` when wallets exist but none are active (was always `STATUS_NOT_SET`).
- Problem 4 — `onboarding.py` `start_command()` re-attaches the persistent `main_menu_kb` for returning users before showing the dashboard (recovers a keyboard lost after app reinstall).
- Problem 5 — `messages_mvp.render_dashboard_default()` second tree leaf changed `🤖 Auto Trade` → `🔄 Auto Trade` (was duplicating the `🤖 Bot Status` emoji).
- Problem 6 — `autotrade.py` `_read_state()` strategy label now resolves from `PRESET_CONFIG[preset]["name"]` (human-readable) with title-case fallback, matching the WARP-65 dashboard pattern (was raw `⚡ {preset.title()}`).

## 2. Current system architecture

Reply-keyboard taps are processed in two PTB groups:
- group=-1 `MessageHandler`s (dispatcher.py) send the visible MVP response first.
- group=0 `_text_router` → `get_menu_route()` (menus/main.py) clears pending wizard `awaiting` state and short-circuits before wizard text handlers. Buttons answered by group=-1 map to `_group0_noop` here so no duplicate message is sent.

Auto-mode labels now follow the same dual-group contract that Dashboard/Portfolio already used. Status resolution mirrors the WARP-65 dashboard ladder: running → RUNNING, paused → PAUSED, configured/has-data → STOPPED, else NOT_SET.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — Problem 1 (widened auto regex + `▶️ Resume` handler)
- `projects/polymarket/crusaderbot/bot/menus/main.py` — Problem 1 (auto-mode routes → `_group0_noop`; orphaned `autotrade` import removed)
- `projects/polymarket/crusaderbot/bot/handlers/mvp/autotrade.py` — Problem 2, 6
- `projects/polymarket/crusaderbot/bot/handlers/mvp/copy_wallet.py` — Problem 3
- `projects/polymarket/crusaderbot/bot/handlers/mvp/onboarding.py` — Problem 4
- `projects/polymarket/crusaderbot/bot/messages_mvp.py` — Problem 5

Created:
- `projects/polymarket/crusaderbot/reports/forge/warp66-ux-polish.md` — this report

## 4. What is working

- Full suite: `1614 passed` (PYTHONPATH=. python3 -m pytest), 0 failed. Baseline was 1613; suite already carried 1614 tests post-WARP-61.
- AST/import sanity clean on all six touched modules.
- `PRESET_CONFIG` verified to expose `name` keys (e.g. `whale_mirror` → "Whale Mirror").

## 5. Known issues

- No new regression tests were added for the auto-mode routing change; coverage relies on the existing dispatcher/menu suites (all green). A targeted test asserting the widened regex + noop mapping would harden this further (P2, non-blocking).
- Pytest required ad-hoc dependency installation in this remote container (cffi/cryptography binding repair + pydantic-settings/web3/eth-account/apscheduler/fastapi); CI environment is authoritative.

## 6. What is next

- WARP🔹CMD review of PR `WARP/warp66-ux-polish`.
- Post-merge: Fly.io redeploy so the running bot pod imports the new routing + label logic.

Suggested Next Step: WARP🔹CMD review + merge, then redeploy.
