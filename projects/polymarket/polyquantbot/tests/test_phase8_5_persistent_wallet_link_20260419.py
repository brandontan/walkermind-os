"""Phase 8.5 tests — persistent wallet-link storage + lifecycle foundation."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from projects.polymarket.polyquantbot.server.main import create_app
from projects.polymarket.polyquantbot.server.storage.wallet_link_store import (
    PersistentWalletLinkStore,
    WalletLinkStorageError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(monkeypatch, tmp_path: Path, *, wallet_storage_name: str = "wallet_links.json"):
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", str(tmp_path / "sessions.json"))
    monkeypatch.setenv("CRUSADER_WALLET_LINK_STORAGE_PATH", str(tmp_path / wallet_storage_name))
    return create_app()


def _setup_user_and_session(
    client: TestClient, tenant_id: str, external_id: str, display_name: str
) -> tuple[dict, dict]:
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


# ---------------------------------------------------------------------------
# Unit tests — PersistentWalletLinkStore direct behavior
# ---------------------------------------------------------------------------


def test_persistent_store_put_and_get_roundtrip(tmp_path: Path) -> None:
    store_path = tmp_path / "wallet_links.json"
    from projects.polymarket.polyquantbot.server.schemas.wallet_link import WalletLinkRecord
    from datetime import datetime, timezone

    store = PersistentWalletLinkStore(storage_path=store_path)
    record = WalletLinkRecord(
        link_id="wlink-unit-001",
        tenant_id="tenant-unit",
        user_id="user-unit",
        wallet_address="0xunit001",
        chain_id="polygon",
        link_type="user_proxy",
        linked_at=datetime(2026, 4, 19, 10, 0, 0, tzinfo=timezone.utc),
        status="active",
    )
    store.put_link(record)

    assert store_path.exists()
    result = store.get_link("wlink-unit-001")
    assert result is not None
    assert result.wallet_address == "0xunit001"
    assert result.status == "active"


def test_persistent_store_load_from_disk_on_init(tmp_path: Path) -> None:
    store_path = tmp_path / "wallet_links.json"
    from projects.polymarket.polyquantbot.server.schemas.wallet_link import WalletLinkRecord
    from datetime import datetime, timezone

    store1 = PersistentWalletLinkStore(storage_path=store_path)
    record = WalletLinkRecord(
        link_id="wlink-persist-001",
        tenant_id="tenant-persist",
        user_id="user-persist",
        wallet_address="0xpersist001",
        chain_id="polygon",
        link_type="external",
        linked_at=datetime(2026, 4, 19, 10, 0, 0, tzinfo=timezone.utc),
        status="active",
    )
    store1.put_link(record)

    # Second instance reads from same path — simulates restart
    store2 = PersistentWalletLinkStore(storage_path=store_path)
    result = store2.get_link("wlink-persist-001")
    assert result is not None
    assert result.wallet_address == "0xpersist001"
    assert result.tenant_id == "tenant-persist"
    assert result.user_id == "user-persist"


def test_persistent_store_set_link_status(tmp_path: Path) -> None:
    store_path = tmp_path / "wallet_links.json"
    from projects.polymarket.polyquantbot.server.schemas.wallet_link import WalletLinkRecord
    from datetime import datetime, timezone

    store = PersistentWalletLinkStore(storage_path=store_path)
    record = WalletLinkRecord(
        link_id="wlink-status-001",
        tenant_id="tenant-status",
        user_id="user-status",
        wallet_address="0xstatus001",
        chain_id="polygon",
        link_type="user_proxy",
        linked_at=datetime(2026, 4, 19, 10, 0, 0, tzinfo=timezone.utc),
        status="active",
    )
    store.put_link(record)

    updated = store.set_link_status("wlink-status-001", "unlinked")
    assert updated.status == "unlinked"

    # Verify persisted
    store2 = PersistentWalletLinkStore(storage_path=store_path)
    reloaded = store2.get_link("wlink-status-001")
    assert reloaded is not None
    assert reloaded.status == "unlinked"


def test_persistent_store_set_link_status_not_found_raises(tmp_path: Path) -> None:
    store_path = tmp_path / "wallet_links.json"
    store = PersistentWalletLinkStore(storage_path=store_path)

    try:
        store.set_link_status("wlink-does-not-exist", "unlinked")
        assert False, "expected WalletLinkStorageError"
    except WalletLinkStorageError as exc:
        assert "wlink-does-not-exist" in str(exc)


def test_persistent_store_list_for_user_scoped(tmp_path: Path) -> None:
    store_path = tmp_path / "wallet_links.json"
    from projects.polymarket.polyquantbot.server.schemas.wallet_link import WalletLinkRecord
    from datetime import datetime, timezone

    store = PersistentWalletLinkStore(storage_path=store_path)
    base_dt = datetime(2026, 4, 19, 10, 0, 0, tzinfo=timezone.utc)

    for i in range(3):
        store.put_link(WalletLinkRecord(
            link_id=f"wlink-ua-{i:03d}",
            tenant_id="tenant-list",
            user_id="user-A",
            wallet_address=f"0xuserA{i:03d}",
            chain_id="polygon",
            link_type="user_proxy",
            linked_at=base_dt,
            status="active",
        ))

    store.put_link(WalletLinkRecord(
        link_id="wlink-ub-000",
        tenant_id="tenant-list",
        user_id="user-B",
        wallet_address="0xuserB000",
        chain_id="polygon",
        link_type="user_proxy",
        linked_at=base_dt,
        status="active",
    ))

    result_a = store.list_links_for_user("tenant-list", "user-A")
    result_b = store.list_links_for_user("tenant-list", "user-B")
    assert len(result_a) == 3
    assert len(result_b) == 1
    assert all(r.user_id == "user-A" for r in result_a)


# ---------------------------------------------------------------------------
# Integration tests — restart-safe readback via HTTP
# ---------------------------------------------------------------------------


def test_wallet_link_persists_across_app_restart(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")

    session_path = str(tmp_path / "sessions.json")
    wallet_path = str(tmp_path / "wallet_links.json")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", session_path)
    monkeypatch.setenv("CRUSADER_WALLET_LINK_STORAGE_PATH", wallet_path)

    link_id: str | None = None

    # First app instance: create user, get session, create wallet-link
    app1 = create_app()
    with TestClient(app1) as client1:
        user, session = _setup_user_and_session(client1, "tenant-restart", "tg_r001", "restart-user")
        headers = _auth_headers(session, user)

        create_resp = client1.post(
            "/auth/wallet-links",
            json={"wallet_address": "0xrestart001", "chain_id": "polygon", "link_type": "user_proxy"},
            headers=headers,
        )
        assert create_resp.status_code == 200
        link_id = create_resp.json()["wallet_link"]["link_id"]

    # Second app instance with same storage paths — simulates server restart
    app2 = create_app()
    with TestClient(app2) as client2:
        # Re-issue session (sessions persist too) — verify wallet-link still present
        list_resp = client2.get("/auth/wallet-links", headers=headers)
        assert list_resp.status_code == 200
        links = list_resp.json()["wallet_links"]
        assert len(links) == 1
        assert links[0]["link_id"] == link_id
        assert links[0]["wallet_address"] == "0xrestart001"
        assert links[0]["status"] == "active"


def test_multiple_users_wallet_links_survive_restart(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")

    session_path = str(tmp_path / "sessions.json")
    wallet_path = str(tmp_path / "wallet_links.json")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", session_path)
    monkeypatch.setenv("CRUSADER_WALLET_LINK_STORAGE_PATH", wallet_path)

    user_a_data: dict = {}
    user_b_data: dict = {}

    app1 = create_app()
    with TestClient(app1) as client1:
        user_a, session_a = _setup_user_and_session(client1, "tenant-multi", "tg_m001", "alice")
        user_b, session_b = _setup_user_and_session(client1, "tenant-multi", "tg_m002", "bob")

        client1.post(
            "/auth/wallet-links",
            json={"wallet_address": "0xalice001"},
            headers=_auth_headers(session_a, user_a),
        )
        client1.post(
            "/auth/wallet-links",
            json={"wallet_address": "0xbob001"},
            headers=_auth_headers(session_b, user_b),
        )

        user_a_data = {"user": user_a, "session": session_a}
        user_b_data = {"user": user_b, "session": session_b}

    app2 = create_app()
    with TestClient(app2) as client2:
        links_a = client2.get(
            "/auth/wallet-links",
            headers=_auth_headers(user_a_data["session"], user_a_data["user"]),
        ).json()["wallet_links"]
        links_b = client2.get(
            "/auth/wallet-links",
            headers=_auth_headers(user_b_data["session"], user_b_data["user"]),
        ).json()["wallet_links"]

        assert len(links_a) == 1
        assert links_a[0]["wallet_address"] == "0xalice001"
        assert len(links_b) == 1
        assert links_b[0]["wallet_address"] == "0xbob001"


# ---------------------------------------------------------------------------
# Integration tests — unlink lifecycle
# ---------------------------------------------------------------------------


def test_unlink_wallet_link_sets_status_unlinked(monkeypatch, tmp_path: Path) -> None:
    app = _make_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        user, session = _setup_user_and_session(client, "tenant-unlink", "tg_u001", "unlink-user")
        headers = _auth_headers(session, user)

        create_resp = client.post(
            "/auth/wallet-links",
            json={"wallet_address": "0xunlink001"},
            headers=headers,
        )
        assert create_resp.status_code == 200
        link_id = create_resp.json()["wallet_link"]["link_id"]

        unlink_resp = client.patch(
            f"/auth/wallet-links/{link_id}/unlink",
            headers=headers,
        )
        assert unlink_resp.status_code == 200
        result = unlink_resp.json()["wallet_link"]
        assert result["status"] == "unlinked"
        assert result["link_id"] == link_id


def test_unlink_status_persists_after_restart(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")

    session_path = str(tmp_path / "sessions.json")
    wallet_path = str(tmp_path / "wallet_links.json")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", session_path)
    monkeypatch.setenv("CRUSADER_WALLET_LINK_STORAGE_PATH", wallet_path)

    link_id: str = ""
    headers: dict = {}

    app1 = create_app()
    with TestClient(app1) as client1:
        user, session = _setup_user_and_session(client1, "tenant-unlinkpersist", "tg_up001", "up-user")
        headers = _auth_headers(session, user)

        create_resp = client1.post(
            "/auth/wallet-links",
            json={"wallet_address": "0xunlinkpersist001"},
            headers=headers,
        )
        link_id = create_resp.json()["wallet_link"]["link_id"]

        client1.patch(f"/auth/wallet-links/{link_id}/unlink", headers=headers)

    app2 = create_app()
    with TestClient(app2) as client2:
        list_resp = client2.get("/auth/wallet-links", headers=headers)
        links = list_resp.json()["wallet_links"]
        assert len(links) == 1
        assert links[0]["link_id"] == link_id
        assert links[0]["status"] == "unlinked"


def test_unlink_not_found_returns_404(monkeypatch, tmp_path: Path) -> None:
    app = _make_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        user, session = _setup_user_and_session(client, "tenant-unlink404", "tg_404", "not-found-user")
        headers = _auth_headers(session, user)

        resp = client.patch("/auth/wallet-links/wlink-does-not-exist/unlink", headers=headers)
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]


def test_unlink_cross_user_denied_returns_403(monkeypatch, tmp_path: Path) -> None:
    app = _make_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        user_a, session_a = _setup_user_and_session(client, "tenant-crossunlink", "tg_cu001", "owner")
        user_b, session_b = _setup_user_and_session(client, "tenant-crossunlink", "tg_cu002", "intruder")

        create_resp = client.post(
            "/auth/wallet-links",
            json={"wallet_address": "0xowner001"},
            headers=_auth_headers(session_a, user_a),
        )
        assert create_resp.status_code == 200
        link_id = create_resp.json()["wallet_link"]["link_id"]

        # user_b attempts to unlink user_a's wallet-link
        resp = client.patch(
            f"/auth/wallet-links/{link_id}/unlink",
            headers=_auth_headers(session_b, user_b),
        )
        assert resp.status_code == 403


def test_unlink_requires_authenticated_session(monkeypatch, tmp_path: Path) -> None:
    app = _make_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        resp = client.patch(
            "/auth/wallet-links/wlink-any/unlink",
            headers={
                "X-Session-Id": "sess_missing",
                "X-Auth-Tenant-Id": "tenant-alpha",
                "X-Auth-User-Id": "user-xyz",
            },
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Integration tests — cross-user isolation on persistent storage
# ---------------------------------------------------------------------------


def test_persistent_cross_user_isolation_via_http(monkeypatch, tmp_path: Path) -> None:
    app = _make_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        user_a, session_a = _setup_user_and_session(client, "tenant-iso", "tg_iso001", "iso-user-a")
        user_b, session_b = _setup_user_and_session(client, "tenant-iso", "tg_iso002", "iso-user-b")

        client.post(
            "/auth/wallet-links",
            json={"wallet_address": "0xisoA001"},
            headers=_auth_headers(session_a, user_a),
        )

        list_b = client.get("/auth/wallet-links", headers=_auth_headers(session_b, user_b))
        assert list_b.status_code == 200
        assert list_b.json()["wallet_links"] == []
