"""Lane 2C-2b — complete-set arbitrage scan + PAPER booking wiring.

Two surfaces:
  1. ``complete_set_scan.scan_complete_set_for_user`` — the per-user detect ->
     log -> gate -> book pipeline, exercised hermetically with injected fakes
     (no DB, broker, or network).
  2. ``gate.evaluate`` step 13 ``complete_set`` path — the combined-cost hard-cap
     (no Kelly shrink, reject when over the per-position cap).
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.domain.risk import gate as gate_mod
from projects.polymarket.crusaderbot.domain.risk.gate import GateContext, GateResult
from projects.polymarket.crusaderbot.services.signal_scan import complete_set_scan as css


def _run(coro):
    return asyncio.run(coro)


# --- fixtures -----------------------------------------------------------------

def _arb_book(price: float, size: float) -> dict:
    return {"asks": [{"price": str(price), "size": str(size)}]}


def _row(**over: Any) -> dict:
    base = {
        "user_id": str(uuid4()),
        "telegram_user_id": 12345,
        "role": "user",
        "auto_trade_on": True,
        "paused": False,
        "resolved_profile": "balanced",
        "trading_mode": "paper",
        "active_preset": "close_sweep",
    }
    base.update(over)
    return base


def _market(**over: Any) -> dict:
    base = {
        "id": "MKT-1",
        "condition_id": "0xcond1",
        "yes_token_id": "TYES",
        "no_token_id": "TNO",
        "status": "active",
        "liquidity_usdc": 50_000.0,
        "question": "Will X happen?",
        "resolved": False,
    }
    base.update(over)
    return base


def _settings(edge: float = 0.02) -> SimpleNamespace:
    return SimpleNamespace(MIN_COMPLETE_SET_EDGE=edge)


class _Booker:
    def __init__(self, status: str = "open") -> None:
        self.calls: list[dict] = []
        self._status = status

    async def __call__(self, **kw: Any) -> dict:
        self.calls.append(kw)
        return {"status": self._status, "mode": "paper"}


def _approve(_ctx: GateContext) -> Any:
    async def _inner() -> GateResult:
        return GateResult(True, "approved", None, _ctx.proposed_size_usdc, "paper")
    return _inner()


async def _balance(_uid: Any) -> float:
    return 10_000.0


# --- pipeline tests -----------------------------------------------------------

def test_happy_path_detects_logs_gates_books():
    booker = _Booker()
    fetched: list[str] = []

    async def fetch(token_id: str) -> dict:
        fetched.append(token_id)
        return _arb_book(0.45, 100.0)  # pair cost 0.90 < threshold 0.98

    res = _run(css.scan_complete_set_for_user(
        _row(), [_market()], settings=_settings(),
        book_fetcher=fetch, gate_evaluate=_approve,
        booker=booker, balance_reader=_balance,
    ))
    assert res.markets_scanned == 1
    assert res.quotes_found == 1
    assert res.booked == 1
    assert res.rejected == 0
    assert set(fetched) == {"TYES", "TNO"}  # concurrent fetch — order not guaranteed
    assert len(booker.calls) == 1
    call = booker.calls[0]
    assert call["idempotency_key"].startswith("complete_set:")
    assert call["idempotency_key"].endswith(":MKT-1")
    assert call["quote"].market_id == "MKT-1"
    assert call["market_question"] == "Will X happen?"


def test_paper_duplicate_books_nothing():
    booker = _Booker(status="duplicate")  # idempotency hit — nothing persisted

    async def fetch(token_id: str) -> dict:
        return _arb_book(0.45, 100.0)

    res = _run(css.scan_complete_set_for_user(
        _row(), [_market()], settings=_settings(),
        book_fetcher=fetch, gate_evaluate=_approve,
        booker=booker, balance_reader=_balance,
    ))
    assert res.booked == 0  # mirrors the live branch — a no-op never inflates booked
    assert len(booker.calls) == 1


def test_dormant_when_margin_floor_zero():
    booker = _Booker()

    async def fetch(token_id: str) -> dict:  # must never be called
        raise AssertionError("book fetched while dormant")

    res = _run(css.scan_complete_set_for_user(
        _row(), [_market()], settings=_settings(edge=0.0),
        book_fetcher=fetch, gate_evaluate=_approve,
        booker=booker, balance_reader=_balance,
    ))
    assert (res.markets_scanned, res.quotes_found, res.booked) == (0, 0, 0)
    assert booker.calls == []


def test_no_fillable_arb_does_not_book():
    booker = _Booker()

    async def fetch(token_id: str) -> dict:
        return _arb_book(0.60, 100.0)  # pair cost 1.20 > 1.0 — no arb

    res = _run(css.scan_complete_set_for_user(
        _row(), [_market()], settings=_settings(),
        book_fetcher=fetch, gate_evaluate=_approve,
        booker=booker, balance_reader=_balance,
    ))
    assert res.markets_scanned == 1
    assert res.quotes_found == 0
    assert res.booked == 0
    assert booker.calls == []


def test_gate_rejection_blocks_booking():
    booker = _Booker()

    async def fetch(token_id: str) -> dict:
        return _arb_book(0.45, 100.0)

    def reject(_ctx: GateContext) -> Any:
        async def _inner() -> GateResult:
            return GateResult(False, "max_concurrent_trades", 7)
        return _inner()

    res = _run(css.scan_complete_set_for_user(
        _row(), [_market()], settings=_settings(),
        book_fetcher=fetch, gate_evaluate=reject,
        booker=booker, balance_reader=_balance,
    ))
    assert res.quotes_found == 1
    assert res.booked == 0
    assert res.rejected == 1
    assert booker.calls == []


class _LiveBooker:
    def __init__(self, status: str = "open") -> None:
        self.calls: list[dict] = []
        self._status = status

    async def __call__(self, **kw: Any) -> dict:
        self.calls.append(kw)
        return {"status": self._status, "mode": "live"}


def _approve_live(_ctx: GateContext) -> Any:
    async def _inner() -> GateResult:
        return GateResult(True, "approved", None, _ctx.proposed_size_usdc, "live")
    return _inner()


def test_live_decision_routes_to_live_booker():
    booker = _Booker()  # paper booker — must NOT be called
    live = _LiveBooker(status="open")

    async def fetch(token_id: str) -> dict:
        return _arb_book(0.45, 100.0)

    res = _run(css.scan_complete_set_for_user(
        _row(role="admin", trading_mode="live"), [_market()], settings=_settings(),
        book_fetcher=fetch, gate_evaluate=_approve_live,
        booker=booker, live_booker=live, balance_reader=_balance,
    ))
    assert res.booked == 1
    assert res.rejected == 0
    assert booker.calls == []  # paper primitive untouched on a live decision
    assert len(live.calls) == 1
    call = live.calls[0]
    # the live booker needs role/trading_mode/both books that the paper one omits
    assert call["role"] == "admin"
    assert call["trading_mode"] == "live"
    assert call["yes_book"] is not None and call["no_book"] is not None
    assert call["quote"].market_id == "MKT-1"
    assert call["idempotency_key"].endswith(":MKT-1")
    assert call["active_preset"] == "close_sweep"


def test_live_no_fill_books_nothing():
    live = _LiveBooker(status="no_fill")  # clean YES kill — zero exposure

    async def fetch(token_id: str) -> dict:
        return _arb_book(0.45, 100.0)

    res = _run(css.scan_complete_set_for_user(
        _row(trading_mode="live"), [_market()], settings=_settings(),
        book_fetcher=fetch, gate_evaluate=_approve_live,
        live_booker=live, balance_reader=_balance,
    ))
    assert res.booked == 0  # nothing persisted
    assert res.rejected == 0
    assert res.errors == 0
    assert len(live.calls) == 1


def test_live_naked_halt_counts_as_booked():
    live = _LiveBooker(status="naked_halt")  # naked leg persisted force-exitable

    async def fetch(token_id: str) -> dict:
        return _arb_book(0.45, 100.0)

    res = _run(css.scan_complete_set_for_user(
        _row(trading_mode="live"), [_market()], settings=_settings(),
        book_fetcher=fetch, gate_evaluate=_approve_live,
        live_booker=live, balance_reader=_balance,
    ))
    assert res.booked == 1  # a position row exists (even though the bot halted)
    assert len(live.calls) == 1


def test_live_naked_halt_persist_failed_is_error():
    # Worst case: naked leg could NOT be persisted -> UNTRACKED live exposure. The
    # booker halts + pages, but the scan MUST surface it as an error, never a clean
    # non-booked no-op (else signal_scan_job logs the run as successful).
    live = _LiveBooker(status="naked_halt_persist_failed")

    async def fetch(token_id: str) -> dict:
        return _arb_book(0.45, 100.0)

    res = _run(css.scan_complete_set_for_user(
        _row(trading_mode="live"), [_market()], settings=_settings(),
        book_fetcher=fetch, gate_evaluate=_approve_live,
        live_booker=live, balance_reader=_balance,
    ))
    assert res.booked == 0
    assert res.errors == 1  # masked-blocker guard
    assert len(live.calls) == 1


def test_live_unknown_status_is_error_safe_by_default():
    live = _LiveBooker(status="something_new")  # unrecognised -> treat as unsafe

    async def fetch(token_id: str) -> dict:
        return _arb_book(0.45, 100.0)

    res = _run(css.scan_complete_set_for_user(
        _row(trading_mode="live"), [_market()], settings=_settings(),
        book_fetcher=fetch, gate_evaluate=_approve_live,
        live_booker=live, balance_reader=_balance,
    ))
    assert res.booked == 0
    assert res.errors == 1


def test_live_booker_raise_isolated_to_market():
    # An ambiguous post-submit raises LivePostSubmitError (booker already halted +
    # paged); the per-market handler isolates it as an error, not a crash.
    async def fetch(token_id: str) -> dict:
        return _arb_book(0.45, 100.0)

    async def raising_live(**_kw: Any) -> dict:
        raise RuntimeError("ambiguous post-submit halt")

    res = _run(css.scan_complete_set_for_user(
        _row(trading_mode="live"), [_market()], settings=_settings(),
        book_fetcher=fetch, gate_evaluate=_approve_live,
        live_booker=raising_live, balance_reader=_balance,
    ))
    assert res.booked == 0
    assert res.errors == 1


def test_unknown_chosen_mode_skipped_not_executed():
    booker = _Booker()
    live = _LiveBooker()

    async def fetch(token_id: str) -> dict:
        return _arb_book(0.45, 100.0)

    def approve_weird(_ctx: GateContext) -> Any:
        async def _inner() -> GateResult:
            return GateResult(True, "approved", None, _ctx.proposed_size_usdc, "shadow")
        return _inner()

    res = _run(css.scan_complete_set_for_user(
        _row(), [_market()], settings=_settings(),
        book_fetcher=fetch, gate_evaluate=approve_weird,
        booker=booker, live_booker=live, balance_reader=_balance,
    ))
    assert res.booked == 0
    assert res.rejected == 1
    assert booker.calls == [] and live.calls == []


def test_capital_too_small_returns_early():
    booker = _Booker()

    async def fetch(token_id: str) -> dict:
        raise AssertionError("book fetched with insufficient capital")

    async def tiny_balance(_uid: Any) -> float:
        return 1.0  # balance * max_pos_pct * kelly < 1 share

    res = _run(css.scan_complete_set_for_user(
        _row(), [_market()], settings=_settings(),
        book_fetcher=fetch, gate_evaluate=_approve,
        booker=booker, balance_reader=tiny_balance,
    ))
    assert (res.markets_scanned, res.quotes_found, res.booked) == (0, 0, 0)


def test_missing_tokens_skipped():
    booker = _Booker()

    async def fetch(token_id: str) -> dict:
        return _arb_book(0.45, 100.0)

    res = _run(css.scan_complete_set_for_user(
        _row(), [_market(yes_token_id=None)], settings=_settings(),
        book_fetcher=fetch, gate_evaluate=_approve,
        booker=booker, balance_reader=_balance,
    ))
    assert res.markets_scanned == 0
    assert res.booked == 0


def test_resolved_market_skipped():
    booker = _Booker()

    async def fetch(token_id: str) -> dict:
        return _arb_book(0.45, 100.0)

    res = _run(css.scan_complete_set_for_user(
        _row(), [_market(resolved=True)], settings=_settings(),
        book_fetcher=fetch, gate_evaluate=_approve,
        booker=booker, balance_reader=_balance,
    ))
    assert res.markets_scanned == 0
    assert res.booked == 0


def test_per_market_error_isolated():
    booker = _Booker()
    calls = {"n": 0}

    async def fetch(token_id: str) -> dict:
        calls["n"] += 1
        # First market's YES fetch raises; second market succeeds.
        if calls["n"] == 1:
            raise RuntimeError("book api down")
        return _arb_book(0.45, 100.0)

    res = _run(css.scan_complete_set_for_user(
        _row(), [_market(id="MKT-1"), _market(id="MKT-2")], settings=_settings(),
        book_fetcher=fetch, gate_evaluate=_approve,
        booker=booker, balance_reader=_balance,
    ))
    assert res.errors == 1
    assert res.booked == 1  # second market still processed
    assert len(booker.calls) == 1


# --- gate step-13 complete_set hard-cap tests ---------------------------------

def _patch_gate_passthrough(monkeypatch: pytest.MonkeyPatch, *, balance: float) -> None:
    async def _noop_log(*a: Any, **k: Any) -> None:
        return None

    async def _caps_ok(_uid: Any, _sz: Any, max_open_cap: Any = None) -> GateResult:
        return GateResult(True, "ok")

    async def _false(*a: Any, **k: Any) -> bool:
        return False

    async def _zero_pnl(*a: Any, **k: Any) -> Decimal:
        return Decimal("0")

    async def _zero_int(*a: Any, **k: Any) -> int:
        return 0

    async def _bal(*a: Any, **k: Any) -> Decimal:
        return Decimal(str(balance))

    async def _zero_dec(*a: Any, **k: Any) -> Decimal:
        return Decimal("0")

    async def _record(*a: Any, **k: Any) -> None:
        return None

    monkeypatch.setattr(gate_mod, "_log", _noop_log)
    monkeypatch.setattr(gate_mod, "validate_risk_caps", _caps_ok)
    monkeypatch.setattr(gate_mod, "kill_switch_is_active", _false)
    monkeypatch.setattr(gate_mod, "daily_pnl", _zero_pnl)
    monkeypatch.setattr(gate_mod, "_max_drawdown_breached", _false)
    monkeypatch.setattr(gate_mod, "_open_position_count", _zero_int)
    monkeypatch.setattr(gate_mod, "get_balance", _bal)
    monkeypatch.setattr(gate_mod, "_open_exposure", _zero_dec)
    monkeypatch.setattr(gate_mod, "_idempotent_already_seen", _false)
    monkeypatch.setattr(gate_mod, "_recent_dup_market_trade", _false)
    monkeypatch.setattr(gate_mod, "_record_idempotency", _record)
    # evaluate() does `from ...config import get_settings` at call time — patch
    # the source module so the local import picks up the fake.
    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.config.get_settings",
        lambda: SimpleNamespace(
            MAX_DAILY_LOSS_USD=100000.0, MAX_TOTAL_EXPOSURE_PCT=1.0,
            ENABLE_LIVE_TRADING=False, EXECUTION_PATH_VALIDATED=False,
            CAPITAL_MODE_CONFIRMED=False,
        ),
    )


def _cset_ctx(size: float) -> GateContext:
    return GateContext(
        user_id=uuid4(), telegram_user_id=1, role="user",
        auto_trade_on=True, paused=False, market_id="MKT-1", side="yes",
        proposed_size_usdc=Decimal(str(size)), proposed_price=0.9,
        market_liquidity=50_000.0, market_status="active", edge_bps=None,
        signal_ts=None, idempotency_key="complete_set:x:MKT-1",
        strategy_type="complete_set_arb", risk_profile="balanced",
        daily_loss_override=None, trading_mode="paper", complete_set=True,
    )


def test_gate_complete_set_passes_size_through_unshrunk(monkeypatch: pytest.MonkeyPatch):
    # balanced: kelly 0.25 (capped) * max_pos_pct. balance large so cap >> size.
    _patch_gate_passthrough(monkeypatch, balance=100_000.0)
    res = _run(gate_mod.evaluate(_cset_ctx(90.0)))
    assert res.approved
    assert res.chosen_mode == "paper"
    # No Kelly shrink: approved size equals the combined cost passed in.
    assert res.final_size_usdc == Decimal("90.0")


def test_gate_complete_set_rejects_over_cap(monkeypatch: pytest.MonkeyPatch):
    # balance=1000: exposure (90/1000=0.09) passes step 8, but the per-position
    # cap (1000 * max_pos_pct * 0.25 << 90) rejects at step 13.
    _patch_gate_passthrough(monkeypatch, balance=1000.0)
    res = _run(gate_mod.evaluate(_cset_ctx(90.0)))
    assert not res.approved
    assert res.reason == "complete_set_size_over_cap"
    assert res.failed_step == 13
