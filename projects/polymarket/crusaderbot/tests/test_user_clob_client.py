"""Per-user CLOB client foundation (WARP/root-per-user-clob-client — Step 1).

Covers:

* ``resolve_deposit_wallet_creds`` — extracted single-key path returns the SDK
  wallet + creds (no funder hardcode, key never leaks into the result).
* Cross-user isolation invariant — ``user_id=None`` / non-UUID hard-fails with
  ``PerUserClobIsolationError`` and never builds a client.
* ``USE_REAL_CLOB=False`` — refuses, points the caller at ``get_clob_client``.
* Per-user cache — same user → one resolution, two clients for two users are
  distinct, each with their own resolved wallet.
* Single-flight — concurrent calls for the same user share ONE
  ``AsyncSecureClient.create`` + ONE vault decryption.
* Bounded LRU — capacity boundary evicts the least-recently-used entry and
  closes its client.

All SDK + vault calls are mocked; no key material, no network, no DB.
"""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot.integrations import clob as clob_pkg
from projects.polymarket.crusaderbot.integrations.clob import user_client as uc


# --- shared fakes ---------------------------------------------------------


class _FakeCreds:
    def __init__(self, key: str) -> None:
        self.key = key
        self.secret = f"secret_{key}"
        self.passphrase = f"pass_{key}"


class _FakeSecureClient:
    """Stand-in for ``polymarket.AsyncSecureClient``.

    Records every ``create`` call and returns a deterministic per-key wallet so
    we can prove two users get two distinct wallets and single-flight collapses
    repeat calls.
    """

    create_calls: list[str] = []
    create_delay: float = 0.0

    def __init__(self, key: str) -> None:
        # Derive the wallet from the key so distinct users -> distinct wallets.
        suffix = (key.replace("0x", "") + "0" * 40)[:40]
        self.wallet = "0x" + suffix
        self.credentials = _FakeCreds(key[:10])

    async def close(self) -> None:
        return None

    @classmethod
    async def create(cls, *, private_key: str, wallet=None, **_kw):
        cls.create_calls.append(private_key)
        if cls.create_delay:
            await asyncio.sleep(cls.create_delay)
        return cls(private_key)


class _FakeClobV2Client:
    """Stand-in for ``ClobV2Client`` so tests never touch the v2 SDK."""

    instances: list["_FakeClobV2Client"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.funder = kwargs.get("funder_address")
        self.signature_type = kwargs.get("signature_type")
        self.closed = False
        _FakeClobV2Client.instances.append(self)

    async def aclose(self) -> None:
        self.closed = True


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")


def _make_settings(monkeypatch, *, real: bool = True):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("USE_REAL_CLOB", "true" if real else "false")
    monkeypatch.setenv("USE_CLOB_V2", "true")
    monkeypatch.setenv("POLYMARKET_SIGNATURE_TYPE", "3")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "0x" + "11" * 32)
    monkeypatch.delenv("POLYMARKET_FUNDER_ADDRESS", raising=False)
    crusaderbot_config.get_settings.cache_clear()
    return crusaderbot_config.Settings()  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch):
    crusaderbot_config.get_settings.cache_clear()
    _FakeSecureClient.create_calls = []
    _FakeSecureClient.create_delay = 0.0
    _FakeClobV2Client.instances = []

    import polymarket
    monkeypatch.setattr(polymarket, "AsyncSecureClient", _FakeSecureClient)
    # The user_client module imports ClobV2Client at module load time;
    # substitute the symbol it actually uses.
    monkeypatch.setattr(uc, "ClobV2Client", _FakeClobV2Client)

    yield
    # Reset cache between tests so capacity / single-flight state never leaks.
    # Sync drop is sufficient — the fake client's aclose is a no-op and there
    # is no awaitable cleanup work to do. Also clear the strong-ref set so
    # eviction-task references don't bleed between tests.
    uc._user_cache.clear()
    uc._inflight.clear()
    uc._background_tasks.clear()
    crusaderbot_config.get_settings.cache_clear()


def _patch_vault(monkeypatch, mapping: dict[UUID, str]):
    """Patch ``wallet.vault.get_decrypted_pk`` to a dict lookup."""
    from projects.polymarket.crusaderbot.wallet import vault as vault_mod

    async def _fake_get(user_id):
        return mapping.get(user_id)

    monkeypatch.setattr(vault_mod, "get_decrypted_pk", _fake_get)


# --- exported surface ----------------------------------------------------


def test_package_reexports_per_user_surface():
    """The package ``__init__`` re-exports the per-user surface so callers
    don't need to know which submodule defines it."""
    assert clob_pkg.get_user_clob_client is uc.get_user_clob_client
    assert clob_pkg.resolve_deposit_wallet_creds is uc.resolve_deposit_wallet_creds
    assert clob_pkg.PerUserClobError is uc.PerUserClobError
    assert clob_pkg.PerUserClobIsolationError is uc.PerUserClobIsolationError


# --- resolve_deposit_wallet_creds ----------------------------------------


@pytest.mark.asyncio
async def test_resolve_returns_wallet_and_creds():
    wallet, creds = await uc.resolve_deposit_wallet_creds("0x" + "ab" * 32)
    assert wallet.startswith("0x") and len(wallet) == 42
    assert set(creds.keys()) == {"api_key", "api_secret", "passphrase"}
    assert creds["api_key"].startswith("0xabababab")
    # SDK saw the key but it is NOT in the returned creds.
    assert _FakeSecureClient.create_calls == ["0x" + "ab" * 32]
    assert "0x" + "ab" * 32 not in creds.values()


@pytest.mark.asyncio
async def test_resolve_rejects_empty_private_key():
    with pytest.raises(uc.PerUserClobError, match="empty"):
        await uc.resolve_deposit_wallet_creds("")


# --- cross-user isolation -------------------------------------------------


@pytest.mark.asyncio
async def test_isolation_violation_on_none_user_id(monkeypatch, caplog):
    s = _make_settings(monkeypatch)
    caplog.set_level("WARNING")
    with pytest.raises(uc.PerUserClobIsolationError):
        await uc.get_user_clob_client(None, s)  # type: ignore[arg-type]
    assert any("ISOLATION VIOLATION" in rec.message for rec in caplog.records)
    # No SDK call, no client built.
    assert _FakeSecureClient.create_calls == []
    assert _FakeClobV2Client.instances == []


@pytest.mark.asyncio
async def test_isolation_violation_on_wrong_type(monkeypatch):
    s = _make_settings(monkeypatch)
    with pytest.raises(uc.PerUserClobIsolationError):
        await uc.get_user_clob_client("not-a-uuid", s)  # type: ignore[arg-type]
    assert _FakeSecureClient.create_calls == []


@pytest.mark.asyncio
async def test_paper_mode_refuses(monkeypatch):
    """USE_REAL_CLOB=False — caller must route through ``get_clob_client``
    (mock). The per-user path never silently fabricates a paper client."""
    s = _make_settings(monkeypatch, real=False)
    u = uuid4()
    _patch_vault(monkeypatch, {u: "0x" + "33" * 32})
    with pytest.raises(clob_pkg.ClobConfigError, match="paper mode"):
        await uc.get_user_clob_client(u, s)


@pytest.mark.asyncio
async def test_no_key_in_vault_hard_fails(monkeypatch):
    s = _make_settings(monkeypatch)
    _patch_vault(monkeypatch, {})
    u = uuid4()
    with pytest.raises(uc.PerUserClobError, match="encrypted_key"):
        await uc.get_user_clob_client(u, s)


# --- per-user cache + distinct wallets -----------------------------------


@pytest.mark.asyncio
async def test_two_users_get_distinct_wallets_and_clients(monkeypatch):
    s = _make_settings(monkeypatch)
    u1, u2 = uuid4(), uuid4()
    _patch_vault(monkeypatch, {
        u1: "0x" + "11" * 32,
        u2: "0x" + "22" * 32,
    })

    c1 = await uc.get_user_clob_client(u1, s)
    c2 = await uc.get_user_clob_client(u2, s)

    assert c1 is not c2
    # Each user's client is built with that user's resolved deposit wallet as
    # the funder/maker — proves wallets do NOT cross.
    assert c1.funder.startswith("0x1111")
    assert c2.funder.startswith("0x2222")
    assert c1.signature_type == 3
    assert c2.signature_type == 3
    # Each user has exactly one SDK call against THEIR key.
    assert sorted(_FakeSecureClient.create_calls) == sorted([
        "0x" + "11" * 32, "0x" + "22" * 32,
    ])


@pytest.mark.asyncio
async def test_same_user_repeat_calls_hit_cache(monkeypatch):
    s = _make_settings(monkeypatch)
    u = uuid4()
    _patch_vault(monkeypatch, {u: "0x" + "11" * 32})

    a = await uc.get_user_clob_client(u, s)
    b = await uc.get_user_clob_client(u, s)
    c = await uc.get_user_clob_client(u, s)

    assert a is b is c
    # ONE SDK call, ONE client built — not three.
    assert _FakeSecureClient.create_calls == ["0x" + "11" * 32]
    assert len(_FakeClobV2Client.instances) == 1


# --- single-flight --------------------------------------------------------


@pytest.mark.asyncio
async def test_single_flight_collapses_concurrent_same_user(monkeypatch):
    """N concurrent get_user_clob_client(U) → 1 vault decrypt + 1 SDK create."""
    s = _make_settings(monkeypatch)
    u = uuid4()

    # Count decryptions to prove the vault is hit at most once.
    decrypt_count = 0
    from projects.polymarket.crusaderbot.wallet import vault as vault_mod

    async def _slow_get(user_id):
        nonlocal decrypt_count
        decrypt_count += 1
        await asyncio.sleep(0.05)
        return "0x" + "11" * 32

    monkeypatch.setattr(vault_mod, "get_decrypted_pk", _slow_get)
    _FakeSecureClient.create_delay = 0.05

    results = await asyncio.gather(*[
        uc.get_user_clob_client(u, s) for _ in range(10)
    ])

    assert all(r is results[0] for r in results)
    assert decrypt_count == 1
    assert _FakeSecureClient.create_calls == ["0x" + "11" * 32]
    assert len(_FakeClobV2Client.instances) == 1


@pytest.mark.asyncio
async def test_task_cancellation_does_not_wedge_inflight(monkeypatch):
    """Hardening regression (Gemini #1732 MED).

    If the in-flight task ITSELF is cancelled, the ``finally`` in
    ``_build_and_cache`` must still clear ``_inflight[user_id]``. Without
    ``asyncio.shield`` around the cleanup, the cancellation would propagate
    through the unshielded ``async with _state_lock`` await and skip the
    pop — leaving a dead task in ``_inflight`` that wedges every future
    caller (each new caller awaits ``asyncio.shield(dead_task)`` which
    re-raises CancelledError immediately and never repopulates the slot).
    """
    s = _make_settings(monkeypatch)
    u = uuid4()

    from projects.polymarket.crusaderbot.wallet import vault as vault_mod

    async def _slow_get(user_id):
        await asyncio.sleep(0.10)
        return "0x" + "11" * 32

    monkeypatch.setattr(vault_mod, "get_decrypted_pk", _slow_get)

    # Start a caller and grab a handle to the in-flight TASK (not the caller).
    caller = asyncio.create_task(uc.get_user_clob_client(u, s))
    await asyncio.sleep(0.01)
    assert u in uc._inflight
    inflight_task = uc._inflight[u]

    # Cancel the build task itself.
    inflight_task.cancel()
    with pytest.raises(BaseException):
        await caller

    # The shielded cleanup MUST have run. With unshielded cleanup,
    # _inflight[u] would still hold the dead task here.
    assert u not in uc._inflight

    # A fresh call now succeeds — proves the wedge is gone.
    _patch_vault(monkeypatch, {u: "0x" + "11" * 32})
    client = await uc.get_user_clob_client(u, s)
    assert client.funder.startswith("0x1111")


@pytest.mark.asyncio
async def test_holder_cancellation_does_not_defeat_single_flight(monkeypatch):
    """Hardening regression (Gemini #1731 HIGH).

    If the first caller is cancelled mid-build, the in-flight slot must NOT
    be released while the underlying ``_build_and_cache`` task is still
    running in the background (the task is shielded). A second caller
    arriving during the still-running build must join the SAME task, not
    spawn a duplicate ``AsyncSecureClient.create``.
    """
    s = _make_settings(monkeypatch)
    u = uuid4()

    decrypt_count = 0
    from projects.polymarket.crusaderbot.wallet import vault as vault_mod

    async def _slow_get(user_id):
        nonlocal decrypt_count
        decrypt_count += 1
        await asyncio.sleep(0.10)
        return "0x" + "11" * 32

    monkeypatch.setattr(vault_mod, "get_decrypted_pk", _slow_get)

    # Start caller A, cancel it before the build completes.
    a = asyncio.create_task(uc.get_user_clob_client(u, s))
    await asyncio.sleep(0.02)
    a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await a

    # Caller B arrives mid-build — must join the still-running task, not
    # spawn a new one. The in-flight slot must still be occupied because the
    # task is shielded against caller A's cancellation.
    assert u in uc._inflight
    b = await uc.get_user_clob_client(u, s)
    assert b.funder.startswith("0x1111")

    # ONE vault decrypt + ONE SDK call total — single-flight survived the
    # cancellation.
    assert decrypt_count == 1
    assert _FakeSecureClient.create_calls == ["0x" + "11" * 32]
    assert len(_FakeClobV2Client.instances) == 1


@pytest.mark.asyncio
async def test_single_flight_failure_propagates_and_clears(monkeypatch):
    """If the build fails, every waiter gets the error AND the next call
    retries (the in-flight slot is dropped)."""
    s = _make_settings(monkeypatch)
    u = uuid4()
    _patch_vault(monkeypatch, {})  # no key → PerUserClobError

    with pytest.raises(uc.PerUserClobError):
        await asyncio.gather(uc.get_user_clob_client(u, s),
                             uc.get_user_clob_client(u, s))
    # Slot must NOT be left in-flight or cached.
    assert u not in uc._inflight
    assert u not in uc._user_cache

    # A retry now (with a key) succeeds.
    _patch_vault(monkeypatch, {u: "0x" + "11" * 32})
    client = await uc.get_user_clob_client(u, s)
    assert client.funder.startswith("0x1111")


# --- bounded LRU eviction -------------------------------------------------


@pytest.mark.asyncio
async def test_lru_eviction_at_capacity_closes_evicted_client(monkeypatch):
    s = _make_settings(monkeypatch)
    monkeypatch.setattr(uc, "USER_CACHE_CAPACITY", 2)

    users = [uuid4() for _ in range(3)]
    keys = {u: "0x" + format(i, "02x") * 32 for i, u in enumerate(users)}
    _patch_vault(monkeypatch, keys)

    c0 = await uc.get_user_clob_client(users[0], s)
    c1 = await uc.get_user_clob_client(users[1], s)
    c2 = await uc.get_user_clob_client(users[2], s)

    # users[0] was LRU when users[2] arrived → evicted.
    assert users[0] not in uc._user_cache
    assert users[1] in uc._user_cache
    assert users[2] in uc._user_cache
    # Eviction schedules aclose as a background task; let it run.
    await asyncio.sleep(0.01)
    assert c0.closed is True
    assert c1.closed is False
    assert c2.closed is False


@pytest.mark.asyncio
async def test_cache_hit_promotes_to_mru(monkeypatch):
    s = _make_settings(monkeypatch)
    monkeypatch.setattr(uc, "USER_CACHE_CAPACITY", 2)

    u_a, u_b, u_c = uuid4(), uuid4(), uuid4()
    _patch_vault(monkeypatch, {
        u_a: "0x" + "aa" * 32,
        u_b: "0x" + "bb" * 32,
        u_c: "0x" + "cc" * 32,
    })

    await uc.get_user_clob_client(u_a, s)
    await uc.get_user_clob_client(u_b, s)
    # Touch u_a so it becomes MRU; u_b is now LRU.
    await uc.get_user_clob_client(u_a, s)
    await uc.get_user_clob_client(u_c, s)

    assert u_b not in uc._user_cache  # the LRU got evicted
    assert u_a in uc._user_cache
    assert u_c in uc._user_cache


@pytest.mark.asyncio
async def test_clear_cache_closes_all(monkeypatch):
    s = _make_settings(monkeypatch)
    u1, u2 = uuid4(), uuid4()
    _patch_vault(monkeypatch, {
        u1: "0x" + "11" * 32, u2: "0x" + "22" * 32,
    })
    c1 = await uc.get_user_clob_client(u1, s)
    c2 = await uc.get_user_clob_client(u2, s)
    await uc.clear_user_clob_cache()
    assert uc._user_cache == {}
    assert uc._inflight == {}
    assert c1.closed is True and c2.closed is True
