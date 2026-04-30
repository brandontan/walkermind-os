"""Mock CLOB client for integration tests — no real network calls, no real funds.

MockClobClient satisfies ClobClientProtocol and returns deterministic
responses for test harnesses.  It records all submitted payloads so
tests can assert on submission content and count.

Usage::

    client = MockClobClient(order_id="test-order-001", status="MATCHED")
    adapter = ClobExecutionAdapter(config=live_cfg, client=client, mode="mocked")
    result = await adapter.submit_order(state, signal, token_id="abc123", provider=provider)
    assert result.order_id == "test-order-001"
    assert len(client.submitted_payloads) == 1
"""
from __future__ import annotations

from typing import Any

from projects.polymarket.polyquantbot.server.execution.clob_execution_adapter import ClobSubmissionError


class MockClobClient:
    """Deterministic mock CLOB client for integration testing.

    Satisfies ClobClientProtocol without any network calls or real funds.

    Args:
        order_id:    Order ID to return in the mock response.
        status:      Status string to return (e.g. "MATCHED", "LIVE").
        raise_error: If set, raises ClobSubmissionError on post_order().
        extra_fields: Additional fields to include in the mock response dict.
    """

    def __init__(
        self,
        order_id: str = "mock-order-0001",
        status: str = "MATCHED",
        raise_error: Exception | None = None,
        extra_fields: dict[str, Any] | None = None,
    ) -> None:
        self._order_id = order_id
        self._status = status
        self._raise_error = raise_error
        self._extra_fields = extra_fields or {}
        self.submitted_payloads: list[dict[str, Any]] = []
        self.call_count: int = 0

    async def post_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record payload and return a deterministic mock response.

        Args:
            payload: Order payload dict from ClobExecutionAdapter.

        Returns:
            Mock response dict with orderId and status.

        Raises:
            ClobSubmissionError: If raise_error was set at construction time.
        """
        self.call_count += 1
        self.submitted_payloads.append(payload)
        if self._raise_error is not None:
            raise self._raise_error
        response: dict[str, Any] = {
            "orderId": self._order_id,
            "status": self._status,
        }
        response.update(self._extra_fields)
        return response
