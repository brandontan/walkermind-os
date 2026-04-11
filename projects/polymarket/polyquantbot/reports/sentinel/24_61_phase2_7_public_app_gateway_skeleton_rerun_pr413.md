# SENTINEL Rerun Report — phase2-7-public-app-gateway-skeleton-rerun-pr413

## Validation Metadata
- Date (UTC): 2026-04-11
- PR: #413 (FORGE-X code PR)
- Validation Tier: MAJOR
- Claim Level: FOUNDATION
- Verdict: **BLOCKED**
- Merge Safety: **NOT SAFE TO MERGE**
- Branch context: Codex worktree HEAD reports `work` (accepted per worktree rule); validation executed against current local branch contents.

## 1) Gate Confirmation
- PR type: FORGE-X code PR (gateway + tests + forge report artifacts in target project).
- Tier: MAJOR.
- SENTINEL requirement: mandatory before merge (satisfied by this rerun).

## 2) Branch-Accurate Artifact Truth
Requested target set names and current branch names are not fully aligned. Rerun used **actual branch artifacts** as authoritative code truth.

### Requested target path status
- Exists: `platform/gateway/__init__.py`
- Missing by name: `platform/gateway/gateway_factory.py` (branch has `platform/gateway/factory.py`)
- Exists: `platform/gateway/public_app_gateway.py`
- Exists: `api/__init__.py`
- Missing: `api/app_gateway.py`
- Missing by name: `tests/test_phase2_7_public_app_gateway_skeleton_20260411.py` (branch has `tests/test_gateway_skeleton.py`)
- Exists: `tests/test_phase2_legacy_core_facade_adapter_foundation_20260411.py`
- Missing by name: `reports/forge/24_60_phase2_7_public_app_gateway_skeleton_foundation.md` (branch has `reports/forge/24_7_public_app_gateway_skeleton.md`)

### Branch-accurate validation set used
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/__init__.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/factory.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/facade_factory.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/legacy_core_facade.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/api/__init__.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_gateway_skeleton.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_phase2_legacy_core_facade_adapter_foundation_20260411.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_7_public_app_gateway_skeleton.md`
- `/workspace/walker-ai-team/ROADMAP.md`
- `/workspace/walker-ai-team/PROJECT_STATE.md`

## 3) Required Command Evidence
1. `find /workspace/walker-ai-team -type d -name 'phase*'`
- Result: PASS (no phase folders).

2. `python -m compileall /workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway /workspace/walker-ai-team/projects/polymarket/polyquantbot/api /workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_phase2_7_public_app_gateway_skeleton_20260411.py`
- Result: PARTIAL (gateway + api compile; requested test path missing so compileall prints `Can't list ...test_phase2_7_public_app_gateway_skeleton_20260411.py`).

3. `PYTHONPATH=/workspace/walker-ai-team pytest -q /workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_phase2_7_public_app_gateway_skeleton_20260411.py /workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_phase2_legacy_core_facade_adapter_foundation_20260411.py`
- Result: FAIL (requested phase2_7 test file missing).

Supplemental branch-accurate evidence runs:
- `PYTHONPATH=/workspace/walker-ai-team pytest -q .../tests/test_gateway_skeleton.py` → FAIL at collection (`ModuleNotFoundError: No module named 'platform.gateway'; 'platform' is not a package`).
- `PYTHONPATH=/workspace/walker-ai-team pytest -q .../tests/test_phase2_legacy_core_facade_adapter_foundation_20260411.py` → PASS (4 tests).
- Runtime break check:
  - `GatewayFactory.build_gateway(GatewayConfig())` raises `TypeError: Protocols cannot be instantiated` (because factory calls `LegacyCoreFacade()` directly).

## 4) Seam and Boundary Findings (Severity-ranked)

### CRITICAL-1 — Factory seam is non-functional at runtime (protocol instantiation)
Evidence:
- `factory.py` uses `facade = LegacyCoreFacade()`.
- `LegacyCoreFacade` is a `Protocol`; Protocols are not instantiable.
- Runtime proof command returns `TypeError: Protocols cannot be instantiated`.
Impact:
- The claimed Phase 2.7 gateway seam cannot be constructed reliably in real execution path.
- Merge is unsafe for FOUNDATION seam continuity claim.

### CRITICAL-2 — Phase 2.8 facade seam reuse claim is not satisfied in gateway factory path
Evidence:
- Deterministic seam exists in `facade_factory.py` via `build_legacy_core_facade(...)` with disabled-safe default and fallback parsing.
- `factory.py` bypasses this and directly instantiates the protocol type.
Impact:
- Composition path does not match claimed architecture continuity.
- Deterministic mode handling from Phase 2.8 is not reused in gateway builder.

### CRITICAL-3 — Branch test evidence for Phase 2.7 seam is non-executable
Evidence:
- Requested phase2_7 test file does not exist.
- Existing gateway test file fails import due wrong module root (`platform.gateway...`).
Impact:
- Non-activation and seam contract are not test-proven on branch.
- MAJOR-tier validation cannot approve without executable direct contract evidence.

### HIGH-1 — Non-activating semantics are ambiguous at gateway layer
Evidence:
- `PublicAppGateway.is_active` returns `mode != "disabled"`.
- `GatewayConfig` allows `legacy` and `platform`, both considered active.
Assessment:
- If “active” means public/app routing activation, this conflicts with FOUNDATION non-activation intent.
- If “active” means mode intent only, naming is misleading and needs explicit contract clarification.
Impact:
- Not sole blocker by itself, but materially increases contract ambiguity.

### MEDIUM-1 — Requested file/report names vs branch filenames are drifted
Evidence:
- Requested `gateway_factory.py`, `api/app_gateway.py`, `test_phase2_7...`, forge `24_60...` not present by those names.
- Branch has `factory.py`, no `api/app_gateway.py`, `test_gateway_skeleton.py`, forge `24_7...`.
Impact:
- Governance/traceability drift. Treated as rerun context mismatch, not a standalone runtime blocker.

### MEDIUM-2 — ROADMAP/PROJECT_STATE phase tracking drifts from branch artifacts
- ROADMAP and root PROJECT_STATE still indicate 2.7/2.8 not started while related files exist.
- Classified as governance drift only for this rerun scope.

## 5) Validation Focus Conclusions
- Real seam vs cosmetic: **partially present** structurally, but runtime construction currently broken.
- Deterministic non-activation default: present in `facade_factory.py`, but **not used** by `factory.py` path.
- Explicit legacy-facade mode FOUNDATION-only at public/app layer: **not proven** due broken gateway factory + failing gateway tests.
- API boundary seam-only behavior: no `api/app_gateway.py` on branch; no evidence of hidden bootstrap activation in touched files.
- Execution/risk/runtime drift in direct dependency scope: no touched `risk/` or `execution/` module changes detected in this rerun scope.
- Forge report truthfulness: partially aligned to intent but overstates “deterministic construction via GatewayFactory” under current broken instantiation behavior.

## 6) Hardcoded facade mode string check (requested)
- `gateway_factory.py` does not exist on branch; therefore this specific string-constant check is N/A on the requested filename.
- In actual branch files, no hardcoded facade mode string is used in `factory.py` because facade mode selection is not wired there yet.
- Severity classification: **Advisory/Design debt** once factory is corrected to call `build_legacy_core_facade(...)`; then use exported constants for mode values.

## 7) Final Decision for COMMANDER
- **Verdict: BLOCKED**
- **Merge Safety: NOT SAFE TO MERGE**
- Non-activating seam claim support: **insufficient** on this branch head because gateway factory is runtime-broken and seam tests are non-executable.
- Merge status classification: **blocked pending fix** (not merge-safe as-is; not “merge-safe with advisory”).

## 8) Required Fixes Before Next SENTINEL Rerun
1. Fix `platform/gateway/factory.py` to compose through `build_legacy_core_facade(...)` (Phase 2.8 seam) instead of protocol instantiation.
2. Repair/replace gateway seam test to import from repo package path and execute in CI/local.
3. Add/align canonical Phase 2.7 test/report filenames or update declared validation target artifact list to actual canonical names.
4. Clarify gateway-layer activation semantics (name and behavior) so FOUNDATION non-activation is explicit and test-enforced.
5. Keep governance drift (ROADMAP/PROJECT_STATE naming/status) tracked separately from runtime blockers.
