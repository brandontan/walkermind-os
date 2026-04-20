from __future__ import annotations

import asyncio

import pytest

from projects.polymarket.polyquantbot.client.telegram.dispatcher import TelegramCommandContext, TelegramDispatcher
from projects.polymarket.polyquantbot.client.telegram.runtime import TelegramInboundUpdate, TelegramPollingLoop, TelegramRuntimeAdapter
from projects.polymarket.polyquantbot.server.core.public_beta_state import STATE

pytest.importorskip(
    "fastapi",
    reason="fastapi dependency is required for Phase 8.9 runtime-surface validation evidence.",
)
from fastapi.testclient import TestClient

from projects.polymarket.polyquantbot.server.main import create_app


class FakeBackend:
    async def request_handoff(self, request):
        class _Result:
            outcome = "issued"
            session_id = "sess-1"
            detail = ""

        return _Result()

    async def beta_get(self, path: str, params=None):
        if path == "/beta/status":
            return {
                "mode": "paper",
                "autotrade": False,
                "kill_switch": False,
                "position_count": 0,
                "last_risk_reason": "autotrade_disabled",
                "managed_beta_state": {"state": "managed"},
                "execution_guard": {
                    "entry_allowed": False,
                    "blocked_reasons": ["autotrade_disabled"],
                },
            }
        return {}

    async def beta_post(self, path: str, payload: dict[str, object]):
        return {"ok": True}


class _Adapter(TelegramRuntimeAdapter):
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def get_updates(self, offset: int = 0, limit: int = 100) -> list[TelegramInboundUpdate]:
        return [
            TelegramInboundUpdate(
                update_id=offset + 1,
                chat_id="chat-1",
                from_user_id="tg-404",
                text="/status",
            )
        ]

    async def send_reply(self, chat_id: str, text: str) -> None:
        self.replies.append(text)


class _IdentityNotFoundResolver:
    async def resolve_telegram_identity(self, telegram_user_id: str):
        class _Resolution:
            outcome = "not_found"
            tenant_id = None
            user_id = None

        return _Resolution()


def _reset_state() -> None:
    STATE.mode = "paper"
    STATE.autotrade_enabled = False
    STATE.kill_switch = False
    STATE.last_risk_reason = ""
    STATE.positions.clear()


def test_beta_status_payload_exposes_operator_interpretation_contract() -> None:
    _reset_state()
    app = create_app()
    with TestClient(app) as client:
        payload = client.get("/beta/status").json()

    assert payload["paper_only_execution_boundary"] is True
    assert payload["execution_guard"]["reason_count"] >= 1
    assert payload["readiness_interpretation"]["control_surface"] == "telegram_and_api_control_only"
    assert payload["readiness_interpretation"]["execution_authority"] == "paper_only"
    assert payload["readiness_interpretation"]["live_trading_ready"] is False


def test_status_command_text_keeps_public_beta_boundary_truth() -> None:
    backend = FakeBackend()
    dispatcher = TelegramDispatcher(backend=backend)
    ctx = TelegramCommandContext(
        command="/status",
        from_user_id="tg-1",
        chat_id="chat-1",
        tenant_id="tenant-1",
        user_id="user-1",
    )

    result = asyncio.run(dispatcher.dispatch(ctx))

    assert "public paper beta" in result.reply_text
    assert "Guard reasons" in result.reply_text
    assert "Managed beta state" in result.reply_text
    assert "no manual trade-entry commands" not in result.reply_text
    assert "paper-only execution" in result.reply_text


def test_not_registered_runtime_reply_mentions_control_only_boundary() -> None:
    adapter = _Adapter()
    backend = FakeBackend()
    dispatcher = TelegramDispatcher(backend=backend)
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=_IdentityNotFoundResolver(),
    )

    processed = asyncio.run(loop.run_once())

    assert processed == 1
    assert len(adapter.replies) == 1
    assert "control/read commands only after onboarding" in adapter.replies[0]
    assert "manual trade-entry is unavailable" in adapter.replies[0]
