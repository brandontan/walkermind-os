"""Hermetic regression tests for the WARP-54 WARP•R00T-audit follow-up lanes.

Covers four of the audit findings reconciled in this lane (max-concurrent ceiling
is covered separately in ``test_concurrency_policy.py``):

  * Lane 1 (edge floor)        — ``signal_scan_job._edge_bps_from_metadata``
  * Lane 3 (complete-set 2%)   — ``complete_set_scan`` clamps the operator floor
                                 UP to the AGENTS.md 2% arbitrage hard floor
  * Lane 5 (audit observ.)     — ``kill_switch_exec._write_audit_log`` mirrors
                                 into the canonical ``audit.log`` destination
  * Lane 6 (silent excepts)    — fire-and-forget emit failures now log

No DB, no broker, no Telegram, no network. All side-effecting deps injected/patched.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from projects.polymarket.crusaderbot.services.signal_scan import complete_set_scan as css
from projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job import (
    _edge_bps_from_metadata,
)


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- Lane 1


def test_edge_bps_from_edge_fraction_converts_to_bps():
    # Playbook closing-edge module stamps metadata["edge"] as a fraction vs
    # fair price; the floor consumes it as basis points (×10_000).
    assert _edge_bps_from_metadata({"edge": 0.03}) == 300.0
    assert _edge_bps_from_metadata({"edge": 0.005}) == 50.0


def test_edge_bps_explicit_bps_passthrough_takes_precedence():
    assert _edge_bps_from_metadata({"edge_bps": 420.0}) == 420.0
    # explicit bps wins over a fraction if both present
    assert _edge_bps_from_metadata({"edge_bps": 250, "edge": 0.01}) == 250.0


def test_edge_bps_none_for_heuristic_strategies_without_edge():
    # late_entry_v3 carries ask_diff/imbalance heuristics, NOT a measured edge,
    # so it returns None and stays honestly ungated by gate step 12 (no
    # fabricated EV — consistent with the WARP-58 UNPROVEN OOS finding).
    assert _edge_bps_from_metadata({"ask_diff": 0.05, "underdog_mode": True}) is None
    assert _edge_bps_from_metadata({}) is None
    assert _edge_bps_from_metadata(None) is None
    assert _edge_bps_from_metadata("not-a-dict") is None


def test_edge_bps_rejects_non_finite_and_unparseable():
    assert _edge_bps_from_metadata({"edge": float("nan")}) is None
    assert _edge_bps_from_metadata({"edge": float("inf")}) is None
    assert _edge_bps_from_metadata({"edge": "garbage"}) is None
    # non-finite explicit bps falls through to (absent) edge -> None
    assert _edge_bps_from_metadata({"edge_bps": float("inf")}) is None


# --------------------------------------------------------------------------- Lane 3


def _arb_book(price: float, size: float) -> dict:
    return {"asks": [{"price": str(price), "size": str(size)}]}


def _market() -> dict:
    return {
        "id": "MKT-1", "condition_id": "0xc1", "yes_token_id": "TYES",
        "no_token_id": "TNO", "status": "active", "liquidity_usdc": 50_000.0,
        "question": "Will X happen?", "resolved": False,
    }


def _row() -> dict:
    return {
        "user_id": str(uuid4()), "telegram_user_id": 1, "role": "user",
        "auto_trade_on": True, "paused": False, "resolved_profile": "balanced",
        "trading_mode": "paper", "active_preset": "close_sweep",
    }


def _approve(ctx: Any) -> Any:
    from projects.polymarket.crusaderbot.domain.risk.gate import GateResult

    async def _inner() -> GateResult:
        return GateResult(True, "approved", None, ctx.proposed_size_usdc, "paper")
    return _inner()


async def _balance(_uid: Any) -> float:
    return 10_000.0


class _Booker:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, **kw: Any) -> dict:
        self.calls.append(kw)
        return {"status": "open", "mode": "paper"}


def test_sub_two_percent_operator_floor_is_clamped_up_and_rejects():
    # Operator sets a 0.5% floor; a 1.5%-margin pair would book at 0.5% but the
    # hard floor clamps the effective margin UP to 2%, so nothing books.
    booker = _Booker()

    async def fetch(_tok: str) -> dict:
        return _arb_book(0.4925, 100.0)  # pair cost 0.985 -> margin 0.015 (1.5%)

    res = _run(css.scan_complete_set_for_user(
        _row(), [_market()],
        settings=SimpleNamespace(MIN_COMPLETE_SET_EDGE=0.005),
        book_fetcher=fetch, gate_evaluate=_approve,
        booker=booker, balance_reader=_balance,
    ))
    assert res.markets_scanned == 1
    assert res.quotes_found == 0
    assert res.booked == 0
    assert booker.calls == []


def test_margin_above_hard_floor_still_books_under_sub_two_percent_setting():
    # Same sub-2% operator setting, but a 3%-margin pair clears the 2% hard floor.
    booker = _Booker()

    async def fetch(_tok: str) -> dict:
        return _arb_book(0.485, 100.0)  # pair cost 0.97 -> margin 0.03 (3%)

    res = _run(css.scan_complete_set_for_user(
        _row(), [_market()],
        settings=SimpleNamespace(MIN_COMPLETE_SET_EDGE=0.005),
        book_fetcher=fetch, gate_evaluate=_approve,
        booker=booker, balance_reader=_balance,
    ))
    assert res.quotes_found == 1
    assert res.booked == 1


def test_dormant_zero_floor_unchanged_no_book():
    # MIN_COMPLETE_SET_EDGE=0 keeps the path dormant (escape hatch preserved);
    # the clamp only applies once activated with a positive value.
    booker = _Booker()

    async def fetch(_tok: str) -> dict:
        return _arb_book(0.40, 100.0)  # 20% margin — would book if active

    res = _run(css.scan_complete_set_for_user(
        _row(), [_market()],
        settings=SimpleNamespace(MIN_COMPLETE_SET_EDGE=0.0),
        book_fetcher=fetch, gate_evaluate=_approve,
        booker=booker, balance_reader=_balance,
    ))
    assert res.markets_scanned == 0
    assert res.booked == 0


# --------------------------------------------------------------------------- Lane 5


def test_kill_switch_audit_mirrors_into_canonical_audit_log(monkeypatch):
    from projects.polymarket.crusaderbot.domain.risk import kill_switch_exec as kse
    from projects.polymarket.crusaderbot import audit as audit_mod

    executed: list[tuple] = []

    class _Conn:
        async def execute(self, *args: Any) -> None:
            executed.append(args)

    class _Acq:
        async def __aenter__(self) -> "_Conn":
            return _Conn()

        async def __aexit__(self, *a: Any) -> None:
            return None

    monkeypatch.setattr(kse, "get_pool", lambda: SimpleNamespace(acquire=lambda: _Acq()))
    mirror = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_mod, "write", mirror)

    _run(kse._write_audit_log(event="KILL_SWITCH_ACTIVATED",
                              triggered_by="op", reason="boom"))

    # Legacy public audit_log row still written.
    assert any("INSERT INTO audit_log" in a[0] for a in executed)
    # Canonical audit.log mirror invoked with normalized action + payload.
    mirror.assert_awaited_once()
    kwargs = mirror.await_args.kwargs
    assert kwargs["action"] == "kill_switch_activated"
    assert kwargs["actor_role"] == "system"
    assert kwargs["payload"] == {"reason": "boom", "triggered_by": "op"}


# --------------------------------------------------------------------------- Lane 6


def test_settings_changed_emit_failure_is_logged_not_silent(monkeypatch):
    from projects.polymarket.crusaderbot import users as users_mod
    from projects.polymarket.crusaderbot.core import event_bus

    async def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("bus down")

    monkeypatch.setattr(event_bus, "emit", _boom)
    debug = Mock(return_value=None)  # structlog .debug is synchronous
    monkeypatch.setattr(users_mod, "log", SimpleNamespace(debug=debug))

    # Must NOT raise, and must log (zero silent failures).
    _run(users_mod._emit_settings_changed(uuid4()))
    assert debug.called
    assert "settings_changed emit failed" in debug.call_args.args[0]


def test_no_bare_silent_pass_remains_in_touched_handlers():
    # Guard against regression to ``except Exception:\n    pass`` in the two
    # spots the audit flagged.
    import pathlib

    root = pathlib.Path(users_root())
    users_src = (root / "users.py").read_text(encoding="utf-8")
    trades_src = (root / "bot" / "handlers" / "trades.py").read_text(encoding="utf-8")
    assert "except Exception:\n        pass" not in users_src
    assert "except Exception:\n                pass" not in trades_src


def users_root() -> str:
    import projects.polymarket.crusaderbot as pkg
    import pathlib
    return str(pathlib.Path(pkg.__file__).parent)
