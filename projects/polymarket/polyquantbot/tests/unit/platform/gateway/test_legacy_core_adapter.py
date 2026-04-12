# projects/polymarket/polyquantbot/tests/unit/platform/gateway/test_legacy_core_adapter.py
# NEXUS/FORGE-X — Phase 2.8: Adapter unit tests

import pytest
from unittest.mock import MagicMock

from projects.polymarket.polyquantbot.platform.gateway.legacy_core_adapter import (
    LegacyCoreFacadeAdapter,
    ExecutionSignal,
    TradeValidation,
    ExecutionContext,
)


class TestLegacyCoreFacadeAdapter:
    """Unit tests for LegacyCoreFacadeAdapter."""

    @pytest.fixture
    def mock_execution_engine(self):
        mock = MagicMock()
        mock.execute.return_value = {"order_id": "123", "status": "filled"}
        mock.prepare_context.return_value = {"id": "ctx_456", "data": {"balance": 1000}}
        return mock

    @pytest.fixture
    def mock_risk_validator(self):
        mock = MagicMock()
        mock.validate.return_value = {"is_valid": True, "reason": "OK"}
        return mock

    @pytest.fixture
    def mock_strategy_executor(self):
        return MagicMock()

    @pytest.fixture
    def adapter(self, mock_execution_engine, mock_risk_validator, mock_strategy_executor):
        return LegacyCoreFacadeAdapter(
            execution_engine=mock_execution_engine,
            risk_validator=mock_risk_validator,
            strategy_executor=mock_strategy_executor,
        )

    def test_execute_signal_delegates_to_execution_engine(self, adapter, mock_execution_engine):
        signal = ExecutionSignal(
            market_id="BTC-USD",
            direction="buy",
            size=0.1,
            context={},
        )
        result = adapter.execute_signal(signal)
        mock_execution_engine.execute.assert_called_once()
        assert result["status"] == "executed"

    def test_validate_trade_delegates_to_risk_validator(self, adapter, mock_risk_validator):
        request = TradeValidation(
            market_id="BTC-USD",
            order_type="limit",
            notional=100.0,
            risk_params={},
        )
        result = adapter.validate_trade(request)
        mock_risk_validator.validate.assert_called_once()
        assert result["valid"] is True

    def test_prepare_execution_context_delegates_to_execution_engine(self, adapter, mock_execution_engine):
        context = ExecutionContext(
            user_id="user_789",
            session_id="session_abc",
            capital_snapshot={"USD": 5000},
        )
        result = adapter.prepare_execution_context(context)
        mock_execution_engine.prepare_context.assert_called_once()
        assert result["context_id"] == "ctx_456"

    def test_adapter_normalizes_input_output(self, adapter):
        """Ensure adapter enforces DTO-style input/output."""
        signal = ExecutionSignal(
            market_id="ETH-USD",
            direction="sell",
            size=0.5,
            context={"note": "test"},
        )
        result = adapter.execute_signal(signal)
        assert isinstance(result, dict)
        assert "status" in result
        assert "data" in result