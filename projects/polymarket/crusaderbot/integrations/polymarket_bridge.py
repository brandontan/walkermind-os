"""Polymarket Bridge API adapter and pUSD settlement helpers.

Docs source of truth (read during #1805): https://docs.polymarket.com/api-reference/bridge

This module is deliberately network-adapter only: CI/tests pass mocked payloads
or monkeypatch ``_request_json``. Runtime callers fail closed on Bridge outage and
must only credit balances from terminal COMPLETED status records whose target is
Polygon pUSD.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping

import aiohttp

from ..config import get_settings

POLYGON_CHAIN_ID = 137
PUSD_POLYGON = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
USDCE_POLYGON = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
NATIVE_USDC_POLYGON = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
# Bridge docs/API currently expose Polygon USDT as Wormhole Bridged USDT.
BRIDGE_USDT_POLYGON = "0x9417669fBF23357D2774e9D421307bd5eA1006d2"

TERMINAL_SUCCESS = "COMPLETED"
TERMINAL_FAILURES = frozenset({"FAILED", "EXPIRED", "CANCELLED", "CANCELED", "ERROR"})
NON_TERMINAL = frozenset({
    "DEPOSIT_DETECTED", "PROCESSING", "ORIGIN_TX_CONFIRMED", "SUBMITTED", "PENDING",
})


@dataclass(frozen=True)
class BridgeAsset:
    chain_id: int
    chain_name: str
    symbol: str
    name: str
    address: str
    decimals: int
    min_checkout_usd: Decimal | None

    @property
    def address_lower(self) -> str:
        return self.address.lower()


@dataclass(frozen=True)
class BridgeDepositAddresses:
    evm: str | None = None
    svm: str | None = None
    btc: str | None = None
    tvm: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class BridgeQuote:
    quote_id: str | None
    est_to_token_base_unit: str | None
    est_input_usd: Decimal | None
    est_output_usd: Decimal | None
    min_received: Decimal | None
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class BridgeTransaction:
    from_chain_id: int | None
    from_token_address: str | None
    from_amount_base_unit: str | None
    to_chain_id: int | None
    to_token_address: str | None
    status: str
    tx_hash: str | None
    created_time_ms: int | None
    raw: Mapping[str, Any]

    @property
    def is_completed_pusd_settlement(self) -> bool:
        return (
            self.status.upper() == TERMINAL_SUCCESS
            and self.to_chain_id == POLYGON_CHAIN_ID
            and (self.to_token_address or "").lower() == PUSD_POLYGON.lower()
        )

    @property
    def is_terminal_failure(self) -> bool:
        return self.status.upper() in TERMINAL_FAILURES


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def parse_supported_assets(payload: Mapping[str, Any]) -> tuple[BridgeAsset, ...]:
    assets: list[BridgeAsset] = []
    for raw in payload.get("supportedAssets") or []:
        token = raw.get("token") or {}
        chain_id = _int_or_none(raw.get("chainId"))
        address = token.get("address")
        symbol = token.get("symbol")
        if chain_id is None or not address or not symbol:
            continue
        assets.append(BridgeAsset(
            chain_id=chain_id,
            chain_name=str(raw.get("chainName") or ""),
            symbol=str(symbol),
            name=str(token.get("name") or symbol),
            address=str(address),
            decimals=int(token.get("decimals") or 0),
            min_checkout_usd=_decimal_or_none(raw.get("minCheckoutUsd")),
        ))
    return tuple(assets)


def polygon_asset_by_address(assets: Iterable[BridgeAsset], address: str | None) -> BridgeAsset | None:
    if not address:
        return None
    wanted = address.lower()
    for asset in assets:
        if asset.chain_id == POLYGON_CHAIN_ID and asset.address_lower == wanted:
            return asset
    return None


def required_polygon_bridge_assets_present(assets: Iterable[BridgeAsset]) -> dict[str, bool]:
    """Docs/API proof matrix for #1805 requested Polygon deposit tokens.

    True means the Bridge advertises the source token. It does NOT by itself
    mean CrusaderBot may credit the token; settlement still requires completed
    pUSD status handling.
    """
    seq = tuple(assets)
    return {
        "USDC.e": polygon_asset_by_address(seq, USDCE_POLYGON) is not None,
        "USDC": polygon_asset_by_address(seq, NATIVE_USDC_POLYGON) is not None,
        "USDT": polygon_asset_by_address(seq, BRIDGE_USDT_POLYGON) is not None,
        "pUSD": polygon_asset_by_address(seq, PUSD_POLYGON) is not None,
    }


def parse_deposit_addresses(payload: Mapping[str, Any]) -> BridgeDepositAddresses:
    addr = payload.get("address") or {}
    return BridgeDepositAddresses(
        evm=addr.get("evm"), svm=addr.get("svm"), btc=addr.get("btc"),
        tvm=addr.get("tvm"), note=payload.get("note"),
    )


def parse_quote(payload: Mapping[str, Any]) -> BridgeQuote:
    fee = payload.get("estFeeBreakdown") or {}
    return BridgeQuote(
        quote_id=payload.get("quoteId"),
        est_to_token_base_unit=payload.get("estToTokenBaseUnit"),
        est_input_usd=_decimal_or_none(payload.get("estInputUsd")),
        est_output_usd=_decimal_or_none(payload.get("estOutputUsd")),
        min_received=_decimal_or_none(fee.get("minReceived")),
        raw=dict(payload),
    )


def parse_status(payload: Mapping[str, Any]) -> tuple[BridgeTransaction, ...]:
    txs: list[BridgeTransaction] = []
    for raw in payload.get("transactions") or []:
        txs.append(BridgeTransaction(
            from_chain_id=_int_or_none(raw.get("fromChainId")),
            from_token_address=raw.get("fromTokenAddress"),
            from_amount_base_unit=raw.get("fromAmountBaseUnit"),
            to_chain_id=_int_or_none(raw.get("toChainId")),
            to_token_address=raw.get("toTokenAddress"),
            status=str(raw.get("status") or "").upper(),
            tx_hash=raw.get("txHash"),
            created_time_ms=_int_or_none(raw.get("createdTimeMs")),
            raw=dict(raw),
        ))
    return tuple(txs)


def base_units_to_decimal(amount_base_unit: str | int, decimals: int) -> Decimal:
    return Decimal(str(amount_base_unit)) / (Decimal(10) ** int(decimals))


def completed_pusd_settlements(transactions: Iterable[BridgeTransaction]) -> tuple[BridgeTransaction, ...]:
    return tuple(tx for tx in transactions if tx.is_completed_pusd_settlement)


async def _request_json(method: str, path: str, *, json_body: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    settings = get_settings()
    base = getattr(settings, "POLYMARKET_BRIDGE_URL", "https://bridge.polymarket.com").rstrip("/")
    timeout = aiohttp.ClientTimeout(total=float(getattr(settings, "POLYMARKET_BRIDGE_TIMEOUT_SECONDS", 20)))
    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "CrusaderBot/bridge"}) as session:
        async with session.request(method, f"{base}{path}", json=json_body) as resp:
            resp.raise_for_status()
            data = await resp.json()
    if not isinstance(data, Mapping):
        raise ValueError("Bridge response was not a JSON object")
    return data


async def get_supported_assets() -> tuple[BridgeAsset, ...]:
    return parse_supported_assets(await _request_json("GET", "/supported-assets"))


async def create_deposit_addresses(polymarket_wallet_address: str) -> BridgeDepositAddresses:
    return parse_deposit_addresses(await _request_json(
        "POST", "/deposit", json_body={"address": polymarket_wallet_address},
    ))


async def get_quote(*, from_amount_base_unit: str, from_chain_id: int, from_token_address: str,
                    recipient_address: str, to_chain_id: int = POLYGON_CHAIN_ID,
                    to_token_address: str = PUSD_POLYGON) -> BridgeQuote:
    return parse_quote(await _request_json("POST", "/quote", json_body={
        "fromAmountBaseUnit": str(from_amount_base_unit),
        "fromChainId": str(from_chain_id),
        "fromTokenAddress": from_token_address,
        "recipientAddress": recipient_address,
        "toChainId": str(to_chain_id),
        "toTokenAddress": to_token_address,
    }))


async def get_status(address: str) -> tuple[BridgeTransaction, ...]:
    return parse_status(await _request_json("GET", f"/status/{address}"))
