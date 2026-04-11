# SENTINEL Validation — resolver-purity-final-validation-pr390-2026-04-10

- Date: 2026-04-10
- Branch: `fix/resolver-purity-final-unblock-2026-04-10`
- Env: `dev`
- Validation Tier: `MAJOR`
- Scope: resolver purity loop closure for PR #390 (target files from COMMANDER task)

## Verdict
- Verdict: **BLOCKED**
- Resolver is PURE: **NO**
- Execution path clean: **NO**
- Final recommendation: **FIX REQUIRED (do not merge PR #390 yet)**

## Hard Gate Results

### 1) Syntax + Compile
**FAILED**

Command:
- `python -m py_compile projects/polymarket/polyquantbot/platform/context/resolver.py ...`

Evidence:
- `SyntaxError: expected ':'` in resolver constructor signature (`) => None:`). File: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/context/resolver.py` line 38.

Additional syntax blockers found in targeted test file:
- `From __future__ import annotations` (invalid keyword case)
- malformed env assignment string at line 38 (`PLATFORM_AUTH_PROVIDER � = "polymarket"`), causing unterminated string literal.

### 2) Import Chain
**FAILED**

Command:
- Python import probe for:
  - `projects.polymarket.polyquantbot.main`
  - `projects.polymarket.polyquantbot.telegram.command_handler`
  - `projects.polymarket.polyquantbot.execution.strategy_trigger`
  - `projects.polymarket.polyquantbot.legacy.adapters.context_bridge`
  - `projects.polymarket.polyquantbot.platform.context.resolver`

Evidence:
- `main` import succeeds.
- Remaining chain fails with resolver syntax exception (`resolver.py`, line 38), therefore startup/import chain is not stable.

### 3) Resolver Purity — Direct
**FAILED**

Status:
- Resolver cannot execute due syntax failure.
- Direct purity contract cannot be proven runtime-safe until syntax is fixed.

### 4) Resolver Purity — Indirect
**FAILED**

Evidence (read path still writes when repos are injected):
- `AccountService.resolve_user_account(...)` performs `self._repository.upsert(record)` when no existing row.
- `WalletAuthService.resolve_wallet_binding(...)` performs `self._repository.upsert(record)` when no existing row.
- `PermissionService.resolve_permission_profile(...)` performs `self._repository.upsert(record)` when no existing row.

Result:
- Indirect resolver path is not read-only under repository-enabled mode.

### 5) Explicit Read/Write Split Verification
**FAILED**

Expected by validation target:
- explicit write methods: `ensure_user_account`, `ensure_wallet_binding`, `ensure_permission_profile`
- explicit read methods: `resolve_*` no writes

Observed:
- `ensure_*` methods do not exist in the scoped services.
- `resolve_*` methods contain persistence writes.

Conclusion:
- read/write split is not implemented; current split is cosmetic/non-existent.

### 6) Write-Spy Proof
**FAILED / NOT PROVABLE**

Result:
- No passing write-spy regression evidence available in scoped tests.
- Existing targeted tests do not produce demonstrable `write_calls == []` proof for resolver path.

### 7) Bridge Integrity
**FAILED**

Evidence:
- `LegacyContextBridge` constructs `ContextResolver(...)` with unsupported args:
  - `execution_context_repository=...`
  - `audit_event_repository=...`
- Current resolver constructor in scope does not accept those parameters.

Result:
- Bridge wiring and resolver constructor signature are mismatched.

### 8) Startup Stability
**FAILED**

Evidence:
- Import chain instability via resolver syntax failure blocks normal startup chain consumers.
- `main.py` still contains startup print lines (`"🚀 PolyQuantBot starting (Railway)"`, `"🚀 NEW TELEGRAM SYSTEM ACTIVE"`, `"ENTRYPOINT: main.py"`), so duplicate banner-spam removal claim is not evidenced.

### 9) Activation Monitor Safety
**FAILED**

Evidence:
- `SystemActivationMonitor.start()` creates background tasks directly using `asyncio.create_task(...)` for log/assert loops.
- No guarded task wrapper / done-callback / exception-drain mechanism is present.
- `_assert_loop()` raises `RuntimeError` on no events; no active containment path to prevent unhandled background exception leakage.

Result:
- final activation-monitor safety objective is not met.

### 10) Targeted Test Execution
**FAILED**

Command:
- `pytest -q projects/polymarket/polyquantbot/tests/test_platform_phase2_persistence_wallet_auth_foundation_20260410.py projects/polymarket/polyquantbot/tests/test_platform_foundation_phase1_legacy_readonly_bridge_20260410.py projects/polymarket/polyquantbot/tests/test_system_activation_final.py`

Evidence:
- collection error from syntax corruption in `test_platform_phase2_persistence_wallet_auth_foundation_20260410.py`
- resolver syntax error propagates into bridge/runtime test collection

### 11) Execution Path Contamination Check
**CONDITIONAL ADVISORY**

Findings:
- No direct strategy-alpha/risk-model rule edits were validated as changed in this scoped check.
- However, import-chain breakage and bridge mismatch contaminate runtime startup and can alter behavior through failure/degraded paths.

Conclusion:
- execution path cannot be certified clean for merge in current state.

### 12) Forge Report Integrity
**FAILED**

Expected report path from task:
- `projects/polymarket/polyquantbot/reports/forge/24_52_resolver_purity_final_unblock_20260410.md`

Observed:
- file is missing.
- latest existing forge files are `24_50_...` and `24_51_...`.

Result:
- report/code traceability for this claimed final unblock is broken.

## Critical Issues
1. Resolver syntax invalid (`resolver.py` line 38) blocks compile/import chain.
2. Resolver path is not pure under repository mode due indirect `upsert` writes in `resolve_*` methods.
3. Explicit read/write split contract missing (`ensure_*` not implemented).
4. Bridge constructor wiring passes unsupported resolver dependencies.
5. Activation monitor lacks guarded background-task exception containment.
6. Declared forge report for this PR scope is missing.
7. Targeted tests fail at collection; no passing safety proof.

## Non-Critical Issues
- Pytest warning: unknown config option `asyncio_mode` (environment/config warning, non-primary blocker).
- Startup print noise still present; requires confirmation against intended logging policy after blockers are fixed.

## Required Remediation Before Revalidation
1. Fix resolver and scoped test-file syntax errors.
2. Implement true read/write split:
   - keep `resolve_*` strictly read-only
   - move writes to explicit `ensure_*` methods
   - update call sites accordingly
3. Remove unsupported resolver constructor args from bridge or update resolver signature coherently (while preserving purity target).
4. Add guarded task runner/exception handling path for activation monitor background tasks.
5. Restore/commit missing forge report at declared path with claims matching code reality.
6. Re-run py_compile + import chain + targeted tests with clean pass evidence.

