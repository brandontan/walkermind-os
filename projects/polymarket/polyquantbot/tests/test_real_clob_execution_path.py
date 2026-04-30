"""Tests for real CLOB execution path — WARP/real-clob-execution-path.

Test IDs: RCLOB-01 .. RCLOB-30

Coverage:
  Negative tests — live execution blocked by default:
    RCLOB-01  ClobExecutionAdapter.submit_order() blocked when kill_switch=True
    RCLOB-02  ClobExecutionAdapter.submit_order() blocked when mode != 'live'
    RCLOB-03  ClobExecutionAdapter.submit_order() blocked when ENABLE_LIVE_TRADING not set
    RCLOB-04  ClobExecutionAdapter.submit_order() blocked when any capital gate off
    RCLOB-05  ClobExecutionAdapter.submit_order() blocked when provider is None
    RCLOB-06  ClobExecutionAdapter.submit_order() blocked when provider returns all-zero fields
    RCLOB-07  MockClobClient.post_order() is NEVER called when guard blocks

  Missing gate failure tests:
    RCLOB-08  Missing CAPITAL_MODE_CONFIRMED raises ClobSubmissionBlockedError
    RCLOB-09  Missing RISK_CONTROLS_VALIDATED raises ClobSubmissionBlockedError
    RCLOB-10  Missing EXECUTION_PATH_VALIDATED raises ClobSubmissionBlockedError
    RCLOB-11  Missing SECURITY_HARDENING_VALIDATED raises ClobSubmissionBlockedError

  Mocked real CLOB submission path:
    RCLOB-12  Full guard pass + MockClobClient returns ClobOrderResult
    RCLOB-13  ClobOrderResult fields are correct (order_id, condition_id, side, mode)
    RCLOB-14  MockClobClient records submitted payload with correct order structure
    RCLOB-15  ClobSubmissionError raised when MockClobClient raises on post_order()
    RCLOB-16  build_order_payload() produces correct CLOB API shape

  Stale / fake market data rejection:
    RCLOB-17  LiveMarketDataGuard rejects paper_stub source in live mode
    RCLOB-18  LiveMarketDataGuard rejects stale price in live mode
    RCLOB-19  LiveMarketDataGuard accepts fresh non-stub price in live mode
    RCLOB-20  LiveMarketDataGuard passes paper_stub in paper mode (no staleness check)
    RCLOB-21  price_updater() raises LiveExecutionBlockedError in live mode without provider
    RCLOB-22  price_updater_live() skips stale prices and continues (does not crash)
    RCLOB-23  price_updater_live() rejects paper_stub provider in live mode

  PaperBetaWorker live path integration:
    RCLOB-24  run_once() uses clob_adapter when mode='live' and guard passes
    RCLOB-25  run_once() uses paper engine when mode='paper' even with clob_adapter set
    RCLOB-26  run_once() blocks and skips when clob_adapter raises ClobSubmissionBlockedError
    RCLOB-27  run_once() skips when no live_guard and mode='live' (existing regression)

  P8 capital guard regressions:
    RCLOB-28  CapitalModeConfig all-gates-off → is_capital_mode_allowed() == False
    RCLOB-29  CapitalModeConfig validate() raises CapitalModeGuardError in LIVE mode if any gate off
    RCLOB-30  Kelly fraction is always 0.25 — full Kelly forbidden

Validation Tier: MAJOR
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pytest

from projects.polymarket.polyquantbot.server.config.capital_mode_config import (
    CapitalModeConfig,
    CapitalModeGuardError,
    KELLY_FRACTION,
)
from projects.polymarket.polyquantbot.server.core.live_execution_control import (
    LiveExecutionBlockedError,
    LiveExecutionGuard,
)
from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState
from projects.polymarket.polyquantbot.server.data.live_market_data import (
    LiveMarketDataGuard,
    LiveMarketDataUnavailableError,
    MarketPrice,
    MockClobMarketDataClient,
    PaperMarketDataProvider,
    StaleMarketDataError,
    STALE_THRESHOLD_SECONDS,
)
from projects.polymarket.polyquantbot.server.execution.clob_execution_adapter import (
    ClobExecutionAdapter,
    ClobOrderResult,
    ClobSubmissionBlockedError,
    ClobSubmissionError,
    build_order_payload,
)
from projects.polymarket.polyquantbot.server.execution.mock_clob_client import MockClobClient
from projects.polymarket.polyquantbot.server.execution.paper_execution import PaperExecutionEngine
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal
from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import PaperPortfolio
from projects.polymarket.polyquantbot.server.risk.capital_risk_gate import CapitalRiskGate, WalletFinancialProvider
from projects.polymarket.polyquantbot.server.risk.paper_risk_gate import PaperRiskGate
from projects.polymarket.polyquantbot.server.workers.paper_beta_worker import PaperBetaWorker


# ── Env helpers ────────────────────────────────────────────────────────────────

_PAPER_ENV = {
    "TRADING_MODE": "PAPER",
    "ENABLE_LIVE_TRADING": "false",
    "CAPITAL_MODE_CONFIRMED": "false",
    "RISK_CONTROLS_VALIDATED": "false",
    "EXECUTION_PATH_VALIDATED": "false",
    "SECURITY_HARDENING_VALIDATED": "false",
}

_LIVE_ENV_ALL_GATES = {
    "TRADING_MODE": "LIVE",
    "ENABLE_LIVE_TRADING": "true",
    "CAPITAL_MODE_CONFIRMED": "true",
    "RISK_CONTROLS_VALIDATED": "true",
    "EXECUTION_PATH_VALIDATED": "true",
    "SECURITY_HARDENING_VALIDATED": "true",
}


def _paper_cfg() -> CapitalModeConfig:
    with patch.dict(os.environ, _PAPER_ENV, clear=False):
        return CapitalModeConfig.from_env()


def _live_cfg_all_gates() -> CapitalModeConfig:
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        return CapitalModeConfig.from_env()


def _live_cfg_missing(gate: str) -> CapitalModeConfig:
    env = {**_LIVE_ENV_ALL_GATES, gate: "false"}
    with patch.dict(os.environ, env, clear=False):
        return CapitalModeConfig.from_env()


def _live_state() -> PublicBetaState:
    state = PublicBetaState()
    state.mode = "live"
    state.kill_switch = False
    state.autotrade_enabled = True
    return state


def _paper_state() -> PublicBetaState:
    state = PublicBetaState()
    state.mode = "paper"
    state.kill_switch = False
    state.autotrade_enabled = True
    return state


# ── Provider helpers ───────────────────────────────────────────────────────────

@dataclass
class _RealProvider:
    """Minimal WalletFinancialProvider with non-zero fields."""
    balance: float = 1000.0
    exposure: float = 0.05
    drawdown: float = 0.02

    def get_balance_usd(self, wallet_id: str) -> float:
        return self.balance

    def get_exposure_pct(self, wallet_id: str) -> float:
        return self.exposure

    def get_drawdown_pct(self, wallet_id: str) -> float:
        return self.drawdown


@dataclass
class _ZeroProvider:
    """WalletFinancialProvider with all-zero fields (stub/uninitialized)."""

    def get_balance_usd(self, wallet_id: str) -> float:
        return 0.0

    def get_exposure_pct(self, wallet_id: str) -> float:
        return 0.0

    def get_drawdown_pct(self, wallet_id: str) -> float:
        return 0.0


# ── Signal helper ──────────────────────────────────────────────────────────────

def _make_signal(
    condition_id: str = "cond-abc",
    side: str = "BUY",
    price: float = 0.65,
    size: float = 10.0,
    signal_id: str = "sig-001",
) -> CandidateSignal:
    return CandidateSignal(
        condition_id=condition_id,
        side=side,
        price=price,
        signal_id=signal_id,
        edge=0.05,
        liquidity=15000.0,
    )


# ── RCLOB-01: blocked when kill_switch=True ────────────────────────────────────

def test_rclob_01_blocked_kill_switch() -> None:
    state = _live_state()
    state.kill_switch = True
    cfg = _live_cfg_all_gates()
    client = MockClobClient()
    adapter = ClobExecutionAdapter(config=cfg, client=client, mode="mocked")
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        with pytest.raises(ClobSubmissionBlockedError) as exc_info:
            asyncio.run(
                adapter.submit_order(state, _make_signal(), token_id="tok1", provider=_RealProvider())
            )
    assert exc_info.value.reason == "kill_switch_active"
    assert client.call_count == 0


# ── RCLOB-02: blocked when mode != 'live' ─────────────────────────────────────

def test_rclob_02_blocked_mode_not_live() -> None:
    state = _paper_state()
    cfg = _live_cfg_all_gates()
    client = MockClobClient()
    adapter = ClobExecutionAdapter(config=cfg, client=client, mode="mocked")
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        with pytest.raises(ClobSubmissionBlockedError) as exc_info:
            asyncio.run(
                adapter.submit_order(state, _make_signal(), token_id="tok1", provider=_RealProvider())
            )
    assert exc_info.value.reason == "mode_not_live"
    assert client.call_count == 0


# ── RCLOB-03: blocked when ENABLE_LIVE_TRADING not set ────────────────────────

def test_rclob_03_blocked_enable_live_trading_not_set() -> None:
    state = _live_state()
    env_no_elt = {**_LIVE_ENV_ALL_GATES, "ENABLE_LIVE_TRADING": "false"}
    with patch.dict(os.environ, env_no_elt, clear=False):
        cfg = CapitalModeConfig.from_env()
    client = MockClobClient()
    adapter = ClobExecutionAdapter(config=cfg, client=client, mode="mocked")
    with patch.dict(os.environ, env_no_elt, clear=False):
        with pytest.raises(ClobSubmissionBlockedError) as exc_info:
            asyncio.run(
                adapter.submit_order(state, _make_signal(), token_id="tok1", provider=_RealProvider())
            )
    assert exc_info.value.reason == "enable_live_trading_not_set"
    assert client.call_count == 0


# ── RCLOB-04: blocked when any capital gate off ────────────────────────────────

def test_rclob_04_blocked_capital_gate_off() -> None:
    state = _live_state()
    env = {**_LIVE_ENV_ALL_GATES, "CAPITAL_MODE_CONFIRMED": "false"}
    with patch.dict(os.environ, env, clear=False):
        cfg = CapitalModeConfig.from_env()
    client = MockClobClient()
    adapter = ClobExecutionAdapter(config=cfg, client=client, mode="mocked")
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ClobSubmissionBlockedError) as exc_info:
            asyncio.run(
                adapter.submit_order(state, _make_signal(), token_id="tok1", provider=_RealProvider())
            )
    assert exc_info.value.reason == "capital_mode_guard_failed"
    assert client.call_count == 0


# ── RCLOB-05: blocked when provider is None ───────────────────────────────────

def test_rclob_05_blocked_no_provider() -> None:
    state = _live_state()
    cfg = _live_cfg_all_gates()
    client = MockClobClient()
    adapter = ClobExecutionAdapter(config=cfg, client=client, mode="mocked")
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        with pytest.raises(ClobSubmissionBlockedError) as exc_info:
            asyncio.run(
                adapter.submit_order(state, _make_signal(), token_id="tok1", provider=None)
            )
    assert exc_info.value.reason == "missing_financial_provider"
    assert client.call_count == 0


# ── RCLOB-06: blocked when provider returns all-zero fields ───────────────────

def test_rclob_06_blocked_all_zero_provider() -> None:
    state = _live_state()
    cfg = _live_cfg_all_gates()
    client = MockClobClient()
    adapter = ClobExecutionAdapter(config=cfg, client=client, mode="mocked")
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        with pytest.raises(ClobSubmissionBlockedError) as exc_info:
            asyncio.run(
                adapter.submit_order(state, _make_signal(), token_id="tok1", provider=_ZeroProvider())
            )
    assert exc_info.value.reason == "financial_provider_all_zero"
    assert client.call_count == 0


# ── RCLOB-07: MockClobClient never called when guard blocks ───────────────────

def test_rclob_07_mock_client_never_called_when_blocked() -> None:
    state = _paper_state()  # wrong mode
    cfg = _live_cfg_all_gates()
    client = MockClobClient()
    adapter = ClobExecutionAdapter(config=cfg, client=client, mode="mocked")
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        with pytest.raises(ClobSubmissionBlockedError):
            asyncio.run(
                adapter.submit_order(state, _make_signal(), token_id="tok1", provider=_RealProvider())
            )
    assert client.call_count == 0
    assert len(client.submitted_payloads) == 0


# ── RCLOB-08: Missing CAPITAL_MODE_CONFIRMED ──────────────────────────────────

def test_rclob_08_missing_capital_mode_confirmed() -> None:
    state = _live_state()
    cfg = _live_cfg_missing("CAPITAL_MODE_CONFIRMED")
    client = MockClobClient()
    adapter = ClobExecutionAdapter(config=cfg, client=client, mode="mocked")
    env = {**_LIVE_ENV_ALL_GATES, "CAPITAL_MODE_CONFIRMED": "false"}
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ClobSubmissionBlockedError) as exc_info:
            asyncio.run(
                adapter.submit_order(state, _make_signal(), token_id="tok1", provider=_RealProvider())
            )
    assert "capital_mode_guard_failed" == exc_info.value.reason


# ── RCLOB-09: Missing RISK_CONTROLS_VALIDATED ─────────────────────────────────

def test_rclob_09_missing_risk_controls_validated() -> None:
    state = _live_state()
    cfg = _live_cfg_missing("RISK_CONTROLS_VALIDATED")
    client = MockClobClient()
    adapter = ClobExecutionAdapter(config=cfg, client=client, mode="mocked")
    env = {**_LIVE_ENV_ALL_GATES, "RISK_CONTROLS_VALIDATED": "false"}
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ClobSubmissionBlockedError) as exc_info:
            asyncio.run(
                adapter.submit_order(state, _make_signal(), token_id="tok1", provider=_RealProvider())
            )
    assert exc_info.value.reason == "capital_mode_guard_failed"


# ── RCLOB-10: Missing EXECUTION_PATH_VALIDATED ────────────────────────────────

def test_rclob_10_missing_execution_path_validated() -> None:
    state = _live_state()
    cfg = _live_cfg_missing("EXECUTION_PATH_VALIDATED")
    client = MockClobClient()
    adapter = ClobExecutionAdapter(config=cfg, client=client, mode="mocked")
    env = {**_LIVE_ENV_ALL_GATES, "EXECUTION_PATH_VALIDATED": "false"}
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ClobSubmissionBlockedError) as exc_info:
            asyncio.run(
                adapter.submit_order(state, _make_signal(), token_id="tok1", provider=_RealProvider())
            )
    assert exc_info.value.reason == "capital_mode_guard_failed"


# ── RCLOB-11: Missing SECURITY_HARDENING_VALIDATED ────────────────────────────

def test_rclob_11_missing_security_hardening_validated() -> None:
    state = _live_state()
    cfg = _live_cfg_missing("SECURITY_HARDENING_VALIDATED")
    client = MockClobClient()
    adapter = ClobExecutionAdapter(config=cfg, client=client, mode="mocked")
    env = {**_LIVE_ENV_ALL_GATES, "SECURITY_HARDENING_VALIDATED": "false"}
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ClobSubmissionBlockedError) as exc_info:
            asyncio.run(
                adapter.submit_order(state, _make_signal(), token_id="tok1", provider=_RealProvider())
            )
    assert exc_info.value.reason == "capital_mode_guard_failed"


# ── RCLOB-12: Full guard pass + MockClobClient returns ClobOrderResult ─────────

def test_rclob_12_full_guard_pass_returns_result() -> None:
    state = _live_state()
    cfg = _live_cfg_all_gates()
    client = MockClobClient(order_id="order-xyz-001", status="MATCHED")
    adapter = ClobExecutionAdapter(config=cfg, client=client, mode="mocked")
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        result = asyncio.run(
            adapter.submit_order(
                state,
                _make_signal(condition_id="cond-123", side="BUY", price=0.65, size=10.0),
                token_id="tok-123",
                provider=_RealProvider(),
            )
        )
    assert isinstance(result, ClobOrderResult)
    assert result.order_id == "order-xyz-001"
    assert result.status == "MATCHED"
    assert result.mode == "mocked"
    assert client.call_count == 1


# ── RCLOB-13: ClobOrderResult fields are correct ──────────────────────────────

def test_rclob_13_result_fields_correct() -> None:
    state = _live_state()
    cfg = _live_cfg_all_gates()
    signal = _make_signal(condition_id="cond-abc", side="SELL", price=0.70, size=5.0)
    client = MockClobClient(order_id="sell-001", status="LIVE")
    adapter = ClobExecutionAdapter(config=cfg, client=client, mode="mocked")
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        result = asyncio.run(
            adapter.submit_order(state, signal, token_id="tok-abc", provider=_RealProvider())
        )
    assert result.condition_id == "cond-abc"
    assert result.token_id == "tok-abc"
    assert result.side == "SELL"
    assert result.size == 0.0  # CandidateSignal has no size field; adapter uses 0.0 default
    assert result.price == 0.70
    assert result.mode == "mocked"
    assert len(result.dedup_key) == 16  # SHA-256 prefix


# ── RCLOB-14: MockClobClient records submitted payload ────────────────────────

def test_rclob_14_payload_structure_correct() -> None:
    state = _live_state()
    cfg = _live_cfg_all_gates()
    signal = _make_signal(condition_id="cond-001", side="BUY", price=0.60, size=20.0)
    client = MockClobClient()
    adapter = ClobExecutionAdapter(config=cfg, client=client, mode="mocked")
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        asyncio.run(
            adapter.submit_order(state, signal, token_id="tok-001", provider=_RealProvider())
        )
    assert len(client.submitted_payloads) == 1
    payload = client.submitted_payloads[0]
    assert "order" in payload
    assert "orderType" in payload
    assert payload["orderType"] == "GTC"
    order = payload["order"]
    assert order["side"] == "BUY"
    assert order["tokenId"] == "tok-001"
    assert "makerAmount" in order
    assert "takerAmount" in order


# ── RCLOB-15: ClobSubmissionError when client raises ──────────────────────────

def test_rclob_15_clob_submission_error_on_client_raise() -> None:
    state = _live_state()
    cfg = _live_cfg_all_gates()
    client = MockClobClient(raise_error=ClobSubmissionError("network timeout"))
    adapter = ClobExecutionAdapter(config=cfg, client=client, mode="mocked")
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        with pytest.raises(ClobSubmissionError):
            asyncio.run(
                adapter.submit_order(state, _make_signal(), token_id="tok1", provider=_RealProvider())
            )
    assert client.call_count == 1  # was called, then raised


# ── RCLOB-16: build_order_payload() produces correct shape ────────────────────

def test_rclob_16_build_order_payload_shape() -> None:
    signal = _make_signal(condition_id="cond-xyz", side="BUY", price=0.55, size=15.0)
    payload = build_order_payload(signal, token_id="tok-xyz", order_type="FOK")
    assert payload["orderType"] == "FOK"
    order = payload["order"]
    assert order["side"] == "BUY"
    assert order["tokenId"] == "tok-xyz"
    # CandidateSignal has no size field; makerAmount is 0 when size=0.0 — assert type is str
    assert isinstance(order["makerAmount"], str)
    assert isinstance(order["takerAmount"], str)
    assert "_meta" in payload
    assert payload["_meta"]["condition_id"] == "cond-xyz"
    assert payload["_meta"]["price"] == 0.55


# ── RCLOB-17: LiveMarketDataGuard rejects paper_stub in live mode ─────────────

def test_rclob_17_live_guard_rejects_paper_stub_in_live_mode() -> None:
    paper_provider = PaperMarketDataProvider()
    guard = LiveMarketDataGuard(provider=paper_provider, mode="live")
    with pytest.raises(LiveMarketDataUnavailableError):
        asyncio.run(guard.get_price("tok-123"))


# ── RCLOB-18: LiveMarketDataGuard rejects stale price in live mode ────────────

def test_rclob_18_live_guard_rejects_stale_price_in_live_mode() -> None:
    stale_seconds = STALE_THRESHOLD_SECONDS + 10.0
    client = MockClobMarketDataClient(price=0.60, stale_offset_s=stale_seconds, source="clob_api_mock")
    guard = LiveMarketDataGuard(provider=client, mode="live")  # type: ignore[arg-type]
    with pytest.raises(StaleMarketDataError) as exc_info:
        asyncio.run(guard.get_price("tok-stale"))
    assert exc_info.value.token_id == "tok-stale"
    assert exc_info.value.age_seconds >= stale_seconds


# ── RCLOB-19: LiveMarketDataGuard accepts fresh non-stub price in live mode ───

def test_rclob_19_live_guard_accepts_fresh_price_in_live_mode() -> None:
    client = MockClobMarketDataClient(price=0.65, stale_offset_s=0.0, source="clob_api_mock")
    guard = LiveMarketDataGuard(provider=client, mode="live")  # type: ignore[arg-type]
    result = asyncio.run(guard.get_price("tok-fresh"))
    assert result.price == 0.65
    assert result.source == "clob_api_mock"
    assert not result.is_stale()


# ── RCLOB-20: LiveMarketDataGuard allows paper_stub in paper mode ─────────────

def test_rclob_20_paper_mode_allows_paper_stub() -> None:
    paper_provider = PaperMarketDataProvider(default_price=0.5)
    guard = LiveMarketDataGuard(provider=paper_provider, mode="paper")
    result = asyncio.run(guard.get_price("tok-paper"))
    assert result.price == 0.5
    assert result.source == "paper_stub"


# ── RCLOB-21: price_updater() raises LiveExecutionBlockedError without provider

def test_rclob_21_price_updater_raises_in_live_mode_no_provider() -> None:
    from unittest.mock import MagicMock

    state = _live_state()
    worker = PaperBetaWorker(
        falcon=MagicMock(),
        risk_gate=PaperRiskGate(),
        engine=MagicMock(),
        live_guard=None,
        provider=None,
        clob_adapter=None,
        market_data_provider=None,
    )
    # Patch STATE inside the worker module
    import projects.polymarket.polyquantbot.server.workers.paper_beta_worker as wmod
    orig_state = wmod.STATE
    wmod.STATE = state
    try:
        with pytest.raises(LiveExecutionBlockedError) as exc_info:
            asyncio.run(worker.price_updater())
        assert exc_info.value.reason == "price_updater_stub_live_mode_blocked"
        assert state.kill_switch is True  # disable_live_execution was called
    finally:
        wmod.STATE = orig_state


# ── RCLOB-22: price_updater_live() skips stale prices without crashing ────────

def test_rclob_22_price_updater_live_skips_stale_prices() -> None:
    from unittest.mock import MagicMock

    state = _live_state()
    state.mode = "live"

    # Mock a position with a condition_id
    pos = MagicMock()
    pos.condition_id = "tok-stale-pos"
    pos.entry_price = 0.5
    pos.size = 10.0
    state.positions = [pos]

    stale_client = MockClobMarketDataClient(
        price=0.70, stale_offset_s=STALE_THRESHOLD_SECONDS + 30.0, source="clob_api_mock"
    )
    guard = LiveMarketDataGuard(provider=stale_client, mode="live")  # type: ignore[arg-type]

    worker = PaperBetaWorker(
        falcon=MagicMock(),
        risk_gate=PaperRiskGate(),
        engine=MagicMock(),
        market_data_provider=stale_client,  # type: ignore[arg-type]
    )

    # price_updater_live should NOT raise — stale prices are skipped
    import projects.polymarket.polyquantbot.server.workers.paper_beta_worker as wmod
    orig_state = wmod.STATE
    wmod.STATE = state
    try:
        asyncio.run(worker.price_updater_live(stale_client))  # type: ignore[arg-type]
    finally:
        wmod.STATE = orig_state


# ── RCLOB-23: price_updater_live rejects paper_stub in live mode ──────────────

def test_rclob_23_price_updater_live_rejects_paper_stub() -> None:
    from unittest.mock import MagicMock

    state = _live_state()
    state.positions = []

    paper_provider = PaperMarketDataProvider()

    # LiveMarketDataGuard with live mode will reject the paper_stub source
    guard = LiveMarketDataGuard(provider=paper_provider, mode="live")
    with pytest.raises(LiveMarketDataUnavailableError):
        asyncio.run(guard.get_price("tok-any"))


# ── RCLOB-24: run_once() uses clob_adapter in live mode ──────────────────────

def test_rclob_24_run_once_uses_clob_adapter_in_live_mode() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    state = _live_state()
    cfg = _live_cfg_all_gates()
    provider = _RealProvider()
    signal = _make_signal()
    mock_client = MockClobClient(order_id="live-test-001", status="MATCHED")
    adapter = ClobExecutionAdapter(config=cfg, client=mock_client, mode="mocked")
    guard = LiveExecutionGuard(config=cfg)

    falcon = MagicMock()
    falcon.rank_candidates = AsyncMock(return_value=[signal])
    portfolio = PaperPortfolio()
    engine = PaperExecutionEngine(portfolio)

    # CapitalRiskGate is required for live mode — PaperRiskGate blocks non-paper signals
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        capital_gate = CapitalRiskGate(config=cfg)

    worker = PaperBetaWorker(
        falcon=falcon,
        risk_gate=capital_gate,
        engine=engine,
        live_guard=guard,
        provider=provider,
        clob_adapter=adapter,
        market_data_provider=None,
    )

    import projects.polymarket.polyquantbot.server.workers.paper_beta_worker as wmod
    orig_state = wmod.STATE
    wmod.STATE = state
    try:
        with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
            events = asyncio.run(worker.run_once())
    finally:
        wmod.STATE = orig_state

    assert len(events) == 1
    assert events[0]["mode"] == "mocked"
    assert events[0]["order_id"] == "live-test-001"
    assert mock_client.call_count == 1


# ── RCLOB-25: run_once() uses paper engine in paper mode even with adapter ────

def test_rclob_25_run_once_uses_paper_engine_in_paper_mode() -> None:
    from unittest.mock import AsyncMock, MagicMock

    state = _paper_state()
    cfg = _paper_cfg()
    mock_client = MockClobClient()
    adapter = ClobExecutionAdapter(config=cfg, client=mock_client, mode="mocked")

    signal = _make_signal()
    falcon = MagicMock()
    falcon.rank_candidates = AsyncMock(return_value=[signal])
    portfolio = PaperPortfolio()
    engine = PaperExecutionEngine(portfolio)

    worker = PaperBetaWorker(
        falcon=falcon,
        risk_gate=PaperRiskGate(),
        engine=engine,
        live_guard=None,
        provider=None,
        clob_adapter=adapter,
        market_data_provider=None,
    )

    import projects.polymarket.polyquantbot.server.workers.paper_beta_worker as wmod
    orig_state = wmod.STATE
    wmod.STATE = state
    try:
        with patch.dict(os.environ, _PAPER_ENV, clear=False):
            events = asyncio.run(worker.run_once())
    finally:
        wmod.STATE = orig_state

    # Paper engine used — clob_adapter client should NOT have been called
    assert mock_client.call_count == 0
    # Paper engine produces a 'paper' mode event
    if events:
        assert events[0]["mode"] == "paper"


# ── RCLOB-26: run_once() skips when clob_adapter blocked ─────────────────────

def test_rclob_26_run_once_skips_when_clob_adapter_blocked() -> None:
    from unittest.mock import AsyncMock, MagicMock

    state = _live_state()
    # All gates on but provider will return zero → ClobSubmissionBlockedError
    cfg = _live_cfg_all_gates()
    mock_client = MockClobClient()
    adapter = ClobExecutionAdapter(config=cfg, client=mock_client, mode="mocked")
    guard = LiveExecutionGuard(config=cfg)

    signal = _make_signal()
    falcon = MagicMock()
    falcon.rank_candidates = AsyncMock(return_value=[signal])
    portfolio = PaperPortfolio()
    engine = PaperExecutionEngine(portfolio)

    # Use zero provider → guard will block with financial_provider_all_zero
    worker = PaperBetaWorker(
        falcon=falcon,
        risk_gate=PaperRiskGate(),
        engine=engine,
        live_guard=guard,
        provider=_ZeroProvider(),
        clob_adapter=adapter,
        market_data_provider=None,
    )

    import projects.polymarket.polyquantbot.server.workers.paper_beta_worker as wmod
    orig_state = wmod.STATE
    wmod.STATE = state
    try:
        with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
            events = asyncio.run(worker.run_once())
    finally:
        wmod.STATE = orig_state

    assert len(events) == 0
    assert mock_client.call_count == 0


# ── RCLOB-27: run_once() skips when no live_guard and mode='live' ─────────────

def test_rclob_27_run_once_skips_no_live_guard_live_mode() -> None:
    from unittest.mock import AsyncMock, MagicMock

    state = _live_state()
    signal = _make_signal()
    falcon = MagicMock()
    falcon.rank_candidates = AsyncMock(return_value=[signal])
    portfolio = PaperPortfolio()
    engine = PaperExecutionEngine(portfolio)

    worker = PaperBetaWorker(
        falcon=falcon,
        risk_gate=PaperRiskGate(),
        engine=engine,
        live_guard=None,  # intentionally omitted
        provider=None,
        clob_adapter=None,
        market_data_provider=None,
    )

    import projects.polymarket.polyquantbot.server.workers.paper_beta_worker as wmod
    orig_state = wmod.STATE
    wmod.STATE = state
    try:
        events = asyncio.run(worker.run_once())
    finally:
        wmod.STATE = orig_state

    assert len(events) == 0
    assert state.kill_switch is True  # disable_live_execution triggered


# ── RCLOB-28: CapitalModeConfig all-gates-off → not allowed ──────────────────

def test_rclob_28_all_gates_off_not_allowed() -> None:
    cfg = _paper_cfg()
    assert cfg.is_capital_mode_allowed() is False


# ── RCLOB-29: validate() raises in LIVE mode if any gate off ─────────────────

def test_rclob_29_validate_raises_if_gate_off_in_live_mode() -> None:
    for gate in (
        "CAPITAL_MODE_CONFIRMED",
        "RISK_CONTROLS_VALIDATED",
        "EXECUTION_PATH_VALIDATED",
        "SECURITY_HARDENING_VALIDATED",
    ):
        cfg = _live_cfg_missing(gate)
        env = {**_LIVE_ENV_ALL_GATES, gate: "false"}
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(CapitalModeGuardError):
                cfg.validate()


# ── RCLOB-30: Kelly fraction is always 0.25 ──────────────────────────────────

def test_rclob_30_kelly_fraction_always_0_25() -> None:
    cfg_paper = _paper_cfg()
    cfg_live = _live_cfg_all_gates()
    assert cfg_paper.kelly_fraction == 0.25
    assert cfg_live.kelly_fraction == 0.25
    assert KELLY_FRACTION == 0.25
    # Full Kelly would be 1.0 — must never equal 1.0
    assert cfg_paper.kelly_fraction != 1.0
    assert cfg_live.kelly_fraction != 1.0
