"""RPC + watcher hardening lane (WARP/root-rpc-watcher-hardening).

Pins the fixes for the two 2026-06-11 production failure modes:

1. SCHEDULER WEDGE — the Polygon ``AsyncHTTPProvider`` carried no request
   timeout (aiohttp default: total=300s) and a peer that accepted the TCP
   connection but never answered froze an APScheduler job slot at 06:12 UTC.
   Now: explicit ``ClientTimeout`` on the provider AND an ``asyncio.timeout``
   deadline around every RPC await (``POLYGON_RPC_TIMEOUT_SECONDS``).

2. BLOCK-0 WATCHER OUTAGE — three independent gaps kept every watcher tick
   failing invisibly:
   a. the retry predicate missed aiohttp ``ClientError`` (web3 surfaces
      HTTP 429/5xx as ``ClientResponseError``, not ``Web3RPCError``), so a
      single throttled response failed the call with zero retries;
   b. a provider-side eth_getLogs range/size cap surfaces as a
      ``Web3RPCError`` on EVERY tick with a fixed 1000-block span — now the
      span halves adaptively down to ``_MIN_SCAN_RANGE`` so a smaller scan
      still advances the cursor (transport errors are NOT halved);
   c. the ``_read_cursor`` stage of ``watch_deposits`` was unguarded — an
      exception there bypassed the failure-streak escalation entirely.

Also pins: relayer SDK calls in ``custody._execute_usdc_transfer`` are
bounded by ``RELAYER_CALL_TIMEOUT_SECONDS`` (they previously blocked forever).
"""
from __future__ import annotations

import asyncio
import sys
import time
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from aiohttp import ClientError
from tenacity import (
    AsyncRetrying, retry_if_exception_type, stop_after_attempt,
)
from web3.exceptions import Web3RPCError

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot import scheduler
from projects.polymarket.crusaderbot.integrations import polygon
from projects.polymarket.crusaderbot.wallet import custody


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")


@pytest.fixture(autouse=True)
def _isolated_state():
    polygon._w3 = None
    polygon._usdc = None
    crusaderbot_config.get_settings.cache_clear()
    scheduler._watch_deposits_fail_streak = 0
    yield
    polygon._w3 = None
    polygon._usdc = None
    crusaderbot_config.get_settings.cache_clear()
    scheduler._watch_deposits_fail_streak = 0


def _fast_retry():
    """Same predicate as production, but no backoff sleep — keeps tests fast."""
    return AsyncRetrying(
        reraise=True,
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(
            (Web3RPCError, ClientError, ConnectionError, TimeoutError)
        ),
    )


# ---------------------------------------------------------------------
# 1. Provider construction: explicit aiohttp ClientTimeout
# ---------------------------------------------------------------------


def test_get_w3_sets_explicit_request_timeout():
    fake_settings = MagicMock()
    fake_settings.POLYGON_RPC_URL = "https://rpc.example"
    fake_settings.POLYGON_RPC_TIMEOUT_SECONDS = 17
    fake_settings.USDC_POLYGON = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    captured: dict[str, Any] = {}

    def _capture_provider(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return MagicMock()

    with patch.object(polygon, "get_settings", return_value=fake_settings), \
            patch.object(polygon, "AsyncHTTPProvider",
                         side_effect=_capture_provider), \
            patch.object(polygon, "AsyncWeb3") as fake_w3_cls:
        fake_w3_cls.to_checksum_address = MagicMock(return_value="0xUSDC")
        polygon._get_w3()

    assert captured["url"] == "https://rpc.example"
    timeout = captured["request_kwargs"]["timeout"]
    assert timeout.total == 17


def test_config_defaults():
    # Defaults exist without env overrides (dataclass-level truth).
    assert crusaderbot_config.Settings.model_fields[
        "POLYGON_RPC_TIMEOUT_SECONDS"].default == 20
    assert crusaderbot_config.Settings.model_fields[
        "RELAYER_CALL_TIMEOUT_SECONDS"].default == 180


# ---------------------------------------------------------------------
# 2. Retry predicate covers aiohttp ClientError; deadline bounds a hang
# ---------------------------------------------------------------------


class _FakeEth:
    """``await w3.eth.block_number`` driven by a scripted result list."""

    def __init__(self, results: list[Any]) -> None:
        self._results = results
        self.calls = 0

    @property
    def block_number(self):
        async def _value():
            self.calls += 1
            r = self._results.pop(0)
            if isinstance(r, BaseException):
                raise r
            if r == "hang":
                await asyncio.sleep(5)
            return r
        return _value()


class _FakeW3:
    def __init__(self, results: list[Any]) -> None:
        self.eth = _FakeEth(results)


def test_latest_block_retries_aiohttp_client_error():
    """A throttled HTTP response (aiohttp ClientError) is retried — the
    pre-fix predicate (Web3RPCError/ConnectionError/TimeoutError only)
    reraised it on the first attempt."""
    fake = _FakeW3([ClientError("429 too many requests"), 123])
    with patch.object(polygon, "_get_w3", return_value=fake), \
            patch.object(polygon, "_retry", _fast_retry), \
            patch.object(polygon, "_rpc_deadline", return_value=5):
        assert asyncio.run(polygon.latest_block()) == 123
    assert fake.eth.calls == 2


def test_latest_block_does_not_retry_programmer_errors():
    fake = _FakeW3([ValueError("bad parse"), 123])
    with patch.object(polygon, "_get_w3", return_value=fake), \
            patch.object(polygon, "_retry", _fast_retry), \
            patch.object(polygon, "_rpc_deadline", return_value=5):
        with pytest.raises(ValueError):
            asyncio.run(polygon.latest_block())
    assert fake.eth.calls == 1


def test_latest_block_hang_is_bounded_by_deadline():
    """A peer that never answers can no longer wedge the call: the
    asyncio.timeout deadline fires and (after retries) raises TimeoutError."""
    fake = _FakeW3(["hang", "hang", "hang"])
    single = lambda: AsyncRetrying(  # noqa: E731 — one attempt keeps it fast
        reraise=True, stop=stop_after_attempt(1),
        retry=retry_if_exception_type(TimeoutError),
    )
    with patch.object(polygon, "_get_w3", return_value=fake), \
            patch.object(polygon, "_retry", single), \
            patch.object(polygon, "_rpc_deadline", return_value=0):
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            asyncio.run(polygon.latest_block())
        assert time.monotonic() - started < 2.0


# ---------------------------------------------------------------------
# 3. Adaptive eth_getLogs range
# ---------------------------------------------------------------------


def _scan_recorder(reject_above: int):
    """Fake scan_usdc_transfers that rejects spans wider than the cap —
    the provider-side range-limit behavior."""
    calls: list[tuple[int, int]] = []

    async def _scan(addresses, from_block, to_block, token_address=None):
        calls.append((from_block, to_block))
        if (to_block - from_block + 1) > reject_above:
            raise Web3RPCError("query exceeds max block range")
        return [{"to": "0xabc", "amount": 1.0}]

    return _scan, calls


def test_scan_from_cursor_halves_range_until_provider_accepts():
    scan, calls = _scan_recorder(reject_above=250)
    with patch.object(polygon, "latest_block", AsyncMock(return_value=100_000)), \
            patch.object(polygon, "scan_usdc_transfers", scan):
        transfers, scanned_to = asyncio.run(
            polygon.scan_from_cursor(["0xabc"], cursor=0, lookback=50_000)
        )
    # 1000 rejected -> 500 rejected -> 250 accepted
    assert [e - s + 1 for s, e in calls] == [1000, 500, 250]
    assert transfers and scanned_to == 50_000 + 250 - 1
    # The cursor still ADVANCES on the reduced span — self-healing, no wedge.


def test_scan_from_cursor_reraises_when_floor_exhausted():
    scan, calls = _scan_recorder(reject_above=0)  # provider rejects everything
    with patch.object(polygon, "latest_block", AsyncMock(return_value=100_000)), \
            patch.object(polygon, "scan_usdc_transfers", scan):
        with pytest.raises(Web3RPCError):
            asyncio.run(
                polygon.scan_from_cursor(["0xabc"], cursor=0, lookback=50_000)
            )
    # 1000 -> 500 -> 250 -> 125 -> 62 -> 31 (floor) then reraise
    assert [e - s + 1 for s, e in calls] == [1000, 500, 250, 125, 62, 31]


def test_scan_from_cursor_does_not_halve_transport_errors():
    """Timeouts / throttles / connection drops are not range problems —
    halving would just hammer a sick endpoint 6x. They reraise after the
    in-call retries so the tick fails fast and retries next interval."""
    scan = AsyncMock(side_effect=ClientError("connection reset"))
    with patch.object(polygon, "latest_block", AsyncMock(return_value=100_000)), \
            patch.object(polygon, "scan_usdc_transfers", scan):
        with pytest.raises(ClientError):
            asyncio.run(
                polygon.scan_from_cursor(["0xabc"], cursor=0, lookback=50_000)
            )
    assert scan.await_count == 1


def test_scan_from_cursor_unchanged_contract_on_success():
    """Regression: happy path returns (transfers, end) exactly as before."""
    scan = AsyncMock(return_value=([{"to": "0xabc"}], None))

    async def _ok(addresses, from_block, to_block, token_address=None):
        return [{"to": "0xabc"}]

    with patch.object(polygon, "latest_block", AsyncMock(return_value=5_000)), \
            patch.object(polygon, "scan_usdc_transfers", _ok):
        transfers, scanned_to = asyncio.run(
            polygon.scan_from_cursor(["0xabc"], cursor=3_999, lookback=2_000)
        )
    assert transfers == [{"to": "0xabc"}]
    assert scanned_to == 4_999  # cursor+1 .. min(head, +1000-1)
    assert scan.await_count == 0  # local fake used; just guard the var


# ---------------------------------------------------------------------
# 4. watch_deposits: cursor-read stage is part of the failure surface
# ---------------------------------------------------------------------


class _FakeWatchSettings:
    DEPOSIT_CONFIRMATION_DEPTH = 32
    WRONG_TOKEN_ALERTS_ENABLED = False
    DEPOSIT_SCAN_LOOKBACK_BLOCKS = 50_000


class _WatcherConn:
    async def fetch(self, sql: str, *args):
        if "FROM wallets" in sql:
            return [{
                "user_id": uuid4(),
                "deposit_address": "0x" + "11" * 20,
                "safe_address": None,
                "polymarket_deposit_wallet": None,
            }]
        return []


class _WatcherPool:
    def acquire(self):
        conn = _WatcherConn()

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *_a):
                return None

        return _Ctx()


def test_cursor_read_failure_feeds_the_streak_not_apscheduler():
    """Pre-fix: an exception in _read_cursor escaped watch_deposits entirely
    — invisible to the DOWN escalation. Now it is a counted, staged tick
    failure."""
    fake_log = MagicMock()
    with patch.object(scheduler, "get_settings",
                      return_value=_FakeWatchSettings()), \
            patch.object(scheduler, "get_pool", return_value=_WatcherPool()), \
            patch.object(scheduler.polygon, "latest_block",
                         AsyncMock(return_value=1_000)), \
            patch.object(scheduler, "_read_cursor",
                         AsyncMock(side_effect=RuntimeError("pool wedged"))), \
            patch.object(scheduler, "log", fake_log):
        asyncio.run(scheduler.watch_deposits())  # must NOT raise
    assert scheduler._watch_deposits_fail_streak == 1
    assert fake_log.warning.call_args.kwargs["stage"] == "cursor read"


def test_scan_failure_log_carries_request_context():
    """The failure line now names cursor/head/watched/lookback so one log
    read pins the exact failing request — the block-0 outage hid for five
    weeks behind a context-free line."""
    fake_log = MagicMock()
    with patch.object(scheduler, "get_settings",
                      return_value=_FakeWatchSettings()), \
            patch.object(scheduler, "get_pool", return_value=_WatcherPool()), \
            patch.object(scheduler.polygon, "latest_block",
                         AsyncMock(return_value=1_000)), \
            patch.object(scheduler, "_read_cursor",
                         AsyncMock(return_value=0)), \
            patch.object(scheduler.polygon, "scan_from_cursor",
                         AsyncMock(side_effect=Web3RPCError("range"))), \
            patch.object(scheduler, "log", fake_log):
        asyncio.run(scheduler.watch_deposits())
    kwargs = fake_log.warning.call_args.kwargs
    assert kwargs["stage"] == "scan"
    assert kwargs["cursor"] == 0
    assert kwargs["head"] == 1_000
    assert kwargs["watched"] == 1
    assert kwargs["lookback"] == 50_000


# ---------------------------------------------------------------------
# 5. Relayer SDK calls are bounded
# ---------------------------------------------------------------------


def _stub_relayer_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    models = types.ModuleType("py_builder_relayer_client.models")

    class _OperationType:
        Call = 0

    class _SafeTransaction:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    models.OperationType = _OperationType
    models.SafeTransaction = _SafeTransaction
    pkg = types.ModuleType("py_builder_relayer_client")
    pkg.models = models
    monkeypatch.setitem(sys.modules, "py_builder_relayer_client", pkg)
    monkeypatch.setitem(sys.modules, "py_builder_relayer_client.models", models)


def _custody_fakes(timeout_seconds: float):
    settings = MagicMock()
    settings.USDC_POLYGON = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    settings.USDC_DECIMALS = 6
    settings.RELAYER_CALL_TIMEOUT_SECONDS = timeout_seconds
    w3 = MagicMock()
    w3.eth.contract.return_value.encode_abi.return_value = "0x00"
    return settings, w3


def test_relayer_hang_is_bounded(monkeypatch: pytest.MonkeyPatch):
    _stub_relayer_sdk(monkeypatch)
    settings, w3 = _custody_fakes(timeout_seconds=0.05)
    client = MagicMock()
    client.execute = lambda txs, meta: time.sleep(0.6)  # hung relayer

    from decimal import Decimal
    with patch.object(custody, "get_settings", return_value=settings), \
            patch.object(custody, "_get_w3", return_value=w3):
        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(custody._execute_usdc_transfer(
                client, to="0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
                amount_usdc=Decimal("5"), metadata="t",
            ))


def test_relayer_happy_path_unchanged(monkeypatch: pytest.MonkeyPatch):
    _stub_relayer_sdk(monkeypatch)
    settings, w3 = _custody_fakes(timeout_seconds=5)
    response = MagicMock()
    response.wait = lambda: {"status": "mined"}
    response.transaction_hash = "0xdead"
    response.transaction_id = "tid-1"
    client = MagicMock()
    client.execute = lambda txs, meta: response

    from decimal import Decimal
    with patch.object(custody, "get_settings", return_value=settings), \
            patch.object(custody, "_get_w3", return_value=w3):
        out = asyncio.run(custody._execute_usdc_transfer(
            client, to="0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
            amount_usdc=Decimal("5"), metadata="t",
        ))
    assert out["tx_hash"] == "0xdead"
    assert out["status"] == 1
