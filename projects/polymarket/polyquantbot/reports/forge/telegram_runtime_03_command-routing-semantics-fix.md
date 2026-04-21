# Telegram Runtime 03 — Command Routing Semantics Fix

Date: 2026-04-21 16:08 (Asia/Jakarta)
Branch: feature/fix-telegram-command-routing-and-sync-work-checklist
Project Root: projects/polymarket/polyquantbot/

## 1. What was built

- Fixed Telegram command-routing precedence so start lifecycle hooks (onboarding, activation confirmation, session issuance) execute only for `/start`.
- Preserved command-specific dispatch for non-`/start` commands (`/help`, `/status`, and other command surfaces) so they no longer collapse into the `/start` session/welcome path.
- Added runtime regression tests to lock command semantics: non-`/start` commands bypass start lifecycle hooks, and unresolved users on non-`/start` commands receive an explicit “use `/start` first” boundary reply.
- Synced `work_checklist.md` Priority 1 to current repo/runtime truth with explicit DONE / ACTIVE / NEXT status buckets aligned to observed Fly + Telegram state and this routing-fix lane.

## 2. Current system architecture (relevant slice)

1. Telegram polling loop normalizes inbound command text via `extract_command_context(...)`.
2. Identity resolution still runs before command dispatch when resolver wiring is enabled.
3. Start lifecycle hooks are now gated behind command check `ctx.command == "/start"`:
   - onboarding initiator path,
   - activation confirmer path,
   - session issuer path.
4. Non-`/start` commands:
   - do not trigger onboarding/activation/session issuance flow,
   - proceed to dispatcher command handler path on resolved identities,
   - return explicit guard reply for unresolved identities instructing `/start` first.
5. Dispatcher remains authoritative for command-specific replies (`/help`, `/status`, unknown fallback, etc.).

## 3. Files created / modified (full repo-root paths)

- projects/polymarket/polyquantbot/client/telegram/runtime.py
- projects/polymarket/polyquantbot/tests/test_phase8_9_telegram_runtime_20260419.py
- projects/polymarket/polyquantbot/work_checklist.md
- projects/polymarket/polyquantbot/reports/forge/telegram_runtime_03_command-routing-semantics-evidence.log
- projects/polymarket/polyquantbot/reports/forge/telegram_runtime_03_command-routing-semantics-fix.md
- PROJECT_STATE.md

## 4. What is working

- Local routing semantics are fixed at runtime-code level: non-`/start` commands no longer pass through start lifecycle/session issuance hooks.
- `/help` and `/status` command paths are preserved for dispatcher handling (no forced `/start` welcome/session reply override in the polling loop).
- Local regression test suite for runtime loop command routing passes (`19 passed`).
- `work_checklist.md` now reflects current execution truth for Priority 1 with explicit done/active/next separation.

## 5. Known issues

- Deploy/redeploy execution to Fly is blocked in this runner because `flyctl` is not installed.
- External `/health` and `/ready` probes to `https://crusaderbot.fly.dev` are blocked by proxy 403 from this runner.
- Real Telegram chat verification for `/start`, `/help`, `/status` cannot be executed in this runner (no Telegram bot token/chat interaction channel here).
- Because external verification is blocked, this task closes code-level semantics and checklist truth-sync, but keeps deployed verification as the next gate.

## 6. What is next

- Redeploy `feature/fix-telegram-command-routing-and-sync-work-checklist` in a Fly-capable environment.
- Validate real deployed Telegram behavior for `/start`, `/help`, `/status` against this branch head.
- Capture startup/deploy evidence (`fly logs`, `/health`, `/ready`, live Telegram replies) and hand off to SENTINEL for MAJOR validation verdict.

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : Telegram polling-loop command precedence (`/start` lifecycle gating) + command-specific dispatch continuity (`/help`, `/status`) + checklist truth-sync in `work_checklist.md`
Not in Scope      : webhook redesign, live-trading enablement, production-capital readiness, wallet lifecycle work, broad docs cleanup outside `work_checklist.md`
Suggested Next    : SENTINEL validation on this PR head branch in deploy-capable environment with real Telegram command proof
