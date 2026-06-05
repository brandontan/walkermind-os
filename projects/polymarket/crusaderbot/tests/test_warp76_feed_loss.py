"""WARP-76 H3 — RTDS oracle feed-loss fail-safe.

Pins the protective behaviour added when the Chainlink RTDS WebSocket goes
silent past ``ORACLE_FEED_TIMEOUT_SEC``:

* config: ``ORACLE_FEED_TIMEOUT_SEC`` defaults to 120 and rejects <= 0.
* oracle: ``is_feed_down`` fires only for a feed that delivered ticks then went
  silent (cold start = warming up, not down).
* late_entry_v3: a down feed stamps ``oracle_edge_status='feed_down'``.
* scan loop: a down feed halts evaluation + pages the operator once, and the
  next tick after recovery auto-resumes + pages "restored".

Runtime imports are ``pytest.importorskip``-guarded so the suite runs in CI
(full deps) and skips cleanly in a dependency-less sandbox.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# config — ORACLE_FEED_TIMEOUT_SEC
# ─────────────────────────────────────────────────────────────────────────────


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")


def test_feed_timeout_defaults_to_120(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("pydantic_settings")
    from projects.polymarket.crusaderbot import config as cfg
    _set_required_env(monkeypatch)
    monkeypatch.delenv("ORACLE_FEED_TIMEOUT_SEC", raising=False)
    s = cfg.Settings()  # type: ignore[call-arg]
    assert s.ORACLE_FEED_TIMEOUT_SEC == 120
    cfg.get_settings.cache_clear()


@pytest.mark.parametrize("bad", ["0", "-5"])
def test_feed_timeout_rejects_non_positive(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    pydantic = pytest.importorskip("pydantic")
    from projects.polymarket.crusaderbot import config as cfg
    _set_required_env(monkeypatch)
    monkeypatch.setenv("ORACLE_FEED_TIMEOUT_SEC", bad)
    with pytest.raises(pydantic.ValidationError):
        cfg.Settings()  # type: ignore[call-arg]
    cfg.get_settings.cache_clear()


# ─────────────────────────────────────────────────────────────────────────────
# oracle — is_feed_down / latest_tick_age_sec
# ─────────────────────────────────────────────────────────────────────────────


def _oracle_with_clock(clock):
    rtds = pytest.importorskip(
        "projects.polymarket.crusaderbot.domain.strategy.oracle.rtds"
    )
    o = rtds.PolymarketRTDSOracle(
        ws_url="wss://x", symbols=["btc/usd"], staleness_sec=10.0, clock=clock,
    )
    return rtds, o


def test_feed_down_false_before_any_tick() -> None:
    _, o = _oracle_with_clock(lambda: 1000.0)
    assert o.latest_tick_age_sec() is None
    # cold start = warming up, NOT down (scan must not freeze before first tick)
    assert o.is_feed_down(120) is False


def test_feed_down_true_after_silent_past_timeout() -> None:
    now = [1000.0]
    rtds, o = _oracle_with_clock(lambda: now[0])
    o._ticks["btc/usd"] = rtds._Tick(price=50_000.0, at_monotonic=1000.0)
    assert o.is_feed_down(120) is False  # fresh tick
    now[0] = 1000.0 + 121  # 121s since last tick > 120s timeout
    assert o.is_feed_down(120) is True
    assert o.latest_tick_age_sec() == pytest.approx(121.0)
    now[0] = 1000.0 + 5  # a new fresh tick would reset age
    o._ticks["btc/usd"] = rtds._Tick(price=50_010.0, at_monotonic=now[0])
    assert o.is_feed_down(120) is False  # recovered


# ─────────────────────────────────────────────────────────────────────────────
# late_entry_v3 — feed_down status
# ─────────────────────────────────────────────────────────────────────────────


def test_observe_oracle_edge_reports_feed_down() -> None:
    le = pytest.importorskip(
        "projects.polymarket.crusaderbot.domain.strategy.strategies.late_entry_v3"
    )
    cfg = le.OracleEdgeConfig(
        enabled=True,
        price_provider=lambda _s: 50_000.0,  # would compute, but feed_down wins
        feed_down_provider=lambda: True,
    )
    out = le._observe_oracle_edge(
        cfg, market={}, slug="btc-updown-5m-1771511700",
        seconds_left=300.0, yes_ask=0.5, no_ask=0.5,
    )
    assert out["oracle_edge_status"] == "feed_down"
    assert out["oracle_symbol"] == "btc/usd"


def test_observe_oracle_edge_warming_up_when_feed_up_but_no_price() -> None:
    le = pytest.importorskip(
        "projects.polymarket.crusaderbot.domain.strategy.strategies.late_entry_v3"
    )
    cfg = le.OracleEdgeConfig(
        enabled=True,
        price_provider=lambda _s: None,   # stale/warmup
        feed_down_provider=lambda: False,  # feed is up
    )
    out = le._observe_oracle_edge(
        cfg, market={}, slug="btc-updown-5m-1771511700",
        seconds_left=300.0, yes_ask=0.5, no_ask=0.5,
    )
    assert out["oracle_edge_status"] == "warming_up"


# ─────────────────────────────────────────────────────────────────────────────
# scan loop — halt + alert on feed loss, resume + alert on recovery
# ─────────────────────────────────────────────────────────────────────────────


class _FakeOracle:
    def __init__(self, down: bool) -> None:
        self.down = down

    def is_feed_down(self, _timeout: float) -> bool:
        return self.down


def _wire_scan_gate(monkeypatch, *, oracle, enabled: bool = True):
    """Wire _oracle_feed_halts_scan deps; return (ssj module, captured alerts)."""
    ssj = pytest.importorskip(
        "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job"
    )
    from projects.polymarket.crusaderbot import config as cfg
    from projects.polymarket.crusaderbot import notifications

    alerts: list[str] = []

    async def _notify(text: str, *_a: Any, **_k: Any) -> None:
        alerts.append(text)

    async def _get_oracle():
        return oracle

    monkeypatch.setattr(
        cfg, "get_settings",
        lambda: SimpleNamespace(ORACLE_ENABLED=enabled, ORACLE_FEED_TIMEOUT_SEC=120),
    )
    monkeypatch.setattr(ssj, "get_candle_oracle", _get_oracle)
    monkeypatch.setattr(notifications, "notify_operator", _notify)
    ssj._oracle_feed_down = False  # reset latch
    return ssj, alerts


@pytest.mark.asyncio
async def test_scan_halts_and_pages_on_feed_loss(monkeypatch) -> None:
    ssj, alerts = _wire_scan_gate(monkeypatch, oracle=_FakeOracle(down=True))
    halts = await ssj._oracle_feed_halts_scan()
    assert halts is True
    assert ssj._oracle_feed_down is True
    assert len(alerts) == 1
    assert "RTDS feed lost — scan halted" in alerts[0]


@pytest.mark.asyncio
async def test_scan_resumes_and_pages_on_recovery(monkeypatch) -> None:
    oracle = _FakeOracle(down=True)
    ssj, alerts = _wire_scan_gate(monkeypatch, oracle=oracle)
    # 1st tick: feed down → halt + "lost"
    assert await ssj._oracle_feed_halts_scan() is True
    # feed recovers; 2nd tick → resume + "restored"
    oracle.down = False
    assert await ssj._oracle_feed_halts_scan() is False
    assert ssj._oracle_feed_down is False
    assert len(alerts) == 2
    assert "RTDS feed lost — scan halted" in alerts[0]
    assert "RTDS feed restored — scan resumed" in alerts[1]


@pytest.mark.asyncio
async def test_no_halt_when_oracle_disabled(monkeypatch) -> None:
    ssj, alerts = _wire_scan_gate(
        monkeypatch, oracle=_FakeOracle(down=True), enabled=False,
    )
    assert await ssj._oracle_feed_halts_scan() is False
    assert alerts == []


@pytest.mark.asyncio
async def test_feed_loss_pages_only_once_until_recovery(monkeypatch) -> None:
    ssj, alerts = _wire_scan_gate(monkeypatch, oracle=_FakeOracle(down=True))
    await ssj._oracle_feed_halts_scan()
    await ssj._oracle_feed_halts_scan()  # still down — must NOT re-page
    assert len(alerts) == 1
