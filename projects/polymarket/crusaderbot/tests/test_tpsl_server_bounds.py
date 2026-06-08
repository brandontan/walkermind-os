"""WARP-90 / PR #1688 SENTINEL follow-up — server-side TP/SL bounds + NULL
fallback for the fast_topup / safe_close builder paths.

Two conditions closed here (both CONDITIONAL-PASS items from
``docs/sentinel/1688_retroactive_sentinel.md``):

A. Server-side validation of user-supplied tp_pct / sl_pct. Frontend hints are
   insufficient — any client can POST raw values straight to the API. The
   authoritative guard is a Pydantic ``field_validator`` on every write schema
   that accepts these fields, so an out-of-range present value raises a
   ``ValidationError`` (-> FastAPI 422) before the handler runs. None is allowed
   (means "use strategy default").

B. The NULL -> strategy-default fallback (already wired for normal mode in
   ``_build_trade_signal``) is extended to the two secondary builder paths:
   ``_maybe_fire_fast_topup`` and the stale-queue resume (safe_close) path. A
   NULL user_settings row must never emit a position with tp/sl = None.

Pure-unit: no DB, no network. The fast_topup path is driven through the public
helper; the resume path is pinned at source + via the shared resolver.
"""
from __future__ import annotations

import asyncio
import inspect
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot.domain.strategy import (
    StrategyRegistry,
    bootstrap_default_strategies,
)
from projects.polymarket.crusaderbot.domain.strategy.inventory import MarketInventory
from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as ssj
from projects.polymarket.crusaderbot.services.trade_engine import TradeResult
from projects.polymarket.crusaderbot.webtrader.backend.schemas import (
    MAX_SL_PCT,
    MAX_TP_PCT,
    AdminUserUpdate,
    CustomizeRequest,
    RiskProfileRequest,
)


_USER_UUID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
_MARKET_ID = "tpsl-bounds-market"


# ===========================================================================
# Part A — server-side bounds (Pydantic field validators → 422)
# ===========================================================================
#
# One assertion per invalid input. The three write schemas that accept tp/sl
# (CustomizeRequest, RiskProfileRequest, AdminUserUpdate) all share the same
# validators, so rejection holds regardless of which endpoint is hit.

_WRITE_SCHEMAS = (CustomizeRequest, AdminUserUpdate)


@pytest.mark.parametrize("schema", _WRITE_SCHEMAS)
def test_sl_pct_zero_rejected(schema) -> None:
    with pytest.raises(ValidationError):
        schema(sl_pct=0)


@pytest.mark.parametrize("schema", _WRITE_SCHEMAS)
def test_sl_pct_negative_rejected(schema) -> None:
    with pytest.raises(ValidationError):
        schema(sl_pct=-0.1)


@pytest.mark.parametrize("schema", _WRITE_SCHEMAS)
def test_sl_pct_over_max_rejected(schema) -> None:
    # 2.0 > MAX_SL_PCT (1.0)
    with pytest.raises(ValidationError):
        schema(sl_pct=2.0)


@pytest.mark.parametrize("schema", _WRITE_SCHEMAS)
def test_tp_pct_zero_rejected(schema) -> None:
    with pytest.raises(ValidationError):
        schema(tp_pct=0)


@pytest.mark.parametrize("schema", _WRITE_SCHEMAS)
def test_tp_pct_over_max_rejected(schema) -> None:
    # 999 > MAX_TP_PCT (10.0)
    with pytest.raises(ValidationError):
        schema(tp_pct=999)


def test_risk_profile_request_rejects_out_of_range() -> None:
    # The custom-risk-profile override write path — the exact path SENTINEL
    # flagged as having no server-side numeric bounds.
    with pytest.raises(ValidationError):
        RiskProfileRequest(profile="custom", sl_pct=0)
    with pytest.raises(ValidationError):
        RiskProfileRequest(profile="custom", tp_pct=999)


def test_none_is_allowed_means_strategy_default() -> None:
    # None must pass — it signals "use the strategy default" downstream.
    assert CustomizeRequest(tp_pct=None, sl_pct=None).tp_pct is None
    assert RiskProfileRequest(profile="balanced").sl_pct is None
    assert AdminUserUpdate(tp_pct=None).sl_pct is None


def test_in_range_values_pass() -> None:
    # The EV-validated 1.5 / 0.5 default + boundary values must construct.
    ok = CustomizeRequest(tp_pct=1.5, sl_pct=0.5)
    assert ok.tp_pct == pytest.approx(1.5)
    assert ok.sl_pct == pytest.approx(0.5)
    assert CustomizeRequest(tp_pct=MAX_TP_PCT, sl_pct=MAX_SL_PCT).tp_pct == MAX_TP_PCT


# ===========================================================================
# Part B — NULL → strategy-default fallback on the secondary builder paths
# ===========================================================================


@pytest.fixture(autouse=True)
def _isolated_state():
    StrategyRegistry._reset_for_tests()
    ssj._bankroll_reset_for_tests()
    ssj._fast_topup_reset_for_tests()
    crusaderbot_config.get_settings.cache_clear()
    yield
    StrategyRegistry._reset_for_tests()
    ssj._bankroll_reset_for_tests()
    ssj._fast_topup_reset_for_tests()
    crusaderbot_config.get_settings.cache_clear()


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")


def _row(*, tp_pct, sl_pct, active_preset: str = "safe_close") -> dict:
    return {
        "user_id": _USER_UUID,
        "telegram_user_id": 88,
        "role": "user",
        "auto_trade_on": True,
        "paused": False,
        "balance_usdc": 500.0,
        "tp_pct": tp_pct,
        "sl_pct": sl_pct,
        "daily_loss_override": None,
        "active_preset": active_preset,
        "resolved_profile": "balanced",
        "trading_mode": "paper",
        "live_capital_cap_usdc": 0.0,
    }


def _market() -> dict:
    return {
        "id": _MARKET_ID,
        "slug": "fast-topup-market",
        "question": "Will X happen?",
        "status": "active",
        "yes_price": 0.65,
        "no_price": 0.35,
        "yes_token_id": "tok_yes",
        "no_token_id": "tok_no",
        "liquidity_usdc": 20000.0,
    }


def _inv(yes_size: float, no_size: float) -> MarketInventory:
    return MarketInventory(
        user_id=str(_USER_UUID),
        market_id=_MARKET_ID,
        yes_size_usdc=Decimal(str(yes_size)),
        no_size_usdc=Decimal(str(no_size)),
        yes_count=1 if yes_size > 0 else 0,
        no_count=1 if no_size > 0 else 0,
    )


def _approved_result() -> TradeResult:
    return TradeResult(
        approved=True,
        mode="paper",
        order_id=uuid4(),
        position_id=uuid4(),
        rejection_reason=None,
        failed_gate_step=None,
        chosen_mode="paper",
        final_size_usdc=Decimal("5"),
    )


def _drive_fast_topup(*, row: dict) -> object:
    """Run ``_maybe_fire_fast_topup`` with mocked deps; return the engine
    signal (or None if not fired). Inventory is YES-heavy so a NO top-up fires.
    """
    captured: dict = {"signal": None}

    async def _fake_execute(signal):
        captured["signal"] = signal
        return _approved_result()

    async def _fake_inv(uid, mid):
        return _inv(20.0, 5.0)

    class _Log:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass

    with patch.object(
        ssj, "_fetch_market_inventory_for_override",
        new=AsyncMock(side_effect=_fake_inv),
    ), patch.object(
        ssj, "get_live_market_price", new=AsyncMock(return_value=0.34),
    ), patch.object(
        ssj._engine, "execute", side_effect=_fake_execute,
    ):
        asyncio.run(
            ssj._maybe_fire_fast_topup(
                row=row, market=_market(),
                just_filled_side="yes",
                just_filled_size_usdc=Decimal("10"),
                log=_Log(),
            )
        )
    return captured["signal"]


def test_fast_topup_null_tp_pct_uses_strategy_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fast_topup with NULL tp_pct must fall back to default[0] (the active
    strategy's default_tp_sl take-profit), NOT emit None."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "true")
    monkeypatch.setenv("FAST_TOPUP_MIN_USDC", "5.0")
    bootstrap_default_strategies()

    expected_tp, expected_sl = ssj._strategy_default_tp_sl(ssj._LATE_ENTRY_V3_NAME)
    sig = _drive_fast_topup(row=_row(tp_pct=None, sl_pct=0.08))
    assert sig is not None
    assert sig.tp_pct is not None
    assert sig.tp_pct == pytest.approx(expected_tp)
    # The unset side falls back; the present side is honoured literally.
    assert sig.sl_pct == pytest.approx(0.08)
    # Default[0] is the EV-validated 1.5 baseline for late_entry_v3.
    assert sig.tp_pct == pytest.approx(1.5)


def test_fast_topup_null_both_uses_strategy_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fast_topup with both NULL must emit the full strategy default pair."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "true")
    monkeypatch.setenv("FAST_TOPUP_MIN_USDC", "5.0")
    bootstrap_default_strategies()

    expected_tp, expected_sl = ssj._strategy_default_tp_sl(ssj._LATE_ENTRY_V3_NAME)
    sig = _drive_fast_topup(row=_row(tp_pct=None, sl_pct=None))
    assert sig is not None
    assert sig.tp_pct == pytest.approx(expected_tp)
    assert sig.sl_pct == pytest.approx(expected_sl)
    assert (sig.tp_pct, sig.sl_pct) == pytest.approx((1.5, 0.5))


def test_fast_topup_present_value_honoured_literally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-NULL user value must pass through untouched (no clobber by the
    fallback)."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "true")
    monkeypatch.setenv("FAST_TOPUP_MIN_USDC", "5.0")
    bootstrap_default_strategies()

    sig = _drive_fast_topup(row=_row(tp_pct=0.20, sl_pct=0.08))
    assert sig is not None
    assert sig.tp_pct == pytest.approx(0.20)
    assert sig.sl_pct == pytest.approx(0.08)


def test_safe_close_resume_null_sl_pct_uses_strategy_default() -> None:
    """The stale-queue resume path (covers safe_close) must resolve a NULL
    sl_pct to default[1] from the executed strategy, never pass None.

    The resume block is buried inside the scan-job entry coroutine and is not
    independently callable, so we pin it two ways: (1) source — the block
    references the shared ``_strategy_default_tp_sl`` resolver and the logged
    fallback marker; (2) the resolver itself returns a real (non-None) default
    pair for the executed strategy (_STRATEGY_NAME), so default[1] is a usable
    stop-loss.
    """
    bootstrap_default_strategies()

    src = inspect.getsource(ssj)
    # The resume block resolves via the same mechanism normal mode uses, and
    # tags its logged fallback with the safe_close_resume mode marker.
    assert "_stale_default_tp_pct, _stale_default_sl_pct = _strategy_default_tp_sl(" in src
    assert "_STRATEGY_NAME" in src
    assert 'mode="safe_close_resume"' in src
    assert "user_settings_sl_pct_missing_defensive_fallback" in src

    default_tp, default_sl = ssj._strategy_default_tp_sl(ssj._STRATEGY_NAME)
    assert default_tp is not None and default_tp > 0
    assert default_sl is not None and default_sl > 0
    # default[1] is the EV-validated 0.5 stop-loss baseline.
    assert default_sl == pytest.approx(0.5)


def test_resume_path_no_longer_passes_none_on_null_row() -> None:
    """Regression pin: the resume block must NOT contain the old bare
    None-passthrough for tp/sl (``... else None``) that #1688 left in place."""
    src = inspect.getsource(ssj)
    assert (
        '_tp = float(row["tp_pct"]) if row.get("tp_pct") is not None else None'
        not in src
    )
    assert (
        '_sl = float(row["sl_pct"]) if row.get("sl_pct") is not None else None'
        not in src
    )
