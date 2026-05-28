"""Multi-tenant safety regression tests — Axis #1.

Coverage:
  * per_user_rate_limit dependency: enforces per-user budget, distinct
    users do not share a bucket, distinct scopes do not share a budget,
    overflow returns 429 with Retry-After, anonymous (missing user_id)
    is a no-op.
  * /api/web/kill must NOT activate the global kill switch — it only
    sets users.paused=TRUE for the calling user. Pinned at the route
    body level so a regression that re-introduces kill_switch.set_active
    on this endpoint fails this test.
  * /api/web/emergency-stop must NOT activate the global kill switch.

Hermetic: no DB, no FastAPI app spun up for the /kill body pin (we
inspect the source). The per_user_rate_limit cases use a minimal in-
memory FastAPI app with a fake get_current_user override.
"""
from __future__ import annotations

import asyncio
import inspect
import re
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from projects.polymarket.crusaderbot.api import per_user_rate_limit as prl
from projects.polymarket.crusaderbot.webtrader.backend import auth as auth_mod
from projects.polymarket.crusaderbot.webtrader.backend import router as router_mod


# ---------------------------------------------------------------------
# per_user_rate_limit dependency
# ---------------------------------------------------------------------

def _make_app(scope: str, limit: int, *, current_user: dict):
    """Build a tiny FastAPI app with /ping gated by per_user_rate_limit
    and ``get_current_user`` overridden to return a fixed user dict.
    """
    prl._clear_buckets_for_tests()
    app = FastAPI()
    dep = prl.per_user_rate_limit(scope, limit=limit, window_seconds=60.0)

    @app.get("/ping", dependencies=[Depends(dep)])
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    async def _override() -> dict:
        return current_user

    app.dependency_overrides[auth_mod.get_current_user] = _override
    return app


def test_per_user_rate_limit_allows_within_budget():
    app = _make_app("withdraw", limit=3, current_user={"user_id": "u-a"})
    with TestClient(app) as c:
        for _ in range(3):
            r = c.get("/ping")
            assert r.status_code == 200, r.text


def test_per_user_rate_limit_blocks_over_budget():
    app = _make_app("withdraw", limit=2, current_user={"user_id": "u-b"})
    with TestClient(app) as c:
        assert c.get("/ping").status_code == 200
        assert c.get("/ping").status_code == 200
        r = c.get("/ping")
        assert r.status_code == 429
        assert "withdraw" in r.json()["detail"]
        assert r.headers.get("Retry-After") is not None


def test_per_user_rate_limit_distinct_users_independent():
    """User A's bucket must not affect User B's bucket."""
    prl._clear_buckets_for_tests()
    app = FastAPI()
    dep = prl.per_user_rate_limit("withdraw", limit=1, window_seconds=60.0)

    @app.get("/ping", dependencies=[Depends(dep)])
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    state = {"user_id": "u-c"}

    async def _override() -> dict:
        return {"user_id": state["user_id"]}

    app.dependency_overrides[auth_mod.get_current_user] = _override
    with TestClient(app) as c:
        # User C: spends the budget then gets blocked.
        assert c.get("/ping").status_code == 200
        assert c.get("/ping").status_code == 429
        # User D: still has a full budget — independent bucket.
        state["user_id"] = "u-d"
        assert c.get("/ping").status_code == 200


def test_per_user_rate_limit_distinct_scopes_independent():
    """A user's withdraw bucket and copy_task bucket must be independent."""
    prl._clear_buckets_for_tests()
    app = FastAPI()
    dep_w = prl.per_user_rate_limit("withdraw", limit=1, window_seconds=60.0)
    dep_c = prl.per_user_rate_limit("copy_task", limit=1, window_seconds=60.0)

    @app.get("/w", dependencies=[Depends(dep_w)])
    async def w() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/c", dependencies=[Depends(dep_c)])
    async def c_() -> dict[str, bool]:
        return {"ok": True}

    async def _override() -> dict:
        return {"user_id": "u-e"}

    app.dependency_overrides[auth_mod.get_current_user] = _override
    with TestClient(app) as c:
        assert c.get("/w").status_code == 200
        assert c.get("/w").status_code == 429
        # Distinct scope still has full budget.
        assert c.get("/c").status_code == 200


def test_per_user_rate_limit_missing_user_id_is_noop():
    """When the dependency sees no user_id, it should not raise — it
    silently passes so the downstream auth dependency handles the 401
    in the normal way.
    """
    prl._clear_buckets_for_tests()
    dep = prl.per_user_rate_limit("withdraw", limit=1, window_seconds=60.0)
    # Drive the dep directly with a user dict that lacks user_id; should
    # return None without raising.
    asyncio.run(dep({}))
    asyncio.run(dep({"user_id": ""}))


# ---------------------------------------------------------------------
# Kill-switch + emergency-stop must NOT toggle the global switch
# ---------------------------------------------------------------------

def _router_source() -> str:
    return Path(router_mod.__file__).read_text(encoding="utf-8")


def test_web_kill_does_not_activate_global_kill_switch():
    """web_kill body must call users.set_paused, NOT kill_switch.set_active.

    Pinning at the source level: a regression that re-introduces
    kill_switch.set_active inside web_kill is a multi-tenant violation
    (lets any logged-in user pause everyone). Tested by reading the
    function source rather than spinning up a real DB.
    """
    src = inspect.getsource(router_mod.web_kill)
    assert "kill_switch.set_active" not in src, (
        "Regression: web_kill toggles global kill switch — every "
        "authenticated user could halt all trading. Use users.set_paused "
        "for per-user pause."
    )
    assert "set_paused" in src


def test_web_emergency_stop_does_not_activate_global_kill_switch():
    """web_emergency_stop must call users.set_paused, NOT kill_switch.set_active."""
    src = inspect.getsource(router_mod.web_emergency_stop)
    assert "kill_switch.set_active" not in src, (
        "Regression: web_emergency_stop toggles global kill switch — "
        "every authenticated user could halt all trading."
    )
    assert "set_paused" in src
    assert "mark_force_close_intent_for_user" in src


def test_web_resume_clears_paused():
    """web_resume must call users.set_paused with False."""
    src = inspect.getsource(router_mod.web_resume)
    assert "set_paused" in src
    assert "False" in src


def test_cost_sensitive_endpoints_have_per_user_rate_limit():
    """The 4 cost-sensitive POST endpoints must declare a
    per_user_rate_limit dependency.

    Pinned at the source level — a regression that drops the dependency
    decoration from any of these endpoints reopens the spam vector.
    """
    src = _router_source()
    # The router decorator + endpoint definition lives on consecutive lines,
    # so for each route we want to confirm a per_user_rate_limit call
    # appears between the @router.post(...) line and the `async def` line.
    targets = {
        "/wallet/withdraw": "withdraw",
        "/positions/{position_id}/redeem": "position_action",
        "/positions/{position_id}/close": "position_action",
        "/copy-trade/tasks": "copy_task",
        "/kill": "user_pause",
        "/resume": "user_pause",
        "/emergency-stop": "emergency_stop",
    }
    for path, expected_scope in targets.items():
        pattern = (
            r"@router\.post\(\s*\n?\s*['\"]"
            + re.escape(path)
            + r"['\"][^@]*per_user_rate_limit\(\s*['\"]"
            + re.escape(expected_scope)
            + r"['\"]"
        )
        assert re.search(pattern, src), (
            f"endpoint POST {path} is missing per_user_rate_limit('{expected_scope}', ...) — "
            f"a single authenticated user can spam it"
        )
