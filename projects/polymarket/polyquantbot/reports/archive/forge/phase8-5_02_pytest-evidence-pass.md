# Phase 8.5 — Pytest Gate Evidence (Pass)

**Date:** 2026-04-19 12:04
**Branch:** claude/phase8-5-wallet-link-persistence-ExuR9
**PR:** #600
**SENTINEL PR:** #601 (CONDITIONAL — gate satisfied by this evidence)

---

## Required Command

```
pytest -q projects/polymarket/polyquantbot/tests/test_phase8_5_persistent_wallet_link_20260419.py
```

## Extended Command (full regression)

```
pytest -q \
  projects/polymarket/polyquantbot/tests/test_phase8_5_persistent_wallet_link_20260419.py \
  projects/polymarket/polyquantbot/tests/test_phase8_4_client_auth_wallet_link_20260419.py \
  projects/polymarket/polyquantbot/tests/test_phase8_1_multi_user_foundation_20260419.py
```

---

## Output

```
============================= test session starts ==============================
platform linux -- Python 3.11.15, pytest-9.0.3, pluggy-1.6.0 -- /usr/local/bin/python3
cachedir: .pytest_cache
rootdir: /home/user/walker-ai-team
configfile: pytest.ini
plugins: anyio-4.13.0
collecting ... collected 33 items

projects/polymarket/polyquantbot/tests/test_phase8_5_persistent_wallet_link_20260419.py::test_persistent_store_put_and_get_roundtrip PASSED [  3%]
projects/polymarket/polyquantbot/tests/test_phase8_5_persistent_wallet_link_20260419.py::test_persistent_store_load_from_disk_on_init PASSED [  6%]
projects/polymarket/polyquantbot/tests/test_phase8_5_persistent_wallet_link_20260419.py::test_persistent_store_set_link_status PASSED [  9%]
projects/polymarket/polyquantbot/tests/test_phase8_5_persistent_wallet_link_20260419.py::test_persistent_store_set_link_status_not_found_raises PASSED [ 12%]
projects/polymarket/polyquantbot/tests/test_phase8_5_persistent_wallet_link_20260419.py::test_persistent_store_list_for_user_scoped PASSED [ 15%]
projects/polymarket/polyquantbot/tests/test_phase8_5_persistent_wallet_link_20260419.py::test_wallet_link_persists_across_app_restart PASSED [ 18%]
projects/polymarket/polyquantbot/tests/test_phase8_5_persistent_wallet_link_20260419.py::test_multiple_users_wallet_links_survive_restart PASSED [ 21%]
projects/polymarket/polyquantbot/tests/test_phase8_5_persistent_wallet_link_20260419.py::test_unlink_wallet_link_sets_status_unlinked PASSED [ 24%]
projects/polymarket/polyquantbot/tests/test_phase8_5_persistent_wallet_link_20260419.py::test_unlink_status_persists_after_restart PASSED [ 27%]
projects/polymarket/polyquantbot/tests/test_phase8_5_persistent_wallet_link_20260419.py::test_unlink_not_found_returns_404 PASSED [ 30%]
projects/polymarket/polyquantbot/tests/test_phase8_5_persistent_wallet_link_20260419.py::test_unlink_cross_user_denied_returns_403 PASSED [ 33%]
projects/polymarket/polyquantbot/tests/test_phase8_5_persistent_wallet_link_20260419.py::test_unlink_requires_authenticated_session PASSED [ 36%]
projects/polymarket/polyquantbot/tests/test_phase8_5_persistent_wallet_link_20260419.py::test_persistent_cross_user_isolation_via_http PASSED [ 39%]
projects/polymarket/polyquantbot/tests/test_phase8_4_client_auth_wallet_link_20260419.py::test_handoff_validates_known_telegram_client PASSED [ 42%]
projects/polymarket/polyquantbot/tests/test_phase8_4_client_auth_wallet_link_20260419.py::test_handoff_validates_known_web_client PASSED [ 45%]
projects/polymarket/polyquantbot/tests/test_phase8_4_client_auth_wallet_link_20260419.py::test_handoff_rejects_unsupported_client_type PASSED [ 48%]
projects/polymarket/polyquantbot/tests/test_phase8_4_client_auth_wallet_link_20260419.py::test_handoff_rejects_empty_claim PASSED [ 51%]
projects/polymarket/polyquantbot/tests/test_phase8_4_client_auth_wallet_link_20260419.py::test_handoff_rejects_empty_scope PASSED [ 54%]
projects/polymarket/polyquantbot/tests/test_phase8_4_client_auth_wallet_link_20260419.py::test_client_handoff_issues_session_for_known_user PASSED [ 57%]
projects/polymarket/polyquantbot/tests/test_phase8_4_client_auth_wallet_link_20260419.py::test_client_handoff_rejects_unknown_user PASSED [ 60%]
projects/polymarket/polyquantbot/tests/test_phase8_4_client_auth_wallet_link_20260419.py::test_client_handoff_rejects_unsupported_client_type_via_route PASSED [ 63%]
projects/polymarket/polyquantbot/tests/test_phase8_4_client_auth_wallet_link_20260419.py::test_wallet_link_create_and_read_for_authenticated_user PASSED [ 66%]
projects/polymarket/polyquantbot/tests/test_phase8_4_client_auth_wallet_link_20260419.py::test_wallet_link_requires_authenticated_session PASSED [ 69%]
projects/polymarket/polyquantbot/tests/test_phase8_4_client_auth_wallet_link_20260419.py::test_wallet_link_cross_user_isolation PASSED [ 72%]
projects/polymarket/polyquantbot/tests/test_phase8_4_client_auth_wallet_link_20260419.py::test_wallet_link_cross_tenant_session_denied PASSED [ 75%]
projects/polymarket/polyquantbot/tests/test_phase8_1_multi_user_foundation_20260419.py::test_scope_resolution_rejects_empty_tenant PASSED [ 78%]
projects/polymarket/polyquantbot/tests/test_phase8_1_multi_user_foundation_20260419.py::test_scope_ownership_detects_mismatch PASSED [ 81%]
projects/polymarket/polyquantbot/tests/test_phase8_1_multi_user_foundation_20260419.py::test_multi_user_routes_enforce_wallet_scope PASSED [ 84%]
projects/polymarket/polyquantbot/tests/test_phase8_1_multi_user_foundation_20260419.py::test_scope_dependency_rejects_missing_session PASSED [ 87%]
projects/polymarket/polyquantbot/tests/test_phase8_1_multi_user_foundation_20260419.py::test_scope_dependency_derives_authenticated_scope PASSED [ 90%]
projects/polymarket/polyquantbot/tests/test_phase8_1_multi_user_foundation_20260419.py::test_persisted_session_readback_and_restart_safe_scope PASSED [ 93%]
projects/polymarket/polyquantbot/tests/test_phase8_1_multi_user_foundation_20260419.py::test_revoked_session_is_rejected PASSED [ 96%]
projects/polymarket/polyquantbot/tests/test_phase8_1_multi_user_foundation_20260419.py::test_expired_session_is_rejected PASSED [100%]

=============================== warnings summary ===============================
../../../usr/local/lib/python3.11/dist-packages/_pytest/config/__init__.py:1434: PytestConfigWarning: Unknown config option: asyncio_mode

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 33 passed, 1 warning in 2.23s =========================
```

---

## Summary

| Scope | Tests | Result |
|---|---|---|
| Phase 8.5 (new) | 13 | PASS |
| Phase 8.4 regression | 12 | PASS |
| Phase 8.1 regression | 8 | PASS |
| **Total** | **33** | **PASS** |

Environment: Python 3.11.15, pytest-9.0.3, fastapi-0.136.0, pydantic-v2

**SENTINEL CONDITIONAL gate satisfied.** PR #601 can be closed after COMMANDER merges PR #600.
