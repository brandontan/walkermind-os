# Sentry 01 — Python Runtime Integration

Date: 2026-04-21 22:08 (Asia/Jakarta)
Branch: feature/integrate-sentry-python-runtime
Project Root: projects/polymarket/polyquantbot/

## 1. What was built

- Added a Python-first Sentry runtime integration helper (`server/core/sentry_runtime.py`) that initializes only when `SENTRY_DSN` is configured and remains a no-op when DSN is absent.
- Wired Sentry initialization into FastAPI app creation (`server/main.py`) so framework-level server exceptions can be captured through FastAPI integration when enabled.
- Added explicit runtime exception capture hooks for Telegram polling/runtime paths where exceptions are intentionally caught and handled, ensuring meaningful runtime failures can still be reported without crashing the bot.
- Added dependency declaration for `sentry-sdk[fastapi]` and added targeted tests verifying no-crash behavior when DSN is unset plus env-driven initialization behavior.
- Synced `work_checklist.md` observability section to reflect this landed integration truth.

## 2. Current system architecture (relevant slice)

1. `create_app()` now calls `initialize_sentry()` before building the FastAPI app.
2. `initialize_sentry()` reads only env configuration:
   - `SENTRY_DSN` (required to enable)
   - `SENTRY_ENVIRONMENT` (fallback `APP_ENV`)
   - `SENTRY_RELEASE` (optional)
   - `SENTRY_TRACES_SAMPLE_RATE` (default `0.0`)
3. When DSN is missing, Sentry is explicitly disabled and runtime remains unchanged.
4. FastAPI integration captures unhandled server exceptions when enabled.
5. Telegram runtime catches (identity resolver/onboarding/activation/session issuance/dispatch/send-reply/polling loop) now call `capture_runtime_exception(...)` to forward handled operational exceptions to Sentry when active, while preserving existing safe replies and no-crash behavior.
6. PII posture remains minimal (`send_default_pii=False`) and no secret payload injection is added.

## 3. Files created / modified (full repo-root paths)

- projects/polymarket/polyquantbot/server/core/sentry_runtime.py
- projects/polymarket/polyquantbot/server/main.py
- projects/polymarket/polyquantbot/client/telegram/runtime.py
- projects/polymarket/polyquantbot/tests/test_sentry_runtime_integration_20260421.py
- projects/polymarket/polyquantbot/requirements.txt
- projects/polymarket/polyquantbot/work_checklist.md
- projects/polymarket/polyquantbot/reports/forge/sentry_01_python-runtime-integration.md
- PROJECT_STATE.md

## 4. What is working

- Runtime boot path remains healthy with `SENTRY_DSN` unset (safe no-op).
- Env-driven Sentry initialization path is present and test-validated without hardcoded DSN.
- FastAPI integration is attached in Python runtime lane.
- Explicit Telegram/runtime exception capture hooks are wired for handled exceptions where framework auto-capture would not trigger.

## 5. Known issues

- This task does not include deploy-environment event proof (no real DSN/event round-trip evidence captured in this runner).
- Sentry dashboard verification must be executed in deploy-capable environment with actual secret injection (`fly secrets`).

## 6. What is next

- Deploy this branch with `SENTRY_DSN` configured via Fly secrets.
- Trigger controlled exception paths to verify Sentry receives expected runtime/server events.
- Run SENTINEL MAJOR validation on deployed evidence and confirm signal/noise posture.

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : FastAPI runtime initialization + env-only Sentry enablement + explicit Telegram/runtime handled-exception capture hooks
Not in Scope      : Node.js Sentry integration, alert/dashboard rollout, broad observability redesign, live-trading enablement
Suggested Next    : SENTINEL validation with deploy-environment Sentry event proof and paper-only boundary confirmation
