"""WARP-74 Chunk C (GAP #5) — router must distinguish an INFRA-DEGRADED
live->paper fallback (CLOB dependency failed) from a DELIBERATE one (guard off),
so a live operator is never silently downgraded to paper.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.domain.execution import router
from projects.polymarket.crusaderbot.domain.execution.live import LivePreSubmitError

pytestmark = pytest.mark.asyncio

_AUDIT = "projects.polymarket.crusaderbot.audit.write"
_NOTIFY = "projects.polymarket.crusaderbot.notifications.notify_operator"


# --- pure classifier ----------------------------------------------------------
async def test_infra_fragments_classified() -> None:
    assert router._is_infra_degraded(
        "CLOB market metadata unavailable — refusing entry (token=x): boom")
    assert router._is_infra_degraded("CLOB client config error: missing key")
    assert router._is_infra_degraded("idempotency precheck failed: db down")
    assert router._is_infra_degraded(
        "USE_REAL_CLOB must be True when ENABLE_LIVE_TRADING is set")


async def test_deliberate_reasons_not_infra() -> None:
    assert not router._is_infra_degraded("ENABLE_LIVE_TRADING=false")
    assert not router._is_infra_degraded("role='user' not admin")
    assert not router._is_infra_degraded("user trading_mode=paper")
    assert not router._is_infra_degraded("")


# --- router integration -------------------------------------------------------
_KW: dict[str, Any] = dict(
    chosen_mode="live", user_id=uuid4(), telegram_user_id=1, role="admin",
    market_id="m1", market_question="q", yes_token_id="ty", no_token_id="tn",
    side="yes", size_usdc=Decimal("10"), price=0.5, idempotency_key="k1",
    strategy_type="late_entry_v3", tp_pct=None, sl_pct=None, trading_mode="live",
)


@pytest.fixture
def _wire(monkeypatch):
    rec = {"audit": [], "notify": []}

    async def _audit(**kw):
        rec["audit"].append(kw)

    async def _notify(text, *_a, **_k):
        rec["notify"].append(text)

    async def _paper(**_kw):
        return {"mode": "paper", "_paper": True}

    monkeypatch.setattr(_AUDIT, _audit)
    monkeypatch.setattr(_NOTIFY, _notify)
    monkeypatch.setattr(router.paper_engine, "execute", _paper)
    monkeypatch.setattr(router.live_engine, "assert_live_guards",
                        lambda role, mode: None)
    return rec


async def test_infra_degraded_audits_distinctly_and_pages(monkeypatch, _wire) -> None:
    async def _raise(**_kw):
        raise LivePreSubmitError(
            "CLOB market metadata unavailable — refusing entry (token=ty): boom")
    monkeypatch.setattr(router.live_engine, "execute", _raise)

    res = await router.execute(**_KW)
    assert res.get("_paper") is True  # still falls back to paper
    actions = [a["action"] for a in _wire["audit"]]
    assert "live_infra_degraded_paper_fallback" in actions
    assert "live_blocked_fallback_paper" not in actions
    assert _wire["notify"], "infra-degraded must page the operator"


async def test_deliberate_fallback_uses_normal_audit(monkeypatch, _wire) -> None:
    async def _raise(**_kw):
        raise LivePreSubmitError("user trading_mode=paper")
    monkeypatch.setattr(router.live_engine, "execute", _raise)

    res = await router.execute(**_KW)
    assert res.get("_paper") is True
    actions = [a["action"] for a in _wire["audit"]]
    assert "live_blocked_fallback_paper" in actions
    assert "live_infra_degraded_paper_fallback" not in actions
