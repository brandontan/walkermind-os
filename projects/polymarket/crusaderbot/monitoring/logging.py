"""Structured (JSON) logging baseline for HTTP requests + errors.

Scope (per task spec): HTTP request lifecycle and error events only.
Trading and execution paths are intentionally NOT instrumented from here.

Usage from ``main.py``::

    from .monitoring.logging import configure_json_logging, RequestLogMiddleware

    configure_json_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
    app.add_middleware(RequestLogMiddleware)
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


_RESERVED_LOGRECORD_KEYS = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "asctime", "taskName",
    }
)


class _JsonFormatter(logging.Formatter):
    """Minimal JSON formatter for the stdlib ``logging`` root logger.

    Any ``extra={...}`` fields passed into the log call are merged into the
    top-level JSON object, which keeps request-log lines flat and queryable.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOGRECORD_KEYS or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            exc_type = record.exc_info[0]
            payload["exc_type"] = exc_type.__name__ if exc_type else None
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_json_logging(level: str = "INFO") -> None:
    """Replace stdlib + structlog renderers with JSON output."""
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_JsonFormatter())

    root = logging.getLogger()
    # Remove any handlers attached by basicConfig() during early imports.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level.upper())

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO),
        ),
        cache_logger_on_first_use=True,
    )


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Log one structured line per HTTP request.

    Fields: method, path, status_code, duration_ms.
    Errors raised by the app are logged at ERROR with ``exc_type`` and re-raised.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        log = logging.getLogger("crusaderbot.http")
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 — re-raised after logging
            duration_ms = (time.perf_counter() - start) * 1000.0
            log.error(
                "request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": round(duration_ms, 2),
                    "exc_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
        duration_ms = (time.perf_counter() - start) * 1000.0
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return response
