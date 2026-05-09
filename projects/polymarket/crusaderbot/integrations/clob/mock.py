"""MockClobClient — deterministic, network-free CLOB stub.

Used by the ``USE_REAL_CLOB=False`` factory branch (paper-safe default)
and by every unit test that does not specifically exercise signing.
Every operation returns a synthetic but well-formed response shape that
matches what the real ``ClobAdapter`` returns, so callers cannot
inadvertently rely on broker-specific fields.

Hard rule: this client MUST NOT make any network call, ever. Tests
verify there is no ``httpx.AsyncClient`` instantiated here.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

_ORDER_ID_NS = uuid.UUID("00000000-0000-0000-0000-000000000ABC")


class MockClobClient:
    """In-memory stand-in for ``ClobAdapter``.

    All methods are async to match the real surface (so callers can swap
    implementations without changing await sites). Returned payloads use
    realistic field names so unit tests of upstream code don't drift
    relative to the real broker shape.
    """

    def __init__(self, *, deterministic: bool = True) -> None:
        self._orders: dict[str, dict] = {}
        self._deterministic = deterministic
        self._counter = 0

    @property
    def has_builder_credentials(self) -> bool:
        return False

    async def aclose(self) -> None:
        return None

    async def __aenter__(self) -> "MockClobClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # ----- L1: credential lifecycle (no-op) -------------------------

    async def derive_api_credentials(self, *, nonce: int = 0) -> dict:
        return {
            "apiKey": "mock-api-key",
            "secret": "bW9jay1zZWNyZXQ=",  # base64("mock-secret")
            "passphrase": "mock-passphrase",
        }

    async def create_api_credentials(self, *, nonce: int = 0) -> dict:
        return await self.derive_api_credentials(nonce=nonce)

    # ----- L2: order surface ----------------------------------------

    async def post_order(
        self,
        *,
        token_id: str,
        side: str,
        price: float,
        size: float,
        order_type: str = "GTC",
        tick_size: Optional[str] = None,
        neg_risk: Optional[bool] = None,
    ) -> dict:
        self._counter += 1
        if self._deterministic:
            order_id = str(
                uuid.uuid5(_ORDER_ID_NS, f"{token_id}|{side}|{price}|{size}|{self._counter}")
            )
        else:  # pragma: no cover - non-deterministic branch is debug-only
            order_id = str(uuid.uuid4())
        record = {
            "orderID": order_id,
            "status": "matched",
            "tokenID": token_id,
            "side": side.upper(),
            "price": float(price),
            "size": float(size),
            "orderType": order_type,
            "tickSize": tick_size,
            "negRisk": bool(neg_risk) if neg_risk is not None else False,
            "transactionsHashes": [],
            "errorMsg": "",
            "_mock": True,
        }
        self._orders[order_id] = record
        logger.debug("MockClobClient.post_order accepted %s", order_id)
        return record

    async def cancel_order(self, order_id: str) -> dict:
        existing = self._orders.pop(order_id, None)
        return {
            "canceled": [order_id] if existing else [],
            "not_canceled": {} if existing else {order_id: "not_found"},
            "_mock": True,
        }

    async def cancel_all_orders(self, market: Optional[str] = None) -> dict:
        if market is not None:
            kept: dict[str, dict] = {}
            cancelled: list[str] = []
            for oid, rec in self._orders.items():
                if rec.get("market") == market or rec.get("tokenID") == market:
                    cancelled.append(oid)
                else:
                    kept[oid] = rec
            self._orders = kept
            return {
                "canceled": cancelled, "not_canceled": {}, "_mock": True,
                "market": market,
            }
        ids = list(self._orders.keys())
        self._orders.clear()
        return {"canceled": ids, "not_canceled": {}, "_mock": True}

    async def cancel_all(self) -> dict:
        return await self.cancel_all_orders()

    async def get_order(self, order_id: str) -> dict:
        return self._orders.get(
            order_id, {"orderID": order_id, "status": "not_found", "_mock": True},
        )

    async def get_fills(self, order_id: str) -> list[dict]:
        """Return synthetic fills for tests.

        The default mock returns an empty list — paper-mode lifecycle
        uses ``poll_attempts`` to simulate a fill without consulting
        this surface, so the absence of real fills here is correct.
        Tests that need fill-shaped payloads call ``record_fill``.
        """
        order = self._orders.get(order_id)
        if order is None:
            return []
        fills = order.get("_fills")
        return list(fills) if isinstance(fills, list) else []

    async def get_open_orders(
        self, market: Optional[str] = None,
    ) -> list[dict]:
        if market is None:
            return list(self._orders.values())
        return [
            rec for rec in self._orders.values()
            if rec.get("market") == market or rec.get("tokenID") == market
        ]

    def record_fill(self, order_id: str, fill: dict) -> None:
        """Test helper — attach a fill payload onto an existing order."""
        order = self._orders.get(order_id)
        if order is None:
            return
        order.setdefault("_fills", []).append(fill)

    async def request(
        self, method: str, path: str, *, body: str = "",
    ) -> dict:
        return {"_mock": True, "method": method, "path": path, "echo": body}

    # ----- helpers used in tests ------------------------------------

    def reset(self) -> None:
        """Drop the in-memory order book — handy between tests."""
        self._orders.clear()
        self._counter = 0

    def open_orders(self) -> list[dict]:
        return list(self._orders.values())
