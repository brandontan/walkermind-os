"""WARP•R00T audit Lane 3a — API hardening regression tests.

Hermetic: no DB, no network. Covers:
- B1: GET /ops renders NO operational data when OPS_SECRET is unset (503).
- B3: ops mutators no longer accept the legacy ?token= query param.
- B4: /autotrade/customize rejects out-of-range sizing/threshold inputs.
- B5: per_ip_rate_limit enforces a 429 ceiling for pre-auth endpoints.
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import MagicMock, patch

import pytest

from projects.polymarket.crusaderbot.api import ops as ops_mod
from projects.polymarket.crusaderbot.api import per_user_rate_limit as rl
from projects.polymarket.crusaderbot.webtrader.backend import router as r
from projects.polymarket.crusaderbot.webtrader.backend.schemas import CustomizeRequest


# ── B1: ops dashboard never leaks data without a configured secret ────────────

def test_ops_dashboard_no_data_when_secret_unset():
    req = MagicMock()
    req.cookies = {}
    with patch.object(ops_mod, "_ops_secret", return_value=""):
        resp = asyncio.run(ops_mod.ops_dashboard(req))
    assert resp.status_code == 503
    body = resp.body.decode("utf-8") if isinstance(resp.body, (bytes, bytearray)) else str(resp.body)
    # Login/disabled page only — never the operational dashboard fields.
    assert "OPS_SECRET" in body
    assert "Audit" not in body and "Kill switch" not in body


# ── B3: legacy ?token= removed from mutators + the shared authorizer ──────────

def test_ops_mutators_drop_legacy_token_param():
    for fn in (ops_mod.ops_kill, ops_mod.ops_resume):
        params = inspect.signature(fn).parameters
        assert "token" not in params, f"{fn.__name__} must not accept ?token= anymore"
    assert "token" not in inspect.signature(ops_mod._authorize_mutation).parameters


def test_authorize_mutation_accepts_header_only_secret(monkeypatch):
    monkeypatch.setattr(ops_mod, "_ops_secret", lambda: "topsecret")
    req = MagicMock()
    # header credential matches -> no raise
    ops_mod._authorize_mutation(request=req, header="topsecret", cookie=None)


def test_authorize_mutation_rejects_no_credential(monkeypatch):
    monkeypatch.setattr(ops_mod, "_ops_secret", lambda: "topsecret")
    req = MagicMock()
    with pytest.raises(Exception) as exc:
        ops_mod._authorize_mutation(request=req, header=None, cookie=None)
    assert "403" in str(exc.value) or "forbidden" in str(exc.value)


# ── B4: /autotrade/customize input bounds ─────────────────────────────────────

def _customize(**kw):
    body = CustomizeRequest(**kw)
    with patch.object(r, "get_pool", return_value=MagicMock()):
        return asyncio.run(r.customize_strategy(body, {"user_id": "u"}))


@pytest.mark.parametrize("kw", [
    {"capital_alloc_pct": 99999.0},
    {"capital_alloc_pct": -1.0},
    {"tp_pct": -0.5},
    {"sl_pct": 5.0},
    {"max_position_pct": 0.9},
    {"max_per_trade_usdc": -100.0},
    {"max_per_trade_pct": 2.0},
])
def test_customize_rejects_out_of_range(kw):
    with pytest.raises(Exception) as exc:
        _customize(**kw)
    assert "400" in str(exc.value) or "must be" in str(exc.value)


# ── B5: per_ip_rate_limit ceiling ─────────────────────────────────────────────

def test_per_ip_rate_limit_blocks_after_limit():
    rl._clear_buckets_for_tests()
    dep = rl.per_ip_rate_limit("auth_login_test", limit=2, window_seconds=60.0)
    req = MagicMock()
    req.headers = {"fly-client-ip": "1.2.3.4"}
    req.client = MagicMock(host="1.2.3.4")

    asyncio.run(dep(req))   # 1
    asyncio.run(dep(req))   # 2
    with pytest.raises(Exception) as exc:
        asyncio.run(dep(req))   # 3 -> 429
    assert "429" in str(exc.value) or "rate limit" in str(exc.value)


def test_per_ip_rate_limit_distinct_ips_independent():
    rl._clear_buckets_for_tests()
    dep = rl.per_ip_rate_limit("auth_login_test2", limit=1, window_seconds=60.0)
    a, b = MagicMock(), MagicMock()
    a.headers = {"fly-client-ip": "10.0.0.1"}; a.client = MagicMock(host="10.0.0.1")
    b.headers = {"fly-client-ip": "10.0.0.2"}; b.client = MagicMock(host="10.0.0.2")
    asyncio.run(dep(a))  # uses A's budget
    asyncio.run(dep(b))  # B independent -> ok
