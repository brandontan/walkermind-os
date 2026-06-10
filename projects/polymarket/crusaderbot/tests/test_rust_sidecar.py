"""Rust order-sidecar Python wrapper (WARP/root-rust-order-sidecar).

Hermetic — no Rust toolchain, no network. The "sidecar" under test is a tiny
python script that speaks the same JSON-over-stdio protocol, so the wrapper's
process handling, env passing, error mapping, and protocol parsing are pinned
without the real binary.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import textwrap

import pytest

from projects.polymarket.crusaderbot.integrations.clob.exceptions import (
    ClobAPIError,
    ClobConfigError,
    ClobNetworkError,
)
from projects.polymarket.crusaderbot.integrations.clob.rust_sidecar import (
    RustSidecarClient,
    _decimal_str,
)

_PK = "0x" + "1" * 64
_FUNDER = "0x3feC630a07a263Ee0bd6cD108ff4b8Ed1eB606A9"


def _fake_sidecar(tmp_path, body: str) -> str:
    """Write an executable python script that acts as the sidecar."""
    script = tmp_path / "fake-sidecar"
    script.write_text(
        f"#!{sys.executable}\n" + textwrap.dedent(body)
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def _echo_sidecar(tmp_path, response: dict, exit_code: int = 0) -> str:
    """A sidecar that ignores stdin and prints a fixed JSON response."""
    return _fake_sidecar(tmp_path, f"""
        import json, sys
        sys.stdin.read()
        print(json.dumps({response!r}))
        sys.exit({exit_code})
    """)


def _client(path: str, **kw) -> RustSidecarClient:
    return RustSidecarClient(
        binary_path=path,
        private_key=_PK,
        funder_address=_FUNDER,
        timeout_sec=kw.pop("timeout_sec", 10.0),
        **kw,
    )


# ── construction guards ──────────────────────────────────────────────────────


def test_missing_funder_hard_fails() -> None:
    with pytest.raises(ClobConfigError, match="funder_address"):
        RustSidecarClient(binary_path="/bin/true", private_key=_PK, funder_address="")


def test_missing_private_key_hard_fails() -> None:
    with pytest.raises(ClobConfigError, match="private_key"):
        RustSidecarClient(binary_path="/bin/true", private_key="", funder_address=_FUNDER)


def test_missing_binary_path_hard_fails() -> None:
    with pytest.raises(ClobConfigError, match="binary_path"):
        RustSidecarClient(binary_path="", private_key=_PK, funder_address=_FUNDER)


# ── happy paths ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_order_round_trip(tmp_path) -> None:
    """The wrapper sends the right request JSON and surfaces the result dict."""
    path = _fake_sidecar(tmp_path, """
        import json, sys
        req = json.loads(sys.stdin.read())
        assert req["action"] == "place_order", req
        p = req["params"]
        assert p["side"] == "BUY" and p["order_type"] == "GTC"
        # price/size must arrive as decimal STRINGS, not floats
        assert isinstance(p["price"], str) and isinstance(p["size"], str)
        print(json.dumps({"ok": True, "result": {
            "success": True, "orderID": "0xabc", "order_id": "0xabc",
            "status": "live", "error_msg": None,
        }}))
    """)
    out = await _client(path).post_order(
        token_id="123", side="buy", price=0.55, size=10.0,
    )
    assert out["success"] is True
    assert out["orderID"] == "0xabc"


@pytest.mark.asyncio
async def test_get_open_orders_unwraps_and_market_filters(tmp_path) -> None:
    path = _echo_sidecar(tmp_path, {"ok": True, "result": {"orders": [
        {"id": "1", "market": "0xaaa"},
        {"id": "2", "market": "0xbbb"},
    ], "next_cursor": "LTE=", "count": 2}})
    client = _client(path)
    all_orders = await client.get_open_orders()
    assert [o["id"] for o in all_orders] == ["1", "2"]
    scoped = await client.get_open_orders(market="0xaaa")
    assert [o["id"] for o in scoped] == ["1"]


@pytest.mark.asyncio
async def test_get_fills_unwraps_trades(tmp_path) -> None:
    path = _echo_sidecar(tmp_path, {"ok": True, "result": {"trades": [
        {"id": "t1", "price": "0.55"},
    ], "next_cursor": "LTE=", "count": 1}})
    fills = await _client(path).get_fills("0xabc")
    assert fills == [{"id": "t1", "price": "0.55"}]


@pytest.mark.asyncio
async def test_secrets_travel_via_env_not_argv(tmp_path) -> None:
    """The private key must reach the child via env (argv is world-readable)."""
    path = _fake_sidecar(tmp_path, """
        import json, os, sys
        sys.stdin.read()
        assert os.environ.get("SIDECAR_PRIVATE_KEY"), "pk must be in env"
        assert os.environ.get("SIDECAR_FUNDER"), "funder must be in env"
        # argv carries NOTHING beyond the program name
        assert len(sys.argv) == 1, sys.argv
        print(json.dumps({"ok": True, "result": {"orders": []}}))
    """)
    out = await _client(path).get_open_orders()
    assert out == []


@pytest.mark.asyncio
async def test_l2_creds_forwarded_when_complete(tmp_path) -> None:
    path = _fake_sidecar(tmp_path, """
        import json, os, sys
        sys.stdin.read()
        assert os.environ.get("SIDECAR_API_KEY") == "k"
        assert os.environ.get("SIDECAR_API_SECRET") == "s"
        assert os.environ.get("SIDECAR_PASSPHRASE") == "p"
        print(json.dumps({"ok": True, "result": {"orders": []}}))
    """)
    client = _client(path, api_key="k", api_secret="s", passphrase="p")
    assert await client.get_open_orders() == []


# ── failure mapping ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_action_failure_maps_to_api_error(tmp_path) -> None:
    """ok=false + exit 0 = broker/action failure → ClobAPIError."""
    path = _echo_sidecar(tmp_path, {
        "ok": False, "kind": "action", "error": "not enough balance",
    })
    with pytest.raises(ClobAPIError, match="not enough balance"):
        await _client(path).cancel_order("0xabc")


@pytest.mark.asyncio
async def test_nonzero_exit_maps_to_network_error(tmp_path) -> None:
    path = _echo_sidecar(tmp_path, {"ok": False, "kind": "protocol",
                                    "error": "x"}, exit_code=2)
    with pytest.raises(ClobNetworkError, match="exited 2"):
        await _client(path).cancel_order("0xabc")


@pytest.mark.asyncio
async def test_garbage_stdout_maps_to_network_error(tmp_path) -> None:
    path = _fake_sidecar(tmp_path, """
        import sys
        sys.stdin.read()
        print("definitely not json")
    """)
    with pytest.raises(ClobNetworkError, match="invalid JSON"):
        await _client(path).get_open_orders()


@pytest.mark.asyncio
async def test_missing_binary_maps_to_config_error(tmp_path) -> None:
    client = _client(str(tmp_path / "does-not-exist"))
    with pytest.raises(ClobConfigError, match="not found"):
        await client.get_open_orders()


@pytest.mark.asyncio
async def test_hang_is_killed_at_timeout(tmp_path) -> None:
    path = _fake_sidecar(tmp_path, """
        import time, sys
        sys.stdin.read()
        time.sleep(60)
    """)
    client = _client(path, timeout_sec=0.5)
    with pytest.raises(ClobNetworkError, match="timed out"):
        await client.get_open_orders()


@pytest.mark.asyncio
async def test_unsupported_order_type_fails_before_spawn(tmp_path) -> None:
    client = _client(str(tmp_path / "never-spawned"))
    with pytest.raises(ClobConfigError, match="GTD"):
        await client.post_order(
            token_id="1", side="BUY", price=0.5, size=1.0, order_type="GTD",
        )


@pytest.mark.asyncio
async def test_market_scoped_cancel_all_refuses(tmp_path) -> None:
    """Account-wide cancel when the caller asked for one market would cancel
    MORE than requested — must refuse loudly."""
    client = _client(str(tmp_path / "never-spawned"))
    with pytest.raises(ClobConfigError, match="market-scoped"):
        await client.cancel_all_orders(market="0xaaa")


# ── factory wiring ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_factory_selects_sidecar_with_highest_precedence(monkeypatch) -> None:
    """USE_RUST_SIDECAR wins over USE_CLOB_V2 + USE_PYSDK_CLOB."""
    from projects.polymarket.crusaderbot.integrations import clob as clob_pkg

    class _S:
        USE_REAL_CLOB = True
        USE_RUST_SIDECAR = True
        USE_CLOB_V2 = True       # would otherwise win
        USE_PYSDK_CLOB = True    # would otherwise win
        RUST_SIDECAR_PATH = "/usr/local/bin/order-sidecar"
        POLYMARKET_PRIVATE_KEY = _PK
        POLYMARKET_FUNDER_ADDRESS = _FUNDER
        POLYMARKET_SIGNATURE_TYPE = 3
        POLYMARKET_API_KEY = "k"
        POLYMARKET_API_SECRET = "s"
        POLYMARKET_API_PASSPHRASE = "p"
        POLYMARKET_BUILDER_CODE = ""
        POLYMARKET_BUILDER_ADDRESS = ""
        CIRCUIT_BREAKER_THRESHOLD = 5
        CIRCUIT_BREAKER_RESET_SECONDS = 30
        CLOB_RATE_LIMIT_RPS = 0

    clob_pkg.reset_clob_resilience()
    try:
        client = clob_pkg.get_clob_client(_S())
    finally:
        clob_pkg.reset_clob_resilience()
    from projects.polymarket.crusaderbot.integrations.clob.rust_sidecar import (
        RustSidecarClient as _RSC,
    )
    assert isinstance(client, _RSC)


@pytest.mark.asyncio
async def test_factory_sidecar_requires_funder(monkeypatch) -> None:
    from projects.polymarket.crusaderbot.integrations import clob as clob_pkg

    class _S:
        USE_REAL_CLOB = True
        USE_RUST_SIDECAR = True
        USE_CLOB_V2 = False
        USE_PYSDK_CLOB = False
        RUST_SIDECAR_PATH = "/usr/local/bin/order-sidecar"
        POLYMARKET_PRIVATE_KEY = _PK
        POLYMARKET_FUNDER_ADDRESS = ""
        POLYMARKET_SIGNATURE_TYPE = 0  # not 3 → skips the package-level guard
        POLYMARKET_API_KEY = "k"
        POLYMARKET_API_SECRET = "s"
        POLYMARKET_API_PASSPHRASE = "p"
        POLYMARKET_BUILDER_CODE = ""
        POLYMARKET_BUILDER_ADDRESS = ""
        CIRCUIT_BREAKER_THRESHOLD = 5
        CIRCUIT_BREAKER_RESET_SECONDS = 30
        CLOB_RATE_LIMIT_RPS = 0

    clob_pkg.reset_clob_resilience()
    try:
        with pytest.raises(ClobConfigError, match="funder"):
            clob_pkg.get_clob_client(_S())
    finally:
        clob_pkg.reset_clob_resilience()


# ── decimal rendering ────────────────────────────────────────────────────────


def test_decimal_str_strips_binary_dust() -> None:
    assert _decimal_str(0.55) == "0.55"
    assert _decimal_str(10.0) == "10"
    assert _decimal_str(0.1 + 0.2) == "0.3"
    assert _decimal_str(0) == "0"
    assert _decimal_str(0.001) == "0.001"
