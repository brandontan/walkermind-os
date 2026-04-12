# SENTINEL Report — 24_66_phase2_9_dual_mode_routing_validation_pr424

## Environment
- Repo: `/workspace/walker-ai-team`
- Branch context: `work` (Codex worktree mode; accepted per CODEX WORKTREE RULE)
- Validation date (UTC): `2026-04-12`
- Tier: `MAJOR`
- Claim Level: `NARROW INTEGRATION`
- Validation Mode: `NARROW_INTEGRATION_CHECK`

## Validation Context
- Forge source: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_65_phase2_9_dual_mode_routing_foundation.md`
- Target files validated:
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/gateway_factory.py`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/__init__.py`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_phase2_7_public_app_gateway_skeleton_20260411.py`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_phase2_9_dual_mode_routing_foundation_20260412.py`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_phase2_legacy_core_facade_adapter_foundation_20260411.py`
- Not in scope enforced: live/public activation, execution rewrite, risk changes, multi-user DB, wallet auth, Fly.io deploy, Phase 3 MVP.

## Phase 0 Checks
1. Forge report existence + 6 mandatory sections: **PASS** (all sections present).
2. `PROJECT_STATE.md` timestamp format (`YYYY-MM-DD HH:MM`): **PASS** (`2026-04-12 02:10`).
3. Domain structure validity for touched files: **PASS** (all under locked domain + root metadata).
4. Forbidden `phase*/` folders: **PASS** (`find` output empty).
5. Claimed routing additions present in code: **PASS**.
6. Drift check (report/state/code): **PASS with advisory** (ROADMAP status lag; see Broader Audit Finding).

## Findings by category

### A) Architecture & Surface Continuity

**A1 — Dual-mode routing contract implemented additively (PASS)**  
- File: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`  
- Lines: 9-13, 24-45, 113-172  
- Snippet:
```python
PUBLIC_APP_GATEWAY_DISABLED = "disabled"
PUBLIC_APP_GATEWAY_LEGACY_ONLY = "legacy-only"
PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW = "platform-gateway-shadow"
PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY = "platform-gateway-primary"
...
class PublicAppGatewayRoutingTrace:
...
class PublicAppGatewayPlatformGatewayShadow:
class PublicAppGatewayPlatformGatewayPrimary:
```
- Reason: Adds explicit routing modes/trace/classes without removing prior seam classes.
- Severity: INFO

**A2 — Phase 2.7/2.8 seam continuity preserved (PASS)**  
- File: `projects/polymarket/polyquantbot/platform/gateway/__init__.py`  
- Lines: 20-61  
- Snippet:
```python
PUBLIC_APP_GATEWAY_LEGACY_FACADE,
PublicAppGatewayLegacyFacade,
...
"PUBLIC_APP_GATEWAY_LEGACY_FACADE",
"PublicAppGatewayLegacyFacade",
```
- Reason: Existing exports still present; additive extension only.
- Severity: INFO

**A3 — No direct core import regression in gateway routing file (PASS)**  
- File: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`  
- Lines: 1-7  
- Snippet:
```python
from ..context.resolver import LegacySessionSeed
from .legacy_core_facade import LegacyCoreFacade, LegacyCoreFacadeResolution
```
- Reason: Gateway file imports context/facade seams only; no direct `core` import path.
- Severity: INFO

### B) Functional Routing Validation

**B1 — Mode parser supports required modes and fails closed (PASS)**  
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
- Reason: Deterministic allowed-set parse + fail-closed error path.
- Severity: INFO

**B2 — Legacy-only path remains non-activating (PASS)**  
- File: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`  
- Lines: 102-110  
- Snippet:
```python
return PublicAppGatewayResolution(
    activated=False,
    runtime_routing_active=False,
    mode=self._config.mode,
    source=PUBLIC_APP_GATEWAY_LEGACY_ONLY,
```
- Reason: Explicit runtime and activation flags remain false.
- Severity: INFO

**B3 — Shadow and primary remain structural and non-activating (PASS)**  
- File: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`  
- Lines: 133-141, 164-172  
- Snippet:
```python
activated=False,
runtime_routing_active=False,
source=PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW,
...
activated=False,
runtime_routing_active=False,
source=PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY,
```
- Reason: Both platform modes kept inactive by contract.
- Severity: INFO

**B4 — Routing trace metadata populated (PASS)**  
- File: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`  
- Lines: 24-33, 95-101, 126-132, 157-163  
- Snippet:
```python
class PublicAppGatewayRoutingTrace:
    selected_mode: str
    selected_path: str
    platform_participated: bool
    adapter_enforced: bool
    runtime_activation_remained_disabled: bool
```
- Reason: All required metadata fields exist and are populated across modes.
- Severity: INFO

### C) Guardrail / Bypass Attempts

**C1 — Adapter bypass blocked on legacy path (PASS)**  
- File: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`  
- Lines: 89-93  
- Snippet:
```python
if not self._facade.assert_adapter_usage():
    raise RuntimeError("adapter_not_used_in_gateway_path")
```
- Runtime proof: `RuntimeError adapter_not_used_in_gateway_path` (manual break test).
- Reason: Intended path cannot bypass adapter gate.
- Severity: INFO

**C2 — Adapter bypass blocked on platform path (PASS)**  
- File: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`  
- Lines: 120-123, 151-154  
- Snippet:
```python
if not self._facade.assert_adapter_usage():
    raise RuntimeError("adapter_not_used_in_platform_gateway_path")
```
- Runtime proof: `RuntimeError adapter_not_used_in_platform_gateway_path`.
- Reason: Platform path enforces fail-fast adapter guard.
- Severity: INFO

**C3 — Unsafe activation blocked (PASS)**  
- File: `projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`  
- Lines: 92-94, 123-125, 154-156  
- Snippet:
```python
if self._config.activation_requested:
    raise RuntimeError("attempted_active_routing_without_explicit_safe_contract")
```
- Runtime proof: `RuntimeError attempted_active_routing_without_explicit_safe_contract`.
- Reason: Explicit active routing attempts fail fast.
- Severity: INFO

### D) Test Evidence

**D1 — Focused suite passes (PASS)**  
- Command: `PYTHONPATH=/workspace/walker-ai-team pytest -q ...`  
- Result: `22 passed, 1 warning`.
- Reason: All targeted tests for Phase 2.7/2.8/2.9 pass.
- Severity: INFO

**D2 — Malformed/unsupported mode input fails closed (PASS)**  
- Runtime proof command outputs:
  - `INVALID='bad-mode' -> ValueError:invalid_gateway_mode:bad-mode`
  - `INVALID=' platform-gateway-shadow\ninvalid ' -> ValueError:invalid_gateway_mode:...`
  - `INVALID='legacy_only' -> ValueError:invalid_gateway_mode:legacy_only`
- Reason: Parser rejects malformed and unsupported alias formats.
- Severity: INFO

## Score Breakdown
- Phase 0 checks: 20/20
- Architecture integrity: 20/20
- Functional routing behavior: 25/25
- Guardrail/bypass resistance: 20/20
- Test/runtime evidence quality: 13/15 (minor deduction: warning-only environment has pytest config warning)
- Drift/state consistency: 7/10 (ROADMAP lag advisory)

**Final Score: 95/100**

## Critical Issues
- None.

## Status
- SENTINEL Verdict: **APPROVED**
- Claim validation: **Aligned** with `NARROW INTEGRATION` (structural inactive routing only).

## PR Gate Result
- **APPROVED** for COMMANDER merge decision.

## Broader Audit Finding
- `ROADMAP.md` still marks Phase 2.9 as `❌` and Phase 2.8 as `🚧`, while `PROJECT_STATE.md` and code indicate Phase 2.9 implementation landed. This is documentation-state lag, not runtime risk.

## Reasoning
- The implementation is structurally additive, retains prior seams, and enforces explicit fail-closed/fail-fast safety contracts.
- Runtime proof demonstrates that all supported modes remain non-activating in this phase.
- Negative/bypass attempts behave as required and do not expose execution/public activation drift.

## Fix Recommendations
1. Sync `ROADMAP.md` phase 2.8/2.9 status to match merged code reality.
2. Keep `activation_requested` guard immutable in factory defaults until explicit future safe-enable contract is reviewed by SENTINEL.

## Out-of-scope Advisory
- No findings in execution, capital, risk constants, or live trading activation layers were evaluated beyond gateway boundary impact (per declared scope).

## Deferred Minor Backlog
- [DEFERRED] `ROADMAP.md` phase status lag for 2.8/2.9 versus `PROJECT_STATE.md` + code evidence (documentation consistency only).

## Telegram Visual Preview
- N/A — no frontend/UI component changes in this task; no browser screenshot required.
