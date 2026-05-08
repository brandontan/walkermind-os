"""Tests for the /ops HTML dashboard + kill / resume buttons.

The tests build a minimal FastAPI app that mounts only the ``api.ops``
router so we can exercise the routes without spinning up the full
lifespan (DB pool, Telegram bot, scheduler). Every external call —
``run_health_checks``, ``kill_switch.set_active``, ``audit.write``, the
DB pool — is patched.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from projects.polymarket.crusaderbot.api import ops as api_ops


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(api_ops.router)
    return app


def _ok_health():
    return {
        "status": "ok",
        "service": "CrusaderBot",
        "checks": {
            "database": "ok",
            "telegram": "ok",
            "alchemy_rpc": "ok",
            "alchemy_ws": "ok",
        },
        "ready": True,
    }


OPS_TOKEN = "demo-secret-token"


def _settings(*, paper: bool = True, version: str | None = "abc1234",
              ops_secret: str | None = OPS_TOKEN):
    return MagicMock(
        ENABLE_LIVE_TRADING=not paper,
        EXECUTION_PATH_VALIDATED=not paper,
        CAPITAL_MODE_CONFIRMED=not paper,
        APP_VERSION=version,
        OPS_SECRET=ops_secret,
    )


_UNSET = object()


def _patch_route_io(monkeypatch, *, kill_active: bool = False,
                    user_count: int | None = 12,
                    audit_rows=_UNSET,
                    health=None,
                    settings=None):
    """Patch every external dependency the route relies on."""
    if health is None:
        health = _ok_health()
    if settings is None:
        settings = _settings()
    if audit_rows is _UNSET:
        audit_rows = []

    async def _fake_run_health():
        return health

    async def _fake_count():
        return user_count

    async def _fake_audit_tail(limit=10):
        return audit_rows

    async def _fake_kill_state():
        return "ACTIVE" if kill_active else "PAUSED"

    monkeypatch.setattr(api_ops, "run_health_checks", _fake_run_health)
    monkeypatch.setattr(api_ops, "_count_users", _fake_count)
    monkeypatch.setattr(api_ops, "_fetch_audit_tail", _fake_audit_tail)
    monkeypatch.setattr(api_ops, "_kill_switch_state", _fake_kill_state)
    monkeypatch.setattr(api_ops, "get_settings", lambda: settings)


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_format_uptime_renders_seconds_minutes_hours_days():
    assert api_ops._format_uptime(5) == "5s"
    assert api_ops._format_uptime(75) == "1m 15s"
    assert api_ops._format_uptime(3 * 3600 + 25 * 60) == "3h 25m"
    assert api_ops._format_uptime(2 * 86400 + 3 * 3600 + 5 * 60) == "2d 3h 5m"


def test_resolve_mode_paper_unless_all_guards_open(monkeypatch):
    monkeypatch.setattr(api_ops, "get_settings", lambda: _settings(paper=True))
    assert api_ops._resolve_mode() == "paper"
    monkeypatch.setattr(api_ops, "get_settings", lambda: _settings(paper=False))
    assert api_ops._resolve_mode() == "live"


def test_resolve_version_falls_back_to_unknown(monkeypatch):
    monkeypatch.setattr(api_ops, "get_settings", lambda: _settings(version=None))
    assert api_ops._resolve_version() == "unknown"
    monkeypatch.setattr(api_ops, "get_settings", lambda: _settings(version="  "))
    assert api_ops._resolve_version() == "unknown"
    monkeypatch.setattr(api_ops, "get_settings", lambda: _settings(version="v9"))
    assert api_ops._resolve_version() == "v9"


def test_badge_renders_state_classes():
    assert 'class="badge ok"' in api_ops._badge("ok")
    assert 'class="badge fail"' in api_ops._badge("error: down")
    assert 'class="badge warn"' in api_ops._badge("degraded")


def test_badge_escapes_state_text():
    out = api_ops._badge("<script>alert(1)</script>")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_render_audit_rows_handles_none_and_empty():
    assert "N/A" in api_ops._render_audit_rows(None)
    assert "no audit entries" in api_ops._render_audit_rows([])


def test_render_audit_rows_escapes_action_and_actor():
    from datetime import datetime, timezone
    rows = [{
        "ts": datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc),
        "action": "<script>x</script>",
        "actor_role": "<b>boss</b>",
    }]
    out = api_ops._render_audit_rows(rows)
    assert "<script>x</script>" not in out
    assert "&lt;script&gt;" in out
    assert "&lt;b&gt;boss&lt;/b&gt;" in out


# ---------------------------------------------------------------------------
# GET /ops
# ---------------------------------------------------------------------------


def test_ops_route_returns_200_html(monkeypatch):
    _patch_route_io(monkeypatch)
    client = TestClient(_build_app())
    r = client.get("/ops")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    # Brief-required content present:
    assert "CrusaderBot" in body
    assert "Mode" in body and "PAPER" in body
    assert "Active users" in body
    assert "Kill switch" in body
    assert "Health checks" in body
    assert "database" in body and "telegram" in body
    assert "alchemy_rpc" in body and "alchemy_ws" in body
    assert "Audit log" in body
    assert "auto-refresh" in body
    # Auto-refresh meta tag present.
    assert '<meta http-equiv="refresh"' in body
    # Both action forms present.
    assert 'action="/ops/kill"' in body
    assert 'action="/ops/resume"' in body


def test_ops_route_renders_kill_state_active(monkeypatch):
    _patch_route_io(monkeypatch, kill_active=True)
    client = TestClient(_build_app())
    body = client.get("/ops").text
    assert ">ACTIVE<" in body  # kill switch label rendered
    assert 'class="badge fail"' in body  # red badge while killed


def test_ops_route_renders_kill_state_paused(monkeypatch):
    _patch_route_io(monkeypatch, kill_active=False)
    client = TestClient(_build_app())
    body = client.get("/ops").text
    assert ">PAUSED<" in body
    assert 'class="badge ok"' in body  # green badge while running


def test_ops_route_user_count_na_when_db_down(monkeypatch):
    _patch_route_io(monkeypatch, user_count=None)
    client = TestClient(_build_app())
    body = client.get("/ops").text
    assert "N/A" in body


def test_ops_route_audit_section_na_on_db_failure(monkeypatch):
    _patch_route_io(monkeypatch, audit_rows=None)
    client = TestClient(_build_app())
    body = client.get("/ops").text
    assert "N/A — data not available" in body


def test_ops_route_renders_audit_rows(monkeypatch):
    from datetime import datetime, timezone
    _patch_route_io(monkeypatch, audit_rows=[
        {
            "ts": datetime(2026, 5, 8, 9, 30, tzinfo=timezone.utc),
            "action": "kill_switch_pause",
            "actor_role": "operator",
        },
        {
            "ts": datetime(2026, 5, 8, 9, 25, tzinfo=timezone.utc),
            "action": "kill_switch_resume",
            "actor_role": "operator",
        },
    ])
    client = TestClient(_build_app())
    body = client.get("/ops").text
    assert "kill_switch_pause" in body
    assert "kill_switch_resume" in body
    assert "operator" in body


def test_ops_route_flash_message_round_trip(monkeypatch):
    _patch_route_io(monkeypatch)
    client = TestClient(_build_app())
    r = client.get("/ops?flash=Hello%20operator")
    assert "Hello operator" in r.text


def test_ops_route_flash_message_is_escaped(monkeypatch):
    _patch_route_io(monkeypatch)
    client = TestClient(_build_app())
    r = client.get("/ops?flash=<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_ops_route_degrades_when_health_raises(monkeypatch):
    """A health-check exception must NOT crash the dashboard; the page
    still renders so the operator can see the kill switch state.
    """
    async def _boom():
        raise RuntimeError("boom")

    _patch_route_io(monkeypatch)
    monkeypatch.setattr(api_ops, "run_health_checks", _boom)
    client = TestClient(_build_app())
    r = client.get("/ops")
    assert r.status_code == 200
    # Health table renders the four expected rows with N/A badges.
    body = r.text
    assert "alchemy_ws" in body


# ---------------------------------------------------------------------------
# POST /ops/kill
# ---------------------------------------------------------------------------


def test_ops_kill_calls_set_active_pause_and_redirects(monkeypatch):
    _patch_route_io(monkeypatch)
    set_active = AsyncMock(return_value={"active": True, "lock_mode": False, "users_disabled": 0})
    audit_write = AsyncMock()
    monkeypatch.setattr(api_ops.kill_switch, "set_active", set_active)
    monkeypatch.setattr(api_ops.audit, "write", audit_write)

    client = TestClient(_build_app())
    r = client.post(
        "/ops/kill",
        headers={"X-Ops-Token": OPS_TOKEN},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/ops?flash=")
    set_active.assert_awaited_once()
    kwargs = set_active.await_args.kwargs
    assert kwargs.get("action") == "pause"
    audit_write.assert_awaited_once()
    audit_kwargs = audit_write.await_args.kwargs
    assert audit_kwargs.get("action") == "kill_switch_pause"
    assert audit_kwargs.get("actor_role") == "operator"
    assert audit_kwargs.get("payload", {}).get("source") == "ops_dashboard_web"


def test_ops_kill_redirects_with_failure_flash_when_set_active_raises(monkeypatch):
    _patch_route_io(monkeypatch)

    async def _boom(**kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(api_ops.kill_switch, "set_active", _boom)
    monkeypatch.setattr(api_ops.audit, "write", AsyncMock())

    client = TestClient(_build_app())
    r = client.post(
        "/ops/kill",
        headers={"X-Ops-Token": OPS_TOKEN},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "Kill+failed" in r.headers["location"] or "Kill%20failed" in r.headers["location"]


# ---------------------------------------------------------------------------
# POST /ops/resume
# ---------------------------------------------------------------------------


def test_ops_resume_calls_set_active_resume_and_redirects(monkeypatch):
    _patch_route_io(monkeypatch)
    set_active = AsyncMock(return_value={"active": False, "lock_mode": False, "users_disabled": 0})
    audit_write = AsyncMock()
    monkeypatch.setattr(api_ops.kill_switch, "set_active", set_active)
    monkeypatch.setattr(api_ops.audit, "write", audit_write)

    client = TestClient(_build_app())
    r = client.post(
        "/ops/resume",
        headers={"X-Ops-Token": OPS_TOKEN},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/ops?flash=")
    kwargs = set_active.await_args.kwargs
    assert kwargs.get("action") == "resume"
    audit_kwargs = audit_write.await_args.kwargs
    assert audit_kwargs.get("action") == "kill_switch_resume"


def test_ops_resume_redirects_with_failure_flash_when_set_active_raises(monkeypatch):
    _patch_route_io(monkeypatch)

    async def _boom(**kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(api_ops.kill_switch, "set_active", _boom)
    monkeypatch.setattr(api_ops.audit, "write", AsyncMock())

    client = TestClient(_build_app())
    r = client.post(
        "/ops/resume",
        headers={"X-Ops-Token": OPS_TOKEN},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "Resume+failed" in r.headers["location"] or "Resume%20failed" in r.headers["location"]


# ---------------------------------------------------------------------------
# Auth gate on POST /ops/kill + /ops/resume
# ---------------------------------------------------------------------------


@pytest.fixture
def _stub_ops_mutators(monkeypatch):
    """Patch kill_switch.set_active and audit.write so successful auth
    paths don't actually call into the real DB layer.
    """
    monkeypatch.setattr(
        api_ops.kill_switch, "set_active",
        AsyncMock(return_value={"active": True, "lock_mode": False, "users_disabled": 0}),
    )
    monkeypatch.setattr(api_ops.audit, "write", AsyncMock())


@pytest.mark.parametrize("path", ["/ops/kill", "/ops/resume"])
def test_ops_post_returns_503_when_ops_secret_unset(
    monkeypatch, _stub_ops_mutators, path,
):
    """When the operator hasn't configured ``OPS_SECRET``, the mutators
    must respond 503 (not 200, not 403) so the operator can distinguish
    "not configured" from "wrong token". Mirrors the /admin/sentry-test
    contract for ADMIN_API_TOKEN.
    """
    _patch_route_io(monkeypatch)
    monkeypatch.setattr(
        api_ops, "get_settings", lambda: _settings(ops_secret=None),
    )
    client = TestClient(_build_app())
    r = client.post(path, follow_redirects=False)
    assert r.status_code == 503
    api_ops.kill_switch.set_active.assert_not_awaited()


@pytest.mark.parametrize("path", ["/ops/kill", "/ops/resume"])
def test_ops_post_returns_403_when_token_missing(
    monkeypatch, _stub_ops_mutators, path,
):
    """No ``X-Ops-Token`` header and no ``?token=`` query param → 403.
    The kill switch must NOT be flipped.
    """
    _patch_route_io(monkeypatch)
    client = TestClient(_build_app())
    r = client.post(path, follow_redirects=False)
    assert r.status_code == 403
    api_ops.kill_switch.set_active.assert_not_awaited()


@pytest.mark.parametrize("path", ["/ops/kill", "/ops/resume"])
def test_ops_post_returns_403_when_token_wrong(
    monkeypatch, _stub_ops_mutators, path,
):
    _patch_route_io(monkeypatch)
    client = TestClient(_build_app())
    r = client.post(
        path,
        headers={"X-Ops-Token": "wrong-token"},
        follow_redirects=False,
    )
    assert r.status_code == 403
    api_ops.kill_switch.set_active.assert_not_awaited()


@pytest.mark.parametrize("path", ["/ops/kill", "/ops/resume"])
def test_ops_post_accepts_token_via_query_param(
    monkeypatch, _stub_ops_mutators, path,
):
    """The dashboard's HTML form action embeds the token as ``?token=``
    so a phone bookmark works without needing to inject a header. The
    handler must accept that path too.
    """
    _patch_route_io(monkeypatch)
    client = TestClient(_build_app())
    r = client.post(f"{path}?token={OPS_TOKEN}", follow_redirects=False)
    assert r.status_code == 303
    api_ops.kill_switch.set_active.assert_awaited_once()


@pytest.mark.parametrize("path", ["/ops/kill", "/ops/resume"])
def test_ops_post_redirect_preserves_token_query_param(
    monkeypatch, _stub_ops_mutators, path,
):
    """Post-action redirect must include the token query param so the
    next dashboard render still has a working pair of buttons.
    """
    _patch_route_io(monkeypatch)
    client = TestClient(_build_app())
    r = client.post(f"{path}?token={OPS_TOKEN}", follow_redirects=False)
    assert r.status_code == 303
    location = r.headers["location"]
    assert "token=" + OPS_TOKEN in location, (
        f"redirect lost the token: {location!r}"
    )


def test_ops_get_does_not_require_token(monkeypatch):
    """GET /ops is intentionally open so the dashboard renders for
    anyone who lands on the URL — only the mutators are gated.
    """
    _patch_route_io(monkeypatch)
    client = TestClient(_build_app())
    r = client.get("/ops")
    assert r.status_code == 200


def test_ops_get_with_token_embeds_into_form_actions(monkeypatch):
    """When the operator opens ``/ops?token=...``, the rendered form
    actions must point at ``/ops/kill?token=...`` so the POST carries
    the token without an extra hidden input the operator has to set.
    """
    _patch_route_io(monkeypatch)
    client = TestClient(_build_app())
    r = client.get(f"/ops?token={OPS_TOKEN}")
    assert r.status_code == 200
    body = r.text
    assert f'action="/ops/kill?token={OPS_TOKEN}"' in body
    assert f'action="/ops/resume?token={OPS_TOKEN}"' in body


def test_ops_get_without_token_renders_unsigned_form_actions(monkeypatch):
    """A bare ``/ops`` GET (no token) must still render — the buttons
    appear but POST will 403. This keeps the dashboard discoverable.
    """
    _patch_route_io(monkeypatch)
    client = TestClient(_build_app())
    body = client.get("/ops").text
    assert 'action="/ops/kill"' in body
    assert 'action="/ops/resume"' in body


# ---------------------------------------------------------------------------
# DB-shaped helpers
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


def test_count_users_returns_count_from_pool(monkeypatch):
    pool = MagicMock()
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=42)

    class _Acq:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *a):
            return False

    pool.acquire = MagicMock(return_value=_Acq())
    monkeypatch.setattr(api_ops, "get_pool", lambda: pool)
    assert _run(api_ops._count_users()) == 42


def test_count_users_returns_none_on_error(monkeypatch):
    def _boom():
        raise RuntimeError("pool not initialised")

    monkeypatch.setattr(api_ops, "get_pool", _boom)
    assert _run(api_ops._count_users()) is None


def test_fetch_audit_tail_returns_rows_from_pool(monkeypatch):
    pool = MagicMock()
    conn = MagicMock()
    rows = [{"ts": "x", "action": "a", "actor_role": "operator"}]
    conn.fetch = AsyncMock(return_value=rows)

    class _Acq:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *a):
            return False

    pool.acquire = MagicMock(return_value=_Acq())
    monkeypatch.setattr(api_ops, "get_pool", lambda: pool)
    out = _run(api_ops._fetch_audit_tail(limit=5))
    assert out == [{"ts": "x", "action": "a", "actor_role": "operator"}]
    args = conn.fetch.await_args.args
    assert "audit.log" in args[0]
    assert args[1] == 5


def test_kill_switch_state_returns_active_or_paused(monkeypatch):
    monkeypatch.setattr(api_ops.kill_switch, "is_active", AsyncMock(return_value=True))
    assert _run(api_ops._kill_switch_state()) == "ACTIVE"
    monkeypatch.setattr(api_ops.kill_switch, "is_active", AsyncMock(return_value=False))
    assert _run(api_ops._kill_switch_state()) == "PAUSED"


def test_kill_switch_state_returns_na_on_error(monkeypatch):
    async def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(api_ops.kill_switch, "is_active", _boom)
    assert _run(api_ops._kill_switch_state()) == "N/A"
