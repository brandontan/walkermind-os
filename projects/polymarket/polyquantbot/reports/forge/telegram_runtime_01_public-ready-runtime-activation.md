# Telegram Runtime 01 — Public-Ready Runtime Activation

Date: 2026-04-21 13:59 (Asia/Jakarta)
Branch: feature/public-ready-telegram-runtime-on-fly
Project Root: projects/polymarket/polyquantbot/

## 1. What was built

- Activated Telegram polling runtime from the Fly API process lane by bootstrapping Telegram runtime in `server/main.py` lifespan startup using `run_polling_loop(...)` as an in-process async task.
- Added explicit Telegram runtime readiness state in `RuntimeState` and wired `/ready` to reflect true Telegram runtime status (required/enabled/startup_complete/active/iterations/last_error).
- Added fail-loud Telegram requirement control (`CRUSADER_TELEGRAM_RUNTIME_REQUIRED`) and mapped Fly config to require Telegram runtime on deploy (`fly.toml`).
- Added public baseline `/help` command support in Telegram dispatcher and updated unknown-command help text accordingly.
- Added runtime observability hooks for startup, iteration, reply sent, error, and shutdown events via observer callbacks from Telegram polling loop to server runtime state.

## 2. Current system architecture (relevant slice)

1. Fly runtime still serves FastAPI from `server/main.py`.
2. During FastAPI lifespan startup:
   - API startup validation runs.
   - Telegram runtime bootstrap validation runs (`TELEGRAM_BOT_TOKEN` required).
   - If valid, polling loop starts as a background asyncio task and reports lifecycle state through runtime observer.
   - If invalid and Telegram runtime is marked required, startup fails loudly.
3. `/ready` now reports Telegram runtime truth in `readiness.telegram_runtime` and returns `503 not_ready` when Telegram runtime is required but not active.
4. Telegram command baseline now includes `/help` as a first-class dispatcher command with paper-only boundary messaging.

## 3. Files created / modified (full repo-root paths)

- projects/polymarket/polyquantbot/server/core/runtime.py
- projects/polymarket/polyquantbot/server/main.py
- projects/polymarket/polyquantbot/server/api/routes.py
- projects/polymarket/polyquantbot/client/telegram/runtime.py
- projects/polymarket/polyquantbot/client/telegram/dispatcher.py
- projects/polymarket/polyquantbot/fly.toml
- projects/polymarket/polyquantbot/tests/test_crusader_runtime_surface.py
- projects/polymarket/polyquantbot/tests/test_phase8_8_telegram_dispatch_20260419.py
- projects/polymarket/polyquantbot/tests/test_phase8_9_telegram_runtime_20260419.py
- projects/polymarket/polyquantbot/reports/forge/telegram_runtime_01_public-ready-runtime-evidence.log
- projects/polymarket/polyquantbot/reports/forge/telegram_runtime_01_public-ready-runtime-activation.md
- PROJECT_STATE.md

## 4. What is working

- Telegram runtime is now wired into deploy entrypoint path (API process) rather than isolated script-only path.
- `/ready` now includes explicit Telegram runtime truth fields and can gate readiness when runtime is required.
- Missing Telegram token no longer silently degrades when required mode is enabled.
- `/help` is now implemented as a real command response.
- Targeted runtime + dispatcher + readiness tests pass (32 passed, 1 skipped).

## 5. Known issues

- Deployed Fly verification and real Telegram chat command confirmation (`/start`, `/help`, `/status`) are blocked in this runner due missing `flyctl` and outbound proxy 403 on `crusaderbot.fly.dev`.
- Because deploy verification is blocked here, this lane is outcome-labeled as **blocked for external verification** while code/runtime truth changes are landed.
- No live-trading or production-capital readiness is claimed.

## 6. What is next

- SENTINEL must validate this PR head branch as MAJOR lane and verify deployed behavior using a Fly-capable environment:
  - startup logs include Telegram runtime lifecycle signals,
  - `/ready` reflects truthful Telegram runtime state,
  - deployed bot replies to `/start`, `/help`, `/status`.
- If external verification succeeds, close blocker and advance COMMANDER decision.

Validation Tier   : MAJOR
Claim Level       : FULL RUNTIME INTEGRATION
Validation Target : Fly startup path + Telegram polling runtime activation + `/ready` truth surface + baseline Telegram commands (`/start`, `/help`, `/status`) in deployed environment
Not in Scope      : live-trading enablement, production-capital readiness, wallet lifecycle expansion, strategy upgrades, unrelated dashboard/doc cleanup
Suggested Next    : SENTINEL validation on actual PR head branch in deploy-capable environment
