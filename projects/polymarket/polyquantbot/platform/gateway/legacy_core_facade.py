from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ...core.risk.pre_trade_validator import PreTradeValidator
from ...core.signal.signal_engine import generate_signals
from ..context.models import PlatformContextEnvelope
from ..context.resolver import ContextResolver, LegacySessionSeed


@dataclass(frozen=True)
class LegacyCoreFacadeResolution:
    """Deterministic facade output for boundary consumers."""

    context_envelope: PlatformContextEnvelope | None
    source: str
    activated: bool


@dataclass(frozen=True)
class LegacySignalExecutionRequest:
    """DTO-style request contract for legacy strategy signal execution delegation."""

    markets: tuple[dict[str, Any], ...]
    bankroll: float
    force_signal_mode: bool | None = None


@dataclass(frozen=True)
class LegacySignalExecutionResult:
    """Normalized output contract for delegated legacy signal execution."""

    signals: tuple[dict[str, Any], ...]
    source: str


@dataclass(frozen=True)
class LegacyTradeValidationRequest:
    """DTO-style request contract for legacy risk validation delegation."""

    signal_data: dict[str, Any]
    decision_data: dict[str, Any]
    risk_state: dict[str, Any]
    execution_context: dict[str, Any] | None


@dataclass(frozen=True)
class LegacyTradeValidationResult:
    """Normalized output contract for delegated legacy trade validation."""

    decision: str
    reason: str
    checks: dict[str, float | bool]
    source: str


@runtime_checkable
class LegacyCoreFacade(Protocol):
    """Stable seam between platform-facing gateway code and legacy-core surfaces."""

    def resolve_context(self, seed: LegacySessionSeed) -> LegacyCoreFacadeResolution:
        """Resolve platform context through a legacy-core backed adapter or deterministic fallback."""

    async def execute_signal(self, request: LegacySignalExecutionRequest) -> LegacySignalExecutionResult:
        """Execute signal generation through controlled facade delegation."""

    def validate_trade(self, request: LegacyTradeValidationRequest) -> LegacyTradeValidationResult:
        """Validate trade readiness through controlled facade delegation."""

    def prepare_execution_context(self, seed: LegacySessionSeed) -> LegacyCoreFacadeResolution:
        """Prepare execution context via controlled facade delegation."""

    def assert_adapter_usage(self) -> bool:
        """Return True only for implementations intended for gateway-mediated routing."""


class LegacyCoreResolverAdapter:
    """Legacy-backed adapter shell that delegates to legacy core entrypoints without business logic."""

    def __init__(
        self,
        resolver: ContextResolver | None = None,
        validator: PreTradeValidator | None = None,
    ) -> None:
        self._resolver = resolver or ContextResolver()
        self._validator = validator or PreTradeValidator()

    def resolve_context(self, seed: LegacySessionSeed) -> LegacyCoreFacadeResolution:
        envelope = self._resolver.resolve(seed)
        return LegacyCoreFacadeResolution(
            context_envelope=envelope,
            source="legacy-context-resolver",
            activated=True,
        )

    async def execute_signal(self, request: LegacySignalExecutionRequest) -> LegacySignalExecutionResult:
        if len(request.markets) == 0:
            raise ValueError("invalid_signal_format: markets must not be empty")
        for market in request.markets:
            if not {"market_id", "p_market", "liquidity_usd"}.issubset(market.keys()):
                raise ValueError("invalid_signal_format: required keys missing")
        signals = await generate_signals(
            request.markets,
            bankroll=request.bankroll,
            force_signal_mode=request.force_signal_mode,
        )
        normalized_signals: tuple[dict[str, Any], ...] = tuple(
            {
                "signal_id": signal.signal_id,
                "market_id": signal.market_id,
                "side": signal.side,
                "edge": signal.edge,
                "size_usd": signal.size_usd,
                "liquidity_usd": signal.liquidity_usd,
            }
            for signal in signals
        )
        return LegacySignalExecutionResult(signals=normalized_signals, source="legacy-signal-engine")

    def validate_trade(self, request: LegacyTradeValidationRequest) -> LegacyTradeValidationResult:
        if request.execution_context is None:
            raise ValueError("missing_execution_context")
        validation_result = self._validator.validate(
            signal_data=request.signal_data,
            decision_data=request.decision_data,
            risk_state=request.risk_state,
        )
        return LegacyTradeValidationResult(
            decision=validation_result.decision,
            reason=validation_result.reason,
            checks=validation_result.checks,
            source="legacy-pre-trade-validator",
        )

    def prepare_execution_context(self, seed: LegacySessionSeed) -> LegacyCoreFacadeResolution:
        return self.resolve_context(seed)

    def assert_adapter_usage(self) -> bool:
        return True


class LegacyCoreFacadeDisabled:
    """Deterministic fallback when facade activation is intentionally disabled."""

    def resolve_context(self, seed: LegacySessionSeed) -> LegacyCoreFacadeResolution:
        _ = seed
        return LegacyCoreFacadeResolution(
            context_envelope=None,
            source="disabled",
            activated=False,
        )

    async def execute_signal(self, request: LegacySignalExecutionRequest) -> LegacySignalExecutionResult:
        _ = request
        return LegacySignalExecutionResult(signals=tuple(), source="disabled")

    def validate_trade(self, request: LegacyTradeValidationRequest) -> LegacyTradeValidationResult:
        _ = request
        return LegacyTradeValidationResult(
            decision="BLOCK",
            reason="disabled",
            checks={"global_trade_block": True},
            source="disabled",
        )

    def prepare_execution_context(self, seed: LegacySessionSeed) -> LegacyCoreFacadeResolution:
        return self.resolve_context(seed)

    def assert_adapter_usage(self) -> bool:
        return True
