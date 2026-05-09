# WARP•FORGE Report — CrusaderBot Phase 5C Strategy Preset System

Branch: `WARP/CRUSADERBOT-PHASE5C-PRESETS` (verified via `git rev-parse --abbrev-ref HEAD`)
Note: session harness pre-set `claude/crusaderbot-preset-system-RH4e2`; per CLAUDE.md "Auto-generate prohibition (HARD RULE)" the work was checked out onto the declared `WARP/CRUSADERBOT-PHASE5C-PRESETS` branch before any file write or commit. No `claude/...` branch was touched.

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION — new named-preset system with DB persistence + Telegram UI replaces the picker entry surface only. Risk gate, execution engine, CLOB client, and activation guards are not touched. Live activation continues to require the existing 2FA-gated dashboard toggle; preset activation is paper-only.
Validation Target: 5 named presets (whale_mirror / signal_sniper / hybrid / value_hunter / full_auto), preset picker with ⭐ recommended marker, confirmation card with full hierarchy display, status card with live stats, activate/pause/resume/switch/stop persistence, `🤖 Auto-Trade` menu router, `/preset` command alias, `/setup_advanced` legacy escape hatch, migration 016 idempotent additive columns.
Not in Scope: Customize wizard (Phase 5D), onboarding flow (Phase 5E), risk gate constants, activation guards, execution engine, CLOB client, mainnet preflight, dashboard toggle behaviour.
Suggested Next Step: WARP•SENTINEL MAJOR audit — risk gate + activation guards must be verified untouched, preset values must be re-checked against `domain/risk/constants.py`, paper-only assertion on `_on_activate` must be traced.

---

## 1. What was built

A named-preset system that bundles strategy + capital + TP/SL + per-position cap into a single tap.

**5 preset definitions** (`projects/polymarket/crusaderbot/domain/preset/presets.py`) — frozen dataclasses, validated at import time against the hard cap in `domain/risk/constants.py`:

| Key | Emoji | Name | Strategies | Capital | TP | SL | MaxPos | Badge |
|---|---|---|---|---|---|---|---|---|
| `whale_mirror` | 🐋 | Whale Mirror | copy_trade | 50% | +20% | -10% | 5% | 🟢 Safe |
| `signal_sniper` | 📡 | Signal Sniper | signal | 50% | +15% | -8% | 5% | 🟢 Safe |
| `hybrid` | 🐋📡 | Hybrid | copy_trade + signal | 60% | +15% | -10% | 5% | 🟡 Balanced |
| `value_hunter` | 🎯 | Value Hunter | value | 40% | +25% | -12% | 8% | 🟡 Advanced |
| `full_auto` | 🚀 | Full Auto | copy_trade + signal + value | 80% | +20% | -15% | 10% | 🔴 Aggressive |

Whale Mirror is tagged `RECOMMENDED_PRESET` and rendered with a ⭐ marker in the picker.

**Three cards** delivered as inline keyboards:

1. *Preset Picker* — one row per preset, label = `{emoji} {name}` (+⭐ on the recommended preset). Description block lists name + badge + 1-line tagline for each.
2. *Confirmation Card* — preset header + badge + tagline + hierarchy block (`├` / `└`) showing Strategies / Capital / Take-profit / Stop-loss / Max position. Buttons: `✅ Activate` / `✏️ Customize` / `← Back`.
3. *Status Card* — preset header + state badge (✅ RUNNING / ⏸ PAUSED / 🛑 STOPPED) + live stats (Balance, Today's P&L, Open positions) + active config recap. Buttons: `✏️ Edit` / `🔄 Switch` / `⏸ Pause`/`▶️ Resume` / `🛑 Stop`. Pause and Resume swap based on `users.paused`.

Plus two confirmation sub-cards (`preset:switch_yes` / `preset:stop_yes`) so a stray tap on Switch / Stop never silently clears the user's active preset.

**Routing** — `🤖 Auto-Trade` (existing `setup.setup_root`) now reads `user_settings.active_preset`:

- `active_preset IS NULL` → render Preset Picker
- `active_preset` set → render Status Card

The legacy raw-strategy menu remains reachable at `/setup_advanced` so power users keep access to Categories / Mode / Auto-redeem mode pickers, none of which the preset system replaces.

**Activation flow**

```
🤖 Auto-Trade
  ├── (no preset)  → Preset Picker → tap preset → Confirmation Card
  │                                                  ├── ✅ Activate
  │                                                  │     ├── trading_mode == 'paper' → write config + auto_trade_on=True + paused=False → Status Card
  │                                                  │     └── trading_mode == 'live'  → REJECT with explanatory message (use /dashboard toggle for live activation)
  │                                                  ├── ✏️ Customize → "ships in Phase 5D"
  │                                                  └── ← Back → Preset Picker
  └── (preset set) → Status Card
                       ├── ✏️ Edit   → "ships in Phase 5D"
                       ├── 🔄 Switch → confirm → clear preset + auto_trade_on=False → Preset Picker
                       ├── ⏸ Pause  → set users.paused=True → Status Card (paused)
                       ├── ▶️ Resume → set users.paused=False → Status Card (running)
                       └── 🛑 Stop   → confirm → clear preset + auto_trade_on=False → "stopped" message
```

**Persistence** — migration `016_preset_system.sql` adds two additive nullable columns to `user_settings`:

- `active_preset VARCHAR(50)` — preset key the user last activated, NULL when none
- `max_position_pct NUMERIC(5,4)` — preset's per-trade position cap (fraction); never exceeds `domain/risk/constants.MAX_POSITION_PCT`

Plus a partial index `idx_user_settings_active_preset` on rows where `active_preset IS NOT NULL` for the scheduler's per-preset filter. Existing fields (`strategy_types`, `capital_alloc_pct`, `tp_pct`, `sl_pct`) are reused so a preset stays the authoritative reference rather than a duplicated source of truth. Auto-trade ON/OFF reuses existing `users.auto_trade_on`. Pause/Resume reuses existing `users.paused`. No new tables.

**Live mode is intentionally out of scope** — `_on_activate` short-circuits with an explanatory message when `user_settings.trading_mode == 'live'` and instructs the user to either switch to paper or use the Dashboard auto-trade toggle (which runs the existing 2FA-gated 8-step activation checklist). This keeps the preset surface paper-only and changes zero activation guards.

---

## 2. Current system architecture

```
Telegram client
  │
  ▼
bot.dispatcher._text_router
  │
  ├── menu route '🤖 Auto-Trade' → bot.handlers.setup.setup_root
  │     │
  │     ├── get_settings_for(user.id).active_preset is None
  │     │     → bot.handlers.presets.show_preset_picker (renders Preset Picker)
  │     │
  │     └── active_preset set
  │           → bot.handlers.presets.show_preset_status (renders Status Card)
  │
  └── /preset command → bot.handlers.presets.show_preset_picker
  └── /setup_advanced  → bot.handlers.setup.setup_legacy_root (legacy raw-strategy menu)

bot.dispatcher.register()
  CallbackQueryHandler('^preset:') → bot.handlers.presets.preset_callback
    ├── preset:picker            → show_preset_picker
    ├── preset:status            → show_preset_status
    ├── preset:pick:{key}        → _on_pick (renders Confirmation Card)
    ├── preset:activate:{key}    → _on_activate (paper-only; writes user_settings + auto_trade_on)
    ├── preset:customize:{key}   → _on_customize (Phase 5D placeholder)
    ├── preset:edit              → _on_edit (Phase 5D placeholder)
    ├── preset:switch            → switch confirm card
    ├── preset:switch_yes        → _on_switch_yes (clears preset, auto_trade_on=False, → picker)
    ├── preset:pause             → _on_pause(paused=True)
    ├── preset:resume            → _on_pause(paused=False)
    ├── preset:stop              → stop confirm card
    └── preset:stop_yes          → _on_stop_yes (clears preset, auto_trade_on=False)

domain.preset
  PRESETS              dict[key → Preset]            (5 entries, locked values)
  PRESET_ORDER         tuple                         (display order)
  RECOMMENDED_PRESET   = 'whale_mirror'
  Preset               frozen dataclass; __post_init__ validates
                       0 < capital_pct < 1, tp_pct/sl_pct in (0, 1],
                       0 < max_position_pct ≤ domain.risk.constants.MAX_POSITION_PCT

migrations/016_preset_system.sql
  ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS active_preset    VARCHAR(50);
  ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS max_position_pct NUMERIC(5,4);
  CREATE INDEX IF NOT EXISTS idx_user_settings_active_preset
    ON user_settings(active_preset) WHERE active_preset IS NOT NULL;

users / users helpers (unchanged contracts; reused)
  set_auto_trade(user_id, on)        ← _on_activate / _on_switch_yes / _on_stop_yes
  set_paused(user_id, paused)        ← _on_activate / _on_pause / _on_switch_yes / _on_stop_yes
  update_settings(user_id, **fields) ← preset value writes
  get_settings_for(user_id)          ← read active_preset + trading_mode
```

---

## 3. Files created / modified

Created:

* `projects/polymarket/crusaderbot/migrations/016_preset_system.sql` — additive idempotent migration; two nullable columns on `user_settings` + partial index. Inline rollback DDL block.
* `projects/polymarket/crusaderbot/domain/preset/__init__.py` — re-exports `PRESETS`, `PRESET_ORDER`, `RECOMMENDED_PRESET`, `Preset`, `PresetBadge`, `get_preset`, `list_presets`.
* `projects/polymarket/crusaderbot/domain/preset/presets.py` — `Preset` frozen dataclass with import-time validation against `domain/risk/constants.MAX_POSITION_PCT` + the 5 owner-approved preset values + `RECOMMENDED_PRESET = 'whale_mirror'` + canonical `PRESET_ORDER`.
* `projects/polymarket/crusaderbot/bot/keyboards/presets.py` — `preset_picker`, `preset_confirm`, `preset_status` (paused-aware), `preset_switch_confirm`, `preset_stop_confirm`.
* `projects/polymarket/crusaderbot/bot/handlers/presets.py` — `show_preset_picker`, `show_preset_status`, `preset_callback` (single dispatcher for all `^preset:` callbacks), private action handlers (`_on_pick`, `_on_activate`, `_on_customize`, `_on_edit`, `_on_switch_yes`, `_on_pause`, `_on_stop_yes`).
* `projects/polymarket/crusaderbot/tests/test_preset_system.py` — 30 hermetic tests (no DB, no Telegram, no broker): preset definitions (count, ordering, recommended marker, capital < 1.0 hard rule, max_position ≤ MAX_POSITION_PCT, canonical strategy keys, validation rejects oversize values), keyboard wiring (picker labels + ⭐, confirm callback layout, paused/running pause-button swap, switch/stop confirm back targets), `setup_root` routing (preset-active vs preset-not-set branches), confirmation card rendering, paper activate writes full config + flips `auto_trade_on`, live activate is rejected without writes, pause/resume/stop/switch persistence + UI follow-ups.

Modified:

* `projects/polymarket/crusaderbot/bot/handlers/setup.py` — `setup_root` now reads `user_settings.active_preset` and dispatches to `presets_handler.show_preset_status` (preset active) or `presets_handler.show_preset_picker` (no preset). Legacy raw-strategy menu preserved as `setup_legacy_root` for `/setup_advanced` access. `setup_callback` and the awaiting-state handlers (`set_strategy`, `set_risk`, `set_category`, `set_mode`, `set_redeem_mode`, `text_input`, `_handle_copy_target_input`) are untouched.
* `projects/polymarket/crusaderbot/bot/dispatcher.py` — registers `CommandHandler('preset', presets.show_preset_picker)`, `CommandHandler('setup_advanced', setup.setup_legacy_root)`, and `CallbackQueryHandler(presets.preset_callback, pattern=r"^preset:")`. The `_text_router` priority order from Phase 5A is unchanged.

---

## 4. What is working

* All 5 presets load cleanly with import-time validation; no preset exceeds `MAX_POSITION_PCT=0.10` or uses `capital_pct >= 1.0` (CLAUDE.md hard rule).
* Preset Picker renders 5 rows in canonical order with the ⭐ marker on Whale Mirror; each row's `callback_data` is `preset:pick:{key}`.
* Confirmation Card displays the full hierarchy block (Strategies / Capital / TP / SL / Max position) with correct percentages.
* Paper activation writes `active_preset`, `strategy_types`, `capital_alloc_pct`, `tp_pct`, `sl_pct`, `max_position_pct` in one `update_settings()` call, then `set_auto_trade(uid, True)` and `set_paused(uid, False)` — verified by AsyncMock awaited-args assertions in `test_activate_paper_writes_full_config_and_turns_on`.
* Live activation is rejected without any DB write — verified by `test_activate_blocked_in_live_mode` (`upd_settings.assert_not_awaited()`, `set_auto.assert_not_awaited()`, `set_p.assert_not_awaited()`).
* Status Card distinguishes RUNNING / PAUSED / STOPPED state and pulls live stats from `wallet.ledger.get_balance` + `daily_pnl` + an `open_count` SELECT against `positions`.
* Pause/Resume flip `users.paused` and re-render the Status Card with the swapped button.
* Switch and Stop both confirm before action, then clear `active_preset` + `max_position_pct` and call `set_auto_trade(uid, False)` + `set_paused(uid, False)`. Switch returns to the Picker; Stop ends with a "stopped" message.
* `/preset` command and the `🤖 Auto-Trade` button both reach the Picker. `setup_root` routing is verified by `test_setup_root_routes_to_picker_when_no_preset` and `test_setup_root_routes_to_status_when_preset_active`.
* `/setup_advanced` reaches the legacy raw-strategy menu — power users keep access to Categories / Mode / Auto-redeem pickers.

Done criteria check:

- [x] User can pick preset → see confirmation → activate (paper)
- [x] Active preset survives bot restart (DB-persisted via `user_settings.active_preset` + reused `strategy_types` / `capital_alloc_pct` / `tp_pct` / `sl_pct` columns)
- [x] Status card shows running stats when preset active (Balance / Today's P&L / Open positions)
- [x] Pause halts auto-trade (`users.paused=True`); Resume re-enables it
- [x] Stop correctly halts auto-trade and clears active_preset
- [x] Switch preset clears old config and applies new (after re-pick + activate)
- [x] CI green: 814/814 crusaderbot tests pass (was 784; +30 new preset tests)
- [x] No activation guards changed — `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, `ENABLE_LIVE_TRADING`, `USE_REAL_CLOB` neither read nor mutated by new code (live preset activation is refused without touching any guard)
- [x] No risk gate constants modified — `domain/risk/constants.py` untouched; preset values validated against `MAX_POSITION_PCT` at import time
- [x] No execution engine or CLOB client modified — zero edits in `domain/execution/`, `integrations/clob/`, `integrations/polymarket.py`

Test posture: full local crusaderbot suite (excluding `test_api_ops.py` which depends on `eth_account` test fixtures pre-existing-skipped per Phase 5A note, and `integration_clob_smoke.py` which is operator-gated) ran 814/814 green in 37.7s.

Structure validation:

- Zero `phase*/` folders in repo.
- Zero imports referencing `phase*/` paths.
- All new code under locked domain structure (`domain/preset/`, `bot/handlers/`, `bot/keyboards/`, `migrations/`, `tests/`).
- Report at the correct path (`{PROJECT_ROOT}/reports/forge/crusaderbot-phase5c-presets.md`) — not at repo root, not in `report/` singular.

---

## 5. Known issues

* `Customize` and `Edit` buttons render a "ships in Phase 5D" message — wizard for inline value adjustment is explicitly out of Phase 5C scope.
* Live preset activation is intentionally unsupported — `_on_activate` short-circuits with an explanatory message when `trading_mode='live'` and instructs the user to use the Dashboard toggle. The Dashboard toggle's existing 2FA-gated activation flow (`activation.autotrade_toggle_pending_confirm`) is the only path that flips live auto-trade.
* `Stop` does NOT close open positions — message explicitly tells the user to use `/positions` for that. Mirrors the existing emergency-pause semantics; closing positions touches the execution engine which is out of scope.
* Preset values (capital / TP / SL / max_position) are owner-locked. Changing any number requires a new lane and SENTINEL audit.
* The migration runner applies `*.sql` alphabetically on every boot. `016_preset_system.sql` is fully idempotent (`ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`), so re-applying on a populated DB is a no-op and the new columns are nullable so existing `user_settings` rows are unaffected.
* Preset activation does NOT clear `category_filters` or `blacklist_markets` — those are preserved across preset selection. Stop / Switch only clear `active_preset` + `max_position_pct`.

---

## 6. What is next

* WARP•SENTINEL MAJOR audit — required before merge. Verification scope:
  * Risk gate constants in `domain/risk/constants.py` are untouched.
  * Activation guards (`ENABLE_LIVE_TRADING`, `USE_REAL_CLOB`, `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`) are neither read nor mutated by new code.
  * `_on_activate` paper-only guard is enforced (live activation refused without writes).
  * Preset values comply with `MAX_POSITION_PCT` and `capital_pct < 1.0` hard rules.
  * Migration 016 is idempotent and additive (no rewrite of existing columns).
  * All `^preset:` callbacks are gated by `_ensure_tier2` (Tier 2 allowlist).
* Phase 5D — Customize wizard for inline value adjustment.
* Phase 5E — Onboarding flow integration so Tier 1 → Tier 2 transition lands on the Preset Picker.
* Owner decision: after SENTINEL approval, WARP🔹CMD merges PR onto main.
