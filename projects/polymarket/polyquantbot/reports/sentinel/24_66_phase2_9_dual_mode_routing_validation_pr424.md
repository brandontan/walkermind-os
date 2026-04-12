# SENTINEL Report — 24_66_phase2_9_dual_mode_routing_validation_pr424

## Environment
- Repo: `/workspace/walker-ai-team`
- Branch context: `work` (Codex worktree mode accepted per CODEX WORKTREE RULE)
- Validation date (UTC): `2026-04-12`
- Tier: `MAJOR`
- Claim Level: `NARROW INTEGRATION`
- Validation Mode: `NARROW_INTEGRATION_CHECK`

## Validation Context
- Forge source: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_65_phase2_9_dual_mode_routing_foundation.md`
- Target files:
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/gateway_factory.py`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/__init__.py`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_phase2_7_public_app_gateway_skeleton_20260411.py`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_phase2_9_dual_mode_routing_foundation_20260412.py`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_phase2_legacy_core_facade_adapter_foundation_20260411.py`
- Not in Scope enforced: live trading activation; public API activation; execution engine rewrite; risk model changes; multi-user DB integration; wallet auth implementation; Fly.io staging deploy; Phase 3 execution-safe MVP.

## Phase 0 Checks
1. Forge report exists at exact path and contains all 6 mandatory sections: **PASS**.
2. `PROJECT_STATE.md` uses full timestamp format (`YYYY-MM-DD HH:MM`): **PASS**.
3. Domain structure valid for touched scope: **PASS**.
4. Forbidden `phase*/` folders present: **NO** (`find` returned empty): **PASS**.
5. Implementation evidence exists for claimed routing additions: **PASS**.
6. Drift between report/state/code for declared scope: **NONE DETECTED**.

## Findings by category

### 1) Architecture Validation

**F1 — Dual-mode routing is additive and preserves 2.7/2.8 seam (PASS)**
- File: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`
- Lines: 9-13, 76-172
- Snippet:
```python
PUBLIC_APP_GATEWAY_DISABLED = "disabled"
PUBLIC_APP_GATEWAY_LEGACY_ONLY = "legacy-only"
PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW = "platform-gateway-shadow"
PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY = "platform-gateway-primary"
...
class PublicAppGatewayLegacyFacade:
...
class PublicAppGatewayPlatformGatewayShadow:
...
class PublicAppGatewayPlatformGatewayPrimary:
```
- Reason: Existing legacy facade surface is retained and new platform shadow/primary classes are additive.
- Severity: INFO

**F2 — Facade adapter enforcement and no fake abstraction regression (PASS)**
- File: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`
- Lines: 89-94, 120-125, 151-156
- Snippet:
```python
if not self._facade.assert_adapter_usage():
    raise RuntimeError("adapter_not_used_in_gateway_path")
if self._config.activation_requested:
    raise RuntimeError("attempted_active_routing_without_explicit_safe_contract")
```
- Reason: Runtime path explicitly blocks adapter bypass and active routing in this phase.
- Severity: INFO

**F3 — Imports resolve to real platform modules, no direct core import regression (PASS)**
- File: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`
- Lines: 1-7
- Snippet:
```python
from ..context.resolver import LegacySessionSeed
from .legacy_core_facade import LegacyCoreFacade, LegacyCoreFacadeResolution
```
- Reason: Gateway routing file stays on declared platform seam and does not import core runtime modules directly.
- Severity: INFO

### 2) Functional Validation

**F4 — `parse_public_app_gateway_mode()` supports required modes and fails closed (PASS)**
- File: `projects/polymarket/polyquantbot/platform/gateway/gateway_factory.py`
- Lines: 24-40
- Snippet:
```python
supported_modes = {
    PUBLIC_APP_GATEWAY_DISABLED,
    PUBLIC_APP_GATEWAY_LEGACY_ONLY,
    PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW,
    PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY,
}
if normalized not in supported_modes:
    raise ValueError(f"invalid_gateway_mode:{selected}")
```
- Reason: Unsupported/malformed values are rejected deterministically.
- Severity: INFO

**F5 — Legacy-only / shadow / primary all remain non-activating (PASS)**
- File: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`
- Lines: 102-110, 133-141, 164-172
- Snippet:
```python
activated=False,
runtime_routing_active=False,
```
- Reason: All supported mode resolutions keep activation disabled and routing inactive.
- Severity: INFO

**F6 — Routing trace metadata contract populated (PASS)**
- File: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`
- Lines: 24-33, 95-101, 126-132, 157-163
- Snippet:
```python
selected_mode
selected_path
platform_participated
adapter_enforced
runtime_activation_remained_disabled
```
- Reason: Required trace fields exist and are set on each path.
- Severity: INFO

### 3) Behavior / Bypass Checks

**F7 — Invalid mode/malformed input fails closed (PASS)**
- Files: `projects/polymarket/polyquantbot/platform/gateway/gateway_factory.py`, `projects/polymarket/polyquantbot/tests/test_phase2_9_dual_mode_routing_foundation_20260412.py`
- Lines: gateway_factory.py 38-39; test file 36-44
- Snippet:
```python
raise ValueError(f"invalid_gateway_mode:{selected}")
```
- Runtime proof:
  - `invalid_mode_check: ValueError invalid_gateway_mode:bad-mode`
- Reason: fail-closed semantics are active in parser and runtime.
- Severity: INFO

**F8 — Activation request fails fast (PASS)**
- File: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`
- Lines: 123-125, 154-156
- Snippet:
```python
if self._config.activation_requested:
    raise RuntimeError("attempted_active_routing_without_explicit_safe_contract")
```
- Runtime proof:
  - `activation_requested_check: RuntimeError attempted_active_routing_without_explicit_safe_contract`
- Reason: explicit block prevents unsafe activation during foundation phase.
- Severity: INFO

**F9 — Adapter bypass attempt fails fast (PASS)**
- Files: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`, `projects/polymarket/polyquantbot/tests/test_phase2_9_dual_mode_routing_foundation_20260412.py`
- Lines: public_app_gateway.py 89-90; test file 106-134
- Snippet:
```python
if not self._facade.assert_adapter_usage():
    raise RuntimeError("adapter_not_used_in_gateway_path")
```
- Runtime proof:
  - `adapter_enforcement_check: RuntimeError adapter_not_used_in_gateway_path`
- Reason: intended gateway path cannot bypass adapter contract.
- Severity: INFO

**F10 — No execution endpoint invocation introduced by this task (PASS)**
- Files: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`, `projects/polymarket/polyquantbot/platform/gateway/gateway_factory.py`
- Lines: public_app_gateway.py 84-172; gateway_factory.py 43-73
- Snippet:
```python
facade_resolution = self._facade.prepare_execution_context(seed)
```
- Reason: route resolution remains context/facade structural; no execution submit/cancel invocation added.
- Severity: INFO

## Score Breakdown
- Phase 0 Checks: 20/20
- Architecture Validation: 20/20
- Functional Validation: 25/25
- Behavior / Bypass Checks: 20/20
- Evidence completeness + command verification: 15/15

**Final Score: 100/100**

## Critical Issues
- None.

## Status
- Verdict: **APPROVED**
- Tier/Claim alignment: **Aligned** (`MAJOR` / `NARROW INTEGRATION`)

## PR Gate Result
- **APPROVED** — ready for COMMANDER merge decision.

## Broader Audit Finding
- None in declared scope.

## Reasoning
- The validated implementation is additive, preserves Phase 2.7 and 2.8 surfaces, enforces fail-closed mode parsing, and retains structural non-activation for all supported routing modes.
- Break attempts (invalid mode, activation request, adapter bypass) failed as required.

## Fix Recommendations
1. Preserve `activation_requested=False` factory default until future explicit safe-contract phase is validated.
2. Keep parser allowlist strict to prevent unsupported alias drift.

## Out-of-scope Advisory
- Live/public activation, execution engine semantics, and risk model behavior were intentionally not evaluated beyond routing-surface non-activation guarantees.

## Deferred Minor Backlog
- None.

## Telegram Visual Preview
- N/A — backend routing validation only; no front-end visual component changes.
