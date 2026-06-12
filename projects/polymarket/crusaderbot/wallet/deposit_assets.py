"""Supported deposit asset truth for WebTrader + custody watcher.

This module deliberately combines product-facing token/network options with the
backend's *actual* detection/accounting capabilities. UI code may show disabled
options as a roadmap teaser, but only ``enabled`` options may produce a deposit
instruction or be credited by the watcher.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Iterable

from ..config import get_settings


@dataclass(frozen=True)
class DepositAsset:
    """One token/network deposit option and backend support verdict."""

    id: str
    token_symbol: str
    token_label: str
    token_contract: str | None
    network: str
    chain_id: int
    display_label: str
    decimals: int
    min_deposit: Decimal | None
    backend_supported: bool
    watcher_supported: bool
    bridge_custody_supported: bool
    enabled: bool
    unavailable_reason: str | None = None

    def to_api(self, deposit_address: str) -> dict[str, Any]:
        data = asdict(self)
        data["min_deposit"] = float(self.min_deposit) if self.min_deposit is not None else None
        data["deposit_address"] = deposit_address if self.enabled else None
        return data


_PRIMARY_DEPOSIT_ASSET_ID = "polygon-usdc-e"


def supported_deposit_assets() -> tuple[DepositAsset, ...]:
    """Return the static allowlist plus disabled unsupported options.

    Current backend truth is intentionally conservative:
    * Polygon USDC.e is enabled because the watcher scans the configured
      ``USDC_POLYGON`` ERC-20, credits the ledger in USDC units, and the sweep
      path transfers the same configured token.
    * Native Polygon USDC is detected only by the wrong-token alert lane and is
      never credited.
    * USDT and non-Polygon networks are not watched/swept/reconciled here, so
      they remain disabled.
    """
    settings = get_settings()
    min_deposit = Decimal(str(getattr(settings, "MIN_DEPOSIT_USDC", 50)))
    usdc_decimals = int(getattr(settings, "USDC_DECIMALS", 6))
    return (
        DepositAsset(
            id=_PRIMARY_DEPOSIT_ASSET_ID,
            token_symbol="USDC.e",
            token_label="USDC.e (bridged)",
            token_contract=settings.USDC_POLYGON,
            network="Polygon",
            chain_id=137,
            display_label="USDC.e on Polygon",
            decimals=usdc_decimals,
            min_deposit=min_deposit,
            backend_supported=True,
            watcher_supported=True,
            bridge_custody_supported=True,
            enabled=True,
        ),
        DepositAsset(
            id="polygon-usdc-native",
            token_symbol="USDC",
            token_label="USDC (native)",
            token_contract=getattr(settings, "USDC_NATIVE_POLYGON", None),
            network="Polygon",
            chain_id=137,
            display_label="USDC on Polygon",
            decimals=usdc_decimals,
            min_deposit=None,
            backend_supported=True,
            watcher_supported=False,
            bridge_custody_supported=False,
            enabled=False,
            unavailable_reason="Detected for support alerts only; not credited or swept.",
        ),
        DepositAsset(
            id="polygon-usdt",
            token_symbol="USDT",
            token_label="USDT",
            token_contract=None,
            network="Polygon",
            chain_id=137,
            display_label="USDT on Polygon",
            decimals=6,
            min_deposit=None,
            backend_supported=False,
            watcher_supported=False,
            bridge_custody_supported=False,
            enabled=False,
            unavailable_reason="No watcher, ledger normalization, or custody sweep support yet.",
        ),
        DepositAsset(
            id="base-usdc",
            token_symbol="USDC",
            token_label="USDC",
            token_contract=None,
            network="Base",
            chain_id=8453,
            display_label="USDC on Base",
            decimals=6,
            min_deposit=None,
            backend_supported=False,
            watcher_supported=False,
            bridge_custody_supported=False,
            enabled=False,
            unavailable_reason="Base deposits are not watched or reconciled by CrusaderBot yet.",
        ),
        DepositAsset(
            id="arbitrum-usdc",
            token_symbol="USDC",
            token_label="USDC",
            token_contract=None,
            network="Arbitrum",
            chain_id=42161,
            display_label="USDC on Arbitrum",
            decimals=6,
            min_deposit=None,
            backend_supported=False,
            watcher_supported=False,
            bridge_custody_supported=False,
            enabled=False,
            unavailable_reason="Arbitrum deposits are not watched or reconciled by CrusaderBot yet.",
        ),
    )


def enabled_deposit_assets() -> tuple[DepositAsset, ...]:
    """Selectable assets: all capability flags must be true."""
    return tuple(
        asset for asset in supported_deposit_assets()
        if asset.enabled
        and asset.backend_supported
        and asset.watcher_supported
        and asset.bridge_custody_supported
    )


def primary_deposit_asset() -> DepositAsset:
    """The canonical asset currently credited by the deposit watcher."""
    for asset in enabled_deposit_assets():
        if asset.id == _PRIMARY_DEPOSIT_ASSET_ID:
            return asset
    raise RuntimeError("primary deposit asset is not enabled")


def get_deposit_asset(asset_id: str) -> DepositAsset | None:
    for asset in supported_deposit_assets():
        if asset.id == asset_id:
            return asset
    return None


def require_enabled_deposit_asset(asset_id: str) -> DepositAsset:
    asset = get_deposit_asset(asset_id)
    if asset is None:
        raise ValueError(f"Unknown deposit asset: {asset_id}")
    if asset not in enabled_deposit_assets():
        raise ValueError(f"Deposit asset is not enabled: {asset.display_label}")
    return asset


def asset_api_options(deposit_address: str) -> list[dict[str, Any]]:
    return [asset.to_api(deposit_address) for asset in supported_deposit_assets()]


def enabled_asset_ids(assets: Iterable[DepositAsset] | None = None) -> set[str]:
    source = tuple(assets) if assets is not None else enabled_deposit_assets()
    return {asset.id for asset in source if asset.enabled}
