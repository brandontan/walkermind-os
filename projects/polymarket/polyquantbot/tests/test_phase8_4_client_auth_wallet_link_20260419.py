"""Phase 8.4 tests — client auth handoff contract + wallet-link ownership enforcement."""
from __future__ import annotations

from fastapi.testclient import TestClient

from projects.polymarket.polyquantbot.server.core.client_auth_handoff import (
    ClientHandoffContract,
    validate_client_handoff,
)
from projects.polymarket.polyquantbot.server.main import create_app


# ---------------------------------------------------------------------------
# Unit tests — client auth handoff contract (no HTTP, pure function)
# ---------------------------------------------------------------------------


def test_handoff_validates_known_telegram_client() -> None:
    result = validate_client_handoff(
        ClientHandoffContract(
            client_type="telegram",
            client_identity_claim="tg_9999",
            tenant_id="tenant-alpha",
            user_id="user-a",
        )
    )
    assert result.outcome == "valid"
    assert result.auth_method == "telegram"


def test_handoff_validates_known_web_client() -> None:
    result = validate_client_handoff(
        ClientHandoffContract(
            client_type="web",
            client_identity_claim="web-session-token-abc",
            tenant_id="tenant-alpha",
            user_id="user-b",
        )
    )
    assert result.outcome == "valid"
    assert result.auth_method == "web"


def test_handoff_rejects_unsupported_client_type() -> None:
    result = validate_client_handoff(
        ClientHandoffContract(
            client_type="discord",
            client_identity_claim="discord_123",
            tenant_id="tenant-alpha",
            user_id="user-a",
        )
    )
    assert result.outcome == "rejected_unsupported_client_type"


def test_handoff_rejects_empty_claim() -> None:
    result = validate_client_handoff(
        ClientHandoffContract(
            client_type="telegram",
            client_identity_claim="   ",
            tenant_id="tenant-alpha",
            user_id="user-a",
        )
    )
    assert result.outcome == "rejected_empty_claim"


def test_handoff_rejects_empty_scope() -> None:
    result = validate_client_handoff(
        ClientHandoffContract(
            client_type="telegram",
            client_identity_claim="tg_9999",
            tenant_id="",
            user_id="user-a",
        )
    )
    assert result.outcome == "rejected_empty_scope"


# ---------------------------------------------------------------------------
# Integration tests — /auth/handoff route
# ---------------------------------------------------------------------------


def test_client_handoff_issues_session_for_known_user(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", str(tmp_path / "sessions.json"))

    app = create_app()
    with TestClient(app) as client:
        user_resp = client.post(
            "/foundation/users",
            json={"tenant_id": "tenant-alpha", "external_id": "tg_1001", "display_name": "alice"},
        )
        assert user_resp.status_code == 200
        user = user_resp.json()["user"]

        handoff_resp = client.post(
            "/auth/handoff",
            json={
                "client_type": "telegram",
                "client_identity_claim": "tg_1001",
                "tenant_id": user["tenant_id"],
                "user_id": user["user_id"],
            },
        )
        assert handoff_resp.status_code == 200
        payload = handoff_resp.json()
        assert payload["session"]["status"] == "active"
        assert payload["session"]["auth_method"] == "telegram"
        assert payload["scope"]["tenant_id"] == user["tenant_id"]
        assert payload["scope"]["user_id"] == user["user_id"]


def test_client_handoff_rejects_unknown_user(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", str(tmp_path / "sessions.json"))

    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/auth/handoff",
            json={
                "client_type": "telegram",
                "client_identity_claim": "tg_9999",
                "tenant_id": "tenant-alpha",
                "user_id": "user-does-not-exist",
            },
        )
        assert resp.status_code == 400
        assert "user not found" in resp.json()["detail"]


def test_client_handoff_rejects_unsupported_client_type_via_route(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", str(tmp_path / "sessions.json"))

    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/auth/handoff",
            json={
                "client_type": "discord",
                "client_identity_claim": "discord_999",
                "tenant_id": "tenant-alpha",
                "user_id": "user-abc",
            },
        )
        assert resp.status_code == 400
        assert "unsupported client_type" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Integration tests — wallet-link create / read / isolation
# ---------------------------------------------------------------------------


def _setup_user_and_session(client: TestClient, tenant_id: str, external_id: str, display_name: str) -> tuple[dict, dict]:
    user_resp = client.post(
        "/foundation/users",
        json={"tenant_id": tenant_id, "external_id": external_id, "display_name": display_name},
    )
    assert user_resp.status_code == 200
    user = user_resp.json()["user"]

    handoff_resp = client.post(
        "/auth/handoff",
        json={
            "client_type": "telegram",
            "client_identity_claim": external_id,
            "tenant_id": user["tenant_id"],
            "user_id": user["user_id"],
        },
    )
    assert handoff_resp.status_code == 200
    session = handoff_resp.json()["session"]
    return user, session


def _auth_headers(session: dict, user: dict) -> dict[str, str]:
    return {
        "X-Session-Id": session["session_id"],
        "X-Auth-Tenant-Id": user["tenant_id"],
        "X-Auth-User-Id": user["user_id"],
    }


def test_wallet_link_create_and_read_for_authenticated_user(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", str(tmp_path / "sessions.json"))

    app = create_app()
    with TestClient(app) as client:
        user, session = _setup_user_and_session(client, "tenant-beta", "tg_2001", "bob")
        headers = _auth_headers(session, user)

        create_resp = client.post(
            "/auth/wallet-links",
            json={"wallet_address": "0xdeadbeef001", "chain_id": "polygon", "link_type": "user_proxy"},
            headers=headers,
        )
        assert create_resp.status_code == 200
        link = create_resp.json()["wallet_link"]
        assert link["wallet_address"] == "0xdeadbeef001"
        assert link["tenant_id"] == user["tenant_id"]
        assert link["user_id"] == user["user_id"]
        assert link["status"] == "active"
        assert link["link_type"] == "user_proxy"

        list_resp = client.get("/auth/wallet-links", headers=headers)
        assert list_resp.status_code == 200
        links = list_resp.json()["wallet_links"]
        assert len(links) == 1
        assert links[0]["link_id"] == link["link_id"]


def test_wallet_link_requires_authenticated_session(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", str(tmp_path / "sessions.json"))

    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/auth/wallet-links",
            json={"wallet_address": "0xfakeaddr"},
            headers={
                "X-Session-Id": "sess_missing",
                "X-Auth-Tenant-Id": "tenant-alpha",
                "X-Auth-User-Id": "user-xyz",
            },
        )
        assert resp.status_code == 403


def test_wallet_link_cross_user_isolation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", str(tmp_path / "sessions.json"))

    app = create_app()
    with TestClient(app) as client:
        user_a, session_a = _setup_user_and_session(client, "tenant-gamma", "tg_3001", "carol")
        user_b, session_b = _setup_user_and_session(client, "tenant-gamma", "tg_3002", "dave")

        client.post(
            "/auth/wallet-links",
            json={"wallet_address": "0xcarol111"},
            headers=_auth_headers(session_a, user_a),
        )

        list_resp_b = client.get(
            "/auth/wallet-links",
            headers=_auth_headers(session_b, user_b),
        )
        assert list_resp_b.status_code == 200
        # user_b has no wallet-links — cannot see user_a's
        assert list_resp_b.json()["wallet_links"] == []


def test_wallet_link_cross_tenant_session_denied(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", str(tmp_path / "sessions.json"))

    app = create_app()
    with TestClient(app) as client:
        user_a, session_a = _setup_user_and_session(client, "tenant-delta", "tg_4001", "erin")

        tampered_headers = {
            "X-Session-Id": session_a["session_id"],
            "X-Auth-Tenant-Id": "tenant-delta",
            "X-Auth-User-Id": "intruder-user-999",
        }
        resp = client.post(
            "/auth/wallet-links",
            json={"wallet_address": "0xintruder"},
            headers=tampered_headers,
        )
        assert resp.status_code == 403
