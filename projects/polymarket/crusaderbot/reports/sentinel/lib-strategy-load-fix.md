# WARP•SENTINEL — lib-strategy-load-fix

Validated: 2026-05-23 10:45 WIB
Branch: WARP/lib-strategy-load-fix | PR: #1298
Tier: MAJOR (auto-trade candidate path)
Source report: projects/polymarket/crusaderbot/reports/forge/lib-strategy-load-fix.md
Default posture: unsafe until proven; code/catalog is truth, forge report not trusted blindly.

## TEST PLAN

Phase 0 — Pre-test gate.
Phase 1 — Functional: every catalogued lib strategy loads via the real runner.
Phase 2 — Loader correctness in BOTH dev and prod (the dev/prod gap that caused the bug).
Phase 3 — Blast radius: confirm no risk/guard/execution change; lib classes unmodified.
Phase 4 — Failure modes (missing module, unknown name, removed sys.path hack, circular import).
Phase 5 — Regression (targeted + CI full suite).
Latency/Telegram phases: N/A (no runtime-perf or UI surface).

## PHASE 0 — PRE-TEST

- Forge report present, correct path, 6 sections + Tier/Claim/Target/Not-in-Scope: PASS.
- PROJECT_STATE.md updated (Status/NEXT PRIORITY/KNOWN ISSUES): PASS.
- No phase*/ folders; new code inside the package; regression test added: PASS.
- Claim "lib classes unmodified": VERIFIED — all 14 lib files are git R100 (100% rename, 0 content change).
Phase 0 = PASS.

## FINDINGS (evidence: file:line / command output)

Phase 1 — Functional
- _load_strategy loads all 7 catalogued strategies (trend_breakout, momentum, value_investor, expiration_timing, pair_arb, ensemble, whale_tracking); independent re-run: ok=7 fail=0 (was 0/7 pre-fix). PASS.
- ensemble builds sub-strategies via lib/strategies/__init__.py:get_strategy without raising. PASS.

Phase 2 — Loader correctness (dev + prod)
- lib_strategy_runner.py: `_PKG_ROOT = (__package__ or "").rsplit(".services.",1)[0]`; `_LIB_PKG = f"{_PKG_ROOT}.lib"`.
- Dev: _LIB_PKG = "projects.polymarket.crusaderbot.lib" (observed). PASS.
- Prod: pyproject name="crusaderbot"; Dockerfile CMD `uvicorn crusaderbot.main:app` → __package__="crusaderbot.services.signal_scan" → _LIB_PKG="crusaderbot.lib". lib/ is copied to /app/crusaderbot/lib with __init__.py at lib/ and lib/strategies/ → importable as crusaderbot.lib.strategies.*. PASS (the original file-path loader + repo-root lib/ failed both because lib/ was outside the build context AND relative imports can't resolve under spec_from_file_location).
- lib/ now ships: it lives inside the crusaderbot dir = the Docker build context (`working-directory: projects/polymarket/crusaderbot`, `COPY . /app/crusaderbot/`). PASS.

Phase 3 — Blast radius
- git diff --stat: only lib_strategy_runner.py (loader, -36/+57), lib/__init__.py, lib/strategies/__init__.py, tests/test_lib_strategy_loading.py, report, 3 state files, + 14 R100 renames. No change to domain/risk, domain/execution, paper.py, router, scheduler, gate. PASS — risk/guard/execution untouched; candidates still flow through the unchanged 13-step gate + ENABLE_LIVE_TRADING guard.

Phase 4 — Failure modes
- Missing module → importlib.import_module raises ImportError → run_lib_strategy:247 catches → returns [] (no crash, logged). PASS.
- get_strategy unknown name → ValueError → ensemble.py catches ValueError → sub-strategy skipped. PASS.
- Removed sys.path.insert / file-path loader: grep confirms no remaining `from strategy_base import` bare import depended on it. PASS.
- Circular import: lib/strategies/__init__ imports ..strategy_base (no relative imports in strategy_base) → no cycle; ensemble import verified at runtime. PASS.

Phase 5 — Regression
- Targeted: 60 passed (15 new test_lib_strategy_loading + 45 test_signal_scan_job).
- Full local suite (forge): 1628 passed / 1 skipped / 0 failed (was 1613; +15).
- CI on #1298: 3/3 green (Lint + Test x2, notify) — independent clean-env confirmation.
- Ruff: clean on all changed files. PASS.

## CRITICAL ISSUES

None found.

## STABILITY SCORE

- Architecture (20%): 20 — package-submodule import is the correct mechanism; __package__-derived root is dev+prod safe; lib classes untouched.
- Functional (20%): 20 — 7/7 load (was 0); 60 targeted + CI full suite green.
- Failure modes (20%): 19 — all degrade safely; −1 because live trade emission is not exercisable in-sandbox (scope, not a defect).
- Risk rules (20%): 20 — zero changes to risk/guard/execution/Kelly; gate path unchanged.
- Infra (10%): 10 — build-context/packaging fix verified vs Dockerfile + fly.toml + pyproject; CI green.
- Latency (10%): 10 — load-once cache unchanged; negligible overhead.
TOTAL: 99/100.

## GO-LIVE STATUS

APPROVED — Score 99/100, zero critical issues.

Reasoning: the fix correctly makes the lib strategies both shippable (inside the build context) and loadable (package submodule import resolves their relative imports), verified for dev and prod; it touches no risk/execution code and all candidates still pass the unchanged risk gate. Safe to merge.

## FIX RECOMMENDATIONS (priority ordered)

1. (P1, post-deploy verification — NOT a merge blocker) After Fly deploy, confirm lib strategies actually emit candidates: check job_runs `signal_following_scan` + `scan_outcome` logs for `accepted`/`rejected` (gate reached) and that positions/orders populate. This change proves loadability, not live triggering.
2. (P2, separate lane) Investigate Phase C `evaluate_publications_for_user` — a second possible zero-candidate cause (6,964 publications, 0 trades). Out of scope here.
3. (P3) Collapse the dual CopyTradeStrategy classes / retire the legacy scheduler.run_signal_scan copy_trade loop (pre-existing follow-up).

## TELEGRAM PREVIEW

N/A — no Telegram/UI surface in this lane.
