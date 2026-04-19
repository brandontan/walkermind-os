"""Phase 8.6 — Persistent Multi-User Store Foundation tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

from projects.polymarket.polyquantbot.server.main import create_app
from projects.polymarket.polyquantbot.server.schemas.multi_user import (
    AccountCreate,
    UserCreate,
    WalletCreate,
    new_id,
    now_utc,
)
from projects.polymarket.polyquantbot.server.storage.multi_user_store import (
    MultiUserStoreError,
    PersistentMultiUserStore,
)
from projects.polymarket.polyquantbot.server.schemas.multi_user import (
    AccountRecord,
    UserRecord,
    UserSettingsRecord,
    WalletRecord,
)


# ---------------------------------------------------------------------------
# Unit tests — PersistentMultiUserStore directly
# ---------------------------------------------------------------------------


def test_persistent_store_user_put_and_get_roundtrip(tmp_path) -> None:
    storage = tmp_path / "multi_user.json"
    store = PersistentMultiUserStore(storage_path=storage)

    user = UserRecord(
        user_id=new_id("usr"),
        tenant_id="tenant-alpha",
        external_id="tg_unit_1",
        display_name="Alice",
        created_at=now_utc(),
    )
    store.put_user(user)

    store2 = PersistentMultiUserStore(storage_path=storage)
    result = store2.get_user(user.user_id)
    assert result is not None
    assert result.user_id == user.user_id
    assert result.tenant_id == "tenant-alpha"
    assert result.external_id == "tg_unit_1"


def test_persistent_store_account_put_and_get_roundtrip(tmp_path) -> None:
    storage = tmp_path / "multi_user.json"
    store = PersistentMultiUserStore(storage_path=storage)

    user = UserRecord(
        user_id=new_id("usr"),
        tenant_id="tenant-alpha",
        external_id="tg_unit_2",
        created_at=now_utc(),
    )
    store.put_user(user)

    account = AccountRecord(
        account_id=new_id("acct"),
        tenant_id="tenant-alpha",
        user_id=user.user_id,
        label="primary",
        created_at=now_utc(),
    )
    store.put_account(account)

    store2 = PersistentMultiUserStore(storage_path=storage)
    result = store2.get_account(account.account_id)
    assert result is not None
    assert result.account_id == account.account_id
    assert result.user_id == user.user_id


def test_persistent_store_wallet_put_and_get_roundtrip(tmp_path) -> None:
    storage = tmp_path / "multi_user.json"
    store = PersistentMultiUserStore(storage_path=storage)

    user = UserRecord(
        user_id=new_id("usr"),
        tenant_id="tenant-alpha",
        external_id="tg_unit_3",
        created_at=now_utc(),
    )
    account = AccountRecord(
        account_id=new_id("acct"),
        tenant_id="tenant-alpha",
        user_id=user.user_id,
        label="primary",
        created_at=now_utc(),
    )
    wallet = WalletRecord(
        wallet_id=new_id("wlt"),
        tenant_id="tenant-alpha",
        user_id=user.user_id,
        account_id=account.account_id,
        address="0xdeadbeef",
        created_at=now_utc(),
    )
    store.put_user(user)
    store.put_account(account)
    store.put_wallet(wallet)

    store2 = PersistentMultiUserStore(storage_path=storage)
    result = store2.get_wallet(wallet.wallet_id)
    assert result is not None
    assert result.wallet_id == wallet.wallet_id
    assert result.address == "0xdeadbeef"


def test_persistent_store_load_from_disk_on_init(tmp_path) -> None:
    storage = tmp_path / "multi_user.json"
    store1 = PersistentMultiUserStore(storage_path=storage)

    user = UserRecord(
        user_id=new_id("usr"),
        tenant_id="tenant-gamma",
        external_id="tg_unit_4",
        created_at=now_utc(),
    )
    store1.put_user(user)
    assert storage.exists()

    store2 = PersistentMultiUserStore(storage_path=storage)
    assert store2.get_user(user.user_id) is not None


def test_persistent_store_user_settings_roundtrip(tmp_path) -> None:
    storage = tmp_path / "multi_user.json"
    store = PersistentMultiUserStore(storage_path=storage)

    user = UserRecord(
        user_id=new_id("usr"),
        tenant_id="tenant-delta",
        external_id="tg_unit_5",
        created_at=now_utc(),
    )
    settings = UserSettingsRecord(
        settings_id=new_id("uset"),
        tenant_id="tenant-delta",
        user_id=user.user_id,
        created_at=now_utc(),
    )
    store.put_user(user)
    store.put_user_settings(settings)

    store2 = PersistentMultiUserStore(storage_path=storage)
    result = store2.get_user_settings_for_user(user.user_id)
    assert result is not None
    assert result.settings_id == settings.settings_id


def test_persistent_store_list_accounts_for_user(tmp_path) -> None:
    storage = tmp_path / "multi_user.json"
    store = PersistentMultiUserStore(storage_path=storage)

    user_a = UserRecord(user_id=new_id("usr"), tenant_id="t1", external_id="ea", created_at=now_utc())
    user_b = UserRecord(user_id=new_id("usr"), tenant_id="t1", external_id="eb", created_at=now_utc())
    acct_a1 = AccountRecord(account_id=new_id("acct"), tenant_id="t1", user_id=user_a.user_id, label="a1", created_at=now_utc())
    acct_a2 = AccountRecord(account_id=new_id("acct"), tenant_id="t1", user_id=user_a.user_id, label="a2", created_at=now_utc())
    acct_b1 = AccountRecord(account_id=new_id("acct"), tenant_id="t1", user_id=user_b.user_id, label="b1", created_at=now_utc())

    for obj in [user_a, user_b]:
        store.put_user(obj)
    for obj in [acct_a1, acct_a2, acct_b1]:
        store.put_account(obj)

    a_accounts = store.list_accounts_for_user("t1", user_a.user_id)
    assert len(a_accounts) == 2
    assert all(a.user_id == user_a.user_id for a in a_accounts)

    b_accounts = store.list_accounts_for_user("t1", user_b.user_id)
    assert len(b_accounts) == 1


def test_persistent_store_list_wallets_for_account(tmp_path) -> None:
    storage = tmp_path / "multi_user.json"
    store = PersistentMultiUserStore(storage_path=storage)

    user = UserRecord(user_id=new_id("usr"), tenant_id="t1", external_id="eu", created_at=now_utc())
    acct = AccountRecord(account_id=new_id("acct"), tenant_id="t1", user_id=user.user_id, label="main", created_at=now_utc())
    w1 = WalletRecord(wallet_id=new_id("wlt"), tenant_id="t1", user_id=user.user_id, account_id=acct.account_id, address="0xw1", created_at=now_utc())
    w2 = WalletRecord(wallet_id=new_id("wlt"), tenant_id="t1", user_id=user.user_id, account_id=acct.account_id, address="0xw2", created_at=now_utc())

    store.put_user(user)
    store.put_account(acct)
    store.put_wallet(w1)
    store.put_wallet(w2)

    wallets = store.list_wallets_for_account("t1", acct.account_id)
    assert len(wallets) == 2


# ---------------------------------------------------------------------------
# Integration tests — via HTTP + simulated restart (create_app)
# ---------------------------------------------------------------------------


def _make_app(monkeypatch, tmp_path, label: str):
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", str(tmp_path / "sessions.json"))
    monkeypatch.setenv("CRUSADER_MULTI_USER_STORAGE_PATH", str(tmp_path / "multi_user.json"))
    monkeypatch.setenv("CRUSADER_WALLET_LINK_STORAGE_PATH", str(tmp_path / "wallet_links.json"))
    return create_app()


def test_persisted_user_readback(monkeypatch, tmp_path) -> None:
    app = _make_app(monkeypatch, tmp_path, "user-readback")
    with TestClient(app) as client:
        resp = client.post(
            "/foundation/users",
            json={"tenant_id": "t-alpha", "external_id": "tg_9001", "display_name": "alice"},
        )
        assert resp.status_code == 200
        user_id = resp.json()["user"]["user_id"]

    app2 = _make_app(monkeypatch, tmp_path, "user-readback-restart")
    with TestClient(app2) as client2:
        resp2 = client2.post(
            "/foundation/users",
            json={"tenant_id": "t-alpha", "external_id": "tg_9002", "display_name": "bob"},
        )
        assert resp2.status_code == 200
        resp_session = client2.post(
            "/foundation/sessions",
            json={"tenant_id": "t-alpha", "user_id": user_id},
        )
        assert resp_session.status_code == 200, f"user {user_id} should still exist after restart"


def test_persisted_account_readback(monkeypatch, tmp_path) -> None:
    app = _make_app(monkeypatch, tmp_path, "account-readback")
    account_id: str = ""
    with TestClient(app) as client:
        user_resp = client.post(
            "/foundation/users",
            json={"tenant_id": "t-beta", "external_id": "tg_9003"},
        )
        user_payload = user_resp.json()["user"]

        acct_resp = client.post(
            "/foundation/accounts",
            json={"tenant_id": "t-beta", "user_id": user_payload["user_id"], "label": "main"},
        )
        assert acct_resp.status_code == 200
        account_id = acct_resp.json()["account"]["account_id"]

    app2 = _make_app(monkeypatch, tmp_path, "account-readback-restart")
    with TestClient(app2) as client2:
        user_resp2 = client2.post(
            "/foundation/users",
            json={"tenant_id": "t-beta", "external_id": "tg_9099"},
        )
        user_payload2 = user_resp2.json()["user"]
        wallet_resp = client2.post(
            "/foundation/wallets",
            json={
                "tenant_id": "t-beta",
                "user_id": user_payload2["user_id"],
                "account_id": account_id,
                "address": "0xprobe",
            },
        )
        assert wallet_resp.status_code == 400, (
            f"account {account_id} is owned by different user — wallet create should 400, got {wallet_resp.status_code}"
        )


def test_persisted_wallet_readback(monkeypatch, tmp_path) -> None:
    app = _make_app(monkeypatch, tmp_path, "wallet-readback")
    wallet_id: str = ""
    session_id: str = ""
    tenant_id: str = "t-gamma"
    user_id: str = ""
    with TestClient(app) as client:
        user_resp = client.post(
            "/foundation/users",
            json={"tenant_id": tenant_id, "external_id": "tg_9004"},
        )
        user_payload = user_resp.json()["user"]
        user_id = user_payload["user_id"]

        sess_resp = client.post(
            "/foundation/sessions",
            json={"tenant_id": tenant_id, "user_id": user_id},
        )
        session_id = sess_resp.json()["session"]["session_id"]

        acct_resp = client.post(
            "/foundation/accounts",
            json={"tenant_id": tenant_id, "user_id": user_id, "label": "main"},
        )
        account_payload = acct_resp.json()["account"]

        wallet_resp = client.post(
            "/foundation/wallets",
            json={
                "tenant_id": tenant_id,
                "user_id": user_id,
                "account_id": account_payload["account_id"],
                "address": "0xpersist",
            },
        )
        assert wallet_resp.status_code == 200
        wallet_id = wallet_resp.json()["wallet"]["wallet_id"]

    app2 = _make_app(monkeypatch, tmp_path, "wallet-readback-restart")
    with TestClient(app2) as client2:
        get_resp = client2.get(
            f"/foundation/wallets/{wallet_id}",
            headers={
                "X-Session-Id": session_id,
                "X-Auth-Tenant-Id": tenant_id,
                "X-Auth-User-Id": user_id,
            },
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["wallet"]["address"] == "0xpersist"


def test_restart_safe_ownership_chain_intact(monkeypatch, tmp_path) -> None:
    app = _make_app(monkeypatch, tmp_path, "chain-pre-restart")
    wallet_id: str = ""
    session_id: str = ""
    tenant_id: str = "t-delta"
    user_id: str = ""

    with TestClient(app) as client:
        user_resp = client.post(
            "/foundation/users",
            json={"tenant_id": tenant_id, "external_id": "tg_9005"},
        )
        user_id = user_resp.json()["user"]["user_id"]

        sess_resp = client.post(
            "/foundation/sessions",
            json={"tenant_id": tenant_id, "user_id": user_id},
        )
        session_id = sess_resp.json()["session"]["session_id"]

        acct_resp = client.post(
            "/foundation/accounts",
            json={"tenant_id": tenant_id, "user_id": user_id, "label": "savings"},
        )
        account_id = acct_resp.json()["account"]["account_id"]

        wallet_resp = client.post(
            "/foundation/wallets",
            json={
                "tenant_id": tenant_id,
                "user_id": user_id,
                "account_id": account_id,
                "address": "0xchain",
            },
        )
        wallet_id = wallet_resp.json()["wallet"]["wallet_id"]

    app2 = _make_app(monkeypatch, tmp_path, "chain-post-restart")
    with TestClient(app2) as client2:
        get_resp = client2.get(
            f"/foundation/wallets/{wallet_id}",
            headers={
                "X-Session-Id": session_id,
                "X-Auth-Tenant-Id": tenant_id,
                "X-Auth-User-Id": user_id,
            },
        )
        assert get_resp.status_code == 200
        wallet_data = get_resp.json()["wallet"]
        assert wallet_data["user_id"] == user_id
        assert wallet_data["tenant_id"] == tenant_id
        assert wallet_data["address"] == "0xchain"


def test_cross_user_isolation_after_restart(monkeypatch, tmp_path) -> None:
    app = _make_app(monkeypatch, tmp_path, "isolation-pre-restart")
    wallet_a_id: str = ""
    session_b_id: str = ""
    tenant_id: str = "t-epsilon"
    user_a_id: str = ""
    user_b_id: str = ""

    with TestClient(app) as client:
        ua_resp = client.post(
            "/foundation/users",
            json={"tenant_id": tenant_id, "external_id": "tg_9006a"},
        )
        user_a_id = ua_resp.json()["user"]["user_id"]

        ub_resp = client.post(
            "/foundation/users",
            json={"tenant_id": tenant_id, "external_id": "tg_9006b"},
        )
        user_b_id = ub_resp.json()["user"]["user_id"]

        sess_b = client.post(
            "/foundation/sessions",
            json={"tenant_id": tenant_id, "user_id": user_b_id},
        )
        session_b_id = sess_b.json()["session"]["session_id"]

        acct_a = client.post(
            "/foundation/accounts",
            json={"tenant_id": tenant_id, "user_id": user_a_id, "label": "a-acct"},
        )
        account_a_id = acct_a.json()["account"]["account_id"]

        wallet_a = client.post(
            "/foundation/wallets",
            json={
                "tenant_id": tenant_id,
                "user_id": user_a_id,
                "account_id": account_a_id,
                "address": "0xuserA",
            },
        )
        wallet_a_id = wallet_a.json()["wallet"]["wallet_id"]

    app2 = _make_app(monkeypatch, tmp_path, "isolation-post-restart")
    with TestClient(app2) as client2:
        denied = client2.get(
            f"/foundation/wallets/{wallet_a_id}",
            headers={
                "X-Session-Id": session_b_id,
                "X-Auth-Tenant-Id": tenant_id,
                "X-Auth-User-Id": user_b_id,
            },
        )
        assert denied.status_code == 403, "user B must not read user A wallet after restart"


def test_cross_user_isolation_regression(monkeypatch, tmp_path) -> None:
    app = _make_app(monkeypatch, tmp_path, "isolation-regression")
    tenant_id: str = "t-zeta"

    with TestClient(app) as client:
        ua = client.post("/foundation/users", json={"tenant_id": tenant_id, "external_id": "iso_a"})
        ub = client.post("/foundation/users", json={"tenant_id": tenant_id, "external_id": "iso_b"})
        user_a_id = ua.json()["user"]["user_id"]
        user_b_id = ub.json()["user"]["user_id"]

        sess_b = client.post("/foundation/sessions", json={"tenant_id": tenant_id, "user_id": user_b_id})
        session_b_id = sess_b.json()["session"]["session_id"]

        acct_a = client.post("/foundation/accounts", json={"tenant_id": tenant_id, "user_id": user_a_id, "label": "main"})
        account_a_id = acct_a.json()["account"]["account_id"]

        wallet_a = client.post(
            "/foundation/wallets",
            json={"tenant_id": tenant_id, "user_id": user_a_id, "account_id": account_a_id, "address": "0xreg"},
        )
        wallet_a_id = wallet_a.json()["wallet"]["wallet_id"]

        denied = client.get(
            f"/foundation/wallets/{wallet_a_id}",
            headers={
                "X-Session-Id": session_b_id,
                "X-Auth-Tenant-Id": tenant_id,
                "X-Auth-User-Id": user_b_id,
            },
        )
        assert denied.status_code == 403
