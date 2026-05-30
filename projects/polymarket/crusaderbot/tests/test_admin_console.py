"""WebTrader Admin console + global strategy on/off — hermetic tests."""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.webtrader.backend import router as r
from projects.polymarket.crusaderbot.webtrader.backend.schemas import StrategyToggleRequest
from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as job


# ── fake pool helpers ─────────────────────────────────────────────────────────


def _ctx(value=None):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _pool(conn):
    p = MagicMock()
    p.acquire = MagicMock(return_value=_ctx(conn))
    return p


# ── global strategy gate (scanner) ────────────────────────────────────────────


def test_preset_allows_blocks_globally_disabled():
    """A globally-disabled strategy is never allowed, regardless of preset."""
    original = job._GLOBALLY_DISABLED_STRATEGIES
    try:
        job._GLOBALLY_DISABLED_STRATEGIES = frozenset({"late_entry_v3"})
        # late_entry_v3 would normally be allowed under a candle preset
        assert job._preset_allows("close_sweep", "late_entry_v3") is False
    finally:
        job._GLOBALLY_DISABLED_STRATEGIES = original


def test_preset_allows_default_when_none_disabled():
    """Each candle preset fires exactly its backing strategy when no global
    toggle is OFF — and nothing else."""
    original = job._GLOBALLY_DISABLED_STRATEGIES
    try:
        job._GLOBALLY_DISABLED_STRATEGIES = frozenset()
        for preset in ("close_sweep", "safe_close", "flip_hunter"):
            assert job._preset_allows(preset, "late_entry_v3") is True
            assert job._preset_allows(preset, "signal_following") is False
    finally:
        job._GLOBALLY_DISABLED_STRATEGIES = original


def test_refresh_disabled_strategies_fail_safe():
    """A DB error must NOT change the disabled set (fail-safe)."""
    original = job._GLOBALLY_DISABLED_STRATEGIES
    try:
        job._GLOBALLY_DISABLED_STRATEGIES = frozenset({"x"})
        boom = MagicMock()
        boom.acquire = MagicMock(side_effect=RuntimeError("db down"))
        with patch.object(job, "get_pool", return_value=boom):
            asyncio.run(job._refresh_disabled_strategies())
        assert job._GLOBALLY_DISABLED_STRATEGIES == frozenset({"x"})  # unchanged
    finally:
        job._GLOBALLY_DISABLED_STRATEGIES = original


def test_signal_following_loader_has_global_gate():
    """The signal_following loader query must fail-safe gate on the strategies table."""
    src = inspect.getsource(job)
    assert "NOT EXISTS" in src
    assert "FROM strategies st" in src
    assert "st.enabled = FALSE" in src


def test_run_once_refreshes_toggle():
    src = inspect.getsource(job.run_once)
    assert "_refresh_disabled_strategies()" in src


# ── _require_admin ────────────────────────────────────────────────────────────


def test_require_admin_allows_admin():
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value="admin")
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        out = asyncio.run(r._require_admin({"user_id": str(uuid4())}))
    assert out["user_id"]


def test_require_admin_rejects_non_admin():
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value="user")
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        with pytest.raises(Exception) as exc:
            asyncio.run(r._require_admin({"user_id": str(uuid4())}))
    assert "403" in str(exc.value) or "admin only" in str(exc.value)


# ── admin_strategies ──────────────────────────────────────────────────────────


def test_admin_strategies_returns_full_roster_default_on():
    conn = MagicMock()
    # only one explicit row (disabled); the rest default to ON
    conn.fetch = AsyncMock(return_value=[{"name": "copy_trade", "enabled": False}])
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        out = asyncio.run(r.admin_strategies({"user_id": "x"}))
    names = {s["name"]: s["enabled"] for s in out["strategies"]}
    assert names["copy_trade"] is False           # explicit disabled
    assert names["late_entry_v3"] is True          # default ON (no row)
    assert len(out["strategies"]) == len(r._ADMIN_STRATEGIES)


# ── admin_toggle_strategy ─────────────────────────────────────────────────────


def test_admin_toggle_rejects_unknown_strategy():
    body = StrategyToggleRequest(name="not_a_strategy", enabled=False)
    with pytest.raises(Exception) as exc:
        asyncio.run(r.admin_toggle_strategy(body, {"user_id": str(uuid4())}))
    assert "unknown strategy" in str(exc.value) or "400" in str(exc.value)


def test_admin_toggle_writes_and_audits():
    body = StrategyToggleRequest(name="late_entry_v3", enabled=False)
    conn = MagicMock()
    conn.execute = AsyncMock()
    with patch.object(r, "get_pool", return_value=_pool(conn)), \
         patch.object(r.audit, "write", AsyncMock()) as mock_audit:
        out = asyncio.run(r.admin_toggle_strategy(body, {"user_id": str(uuid4())}))
    assert out == {"name": "late_entry_v3", "enabled": False}
    conn.execute.assert_awaited_once()
    mock_audit.assert_awaited_once()


# ── /me role ──────────────────────────────────────────────────────────────────


def test_admin_overview_exposes_polymarket_config():
    """Overview must surface funder/sig-type/creds so the operator can verify
    the Polymarket trading config actually loaded (it lives in env, not the DB)."""
    import inspect
    src = inspect.getsource(r.admin_overview)
    assert '"polymarket"' in src
    assert "funder_address" in src
    assert "signature_type" in src
    assert "creds_source" in src
    assert "effective_credentials" in src


def test_get_me_includes_role_and_is_admin():
    conn = MagicMock()
    async def fetchrow(q, *a):
        # /me runs a second query for user_settings.trading_mode.
        if "user_settings" in q:
            return {"trading_mode": "paper"}
        return {"email": "a@b.com", "username": "u", "telegram_user_id": 1, "role": "admin"}
    conn.fetchrow = fetchrow
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        out = asyncio.run(r.get_me({"user_id": "x", "first_name": "A"}))
    assert out["role"] == "admin"
    assert out["is_admin"] is True


# ── get_autotrade reflects global strategy on/off ─────────────────────────────

def _autotrade_settings_row(preset):
    return {
        "risk_profile": "balanced", "capital_alloc_pct": 0.4, "tp_pct": 0.2,
        "sl_pct": 0.15, "active_preset": preset, "category_filters": None,
        "min_liquidity": None, "max_resolution_days": None, "min_volume_24h": None,
        "slippage_tolerance_pct": None, "selected_timeframe": "5m",
        "selected_assets": None, "max_per_trade_mode": "auto",
        "max_per_trade_usdc": None, "max_per_trade_pct": None,
        "daily_loss_override": None, "max_drawdown_pct": None,
    }


def _run_get_autotrade(preset, strategy_enabled):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"auto_trade_on": True},
        _autotrade_settings_row(preset),
        {"equity_usdc": 100.0},
    ])
    conn.fetchval = AsyncMock(return_value=strategy_enabled)
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        return asyncio.run(r.get_autotrade({"user_id": str(uuid4())}))


def test_get_autotrade_flags_globally_disabled_preset():
    """close_sweep → late_entry_v3; when globally OFF, dashboard flag is False."""
    out = _run_get_autotrade("close_sweep", False)
    assert out.active_preset == "close_sweep"
    assert out.active_preset_globally_enabled is False


def test_get_autotrade_globally_enabled_when_strategy_on():
    out = _run_get_autotrade("close_sweep", True)
    assert out.active_preset_globally_enabled is True


def test_get_autotrade_globally_enabled_when_no_strategy_row():
    """Missing strategies row (never toggled) defaults to enabled."""
    out = _run_get_autotrade("close_sweep", None)
    assert out.active_preset_globally_enabled is True


# ── /autotrade/preset-availability picker filter ──────────────────────────────


def test_preset_availability_returns_one_entry_per_mapped_preset():
    """Endpoint surfaces every preset in _PRESET_TO_STRATEGY with its enabled bit."""
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[
        {"name": "late_entry_v3", "enabled": False},
    ])
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        out = asyncio.run(r.get_preset_availability({"user_id": "x"}))
    keys = {p["key"] for p in out["presets"]}
    assert keys == set(r._PRESET_TO_STRATEGY.keys())
    # Every preset routes to late_entry_v3 → all disabled when that strategy is OFF.
    assert all(p["enabled"] is False for p in out["presets"])


def test_preset_availability_default_enabled_when_no_row():
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[])
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        out = asyncio.run(r.get_preset_availability({"user_id": "x"}))
    assert all(p["enabled"] is True for p in out["presets"])


def test_preset_availability_includes_strategies_map():
    """strategies payload covers every admin-toggle key so the frontend can
    gate non-preset features (Copy Trade tab) without a separate fetch."""
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[
        {"name": "copy_trade", "enabled": False},
    ])
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        out = asyncio.run(r.get_preset_availability({"user_id": "x"}))
    assert set(out["strategies"].keys()) == set(r._ADMIN_STRATEGIES)
    assert out["strategies"]["copy_trade"] is False
    # FAIL-SAFE: a missing row defaults to enabled=True.
    assert out["strategies"]["late_entry_v3"] is True
    assert out["strategies"]["signal_following"] is True


def test_preset_availability_strategies_default_enabled_on_db_error():
    """A DB blip must NOT 500 — strategies map reports every admin key as
    enabled=True instead, consistent with the presets fail-safe."""
    pool = MagicMock()
    pool.acquire = MagicMock(side_effect=RuntimeError("db down"))
    with patch.object(r, "get_pool", return_value=pool):
        out = asyncio.run(r.get_preset_availability({"user_id": "x"}))
    assert all(out["strategies"][name] is True for name in r._ADMIN_STRATEGIES)


def test_preset_params_roster_matches_admin_presets_after_cleanup():
    """activate_preset must reject any archived legacy key. After WARP/R00T
    cleanup, only the 3 candle presets are valid — a stale client persisting
    `signal_sniper` / `full_auto` / `ensemble` would create a silent no-op
    (scanner emits nothing, dashboard can't mark it PAUSED). Pinned here so a
    future map widening is intentional."""
    assert set(r._PRESET_PARAMS.keys()) == {"close_sweep", "safe_close", "flip_hunter"}
    assert set(r._PRESET_TO_STRATEGY.keys()) == set(r._PRESET_PARAMS.keys())


def test_preset_availability_fail_safe_on_db_error():
    """A DB blip must NOT 500 — every preset reports enabled=True instead."""
    pool = MagicMock()
    pool.acquire = MagicMock(side_effect=RuntimeError("db down"))
    with patch.object(r, "get_pool", return_value=pool):
        out = asyncio.run(r.get_preset_availability({"user_id": "x"}))
    assert all(p["enabled"] is True for p in out["presets"])
    assert len(out["presets"]) == len(r._PRESET_TO_STRATEGY)


def test_preset_to_strategy_maps_candle_presets_to_late_entry():
    assert r._PRESET_TO_STRATEGY["close_sweep"] == "late_entry_v3"
    assert r._PRESET_TO_STRATEGY["safe_close"] == "late_entry_v3"
    assert r._PRESET_TO_STRATEGY["flip_hunter"] == "late_entry_v3"


# ── /dashboard mirrors active_preset_globally_enabled + alerts_ack_at ─────────
# The desktop sidebar System Status block and the AlertCenter visibleAlerts
# filter both read these fields from /dashboard. Previously SCANNER kept
# saying RUNNING during an admin pause because the dashboard payload had no
# such flag, and "Mark all read" was localStorage-only — clearing storage or
# switching devices resurfaced every alert.


def _dashboard_settings_row(active_preset, alerts_ack_at=None):
    return {
        "risk_profile": "balanced",
        "capital_alloc_pct": 0.4,
        "tp_pct": 0.2,
        "sl_pct": 0.15,
        "active_preset": active_preset,
        "trading_mode": "paper",
        "alerts_ack_at": alerts_ack_at,
    }


def _run_get_dashboard(active_preset, *, strategy_enabled=True, alerts_ack_at=None):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"auto_trade_on": True},
        _dashboard_settings_row(active_preset, alerts_ack_at),
        {"balance_usdc": 100.0},
        {"total": 0, "wins": 0, "losses": 0},
    ])
    # fetchval call order in get_dashboard:
    #   open_count → pnl_today → pnl_7d → pnl_alltime → signals_today
    #   → (only if active_preset set) strategies.enabled lookup.
    fetchval_returns = [0, 0, 0, 0, 0]
    if active_preset:
        fetchval_returns.append(strategy_enabled)
    conn.fetchval = AsyncMock(side_effect=fetchval_returns)
    with patch.object(r, "get_pool", return_value=_pool(conn)), \
         patch.object(r.kill_switch, "is_active", AsyncMock(return_value=False)):
        return asyncio.run(r.get_dashboard({"user_id": str(uuid4())}))


def test_dashboard_marks_active_preset_paused_when_strategy_off():
    """SCANNER must read PAUSED (ADMIN) when the backing strategy is OFF."""
    out = _run_get_dashboard("close_sweep", strategy_enabled=False)
    assert out.active_preset_globally_enabled is False


def test_dashboard_marks_active_preset_enabled_when_strategy_on():
    out = _run_get_dashboard("close_sweep", strategy_enabled=True)
    assert out.active_preset_globally_enabled is True


def test_dashboard_globally_enabled_when_no_active_preset():
    """No preset selected → no strategies lookup, defaults to enabled=True."""
    out = _run_get_dashboard(None)
    assert out.active_preset_globally_enabled is True


def test_dashboard_surfaces_alerts_ack_at():
    """AlertCenter watermark must round-trip through the dashboard payload so
    a localStorage-clear or second-device session still respects the click."""
    from datetime import datetime, timezone
    ts = datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)
    out = _run_get_dashboard("close_sweep", alerts_ack_at=ts)
    assert out.alerts_ack_at == ts


def test_dashboard_alerts_ack_at_defaults_none():
    out = _run_get_dashboard("close_sweep")
    assert out.alerts_ack_at is None


# ── /alerts/ack-all persists the click server-side ────────────────────────────


def test_ack_all_alerts_writes_now_and_returns_iso_ts():
    """Endpoint upserts NOW() into user_settings.alerts_ack_at and returns
    the new timestamp as ISO-8601 so the client can update its filter
    immediately without waiting for the next /dashboard."""
    from datetime import datetime, timezone
    ts = datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"alerts_ack_at": ts})
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        out = asyncio.run(r.ack_all_alerts({"user_id": str(uuid4())}))
    assert out["alerts_ack_at"] == ts.isoformat()
    # Sanity: the upsert query, not a bare UPDATE — covers users without an
    # existing user_settings row.
    args = conn.fetchrow.call_args
    assert "INSERT INTO user_settings" in args.args[0]
    assert "ON CONFLICT" in args.args[0]


def test_ack_all_alerts_handles_null_return():
    """Hardened: if the upsert returns no row (shouldn't happen, but guards
    against an asyncpg edge case) the endpoint returns None instead of
    raising AttributeError on the response builder."""
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        out = asyncio.run(r.ack_all_alerts({"user_id": str(uuid4())}))
    assert out["alerts_ack_at"] is None


def test_get_autotrade_sl_only_custom_returns_null_tp():
    """Custom SL-only (tp_pct NULL in DB) must serialize tp_pct=None, not crash."""
    row = _autotrade_settings_row("close_sweep")
    row["risk_profile"] = "custom"
    row["tp_pct"] = None
    row["sl_pct"] = 0.20
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"auto_trade_on": True}, row, {"equity_usdc": 100.0},
    ])
    conn.fetchval = AsyncMock(return_value=True)
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        out = asyncio.run(r.get_autotrade({"user_id": str(uuid4())}))
    assert out.tp_pct is None
    assert out.sl_pct == 0.20


# ── admin_user_detail + admin_user_update ─────────────────────────────────────


def _admin_user_row(*, role="user", auto_on=False, paused=False):
    return {
        "id": uuid4(),
        "username": "alice",
        "email": "alice@example.com",
        "role": role,
        "auto_trade_on": auto_on,
        "paused": paused,
        "created_at": None,
        "telegram_user_id": None,
    }


def _wallet_row(balance: float = 0.0, addr: str | None = None) -> dict:
    """Mirror the columns admin_user_detail now SELECTs from `wallets`."""
    return {"balance_usdc": balance, "deposit_address": addr}


def _admin_settings_row(**overrides):
    base = {
        "trading_mode": "paper",
        "active_preset": "close_sweep",
        "risk_profile": "balanced",
        "capital_alloc_pct": 0.40,
        "tp_pct": 0.20,
        "sl_pct": 0.15,
        "max_per_trade_mode": "auto",
        "max_per_trade_usdc": None,
        "max_per_trade_pct": None,
        "selected_timeframe": "5m",
        "selected_assets": None,
    }
    base.update(overrides)
    return base


def test_admin_user_detail_returns_full_view():
    u_row = _admin_user_row()
    s_row = _admin_settings_row()
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=[u_row, s_row, _wallet_row(123.45, "0xabc")])
    conn.fetchval = AsyncMock(return_value=2)
    conn.fetch = AsyncMock(side_effect=[[], []])  # recent_trades, recent_audit
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        out = asyncio.run(r.admin_user_detail(str(u_row["id"]), {"user_id": str(uuid4())}))
    assert out.user_id == str(u_row["id"])
    assert out.username == "alice"
    assert out.trading_mode == "paper"
    assert out.active_preset == "close_sweep"
    assert out.balance_usdc == 123.45
    assert out.wallet_address == "0xabc"
    assert out.open_positions == 2
    assert out.recent_trades == []
    assert out.recent_audit == []


def test_admin_user_detail_404_when_missing():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        with pytest.raises(r.HTTPException) as exc:
            asyncio.run(r.admin_user_detail(str(uuid4()), {"user_id": str(uuid4())}))
        assert exc.value.status_code == 404


def test_admin_user_detail_400_invalid_uuid():
    with pytest.raises(r.HTTPException) as exc:
        asyncio.run(r.admin_user_detail("not-a-uuid", {"user_id": str(uuid4())}))
    assert exc.value.status_code == 400


def test_admin_user_detail_strips_telegram_local_email():
    u_row = _admin_user_row()
    u_row["email"] = "12345@telegram.local"
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=[u_row, _admin_settings_row(), None])
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetch = AsyncMock(side_effect=[[], []])
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        out = asyncio.run(r.admin_user_detail(str(u_row["id"]), {"user_id": str(uuid4())}))
    assert out.email is None


def test_admin_user_detail_missing_settings_defaults_to_paper_balanced():
    """Edge case: user exists but user_settings row absent (legacy / not-yet-bootstrapped)."""
    u_row = _admin_user_row()
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=[u_row, None, None])
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetch = AsyncMock(side_effect=[[], []])
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        out = asyncio.run(r.admin_user_detail(str(u_row["id"]), {"user_id": str(uuid4())}))
    assert out.trading_mode == "paper"
    assert out.risk_profile == "balanced"
    assert out.capital_alloc_pct == 0.40
    assert out.balance_usdc == 0.0
    assert out.wallet_address is None


def test_admin_user_update_validates_preset():
    from projects.polymarket.crusaderbot.webtrader.backend.schemas import AdminUserUpdate
    with pytest.raises(r.HTTPException) as exc:
        asyncio.run(r.admin_user_update(
            str(uuid4()),
            AdminUserUpdate(active_preset="archived_legacy_preset"),
            {"user_id": str(uuid4())},
        ))
    assert exc.value.status_code == 400
    assert "active_preset" in exc.value.detail


def test_admin_user_update_validates_risk_profile():
    from projects.polymarket.crusaderbot.webtrader.backend.schemas import AdminUserUpdate
    with pytest.raises(r.HTTPException) as exc:
        asyncio.run(r.admin_user_update(
            str(uuid4()),
            AdminUserUpdate(risk_profile="degen_mode"),
            {"user_id": str(uuid4())},
        ))
    assert exc.value.status_code == 400
    assert "risk_profile" in exc.value.detail


@pytest.mark.parametrize("field,bad,good", [
    ("capital_alloc_pct", 0.90, 0.5),  # >MAX (0.80)
    ("capital_alloc_pct", 0.0, 0.5),   # <MIN
    ("tp_pct", 15.0, 0.5),             # >MAX (10.0)
    ("sl_pct", 2.0, 0.5),              # >MAX (1.0)
    ("max_per_trade_usdc", 999.0, 100.0),  # >MAX (500)
    ("max_per_trade_pct", 0.50, 0.05),     # >MAX (0.10)
])
def test_admin_user_update_validates_numeric_bounds(field, bad, good):
    from projects.polymarket.crusaderbot.webtrader.backend.schemas import AdminUserUpdate
    with pytest.raises(r.HTTPException) as exc:
        asyncio.run(r.admin_user_update(
            str(uuid4()),
            AdminUserUpdate(**{field: bad}),
            {"user_id": str(uuid4())},
        ))
    assert exc.value.status_code == 400
    # Good value should NOT raise — validate-only (we test the patch path
    # E2E below; here just confirm the bounds gate accepts the in-range value).
    r._validate_admin_user_patch(AdminUserUpdate(**{field: good}))


def test_admin_user_update_rejects_empty_patch():
    from projects.polymarket.crusaderbot.webtrader.backend.schemas import AdminUserUpdate
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=1)
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        with pytest.raises(r.HTTPException) as exc:
            asyncio.run(r.admin_user_update(
                str(uuid4()), AdminUserUpdate(), {"user_id": str(uuid4())},
            ))
        assert exc.value.status_code == 400
        assert "empty patch" in exc.value.detail


def test_admin_user_update_404_when_target_missing():
    from projects.polymarket.crusaderbot.webtrader.backend.schemas import AdminUserUpdate
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=None)
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        with pytest.raises(r.HTTPException) as exc:
            asyncio.run(r.admin_user_update(
                str(uuid4()),
                AdminUserUpdate(active_preset="close_sweep"),
                {"user_id": str(uuid4())},
            ))
        assert exc.value.status_code == 404


def test_admin_user_update_writes_audit_and_returns_detail():
    """Happy path: valid patch → upsert executes → audit.write called →
    admin_user_detail re-fetched and returned."""
    from projects.polymarket.crusaderbot.webtrader.backend.schemas import AdminUserUpdate
    target_id = uuid4()
    actor_id = uuid4()
    u_row = _admin_user_row()
    u_row["id"] = target_id
    s_row = _admin_settings_row(active_preset="safe_close", risk_profile="aggressive")
    conn = MagicMock()
    # Order: exists-check (fetchval), execute, then detail re-fetch
    # (fetchrow x2: u_row, s_row, then fetchrow: wallet, then fetchval: open_count).
    conn.fetchval = AsyncMock(side_effect=[1, 0])  # exists, then open_count
    conn.execute = AsyncMock(return_value=None)
    conn.fetchrow = AsyncMock(side_effect=[u_row, s_row, _wallet_row(50.0, "0xdef")])
    conn.fetch = AsyncMock(side_effect=[[], []])
    audit_calls = []

    async def _fake_audit_write(**kwargs):
        audit_calls.append(kwargs)

    with patch.object(r, "get_pool", return_value=_pool(conn)), \
         patch.object(r.audit, "write", side_effect=_fake_audit_write):
        out = asyncio.run(r.admin_user_update(
            str(target_id),
            AdminUserUpdate(active_preset="safe_close", risk_profile="aggressive"),
            {"user_id": str(actor_id)},
        ))
    assert out.active_preset == "safe_close"
    assert out.risk_profile == "aggressive"
    # Audit row is scoped to the TARGET user (so admin_user_detail's per-user
    # recent-audit slice surfaces the change in that user's drawer); the actor
    # id is preserved in the payload.
    assert len(audit_calls) == 1
    assert audit_calls[0]["actor_role"] == "admin"
    assert audit_calls[0]["action"] == "admin_user_settings_update"
    assert audit_calls[0]["user_id"] == target_id
    assert audit_calls[0]["payload"]["target_user_id"] == str(target_id)
    assert audit_calls[0]["payload"]["actor_user_id"] == str(actor_id)
    assert audit_calls[0]["payload"]["patch"] == {
        "active_preset": "safe_close",
        "risk_profile": "aggressive",
    }
    # The upsert SQL must include the paper-default invariant literals when
    # creating a brand-new user_settings row (the INSERT side of ON CONFLICT).
    sql = conn.execute.call_args.args[0]
    assert "INSERT INTO user_settings" in sql
    assert "ON CONFLICT" in sql
    assert "'paper'" in sql  # paper-default invariant
    # risk_profile is part of the patch so the INSERT does NOT also literal
    # 'balanced' (would be a duplicate-column error).
    assert sql.count("risk_profile") >= 1  # at minimum, the patched column


@pytest.mark.parametrize("field", ["risk_profile", "capital_alloc_pct", "max_per_trade_mode"])
def test_admin_user_update_rejects_explicit_null_on_not_null_columns(field):
    """Pinned: explicit null on a NOT NULL column must 400 before reaching the DB
    (otherwise asyncpg would 500 with IntegrityError on the upsert)."""
    from projects.polymarket.crusaderbot.webtrader.backend.schemas import AdminUserUpdate
    body = AdminUserUpdate(**{field: None})
    with pytest.raises(r.HTTPException) as exc:
        asyncio.run(r.admin_user_update(
            str(uuid4()), body, {"user_id": str(uuid4())},
        ))
    assert exc.value.status_code == 400
    assert field in exc.value.detail
    assert "null" in exc.value.detail.lower()


def test_admin_user_update_paper_default_invariant_on_minimal_patch():
    """When patch does NOT touch risk_profile or capital_alloc_pct, the
    INSERT side of the upsert MUST still write 'paper', 'balanced', 0.40 so
    the brand-new-user branch never silently flips trading_mode to live or
    leaves NOT NULL columns missing."""
    from projects.polymarket.crusaderbot.webtrader.backend.schemas import AdminUserUpdate
    target_id = uuid4()
    u_row = _admin_user_row()
    u_row["id"] = target_id
    conn = MagicMock()
    conn.fetchval = AsyncMock(side_effect=[1, 0])
    conn.execute = AsyncMock(return_value=None)
    conn.fetchrow = AsyncMock(side_effect=[u_row, _admin_settings_row(), None])
    conn.fetch = AsyncMock(side_effect=[[], []])
    with patch.object(r, "get_pool", return_value=_pool(conn)), \
         patch.object(r.audit, "write", new=AsyncMock()):
        asyncio.run(r.admin_user_update(
            str(target_id),
            AdminUserUpdate(active_preset="close_sweep"),
            {"user_id": str(uuid4())},
        ))
    sql = conn.execute.call_args.args[0]
    assert "'paper'" in sql
    assert "'balanced'" in sql
    assert "0.40" in sql
