"""WARP-77 Phase 1.2 — real-CLOB-data feed heartbeat tests.

Covers staleness detection (warming-up vs down), the dormancy guard (no page while
USE_PYSDK_CLOB is off — proves it cannot page in current prod), and the latched
once-per-transition page+Sentry on down/recovery. Hermetic — injected page/capture
callables; no network, no Telegram, no Sentry.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from projects.polymarket.crusaderbot.monitoring import clob_heartbeat as hb


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset():
    hb._reset_for_test()
    yield
    hb._reset_for_test()


# ── staleness primitives ──────────────────────────────────────────────────
def test_age_none_until_first_read():
    assert hb.clob_feed_age_sec(now=1000.0) is None
    assert hb.clob_feed_down(180, now=1000.0) is False  # warming up, never down


def test_age_and_down_threshold():
    hb.mark_clob_read_ok(1000.0)
    assert hb.clob_feed_age_sec(now=1050.0) == 50.0
    assert hb.clob_feed_down(180, now=1100.0) is False   # age 100 <= 180
    assert hb.clob_feed_down(180, now=1200.0) is True    # age 200 > 180


# ── dormancy: USE_PYSDK_CLOB off → never pages even when very stale ────────
def test_dormant_when_pysdk_off():
    calls: list[str] = []
    caps: list[str] = []

    async def page(t):
        calls.append(t)

    def cap(m):
        caps.append(m)

    hb.mark_clob_read_ok(1000.0)
    s = SimpleNamespace(USE_PYSDK_CLOB=False, CLOB_DATA_FEED_TIMEOUT_SEC=180)
    down = _run(
        hb.check_clob_feed_and_alert(settings=s, now=99999.0, page_fn=page, capture_fn=cap)
    )
    assert down is False
    assert calls == [] and caps == []  # cannot page on the legacy adapter


# ── armed: latched once-per-transition page + Sentry ──────────────────────
def test_down_then_recovery_pages_once_each():
    calls: list[str] = []
    caps: list[str] = []

    async def page(t):
        calls.append(t)

    def cap(m):
        caps.append(m)

    s = SimpleNamespace(USE_PYSDK_CLOB=True, CLOB_DATA_FEED_TIMEOUT_SEC=180)
    hb.mark_clob_read_ok(1000.0)

    # First stale check → DOWN: one page + one Sentry capture.
    assert _run(hb.check_clob_feed_and_alert(settings=s, now=1300.0, page_fn=page, capture_fn=cap)) is True
    assert len(calls) == 1 and len(caps) == 1
    assert "lost" in calls[0].lower()

    # Still stale → latched: no additional page.
    assert _run(hb.check_clob_feed_and_alert(settings=s, now=1400.0, page_fn=page, capture_fn=cap)) is True
    assert len(calls) == 1 and len(caps) == 1

    # Fresh read → recovery: exactly one more page (restored), no extra Sentry.
    hb.mark_clob_read_ok(1500.0)
    assert _run(hb.check_clob_feed_and_alert(settings=s, now=1510.0, page_fn=page, capture_fn=cap)) is False
    assert len(calls) == 2 and len(caps) == 1
    assert "restored" in calls[1].lower()


def test_failsoft_on_bad_settings():
    # A settings object whose attribute access raises must not escalate → False.
    class _Boom:
        def __getattr__(self, name):
            raise RuntimeError(f"config blew up reading {name}")

    assert _run(hb.check_clob_feed_and_alert(settings=_Boom(), now=1.0)) is False
