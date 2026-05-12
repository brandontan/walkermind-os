# Realtime Paper Full-System Validation Harness

- Role: WARP•FORGE
- Branch: WARP/realtime-paper-system-validation
- Validation Tier: MAJOR
- Claim Level: FULL RUNTIME INTEGRATION
- Validation Target: Realtime paper-mode end-to-end runtime proof for multi-user isolation, DB persistence, market/signal path, paper lifecycle, Telegram UI surfaces, and health visibility.
- Not in Scope: live trading activation, real CLOB orders, guard flips, fee/referral activation, capital/risk constant changes.
- Last Updated: 2026-05-13 01:16

## What was implemented

1. Added harness entrypoint: `projects/polymarket/crusaderbot/scripts/realtime_paper_system_validation.py`
   - Runs guard checks (must remain OFF/NOT SET).
   - Runs DB table existence + two-user namespaced smoke checks.
   - Attempts signal scan only when provider credential exists.
   - Separates PASSED / FAILED / NOT_VALIDATED.
   - Emits markdown summary and optional JSON artifact.
2. Added focused harness behavior test:
   - `projects/polymarket/crusaderbot/tests/test_realtime_paper_system_validation.py`

## Run command

```bash
python -m projects.polymarket.crusaderbot.scripts.realtime_paper_system_validation --json-out projects/polymarket/crusaderbot/reports/forge/realtime-paper-system-validation.json
```

## Validation evidence split

### Realtime validated
- None in this execution environment (dependencies not installed; runtime credentials not supplied in lane container).

### Hermetic validated
- Guard-check behavior test asserts all five activation guards are evaluated and reported.

### NOT VALIDATED / blocked
- DB runtime checks blocked when runtime database dependencies/credentials unavailable.
- Telegram UI callback route-check runtime interaction requires bot token + operator session.
- Paper open/close lifecycle runtime proof requires active seeded signal publication flow.
- Health endpoint runtime check requires running app process.

## Safety posture

- Activation guards remained OFF/NOT SET by harness design (read-only checks only).
- Harness does not mutate guard values.
- Harness does not execute live trading or real CLOB path.

## Risks / follow-up

- Execute harness on staging/prod runner with full dependencies (`pydantic`, async runtime deps) and runtime secrets.
- Capture artifact JSON + logs from real run for SENTINEL gate.
- Expand harness with explicit cross-user close/update negative checks once runtime seed path is available.

## State

- State files updated for lane traceability and next gate handoff.
- NEXT GATE: WARP•SENTINEL required (MAJOR lane).
