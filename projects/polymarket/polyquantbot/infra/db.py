"""Compatibility shim for legacy `infra.db` imports.

Authoritative DB client implementation lives in
`projects.polymarket.polyquantbot.infra.db.database`.
"""
from __future__ import annotations

from projects.polymarket.polyquantbot.infra.db.database import DatabaseClient

__all__ = ["DatabaseClient"]
