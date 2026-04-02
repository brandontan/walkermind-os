"""SA-01–SA-30 — System Activation Final tests.

Validates:
  SA-01–SA-10: New TelegramLive alert methods (startup, ws_connected, ws_error,
               signal, trade, heartbeat)
  SA-11–SA-20: New message_formatter functions
  SA-21–SA-30: SystemActivationMonitor event/signal tracking + assertions
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── SA-01 ─────────────────────────────────────────────────────────────────────

def test_sa01_alert_type_startup_exists():
    """SA-01: AlertType.STARTUP exists in TelegramLive."""
    from projects.polymarket.polyquantbot.telegram.telegram_live import AlertType
    assert AlertType.STARTUP == "STARTUP"


def test_sa02_alert_type_ws_status_exists():
    """SA-02: AlertType.WS_STATUS exists."""
    from projects.polymarket.polyquantbot.telegram.telegram_live import AlertType
    assert AlertType.WS_STATUS == "WS_STATUS"


def test_sa03_alert_type_signal_exists():
    """SA-03: AlertType.SIGNAL exists."""
    from projects.polymarket.polyquantbot.telegram.telegram_live import AlertType
    assert AlertType.SIGNAL == "SIGNAL"


def test_sa04_alert_type_trade_exists():
    """SA-04: AlertType.TRADE exists."""
    from projects.polymarket.polyquantbot.telegram.telegram_live import AlertType
    assert AlertType.TRADE == "TRADE"


def test_sa05_alert_type_heartbeat_exists():
    """SA-05: AlertType.HEARTBEAT exists."""
    from projects.polymarket.polyquantbot.telegram.telegram_live import AlertType
    assert AlertType.HEARTBEAT == "HEARTBEAT"


async def test_sa06_alert_startup_enqueues_when_enabled():
    """SA-06: alert_startup() enqueues a message when Telegram is enabled."""
    from projects.polymarket.polyquantbot.telegram.telegram_live import TelegramLive
    tg = TelegramLive(bot_token="tok", chat_id="123", enabled=True)
    await tg.start()
    await tg.alert_startup(mode="PAPER", market_count=5)
    assert tg._queue.qsize() == 1
    await tg.stop()


async def test_sa07_alert_ws_connected_enqueues():
    """SA-07: alert_ws_connected() enqueues a message."""
    from projects.polymarket.polyquantbot.telegram.telegram_live import TelegramLive
    tg = TelegramLive(bot_token="tok", chat_id="123", enabled=True)
    await tg.start()
    await tg.alert_ws_connected(attempt=1)
    assert tg._queue.qsize() == 1
    await tg.stop()


async def test_sa08_alert_ws_error_enqueues():
    """SA-08: alert_ws_error() enqueues a message."""
    from projects.polymarket.polyquantbot.telegram.telegram_live import TelegramLive
    tg = TelegramLive(bot_token="tok", chat_id="123", enabled=True)
    await tg.start()
    await tg.alert_ws_error(reason="connection refused")
    assert tg._queue.qsize() == 1
    await tg.stop()


async def test_sa09_alert_signal_enqueues():
    """SA-09: alert_signal() enqueues a message."""
    from projects.polymarket.polyquantbot.telegram.telegram_live import TelegramLive
    tg = TelegramLive(bot_token="tok", chat_id="123", enabled=True)
    await tg.start()
    await tg.alert_signal(market_id="0xabc", edge=0.07, size=50.0)
    assert tg._queue.qsize() == 1
    await tg.stop()


async def test_sa10_alert_trade_enqueues():
    """SA-10: alert_trade() enqueues a message."""
    from projects.polymarket.polyquantbot.telegram.telegram_live import TelegramLive
    tg = TelegramLive(bot_token="tok", chat_id="123", enabled=True)
    await tg.start()
    await tg.alert_trade(side="YES", price=0.62, size=50.0)
    assert tg._queue.qsize() == 1
    await tg.stop()


async def test_sa11_alert_heartbeat_enqueues():
    """SA-11: alert_heartbeat() enqueues a message."""
    from projects.polymarket.polyquantbot.telegram.telegram_live import TelegramLive
    tg = TelegramLive(bot_token="tok", chat_id="123", enabled=True)
    await tg.start()
    await tg.alert_heartbeat(ws_connected=True, event_count=10, signal_count=2, trade_count=1)
    assert tg._queue.qsize() == 1
    await tg.stop()


def test_sa12_format_startup_contains_mode():
    """SA-12: format_startup() includes mode and market_count."""
    from projects.polymarket.polyquantbot.telegram.message_formatter import format_startup
    msg = format_startup(mode="PAPER", market_count=3)
    assert "KrusaderBot STARTED" in msg
    assert "PAPER" in msg
    assert "3" in msg


def test_sa13_format_ws_connected_contains_status():
    """SA-13: format_ws_connected() includes 'WS CONNECTED'."""
    from projects.polymarket.polyquantbot.telegram.message_formatter import format_ws_connected
    msg = format_ws_connected(attempt=2)
    assert "WS CONNECTED" in msg
    assert "2" in msg


def test_sa14_format_ws_error_contains_reason():
    """SA-14: format_ws_error() includes reason."""
    from projects.polymarket.polyquantbot.telegram.message_formatter import format_ws_error
    msg = format_ws_error(reason="timeout")
    assert "WS ERROR" in msg
    assert "timeout" in msg


def test_sa15_format_signal_alert_contains_fields():
    """SA-15: format_signal_alert() contains market, edge, size."""
    from projects.polymarket.polyquantbot.telegram.message_formatter import format_signal_alert
    msg = format_signal_alert(market_id="0xabc123", edge=0.07, size=50.0)
    assert "SIGNAL" in msg
    assert "0xabc123" in msg
    assert "0.0700" in msg
    assert "50.00" in msg


def test_sa16_format_trade_alert_contains_fields():
    """SA-16: format_trade_alert() contains side, price, size."""
    from projects.polymarket.polyquantbot.telegram.message_formatter import format_trade_alert
    msg = format_trade_alert(side="YES", price=0.62, size=50.0)
    assert "TRADE" in msg
    assert "YES" in msg
    assert "0.6200" in msg
    assert "50.00" in msg


def test_sa17_format_heartbeat_connected():
    """SA-17: format_heartbeat() shows 'connected' when ws_connected=True."""
    from projects.polymarket.polyquantbot.telegram.message_formatter import format_heartbeat
    msg = format_heartbeat(ws_connected=True, event_count=100, signal_count=5, trade_count=2)
    assert "ALIVE" in msg
    assert "connected" in msg
    assert "100" in msg
    assert "5" in msg
    assert "2" in msg


def test_sa18_format_heartbeat_disconnected():
    """SA-18: format_heartbeat() shows 'disconnected' when ws_connected=False."""
    from projects.polymarket.polyquantbot.telegram.message_formatter import format_heartbeat
    msg = format_heartbeat(ws_connected=False, event_count=0, signal_count=0, trade_count=0)
    assert "disconnected" in msg


async def test_sa19_no_enqueue_when_disabled():
    """SA-19: All new alert methods are no-ops when enabled=False."""
    from projects.polymarket.polyquantbot.telegram.telegram_live import TelegramLive
    tg = TelegramLive(bot_token="tok", chat_id="123", enabled=False)
    await tg.start()
    await tg.alert_startup(mode="PAPER", market_count=1)
    await tg.alert_ws_connected()
    await tg.alert_ws_error(reason="err")
    await tg.alert_signal(market_id="0x1", edge=0.05, size=10.0)
    await tg.alert_trade(side="YES", price=0.5, size=10.0)
    await tg.alert_heartbeat(ws_connected=False, event_count=0, signal_count=0, trade_count=0)
    assert tg._queue.qsize() == 0
    await tg.stop()


def test_sa20_ws_client_stats_has_connection_fields():
    """SA-20: WSClientStats has connected, reconnect_count, last_error fields."""
    from projects.polymarket.polyquantbot.data.websocket.ws_client import WSClientStats
    stats = WSClientStats()
    assert hasattr(stats, "connected")
    assert hasattr(stats, "reconnect_count")
    assert hasattr(stats, "last_error")
    assert stats.connected is False
    assert stats.reconnect_count == 0
    assert stats.last_error == ""


async def test_sa21_system_activation_monitor_starts_stops():
    """SA-21: SystemActivationMonitor starts and stops cleanly."""
    from projects.polymarket.polyquantbot.monitoring.system_activation import SystemActivationMonitor
    monitor = SystemActivationMonitor(log_interval_s=0.05, assert_interval_s=9999)
    await monitor.start()
    assert monitor._running is True
    await monitor.stop()
    assert monitor._running is False


async def test_sa22_record_event_increments():
    """SA-22: record_event() increments event_count."""
    from projects.polymarket.polyquantbot.monitoring.system_activation import SystemActivationMonitor
    monitor = SystemActivationMonitor()
    monitor.record_event()
    monitor.record_event()
    assert monitor.event_count == 2


async def test_sa23_record_signal_increments():
    """SA-23: record_signal() increments signal_count."""
    from projects.polymarket.polyquantbot.monitoring.system_activation import SystemActivationMonitor
    monitor = SystemActivationMonitor()
    monitor.record_signal()
    assert monitor.signal_count == 1


async def test_sa24_record_trade_increments():
    """SA-24: record_trade() increments trade_count."""
    from projects.polymarket.polyquantbot.monitoring.system_activation import SystemActivationMonitor
    monitor = SystemActivationMonitor()
    monitor.record_trade()
    assert monitor.trade_count == 1


async def test_sa25_log_loop_fires_at_interval():
    """SA-25: Log loop fires within a short interval."""
    from projects.polymarket.polyquantbot.monitoring.system_activation import SystemActivationMonitor
    monitor = SystemActivationMonitor(log_interval_s=0.05, assert_interval_s=9999)
    await monitor.start()
    await asyncio.sleep(0.2)
    await monitor.stop()


async def test_sa26_assert_loop_raises_on_no_events():
    """SA-26: Assert loop raises RuntimeError if event_count==0 after interval."""
    from projects.polymarket.polyquantbot.monitoring.system_activation import SystemActivationMonitor
    monitor = SystemActivationMonitor(log_interval_s=9999, assert_interval_s=0.05)
    await monitor.start()
    await asyncio.sleep(0.3)
    # The assert_task should have completed; check it has an exception
    assert monitor._assert_task is not None
    assert monitor._assert_task.done()
    exc = monitor._assert_task.exception()
    assert isinstance(exc, RuntimeError)
    assert "No events received" in str(exc)
    await monitor.stop()


async def test_sa27_assert_loop_warns_on_no_signals():
    """SA-27: Assert loop logs WARNING when events>0 but signals==0."""
    import logging
    from projects.polymarket.polyquantbot.monitoring.system_activation import SystemActivationMonitor
    monitor = SystemActivationMonitor(log_interval_s=9999, assert_interval_s=0.05)
    monitor.event_count = 10  # pre-seed events so no RuntimeError
    await monitor.start()
    await asyncio.sleep(0.3)
    # Task should complete without raising
    assert monitor._assert_task is not None
    assert monitor._assert_task.done()
    # No exception (event_count > 0, just a warning logged)
    assert monitor._assert_task.exception() is None
    await monitor.stop()


async def test_sa28_assert_loop_no_warning_when_signals_exist():
    """SA-28: Assert loop exits cleanly when events>0 and signals>0."""
    from projects.polymarket.polyquantbot.monitoring.system_activation import SystemActivationMonitor
    monitor = SystemActivationMonitor(log_interval_s=9999, assert_interval_s=0.05)
    monitor.event_count = 10
    monitor.signal_count = 3
    await monitor.start()
    await asyncio.sleep(0.3)
    assert monitor._assert_task is not None
    assert monitor._assert_task.done()
    assert monitor._assert_task.exception() is None
    await monitor.stop()


def test_sa29_format_startup_returns_string():
    """SA-29: format_startup() always returns a non-empty string."""
    from projects.polymarket.polyquantbot.telegram.message_formatter import format_startup
    msg = format_startup(mode="LIVE", market_count=0)
    assert isinstance(msg, str)
    assert len(msg) > 0


def test_sa30_format_heartbeat_returns_string():
    """SA-30: format_heartbeat() always returns a non-empty string."""
    from projects.polymarket.polyquantbot.telegram.message_formatter import format_heartbeat
    msg = format_heartbeat(ws_connected=True, event_count=0, signal_count=0, trade_count=0)
    assert isinstance(msg, str)
    assert len(msg) > 0
