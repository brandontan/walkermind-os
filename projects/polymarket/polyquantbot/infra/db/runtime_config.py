"""Database runtime configuration helpers for canonical DSN handling."""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import ParseResult, parse_qsl, urlencode, urlparse, urlunparse


@dataclass(frozen=True)
class DatabaseRuntimeConfig:
    dsn: str
    host: str
    port: int
    database: str
    user: str
    source: str


def load_database_runtime_config() -> DatabaseRuntimeConfig:
    """Load canonical DB DSN from env.

    Canonical source is DATABASE_URL. DB_DSN is accepted only as compatibility
    fallback when DATABASE_URL is absent.
    """
    raw_database_url = os.getenv("DATABASE_URL", "").strip()
    raw_db_dsn = os.getenv("DB_DSN", "").strip()

    source = "DATABASE_URL"
    raw_dsn = raw_database_url
    if not raw_dsn:
        if not raw_db_dsn:
            raise ValueError("Missing required DATABASE_URL environment variable")
        source = "DB_DSN_COMPAT"
        raw_dsn = raw_db_dsn

    return parse_database_runtime_dsn(raw_dsn=raw_dsn, source=source)


def parse_database_runtime_dsn(*, raw_dsn: str, source: str) -> DatabaseRuntimeConfig:
    parsed = urlparse(raw_dsn)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must use postgres/postgresql scheme")

    host = (parsed.hostname or "").strip()
    port = int(parsed.port or 5432)
    database = parsed.path.lstrip("/").strip()
    user = (parsed.username or "").strip()

    missing: list[str] = []
    if not host:
        missing.append("DB host")
    if not database:
        missing.append("DB name")
    if not user:
        missing.append("DB user")
    if missing:
        raise ValueError("Invalid DATABASE_URL; missing " + ", ".join(missing))
    if port <= 0 or port > 65535:
        raise ValueError("DB port must be between 1 and 65535")

    normalized_dsn = _normalize_sslmode(raw_dsn=raw_dsn, parsed=parsed, host=host)

    return DatabaseRuntimeConfig(
        dsn=normalized_dsn,
        host=host,
        port=port,
        database=database,
        user=user,
        source=source,
    )


def _normalize_sslmode(*, raw_dsn: str, parsed: ParseResult, host: str) -> str:
    parsed_dsn = parsed
    query_pairs = parse_qsl(parsed_dsn.query, keep_blank_values=True)
    query_map = {key: value for key, value in query_pairs}

    if _is_local_host(host):
        return raw_dsn

    sslmode = (query_map.get("sslmode") or "").strip().lower()
    if not sslmode:
        query_map["sslmode"] = "require"
    elif sslmode != "require":
        raise ValueError("DATABASE_URL must set sslmode=require for non-local DB hosts")

    normalized_query = urlencode(query_map)
    return urlunparse(parsed_dsn._replace(query=normalized_query))


def _is_local_host(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in {"localhost", "127.0.0.1", "::1"}
