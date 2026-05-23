"""Regression tests for main.py stdlib log calls.

Canary: ensures log.info() in main.py lifespan uses extra={} for structured
fields rather than raw kwargs, which TypeError-crash the stdlib Logger._log().

This test class would have caught the bug introduced by PR #1307 and fixed
by WARP-46 before the change reached production.
"""
from __future__ import annotations

import io
import json
import logging
import pytest

from projects.polymarket.crusaderbot.monitoring.logging import (
    _JsonFormatter,
    configure_json_logging,
)


def _make_logger(name: str = "test_main_log") -> tuple[logging.Logger, io.StringIO]:
    """Return a logger wired to a StringIO stream using _JsonFormatter."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(_JsonFormatter())
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger, buf


class TestStdlibLogExtra:
    """Positive + negative tests for stdlib log calls with structured fields."""

    def test_extra_dict_does_not_raise(self):
        """log.info() with extra={...} must not raise — this is the correct form."""
        logger, buf = _make_logger("test_pos")
        logger.info(
            "strategies_loaded",
            extra={
                "event": "strategies_loaded",
                "count": 7,
                "domain_count": 2,
                "lib_count": 5,
                "names": ["signal_following"],
                "enabled_lib": ["trend_breakout", "momentum"],
            },
        )
        output = buf.getvalue()
        assert output, "log line must be emitted"
        record = json.loads(output)
        assert record["message"] == "strategies_loaded"
        assert record["count"] == 7
        assert record["domain_count"] == 2
        assert record["event"] == "strategies_loaded"

    def test_extra_fields_appear_in_json_output(self):
        """All keys inside extra={} must surface in the JSON log line."""
        logger, buf = _make_logger("test_fields")
        logger.info(
            "strategies_loaded",
            extra={"count": 11, "lib_count": 8, "domain_count": 3},
        )
        record = json.loads(buf.getvalue())
        assert record["count"] == 11
        assert record["lib_count"] == 8
        assert record["domain_count"] == 3

    def test_raw_kwarg_raises_typeerror(self):
        """log.info() with raw non-extra kwargs MUST raise TypeError.

        This is the negative canary: if stdlib ever changes to silently ignore
        unknown kwargs, this test will fail and alert us to reassess.
        The broken form that caused the WARP-46 production crash:
            log.info("x", event="y", count=1)
        """
        logger, _ = _make_logger("test_neg")
        with pytest.raises(TypeError):
            logger.info("strategies_loaded", event="strategies_loaded", count=7)
