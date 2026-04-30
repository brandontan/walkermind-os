"""Priority 8-E — Capital Mode Confirmation Flow — Tests.

Test IDs: P8E-01 .. P8E-15

Coverage:
  P8E-01  CapitalModeConfirmationStore.insert returns persisted record
  P8E-02  store.get_active returns None when no row exists
  P8E-03  store.get_active returns most-recent unrevoked row
  P8E-04  store.revoke_latest revokes active row; get_active then returns None
  P8E-05  store.revoke_latest returns None when no active row exists
  P8E-06  CapitalModeConfig.is_capital_mode_fully_allowed: env gates missing -> (False, reason)
  P8E-07  is_capital_mode_fully_allowed: env all set but no receipt -> (False, no_active_receipt)
  P8E-08  is_capital_mode_fully_allowed: env all set + active receipt -> (True, None)
  P8E-09  LiveExecutionGuard.check_with_receipt raises when receipt missing
  P8E-10  check_with_receipt passes when env + receipt + provider all green
  P8E-11  POST /beta/capital_mode_confirm step 1 issues token + gate snapshot
  P8E-12  POST /beta/capital_mode_confirm rejects with 409 when env gates missing
  P8E-13  POST /beta/capital_mode_confirm step 2 commits receipt with valid token
  P8E-14  POST /beta/capital_mode_confirm step 2 rejects mismatched token with 409
  P8E-15  POST /beta/capital_mode_revoke revokes active confirmation
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from projects.polymarket.polyquantbot.configs.falcon import FalconSettings
from projects.polymarket.polyquantbot.server.api.public_beta_routes import (
    _PENDING_CAPITAL_CONFIRMS,
    build_public_beta_router,
)
from projects.polymarket.polyquantbot.server.config.capital_mode_config import (
    CapitalModeConfig,
)
from projects.polymarket.polyquantbot.server.core.live_execution_control import (
    LiveExecutionBlockedError,
    LiveExecutionGuard,
)
from projects.polymarket.polyquantbot.server.core.public_beta_state import (
    PublicBetaState,
)
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import FalconGateway
from projects.polymarket.polyquantbot.server.storage.capital_mode_confirmation_store import (
    CapitalModeConfirmation,
    CapitalModeConfirmationStore,
)


# ── Shared env fixtures ───────────────────────────────────────────────────────

_ALL_GATES_ON = {
    "TRADING_MODE": "LIVE",
    "ENABLE_LIVE_TRADING": "true",
    "CAPITAL_MODE_CONFIRMED": "true",
    "RISK_CONTROLS_VALIDATED": "true",
    "EXECUTION_PATH_VALIDATED": "true",
    "SECURITY_HARDENING_VALIDATED": "true",
}

_ALL_GATES_OFF = {
    "TRADING_MODE": "PAPER",
    "ENABLE_LIVE_TRADING": "false",
    "CAPITAL_MODE_CONFIRMED": "false",
    "RISK_CONTROLS_VALIDATED": "false",
    "EXECUTION_PATH_VALIDATED": "false",
    "SECURITY_HARDENING_VALIDATED": "false",
}

_OPERATOR_API_KEY = "test_operator_api_key"
_OPERATOR_HEADERS = {"X-Operator-Api-Key": _OPERATOR_API_KEY}


# ── In-memory stub DB matching DatabaseClient._execute/_fetch interface ──────


class _StubDB:
    """Test-only DB that records every call and serves rows from a fake table."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.executes: list[tuple[str, tuple]] = []
        self.fetches: list[tuple[str, tuple]] = []
        self.fail_execute: bool = False
        self.fail_fetch: bool = False

    async def _execute(self, sql: str, *args: Any, op_label: str = "execute") -> bool:
        self.executes.append((sql, args))
        if self.fail_execute:
            return False
        sql_l = sql.strip().lower()
        if sql_l.startswith("insert into capital_mode_confirmations"):
            (cid, op_id, mode, token, snap_json, confirmed_at) = args
            try:
                snapshot = json.loads(snap_json)
            except Exception:
                snapshot = {}
            self.rows.append(
                {
                    "confirmation_id": cid,
                    "operator_id": op_id,
                    "mode": mode,
                    "acknowledgment_token": token,
                    "upstream_gates_snapshot": snapshot,
                    "confirmed_at": confirmed_at,
                    "revoked_at": None,
                    "revoked_by": None,
                    "revoke_reason": None,
                }
            )
            return True
        if sql_l.startswith("update capital_mode_confirmations"):
            (revoked_at, revoked_by, reason, cid) = args
            for row in self.rows:
                if row["confirmation_id"] == cid and row["revoked_at"] is None:
                    row["revoked_at"] = revoked_at
                    row["revoked_by"] = revoked_by
                    row["revoke_reason"] = reason
                    return True
            return False
        return True

    async def _fetch(
        self, sql: str, *args: Any, op_label: str = "fetch"
    ) -> list[dict[str, Any]]:
        self.fetches.append((sql, args))
        if self.fail_fetch:
            return []
        sql_l = sql.strip().lower()
        if "from capital_mode_confirmations" in sql_l and "limit 1" in sql_l:
            mode = args[0]
            active = [
                r for r in self.rows if r["mode"] == mode and r["revoked_at"] is None
            ]
            active.sort(key=lambda r: r["confirmed_at"], reverse=True)
            return [active[0]] if active else []
        if "from capital_mode_confirmations" in sql_l:
            limit = args[0] if args else 20
            ordered = sorted(
                self.rows, key=lambda r: r["confirmed_at"], reverse=True
            )
            return ordered[:limit]
        return []


def _make_record(
    *,
    confirmation_id: str = "cid_001",
    operator_id: str = "op_alice",
    mode: str = "LIVE",
    token: str = "tok_abc",
    revoked: bool = False,
) -> CapitalModeConfirmation:
    now = datetime.now(timezone.utc)
    return CapitalModeConfirmation(
        confirmation_id=confirmation_id,
        operator_id=operator_id,
        mode=mode,
        acknowledgment_token=token,
        upstream_gates_snapshot={"trading_mode": mode, "enable_live_trading": True},
        confirmed_at=now,
        revoked_at=now if revoked else None,
        revoked_by="op_bob" if revoked else None,
        revoke_reason="ops_drill" if revoked else None,
    )


def _make_falcon() -> FalconGateway:
    settings = FalconSettings(
        enabled=False, api_key="", base_url="http://localhost", timeout_seconds=10
    )
    return FalconGateway(settings)


def _make_app(store: CapitalModeConfirmationStore | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(build_public_beta_router(falcon=_make_falcon()))
    if store is not None:
        app.state.capital_mode_confirmation_store = store
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _reset_pending_tokens():
    _PENDING_CAPITAL_CONFIRMS.clear()
    yield
    _PENDING_CAPITAL_CONFIRMS.clear()


# ── P8E-01 .. P8E-05: CapitalModeConfirmationStore unit tests ─────────────────


@pytest.mark.asyncio
async def test_p8e_01_store_insert_returns_record() -> None:
    """P8E-01: store.insert returns persisted CapitalModeConfirmation on success."""
    store = CapitalModeConfirmationStore(db=_StubDB())  # type: ignore[arg-type]
    record = await store.insert(
        operator_id="op_alice",
        mode="LIVE",
        acknowledgment_token="tok_abc",
        upstream_gates_snapshot={"enable_live_trading": True},
    )
    assert record is not None
    assert record.operator_id == "op_alice"
    assert record.mode == "LIVE"
    assert record.acknowledgment_token == "tok_abc"
    assert record.upstream_gates_snapshot == {"enable_live_trading": True}
    assert record.revoked_at is None
    assert record.is_active is True


@pytest.mark.asyncio
async def test_p8e_02_store_get_active_returns_none_when_empty() -> None:
    """P8E-02: store.get_active returns None when no row exists."""
    store = CapitalModeConfirmationStore(db=_StubDB())  # type: ignore[arg-type]
    assert await store.get_active("LIVE") is None


@pytest.mark.asyncio
async def test_p8e_03_store_get_active_returns_latest_unrevoked() -> None:
    """P8E-03: store.get_active returns most-recent unrevoked row for the mode."""
    db = _StubDB()
    store = CapitalModeConfirmationStore(db=db)  # type: ignore[arg-type]
    first = await store.insert(
        operator_id="op_alice",
        mode="LIVE",
        acknowledgment_token="t1",
        upstream_gates_snapshot={},
    )
    assert first is not None
    # Force a later confirmed_at on the second row.
    await asyncio.sleep(0.01)
    second = await store.insert(
        operator_id="op_bob",
        mode="LIVE",
        acknowledgment_token="t2",
        upstream_gates_snapshot={},
    )
    assert second is not None
    active = await store.get_active("LIVE")
    assert active is not None
    assert active.confirmation_id == second.confirmation_id


@pytest.mark.asyncio
async def test_p8e_04_store_revoke_latest_clears_active() -> None:
    """P8E-04: store.revoke_latest revokes the active row; get_active then returns None."""
    db = _StubDB()
    store = CapitalModeConfirmationStore(db=db)  # type: ignore[arg-type]
    inserted = await store.insert(
        operator_id="op_alice",
        mode="LIVE",
        acknowledgment_token="t1",
        upstream_gates_snapshot={},
    )
    assert inserted is not None
    revoked = await store.revoke_latest(
        mode="LIVE", revoked_by="op_bob", reason="ops_drill"
    )
    assert revoked is not None
    assert revoked.confirmation_id == inserted.confirmation_id
    assert revoked.revoked_by == "op_bob"
    assert revoked.revoke_reason == "ops_drill"
    assert await store.get_active("LIVE") is None


@pytest.mark.asyncio
async def test_p8e_05_store_revoke_latest_returns_none_when_no_active() -> None:
    """P8E-05: store.revoke_latest returns None when no active row exists."""
    store = CapitalModeConfirmationStore(db=_StubDB())  # type: ignore[arg-type]
    revoked = await store.revoke_latest(
        mode="LIVE", revoked_by="op_alice", reason="nothing_to_revoke"
    )
    assert revoked is None


# ── P8E-06 .. P8E-08: CapitalModeConfig.is_capital_mode_fully_allowed ─────────


@pytest.mark.asyncio
async def test_p8e_06_fully_allowed_blocked_when_env_gates_missing() -> None:
    """P8E-06: env gates not all set -> (False, missing-gates reason)."""
    db = _StubDB()
    store = CapitalModeConfirmationStore(db=db)  # type: ignore[arg-type]
    with patch.dict(os.environ, _ALL_GATES_OFF, clear=False):
        cfg = CapitalModeConfig.from_env()
    ok, reason = await cfg.is_capital_mode_fully_allowed(store)
    assert ok is False
    assert reason is not None
    assert "capital_mode" in reason


@pytest.mark.asyncio
async def test_p8e_07_fully_allowed_blocked_without_receipt() -> None:
    """P8E-07: env all set but no DB row -> (False, capital_mode_no_active_receipt)."""
    db = _StubDB()
    store = CapitalModeConfirmationStore(db=db)  # type: ignore[arg-type]
    with patch.dict(os.environ, _ALL_GATES_ON, clear=False):
        cfg = CapitalModeConfig.from_env()
    ok, reason = await cfg.is_capital_mode_fully_allowed(store)
    assert ok is False
    assert reason == "capital_mode_no_active_receipt"


@pytest.mark.asyncio
async def test_p8e_08_fully_allowed_passes_with_env_and_receipt() -> None:
    """P8E-08: env all set + active receipt -> (True, None)."""
    db = _StubDB()
    store = CapitalModeConfirmationStore(db=db)  # type: ignore[arg-type]
    await store.insert(
        operator_id="op_alice",
        mode="LIVE",
        acknowledgment_token="tok_x",
        upstream_gates_snapshot={"enable_live_trading": True},
    )
    with patch.dict(os.environ, _ALL_GATES_ON, clear=False):
        cfg = CapitalModeConfig.from_env()
    ok, reason = await cfg.is_capital_mode_fully_allowed(store)
    assert ok is True
    assert reason is None


# ── P8E-09 .. P8E-10: LiveExecutionGuard.check_with_receipt ───────────────────


class _StubProvider:
    """WalletFinancialProvider stub returning non-zero financial fields."""

    def get_balance_usd(self, wallet_id: str) -> float:
        return 5_000.0

    def get_exposure_pct(self, wallet_id: str) -> float:
        return 0.05

    def get_drawdown_pct(self, wallet_id: str) -> float:
        return 0.01


@pytest.mark.asyncio
async def test_p8e_09_check_with_receipt_blocks_when_no_receipt() -> None:
    """P8E-09: check_with_receipt raises capital_mode_no_active_receipt when env passes but DB empty."""
    db = _StubDB()
    store = CapitalModeConfirmationStore(db=db)  # type: ignore[arg-type]
    with patch.dict(os.environ, _ALL_GATES_ON, clear=False):
        cfg = CapitalModeConfig.from_env()
    guard = LiveExecutionGuard(config=cfg)
    state = PublicBetaState()
    state.mode = "live"
    state.kill_switch = False
    with patch.dict(os.environ, _ALL_GATES_ON, clear=False):
        with pytest.raises(LiveExecutionBlockedError) as exc_info:
            await guard.check_with_receipt(
                state, store=store, provider=_StubProvider()
            )
    assert exc_info.value.reason == "capital_mode_no_active_receipt"


@pytest.mark.asyncio
async def test_p8e_10_check_with_receipt_passes_with_full_chain() -> None:
    """P8E-10: env + receipt + non-zero provider -> guard passes without raising."""
    db = _StubDB()
    store = CapitalModeConfirmationStore(db=db)  # type: ignore[arg-type]
    await store.insert(
        operator_id="op_alice",
        mode="LIVE",
        acknowledgment_token="tok_x",
        upstream_gates_snapshot={"enable_live_trading": True},
    )
    with patch.dict(os.environ, _ALL_GATES_ON, clear=False):
        cfg = CapitalModeConfig.from_env()
    guard = LiveExecutionGuard(config=cfg)
    state = PublicBetaState()
    state.mode = "live"
    state.kill_switch = False
    with patch.dict(os.environ, _ALL_GATES_ON, clear=False):
        await guard.check_with_receipt(
            state, store=store, provider=_StubProvider()
        )


# ── P8E-11 .. P8E-15: Backend route tests ────────────────────────────────────


def test_p8e_11_confirm_step1_issues_token_and_snapshot() -> None:
    """P8E-11: POST /beta/capital_mode_confirm step 1 (no token) returns token + snapshot."""
    db = _StubDB()
    store = CapitalModeConfirmationStore(db=db)  # type: ignore[arg-type]
    env = {**_ALL_GATES_ON, "CRUSADER_OPERATOR_API_KEY": _OPERATOR_API_KEY}
    with patch.dict(os.environ, env, clear=False):
        client = _make_app(store=store)
        resp = client.post(
            "/beta/capital_mode_confirm",
            json={"operator_id": "op_alice"},
            headers=_OPERATOR_HEADERS,
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["stage"] == "token_issued"
    assert isinstance(body["acknowledgment_token"], str)
    assert len(body["acknowledgment_token"]) >= 16
    assert body["snapshot"]["enable_live_trading"] is True
    # No DB row yet — only step 2 commits.
    assert db.rows == []


def test_p8e_12_confirm_rejects_with_409_when_env_gates_missing() -> None:
    """P8E-12: POST returns 409 with missing-gates list when env not all set."""
    db = _StubDB()
    store = CapitalModeConfirmationStore(db=db)  # type: ignore[arg-type]
    # All gates off except TRADING_MODE=LIVE → missing-gates reason should fire.
    env = {
        **_ALL_GATES_OFF,
        "TRADING_MODE": "LIVE",
        "CRUSADER_OPERATOR_API_KEY": _OPERATOR_API_KEY,
    }
    with patch.dict(os.environ, env, clear=False):
        client = _make_app(store=store)
        resp = client.post(
            "/beta/capital_mode_confirm",
            json={"operator_id": "op_alice"},
            headers=_OPERATOR_HEADERS,
        )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["outcome"] == "rejected_missing_gates"
    assert "ENABLE_LIVE_TRADING" in detail["missing"]
    assert "CAPITAL_MODE_CONFIRMED" in detail["missing"]


def test_p8e_13_confirm_step2_commits_receipt() -> None:
    """P8E-13: POST step 2 (with valid token) inserts receipt + returns committed stage."""
    db = _StubDB()
    store = CapitalModeConfirmationStore(db=db)  # type: ignore[arg-type]
    env = {**_ALL_GATES_ON, "CRUSADER_OPERATOR_API_KEY": _OPERATOR_API_KEY}
    with patch.dict(os.environ, env, clear=False):
        client = _make_app(store=store)
        # Step 1
        first = client.post(
            "/beta/capital_mode_confirm",
            json={"operator_id": "op_alice"},
            headers=_OPERATOR_HEADERS,
        )
        token = first.json()["acknowledgment_token"]
        # Step 2
        resp = client.post(
            "/beta/capital_mode_confirm",
            json={"operator_id": "op_alice", "acknowledgment_token": token},
            headers=_OPERATOR_HEADERS,
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["stage"] == "committed"
    assert body["mode"] == "LIVE"
    assert body["operator_id"] == "op_alice"
    # DB row inserted; pending entry cleared.
    assert len(db.rows) == 1
    assert db.rows[0]["operator_id"] == "op_alice"
    assert "op_alice" not in _PENDING_CAPITAL_CONFIRMS


def test_p8e_14_confirm_step2_rejects_token_mismatch() -> None:
    """P8E-14: POST step 2 with wrong token returns 409 rejected_token_mismatch."""
    db = _StubDB()
    store = CapitalModeConfirmationStore(db=db)  # type: ignore[arg-type]
    env = {**_ALL_GATES_ON, "CRUSADER_OPERATOR_API_KEY": _OPERATOR_API_KEY}
    with patch.dict(os.environ, env, clear=False):
        client = _make_app(store=store)
        # Step 1 to seed pending entry
        first = client.post(
            "/beta/capital_mode_confirm",
            json={"operator_id": "op_alice"},
            headers=_OPERATOR_HEADERS,
        )
        assert first.status_code == 200
        # Step 2 with bogus token
        resp = client.post(
            "/beta/capital_mode_confirm",
            json={
                "operator_id": "op_alice",
                "acknowledgment_token": "deadbeefdeadbeef",
            },
            headers=_OPERATOR_HEADERS,
        )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["outcome"] == "rejected_token_mismatch"
    assert db.rows == []  # nothing committed


def test_p8e_15_revoke_clears_active_confirmation() -> None:
    """P8E-15: POST /beta/capital_mode_revoke marks the active row revoked."""
    db = _StubDB()
    store = CapitalModeConfirmationStore(db=db)  # type: ignore[arg-type]
    env = {**_ALL_GATES_ON, "CRUSADER_OPERATOR_API_KEY": _OPERATOR_API_KEY}
    with patch.dict(os.environ, env, clear=False):
        client = _make_app(store=store)
        # Confirm first (steps 1+2).
        first = client.post(
            "/beta/capital_mode_confirm",
            json={"operator_id": "op_alice"},
            headers=_OPERATOR_HEADERS,
        )
        token = first.json()["acknowledgment_token"]
        client.post(
            "/beta/capital_mode_confirm",
            json={"operator_id": "op_alice", "acknowledgment_token": token},
            headers=_OPERATOR_HEADERS,
        )
        # Revoke
        resp = client.post(
            "/beta/capital_mode_revoke",
            json={"revoked_by": "op_bob", "reason": "ops_drill"},
            headers=_OPERATOR_HEADERS,
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["stage"] == "revoked"
    assert body["revoked_by"] == "op_bob"
    assert body["reason"] == "ops_drill"
    # Underlying row is now revoked → next get_active returns None.
    assert db.rows[0]["revoked_by"] == "op_bob"
    assert db.rows[0]["revoked_at"] is not None


# ── P8E-16 .. P8E-21: Strict receipt enforcement at runtime call sites ───────


@pytest.mark.asyncio
async def test_p8e_16_worker_live_without_store_blocks() -> None:
    """P8E-16: PaperBetaWorker.run_once() in live mode without confirmation_store
    refuses live execution and triggers disable_live_execution.

    Proves that live runtime callers cannot bypass the receipt layer just by
    forgetting to inject the store at construction.
    """
    from unittest.mock import AsyncMock, MagicMock

    from projects.polymarket.polyquantbot.server.core.public_beta_state import (
        PublicBetaState as _PBS,
    )
    from projects.polymarket.polyquantbot.server.execution.paper_execution import (
        PaperExecutionEngine,
    )
    from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import (
        CandidateSignal,
    )
    from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import (
        PaperPortfolio,
    )
    from projects.polymarket.polyquantbot.server.risk.paper_risk_gate import (
        PaperRiskGate,
    )
    from projects.polymarket.polyquantbot.server.workers.paper_beta_worker import (
        PaperBetaWorker,
    )
    import projects.polymarket.polyquantbot.server.workers.paper_beta_worker as wmod

    state = _PBS()
    state.mode = "live"
    state.kill_switch = False
    state.autotrade_enabled = True

    cfg_env = {**_ALL_GATES_ON}
    with patch.dict(os.environ, cfg_env, clear=False):
        cfg = CapitalModeConfig.from_env()
    guard = LiveExecutionGuard(config=cfg)

    falcon = MagicMock()
    falcon.rank_candidates = AsyncMock(
        return_value=[
            CandidateSignal(
                signal_id="sig-p8e16",
                condition_id="cond-001",
                side="YES",
                edge=0.05,
                liquidity=20000.0,
                price=0.6,
            )
        ]
    )
    portfolio = PaperPortfolio()
    engine = PaperExecutionEngine(portfolio)
    worker = PaperBetaWorker(
        falcon=falcon,
        risk_gate=PaperRiskGate(),
        engine=engine,
        live_guard=guard,
        provider=_StubProvider(),
        confirmation_store=None,  # ← the gap that must be enforced
    )

    orig_state = wmod.STATE
    wmod.STATE = state
    try:
        with patch.dict(os.environ, cfg_env, clear=False):
            events = await worker.run_once()
    finally:
        wmod.STATE = orig_state

    assert events == []
    assert state.kill_switch is True
    assert "no_confirmation_store_injected" in state.last_risk_reason


@pytest.mark.asyncio
async def test_p8e_17_worker_live_with_store_no_receipt_blocks() -> None:
    """P8E-17: Worker live mode with store wired but no active receipt
    refuses with reason capital_mode_no_active_receipt."""
    from unittest.mock import AsyncMock, MagicMock

    from projects.polymarket.polyquantbot.server.core.public_beta_state import (
        PublicBetaState as _PBS,
    )
    from projects.polymarket.polyquantbot.server.execution.paper_execution import (
        PaperExecutionEngine,
    )
    from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import (
        CandidateSignal,
    )
    from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import (
        PaperPortfolio,
    )
    from projects.polymarket.polyquantbot.server.risk.paper_risk_gate import (
        PaperRiskGate,
    )
    from projects.polymarket.polyquantbot.server.workers.paper_beta_worker import (
        PaperBetaWorker,
    )
    import projects.polymarket.polyquantbot.server.workers.paper_beta_worker as wmod

    state = _PBS()
    state.mode = "live"
    state.kill_switch = False
    state.autotrade_enabled = True

    cfg_env = {**_ALL_GATES_ON}
    with patch.dict(os.environ, cfg_env, clear=False):
        cfg = CapitalModeConfig.from_env()
    guard = LiveExecutionGuard(config=cfg)

    db = _StubDB()
    store = CapitalModeConfirmationStore(db=db)  # type: ignore[arg-type]

    falcon = MagicMock()
    falcon.rank_candidates = AsyncMock(
        return_value=[
            CandidateSignal(
                signal_id="sig-p8e17",
                condition_id="cond-001",
                side="YES",
                edge=0.05,
                liquidity=20000.0,
                price=0.6,
            )
        ]
    )
    portfolio = PaperPortfolio()
    engine = PaperExecutionEngine(portfolio)
    worker = PaperBetaWorker(
        falcon=falcon,
        risk_gate=PaperRiskGate(),
        engine=engine,
        live_guard=guard,
        provider=_StubProvider(),
        confirmation_store=store,  # store wired but no row inserted
    )

    orig_state = wmod.STATE
    wmod.STATE = state
    try:
        with patch.dict(os.environ, cfg_env, clear=False):
            events = await worker.run_once()
    finally:
        wmod.STATE = orig_state

    assert events == []
    assert state.kill_switch is True
    assert "capital_mode_no_active_receipt" in state.last_risk_reason


def test_p8e_18_adapter_mode_live_without_store_raises() -> None:
    """P8E-18: ClobExecutionAdapter mode='live' without confirmation_store
    raises ValueError at construction. Fail-closed default for production live."""
    from projects.polymarket.polyquantbot.server.execution.clob_execution_adapter import (
        ClobExecutionAdapter,
    )
    from projects.polymarket.polyquantbot.server.execution.mock_clob_client import (
        MockClobClient,
    )

    cfg_env = {**_ALL_GATES_ON}
    with patch.dict(os.environ, cfg_env, clear=False):
        cfg = CapitalModeConfig.from_env()

    with pytest.raises(ValueError) as exc_info:
        ClobExecutionAdapter(
            config=cfg,
            client=MockClobClient(order_id="x", status="MATCHED"),
            mode="live",
            confirmation_store=None,
        )
    assert "confirmation_store" in str(exc_info.value)
    assert "P8-E receipt layer" in str(exc_info.value)


def test_p8e_19_adapter_mode_live_with_store_and_receipt_submits() -> None:
    """P8E-19: ClobExecutionAdapter mode='live' with store + active receipt
    + all env gates set submits an order successfully — full chain pass."""
    from projects.polymarket.polyquantbot.server.execution.clob_execution_adapter import (
        ClobExecutionAdapter,
        ClobOrderResult,
    )
    from projects.polymarket.polyquantbot.server.execution.mock_clob_client import (
        MockClobClient,
    )
    from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import (
        CandidateSignal,
    )

    cfg_env = {**_ALL_GATES_ON}
    with patch.dict(os.environ, cfg_env, clear=False):
        cfg = CapitalModeConfig.from_env()

    db = _StubDB()
    store = CapitalModeConfirmationStore(db=db)  # type: ignore[arg-type]
    asyncio.run(
        store.insert(
            operator_id="op_p8e19",
            mode="LIVE",
            acknowledgment_token="p8e19_tok",
            upstream_gates_snapshot={"enable_live_trading": True},
        )
    )

    state = PublicBetaState()
    state.mode = "live"
    state.kill_switch = False

    client = MockClobClient(order_id="p8e19-001", status="MATCHED")
    adapter = ClobExecutionAdapter(
        config=cfg,
        client=client,
        mode="live",
        confirmation_store=store,
    )

    signal = CandidateSignal(
        signal_id="sig-p8e19",
        condition_id="cond-001",
        side="BUY",
        price=0.6,
        edge=0.05,
        liquidity=20000.0,
    )
    with patch.dict(os.environ, cfg_env, clear=False):
        result = asyncio.run(
            adapter.submit_order(
                state, signal, token_id="tok-p8e19", provider=_StubProvider()
            )
        )
    assert isinstance(result, ClobOrderResult)
    assert result.order_id == "p8e19-001"
    assert client.call_count == 1


@pytest.mark.asyncio
async def test_p8e_20_revoke_persistence_failure_raises() -> None:
    """P8E-20: store.revoke_latest raises CapitalModeRevokeFailedError when
    DB persistence fails after locating an active row.

    Distinguishes from the no-active case (returns None) so callers can
    treat the failure as service-unavailable rather than misleadingly
    reporting nothing-to-revoke.
    """
    from projects.polymarket.polyquantbot.server.storage.capital_mode_confirmation_store import (
        CapitalModeRevokeFailedError,
    )

    db = _StubDB()
    store = CapitalModeConfirmationStore(db=db)  # type: ignore[arg-type]
    await store.insert(
        operator_id="op_p8e20",
        mode="LIVE",
        acknowledgment_token="p8e20_tok",
        upstream_gates_snapshot={},
    )
    db.fail_execute = True

    with pytest.raises(CapitalModeRevokeFailedError) as exc_info:
        await store.revoke_latest(
            mode="LIVE", revoked_by="op_x", reason="db_outage_test"
        )
    assert "may still be in force" in str(exc_info.value)


def test_p8e_21_revoke_route_returns_503_on_persistence_failure() -> None:
    """P8E-21: POST /beta/capital_mode_revoke returns 503 when the store
    raises CapitalModeRevokeFailedError instead of misreporting no_active."""
    db = _StubDB()
    store = CapitalModeConfirmationStore(db=db)  # type: ignore[arg-type]
    env = {**_ALL_GATES_ON, "CRUSADER_OPERATOR_API_KEY": _OPERATOR_API_KEY}
    with patch.dict(os.environ, env, clear=False):
        client = _make_app(store=store)
        # Seed an active confirmation directly (bypass step1/step2 dance).
        first = client.post(
            "/beta/capital_mode_confirm",
            json={"operator_id": "op_alice"},
            headers=_OPERATOR_HEADERS,
        )
        token = first.json()["acknowledgment_token"]
        client.post(
            "/beta/capital_mode_confirm",
            json={"operator_id": "op_alice", "acknowledgment_token": token},
            headers=_OPERATOR_HEADERS,
        )
        # Now simulate DB outage on revoke.
        db.fail_execute = True
        resp = client.post(
            "/beta/capital_mode_revoke",
            json={"revoked_by": "op_bob", "reason": "incident_drill"},
            headers=_OPERATOR_HEADERS,
        )
    assert resp.status_code == 503, resp.text
    detail = resp.json()["detail"]
    assert detail["outcome"] == "persistence_failed"
    assert detail["reason"] == "capital_mode_revoke_persistence_failed"
    assert "may still be in force" in detail["warning"]
