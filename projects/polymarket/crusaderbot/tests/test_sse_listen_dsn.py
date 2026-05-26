"""Regression tests for SSE listener DSN normalisation.

The SSE LISTEN/NOTIFY listener must never rewrite a Supabase pooler URL to
the direct endpoint (db.<ref>.supabase.co:5432) — that host refuses IPv4
connections on the free tier (Errno 111) and the listener reconnect-loops
forever, killing webtrader real-time updates. It must instead use the
session pooler (port 5432 on the pooler host), which supports LISTEN.
"""
from __future__ import annotations

from urllib.parse import urlparse

from projects.polymarket.crusaderbot.webtrader.backend.sse import (
    _normalize_dsn_for_listen,
)


def test_session_pooler_used_as_is() -> None:
    dsn = "postgresql://postgres.abcd1234:pw@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
    out = urlparse(_normalize_dsn_for_listen(dsn))
    assert out.hostname == "aws-0-us-east-1.pooler.supabase.com"
    assert out.port == 5432


def test_transaction_pooler_switched_to_session_port() -> None:
    dsn = "postgresql://postgres.abcd1234:pw@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    out = urlparse(_normalize_dsn_for_listen(dsn))
    # stays on the pooler host, switches to session-mode port
    assert out.hostname == "aws-0-us-east-1.pooler.supabase.com"
    assert out.port == 5432


def test_pooler_never_rewritten_to_direct_host() -> None:
    for port in (5432, 6543):
        dsn = f"postgresql://postgres.abcd1234:pw@aws-0-us-east-1.pooler.supabase.com:{port}/postgres"
        out = urlparse(_normalize_dsn_for_listen(dsn))
        assert "db.abcd1234.supabase.co" != out.hostname
        assert "pooler.supabase.com" in (out.hostname or "")


def test_non_supabase_6543_normalised_to_5432() -> None:
    dsn = "postgresql://user:pw@db.internal.example.com:6543/postgres"
    out = urlparse(_normalize_dsn_for_listen(dsn))
    assert out.port == 5432
    assert out.hostname == "db.internal.example.com"


def test_plain_direct_dsn_unchanged() -> None:
    dsn = "postgresql://user:pw@db.internal.example.com:5432/postgres"
    out = urlparse(_normalize_dsn_for_listen(dsn))
    assert out.port == 5432
    assert out.hostname == "db.internal.example.com"
