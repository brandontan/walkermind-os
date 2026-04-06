# telegram_menu_scope_hardening_20260407

## 1. What was built
- Added persistent Telegram market-scope state handling so market scope survives process restart/re-init:
  - Persists `all_markets_enabled`, `enabled_categories`, and `selection_type` into `projects/polymarket/polyquantbot/infra/market_scope_state.json` (configurable via `POLYQUANT_MARKET_SCOPE_STATE_FILE`).
  - Restores persisted state on scope module load and during callback-router re-init via snapshot hydration.
- Hardened category inference for weak/uncategorized market metadata when `All Markets` is OFF:
  - Deterministic inference order now covers explicit category, direct tag category match, then keyword scoring across question/title/name/description/slug/event metadata.
  - Ambiguous/tie cases are treated as uncategorized instead of making non-deterministic assignments.
  - Weak-metadata uncategorized markets are included through an explicit fallback rule to reduce avoidable scope exclusion.
- Preserved runtime scope gate behavior in trading loop and surfaced fallback usage telemetry via `fallback_applied_count` in market-feed logs.
- Preserved Telegram menu structure behavior (5-item root, Markets controls, Active Scope path) while adding explicit fallback-policy visibility in Active Scope view.

## 2. Design principles
- **Minimal integration only:** scope hardening was limited to market-scope core logic and its direct UI/runtime integration points; no architecture rewrite.
- **State truth over session memory:** scope settings are now explicit persisted state, not implicit in-process memory.
- **Deterministic inference:** category assignment uses an ordered rule path; ambiguity intentionally falls back to uncategorized handling instead of guessing.
- **Operator honesty:** Active Scope UI now includes fallback-policy communication so category-mode behavior is transparent.
- **No logic-layer drift:** strategy/risk/capital/order placement paths were not modified.

## 3. Files changed
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/market_scope.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/pipeline/trading_loop.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/handlers/callback_router.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/interface/ui_formatter.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/interface/telegram/view_handler.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/telegram_menu_scope_hardening_20260407.md`
- `/workspace/walker-ai-team/PROJECT_STATE.md`

## 4. Before/after improvement summary
- **Persistence gap (before → after)**
  - Before: scope state lived in-memory and reset after restart/re-init.
  - After: scope state is persisted to file and restored at initialization, preserving All Markets/category selection and selection type.
- **Restart/re-init restoration (before → after)**
  - Before: Active Scope and dashboard scope label reverted to defaults after restart.
  - After: restored snapshot feeds callback payload/render path, so Dashboard/Home scope summary and Active Scope reflect last persisted selection.
- **Category fallback behavior (before → after)**
  - Before: only simple metadata/keyword mapping; uncategorized markets were dropped when All Markets OFF.
  - After: deterministic multi-source inference + weak-metadata fallback include path reduces false exclusion while keeping behavior explicit.
- **Uncategorizable market treatment (before → after)**
  - Before: uncategorizable markets were excluded.
  - After: if metadata is weak/insufficient, market can be retained via fallback in category mode and summary indicates fallback count.
- **Blocked-scope protection (before → after)**
  - Before: blocked when All Markets OFF and no categories selected.
  - After: unchanged and preserved; still returns blocked scope and stops downstream scan/trade path.
- **Menu-truth regression check (before → after)**
  - Before: validated menu truth from previous pass.
  - After: no root/menu structure redesign or cross-menu behavior change introduced in this hardening pass.

## 5. Issues
- Weak-metadata fallback is intentionally permissive to avoid hard false-negative exclusion; some operators may still prefer tighter category constraints in future tuning.
- External live-network Telegram screenshot validation remains unavailable in this container environment.
- External market-context endpoint connectivity warnings may still appear in this environment and were not part of this targeted hardening scope.

## 6. Next
- SENTINEL validation required for telegram-menu-scope-hardening-20260407 before merge.
Source: projects/polymarket/polyquantbot/reports/forge/telegram_menu_scope_hardening_20260407.md
