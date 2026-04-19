from __future__ import annotations

import asyncio
from dataclasses import dataclass

from projects.polymarket.polyquantbot.client.telegram.dispatcher import (
    TelegramCommandContext,
    TelegramDispatcher,
)
from projects.polymarket.polyquantbot.server.core.public_beta_state import STATE
from projects.polymarket.polyquantbot.server.execution.paper_execution import PaperExecutionEngine
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal
from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import PaperPortfolio
from projects.polymarket.polyquantbot.server.risk.paper_risk_gate import PaperRiskGate
from projects.polymarket.polyquantbot.server.workers.paper_beta_worker import PaperBetaWorker


class FakeFalcon:
    async def rank_candidates(self):
        return [
            CandidateSignal(
                signal_id="sig-1",
                condition_id="cond-1",
                side="YES",
                edge=0.05,
                liquidity=20000.0,
                price=0.62,
            )
        ]


class RecordingWorker(PaperBetaWorker):
    def __init__(self, falcon, risk_gate, engine) -> None:
        super().__init__(falcon, risk_gate, engine)
        self.position_monitor_calls = 0
        self.price_updater_calls = 0

    async def position_monitor(self) -> int:
        self.position_monitor_calls += 1
        return await super().position_monitor()

    async def price_updater(self) -> None:
        self.price_updater_calls += 1
        await super().price_updater()


@dataclass
class FakeBackend:
    last_get_path: str = ""
    last_post_path: str = ""

    async def request_handoff(self, request):
        class _Result:
            outcome = "issued"
            session_id = "sess-1"
            detail = ""

        return _Result()

    async def beta_get(self, path: str, params=None):
        self.last_get_path = path
        if path == "/beta/positions":
            return {"items": []}
        if path == "/beta/pnl":
            return {"pnl": 12.5}
        if path == "/beta/risk":
            return {"drawdown": 0.0, "exposure": 0.02}
        if path == "/beta/status":
            return {"mode": "paper"}
        return {}

    async def beta_post(self, path: str, payload: dict[str, object]):
        self.last_post_path = path
        if path == "/beta/autotrade":
            return {"autotrade": payload.get("enabled", False)}
        if path == "/beta/mode":
            return {"mode": payload.get("mode", "paper")}
        return {"ok": True}


def _reset_state() -> None:
    STATE.mode = "paper"
    STATE.autotrade_enabled = False
    STATE.kill_switch = False
    STATE.pnl = 0.0
    STATE.drawdown = 0.0
    STATE.exposure = 0.0
    STATE.last_risk_reason = ""
    STATE.positions.clear()
    STATE.processed_signals.clear()


def _make_ctx(command: str, argument: str = "") -> TelegramCommandContext:
    return TelegramCommandContext(
        command=command,
        from_user_id="tg-1",
        chat_id="chat-1",
        tenant_id="tenant-1",
        user_id="user-1",
        argument=argument,
    )


def test_autotrade_off_prevents_new_entries() -> None:
    _reset_state()
    worker = PaperBetaWorker(FakeFalcon(), PaperRiskGate(), PaperExecutionEngine(PaperPortfolio()))
    asyncio.run(worker.run_once())
    assert len(STATE.positions) == 0
    assert STATE.last_risk_reason == "autotrade_disabled"


def test_kill_switch_prevents_new_entries() -> None:
    _reset_state()
    STATE.autotrade_enabled = True
    STATE.kill_switch = True
    worker = PaperBetaWorker(FakeFalcon(), PaperRiskGate(), PaperExecutionEngine(PaperPortfolio()))
    asyncio.run(worker.run_once())
    assert len(STATE.positions) == 0
    assert STATE.last_risk_reason == "kill_switch_enabled"


def test_mode_live_blocks_execution_events() -> None:
    _reset_state()
    STATE.mode = "live"
    STATE.autotrade_enabled = True
    worker = PaperBetaWorker(FakeFalcon(), PaperRiskGate(), PaperExecutionEngine(PaperPortfolio()))
    events = asyncio.run(worker.run_once())
    assert events == []
    assert len(STATE.positions) == 0
    assert STATE.last_risk_reason == "mode_live_paper_execution_disabled"
    assert STATE.worker_runtime.last_iteration.skip_mode_count == 1


def test_monitoring_stages_still_run_when_entries_blocked() -> None:
    _reset_state()
    worker = RecordingWorker(FakeFalcon(), PaperRiskGate(), PaperExecutionEngine(PaperPortfolio()))
    asyncio.run(worker.run_once())
    assert worker.position_monitor_calls == 1
    assert worker.price_updater_calls == 1
    assert STATE.worker_runtime.last_iteration.skip_autotrade_count == 1


def test_positions_command_maps_to_positions_endpoint() -> None:
    backend = FakeBackend()
    dispatcher = TelegramDispatcher(backend=backend)
    asyncio.run(dispatcher.dispatch(_make_ctx("/positions")))
    assert backend.last_get_path == "/beta/positions"


def test_pnl_and_risk_commands_map_to_dedicated_endpoints() -> None:
    backend = FakeBackend()
    dispatcher = TelegramDispatcher(backend=backend)
    asyncio.run(dispatcher.dispatch(_make_ctx("/pnl")))
    assert backend.last_get_path == "/beta/pnl"
    asyncio.run(dispatcher.dispatch(_make_ctx("/risk")))
    assert backend.last_get_path == "/beta/risk"


def test_connect_wallet_removed_from_public_shell() -> None:
    backend = FakeBackend()
    dispatcher = TelegramDispatcher(backend=backend)
    result = asyncio.run(dispatcher.dispatch(_make_ctx("/connect_wallet")))
    assert result.outcome == "unknown_command"
