"""Typed exceptions for the Polymarket CLOB adapter.

Phase 4E widens the hierarchy so callers (router, lifecycle, live engine,
preflight, ops dashboard) can route on retry / no-retry / auth / rate
limit / circuit-open without string-matching status codes.

Hierarchy:

    ClobError
      ClobConfigError                missing creds at boot (paper-safe never raised)
      ClobAPIError                   non-2xx HTTP response (carries status/path/body)
        ClobAuthError                400 / 401 / 403 -- never retry
        ClobRateLimitError           429              -- retry with backoff
        ClobServerError              500/502/503/504  -- retry with backoff
      ClobTimeoutError               transport timeout -- retry
      ClobNetworkError               transport failure -- retry
      ClobMaxRetriesError            retries exhausted on retryable class
      ClobCircuitOpenError           breaker OPEN -- request rejected with no broker call

``ClobAuthError`` keeps a single positional ``message`` arg so the
existing ``auth.py`` call sites (``ClobAuthError("EIP-712 sign failed")``)
do not need to change. When raised from the HTTP path the keyword fields
(``status_code`` / ``path`` / ``body``) are populated, matching the
``ClobAPIError`` contract via subclass inheritance.
"""
from __future__ import annotations

from typing import Optional


class ClobError(Exception):
    """Base error for every CLOB adapter failure mode."""


class ClobConfigError(ClobError):
    """Raised when the adapter cannot be constructed because required
    credentials are missing. Surfaced by ``get_clob_client`` only when
    ``USE_REAL_CLOB=True`` -- never for the paper-safe default branch.
    """


class ClobAPIError(ClobError):
    """Raised on non-2xx HTTP responses from the CLOB REST API.

    Carries the HTTP status, response body excerpt, and the request path
    so log lines and alerts can route on broker-class vs adapter-class
    errors without re-fetching.
    """

    def __init__(
        self,
        *,
        status_code: int,
        path: str,
        body: str,
        message: Optional[str] = None,
    ) -> None:
        self.status_code = int(status_code)
        self.path = path
        self.body = body
        super().__init__(
            message or f"CLOB {status_code} on {path}: {(body or '')[:200]}"
        )


class ClobAuthError(ClobAPIError):
    """4xx auth-class rejection -- 400 / 401 / 403. Never retried.

    Also raised for local signing failures (malformed private key,
    EIP-712 encoding errors). In that case ``status_code`` is 0 and
    ``path`` / ``body`` are empty -- the synthetic HTTP frame keeps the
    type uniform without forcing call sites to branch.
    """

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        status_code: int = 0,
        path: str = "",
        body: str = "",
    ) -> None:
        super().__init__(
            status_code=status_code,
            path=path,
            body=body,
            message=message,
        )


class ClobRateLimitError(ClobAPIError):
    """HTTP 429 -- broker-side rate limit. Retried with backoff."""


class ClobServerError(ClobAPIError):
    """HTTP 500 / 502 / 503 / 504 -- broker-side transient. Retried with backoff."""


class ClobTimeoutError(ClobError):
    """Transport-layer timeout (httpx.TimeoutException). Retried with backoff."""


class ClobNetworkError(ClobError):
    """Transport-layer network failure (DNS, connection reset, etc.). Retried."""


class ClobMaxRetriesError(ClobError):
    """All retry attempts exhausted on a retryable error class.

    ``last_exception`` carries the final retryable exception so callers
    can still log the broker status / network detail without re-parsing
    the message string.
    """

    def __init__(
        self,
        message: str,
        *,
        last_exception: Optional[BaseException] = None,
    ) -> None:
        self.last_exception = last_exception
        super().__init__(message)


class ClobCircuitOpenError(ClobError):
    """Circuit breaker is OPEN -- the request was rejected without any
    broker call. Operator must wait for the auto half-open window or
    flip the breaker manually.
    """
