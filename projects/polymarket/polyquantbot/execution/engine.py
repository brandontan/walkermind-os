from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
import statistics
import time
from typing import Any
import uuid

import structlog

from .models import Position
from .analytics import PerformanceTracker
from .trade_trace import TradeTraceEngine

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ExecutionSnapshot:
    positions: tuple[Position, ...]
    cash: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    implied_prob: float
    volatility: float


@dataclass(frozen=True)
class ExecutionValidationProof:
    validation_id: str
    validation_decision: str
    validation_reason: str
    validation_checks_hash: str
    issued_at_unix: float
    signature: str


class ExecutionEngine:
    """Paper-only execution engine with sizing, PnL tracking, and performance analytics."""

    def __init__(self, starting_equity: float = 10_000.0) -> None:
        self._lock = asyncio.Lock()
        self._positions: dict[str, Position] = {}
        self._cash: float = float(starting_equity)
        self._equity: float = float(starting_equity)
        self._realized_pnl: float = 0.0
        self._unrealized_pnl: float = 0.0
        self._implied_prob: float = 0.50
        self._volatility: float = 0.10
        self.max_position_size_ratio: float = 0.10
        self.max_total_exposure_ratio: float = 0.30
        self._analytics = PerformanceTracker()
        self._trace_engine = TradeTraceEngine()
        self._closed_trades: list[dict[str, Any]] = []
        self._position_context: dict[str, dict[str, Any]] = {}
        self._validation_secret: str = secrets.token_hex(32)
        self._last_open_rejection: dict[str, Any] | None = None

    def build_validation_proof(
        self,
        *,
        validation_id: str,
        validation_decision: str,
        validation_reason: str,
        validation_checks: dict[str, bool] | None,
    ) -> ExecutionValidationProof:
        """Create a signed execution validation proof for trusted gateway paths."""
        checks_hash = self._hash_validation_checks(validation_checks or {})
        issued_at_unix = time.time()
        signature = self._sign_validation_fields(
            validation_id=validation_id,
            validation_decision=validation_decision,
            validation_reason=validation_reason,
            validation_checks_hash=checks_hash,
            issued_at_unix=issued_at_unix,
        )
        return ExecutionValidationProof(
            validation_id=validation_id,
            validation_decision=validation_decision,
            validation_reason=validation_reason,
            validation_checks_hash=checks_hash,
            issued_at_unix=issued_at_unix,
            signature=signature,
        )

    async def open_position(
        self,
        market: str,
        market_title: str,
        side: str,
        price: float,
        size: float,
        position_id: str | None = None,
        position_context: dict[str, Any] | None = None,
        validation_proof: ExecutionValidationProof | None = None,
    ) -> Position | None:
        """Create position object and update paper portfolio if risk allows."""
        async with self._lock:
            self._last_open_rejection = None
            if not self._is_validation_proof_allowed(validation_proof):
                self._record_open_rejection(
                    reason="validation_proof_required_or_invalid",
                    market=market,
                    position_id=position_id,
                )
                return None
            size = float(size)
            if size <= 0:
                self._record_open_rejection(
                    reason="size_non_positive",
                    market=market,
                    position_id=position_id,
                    requested_size=size,
                )
                return None
            if not position_id:
                position_id = str(uuid.uuid4())
            equity_base = max(self._equity, 0.0)
            max_position_size = equity_base * self.max_position_size_ratio
            if size > max_position_size:
                self._record_open_rejection(
                    reason="max_position_size_exceeded",
                    market=market,
                    position_id=position_id,
                    requested_size=size,
                    limit=max_position_size,
                    equity=equity_base,
                )
                return None
            current_exposure = self._current_total_exposure()
            total_exposure_limit = equity_base * self.max_total_exposure_ratio
            remaining_total_exposure = max(0.0, total_exposure_limit - current_exposure)
            capital_risk_allowed_size = max(
                0.0,
                min(max_position_size, remaining_total_exposure, self._cash),
            )
            if size > capital_risk_allowed_size:
                binding_constraint = "cash_available"
                if remaining_total_exposure <= self._cash:
                    binding_constraint = "remaining_total_exposure"
                self._record_open_rejection(
                    reason="capital_risk_allowed_size_exceeded",
                    market=market,
                    position_id=position_id,
                    requested_size=size,
                    capital_risk_allowed_size=capital_risk_allowed_size,
                    binding_constraint=binding_constraint,
                    cash_available=self._cash,
                    current_exposure=current_exposure,
                    remaining_total_exposure=remaining_total_exposure,
                    total_exposure_limit=total_exposure_limit,
                    max_position_size=max_position_size,
                    equity=equity_base,
                )
                return None

            position = Position(
                market_id=market,
                market_title=market_title,
                side=side.upper(),
                entry_price=float(price),
                current_price=float(price),
                size=size,
                pnl=0.0,
                position_id=position_id
            )
            self._positions[market] = position
            self._position_context[position.position_id] = dict(position_context or {})
            self._cash -= size
            self._implied_prob = max(0.01, min(0.99, float(price)))
            self._recalculate_unrealized()
            self._refresh_equity()
            log.info("execution_engine_position_opened", market=market, side=side, price=price, size=size)
            return position

    def get_last_open_rejection(self) -> dict[str, Any] | None:
        if self._last_open_rejection is None:
            return None
        return dict(self._last_open_rejection)

    def _record_open_rejection(self, *, reason: str, **details: Any) -> None:
        rejection_payload = {"reason": reason, **details}
        self._last_open_rejection = rejection_payload
        log.warning("execution_engine_open_rejected", **rejection_payload)

    def _is_validation_proof_allowed(self, proof: ExecutionValidationProof | None) -> bool:
        if not isinstance(proof, ExecutionValidationProof):
            return False
        if not proof.validation_id.strip():
            return False
        if proof.validation_decision != "ALLOW":
            return False
        if not proof.validation_checks_hash.strip() or len(proof.validation_checks_hash) != 64:
            return False
        if not isinstance(proof.issued_at_unix, float):
            return False
        expected_signature = self._sign_validation_fields(
            validation_id=proof.validation_id,
            validation_decision=proof.validation_decision,
            validation_reason=proof.validation_reason,
            validation_checks_hash=proof.validation_checks_hash,
            issued_at_unix=proof.issued_at_unix,
        )
        return hmac.compare_digest(expected_signature, proof.signature)

    def _sign_validation_fields(
        self,
        *,
        validation_id: str,
        validation_decision: str,
        validation_reason: str,
        validation_checks_hash: str,
        issued_at_unix: float,
    ) -> str:
        payload = "|".join(
            [
                validation_id.strip(),
                validation_decision.strip().upper(),
                validation_reason.strip(),
                validation_checks_hash.strip(),
                f"{issued_at_unix:.6f}",
            ]
        )
        return hmac.new(
            self._validation_secret.encode("utf-8"),
            payload.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _hash_validation_checks(validation_checks: dict[str, bool]) -> str:
        normalized = json.dumps(validation_checks, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    async def close_position(
        self,
        position: Position,
        price: float,
        close_context: dict[str, Any] | None = None,
    ) -> float:
        """Close position, realize PnL, and update portfolio."""
        async with self._lock:
            live_position = self._positions.get(position.market_id)
            if live_position is None:
                log.warning("execution_engine_close_ignored", reason="position_not_found", market=position.market_id)
                return 0.0

            realized_pnl = live_position.update_price(float(price))
            self._realized_pnl += realized_pnl
            self._cash += live_position.size + realized_pnl
            entry_context = self._position_context.pop(live_position.position_id, {})
            final_context = dict(entry_context)
            final_context.update(dict(close_context or {}))
            duration = max(0.0, (datetime.now(timezone.utc).timestamp() - live_position.created_at))
            theoretical_edge = max(0.0, float(final_context.get("theoretical_edge", 0.0)))
            actual_return = float(final_context.get("actual_return", realized_pnl / max(live_position.size, 1e-9)))
            strategy_source = str(final_context.get("strategy_source", "UNKNOWN")).strip().upper() or "UNKNOWN"
            regime_at_entry = str(final_context.get("regime_at_entry", "CHAOTIC")).strip().upper() or "CHAOTIC"
            entry_quality = str(final_context.get("entry_quality", "not_provided"))
            entry_timing = str(final_context.get("entry_timing", "not_provided"))
            exit_reason = str(final_context.get("exit_reason", "not_provided"))
            slippage_impact = float(final_context.get("slippage_impact", 0.0))
            timing_effectiveness = float(final_context.get("timing_effectiveness", 0.0))
            exit_efficiency = float(final_context.get("exit_efficiency", 0.0))
            closed_trade = {
                "market_id": live_position.market_id,
                "market_title": live_position.market_title,
                "side": live_position.side,
                "entry_price": live_position.entry_price,
                "exit_price": float(price),
                "pnl": realized_pnl,
                "result": "WIN" if realized_pnl >= 0 else "LOSS",
                "closed_at": datetime.now(timezone.utc).isoformat(),
                "position_id": live_position.position_id,
                "size": live_position.size,
                "duration": round(duration, 6),
                "strategy_source": strategy_source,
                "regime_at_entry": regime_at_entry,
                "entry_quality": entry_quality,
                "entry_timing": entry_timing,
                "exit_reason": exit_reason,
                "theoretical_edge": theoretical_edge,
                "actual_return": actual_return,
                "slippage_impact": slippage_impact,
                "timing_effectiveness": timing_effectiveness,
                "exit_efficiency": exit_efficiency,
            }
            self._analytics.record_trade(closed_trade)
            self._closed_trades.append(closed_trade)
            del self._positions[live_position.market_id]
            self._recalculate_unrealized()
            self._refresh_equity()
            log.info("execution_engine_position_closed", market=live_position.market_id, close_price=price, pnl=realized_pnl)
            return realized_pnl

    async def update_mark_to_market(self, market_prices: dict[str, float]) -> float:
        """Update all open positions unrealized PnL from market prices."""
        async with self._lock:
            normalized_prices: list[float] = []
            for market_id, position in self._positions.items():
                maybe_price = market_prices.get(market_id)
                if maybe_price is None:
                    continue
                normalized = max(0.01, min(0.99, float(maybe_price)))
                normalized_prices.append(normalized)
                position.update_price(normalized)
            if normalized_prices:
                self._implied_prob = max(0.01, min(0.99, float(sum(normalized_prices) / len(normalized_prices))))
                self._volatility = max(0.01, float(statistics.pstdev(normalized_prices)) if len(normalized_prices) > 1 else 0.10)
            self._recalculate_unrealized()
            self._refresh_equity()
            return self._unrealized_pnl

    async def snapshot(self) -> ExecutionSnapshot:
        async with self._lock:
            return ExecutionSnapshot(
                positions=tuple(self._positions.values()),
                cash=self._cash,
                equity=self._equity,
                realized_pnl=self._realized_pnl,
                unrealized_pnl=self._unrealized_pnl,
                implied_prob=self._implied_prob,
                volatility=self._volatility,
            )

    def _current_total_exposure(self) -> float:
        return sum(pos.exposure() for pos in self._positions.values())

    def _recalculate_unrealized(self) -> None:
        self._unrealized_pnl = sum(pos.pnl for pos in self._positions.values())

    def _refresh_equity(self) -> None:
        locked_notional = self._current_total_exposure()
        self._equity = self._cash + locked_notional + self._unrealized_pnl

    def get_analytics(self) -> PerformanceTracker:
        """Expose analytics for UI integration."""
        return self._analytics


_engine_singleton: ExecutionEngine | None = None


def get_execution_engine() -> ExecutionEngine:
    global _engine_singleton  # noqa: PLW0603
    if _engine_singleton is None:
        _engine_singleton = ExecutionEngine()
    return _engine_singleton


async def export_execution_payload() -> dict[str, Any]:
    engine = get_execution_engine()
    snapshot = await engine.snapshot()
    return {
        "positions": [
            {
                "market_id": pos.market_id,
                "market_title": pos.market_title,
                "side": pos.side,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price,
                "size": pos.size,
                "pnl": pos.pnl,
                "unrealized_pnl": pos.pnl,
                "position_id": pos.position_id,
                "opened_at": datetime.fromtimestamp(pos.created_at, tz=timezone.utc).isoformat(),
            }
            for pos in snapshot.positions
        ],
        "cash": snapshot.cash,
        "equity": snapshot.equity,
        "realized": snapshot.realized_pnl,
        "unrealized": snapshot.unrealized_pnl,
        "closed_trades": list(reversed(engine._closed_trades)),
    }
