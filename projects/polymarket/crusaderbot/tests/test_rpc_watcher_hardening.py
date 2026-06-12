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
      span halves adaptively down to ``_MIN_SCAN_RANGE`` (= 1: Alchemy Free
      caps at 10 blocks, below the old 31 floor — the cap that kept the prod
      cursor at block 0 for five weeks) and the scan walks the window in
      accepted-size CHUNKS under a per-tick ``max_rpc`` budget, so a tiny
      provider cap still advances the cursor (transport errors are NOT
      halved, and partial coverage is returned rather than thrown away);
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
from aiohttp import ClientError, ClientResponseError
from tenacity import (
    AsyncRetrying, retry_if_exception_type, stop_after_attempt,
)
from web3.exceptions import Web3RPCError

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot import scheduler

# Hermetic stand-in: primary_deposit_asset() reads the full Settings model.
from types import SimpleNamespace as _NS

_FAKE_DEPOSIT_ASSET = _NS(
    token_symbol="USDC.e", token_contract="0x" + "27" * 20,
    network="Polygon", chain_id=137, decimals=6,
)
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
    polygon._accepted_span.clear()
    crusaderbot_config.get_settings.cache_clear()
    scheduler._watch_deposits_fail_streak = 0
    yield
    polygon._w3 = None
    polygon._usdc = None
    polygon._accepted_span.clear()
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
    assert crusaderbot_config.Settings.model_fields[
        "DEPOSIT_SCAN_MAX_RPC_PER_TICK"].default == 60


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

    async def _scan(addresses, from_block, to_block, token_address=None,
                    token_decimals=None):
        calls.append((from_block, to_block))
        if (to_block - from_block + 1) > reject_above:
            raise Web3RPCError("query exceeds max block range")
        return [{"to": "0xabc", "amount": 1.0}]

    return _scan, calls


def test_scan_from_cursor_halves_range_then_chunks_to_budget():
    scan, calls = _scan_recorder(reject_above=250)
    with patch.object(polygon, "latest_block", AsyncMock(return_value=100_000)), \
            patch.object(polygon, "scan_usdc_transfers", scan):
        transfers, scanned_to = asyncio.run(
            polygon.scan_from_cursor(["0xabc"], cursor=0, lookback=50_000)
        )
    # 1000 rejected -> 500 rejected -> 250 accepted, then the remaining
    # budget (60 - 2 rejected probes = 58 accepted chunks) walks the window
    # in 250-block chunks. The cursor ADVANCES over everything covered.
    spans = [e - s + 1 for s, e in calls]
    assert spans == [1000, 500] + [250] * 58
    assert len(transfers) == 58
    assert scanned_to == 50_000 + 58 * 250 - 1
    # Chunks are contiguous: each starts right after the previous end.
    accepted = calls[2:]
    assert all(accepted[i + 1][0] == accepted[i][1] + 1
               for i in range(len(accepted) - 1))


def test_scan_from_cursor_reraises_when_floor_exhausted():
    scan, calls = _scan_recorder(reject_above=0)  # provider rejects everything
    with patch.object(polygon, "latest_block", AsyncMock(return_value=100_000)), \
            patch.object(polygon, "scan_usdc_transfers", scan):
        with pytest.raises(Web3RPCError):
            asyncio.run(
                polygon.scan_from_cursor(["0xabc"], cursor=0, lookback=50_000)
            )
    # Full ladder down to the single-block floor, then reraise: a provider
    # that rejects a ONE-block range is genuinely broken, not range-capped.
    assert [e - s + 1 for s, e in calls] == [
        1000, 500, 250, 125, 62, 31, 15, 7, 3, 1,
    ]


def test_scan_from_cursor_survives_ten_block_provider_cap():
    """THE 2026-06-11 prod outage shape: Alchemy Free rejects any
    eth_getLogs over 10 blocks (HTTP 400). The old 31-block floor sat ABOVE
    the cap, so every tick failed and the cursor never left block 0. The
    ladder must now walk below the cap and chunk forward from there."""
    calls: list[tuple[int, int]] = []

    async def _scan(addresses, from_block, to_block, token_address=None,
                    token_decimals=None):
        calls.append((from_block, to_block))
        if (to_block - from_block + 1) > 10:
            raise _http_rejection(400)
        return [{"to": "0xabc", "amount": 1.0}]

    with patch.object(polygon, "latest_block", AsyncMock(return_value=100_000)), \
            patch.object(polygon, "scan_usdc_transfers", _scan):
        transfers, scanned_to = asyncio.run(
            polygon.scan_from_cursor(["0xabc"], cursor=0, lookback=50_000)
        )
    spans = [e - s + 1 for s, e in calls]
    # 7 rejected probes (1000..15) discover span 7, then 53 accepted chunks.
    assert spans == [1000, 500, 250, 125, 62, 31, 15] + [7] * 53
    assert len(transfers) == 53
    assert scanned_to == 50_000 + 53 * 7 - 1
    # Discovered span is remembered — the next tick opens at 7, no re-walk.
    assert polygon._accepted_span[None][0] == 7


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


def _http_rejection(status: int) -> ClientResponseError:
    return ClientResponseError(None, (), status=status, message="provider says no")


def test_scan_from_cursor_halves_on_http_400_rejection():
    """web3 v7 raise_for_status()es non-2xx BEFORE parsing the JSON-RPC body,
    so an Alchemy-class range/size cap arrives as ClientResponseError(400) —
    NOT Web3RPCError. The adaptive scan must treat that as a range verdict
    (halve), or the prod block-0 outage mode persists on such vendors."""
    calls: list[tuple[int, int]] = []

    async def _scan(addresses, from_block, to_block, token_address=None,
                    token_decimals=None):
        calls.append((from_block, to_block))
        if (to_block - from_block + 1) > 250:
            raise _http_rejection(400)
        return [{"to": "0xabc", "amount": 1.0}]

    with patch.object(polygon, "latest_block", AsyncMock(return_value=100_000)), \
            patch.object(polygon, "scan_usdc_transfers", _scan):
        transfers, scanned_to = asyncio.run(
            polygon.scan_from_cursor(["0xabc"], cursor=0, lookback=50_000)
        )
    spans = [e - s + 1 for s, e in calls]
    assert spans == [1000, 500] + [250] * 58
    assert len(transfers) == 58
    assert scanned_to == 50_000 + 58 * 250 - 1


def test_scan_from_cursor_treats_429_as_transport():
    """A throttle is not a range verdict — no halving, fail fast, retry next
    tick (the per-call tenacity layer already backs 429s off)."""
    scan = AsyncMock(side_effect=_http_rejection(429))
    with patch.object(polygon, "latest_block", AsyncMock(return_value=100_000)), \
            patch.object(polygon, "scan_usdc_transfers", scan):
        with pytest.raises(ClientResponseError):
            asyncio.run(
                polygon.scan_from_cursor(["0xabc"], cursor=0, lookback=50_000)
            )
    assert scan.await_count == 1


def test_accepted_span_is_remembered_without_oscillation():
    """The halving ladder must not be re-walked from max_range every tick;
    a tick that just halved must not store the size it saw rejected (Gemini
    #1762); and ONLY clean FULL-WINDOW passes build the probe-up streak
    (Gemini #1763) — a budget-exhausted catch-up tick never wastes a probe
    request on a span the provider just capped. The probe fires after
    _PROBE_UP_AFTER clean full passes, gets rejected once, and settles."""
    calls: list[tuple[int, int]] = []
    cursor = 0

    async def _scan(addresses, from_block, to_block, token_address=None,
                    token_decimals=None):
        calls.append((from_block, to_block))
        if (to_block - from_block + 1) > 250:
            raise _http_rejection(400)
        return []

    def _tick(head: int, **kw):
        nonlocal cursor
        with patch.object(polygon, "latest_block",
                          AsyncMock(return_value=head)):
            _, scanned_to = asyncio.run(polygon.scan_from_cursor(
                ["0xabc"], cursor=cursor, lookback=50_000, **kw,
            ))
        cursor = scanned_to
        spans = [e - s + 1 for s, e in calls]
        calls.clear()
        return spans

    with patch.object(polygon, "scan_usdc_transfers", _scan):
        # Discovery walk, once — deep window, budget-exhausted.
        assert _tick(100_000, max_rpc=3) == [1000, 500, 250]
        # Catch-up (budget exhausted every tick): opens at the remembered
        # 250 with NO re-walk and NO upward probe, however many ticks pass.
        for _ in range(polygon._PROBE_UP_AFTER + 1):
            assert _tick(100_000, max_rpc=3) == [250, 250, 250]
        # Caught up: clean full-window passes (2 chunks each) build the
        # streak; the tick after the streak-th probes 500, gets rejected
        # once, and settles back — bounded, infrequent probing.
        for _ in range(polygon._PROBE_UP_AFTER):
            assert _tick(cursor + 500) == [250, 250]
        assert _tick(cursor + 500) == [500, 250, 250]


def test_should_retry_classification():
    assert polygon._should_retry(_http_rejection(400)) is False
    assert polygon._should_retry(_http_rejection(413)) is False
    assert polygon._should_retry(_http_rejection(429)) is True
    assert polygon._should_retry(_http_rejection(503)) is True
    assert polygon._should_retry(Web3RPCError("limit")) is True
    assert polygon._should_retry(ClientError("conn reset")) is True
    assert polygon._should_retry(TimeoutError()) is True
    assert polygon._should_retry(ValueError("bug")) is False


def test_scan_from_cursor_covers_window_to_head_on_success():
    """Happy path: an uncapped provider covers the whole window to head
    within budget — one full-span chunk plus the 1-block remainder — and
    returns every transfer with scanned_to == head."""

    async def _ok(addresses, from_block, to_block, token_address=None,
                  token_decimals=None):
        return [{"to": "0xabc"}]

    with patch.object(polygon, "latest_block", AsyncMock(return_value=5_000)), \
            patch.object(polygon, "scan_usdc_transfers", _ok):
        transfers, scanned_to = asyncio.run(
            polygon.scan_from_cursor(["0xabc"], cursor=3_999, lookback=2_000)
        )
    # 4_000..4_999 (span 1000) then 5_000..5_000 — window fully drained.
    assert transfers == [{"to": "0xabc"}] * 2
    assert scanned_to == 5_000


def test_scan_from_cursor_keeps_partial_coverage_on_midcall_transport():
    """A transport failure AFTER some chunks succeeded must not throw the
    coverage away: the covered range is returned (cursor advances past it)
    and the failing offset is retried at the start of the next tick — where
    a repeat failure raises and feeds the DOWN escalation."""
    calls: list[tuple[int, int]] = []

    async def _scan(addresses, from_block, to_block, token_address=None,
                    token_decimals=None):
        calls.append((from_block, to_block))
        if len(calls) == 3:
            raise ClientError("connection reset")
        return [{"to": "0xabc", "amount": 1.0}]

    with patch.object(polygon, "latest_block", AsyncMock(return_value=100_000)), \
            patch.object(polygon, "scan_usdc_transfers", _scan):
        transfers, scanned_to = asyncio.run(
            polygon.scan_from_cursor(["0xabc"], cursor=0, lookback=50_000)
        )
    assert len(calls) == 3
    assert len(transfers) == 2
    assert scanned_to == 50_000 + 2 * 1000 - 1


def test_scan_from_cursor_zero_coverage_budget_burn_raises():
    """If the whole rpc budget burns on rejected probes without ONE accepted
    chunk, the tick must fail loudly (streak escalation), never return a
    silent empty success that would advance nothing forever."""
    scan, calls = _scan_recorder(reject_above=0)
    with patch.object(polygon, "latest_block", AsyncMock(return_value=100_000)), \
            patch.object(polygon, "scan_usdc_transfers", scan):
        with pytest.raises(Web3RPCError, match="no chunk accepted"):
            asyncio.run(polygon.scan_from_cursor(
                ["0xabc"], cursor=0, lookback=50_000, max_rpc=3,
            ))
    assert [e - s + 1 for s, e in calls] == [1000, 500, 250]


# ---------------------------------------------------------------------
# 4. watch_deposits: cursor-read stage is part of the failure surface
# ---------------------------------------------------------------------


class _FakeWatchSettings:
    DEPOSIT_CONFIRMATION_DEPTH = 32
    WRONG_TOKEN_ALERTS_ENABLED = False
    DEPOSIT_SCAN_LOOKBACK_BLOCKS = 50_000
    DEPOSIT_SCAN_MAX_RPC_PER_TICK = 77


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


def test_watch_deposits_threads_rpc_budget_from_settings():
    """The per-tick request budget is operator-tunable: watch_deposits must
    pass DEPOSIT_SCAN_MAX_RPC_PER_TICK through to scan_from_cursor."""
    scan = AsyncMock(side_effect=Web3RPCError("range"))
    with patch.object(scheduler, "get_settings",
                      return_value=_FakeWatchSettings()), \
            patch.object(scheduler, "get_pool", return_value=_WatcherPool()), \
            patch.object(scheduler.polygon, "latest_block",
                         AsyncMock(return_value=1_000)), \
            patch.object(scheduler, "_read_cursor",
                         AsyncMock(return_value=0)), \
            patch.object(scheduler, "primary_deposit_asset",
                         lambda: _FAKE_DEPOSIT_ASSET), \
            patch.object(scheduler.polygon, "scan_from_cursor", scan), \
            patch.object(scheduler, "log", MagicMock()):
        asyncio.run(scheduler.watch_deposits())
    assert scan.await_args.kwargs["max_rpc"] == 77
    assert scan.await_args.kwargs["lookback"] == 50_000


# ---------------------------------------------------------------------
# 5. RPC secrets never reach logs
# ---------------------------------------------------------------------


def _redact_settings():
    return types.SimpleNamespace(
        POLYGON_RPC_URL="https://polygon-mainnet.g.alchemy.com/v2/SECRETKEY12345678",
        ALCHEMY_POLYGON_RPC_URL=None,
        ALCHEMY_POLYGON_WS_URL="wss://polygon-mainnet.g.alchemy.com/v2/WSKEY9876543210",
    )


def test_redact_rpc_secrets_strips_api_key():
    """aiohttp error reprs carry the full request URL — provider API key
    included. The redactor must strip every configured key while keeping
    the host (the diagnostic part) readable."""
    raw = (
        "ClientResponseError(RequestInfo(url=URL("
        "'https://polygon-mainnet.g.alchemy.com/v2/SECRETKEY12345678'), "
        "real_url=URL('https://polygon-mainnet.g.alchemy.com/v2/"
        "SECRETKEY12345678')), status=400) via wss://polygon-mainnet"
        ".g.alchemy.com/v2/WSKEY9876543210"
    )
    with patch.object(polygon, "get_settings", return_value=_redact_settings()):
        out = polygon.redact_rpc_secrets(raw)
    assert "SECRETKEY12345678" not in out
    assert "WSKEY9876543210" not in out
    assert "polygon-mainnet.g.alchemy.com" in out
    assert "[redacted]" in out


def test_redact_rpc_secrets_handles_empty_query_string():
    """A configured URL ending in '?' yields an empty query string —
    str.replace('', x) would insert x between EVERY character of the log
    line (Gemini #1763). The redactor must leave unrelated text intact."""
    settings = types.SimpleNamespace(
        POLYGON_RPC_URL="https://rpc.example/v2/TRAILINGKEY12345?",
        ALCHEMY_POLYGON_RPC_URL=None,
        ALCHEMY_POLYGON_WS_URL=None,
    )
    with patch.object(polygon, "get_settings", return_value=settings):
        assert polygon.redact_rpc_secrets("plain text") == "plain text"
        assert "TRAILINGKEY12345" not in polygon.redact_rpc_secrets(
            "err at https://rpc.example/v2/TRAILINGKEY12345?"
        )


def test_watch_deposits_failure_line_redacts_rpc_key():
    """The watcher DOWN/tick-failed line goes to Fly logs + Sentry — it must
    never carry the provider API key embedded in aiohttp's error repr."""
    fake_log = MagicMock()
    boom = Web3RPCError(
        "rejected by https://polygon-mainnet.g.alchemy.com/v2/SECRETKEY12345678"
    )
    with patch.object(scheduler, "get_settings",
                      return_value=_FakeWatchSettings()), \
            patch.object(scheduler, "get_pool", return_value=_WatcherPool()), \
            patch.object(scheduler.polygon, "latest_block",
                         AsyncMock(return_value=1_000)), \
            patch.object(scheduler, "_read_cursor",
                         AsyncMock(return_value=0)), \
            patch.object(scheduler, "primary_deposit_asset",
                         lambda: _FAKE_DEPOSIT_ASSET), \
            patch.object(scheduler.polygon, "scan_from_cursor",
                         AsyncMock(side_effect=boom)), \
            patch.object(polygon, "get_settings",
                         return_value=_redact_settings()), \
            patch.object(scheduler, "log", fake_log):
        asyncio.run(scheduler.watch_deposits())
    err = fake_log.warning.call_args.kwargs["err"]
    assert "SECRETKEY12345678" not in err
    assert "[redacted]" in err


def test_configure_json_logging_quiets_httpx_request_urls():
    """httpx logs every request URL at INFO — for Telegram that URL embeds
    the bot token (api.telegram.org/bot<TOKEN>/...). The logging setup must
    pin the httpx logger to WARNING so those lines never reach Fly logs."""
    import logging as _logging

    import structlog as _structlog

    from projects.polymarket.crusaderbot.monitoring.logging import (
        configure_json_logging,
    )

    root = _logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_httpx_level = _logging.getLogger("httpx").level
    saved_structlog = _structlog.get_config()
    try:
        configure_json_logging("INFO")
        assert _logging.getLogger("httpx").level == _logging.WARNING
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)
        _logging.getLogger("httpx").setLevel(saved_httpx_level)
        _structlog.configure(**saved_structlog)


# ---------------------------------------------------------------------
# 6. Relayer SDK calls are bounded
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
