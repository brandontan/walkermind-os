# SENTINEL Validation Report — phase2-7-public-app-gateway-skeleton-validation (PR #413)

> Superseded for merge-gating by `projects/polymarket/polyquantbot/reports/sentinel/24_61_phase2_7_public_app_gateway_skeleton_rerun_pr413.md` (branch-accurate rerun).

## Validation Metadata
- Date (UTC): 2026-04-11
- Role: SENTINEL (explicit COMMANDER request)
- Validation Tier: MAJOR
- Claim Level: FOUNDATION
- Branch Context: `feature/infra-phase2-7-gateway-skeleton-2026-04-12` (Codex worktree head reports `work`)
- Verdict: **BLOCKED**
- Merge Safety: **NOT SAFE TO MERGE**

## Scope Validated
Requested validation target (from task):
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/__init__.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/gateway_factory.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/api/__init__.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/api/app_gateway.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_phase2_7_public_app_gateway_skeleton_20260411.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_60_phase2_7_public_app_gateway_skeleton_foundation.md`
- `/workspace/walker-ai-team/ROADMAP.md`
- `/workspace/walker-ai-team/PROJECT_STATE.md`

Actual repository artifacts found for this scope:
- `platform/gateway/factory.py` exists, but `platform/gateway/gateway_factory.py` is missing.
- `api/app_gateway.py` is missing.
- `tests/test_phase2_7_public_app_gateway_skeleton_20260411.py` is missing.
- Forge report path `24_60_phase2_7_public_app_gateway_skeleton_foundation.md` is missing; only `24_7_public_app_gateway_skeleton.md` exists.

## Required Commands and Evidence
1) Phase-folder scan
- Command: `find /workspace/walker-ai-team -type d -name 'phase*'`
- Result: PASS (no `phase*` directories detected).

2) Compile/parse gate on requested modules
- Command: `python -m compileall /workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway /workspace/walker-ai-team/projects/polymarket/polyquantbot/api /workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_phase2_7_public_app_gateway_skeleton_20260411.py`
- Result: PARTIAL. Gateway and API modules compile, but requested test file path cannot be listed (`Can't list ...test_phase2_7_public_app_gateway_skeleton_20260411.py`).

3) Focused pytest gate
- Command: `PYTHONPATH=/workspace/walker-ai-team pytest -q /workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_phase2_7_public_app_gateway_skeleton_20260411.py /workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_phase2_legacy_core_facade_adapter_foundation_20260411.py`
- Result: FAIL. Requested Phase 2.7 test file does not exist; pytest exits code 4.

Supplemental direct-dependency test attempt:
- Command: `PYTHONPATH=/workspace/walker-ai-team pytest -q /workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_gateway_skeleton.py /workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_phase2_legacy_core_facade_adapter_foundation_20260411.py`
- Result: FAIL. `test_gateway_skeleton.py` import path is invalid (`ModuleNotFoundError: No module named 'platform.gateway'; 'platform' is not a package`).

## Severity-Ranked Findings

### CRITICAL-1 — Validation target artifact mismatch and missing mandatory evidence files
- Requested target files are missing (`gateway_factory.py`, `api/app_gateway.py`, phase2_7 test file, forge report `24_60...`).
- This breaks traceability and prevents branch-specific MAJOR validation against the claimed scope.
- Impact: claim cannot be verified as requested; merge safety cannot be established.

### CRITICAL-2 — Non-activation contract is contradicted by implementation (`legacy`/`platform` modes marked active)
- `PublicAppGateway.is_active` returns `self._config.mode != "disabled"`.
- `GatewayConfig` allows `"legacy"` and `"platform"`; both evaluate active, which violates the task’s required “foundation non-activating seam” interpretation.
- Impact: hidden activation drift risk via mode selection semantics; FOUNDATION claim is overstated for non-activation guarantee.

### CRITICAL-3 — Gateway seam does not compose through the Phase 2.8 deterministic facade factory path
- `GatewayFactory.build_gateway` constructs `LegacyCoreFacade()` directly instead of using `build_legacy_core_facade(...)` from `facade_factory.py`.
- This bypasses deterministic env-mode parsing and fallback behavior in the established Phase 2.8 seam.
- Impact: architectural continuity claim is not met; seam reuse is incomplete and behavior may drift.

### HIGH-1 — Test evidence is not truthful for requested scope and currently non-executable
- Requested test file is missing.
- Existing `test_gateway_skeleton.py` uses non-repo import roots (`from platform.gateway...`) and fails collection.
- Therefore no executable evidence currently proves deterministic disabled-by-default behavior for the public/app seam contract.

### HIGH-2 — Forge report overclaims and is out of sync with code and expected naming/paths
- Forge report path and filename do not match requested artifact (`24_60...` expected vs `24_7...` present).
- Report claims “explicit mode selection (`legacy`, `platform`)” and “reuse of Phase 2.8 facade seam,” but current factory path directly instantiates protocol-like facade and does not route through `build_legacy_core_facade`.
- Impact: report-to-code drift; claim-level trustworthiness reduced.

### MEDIUM-1 — State/Roadmap drift for phase truth
- `ROADMAP.md` still marks 2.7 and 2.8 as not started, while gateway and facade seam files/tests exist.
- `PROJECT_STATE.md` also does not present this Phase 2.7 artifact set in current in-progress/completed truth.
- Impact: project coordination drift; not a direct runtime blocker, but governance risk.

## Code-Level Validation Notes (Direct Dependency Scope)
- `platform/gateway/facade_factory.py` correctly defaults mode to `disabled` and falls back safely for unknown values.
- `platform/gateway/factory.py` does not reuse `facade_factory.py` and therefore misses this deterministic path.
- `platform/gateway/public_app_gateway.py` treats non-disabled as active, which conflicts with requested non-activating skeleton guarantee.
- No direct modifications detected in risk/execution modules within this validation target; no evidence of execution/risk layer drift from this seam-only subset.

## Claim-Level Assessment (FOUNDATION)
- FOUNDATION can be acceptable only if the seam is strictly non-activating by default and does not imply live runtime routing.
- Current code and tests do not sufficiently prove that contract:
  - missing requested tests,
  - failing existing tests,
  - activation semantics set true for non-disabled modes,
  - composition bypass of deterministic facade factory.
- Result: FOUNDATION claim is **not fully supported**.

## Final Decision
- **Verdict: BLOCKED**
- **Merge recommendation for PR #413: Do not merge** until blockers are fixed and requested evidence files/paths are aligned.

## Required Follow-up Before Revalidation
1. Align artifacts to validation target (or update target) so requested files exist and are testable.
2. Route gateway construction through `build_legacy_core_facade(...)` deterministic seam in Phase 2.8 path.
3. Ensure non-activation contract is explicit and unambiguous for all FOUNDATION modes (including explicit legacy-facade seam mode).
4. Replace/fix tests so they import via repo package path and pass in CI/local.
5. Regenerate forge report with accurate file list, correct naming/path, and truthful claims.
6. Sync ROADMAP/PROJECT_STATE to actual Phase 2.7/2.8 code truth.
