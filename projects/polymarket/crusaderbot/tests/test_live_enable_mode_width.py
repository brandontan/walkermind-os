"""Regression: /api/web/live/enable column-width truncation (Sentry
DAWN-SNOWFLAKE-1729-33/34).

``live_mode.enable_live_self_serve`` archives paper simulation rows by setting
``positions.mode`` / ``orders.mode`` = ``'paper_archived'`` (14 chars). Both
columns were ``VARCHAR(10)`` from ``001_init`` so the write threw
``StringDataRightTruncationError`` and rolled back the whole live switch.
Migration 097 widens both columns to ``VARCHAR(20)``. These pins fail if the
sentinel grows past the widened width again, or if the widening migration is
removed.
"""
from __future__ import annotations

import re
from pathlib import Path

from projects.polymarket.crusaderbot.domain.activation import live_mode

_MIG = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "097_widen_positions_orders_mode.sql"
)
_WIDENED_LEN = 20


def test_paper_archived_sentinel_overflowed_old_width_and_fits_new():
    # It must exceed the original VARCHAR(10) (that is the bug), and fit the
    # widened VARCHAR(20).
    assert len(live_mode.PAPER_ARCHIVED_MODE) > 10
    assert len(live_mode.PAPER_ARCHIVED_MODE) <= _WIDENED_LEN


def test_migration_097_widens_positions_and_orders_mode():
    sql = _MIG.read_text(encoding="utf-8")
    for table in ("positions", "orders"):
        assert re.search(
            rf"ALTER TABLE {table} ALTER COLUMN mode TYPE VARCHAR\(20\)", sql
        ), f"migration 097 must widen {table}.mode to VARCHAR(20)"
    # Guarded so re-running is harmless (catalog-only, idempotent).
    assert "character_maximum_length < 20" in sql
