"""live-mode-truth lane (WARP/root-live-mode-truth) — owner directive 2026-06-11.

Pins the four corrections:
1. NO manual live capital amount — the user's REAL deposited balance is the
   live bankroll (sizing base) and the hard exposure ceiling (step 15).
2. Mode-scoped money: live mode shows/uses real money, paper mode paper money
   (one bucket definition shared by balance, feeds, and the scan loader).
3. Single mode truth: trading_mode is canonical; paper_mode_override is a
   synced mirror — every writer updates both, no surface can disagree.
4. Switch-then-deposit: no deposit gate in the live checklist; every mode
   switch AUTO-STOPS the bot; zero real funds can never open a live trade.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

from projects.polymarket.crusaderbot import config as cfg
from projects.polymarket.crusaderbot.domain.risk import gate as gate_mod
from projects.polymarket.crusaderbot.domain.risk.gate import GateContext, GateResult
from projects.polymarket.crusaderbot.wallet import ledger as ledger_mod

_UID = uuid4()
_ROOT = Path(__file__).parents[1]


# ── gate harness (mirrors test_gate_capital_alloc_preload) ───────────────────


def _ctx(**overrides: Any) -> GateContext:
    base: dict[str, Any] = dict(
        user_id=_UID,
        telegram_user_id=9001,
        role="admin",
        auto_trade_on=True,
        paused=False,
        market_id="mkt-1",
        side="yes",
        proposed_size_usdc=Decimal("1000"),
        proposed_price=0.60,
        market_liquidity=50_000.0,
        market_status="active",
        edge_bps=None,
        signal_ts=datetime.now(timezone.utc),
        idempotency_key="sf:livemode",
        strategy_type="late_entry_v3",
        risk_profile="balanced",
        daily_loss_override=None,
        trading_mode="paper",
        capital_alloc_pct=0.80,
        spread=0.002,
        orderbook_depth_usdc=100_000.0,
    )
    base.update(overrides)
    return GateContext(**base)


def _stub_helpers(monkeypatch, *, mixed_balance: float, guards_open: bool) -> None:
    monkeypatch.setattr(gate_mod, "_log", AsyncMock())
    monkeypatch.setattr(
        gate_mod, "validate_risk_caps",
        AsyncMock(return_value=GateResult(True, "caps_ok")),
    )
    monkeypatch.setattr(gate_mod, "kill_switch_is_active", AsyncMock(return_value=False))
    monkeypatch.setattr(gate_mod, "daily_pnl", AsyncMock(return_value=Decimal("0")))
    monkeypatch.setattr(gate_mod, "_max_drawdown_breached", AsyncMock(return_value=False))
    monkeypatch.setattr(gate_mod, "_open_position_count", AsyncMock(return_value=0))
    monkeypatch.setattr(
        gate_mod, "get_balance", AsyncMock(return_value=Decimal(str(mixed_balance))),
    )
    monkeypatch.setattr(gate_mod, "_open_exposure", AsyncMock(return_value=Decimal("0")))
    monkeypatch.setattr(gate_mod, "_open_live_exposure", AsyncMock(return_value=Decimal("0")))
    monkeypatch.setattr(gate_mod, "_idempotent_already_seen", AsyncMock(return_value=False))
    monkeypatch.setattr(gate_mod, "_recent_dup_market_trade", AsyncMock(return_value=False))
    monkeypatch.setattr(gate_mod, "_record_idempotency", AsyncMock())
    # One-shot live-balance read must NOT be needed when preloaded.
    monkeypatch.setattr(
        gate_mod, "get_live_balance",
        AsyncMock(side_effect=AssertionError(
            "one-shot get_live_balance called although live_balance_usdc "
            "was preloaded on the GateContext")),
    )
    flags = dict(
        ENABLE_LIVE_TRADING=guards_open,
        EXECUTION_PATH_VALIDATED=guards_open,
        CAPITAL_MODE_CONFIRMED=guards_open,
        RISK_CONTROLS_VALIDATED=guards_open,
        SECURITY_HARDENING_VALIDATED=guards_open,
        USE_REAL_CLOB=guards_open,
        MAX_OPEN_POSITIONS=5,
        MAX_DAILY_LOSS_USD=2000.0,
    )
    monkeypatch.setattr(cfg, "get_settings", lambda: SimpleNamespace(**flags))


# ── 1. live sizing base = real deposited balance ──────────────────────────────


def test_live_user_sizes_off_real_balance_not_mixed_wallet(monkeypatch):
    """trading_mode='live' with $40 real / $10k mixed: the approved size must
    derive from the REAL balance (40 × 0.06 × 0.20 = 0.48 for balanced), never
    the mixed wallet pool (which would allow 120.0)."""
    _stub_helpers(monkeypatch, mixed_balance=10_000.0, guards_open=True)
    res = asyncio.run(gate_mod.evaluate(_ctx(
        trading_mode="live", live_balance_usdc=40.0, edge_bps=2_000.0,
    )))
    assert res.approved is True
    assert res.chosen_mode == "live"
    assert res.final_size_usdc == Decimal("40") * Decimal("0.06") * Decimal("0.2")


def test_paper_user_sizing_unchanged(monkeypatch):
    """Paper users keep the legacy sizing base (mixed wallet balance) —
    zero behavioral change outside live mode."""
    _stub_helpers(monkeypatch, mixed_balance=10_000.0, guards_open=False)
    res = asyncio.run(gate_mod.evaluate(_ctx(trading_mode="paper")))
    assert res.approved is True
    assert res.chosen_mode == "paper"
    assert res.final_size_usdc == Decimal("10000") * Decimal("0.06") * Decimal("0.2")


def test_live_user_with_zero_funds_cannot_trade(monkeypatch):
    """Switch-then-deposit safety: $0 real balance → size collapses to zero →
    reject. No live trade can exist before the deposit lands."""
    _stub_helpers(monkeypatch, mixed_balance=10_000.0, guards_open=True)
    res = asyncio.run(gate_mod.evaluate(_ctx(
        trading_mode="live", live_balance_usdc=0.0, edge_bps=2_000.0,
    )))
    assert res.approved is False
    assert res.reason in ("size_zero_after_cap", "live_no_funds")


def test_live_exposure_bounded_at_step15_manual_cap_tightens(monkeypatch):
    """Step 15 (complete-set path — size passes through un-shrunk): the real
    balance bounds aggregate exposure, and a manual cap only TIGHTENS it.
    (For non-complete-set trades the step-13 Kelly clamp off the real balance
    binds first; step 15 is the aggregate/defence-in-depth layer.)"""
    _stub_helpers(monkeypatch, mixed_balance=100_000.0, guards_open=True)
    monkeypatch.setattr(
        gate_mod, "_open_live_exposure", AsyncMock(return_value=Decimal("30")),
    )
    # Kelly cap 20_000×0.06×0.2=240 ≥ 200 → passes 13; spendable 20_030;
    # open 30 + 200 = 230 ≤ 20_030 → approved.
    res = asyncio.run(gate_mod.evaluate(_ctx(
        trading_mode="live", live_balance_usdc=20_000.0, edge_bps=2_000.0,
        complete_set=True, proposed_size_usdc=Decimal("200"),
    )))
    assert res.approved is True
    assert res.chosen_mode == "live"
    # Same trade with a manual cap of 150: effective = min(150, 20_030);
    # open 30 + 200 = 230 > 150 → rejected at 15.
    res2 = asyncio.run(gate_mod.evaluate(_ctx(
        trading_mode="live", live_balance_usdc=20_000.0, edge_bps=2_000.0,
        complete_set=True, proposed_size_usdc=Decimal("200"),
        live_capital_cap_usdc=150.0,
    )))
    assert res2.approved is False
    assert res2.failed_step == 15
    assert res2.reason == "live_capital_cap_exceeded"


# ── 2. one bucket definition everywhere ───────────────────────────────────────


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def test_live_money_bucket_definition_is_shared():
    """The live-money bucket (deposit/withdraw + withdrawal-refund adjustments
    + live-position trade rows) must be IDENTICAL in wallet.ledger and the
    scan loader's preload subquery — drift here would make the bot size off a
    different number than the one the user sees."""
    ledger_src = _norm((_ROOT / "wallet" / "ledger.py").read_text(encoding="utf-8"))
    loader_src = _norm(
        (_ROOT / "services" / "signal_scan" / "signal_scan_job.py")
        .read_text(encoding="utf-8")
    )
    for fragment in (
        "type IN ('deposit', 'withdraw')",
        "type = 'adjustment'",
        ".mode = 'live'",
    ):
        assert fragment in ledger_src, f"ledger bucket lost: {fragment}"
        assert fragment in loader_src, f"loader bucket lost: {fragment}"


def test_ledger_filter_alias_rewrite():
    sql_l = ledger_mod.live_ledger_filter_sql("l")
    sql_x = ledger_mod.live_ledger_filter_sql("x")
    assert "l.type" in sql_l and "x.type" in sql_x
    assert "l.type" not in sql_x


def test_wallet_endpoints_are_mode_scoped():
    """The WebTrader money surfaces must scope by the user's mode: balance via
    get_live_balance, feeds via live_ledger_filter_sql, position stats via
    positions.mode."""
    src = (_ROOT / "webtrader" / "backend" / "router.py").read_text(encoding="utf-8")
    assert src.count("get_live_balance(") >= 4   # status/enable/wallet/dashboard/portfolio
    assert src.count("live_ledger_filter_sql(") >= 2  # /wallet + /wallet/ledger
    for anchor in (
        "AND mode=$2 AND status='closed'",          # dashboard pnl scoping
        "AND p.mode = $2",                          # positions list + analytics
        "WHERE user_id=$1::uuid AND mode=$2 AND status IN ('open','pending_settlement')",
    ):
        assert _norm(anchor) in _norm(src), f"mode scoping lost: {anchor}"


# ── 3 + 4. single mode truth, auto-stop, no deposit gate ─────────────────────


def test_mode_writers_keep_both_columns_in_sync_and_auto_stop():
    src = (_ROOT / "webtrader" / "backend" / "router.py").read_text(encoding="utf-8")
    n = _norm(src)
    # enable: live + override cleared + bot stopped (SQL spans adjacent
    # string literals — assert the fragments, not the joined statement)
    assert "trading_mode = 'live'" in n
    assert "paper_mode_override = FALSE" in n
    # disable: paper + override set + bot stopped
    assert "trading_mode = 'paper'" in n
    assert "paper_mode_override = TRUE" in n
    assert n.count("SET auto_trade_on = FALSE WHERE id = $1::uuid") >= 2


def test_telegram_paper_toggle_is_safe_direction_only():
    """The Telegram paper toggle may only DROP to paper (syncing both columns,
    stopping the bot). It must never write trading_mode='live' — going live is
    exclusively the typed-confirm flow."""
    src = (_ROOT / "bot" / "handlers" / "strategy.py").read_text(encoding="utf-8")
    n = _norm(src)
    assert "paper_mode_override=TRUE" in n.replace(" ", "") or \
        "paper_mode_override=TRUE" in n
    assert "trading_mode='paper'" in n.replace(" ", "")
    assert "trading_mode='live'" not in n.replace(" ", "")
    assert "auto_trade_on=FALSE" in n.replace(" ", "")


def test_migration_096_syncs_historic_rows():
    sql = (_ROOT / "migrations" / "096_mode_truth_sync.sql").read_text(encoding="utf-8")
    assert "paper_mode_override = (trading_mode IS DISTINCT FROM 'live')" in _norm(sql)


def test_enable_request_requires_no_capital_amount():
    from projects.polymarket.crusaderbot.webtrader.backend.schemas import (
        LiveEnableRequest,
    )
    req = LiveEnableRequest(confirm_phrase="X")  # no cap — must validate
    assert req.live_capital_cap_usdc == 0.0
