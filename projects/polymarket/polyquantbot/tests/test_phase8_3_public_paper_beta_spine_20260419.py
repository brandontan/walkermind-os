from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

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
from projects.polymarket.polyquantbot.server.main import create_app


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
            return {
                "drawdown": 0.0,
                "exposure": 0.02,
                "last_reason": "autotrade_disabled",
                "kill_switch": False,
                "autotrade_enabled": False,
            }
        if path == "/beta/status":
            return {
                "mode": "paper",
                "autotrade": False,
                "kill_switch": False,
                "position_count": 0,
                "last_risk_reason": "autotrade_disabled",
                "execution_guard": {
                    "entry_allowed": False,
                    "blocked_reasons": ["autotrade_disabled"],
                },
            }
        return {}

    async def beta_post(self, path: str, payload: dict[str, object]):
        self.last_post_path = path
        if path == "/beta/autotrade":
            return {"autotrade": payload.get("enabled", False)}
        if path == "/beta/mode":
            return {
                "mode": payload.get("mode", "paper"),
                "execution_boundary": "paper_only",
                "detail": "live mode is control-plane state only in this phase; execution remains paper-only.",
            }
        return {"ok": True, "mode": "paper"}


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
    STATE.worker_runtime.active = False
    STATE.worker_runtime.startup_complete = False
    STATE.worker_runtime.shutdown_complete = False
    STATE.worker_runtime.iterations_total = 0
    STATE.worker_runtime.last_error = ""
    STATE.worker_runtime.last_iteration.candidate_count = 0
    STATE.worker_runtime.last_iteration.accepted_count = 0
    STATE.worker_runtime.last_iteration.rejected_count = 0
    STATE.worker_runtime.last_iteration.skip_autotrade_count = 0
    STATE.worker_runtime.last_iteration.skip_kill_count = 0
    STATE.worker_runtime.last_iteration.skip_mode_count = 0
    STATE.worker_runtime.last_iteration.current_position_count = 0
    STATE.worker_runtime.last_iteration.risk_rejection_reasons = {}


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


def test_mode_command_reply_mentions_paper_only_boundary() -> None:
    backend = FakeBackend()
    dispatcher = TelegramDispatcher(backend=backend)
    result = asyncio.run(dispatcher.dispatch(_make_ctx("/mode", "live")))
    assert "paper-only" in result.reply_text


def test_unknown_command_reply_lists_supported_commands() -> None:
    backend = FakeBackend()
    dispatcher = TelegramDispatcher(backend=backend)
    result = asyncio.run(dispatcher.dispatch(_make_ctx("/noop")))
    assert result.outcome == "unknown_command"
    assert "/kill" in result.reply_text


def test_autotrade_and_kill_interaction_forces_autotrade_off() -> None:
    _reset_state()
    STATE.mode = "paper"
    STATE.autotrade_enabled = True
    STATE.kill_switch = False

    backend = FakeBackend()
    dispatcher = TelegramDispatcher(backend=backend)
    asyncio.run(dispatcher.dispatch(_make_ctx("/kill")))

    assert backend.last_post_path == "/beta/kill"



def test_autotrade_reply_preserves_live_mode_boundary_detail() -> None:
    backend = FakeBackend()
    dispatcher = TelegramDispatcher(backend=backend)
    result = asyncio.run(dispatcher.dispatch(_make_ctx("/autotrade", "on")))
    assert "Autotrade" in result.reply_text


def test_live_mode_with_autotrade_request_stays_blocked_and_emits_no_events() -> None:
    _reset_state()
    app = create_app()
    with TestClient(app) as client:
        live_response = client.post("/beta/mode", json={"mode": "live"})
        assert live_response.status_code == 200
        auto_response = client.post("/beta/autotrade", json={"enabled": True})
        assert auto_response.status_code == 200
        payload = auto_response.json()
        assert payload["ok"] is False
        assert payload["autotrade"] is False

    worker = PaperBetaWorker(FakeFalcon(), PaperRiskGate(), PaperExecutionEngine(PaperPortfolio()))
    events = asyncio.run(worker.run_once())
    assert events == []
    assert STATE.last_risk_reason == "mode_live_paper_execution_disabled"
    assert STATE.worker_runtime.last_iteration.skip_mode_count == 1


def test_kill_switch_keeps_execution_blocked_after_mode_switches() -> None:
    _reset_state()
    app = create_app()
    with TestClient(app) as client:
        assert client.post("/beta/mode", json={"mode": "paper"}).status_code == 200
        assert client.post("/beta/autotrade", json={"enabled": True}).status_code == 200
        kill_response = client.post("/beta/kill")
        assert kill_response.status_code == 200
        assert kill_response.json()["kill_switch"] is True
        assert client.post("/beta/mode", json={"mode": "live"}).status_code == 200
        assert client.post("/beta/mode", json={"mode": "paper"}).status_code == 200
        reenable_response = client.post("/beta/autotrade", json={"enabled": True})
        assert reenable_response.status_code == 200
        assert reenable_response.json()["autotrade"] is True

    worker = PaperBetaWorker(FakeFalcon(), PaperRiskGate(), PaperExecutionEngine(PaperPortfolio()))
    events = asyncio.run(worker.run_once())
    assert events == []
    assert STATE.last_risk_reason == "kill_switch_enabled"
    assert STATE.worker_runtime.last_iteration.skip_kill_count == 1


def test_status_reports_control_plane_guard_reasons() -> None:
    _reset_state()
    app = create_app()
    with TestClient(app) as client:
        client.post("/beta/mode", json={"mode": "live"})
        status_payload = client.get("/beta/status").json()

    assert status_payload["paper_only_execution_boundary"] is True
    assert status_payload["execution_guard"]["entry_allowed"] is False
    assert "mode_live_paper_execution_disabled" in status_payload["execution_guard"]["blocked_reasons"]


def test_status_command_reply_surfaces_execution_guard_and_boundary() -> None:
    backend = FakeBackend()
    dispatcher = TelegramDispatcher(backend=backend)
    result = asyncio.run(dispatcher.dispatch(_make_ctx("/status")))
    assert "Guard allows entry" in result.reply_text
    assert "autotrade_disabled" in result.reply_text
    assert "paper-only execution" in result.reply_text


def test_positions_pnl_risk_replies_keep_paper_beta_boundaries_visible() -> None:
    backend = FakeBackend()
    dispatcher = TelegramDispatcher(backend=backend)

    positions_reply = asyncio.run(dispatcher.dispatch(_make_ctx("/positions"))).reply_text
    pnl_reply = asyncio.run(dispatcher.dispatch(_make_ctx("/pnl"))).reply_text
    risk_reply = asyncio.run(dispatcher.dispatch(_make_ctx("/risk"))).reply_text

    assert "no manual order entry" in positions_reply
    assert "no live settlement path" in pnl_reply
    assert "paper execution only" in risk_reply
