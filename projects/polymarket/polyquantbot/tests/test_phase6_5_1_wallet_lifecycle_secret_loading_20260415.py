from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_SECRET_LOAD_BLOCK_OWNERSHIP_MISMATCH,
    WALLET_SECRET_LOAD_BLOCK_SECRET_MISSING,
    WALLET_SECRET_LOAD_BLOCK_WALLET_NOT_ACTIVE,
    WalletSecretLoadPolicy,
    WalletSecretLoader,
)


def _base_policy() -> WalletSecretLoadPolicy:
    return WalletSecretLoadPolicy(
        wallet_binding_id="wb-phase6-5-1",
        owner_user_id="user-1",
        requested_by_user_id="user-1",
        wallet_active=True,
        secret_env_var="PHASE6_WALLET_SECRET",
    )


def test_phase6_5_1_secret_loading_success(monkeypatch) -> None:
    monkeypatch.setenv("PHASE6_WALLET_SECRET", "secret-value-123")
    loader = WalletSecretLoader()

    result = loader.load_secret(_base_policy())

    assert result.success is True
    assert result.blocked_reason is None
    assert result.secret_loaded is True
    assert result.secret_fingerprint == "282768175c21798f"
    assert hasattr(result, "secret_value") is False


def test_phase6_5_1_blocks_ownership_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("PHASE6_WALLET_SECRET", "secret-value-123")
    loader = WalletSecretLoader()
    policy = WalletSecretLoadPolicy(
        wallet_binding_id="wb-phase6-5-1",
        owner_user_id="user-owner",
        requested_by_user_id="user-requester",
        wallet_active=True,
        secret_env_var="PHASE6_WALLET_SECRET",
    )

    result = loader.load_secret(policy)

    assert result.success is False
    assert result.blocked_reason == WALLET_SECRET_LOAD_BLOCK_OWNERSHIP_MISMATCH
    assert result.secret_loaded is False
    assert hasattr(result, "secret_value") is False


def test_phase6_5_1_blocks_inactive_wallet(monkeypatch) -> None:
    monkeypatch.setenv("PHASE6_WALLET_SECRET", "secret-value-123")
    loader = WalletSecretLoader()
    policy = WalletSecretLoadPolicy(
        wallet_binding_id="wb-phase6-5-1",
        owner_user_id="user-1",
        requested_by_user_id="user-1",
        wallet_active=False,
        secret_env_var="PHASE6_WALLET_SECRET",
    )

    result = loader.load_secret(policy)

    assert result.success is False
    assert result.blocked_reason == WALLET_SECRET_LOAD_BLOCK_WALLET_NOT_ACTIVE
    assert result.secret_loaded is False


def test_phase6_5_1_blocks_when_secret_missing(monkeypatch) -> None:
    monkeypatch.delenv("PHASE6_WALLET_SECRET", raising=False)
    loader = WalletSecretLoader()

    result = loader.load_secret(_base_policy())

    assert result.success is False
    assert result.blocked_reason == WALLET_SECRET_LOAD_BLOCK_SECRET_MISSING
    assert result.secret_loaded is False
    assert result.secret_fingerprint is None
