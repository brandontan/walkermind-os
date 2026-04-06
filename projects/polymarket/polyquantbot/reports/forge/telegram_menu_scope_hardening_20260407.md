# telegram_menu_scope_hardening_20260407

## 1. What was built
- **FORGE-X addendum (Home live blocker) applied in the same hardening pass:**
  - Audited Home render path (`action:home`/dashboard/menu callbacks) versus `/start` alias flow and identified divergence in callback payload hydration robustness.
  - Unified numeric normalization usage between Home callback payload hydration and `/start`-safe render policy by reusing shared Telegram `safe_number`/`safe_count` normalization.
  - Hardened callback Home payload builder against malformed/shared-state portfolio payload shapes (dict/object/None, malformed numeric strings, missing keys).
  - Added Home render fallback in callback router so degraded payload render errors are recovered to safe Home output instead of surfacing a hard failure.
  - Hardened Active Scope text rendering for malformed restored category payload types.
- Patched `/start` dashboard/menu numeric coercion blocker so placeholder values no longer crash Telegram render flow:
  - Added explicit numeric placeholder normalization in `projects/polymarket/polyquantbot/interface/telegram/view_handler.py` for Telegram-facing dashboard payload derivation.
  - Added callback payload numeric hardening in `projects/polymarket/polyquantbot/telegram/handlers/callback_router.py` so portfolio values such as `"N/A"`, `None`, `""`, and malformed strings are coerced safely before render.
  - Added regression tests for placeholder-heavy and sparse payload render paths in `projects/polymarket/polyquantbot/tests/test_telegram_start_numeric_safety.py`.
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
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/interface/telegram/view_handler.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/handlers/callback_router.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_telegram_start_numeric_safety.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/market_scope.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/pipeline/trading_loop.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/handlers/callback_router.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/interface/ui_formatter.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/interface/telegram/view_handler.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_telegram_start_numeric_safety.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/telegram_menu_scope_hardening_20260407.md`
- `/workspace/walker-ai-team/PROJECT_STATE.md`

## 4. Before/after improvement summary
- **Home callback live blocker path (before → after)**
  - Before: Home callback payload normalization assumed object-style portfolio fields and could break under malformed/shared-state restored payload shapes.
  - After: Home payload hydration safely normalizes dict/object/None portfolio states, malformed numerics (`"N/A"`, `None`, `""`, non-numeric strings), and missing keys without hard crash.
- **Home vs `/start` normalization divergence (before → after)**
  - Before: callback Home normalization duplicated logic and could drift from `/start`-safe behavior.
  - After: callback Home path reuses shared Telegram-safe numeric normalization (`safe_number`/`safe_count`) aligned with `/start` safety policy.
- **Callback-driven Home hard failure behavior (before → after)**
  - Before: render exception in callback path bubbled to error screen flow.
  - After: callback router now recovers to safe Home fallback render with operator note instead of hard-failing menu flow.
- **Persisted scope restore + Home render (before → after)**
  - Before: malformed restored category payload types could produce inconsistent category render behavior.
  - After: scope category display path now enforces list-to-text normalization so restored sparse/malformed values cannot break Home/Scope rendering.
- **Regression evidence added for Home blocker**
  - Added/extended tests for:
    - Home render with malformed portfolio dict payload and placeholder numerics.
    - callback `/start` → Home transition with sparse payload.
    - Home render after persisted scope-state restore containing sparse/malformed category entries.
- **`/start` numeric placeholder crash (before → after)**
  - Before: `/start` render path could execute `float("N/A")` during dashboard payload derivation, producing `ValueError` and CRITICAL ERROR card (`command_handler:/start` context).
  - After: all Telegram-facing numeric coercion on `/start` path routes through explicit safe normalization (`_safe_number`, `_safe_count`) with truthful defaults for degraded input.
- **Dashboard/menu sparse payload behavior (before → after)**
  - Before: sparse payload with placeholder/missing numeric fields could trigger hard failure in position metrics derivation.
  - After: sparse and mixed placeholder payloads render valid premium dashboard output with safe defaults (`0`, `0.0`) and no hard-crash.
- **Callback payload safety (before → after)**
  - Before: callback router normalization used direct `float(...)` conversion on portfolio and position values.
  - After: callback router normalizes all portfolio/position numeric fields via safe conversion to prevent placeholder coercion failure from shared state injection.
- **Regression proof for this blocker**
  - Added tests covering:
    - `"N/A"` numeric placeholders
    - `None` / empty string placeholders
    - sparse `/start`-equivalent payload
    - callback payload normalization with malformed portfolio numbers
  - Added runtime render check script proving home/start render succeeds and does not emit CRITICAL ERROR marker for the placeholder class.
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
- This patch intentionally uses safe numeric defaults for degraded Telegram payloads to preserve runtime safety; semantic data quality still depends on upstream producers.
- Weak-metadata fallback is intentionally permissive to avoid hard false-negative exclusion; some operators may still prefer tighter category constraints in future tuning.
- External live-network Telegram screenshot validation remains unavailable in this container environment.
- External market-context endpoint connectivity warnings may still appear in this environment and were not part of this targeted hardening scope.

## 6. Next
- SENTINEL validation required for telegram-menu-scope-hardening-20260407 before merge.
Source: projects/polymarket/polyquantbot/reports/forge/telegram_menu_scope_hardening_20260407.md
- SENTINEL should validate both `/start` and callback-driven Home placeholder regression paths explicitly (including `"N/A"`, `None`, empty, malformed numerics, sparse/missing fields, and persisted scope restore path) and confirm no CRITICAL ERROR card for this class.
