# WARP•ROOT — preset-gate-deny-by-default

Role: WARP•R00T
Branch: WARP/ROOT/preset-gate-deny-by-default
Date: 2026-05-31 Asia/Jakarta
Validation Tier: MAJOR (touches the strategy-dispatch gate that enforces the "only 3 canonical presets trade" invariant)
Claim Level: NARROW INTEGRATION
Validation Target: `_preset_allows` fallback semantics (services/signal_scan/signal_scan_job.py)
Not in Scope: reconciling the legacy prod `active_preset='contrarian'` row (owner-side DB action); any new strategy logic
Closes: WARP/ROOT/prelaunch-system-audit finding F2 (B4)

## 1. What was built

Hardened the preset→strategy dispatch gate to **deny-by-default**. `_preset_allows(active_preset, strategy_name)` previously fell back to `_LIB_STRATEGY_NAMES` for any `active_preset` not in `_PRESET_ALLOWED` (services/signal_scan/signal_scan_job.py:503). That is fail-open: it is safe today only because `_LIB_STRATEGY_NAMES` is currently empty (services/signal_scan/lib_strategy_runner.py:38-39). A real production row carries `active_preset='contrarian'` (a legacy non-canonical preset), and the lib-runner comment explicitly invites re-adding lib strategies — at which point that user (and any other legacy-preset row) would silently begin trading a non-canonical strategy. The fallback is now `frozenset()`, so an unknown / removed / legacy / NULL preset structurally permits **no** strategy, regardless of the lib registry.

## 2. Current system architecture

No architectural change. The scan loop still gates every candidate through `_preset_allows`; the 3 canonical candle presets (close_sweep / safe_close / flip_hunter) remain mapped to `late_entry_v3` in `_PRESET_ALLOWED`. Only the *default* returned for unmapped keys changed (`_LIB_STRATEGY_NAMES` → `frozenset()`). The existing `active_preset IS NULL` early-skip (services/signal_scan/signal_scan_job.py:2443) is retained as defense-in-depth and its stale comment updated. Behaviourally this is a **no-op today** (both sets are empty) — it removes a latent footgun, not current traffic.

## 3. Files created / modified

- Modified: `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` (line 503 fallback `frozenset()`; `_preset_allows` docstring; stale loop comment ~2440).
- Modified: `projects/polymarket/crusaderbot/tests/test_signal_scan_job.py` (+2 regression tests: deny-by-default robust to a non-empty lib set; source-pin that the fail-open pattern is gone).
- Modified (state): `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `projects/polymarket/crusaderbot/state/CHANGELOG.md`.

## 4. What is working

`_preset_allows('contrarian', x)` and `_preset_allows(None, x)` now return `False` for every `x` **even when `_LIB_STRATEGY_NAMES` is monkeypatched non-empty** — pinned by the new `test_preset_allows_deny_by_default_robust_to_nonempty_lib_set`. Canonical presets unchanged (`close_sweep`→`late_entry_v3` still True). `ruff check` + `py_compile` clean. `test_signal_scan_job.py` 74/74 pass (5 preset-gate tests incl. 2 new).

## 5. Known issues

- The legacy prod row `active_preset='contrarian'` (1 user) still exists and now (as before) fires zero trades; this lane makes that guarantee structural rather than coincidental. Operator should still reconcile the row to a canonical preset or NULL (DB action — out of scope here, not a prod mutation this lane performs).
- `_LIB_STRATEGY_NAMES` (services/signal_scan/lib_strategy_runner.py-derived) is now referenced only by the docstring + tests; the definition is retained intentionally (documents intent; imported by tests).

## 6. What is next

WARP•SENTINEL validation (MAJOR — strategy-dispatch gate). Then WARP🔹CMD merge decision. This lane closes audit finding F2 / LIVE-readiness B4. Remaining audit lanes per WARP/ROOT/prelaunch-system-audit Appendix H.

Suggested Next Step: WARP•SENTINEL pass, then proceed to `WARP/ROOT/bnb-monitor-only-fallback-fix` (B2).
