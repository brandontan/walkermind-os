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
    """One token/network deposit option and its end-to-end backend capability
    verdict (#1800).

    Capability flags are explicit and auditable: a token is user-facing
    ``enabled`` ONLY when it is supported end-to-end — detectable by the
    watcher, creditable to the live ledger, AND sweepable/reconcilable by the
    custody path (or convertible to the collateral token first). A token that
    is merely detectable (e.g. native USDC via the wrong-token alert lane) is
    NEVER ``enabled`` — it cannot become tradeable live balance.
    """

    id: str
    token_symbol: str
    token_label: str
    token_contract: str | None
    network: str
    chain_id: int
    display_label: str
    decimals: int
    min_deposit: Decimal | None
    # Legacy coarse flags (retained for back-compat with #1795/#1798 callers).
    backend_supported: bool
    watcher_supported: bool
    bridge_custody_supported: bool
    enabled: bool
    unavailable_reason: str | None = None
    # Explicit end-to-end capability matrix (#1800). All must hold for an
    # asset to be safely user-facing ``enabled`` (convertible substitutes for
    # creditable/sweepable only once a real conversion-to-collateral path
    # exists — none does today, so the requested tokens stay disabled).
    detectable: bool = False       # the watcher can recognise a transfer of this token
    creditable: bool = False       # credits 1:1 to confirmed available LIVE balance safely
    sweepable: bool = False        # the custody sweep can move it to master
    reconcilable: bool = False     # admin/reconcile surfaces account for it correctly
    convertible: bool = False      # a safe conversion to the collateral token exists
    disabled_reason: str | None = None  # issue-vocabulary mirror of unavailable_reason

    @property
    def is_fully_enabled(self) -> bool:
        """The ONE source of truth for "safe to deposit end-to-end" (#1800).

        Used by both ``enabled_deposit_assets()`` and ``to_api()`` so the
        backend's selectable set and the address/QR the frontend renders can
        never disagree — a stray ``enabled=True`` without the backing
        capability matrix exposes no address.
        """
        return (
            self.enabled
            and self.backend_supported
            and self.watcher_supported
            and self.bridge_custody_supported
            and self.detectable
            and self.creditable
            and self.sweepable
            and self.reconcilable
        )

    def to_api(self, deposit_address: str) -> dict[str, Any]:
        fully = self.is_fully_enabled
        data = asdict(self)
        # Serialize the TRUE end-to-end verdict, not the bare flag — and only
        # attach the address/QR when the asset is fully supported.
        data["enabled"] = fully
        data["min_deposit"] = float(self.min_deposit) if self.min_deposit is not None else None
        data["deposit_address"] = deposit_address if fully else None
        # Keep the two reason fields in sync for any caller reading either.
        data["disabled_reason"] = self.disabled_reason or self.unavailable_reason
        data["unavailable_reason"] = self.unavailable_reason or self.disabled_reason
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
            unavailable_reason=None,
            detectable=True,
            creditable=True,
            sweepable=True,
            reconcilable=True,
            convertible=False,  # it IS the collateral token — no conversion needed
            disabled_reason=None,
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
            # Detectable via the wrong-token alert lane, but NOT tradeable: the
            # custody sweep (polygon_usdc.sweep_usdc_to_master) is hard-bound to
            # settings.USDC_POLYGON (USDC.e) and there is no USDC->USDC.e
            # conversion path, so native USDC cannot become confirmed available
            # live balance safely. Stays disabled until a conversion-custody
            # lane lands (#1800 documented blocker).
            unavailable_reason="Native USDC is detect-only — it is not Polymarket "
            "collateral and cannot be swept or converted to USDC.e yet, so it is "
            "never credited as tradeable balance.",
            detectable=True,
            creditable=False,
            sweepable=False,
            reconcilable=False,
            convertible=False,
            disabled_reason="no USDC->USDC.e conversion / sweep path (sweep is "
            "USDC.e-contract-bound)",
        ),
        DepositAsset(
            id="polygon-usdt",
            token_symbol="USDT",
            token_label="USDT",
            token_contract=getattr(settings, "USDT_POLYGON", None),
            network="Polygon",
            chain_id=137,
            display_label="USDT on Polygon",
            decimals=6,
            min_deposit=None,
            backend_supported=False,
            watcher_supported=False,
            bridge_custody_supported=False,
            enabled=False,
            # USDT is a different asset entirely: not watched, and it requires a
            # USDT->USDC.e conversion/settlement before it could be usable
            # trading collateral. No conversion path exists, so it stays
            # disabled (#1800 documented blocker).
            unavailable_reason="USDT requires a USDT->USDC.e conversion before it "
            "is usable trading collateral; no conversion/settlement path exists, "
            "so it is never watched, credited, or swept.",
            detectable=False,
            creditable=False,
            sweepable=False,
            reconcilable=False,
            convertible=False,
            disabled_reason="no USDT watcher and no USDT->USDC.e conversion path",
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
    """Selectable assets — the FULL end-to-end capability matrix must hold
    (#1800), not just the user-facing ``enabled`` flag. A token is selectable
    only when it is detectable, creditable, sweepable, and reconcilable (or
    convertible to the collateral token). This means a future stray
    ``enabled=True`` without the backing capabilities can never fake-enable a
    token for real deposits."""
    return tuple(
        asset for asset in supported_deposit_assets()
        if asset.is_fully_enabled
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
