# 24_66_phase2_9_dual_mode_routing_validation_pr424

## Environment
- Validation date (UTC): 2026-04-12
- Repository: `/workspace/walker-ai-team`
- HEAD ref: `work` (Codex worktree detached-style ref accepted by policy)
- Requested branch context: `feature/gateway-dual-mode-routing-2026-04-12`
- Validation mode: `NARROW_INTEGRATION_CHECK`

## Validation Context
- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Target files:
  - `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`
  - `projects/polymarket/polyquantbot/platform/gateway/gateway_factory.py`
  - `projects/polymarket/polyquantbot/platform/gateway/__init__.py`
  - `projects/polymarket/polyquantbot/tests/test_phase2_7_public_app_gateway_skeleton_20260411.py`
  - `projects/polymarket/polyquantbot/tests/test_phase2_9_dual_mode_routing_foundation_20260412.py`
  - `projects/polymarket/polyquantbot/tests/test_phase2_legacy_core_facade_adapter_foundation_20260411.py`
- Declared source report: `projects/polymarket/polyquantbot/reports/forge/24_65_phase2_9_dual_mode_routing_foundation.md`
- Not in Scope (as requested): live/public activation, execution engine rewrite, risk model changes, multi-user DB integration, wallet auth implementation, Fly.io staging deploy, Phase 3 execution-safe MVP.

## Phase 0 Checks
1. **Forge report exists at exact path + 6 sections**: **FAIL (Critical Drift)**
   - Expected: `projects/polymarket/polyquantbot/reports/forge/24_65_phase2_9_dual_mode_routing_foundation.md`
   - Actual: file not present; nearest `24_65_*` artifact is `24_65_fix_project_state_ledger_pr423.md`.
2. **PROJECT_STATE full timestamp format**: PASS (`2026-04-12 01:25`)
3. **Domain structure validity**: PASS for touched scope (gateway + tests under existing project structure)
4. **No forbidden phase*/ folders**: PASS (`find` returned no matches)
5. **Implementation evidence for claimed routing additions**: **FAIL** (dual-mode constants/modes absent)
6. **No drift between report/state/code**: **FAIL (Critical Drift)**

## Findings by Category

### A) Artifact & Traceability

#### A1 — Missing mandatory forge source report (CRITICAL)
- File path: `projects/polymarket/polyquantbot/reports/forge/24_65_phase2_9_dual_mode_routing_foundation.md`
- Line(s): N/A (file missing)
- Snippet:
  ```text
  sed: can't read projects/polymarket/polyquantbot/reports/forge/24_65_phase2_9_dual_mode_routing_foundation.md: No such file or directory
  ```
- Reason: MAJOR validation cannot confirm claim metadata against the declared source artifact.
- Severity: **CRITICAL**

#### A2 — Target Phase 2.9 test artifact missing (CRITICAL)
- File path: `projects/polymarket/polyquantbot/tests/test_phase2_9_dual_mode_routing_foundation_20260412.py`
- Line(s): N/A (file missing)
- Snippet:
  ```text
  ERROR: file or directory not found: projects/polymarket/polyquantbot/tests/test_phase2_9_dual_mode_routing_foundation_20260412.py
  ```
- Reason: Required validation surface for Phase 2.9 does not exist in repo snapshot under review.
- Severity: **CRITICAL**

### B) Architecture / Routing Integrity

#### B1 — Dual-mode parser contract not implemented (CRITICAL)
- File path: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`
- Line(s): constants block near top
- Snippet:
  ```python
  PUBLIC_APP_GATEWAY_DISABLED = "disabled"
  PUBLIC_APP_GATEWAY_LEGACY_FACADE = "legacy-facade"
  ```
- Reason: Declared Phase 2.9 modes (`legacy-only`, `platform-gateway-shadow`, `platform-gateway-primary`) are not defined.
- Severity: **CRITICAL**

#### B2 — Parser fails closed to disabled for unimplemented modes (Observed behavior)
- File path: `projects/polymarket/polyquantbot/platform/gateway/gateway_factory.py`
- Line(s): parser function
- Snippet:
  ```python
  if selected in {PUBLIC_APP_GATEWAY_DISABLED, PUBLIC_APP_GATEWAY_LEGACY_FACADE}:
      return selected
  return PUBLIC_APP_GATEWAY_DISABLED
  ```
- Runtime proof:
  ```text
  legacy-only -> disabled
  platform-gateway-shadow -> disabled
  platform-gateway-primary -> disabled
  ```
- Reason: Fail-closed behavior exists, but declared dual-mode routing foundation is absent.
- Severity: **MAJOR**

#### B3 — Phase 2.7 and 2.8 seams remain intact (PASS)
- File path: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`
- Snippet:
  ```python
  if not self._facade.assert_adapter_usage():
      raise RuntimeError("adapter_not_used_in_gateway_path")
  ```
- Reason: Adapter enforcement fail-fast still present; no direct core import regression found in gateway file path tested by existing Phase 2.8 test.
- Severity: INFO

### C) Functional / Safety Behavior

#### C1 — activation_requested fail-fast contract not implemented as specified (CRITICAL)
- File path: `projects/polymarket/polyquantbot/platform/gateway/gateway_factory.py`
- Line(s): `build_public_app_gateway` signature
- Snippet:
  ```python
  def build_public_app_gateway(*, mode: str | None = None, resolver: ContextResolver | None = None) -> PublicAppGateway:
  ```
- Runtime proof:
  ```text
  TypeError: build_public_app_gateway() got an unexpected keyword argument 'activation_requested'
  ```
- Reason: Required explicit fail-fast runtime contract for `activation_requested=True` is not implemented; only Python signature error occurs.
- Severity: **CRITICAL**

#### C2 — Runtime non-activation remains true on available modes (PASS)
- File path: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`
- Snippet:
  ```python
  activated=False,
  runtime_routing_active=False,
  ```
- Runtime proof:
  ```text
  resolve disabled False False ...
  resolve legacy-facade False False ...
  ```
- Reason: Non-activation property remains preserved for currently implemented modes.
- Severity: INFO

### D) Negative Tests and Command Compliance

#### D1 — Mandatory command set partially unexecutable due missing artifacts (CRITICAL)
- File path: test path above (missing)
- Snippet:
  ```text
  [Errno 2] No such file or directory: ...test_phase2_9_dual_mode_routing_foundation_20260412.py
  ```
- Reason: Cannot satisfy full required negative testing set without target test module.
- Severity: **CRITICAL**

## Score Breakdown
- Artifact integrity & traceability: 5 / 20
- Architecture claim match: 8 / 25
- Functional fail-closed + fail-fast contracts: 12 / 25
- Negative testing completeness: 5 / 20
- Safety/regression checks (2.7/2.8 continuity): 8 / 10

**Total Score: 38 / 100**

## Critical Issues
1. Missing declared forge source report at required path.
2. Missing Phase 2.9 target test file.
3. Missing dual-mode routing constants/paths in gateway implementation.
4. Missing explicit `activation_requested=True` fail-fast contract implementation.

## Status
**BLOCKED**

## PR Gate Result
**DO NOT MERGE (BLOCKED)** — Required MAJOR validation evidence cannot be completed and implementation does not match declared Phase 2.9 target behavior.

## Broader Audit Finding
System drift detected:
- component: Forge source artifact linkage
- expected: `projects/polymarket/polyquantbot/reports/forge/24_65_phase2_9_dual_mode_routing_foundation.md`
- actual: Missing; present `24_65_fix_project_state_ledger_pr423.md` is unrelated to Phase 2.9 routing implementation.

System drift detected:
- component: Phase 2.9 runtime/test scope
- expected: dual-mode routing + dedicated Phase 2.9 tests
- actual: gateway currently exposes only `disabled` and `legacy-facade`; Phase 2.9 test file absent.

## Reasoning
- NARROW_INTEGRATION scope was respected by validating only targeted gateway and test surfaces plus direct behavior proofs.
- Existing implementation is still Phase 2.7/2.8 style foundation; it does not satisfy declared Phase 2.9 dual-mode routing foundation scope.
- Fail-closed default remains intact, but this alone is insufficient for approval when explicit new-mode and fail-fast contract requirements are unmet.

## Fix Recommendations
1. Add the missing forge source report at exact declared path with full 6 sections + required metadata.
2. Implement explicit gateway modes and routing contracts for:
   - `legacy-only`
   - `platform-gateway-shadow`
   - `platform-gateway-primary`
3. Add explicit runtime contract for `activation_requested=True` to raise deterministic domain RuntimeError (not generic TypeError).
4. Add required target test module `test_phase2_9_dual_mode_routing_foundation_20260412.py` and cover all mandatory negative tests.
5. Re-run full MAJOR validation command set after implementation/report alignment.

## Out-of-scope Advisory
- Keep public/live activation disabled as declared not-in-scope until Phase 3 safety contracts are validated.
- Preserve adapter enforcement and direct-core-import guard tests from Phase 2.8 during Phase 2.9 implementation.

## Deferred Minor Backlog
- None (all observed blockers are critical for claimed MAJOR scope).

## Telegram Visual Preview
```text
🚫 SENTINEL PR #424 — BLOCKED (38/100)
Critical drift: missing Phase 2.9 forge report + missing Phase 2.9 test file.
Current gateway still supports only disabled/legacy-facade.
Fail-closed default preserved, but claimed dual-mode routing not delivered.
Action: return to FORGE-X for report/code/test alignment, then re-run MAJOR validation.
```
