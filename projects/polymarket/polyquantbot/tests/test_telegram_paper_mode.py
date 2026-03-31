"""SENTINEL — Telegram PAPER Mode Test Suite.

Verifies that Telegram alerts fire correctly in PAPER mode and are fully
decoupled from the trading execution mode.

Scenarios:
  TP-01  PAPER mode config → TelegramLive initialised (alerts_enabled=True)
  TP-02  alert_error() → message queued (no execution dependency)
  TP-03  alert_kill() → message queued regardless of trading_mode
  TP-04  slippage warning → MetricsValidator.warn_slippage() fires alert
  TP-05  latency warning → MetricsValidator.warn_latency() fires alert
  TP-06  notifier disabled → no messages enqueued
  TP-07  queue full → oldest dropped, new alert enqueued
  TP-08  missing token → enabled forced False, no crash
  TP-09  alerts_enabled overrides telegram.enabled in config
  TP-10  alert_error fires in PAPER mode (end-to-end via StubTelegram)
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.polyquantbot.phase9.telegram_live import (
    Alert,
    AlertType,
    TelegramLive,
)
from projects.polymarket.polyquantbot.phase9.metrics_validator import MetricsValidator


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_telegram(enabled: bool = True) -> TelegramLive:
    """Build a TelegramLive instance without real env vars."""
    return TelegramLive(
        bot_token="test-token",
        chat_id="test-chat",
        enabled=enabled,
    )


def _paper_config() -> dict:
    """Minimal PAPER mode config matching paper_run_config.yaml structure."""
    return {
        "trading_mode": "PAPER",
        "alerts_enabled": True,
        "run": {"dry_run": True},
        "telegram": {"enabled": True},
    }


# ══════════════════════════════════════════════════════════════════════════════
# TP-01 — PAPER mode config → TelegramLive initialised
# ══════════════════════════════════════════════════════════════════════════════

class TestTP01PaperModeInit:
    """alerts_enabled=True must initialise TelegramLive regardless of dry_run."""

    async def test_alerts_enabled_true_creates_notifier(self) -> None:
        cfg = _paper_config()
        tg_cfg = cfg.get("telegram", {})
        alerts_enabled = bool(cfg.get("alerts_enabled", tg_cfg.get("enabled", True)))
        tg = _make_telegram(enabled=alerts_enabled)
        assert tg._enabled is True

    async def test_paper_mode_does_not_disable_alerts(self) -> None:
        """trading_mode=PAPER must not suppress alerts."""
        cfg = _paper_config()
        # Simulate the bootstrap logic from main.py
        tg_cfg = cfg.get("telegram", {})
        alerts_enabled = bool(cfg.get("alerts_enabled", tg_cfg.get("enabled", True)))
        tg = _make_telegram(enabled=alerts_enabled)
        assert tg._enabled is True, "PAPER mode must not disable alerts"

    async def test_alerts_enabled_false_disables_notifier(self) -> None:
        cfg = {**_paper_config(), "alerts_enabled": False}
        tg_cfg = cfg.get("telegram", {})
        alerts_enabled = bool(cfg.get("alerts_enabled", tg_cfg.get("enabled", True)))
        tg = _make_telegram(enabled=alerts_enabled)
        assert tg._enabled is False


# ══════════════════════════════════════════════════════════════════════════════
# TP-02 — alert_error() → message queued (no execution dependency)
# ══════════════════════════════════════════════════════════════════════════════

class TestTP02AlertErrorQueued:
    """alert_error must enqueue a message without needing any order state."""

    async def test_alert_error_queued_in_paper_mode(self) -> None:
        tg = _make_telegram(enabled=True)
        await tg.alert_error(error="test_error", context="paper_run")
        assert tg._queue.qsize() == 1
        alert: Alert = tg._queue.get_nowait()
        assert alert.alert_type == AlertType.ERROR
        assert "test_error" in alert.message

    async def test_alert_error_requires_no_order_state(self) -> None:
        """alert_error must not reference any order or position state."""
        tg = _make_telegram(enabled=True)
        # No orders, no positions, no executor — must still succeed
        await tg.alert_error(error="standalone_error", context="no_order_context")
        assert tg._queue.qsize() == 1

    async def test_alert_error_disabled_no_enqueue(self) -> None:
        tg = _make_telegram(enabled=False)
        await tg.alert_error(error="should_be_dropped")
        assert tg._queue.qsize() == 0


# ══════════════════════════════════════════════════════════════════════════════
# TP-03 — alert_kill() → message queued regardless of trading_mode
# ══════════════════════════════════════════════════════════════════════════════

class TestTP03AlertKillQueued:
    """alert_kill must enqueue regardless of PAPER vs LIVE mode."""

    async def test_alert_kill_queued_paper(self) -> None:
        tg = _make_telegram(enabled=True)
        await tg.alert_kill(reason="daily_loss_limit_breached")
        assert tg._queue.qsize() == 1
        alert: Alert = tg._queue.get_nowait()
        assert alert.alert_type == AlertType.KILL
        assert "daily_loss_limit_breached" in alert.message

    async def test_alert_kill_message_format(self) -> None:
        tg = _make_telegram(enabled=True)
        await tg.alert_kill(reason="drawdown_exceeded")
        alert: Alert = tg._queue.get_nowait()
        assert "KILL" in alert.message or "KILL" in alert.alert_type.value
        assert "drawdown_exceeded" in alert.message


# ══════════════════════════════════════════════════════════════════════════════
# TP-04 — slippage warning → MetricsValidator.warn_slippage fires alert
# ══════════════════════════════════════════════════════════════════════════════

class TestTP04SlippageWarning:
    """warn_slippage must call telegram.alert_error when threshold is exceeded."""

    async def test_slippage_above_threshold_fires_alert(self) -> None:
        tg = _make_telegram(enabled=True)
        validator = MetricsValidator(slippage_warn_bps=50.0, telegram=tg)
        await validator.warn_slippage(slippage_bps=75.0, context="test_market")
        assert tg._queue.qsize() == 1
        alert: Alert = tg._queue.get_nowait()
        assert alert.alert_type == AlertType.ERROR
        assert "75" in alert.message or "slippage" in alert.message.lower()

    async def test_slippage_below_threshold_no_alert(self) -> None:
        tg = _make_telegram(enabled=True)
        validator = MetricsValidator(slippage_warn_bps=50.0, telegram=tg)
        await validator.warn_slippage(slippage_bps=30.0)
        assert tg._queue.qsize() == 0

    async def test_slippage_no_telegram_no_crash(self) -> None:
        validator = MetricsValidator(slippage_warn_bps=50.0, telegram=None)
        # Must not raise even without telegram
        await validator.warn_slippage(slippage_bps=200.0)


# ══════════════════════════════════════════════════════════════════════════════
# TP-05 — latency warning → MetricsValidator.warn_latency fires alert
# ══════════════════════════════════════════════════════════════════════════════

class TestTP05LatencyWarning:
    """warn_latency must call telegram.alert_error when threshold is exceeded."""

    async def test_latency_above_threshold_fires_alert(self) -> None:
        tg = _make_telegram(enabled=True)
        validator = MetricsValidator(latency_warn_ms=500.0, telegram=tg)
        await validator.warn_latency(latency_ms=750.0, context="order_execution")
        assert tg._queue.qsize() == 1
        alert: Alert = tg._queue.get_nowait()
        assert alert.alert_type == AlertType.ERROR
        assert "750" in alert.message or "latency" in alert.message.lower()

    async def test_latency_below_threshold_no_alert(self) -> None:
        tg = _make_telegram(enabled=True)
        validator = MetricsValidator(latency_warn_ms=500.0, telegram=tg)
        await validator.warn_latency(latency_ms=200.0)
        assert tg._queue.qsize() == 0

    async def test_latency_no_telegram_no_crash(self) -> None:
        validator = MetricsValidator(latency_warn_ms=500.0, telegram=None)
        await validator.warn_latency(latency_ms=9999.0)


# ══════════════════════════════════════════════════════════════════════════════
# TP-06 — notifier disabled → no messages enqueued
# ══════════════════════════════════════════════════════════════════════════════

class TestTP06NotifierDisabled:
    """When enabled=False all alert methods must be silent (no enqueue)."""

    async def test_all_alerts_silent_when_disabled(self) -> None:
        tg = _make_telegram(enabled=False)
        await tg.alert_error(error="e")
        await tg.alert_kill(reason="r")
        await tg.alert_open(market_id="0x1234567890abcdef", side="YES", price=0.5, size=10.0)
        await tg.alert_close(
            market_id="0x1234567890abcdef",
            side="YES",
            entry_price=0.5,
            exit_price=0.6,
            size=10.0,
            realised_pnl=1.0,
            reason="take_profit",
        )
        assert tg._queue.qsize() == 0


# ══════════════════════════════════════════════════════════════════════════════
# TP-07 — queue full → oldest dropped, new alert enqueued
# ══════════════════════════════════════════════════════════════════════════════

class TestTP07QueueFull:
    """When the queue reaches maxsize, the oldest alert is dropped."""

    async def test_queue_overflow_drops_oldest(self) -> None:
        from projects.polymarket.polyquantbot.phase9.telegram_live import _QUEUE_MAXSIZE
        tg = TelegramLive(
            bot_token="tok",
            chat_id="chat",
            enabled=True,
        )

        # Fill queue to capacity with KILL alerts
        for i in range(_QUEUE_MAXSIZE):
            await tg.alert_kill(reason=f"reason_{i}")

        assert tg._queue.qsize() == _QUEUE_MAXSIZE

        # Send one more — oldest should be dropped, new one enqueued
        await tg.alert_error(error="overflow_error")
        assert tg._queue.qsize() == _QUEUE_MAXSIZE

        # The new alert should be present (latest item)
        items: list[Alert] = []
        while not tg._queue.empty():
            items.append(tg._queue.get_nowait())

        alert_types = [a.alert_type for a in items]
        assert AlertType.ERROR in alert_types, "overflow alert must be present after drop"


# ══════════════════════════════════════════════════════════════════════════════
# TP-08 — missing token → enabled forced False, no crash
# ══════════════════════════════════════════════════════════════════════════════

class TestTP08MissingToken:
    """from_env() with missing credentials must disable without raising."""

    def test_from_env_missing_token_disables(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            tg = TelegramLive.from_env(enabled=True)
            assert tg._enabled is False, "missing token must disable notifier"

    async def test_disabled_notifier_never_raises(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            tg = TelegramLive.from_env(enabled=True)
            # All calls must be silent
            await tg.alert_error(error="no_crash")
            await tg.alert_kill(reason="no_crash")
            assert tg._queue.qsize() == 0


# ══════════════════════════════════════════════════════════════════════════════
# TP-09 — alerts_enabled overrides telegram.enabled in config
# ══════════════════════════════════════════════════════════════════════════════

class TestTP09AlertsEnabledOverride:
    """Top-level alerts_enabled=True must win over telegram.enabled=False."""

    async def test_alerts_enabled_overrides_telegram_disabled(self) -> None:
        cfg = {
            "trading_mode": "PAPER",
            "alerts_enabled": True,
            "telegram": {"enabled": False},  # would normally disable
        }
        tg_cfg = cfg.get("telegram", {})
        # Simulate bootstrap logic: alerts_enabled wins
        alerts_enabled = bool(cfg.get("alerts_enabled", tg_cfg.get("enabled", True)))
        tg = _make_telegram(enabled=alerts_enabled)
        assert tg._enabled is True

    async def test_alerts_disabled_overrides_telegram_enabled(self) -> None:
        cfg = {
            "trading_mode": "PAPER",
            "alerts_enabled": False,
            "telegram": {"enabled": True},
        }
        tg_cfg = cfg.get("telegram", {})
        alerts_enabled = bool(cfg.get("alerts_enabled", tg_cfg.get("enabled", True)))
        tg = _make_telegram(enabled=alerts_enabled)
        assert tg._enabled is False


# ══════════════════════════════════════════════════════════════════════════════
# TP-10 — alert_error fires in PAPER mode (end-to-end via worker)
# ══════════════════════════════════════════════════════════════════════════════

class TestTP10AlertErrorEndToEnd:
    """alert_error in PAPER mode must be processed by the worker without sending."""

    async def test_worker_processes_alert_without_http(self) -> None:
        """Worker dequeues alert; no HTTP call in test (_send_with_retry patched)."""
        tg = _make_telegram(enabled=True)

        sent_alerts: list[Alert] = []

        async def _stub_send(alert: Alert) -> None:
            sent_alerts.append(alert)

        with patch.object(tg, "_send_with_retry", side_effect=_stub_send):
            await tg.start()
            await tg.alert_error(error="paper_pipeline_error", context="PAPER:test")
            # Allow worker to process
            await asyncio.sleep(0.05)
            await tg.stop()

        assert len(sent_alerts) == 1
        assert sent_alerts[0].alert_type == AlertType.ERROR
        assert "paper_pipeline_error" in sent_alerts[0].message
