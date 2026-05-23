# WARP•FORGE — lib-strategy-load-fix

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: the lib auto-trade strategies (trend_breakout, momentum, value_investor, expiration_timing, pair_arb, ensemble, whale_tracking) now load and are reachable by the live scan loop (services/signal_scan/signal_scan_job.run_once). Verified by import + the existing pipeline tests.
Not in Scope: confirming live paper trades actually open (only possible post-deploy with Gamma + DB); whether each strategy triggers on current market conditions; the Phase C feed-evaluator path (evaluate_publications_for_user) — a separate potential zero-candidate cause; the legacy scheduler.run_signal_scan copy_trade loop.
Suggested Next Step: WARP•SENTINEL validation (MAJOR), then merge + Fly deploy, then confirm via job_runs/scan_outcome logs + positions that lib strategies emit candidates and paper trades open.

## 1. What was built

Fix for the primary F-HIGH-2 root cause: the `lib/` algorithmic strategies (the candidate source for auto-trading via `signal_scan_job.run_once`) never produced a single signal in production, for two compounding reasons, both now fixed:

1. NOT SHIPPED — `lib/` lived at the repository root, outside the crusaderbot Docker build context (`crusaderbot-cd.yml` runs flyctl with `working-directory: projects/polymarket/crusaderbot`; the Dockerfile does `COPY . /app/crusaderbot/`). The repo-root `lib/` was never copied into the image, so `_load_strategy` always raised on a missing path.
2. UNLOADABLE EVEN IF PRESENT — the strategy modules use package-relative imports (`from ..strategy_base import ...`; `ensemble` also `from . import get_strategy`) but the runner loaded each file via `importlib.util.spec_from_file_location` as a top-level module, which cannot resolve relative imports → `ImportError: attempted relative import with no known parent package` for every strategy (empirically reproduced for value_investor, momentum, ensemble).

Fix:
- Relocated `lib/` into the crusaderbot package (`projects/polymarket/crusaderbot/lib/`) so it ships inside the build context (`git mv`, history preserved). Verified nothing outside crusaderbot consumed the repo-root `lib/`.
- Made `lib/` a real package: added `lib/__init__.py` and `lib/strategies/__init__.py`. The latter implements `get_strategy(name)` (imported by `ensemble.py`), which loads a sibling strategy module by relative import and returns the matching Strategy instance, raising `ValueError` on failure (ensemble catches `ValueError`).
- Rewrote `lib_strategy_runner._load_strategy` to import strategies as package submodules (`importlib.import_module(f"{_LIB_PKG}.strategies.{name}")`) instead of file-path loading, so relative imports resolve. `_LIB_PKG` is derived from `__package__` at runtime so it works in dev (`projects.polymarket.crusaderbot.lib`) and prod (`crusaderbot.lib`) without any sys.path / file-path hack. Removed the dead `_LIB_ROOT`, `os`, `sys`, `importlib.util` usage.
- The lib strategy files themselves were NOT modified (the runner contract: lib classes are never edited here).

## 2. Current system architecture

Live auto-trade path (unchanged in shape, now functional):
```
scheduler.signal_following_scan (every SIGNAL_SCAN_INTERVAL)
  -> services/signal_scan/signal_scan_job.run_once
       Phase A: lib strategies (ENABLED_STRATEGIES) gated by user active_preset  <-- FIXED HERE
       Phase B: domain confluence_scalper (registry; crypto-gated)
       Phase C: evaluate_publications_for_user (feed subscriptions)             <-- not in scope
  -> _process_candidate -> TradeEngine.execute (13-step risk gate) -> paper fill
```
`run_lib_strategy` loads each enabled strategy once (cached), calls `initialize(strategy_params)` then `scan(markets, positions, balance)`, converts lib Signals → domain SignalCandidate. Candidates flow through the existing, unchanged risk gate + paper execution. No risk, guard, or execution logic was touched.

## 3. Files created / modified (full repo-root paths)

Relocated (git mv, repo root -> package):
- projects/polymarket/crusaderbot/lib/  (strategy_base.py, risk_manager.py, strategies/*.py + str.md — 14 files)

Created:
- projects/polymarket/crusaderbot/lib/__init__.py
- projects/polymarket/crusaderbot/lib/strategies/__init__.py  (get_strategy)
- projects/polymarket/crusaderbot/tests/test_lib_strategy_loading.py
- projects/polymarket/crusaderbot/reports/forge/lib-strategy-load-fix.md

Modified:
- projects/polymarket/crusaderbot/services/signal_scan/lib_strategy_runner.py  (loader rewrite; imports trimmed)
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md
- projects/polymarket/crusaderbot/state/WORKTODO.md
- projects/polymarket/crusaderbot/state/CHANGELOG.md

## 4. What is working

- All 7 catalogued lib strategies now load via the real runner (previously ALL failed):
  trend_breakout, momentum, value_investor, expiration_timing, pair_arb, ensemble, whale_tracking — each returns an instance whose `.name` matches.
- `ensemble` builds its sub-strategies through `get_strategy` without raising; `run_lib_strategy("ensemble", ...)` runs end-to-end (0 candidates on a single synthetic market — expected).
- New regression suite `tests/test_lib_strategy_loading.py` (15 tests) loads every enabled + deferred strategy unmocked, asserts `get_strategy` resolves by name and raises `ValueError` on unknown.
- Full suite: 1628 passed / 1 skipped / 0 failed (was 1613; +15 new). Ruff clean on all changed files. No stale `_LIB_ROOT` / file-path-loader references remain.

## 5. Known issues

- LIVE TRADE GENERATION NOT YET PROVEN. This change makes the strategies loadable and reachable; whether they emit candidates depends on real Gamma market conditions at runtime, which cannot be exercised in this sandbox (no Gamma/DB). Confirm post-deploy via `job_runs` + `scan_outcome` logs + `positions`.
- Phase C feed-evaluator (`evaluate_publications_for_user`) is a SEPARATE candidate source and a possible additional zero-trade cause (6,964 publications, 0 trades). Out of scope for this lane; flagged for a follow-up investigation.
- The legacy `scheduler.run_signal_scan` copy_trade loop (job `signal_scan`) and the dual CopyTradeStrategy classes remain as-is (pre-existing follow-up).
- `lib/` is now vendored into crusaderbot (single consumer verified). If another project later needs it, it must import from the crusaderbot package or re-share deliberately.

## 6. What is next

- WARP•SENTINEL validation (MAJOR — auto-trade candidate path).
- Merge + Fly deploy; confirm lib strategies emit candidates and paper trades open (positions/orders/fills populate → WebTrader/Telegram dashboards show data).
- Follow-up lane: investigate the Phase C feed-eval path so both candidate sources are proven.
