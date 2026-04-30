# 1. Target
- Task: `telegram-menu-structure-20260406`
- Branch context: `feature/telegram-menu-structure-20260406` (Codex worktree HEAD label observed as `work`, treated as valid per repo rule).
- Validation inputs:
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/telegram_menu_structure_20260406.md`
  - `/workspace/walker-ai-team/PROJECT_STATE.md`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/ui/keyboard.py`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/interface/ui_formatter.py`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/interface/telegram/view_handler.py`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/handlers/callback_router.py`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/market_scope.py`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/pipeline/trading_loop.py`

# 2. Score
- **Score: 96/100**
- Rationale:
  - Full static evidence present for menu structure and scope plumbing.
  - Runtime proof provided for menu rendering, callback routing, and trading-loop scope gate behavior (including blocked/enabled states).
  - Negative testing and break attempts executed (All Markets ON/OFF, invalid category, zero category selection, scope-block behavior).
  - Deduction: in-process-only scope persistence remains a real operational limitation after restart (documented known issue).

# 3. Findings by phase

## Phase 0 — Preconditions
- PASS: Forge report exists at required path and contains six sections.
- PASS: `PROJECT_STATE.md` is updated and points to this exact forge task as next priority.
- PASS: all requested target files exist.
- PASS: scope appears limited to Telegram menu/control surfaces + minimal runtime scope enforcement in trading loop.

## Phase 1 — Static evidence
- PASS: root menu is exactly 5 items in `build_main_menu()`:
  - `📊 Dashboard`
  - `💼 Portfolio`
  - `🎯 Markets`
  - `⚙️ Settings`
  - `❓ Help`
- PASS: Markets menu includes required controls in `build_markets_menu()`:
  - `Overview`
  - `🌍 All Markets ✅/⬜`
  - `🗂 Categories`
  - `✅ Active Scope`
  - `🔄 Refresh All`
- PASS: Dashboard/Home scope-at-a-glance exists via `scope_label` rendering in formatter home primary block.
- PASS: scope snapshot injected into callback payload and routed to views (`selection_type`, `enabled_categories`, `trading_scope_summary`, `scope_warning`, `scope_label`).
- PASS: runtime path enforces scope at trading loop market fetch stage:
  - `apply_market_scope(markets)` called before ingest/signal generation.
  - empty scoped result causes `trading_loop_scope_blocked` and skips downstream path.

## Phase 2 — Runtime render proof
- PASS: Rendered and checked titles/menus for:
  - Dashboard/Home, System
  - Portfolio: Wallet, Positions, Exposure, PnL, Performance
  - Markets: Overview, All Markets toggle flow, Categories, Active Scope, Refresh All
  - Settings: Mode, Control, Risk Level, Strategy view, Notifications, Auto Trade
  - Help: Guidance, Bot Info
- PASS: Help icon and view identity are `❓ Help`.
- PASS: Refresh action in redesigned Dashboard/Markets flows is `Refresh All`.
- PASS: no cross-menu keyboard bleed observed in tested callback-router outputs.

## Phase 3 — Market scope behavior validation
- PASS Case A (All Markets ON): category filters ignored; all provided markets remain in scope.
- PASS Case B (All Markets OFF + one category): scoped set reduced to selected category only.
- PASS Case C (All Markets OFF + multiple categories): scoped set reduced to enabled categories only.
- PASS Case D (All Markets OFF + zero categories): scoped result empty; can-trade false; explicit blocked warning shown in Active Scope UI.
- PASS runtime trading-loop gate:
  - blocked scope: no ingest/signals reached.
  - enabled scope: ingest/signals invoked with filtered market count.

## Phase 4 — Negative / break tests
- PASS invalid category toggle (`NotARealCategory`) is safely ignored (no unintended state mutation).
- PASS break attempt (scope disabled but scan continues) did not succeed in loop harness; signals remained uncalled under blocked scope.
- PASS no legacy `ℹ️ Help` menu label found in redesigned menu paths.
- PASS no legacy `Refresh` naming in redesigned Dashboard/Markets controls; legacy wallet-specific refresh remains outside redesigned scope.
- PASS no evidence of menu-truth regressions in tested paths (positions/exposure and pnl/performance remained distinct views).

## Phase 5 — Known-issue validation
- CONFIRMED WARNING: category inference is metadata/keyword-based and uncategorized markets are excluded when All Markets is OFF.
- CONFIRMED WARNING: scope persistence is in-process only; state resets after restart/re-init.
- ACCEPTABILITY: warning-level for this menu-structure task; not a functional mismatch versus forge claim.

## Phase 6 — Regression scope check
- PASS: latest forge commit file set restricted to expected targets + report/state update.
- PASS: no unintended changes detected in strategy/risk/capital sizing/order placement/infra async layers within reviewed commit file list.

# 4. Evidence

## Commands executed
1) Compile check
```bash
python -m py_compile projects/polymarket/polyquantbot/telegram/ui/keyboard.py \
  projects/polymarket/polyquantbot/interface/ui_formatter.py \
  projects/polymarket/polyquantbot/interface/telegram/view_handler.py \
  projects/polymarket/polyquantbot/telegram/handlers/callback_router.py \
  projects/polymarket/polyquantbot/core/market_scope.py \
  projects/polymarket/polyquantbot/core/pipeline/trading_loop.py
```
Result: `py_compile_ok`.

2) Runtime menu render and scope case simulation
```bash
python - <<'PY'
# renders Dashboard/System/Portfolio/Markets/Settings/Help views;
# checks menu labels and runs scope cases A/B/C/D + invalid category.
PY
```
Key output excerpts:
- `main_menu= ['📊 Dashboard', '💼 Portfolio', '🎯 Markets', '⚙️ Settings', '❓ Help']`
- `markets_menu= ['Overview', '🌍 All Markets ✅', '🗂 Categories', '✅ Active Scope', '🔄 Refresh All', '🏠 Main Menu']`
- `help => ❓ Help`
- `A 3 All Markets []`
- `B ['m1'] Categories ['Crypto']`
- `C ['m1', 'm2'] ['Crypto', 'Sports']`
- `D 0 False Trading scope: blocked — no active categories selected.`

3) Callback router behavior render checks
```bash
python - <<'PY'
# instantiates CallbackRouter with stubs and dispatches redesigned actions.
PY
```
Key output excerpts:
- `dashboard => 🏠 Home Command | buttons=['Home', 'Refresh All', '🏠 Main Menu']`
- `markets_overview => 🛰️ Markets | buttons=['Overview', '🌍 All Markets ✅', '🗂 Categories', '✅ Active Scope', '🔄 Refresh All', '🏠 Main Menu']`
- `help => ❓ Help | buttons=['Guidance', 'Bot Info', '🏠 Main Menu']`
- `markets_categories_save => ✅ Active Scope | first= Overview`

4) Trading-loop scope gate runtime harness
```bash
python - <<'PY'
# monkeypatches loop dependencies to run one tick with blocked scope and enabled scope.
PY
```
Key output excerpts:
- Blocked case:
  - `market_feed ... scoped_count=0 selection_type=Categories`
  - `trading_loop_scope_blocked ...`
  - `BLOCKED {'signals': 0, 'ingest': 0}`
- Enabled case:
  - `market_feed ... scoped_count=1 selection_type=Categories`
  - `signals_generated count=0 ... markets_scanned=1`
  - `ENABLED {'signals': 1, 'ingest': 1}`

5) Legacy naming/regression search
```bash
rg -n "ℹ️ Help|❔ Help|Help" projects/polymarket/polyquantbot/telegram/ui/keyboard.py \
  projects/polymarket/polyquantbot/interface/ui_formatter.py \
  projects/polymarket/polyquantbot/interface/telegram/view_handler.py \
  projects/polymarket/polyquantbot/telegram/handlers/callback_router.py

rg -n "\bRefresh\b|Refresh All" projects/polymarket/polyquantbot/telegram/ui/keyboard.py \
  projects/polymarket/polyquantbot/interface/telegram/view_handler.py \
  projects/polymarket/polyquantbot/telegram/handlers/callback_router.py
```
Result highlights:
- `❓ Help` present in keyboard and formatter title mapping.
- `Refresh All` present in redesigned Dashboard/Markets keyboard flows.
- legacy `🔄 Refresh` remains in wallet-specific menus (outside redesign scope).

6) Drift boundary check (changed files)
```bash
git show --name-only --pretty='format:%H %s' --stat HEAD
```
Result: changed files aligned to claimed scope only.

## Static line-level references
- Root menu 5-item structure: `projects/polymarket/polyquantbot/telegram/ui/keyboard.py:41-47`
- Dashboard/Markets refresh naming: `projects/polymarket/polyquantbot/telegram/ui/keyboard.py:69,92`
- Markets controls: `projects/polymarket/polyquantbot/telegram/ui/keyboard.py:84-94`
- Help icon/title mapping: `projects/polymarket/polyquantbot/telegram/ui/keyboard.py:46`, `projects/polymarket/polyquantbot/interface/ui_formatter.py:30`
- Dashboard scope line: `projects/polymarket/polyquantbot/interface/ui_formatter.py:191`
- Scope payload wiring + warning: `projects/polymarket/polyquantbot/telegram/handlers/callback_router.py:362-399`
- Scope toggle/category handlers: `projects/polymarket/polyquantbot/telegram/handlers/callback_router.py:560-579,777-789`
- Market scope state + filter logic: `projects/polymarket/polyquantbot/core/market_scope.py:91-147`
- Trading loop scope gate before ingest/signals: `projects/polymarket/polyquantbot/core/pipeline/trading_loop.py:825-849`

# 5. Critical issues
- No CRITICAL blockers found for this task objective.

Warnings:
1) Scope persistence gap
- Scope selection is process-memory only and does not survive restart.
- Impact: operators must reapply scope after bot restart.

2) Category inference limits
- Category matching relies on category field + keyword inference.
- Impact: uncategorized markets are excluded when All Markets is OFF.

3) Environment limitation during validation
- `market_context_api_failed` warnings occurred because `clob.polymarket.com` was unreachable from this container; did not block local render/scope validation.

# 6. Verdict
**CONDITIONAL**

The Telegram menu redesign and scope-control runtime enforcement are real and behaviorally validated, including blocked-scope prevention before ingest/signal generation. Approval is conditional on accepting the known persistence/inference limitations for this increment (non-blocking for menu-structure objective, but should be tracked for production-hardening).
