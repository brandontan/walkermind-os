from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from projects.polymarket.polyquantbot.server.core.scope import ResourceOwnership, ScopeResolutionError, check_ownership, resolve_scope
from projects.polymarket.polyquantbot.server.main import create_app


def test_scope_resolution_rejects_empty_tenant() -> None:
    try:
        resolve_scope(tenant_id="", user_id="user-1")
    except ScopeResolutionError as exc:
        assert "tenant_id" in str(exc)
    else:
        raise AssertionError("resolve_scope should reject empty tenant_id")


def test_scope_ownership_detects_mismatch() -> None:
    scope = resolve_scope(tenant_id="tenant-alpha", user_id="user-a")
    check = check_ownership(
        scope=scope,
        ownership=ResourceOwnership(
            resource_type="wallet",
            resource_id="wallet-1",
            tenant_id="tenant-alpha",
            user_id="user-b",
        ),
    )
    assert check.is_owner is False


def test_multi_user_routes_enforce_wallet_scope(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", str(tmp_path / "sessions.json"))

    app = create_app()
    with TestClient(app) as client:
        user_response = client.post(
            "/foundation/users",
            json={"tenant_id": "tenant-alpha", "external_id": "tg_1001", "display_name": "alice"},
        )
        assert user_response.status_code == 200
        user_payload = user_response.json()["user"]

        session_response = client.post(
            "/foundation/sessions",
            json={"tenant_id": user_payload["tenant_id"], "user_id": user_payload["user_id"]},
        )
        assert session_response.status_code == 200
        session_payload = session_response.json()["session"]

        account_response = client.post(
            "/foundation/accounts",
            json={
                "tenant_id": user_payload["tenant_id"],
                "user_id": user_payload["user_id"],
                "label": "primary",
            },
        )
        assert account_response.status_code == 200
        account_payload = account_response.json()["account"]

        wallet_response = client.post(
            "/foundation/wallets",
            json={
                "tenant_id": user_payload["tenant_id"],
                "user_id": user_payload["user_id"],
                "account_id": account_payload["account_id"],
                "address": "0xabc123",
            },
        )
        assert wallet_response.status_code == 200
        wallet_payload = wallet_response.json()["wallet"]

        denied_response = client.get(
            f"/foundation/wallets/{wallet_payload['wallet_id']}",
            headers={
                "X-Session-Id": session_payload["session_id"],
                "X-Auth-Tenant-Id": "tenant-alpha",
                "X-Auth-User-Id": "intruder-user",
            },
        )
        assert denied_response.status_code == 403

        allowed_response = client.get(
            f"/foundation/wallets/{wallet_payload['wallet_id']}",
            headers={
                "X-Session-Id": session_payload["session_id"],
                "X-Auth-Tenant-Id": user_payload["tenant_id"],
                "X-Auth-User-Id": user_payload["user_id"],
            },
        )
        assert allowed_response.status_code == 200
        assert allowed_response.json()["wallet"]["address"] == "0xabc123"


def test_scope_dependency_rejects_missing_session(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", str(tmp_path / "sessions.json"))

    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/foundation/auth/scope",
            headers={
                "X-Session-Id": "sess_missing",
                "X-Auth-Tenant-Id": "tenant-alpha",
                "X-Auth-User-Id": "user-alpha",
            },
        )
        assert response.status_code == 403
        assert "session not found" in response.json()["detail"]


def test_scope_dependency_derives_authenticated_scope(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", str(tmp_path / "sessions.json"))

    app = create_app()
    with TestClient(app) as client:
        user_response = client.post(
            "/foundation/users",
            json={"tenant_id": "tenant-beta", "external_id": "tg_2001", "display_name": "bob"},
        )
        assert user_response.status_code == 200
        user_payload = user_response.json()["user"]

        session_response = client.post(
            "/foundation/sessions",
            json={"tenant_id": user_payload["tenant_id"], "user_id": user_payload["user_id"]},
        )
        assert session_response.status_code == 200
        session_payload = session_response.json()["session"]

        scope_response = client.get(
            "/foundation/auth/scope",
            headers={
                "X-Session-Id": session_payload["session_id"],
                "X-Auth-Tenant-Id": user_payload["tenant_id"],
                "X-Auth-User-Id": user_payload["user_id"],
            },
        )
        assert scope_response.status_code == 200
        scope = scope_response.json()["scope"]
        assert scope["tenant_id"] == user_payload["tenant_id"]
        assert scope["user_id"] == user_payload["user_id"]
        assert scope["session_id"] == session_payload["session_id"]


def test_persisted_session_readback_and_restart_safe_scope(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    session_path = tmp_path / "persistent_sessions.json"
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", str(session_path))

    app = create_app()
    with TestClient(app) as client:
        user_response = client.post(
            "/foundation/users",
            json={"tenant_id": "tenant-gamma", "external_id": "tg_3001", "display_name": "carol"},
        )
        user_payload = user_response.json()["user"]

        session_response = client.post(
            "/foundation/sessions",
            json={"tenant_id": user_payload["tenant_id"], "user_id": user_payload["user_id"]},
        )
        assert session_response.status_code == 200
        session_payload = session_response.json()["session"]

    assert session_path.exists()

    app_after_restart = create_app()
    with TestClient(app_after_restart) as restarted_client:
        scope_response = restarted_client.get(
            "/foundation/auth/scope",
            headers={
                "X-Session-Id": session_payload["session_id"],
                "X-Auth-Tenant-Id": user_payload["tenant_id"],
                "X-Auth-User-Id": user_payload["user_id"],
            },
        )
        assert scope_response.status_code == 200
        assert scope_response.json()["scope"]["session_id"] == session_payload["session_id"]


def test_revoked_session_is_rejected(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", str(tmp_path / "sessions.json"))

    app = create_app()
    with TestClient(app) as client:
        user_response = client.post(
            "/foundation/users",
            json={"tenant_id": "tenant-delta", "external_id": "tg_4001", "display_name": "dina"},
        )
        user_payload = user_response.json()["user"]

        session_response = client.post(
            "/foundation/sessions",
            json={"tenant_id": user_payload["tenant_id"], "user_id": user_payload["user_id"]},
        )
        session_payload = session_response.json()["session"]

        revoke_response = client.post(f"/foundation/sessions/{session_payload['session_id']}/revoke")
        assert revoke_response.status_code == 200
        assert revoke_response.json()["session"]["status"] == "revoked"

        scope_response = client.get(
            "/foundation/auth/scope",
            headers={
                "X-Session-Id": session_payload["session_id"],
                "X-Auth-Tenant-Id": user_payload["tenant_id"],
                "X-Auth-User-Id": user_payload["user_id"],
            },
        )
        assert scope_response.status_code == 403
        assert "not active" in scope_response.json()["detail"]


def test_expired_session_is_rejected(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", str(tmp_path / "sessions.json"))

    app = create_app()
    with TestClient(app) as client:
        user_response = client.post(
            "/foundation/users",
            json={"tenant_id": "tenant-epsilon", "external_id": "tg_5001", "display_name": "erin"},
        )
        user_payload = user_response.json()["user"]

        session_response = client.post(
            "/foundation/sessions",
            json={
                "tenant_id": user_payload["tenant_id"],
                "user_id": user_payload["user_id"],
                "ttl_seconds": 60,
            },
        )
        session_payload = session_response.json()["session"]

        from projects.polymarket.polyquantbot.server.services import auth_session_service as auth_module

        original_now_utc = auth_module.now_utc

        def _future_now():
            return original_now_utc() + timedelta(seconds=300)

        monkeypatch.setattr(auth_module, "now_utc", _future_now)

        scope_response = client.get(
            "/foundation/auth/scope",
            headers={
                "X-Session-Id": session_payload["session_id"],
                "X-Auth-Tenant-Id": user_payload["tenant_id"],
                "X-Auth-User-Id": user_payload["user_id"],
            },
        )
        assert scope_response.status_code == 403
        assert "expired" in scope_response.json()["detail"]
