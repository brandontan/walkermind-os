"""Typed exceptions for the Polymarket CLOB adapter.

Keeping these narrow lets callers (router, smoke test, future Phase 4B
live-execution wiring) classify failures correctly without string-matching.
"""
from __future__ import annotations


class ClobError(Exception):
    """Base error for every CLOB adapter failure mode."""


class ClobConfigError(ClobError):
    """Raised when the adapter cannot be constructed because required
    credentials are missing. Surfaced by ``get_clob_client`` only when
    ``USE_REAL_CLOB=True`` — never for the paper-safe default branch.
    """


class ClobAuthError(ClobError):
    """Raised when the CLOB rejects an L1 or L2 signature, or when local
    signing inputs are malformed (e.g. unparseable private key).

    Distinct from ``ClobAPIError`` so callers can distinguish credential
    rotation issues from broker-side rejections.
    """


class ClobAPIError(ClobError):
    """Raised on non-2xx HTTP responses from the CLOB REST API.

    Carries the HTTP status, response body excerpt, and the request path
    so log lines and alerts can route on broker-class vs adapter-class
    errors without re-fetching.
    """

    def __init__(
        self,
        status_code: int,
        path: str,
        body: str,
        message: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.path = path
        self.body = body
        super().__init__(message or f"CLOB {status_code} on {path}: {body[:200]}")
