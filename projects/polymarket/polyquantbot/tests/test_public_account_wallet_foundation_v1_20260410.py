from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from typing import Any

from projects.polymarket.polyquantbot.execution.engine import ExecutionEngine
from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    StrategyAggregationDecision,
    StrategyCandidateScore,
    StrategyConfig,
    StrategyTrigger,
)
from projects.polymarket.polyquantbot.infra.account_runtime import (
    AccountRuntimeResolutionError,
    AccountRuntimeResolver,
    TradeIntentWriter,
)


class _InMemoryAccountRuntimeRepository:
    def __init__(self, row: dict[str, Any] | None = None) -> None:
        self._row = row
        self.trade_intents: list[dict[str, Any]] = []

    async def resolve_account_runtime_row(
        self,
        *,
        user_id: str,
        trading_account_id: str | None,
    ) -> dict[str, Any] | None:
        if self._row is None:
            return None
        if str(self._row.get("user_id")) != user_id:
            return None
        if trading_account_id and str(self._row.get("trading_account_id")) != trading_account_id:
            return None
        return dict(self._row)

    async def insert_trade_intent(self, payload: dict[str, Any]) -> bool:
        self.trade_intents.append(dict(payload))
        return True


def _seed_risk_state_file(path: Path) -> None:
    path.write_text(
        (
            '{"correlated_exposure_ratio":0.0,'
            '"daily_pnl_by_day":{},'
            '"drawdown_ratio":0.0,'
            '"equity":10000.0,'
            '"global_trade_block":false,'
            '"open_trades":0,'
            '"peak_equity":10000.0,'
            '"portfolio_pnl":0.0,'
            '"version":1}'
        ),
        encoding="utf-8",
    )


def _build_aggregation() -> StrategyAggregationDecision:
    candidate = StrategyCandidateScore(
        strategy_name="S1",
        decision="ENTER",
        reason="test_signal",
        edge=0.06,
        confidence=0.9,
        score=0.95,
        market_metadata={"market_id": "MARKET-1", "title": "Test Market"},
    )
    return StrategyAggregationDecision(
        selected_trade="S1",
        ranked_candidates=[candidate],
        selection_reason="highest_score",
        top_score=0.95,
        decision="ENTER",
    )


def _build_trigger(
    *,
    resolver: AccountRuntimeResolver | None = None,
    writer: TradeIntentWriter | None = None,
    account_user_id: str | None = None,
    trading_account_id: str | None = None,
) -> StrategyTrigger:
    state_file = Path(tempfile.mkstemp(suffix="_public_account_risk_state.json")[1])
    _seed_risk_state_file(state_file)
    trigger = StrategyTrigger(
        engine=ExecutionEngine(starting_equity=10_000.0),
        config=StrategyConfig(
            market_id="MARKET-1",
            threshold=0.60,
            target_pnl=2.0,
            risk_state_persistence_path=str(state_file),
        ),
        account_runtime_resolver=resolver,
        trade_intent_writer=writer,
        account_user_id=account_user_id,
        trading_account_id=trading_account_id,
    )
    trigger._cooldown_seconds = 0.0  # noqa: SLF001
    trigger._intelligence.evaluate_entry = lambda _snapshot: {"score": 1.0, "reasons": ["test"]}  # type: ignore[assignment] # noqa: SLF001
    return trigger


def test_account_runtime_resolver_resolves_active_paper_envelope() -> None:
    async def _run() -> None:
        repository = _InMemoryAccountRuntimeRepository(
            row={
                "user_id": "user-1",
                "trading_account_id": "acct-1",
                "mode": "paper",
                "wallet_type": "custodial",
                "wallet_address": "0xabc",
                "proxy_wallet_address": "",
                "funder_address": "",
                "credential_reference": "",
                "risk_profile": {"profile": "default"},
            }
        )
        resolver = AccountRuntimeResolver(repository)
        envelope = await resolver.resolve_active_envelope(user_id="user-1", trading_account_id="acct-1")
        assert envelope.mode == "paper"
        assert envelope.trading_account_id == "acct-1"
        assert envelope.risk_profile["profile"] == "default"

    asyncio.run(_run())


def test_account_runtime_resolver_fails_closed_on_invalid_mode() -> None:
    async def _run() -> None:
        repository = _InMemoryAccountRuntimeRepository(
            row={
                "user_id": "user-1",
                "trading_account_id": "acct-1",
                "mode": "sandbox",
                "risk_profile": {"profile": "default"},
            }
        )
        resolver = AccountRuntimeResolver(repository)
        try:
            await resolver.resolve_active_envelope(user_id="user-1", trading_account_id="acct-1")
        except AccountRuntimeResolutionError as exc:
            assert str(exc) == "invalid_account_mode"
            return
        raise AssertionError("expected AccountRuntimeResolutionError for invalid mode")

    asyncio.run(_run())


def test_account_runtime_resolver_fails_closed_on_live_without_auth_metadata() -> None:
    async def _run() -> None:
        repository = _InMemoryAccountRuntimeRepository(
            row={
                "user_id": "user-1",
                "trading_account_id": "acct-1",
                "mode": "live",
                "wallet_type": "custodial",
                "wallet_address": "0xabc",
                "credential_reference": "",
                "risk_profile": {"profile": "strict"},
            }
        )
        resolver = AccountRuntimeResolver(repository)
        try:
            await resolver.resolve_active_envelope(user_id="user-1", trading_account_id="acct-1")
        except AccountRuntimeResolutionError as exc:
            assert str(exc) == "missing_live_auth_metadata"
            return
        raise AssertionError("expected AccountRuntimeResolutionError for missing live auth metadata")

    asyncio.run(_run())


def test_strategy_trigger_records_trade_intent_without_bypassing_execution_proof_path() -> None:
    async def _run() -> None:
        repository = _InMemoryAccountRuntimeRepository(
            row={
                "user_id": "user-1",
                "trading_account_id": "acct-1",
                "mode": "live_shadow",
                "wallet_type": "custodial",
                "wallet_address": "0xabc",
                "credential_reference": "cred-ref-1",
                "risk_profile": {"profile": "default"},
            }
        )
        resolver = AccountRuntimeResolver(repository)
        writer = TradeIntentWriter(repository)
        trigger = _build_trigger(
            resolver=resolver,
            writer=writer,
            account_user_id="user-1",
            trading_account_id="acct-1",
        )
        decision = await trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(),
            market_context={
                "expected_value": 0.10,
                "liquidity_usd": 50_000.0,
                "spread": 0.01,
                "best_bid": 0.445,
                "best_ask": 0.455,
                "model_probability": 0.62,
                "orderbook": {"bids": [[0.45, 20000.0]], "asks": [[0.46, 20000.0]]},
                "timestamp": time.time(),
            },
        )
        assert decision == "OPENED"
        assert len(repository.trade_intents) == 1
        assert repository.trade_intents[0]["mode"] == "live_shadow"
        assert repository.trade_intents[0]["status"] == "recorded"

    asyncio.run(_run())


def test_strategy_trigger_fails_closed_when_live_auth_metadata_missing() -> None:
    async def _run() -> None:
        repository = _InMemoryAccountRuntimeRepository(
            row={
                "user_id": "user-1",
                "trading_account_id": "acct-1",
                "mode": "live",
                "wallet_type": "custodial",
                "wallet_address": "0xabc",
                "credential_reference": "",
                "risk_profile": {"profile": "default"},
            }
        )
        resolver = AccountRuntimeResolver(repository)
        writer = TradeIntentWriter(repository)
        trigger = _build_trigger(
            resolver=resolver,
            writer=writer,
            account_user_id="user-1",
            trading_account_id="acct-1",
        )
        decision = await trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(),
            market_context={
                "expected_value": 0.10,
                "liquidity_usd": 50_000.0,
                "spread": 0.01,
                "best_bid": 0.445,
                "best_ask": 0.455,
            },
        )
        assert decision == "BLOCKED"
        assert repository.trade_intents == []

    asyncio.run(_run())
