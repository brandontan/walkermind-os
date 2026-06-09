"""SafeCustody + custody-mode dispatcher (custody migration chunks 3+4).

Test boundary is deliberately high-level: the SDK encoding/relayer wire path
is exercised by ``_execute_usdc_transfer`` and is patched out in these tests.
What we pin here is the policy surface — guards, balance pre-flight, dispatch,
loud-failure for misconfiguration — because that is what protects user funds.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from projects.polymarket.crusaderbot.wallet import custody as _c
from projects.polymarket.crusaderbot.integrations import (
    builder_relayer as _br,
    polygon_usdc as _pusd,
)


class _EOASettings:
    EXECUTION_PATH_VALIDATED = True
    SWEEP_ONCHAIN_ENABLED = True
    CUSTODY_MODE = "eoa"
    USDC_DECIMALS = 6
    SWEEP_MIN_USDC = 1.0


class _SafeSettings:
    EXECUTION_PATH_VALIDATED = True
    SWEEP_ONCHAIN_ENABLED = True
    CUSTODY_MODE = "safe"
    USDC_DECIMALS = 6
    SWEEP_MIN_USDC = 1.0


class _PaperSettings:
    EXECUTION_PATH_VALIDATED = False
    SWEEP_ONCHAIN_ENABLED = False
    CUSTODY_MODE = "safe"
    USDC_DECIMALS = 6
    SWEEP_MIN_USDC = 1.0


def _master_wallet_stub():
    return ("0xMasterEOA", "0x" + "1" * 64)


# ── dispatcher routing ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispatcher_routes_to_eoa_by_default() -> None:
    """CUSTODY_MODE='eoa' must route to polygon_usdc.transfer_usdc, untouched."""
    with patch.object(_c, "get_settings", return_value=_EOASettings()), \
         patch.object(_pusd, "transfer_usdc",
                      AsyncMock(return_value={"tx_hash": "0xeoa"})) as eoa, \
         patch.object(_c.SafeCustody, "transfer_usdc",
                      AsyncMock()) as safe:
        out = await _c.transfer_usdc("0xdest", Decimal("10"))
    assert out["tx_hash"] == "0xeoa"
    eoa.assert_awaited_once()
    safe.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatcher_routes_to_safe_when_configured() -> None:
    """CUSTODY_MODE='safe' + relayer configured must route to SafeCustody."""
    with patch.object(_c, "get_settings", return_value=_SafeSettings()), \
         patch.object(_c, "is_relayer_configured", return_value=True), \
         patch.object(_pusd, "transfer_usdc", AsyncMock()) as eoa, \
         patch.object(_c.SafeCustody, "transfer_usdc",
                      AsyncMock(return_value={"tx_hash": "0xsafe"})) as safe:
        out = await _c.transfer_usdc("0xdest", Decimal("10"))
    assert out["tx_hash"] == "0xsafe"
    safe.assert_awaited_once()
    eoa.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatcher_raises_when_safe_mode_unwired() -> None:
    """CUSTODY_MODE='safe' without relayer creds must raise — no silent fallback."""
    with patch.object(_c, "get_settings", return_value=_SafeSettings()), \
         patch.object(_c, "is_relayer_configured", return_value=False), \
         patch.object(_pusd, "transfer_usdc", AsyncMock()) as eoa:
        with pytest.raises(_br.BuilderRelayerUnavailable,
                           match="CUSTODY_MODE='safe'"):
            await _c.transfer_usdc("0xdest", Decimal("10"))
    eoa.assert_not_awaited()  # critical: no silent EOA fallback


@pytest.mark.asyncio
async def test_sweep_dispatcher_routes_to_eoa_by_default() -> None:
    with patch.object(_c, "get_settings", return_value=_EOASettings()), \
         patch.object(_pusd, "sweep_usdc_to_master",
                      AsyncMock(return_value={"tx_hash": "0xeoa"})) as eoa, \
         patch.object(_c.SafeCustody, "sweep_usdc_to_master",
                      AsyncMock()) as safe:
        out = await _c.sweep_usdc_to_master("0xfrom", "0xpk")
    assert out["tx_hash"] == "0xeoa"
    eoa.assert_awaited_once()
    safe.assert_not_awaited()


# ── SafeCustody.transfer_usdc — guards + balance ────────────────────────────

@pytest.mark.asyncio
async def test_safe_transfer_blocked_when_execution_path_off() -> None:
    with patch.object(_c, "get_settings", return_value=_PaperSettings()):
        with pytest.raises(_c.PreflightError, match="EXECUTION_PATH_VALIDATED"):
            await _c.SafeCustody.transfer_usdc("0xdest", Decimal("10"))


@pytest.mark.asyncio
async def test_safe_transfer_rejects_non_positive_amount() -> None:
    with patch.object(_c, "get_settings", return_value=_SafeSettings()):
        with pytest.raises(_c.PreflightError, match="non-positive amount"):
            await _c.SafeCustody.transfer_usdc("0xdest", Decimal("0"))


@pytest.mark.asyncio
async def test_safe_transfer_requires_relayer_configured() -> None:
    with patch.object(_c, "get_settings", return_value=_SafeSettings()), \
         patch.object(_c, "is_relayer_configured", return_value=False):
        with pytest.raises(_br.BuilderRelayerUnavailable, match="not configured"):
            await _c.SafeCustody.transfer_usdc("0xdest", Decimal("10"))


@pytest.mark.asyncio
async def test_safe_transfer_blocks_on_insufficient_pool_balance() -> None:
    """Insufficient master-Safe USDC must raise PreflightError pre-broadcast."""

    class _Client:
        def get_expected_safe(self):
            return "0xMasterSafe"

    with patch.object(_c, "get_settings", return_value=_SafeSettings()), \
         patch.object(_c, "is_relayer_configured", return_value=True), \
         patch("projects.polymarket.crusaderbot.wallet.vault.master_wallet",
               return_value=_master_wallet_stub()), \
         patch.object(_c, "make_relayer_client", return_value=_Client()), \
         patch.object(_c, "get_usdc_balance", AsyncMock(return_value=5.0)):
        with pytest.raises(_c.PreflightError, match="< requested"):
            await _c.SafeCustody.transfer_usdc("0xdest", Decimal("10"))


@pytest.mark.asyncio
async def test_safe_transfer_happy_path_returns_tx_hash() -> None:
    """All guards green → _execute_usdc_transfer is invoked and its result returned."""

    class _Client:
        def get_expected_safe(self):
            return "0xMasterSafe"

    with patch.object(_c, "get_settings", return_value=_SafeSettings()), \
         patch.object(_c, "is_relayer_configured", return_value=True), \
         patch("projects.polymarket.crusaderbot.wallet.vault.master_wallet",
               return_value=_master_wallet_stub()), \
         patch.object(_c, "make_relayer_client", return_value=_Client()), \
         patch.object(_c, "get_usdc_balance", AsyncMock(return_value=1000.0)), \
         patch.object(_c, "_execute_usdc_transfer",
                      AsyncMock(return_value={
                          "tx_hash": "0xabc", "tx_id": "tid",
                          "amount_usdc": "10", "status": 1,
                      })) as exec_mock:
        out = await _c.SafeCustody.transfer_usdc(
            "0xAbCd1234567890EF1234567890abcdef12345678", Decimal("10"),
        )
    assert out["tx_hash"] == "0xabc"
    exec_mock.assert_awaited_once()


# ── SafeCustody.sweep_usdc_to_master — guards + dust + path ─────────────────

@pytest.mark.asyncio
async def test_safe_sweep_blocked_when_either_flag_off() -> None:
    class _OnlyExec:
        EXECUTION_PATH_VALIDATED = True
        SWEEP_ONCHAIN_ENABLED = False
        CUSTODY_MODE = "safe"
        USDC_DECIMALS = 6
        SWEEP_MIN_USDC = 1.0

    with patch.object(_c, "get_settings", return_value=_OnlyExec()):
        with pytest.raises(_c.PreflightError, match="SWEEP_ONCHAIN_ENABLED"):
            await _c.SafeCustody.sweep_usdc_to_master("0xfrom", "0xpk")


@pytest.mark.asyncio
async def test_safe_sweep_skips_dust_without_execute() -> None:
    """Below SWEEP_MIN_USDC → return skipped dict, never invoke execute."""

    class _Client:
        def get_expected_safe(self):
            return "0xUserSafe"

    with patch.object(_c, "get_settings", return_value=_SafeSettings()), \
         patch.object(_c, "is_relayer_configured", return_value=True), \
         patch("projects.polymarket.crusaderbot.wallet.vault.master_wallet",
               return_value=_master_wallet_stub()), \
         patch.object(_c, "make_relayer_client", return_value=_Client()), \
         patch.object(_c, "_read_usdc_raw_balance", AsyncMock(return_value=500_000)), \
         patch.object(_c, "_execute_usdc_transfer", AsyncMock()) as exec_mock:
        out = await _c.SafeCustody.sweep_usdc_to_master("0xfrom", "0x" + "1" * 64)
    # 500_000 / 1e6 = 0.5 USDC, below SWEEP_MIN_USDC=1.0
    assert out["skipped"] is True
    exec_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_safe_sweep_happy_path_calls_execute() -> None:
    class _Client:
        def get_expected_safe(self):
            return "0xUserSafe"

    with patch.object(_c, "get_settings", return_value=_SafeSettings()), \
         patch.object(_c, "is_relayer_configured", return_value=True), \
         patch("projects.polymarket.crusaderbot.wallet.vault.master_wallet",
               return_value=_master_wallet_stub()), \
         patch.object(_c, "make_relayer_client", return_value=_Client()), \
         patch.object(_c, "_read_usdc_raw_balance",
                      AsyncMock(return_value=10_000_000)), \
         patch.object(_c, "_execute_usdc_transfer",
                      AsyncMock(return_value={
                          "tx_hash": "0xsweep", "tx_id": "tid",
                          "amount_usdc": "10", "status": 1,
                      })) as exec_mock:
        out = await _c.SafeCustody.sweep_usdc_to_master(
            "0xfrom", "0x" + "1" * 64,
        )
    # 10_000_000 / 1e6 = 10 USDC — well above min
    assert out["tx_hash"] == "0xsweep"
    assert out["amount_usdc"] == "10"
    exec_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_safe_sweep_rejects_empty_signer() -> None:
    with patch.object(_c, "get_settings", return_value=_SafeSettings()):
        with pytest.raises(_c.PreflightError, match="empty signer key"):
            await _c.SafeCustody.sweep_usdc_to_master("0xfrom", "")
