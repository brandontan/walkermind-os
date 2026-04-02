"""SENTINEL — Production Bootstrap Test Suite.

Validates the core.bootstrap module:

  PB-01  validate_credentials — passes when all required env vars are present
  PB-02  validate_credentials — raises RuntimeError when CLOB_API_KEY missing
  PB-03  validate_credentials — raises RuntimeError when CLOB_API_SECRET missing
  PB-04  validate_credentials — raises RuntimeError when CLOB_API_PASSPHRASE missing
  PB-05  validate_credentials — raises RuntimeError when TELEGRAM_TOKEN missing
  PB-06  validate_credentials — raises RuntimeError when TELEGRAM_CHAT_ID missing
  PB-07  validate_credentials — accepts TELEGRAM_BOT_TOKEN as TELEGRAM_TOKEN alias
  PB-08  validate_credentials — error message lists every missing variable
  PB-09  build_config — defaults MODE to PAPER when unset
  PB-10  build_config — respects TRADING_MODE env var
  PB-11  build_config — respects MODE env var when TRADING_MODE not set
  PB-12  build_config — TRADING_MODE takes precedence over MODE
  PB-13  build_config — numeric defaults are correct
  PB-14  build_config — numeric env overrides are applied
  PB-15  build_config — returned dict has all required keys
  PB-16  discover_markets — returns explicit MARKET_IDS from env
  PB-17  discover_markets — calls Gamma API when MARKET_IDS not set
  PB-18  discover_markets — filters markets below min_liquidity
  PB-19  discover_markets — sorts by volume and returns top-N
  PB-20  discover_markets — raises RuntimeError when discovery returns zero markets
  PB-21  discover_markets — handles list-shaped Gamma response
  PB-22  discover_markets — handles dict-shaped Gamma response (markets key)
  PB-23  discover_markets — respects MAX_MARKETS env var
  PB-24  discover_markets — raises RuntimeError on HTTP error from Gamma API
  PB-25  run_bootstrap — returns (cfg, market_ids) tuple on success
  PB-26  run_bootstrap — raises RuntimeError when credentials missing
  PB-27  run_bootstrap — raises RuntimeError when market discovery fails
"""
from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_FULL_ENV = {
    "CLOB_API_KEY": "key-abc",
    "CLOB_API_SECRET": "secret-xyz",
    "CLOB_API_PASSPHRASE": "pass-123",
    "TELEGRAM_TOKEN": "bot-token",
    "TELEGRAM_CHAT_ID": "12345",
}


def _make_gamma_market(
    condition_id: str,
    volume: float = 20_000.0,
    active: bool = True,
) -> dict:
    return {
        "conditionId": condition_id,
        "active": active,
        "closed": False,
        "volume": volume,
    }


def _mock_aiohttp_response(status: int, json_data: Any):
    """Return a mock aiohttp ClientSession context manager yielding *json_data*."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)

    session = AsyncMock()
    session.get = MagicMock(return_value=resp)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    return session


# ─────────────────────────────────────────────────────────────────────────────
# PB-01 – PB-08  validate_credentials
# ─────────────────────────────────────────────────────────────────────────────


class TestValidateCredentials:
    def _run(self, env: dict):
        from projects.polymarket.polyquantbot.core.bootstrap import validate_credentials

        with patch.dict(os.environ, env, clear=True):
            validate_credentials()

    # PB-01
    def test_passes_when_all_present(self):
        self._run(_FULL_ENV)  # must not raise

    # PB-02
    def test_raises_missing_clob_key(self):
        env = {k: v for k, v in _FULL_ENV.items() if k != "CLOB_API_KEY"}
        with pytest.raises(RuntimeError, match="CLOB_API_KEY"):
            self._run(env)

    # PB-03
    def test_raises_missing_clob_secret(self):
        env = {k: v for k, v in _FULL_ENV.items() if k != "CLOB_API_SECRET"}
        with pytest.raises(RuntimeError, match="CLOB_API_SECRET"):
            self._run(env)

    # PB-04
    def test_raises_missing_clob_passphrase(self):
        env = {k: v for k, v in _FULL_ENV.items() if k != "CLOB_API_PASSPHRASE"}
        with pytest.raises(RuntimeError, match="CLOB_API_PASSPHRASE"):
            self._run(env)

    # PB-05
    def test_raises_missing_telegram_token(self):
        env = {k: v for k, v in _FULL_ENV.items() if k != "TELEGRAM_TOKEN"}
        with pytest.raises(RuntimeError, match="TELEGRAM_TOKEN"):
            self._run(env)

    # PB-06
    def test_raises_missing_telegram_chat_id(self):
        env = {k: v for k, v in _FULL_ENV.items() if k != "TELEGRAM_CHAT_ID"}
        with pytest.raises(RuntimeError, match="TELEGRAM_CHAT_ID"):
            self._run(env)

    # PB-07
    def test_accepts_telegram_bot_token_alias(self):
        env = {k: v for k, v in _FULL_ENV.items() if k != "TELEGRAM_TOKEN"}
        env["TELEGRAM_BOT_TOKEN"] = "bot-token-alt"
        self._run(env)  # must not raise

    # PB-08
    def test_error_message_lists_all_missing(self):
        env = {}  # everything missing
        with pytest.raises(RuntimeError) as exc_info:
            self._run(env)
        msg = str(exc_info.value)
        assert "CLOB_API_KEY" in msg
        assert "CLOB_API_SECRET" in msg
        assert "CLOB_API_PASSPHRASE" in msg
        assert "TELEGRAM" in msg


# ─────────────────────────────────────────────────────────────────────────────
# PB-09 – PB-15  build_config
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildConfig:
    def _build(self, env: dict) -> dict:
        from projects.polymarket.polyquantbot.core.bootstrap import build_config

        with patch.dict(os.environ, env, clear=True):
            return build_config()

    # PB-09
    def test_mode_defaults_to_paper(self):
        cfg = self._build({})
        assert cfg["go_live"]["mode"] == "PAPER"

    # PB-10
    def test_respects_trading_mode_env(self):
        cfg = self._build({"TRADING_MODE": "live"})
        assert cfg["go_live"]["mode"] == "LIVE"

    # PB-11
    def test_respects_mode_env(self):
        cfg = self._build({"MODE": "live"})
        assert cfg["go_live"]["mode"] == "LIVE"

    # PB-12
    def test_trading_mode_takes_precedence(self):
        cfg = self._build({"TRADING_MODE": "LIVE", "MODE": "PAPER"})
        assert cfg["go_live"]["mode"] == "LIVE"

    # PB-13
    def test_numeric_defaults(self):
        cfg = self._build({})
        assert cfg["go_live"]["max_capital_usd"] == 10_000.0
        assert cfg["go_live"]["max_trades_per_day"] == 200
        assert cfg["risk"]["daily_loss_limit"] == -2_000.0
        assert cfg["risk"]["max_drawdown_pct"] == 0.08
        assert cfg["execution_guard"]["min_liquidity_usd"] == 10_000.0

    # PB-14
    def test_numeric_env_overrides(self):
        cfg = self._build({
            "MAX_CAPITAL_USD": "5000",
            "DAILY_LOSS_LIMIT": "-1000",
            "MIN_LIQUIDITY_USD": "50000",
        })
        assert cfg["go_live"]["max_capital_usd"] == 5_000.0
        assert cfg["risk"]["daily_loss_limit"] == -1_000.0
        assert cfg["execution_guard"]["min_liquidity_usd"] == 50_000.0

    # PB-15
    def test_required_keys_present(self):
        cfg = self._build({})
        assert "websocket" in cfg
        assert "go_live" in cfg
        assert "risk" in cfg
        assert "metrics" in cfg
        assert "execution_guard" in cfg


# ─────────────────────────────────────────────────────────────────────────────
# PB-16 – PB-24  discover_markets
# ─────────────────────────────────────────────────────────────────────────────


class TestDiscoverMarkets:
    _BASE_CFG = {
        "execution_guard": {"min_liquidity_usd": 10_000.0},
    }

    async def _run(self, env: dict, cfg: dict | None = None) -> tuple[list[str], list[dict]]:
        from projects.polymarket.polyquantbot.core.bootstrap import discover_markets

        with patch.dict(os.environ, env, clear=True):
            return await discover_markets(cfg or self._BASE_CFG)

    # PB-16
    async def test_returns_explicit_market_ids(self):
        market_ids, market_meta = await self._run({"MARKET_IDS": "0xaaa,0xbbb,0xccc"})
        assert market_ids == ["0xaaa", "0xbbb", "0xccc"]

    # PB-17
    async def test_calls_gamma_api_when_no_market_ids(self):
        markets = [_make_gamma_market("0xaaa", 25_000), _make_gamma_market("0xbbb", 15_000)]
        session = _mock_aiohttp_response(200, markets)
        with patch("aiohttp.ClientSession", return_value=session):
            market_ids, market_meta = await self._run({})
        assert "0xaaa" in market_ids

    # PB-18
    async def test_filters_below_min_liquidity(self):
        markets = [
            _make_gamma_market("0xhigh", 50_000),
            _make_gamma_market("0xlow", 500),   # below threshold
        ]
        session = _mock_aiohttp_response(200, markets)
        with patch("aiohttp.ClientSession", return_value=session):
            market_ids, market_meta = await self._run({})
        assert "0xhigh" in market_ids
        assert "0xlow" not in market_ids

    # PB-19
    async def test_returns_top_n_sorted_by_volume(self):
        markets = [
            _make_gamma_market("0x3rd", 30_000),
            _make_gamma_market("0x1st", 90_000),
            _make_gamma_market("0x2nd", 60_000),
            _make_gamma_market("0x4th", 20_000),
            _make_gamma_market("0x5th", 15_000),
            _make_gamma_market("0x6th", 12_000),
        ]
        session = _mock_aiohttp_response(200, markets)
        with patch("aiohttp.ClientSession", return_value=session):
            market_ids, market_meta = await self._run({"MAX_MARKETS": "3"})
        assert market_ids == ["0x1st", "0x2nd", "0x3rd"]

    # PB-20
    async def test_raises_when_discovery_empty(self):
        session = _mock_aiohttp_response(200, [])
        with patch("aiohttp.ClientSession", return_value=session):
            with pytest.raises(RuntimeError, match="zero qualifying"):
                await self._run({})

    # PB-21
    async def test_handles_list_response(self):
        markets = [_make_gamma_market("0xlist", 20_000)]
        session = _mock_aiohttp_response(200, markets)
        with patch("aiohttp.ClientSession", return_value=session):
            market_ids, market_meta = await self._run({})
        assert "0xlist" in market_ids

    # PB-22
    async def test_handles_dict_response(self):
        markets = [_make_gamma_market("0xdict", 20_000)]
        session = _mock_aiohttp_response(200, {"markets": markets})
        with patch("aiohttp.ClientSession", return_value=session):
            market_ids, market_meta = await self._run({})
        assert "0xdict" in market_ids

    # PB-23
    async def test_respects_max_markets_env(self):
        markets = [_make_gamma_market(f"0x{i:03}", 10_000 + i * 1_000) for i in range(10)]
        session = _mock_aiohttp_response(200, markets)
        with patch("aiohttp.ClientSession", return_value=session):
            market_ids, market_meta = await self._run({"MAX_MARKETS": "2"})
        assert len(market_ids) == 2

    # PB-24  HTTP errors are now retried then fall back gracefully so the
    #        pipeline doesn't crash; discover_markets still raises because zero
    #        qualifying markets result from the empty market list.
    async def test_raises_on_gamma_http_error(self):
        session = _mock_aiohttp_response(503, {})
        with patch("aiohttp.ClientSession", return_value=session):
            with patch("asyncio.sleep"):  # skip retry back-off delays
                with pytest.raises(RuntimeError, match="zero qualifying"):
                    await self._run({})


# ─────────────────────────────────────────────────────────────────────────────
# PB-25 – PB-27  run_bootstrap
# ─────────────────────────────────────────────────────────────────────="────────


class TestRunBootstrap:
    async def _run(self, env: dict, market_ids: list[str] | None = None) -> tuple:
        from projects.polymarket.polyquantbot.core.bootstrap import run_bootstrap

        mock_ids = market_ids if market_ids is not None else ["0xaaa"]
        with patch.dict(os.environ, env, clear=True):
            with patch(
                "projects.polymarket.polyquantbot.core.bootstrap.discover_markets",
                new=AsyncMock(return_value=(mock_ids, [])),
            ):
                return await run_bootstrap()

    # PB-25
    async def test_returns_cfg_and_market_ids(self):
        cfg, ids, meta = await self._run(_FULL_ENV)
        assert isinstance(cfg, dict)
        assert isinstance(ids, list)
        assert len(ids) > 0

    # PB-26
    async def test_raises_when_credentials_missing(self):
        with pytest.raises(RuntimeError, match="CLOB_API_KEY"):
            env = {k: v for k, v in _FULL_ENV.items() if k != "CLOB_API_KEY"}
            with patch.dict(os.environ, env, clear=True):
                from projects.polymarket.polyquantbot.core.bootstrap import run_bootstrap

                await run_bootstrap()

    # PB-27
    async def test_raises_when_market_discovery_fails(self):
        from projects.polymarket.polyquantbot.core.bootstrap import run_bootstrap

        with patch.dict(os.environ, _FULL_ENV, clear=True):
            with patch(
                "projects.polymarket.polyquantbot.core.bootstrap.discover_markets",
                new=AsyncMock(side_effect=RuntimeError("zero qualifying markets")),
            ):
                with pytest.raises(RuntimeError, match="zero qualifying"):
                    await run_bootstrap()
