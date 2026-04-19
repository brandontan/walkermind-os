"""SENTINEL Phase 9.1 — shared test fixtures.

Provides lightweight stubs for external dependencies (LiveExecutor, Telegram)
so every test runs in pure-asyncio without network I/O.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── Minimal structlog config so tests produce readable output ─────────────────

structlog.configure(
    processors=[structlog.dev.ConsoleRenderer()],
    wrapper_class=structlog.make_filtering_bound_logger(20),
    logger_factory=structlog.PrintLoggerFactory(),
)


# ── Stub helpers ──────────────────────────────────────────────────────────────

class _ExecutorResult:
    """Minimal execution result returned by stub executor."""

    def __init__(
        self,
        order_id: str = "order-stub-001",
        status: str = "submitted",
        error: Optional[str] = None,
    ) -> None:
        self.order_id = order_id
        self.status = status
        self.error = error


class StubExecutor:
    """Stub LiveExecutor for tests — no real HTTP calls."""

    def __init__(
        self,
        status: str = "submitted",
        order_id: str = "order-stub-001",
        fill_status: str = "filled",
        fill_size: float = 50.0,
        fill_price: float = 0.62,
        should_raise: bool = False,
        raise_exc: Optional[Exception] = None,
        latency_s: float = 0.0,
    ) -> None:
        self.status = status
        self.order_id = order_id
        self.fill_status = fill_status
        self.fill_size = fill_size
        self.fill_price = fill_price
        self.should_raise = should_raise
        self.raise_exc = raise_exc or RuntimeError("stub_executor_error")
        self.latency_s = latency_s
        self.executed_calls: list[dict] = []
        self.cancelled_ids: list[str] = []

    async def execute(self, request: Any) -> _ExecutorResult:
        if self.latency_s > 0:
            await asyncio.sleep(self.latency_s)
        if self.should_raise:
            raise self.raise_exc
        call = {
            "market_id": request.market_id,
            "side": request.side,
            "price": request.price,
            "size": request.size,
        }
        self.executed_calls.append(call)
        return _ExecutorResult(order_id=self.order_id, status=self.status)

    async def cancel_order(self, order_id: str, correlation_id: str = "") -> bool:
        self.cancelled_ids.append(order_id)
        return True

    async def cancel_all_open(self, reason: str = "") -> int:
        return 0

    async def get_order_status(self, order_id: str, correlation_id: str = "") -> Optional[dict]:
        if self.should_raise:
            return None
        return {
            "status": self.fill_status,
            "filled_size": self.fill_size,
            "avg_price": self.fill_price,
        }


class StubTelegram:
    """Stub Telegram dispatcher — records calls, never sends."""

    def __init__(self) -> None:
        self.alerts: list[dict] = []

    async def alert_open(self, **kwargs: Any) -> None:
        self.alerts.append({"type": "open", **kwargs})

    async def alert_close(self, **kwargs: Any) -> None:
        self.alerts.append({"type": "close", **kwargs})

    async def alert_kill(self, **kwargs: Any) -> None:
        self.alerts.append({"type": "kill", **kwargs})

    async def alert_daily(self, **kwargs: Any) -> None:
        self.alerts.append({"type": "daily", **kwargs})

    async def alert_error(self, **kwargs: Any) -> None:
        self.alerts.append({"type": "error", **kwargs})


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def stub_executor() -> StubExecutor:
    return StubExecutor()


@pytest.fixture
def stub_telegram() -> StubTelegram:
    return StubTelegram()


@pytest.fixture
async def risk_guard():
    """Fresh RiskGuard with default limits."""
    from projects.polymarket.polyquantbot.risk.risk_guard import RiskGuard
    guard = RiskGuard(daily_loss_limit=-2000.0, max_drawdown_pct=0.08)
    return guard


@pytest.fixture
async def position_tracker(risk_guard):
    """Fresh PositionTracker wired to a default RiskGuard."""
    from projects.polymarket.polyquantbot.risk.position_tracker import PositionTracker
    return PositionTracker(risk_guard=risk_guard)


@pytest.fixture
async def order_guard(risk_guard):
    """Fresh OrderGuard wired to a default RiskGuard."""
    from projects.polymarket.polyquantbot.risk.order_guard import OrderGuard
    return OrderGuard(risk_guard=risk_guard, order_timeout_sec=30.0)


@pytest.fixture
def metrics_validator():
    """Fresh MetricsValidator with production defaults."""
    from projects.polymarket.polyquantbot.monitoring.metrics_validator import MetricsValidator
    return MetricsValidator(
        ev_capture_target=0.75,
        fill_rate_target=0.70,
        p95_latency_target_ms=500.0,
        max_drawdown_target=0.08,
        min_trades=30,
    )


@pytest.fixture
def system_state():
    """Fresh SystemStateManager in RUNNING state."""
    from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
    return SystemStateManager()


@pytest.fixture
async def circuit_breaker(risk_guard):
    """CircuitBreaker with tight thresholds for fast test triggering."""
    from projects.polymarket.polyquantbot.core.circuit_breaker import CircuitBreaker
    return CircuitBreaker(
        risk_guard=risk_guard,
        error_rate_threshold=0.30,
        error_window_size=5,
        latency_threshold_ms=600.0,
        cooldown_sec=0.0,
        enabled=True,
        consecutive_failures_threshold=3,
    )
