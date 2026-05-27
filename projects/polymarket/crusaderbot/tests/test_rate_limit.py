"""Hermetic tests for the inbound HTTP rate limiter (RateLimitMiddleware).

Builds a minimal FastAPI app wrapping the middleware so no DB, cache, or
network is required. Settings are stubbed so the limit is small and fast to
trip. The stub stays active across the requests because FastAPI builds the
middleware stack lazily at app startup.
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from projects.polymarket.crusaderbot.api.rate_limit import RateLimitMiddleware

_SETTINGS_PATH = "projects.polymarket.crusaderbot.api.rate_limit.get_settings"


@contextmanager
def _client(*, rpm: int = 3, window: int = 60, enabled: bool = True):
    fake = SimpleNamespace(
        RATE_LIMIT_ENABLED=enabled,
        RATE_LIMIT_RPM=rpm,
        RATE_LIMIT_WINDOW_SECONDS=window,
    )
    with patch(_SETTINGS_PATH, return_value=fake):
        app = FastAPI()

        @app.get("/ping")
        async def ping() -> dict[str, bool]:
            return {"ok": True}

        @app.get("/health")
        async def health() -> dict[str, bool]:
            return {"ok": True}

        app.add_middleware(RateLimitMiddleware)
        with TestClient(app) as client:
            yield client


def test_allows_requests_under_the_limit():
    with _client(rpm=3) as client:
        headers = {"fly-client-ip": "1.2.3.4"}
        for _ in range(3):
            assert client.get("/ping", headers=headers).status_code == 200


def test_blocks_requests_over_the_limit_with_retry_after():
    with _client(rpm=3) as client:
        headers = {"fly-client-ip": "1.2.3.4"}
        for _ in range(3):
            assert client.get("/ping", headers=headers).status_code == 200

        blocked = client.get("/ping", headers=headers)
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) >= 1
        body = blocked.json()
        assert body["retry_after"] >= 1
        assert "Too many requests" in body["detail"]


def test_limit_is_per_client_ip():
    with _client(rpm=2) as client:
        a = {"fly-client-ip": "10.0.0.1"}
        b = {"fly-client-ip": "10.0.0.2"}
        assert client.get("/ping", headers=a).status_code == 200
        assert client.get("/ping", headers=a).status_code == 200
        assert client.get("/ping", headers=a).status_code == 429  # A exhausted
        # B has its own independent budget.
        assert client.get("/ping", headers=b).status_code == 200
        assert client.get("/ping", headers=b).status_code == 200


def test_health_path_is_exempt():
    with _client(rpm=2) as client:
        headers = {"fly-client-ip": "9.9.9.9"}
        # Far exceed the limit on the exempt path — never throttled.
        for _ in range(10):
            assert client.get("/health", headers=headers).status_code == 200


def test_disabled_flag_is_passthrough():
    with _client(rpm=1, enabled=False) as client:
        headers = {"fly-client-ip": "8.8.8.8"}
        for _ in range(5):
            assert client.get("/ping", headers=headers).status_code == 200


def test_x_forwarded_for_first_hop_is_used_when_no_fly_header():
    with _client(rpm=1) as client:
        # Same first hop, different downstream proxies -> same client bucket.
        h1 = {"x-forwarded-for": "203.0.113.7, 70.0.0.1"}
        h2 = {"x-forwarded-for": "203.0.113.7, 70.0.0.2"}
        assert client.get("/ping", headers=h1).status_code == 200
        assert client.get("/ping", headers=h2).status_code == 429
