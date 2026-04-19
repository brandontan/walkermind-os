# FORGE-X Report — phase8-1_02_pytest-evidence-pass

**Date:** 2026-04-19 09:18
**Branch:** claude/add-pytest-evidence-pr590-caYse
**PR Evidence Attached To:** PR #590 (feature/establish-multi-user-foundation-based-on-crusader-blueprint-2026-04-19)
**SENTINEL PR:** #591

---

## 1. What was built

No feature code was written. This task produced and attached real executable pytest pass evidence for the Phase 8.1 multi-user foundation implementation delivered in PR #590.

The SENTINEL PR #591 issued a CONDITIONAL verdict because the Codex runner lacked `fastapi` and `pydantic`, causing pytest collection failure. This task ran the required commands in a dependency-complete environment (Python 3.11, fastapi + pydantic + structlog + uvicorn + httpx installed), confirmed 8/8 tests pass, and posted the output to PR #590 and PR #591.

---

## 2. Current system architecture

No architectural changes. All Phase 8.1 multi-user foundation modules remain as delivered in PR #590:

```
server/
  core/scope.py              -- tenant/user scope resolution + ownership guards
  core/runtime.py            -- ApiSettings, RuntimeState, lifecycle helpers
  schemas/multi_user.py      -- Pydantic schemas (User, Account, Wallet, ScopeContext)
  storage/in_memory_store.py -- InMemoryMultiUserStore boundary
  storage/models.py          -- storage dataclasses
  services/user_service.py   -- UserService (create + get)
  services/account_service.py -- AccountService (create + get, scope-checked)
  services/wallet_service.py -- WalletService (create + scope-checked get)
  api/multi_user_foundation_routes.py -- /foundation router
  api/routes.py              -- /health + /ready routes
  main.py                    -- create_app() + lifespan wiring
```

---

## 3. Files created / modified

Created:
- `projects/polymarket/polyquantbot/reports/forge/phase8-1_02_pytest-evidence-pass.md` (this file)

Modified:
- `PROJECT_STATE.md` — updated NEXT PRIORITY and IN PROGRESS to reflect evidence confirmed and COMMANDER merge decision pending

No feature code files were modified.

---

## 4. What is working

Full pytest run on the PR #590 feature branch (`feature/establish-multi-user-foundation-based-on-crusader-blueprint-2026-04-19`):

```
Command:
pytest -q projects/polymarket/polyquantbot/tests/test_crusader_runtime_surface.py \
          projects/polymarket/polyquantbot/tests/test_phase8_1_multi_user_foundation_20260419.py

Output:
........                                                                 [100%]
=============================== warnings summary ===============================
PytestConfigWarning: Unknown config option: asyncio_mode
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
8 passed, 1 warning in 1.00s
```

Test breakdown:

| Test | File | Result |
|---|---|---|
| test_api_settings_uses_fly_port | test_crusader_runtime_surface.py | PASS |
| test_api_settings_rejects_non_strict_startup_mode | test_crusader_runtime_surface.py | PASS |
| test_validate_api_environment_accepts_paper_defaults | test_crusader_runtime_surface.py | PASS |
| test_health_route_reports_crusaderbot_service | test_crusader_runtime_surface.py | PASS |
| test_ready_route_reports_ready_after_startup | test_crusader_runtime_surface.py | PASS |
| test_scope_resolution_rejects_empty_tenant | test_phase8_1_multi_user_foundation_20260419.py | PASS |
| test_scope_ownership_detects_mismatch | test_phase8_1_multi_user_foundation_20260419.py | PASS |
| test_multi_user_routes_enforce_wallet_scope | test_phase8_1_multi_user_foundation_20260419.py | PASS |

---

## 5. Known issues

- `asyncio_mode` pytest config warning is pre-existing hygiene backlog — not a test failure. Carried as `[DEFERRED]` in PROJECT_STATE.md.

---

## 6. What is next

- COMMANDER reviews PR #590 and decides merge.
- PR #591 (SENTINEL CONDITIONAL) can be closed at COMMANDER discretion — its gate condition is now satisfied.
- Post-merge: PROJECT_STATE.md + ROADMAP.md sync for Phase 8.1 completion milestone.

---

**Validation Tier:** MINOR
**Claim Level:** FOUNDATION
**Validation Target:** Real executable pytest output for Phase 8.1 test suite — 8 tests, 0 failures
**Not in Scope:** Feature code changes, live trading, database integration, wallet signing, auth/session
**Suggested Next:** COMMANDER review + merge decision on PR #590
