# projects/polymarket/polyquantbot/platform/gateway/legacy_core_adapter.py
# NEXUS/FORGE-X — Phase 2.8 Legacy-Core Facade Adapter
# Claim: NARROW INTEGRATION (gateway → core delegation only)

from typing import Dict, Any, Optional
from dataclasses import dataclass

from projects.polymarket.polyquantbot.core.execution import LegacyExecutionEngine
from projects.polymarket.polyquantbot.core.risk import RiskValidator
from projects.polymarket.polyquantbot.core.strategy import StrategyExecutor


@dataclass
class ExecutionSignal:
    """Normalized signal input for legacy core."""
    market_id: str
    direction: str  # 'buy'/'sell'
    size: float
    context: Dict[str, Any]


@dataclass
class TradeValidation:
    """Normalized trade validation request."""
    market_id: str
    order_type: str
    notional: float
    risk_params: Dict[str, Any]


@dataclass
class ExecutionContext:
    """Normalized execution context."""
    user_id: str
    session_id: str
    capital_snapshot: Dict[str, float]


class LegacyCoreFacadeAdapter:
    """
    Strict facade for legacy core entrypoints.
    Rules:
    - No business logic
    - Pure delegation
    - Enforce input/output normalization
    """

    def __init__(
        self,
        execution_engine: LegacyExecutionEngine,
        risk_validator: RiskValidator,
        strategy_executor: StrategyExecutor,
    ):
        self._execution = execution_engine
        self._risk = risk_validator
        self._strategy = strategy_executor

    def execute_signal(self, signal: ExecutionSignal) -> Dict[str, Any]:
        """Delegate signal execution to legacy core."""
        legacy_input = {
            "market": signal.market_id,
            "side": signal.direction,
            "amount": signal.size,
            "meta": signal.context,
        }
        result = self._execution.execute(**legacy_input)
        return {"status": "executed", "data": result}

    def validate_trade(self, request: TradeValidation) -> Dict[str, Any]:
        """Delegate trade validation to legacy core."""
        legacy_input = {
            "market": request.market_id,
            "type": request.order_type,
            "notional": request.notional,
            **request.risk_params,
        }
        validation = self._risk.validate(**legacy_input)
        return {"valid": validation["is_valid"], "reason": validation.get("reason")}

    def prepare_execution_context(self, context: ExecutionContext) -> Dict[str, Any]:
        """Delegate context preparation to legacy core."""
        legacy_input = {
            "user": context.user_id,
            "session": context.session_id,
            **context.capital_snapshot,
        }
        prepared = self._execution.prepare_context(**legacy_input)
        return {"context_id": prepared["id"], "snapshot": prepared["data"]}
