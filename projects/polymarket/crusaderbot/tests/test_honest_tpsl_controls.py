"""WARP-83 Sub-Lane E.2 (Path C) — honest TP/SL controls.

Pins the UX-deception fix: the strategy entry path sources TP/SL from
``user_settings.tp_pct / sl_pct`` (single source of truth) instead of a
hardcoded / per-rule / per-profile bundle, with a logged defensive fallback to
the Balanced strategy default (150% / 50%) when the column is NULL.

Also pins the entry-time-only / non-retroactive guarantee of migration 089:
the backfill SQL touches ``user_settings`` only and never ``positions``.

These are pure-unit tests over ``_build_trade_signal`` and the migration files —
no DB, no network.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.domain.strategy.types import SignalCandidate
from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as ssj


_MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[1] / "migrations"
)
_MIGRATION_089 = _MIGRATIONS_DIR / "089_backfill_user_settings_tpsl.sql"
_ROLLBACK_089 = (
    _MIGRATIONS_DIR / "rollback" / "089_backfill_user_settings_tpsl_rollback.sql"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cand(metadata: dict | None = None) -> SignalCandidate:
    return SignalCandidate(
        market_id="MKT",
        condition_id="MKT",
        side="YES",
        confidence=0.6,
        suggested_size_usdc=5.0,
        strategy_name="late_entry_v3",
        signal_ts=datetime.now(timezone.utc),
        metadata=metadata if metadata is not None else {},
    )


def _row(*, tp_pct, sl_pct) -> dict:
    """A minimal-but-complete scan-loop row for _build_trade_signal."""
    return {
        "user_id": uuid4(),
        "telegram_user_id": 12345,
        "role": "user",
        "auto_trade_on": True,
        "paused": False,
        "resolved_profile": "balanced",
        "trading_mode": "paper",
        "tp_pct": tp_pct,
        "sl_pct": sl_pct,
        "daily_loss_override": None,
        "min_liquidity_threshold": 0.0,
        "max_drawdown_pct": None,
        "active_preset": "candle_auto",
        "max_concurrent_override": None,
        "balance_usdc": 100.0,
    }


def _market() -> dict:
    return {
        "question": "Will it?",
        "yes_token_id": "yt",
        "no_token_id": "nt",
        "status": "active",
        "liquidity_usdc": 1000.0,
    }


def _build(monkeypatch, *, tp_pct, sl_pct, metadata=None):
    # Neutralise the bankroll multiplier (it reads config/DB) — fail-safe is 1.0
    # in production anyway; pin it here for a deterministic unit test.
    monkeypatch.setattr(ssj, "_bankroll_multiplier", lambda *a, **k: 1.0)
    return ssj._build_trade_signal(
        row=_row(tp_pct=tp_pct, sl_pct=sl_pct),
        cand=_cand(metadata),
        market=_market(),
        idempotency_key="idem-1",
        live_price_override=0.42,
    )


# ---------------------------------------------------------------------------
# Strategy reads user_settings literally
# ---------------------------------------------------------------------------

def test_strategy_reads_user_settings_tpsl_literally(monkeypatch):
    sig = _build(monkeypatch, tp_pct=0.20, sl_pct=0.10)
    # The user's UI config (0.20 / 0.10) must be applied LITERALLY — not the
    # hardcoded 1.5 / 0.5, not a per-profile bundle.
    assert sig.tp_pct == pytest.approx(0.20)
    assert sig.sl_pct == pytest.approx(0.10)


def test_balanced_default_passthrough(monkeypatch):
    # A user backfilled by migration 089 to the strategy default sees 150/50.
    sig = _build(monkeypatch, tp_pct=1.5, sl_pct=0.5)
    assert sig.tp_pct == pytest.approx(1.5)
    assert sig.sl_pct == pytest.approx(0.5)


def test_candle_auto_metadata_does_not_override_user_settings(monkeypatch):
    # Even if stale per-rule TP/SL keys somehow appear in candidate metadata,
    # the builder no longer honours them — user_settings wins.
    sig = _build(
        monkeypatch,
        tp_pct=0.20,
        sl_pct=0.10,
        metadata={"applied_tp_pct": 1.5, "applied_sl_pct": 0.5},
    )
    assert sig.tp_pct == pytest.approx(0.20)
    assert sig.sl_pct == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# Defensive fallback when user_settings is NULL/missing
# ---------------------------------------------------------------------------

def test_defensive_fallback_when_tpsl_null(monkeypatch):
    sig = _build(monkeypatch, tp_pct=None, sl_pct=None)
    # WARP-85: the fallback now resolves from the active strategy's
    # default_tp_sl() hook; late_entry_v3 returns the Balanced baseline, equal to
    # the last-resort guard, so the value is byte-identical (150% / 50%).
    assert sig.tp_pct == pytest.approx(ssj._LAST_RESORT_TP_PCT)
    assert sig.sl_pct == pytest.approx(ssj._LAST_RESORT_SL_PCT)
    # Pin the signed-off default values explicitly (150% / 50%).
    assert sig.tp_pct == pytest.approx(1.5)
    assert sig.sl_pct == pytest.approx(0.5)


def test_defensive_fallback_partial_null(monkeypatch):
    # tp present, sl NULL → tp honoured literally, sl falls back.
    sig = _build(monkeypatch, tp_pct=0.30, sl_pct=None)
    assert sig.tp_pct == pytest.approx(0.30)
    assert sig.sl_pct == pytest.approx(ssj._LAST_RESORT_SL_PCT)


def test_per_rule_tpsl_helper_removed():
    # The per-rule TP/SL bundle helper must be gone (Path C rejects bundles).
    assert not hasattr(ssj, "_candle_auto_rule_tpsl")


# ---------------------------------------------------------------------------
# Migration 089 — idempotent + rollback-safe + non-retroactive
# ---------------------------------------------------------------------------

def test_migration_089_exists_and_rollback_exists():
    assert _MIGRATION_089.is_file(), f"missing {_MIGRATION_089}"
    assert _ROLLBACK_089.is_file(), f"missing {_ROLLBACK_089}"


def test_migration_089_backfills_user_settings_to_strategy_default():
    sql = _MIGRATION_089.read_text(encoding="utf-8")
    low = sql.lower()
    assert "update user_settings" in low
    assert "tp_pct = 1.5" in low
    assert "sl_pct = 0.5" in low


def test_migration_089_is_idempotent_shaped():
    # Idempotent shape: a guarded UPDATE that converges (no-op once values match).
    sql = _MIGRATION_089.read_text(encoding="utf-8").lower()
    assert "where" in sql
    assert "is distinct from" in sql


def _strip_sql_comments(sql: str) -> str:
    """Drop ``-- ...`` line comments so assertions test only executable SQL."""
    return "\n".join(
        line.split("--", 1)[0] for line in sql.splitlines()
    ).lower()


def test_migration_089_never_touches_positions():
    # Entry-time-only guarantee: the backfill must NOT alter any positions row
    # (applied_tp_pct / applied_sl_pct are immutable entry snapshots). Assert
    # against the executable SQL only (comments may discuss positions).
    body = _strip_sql_comments(_MIGRATION_089.read_text(encoding="utf-8"))
    assert not re.search(r"\b(update|delete|insert|alter|drop)\b[^;]*\bpositions\b", body)
    assert "applied_tp_pct" not in body
    assert "applied_sl_pct" not in body
    # The only table written is user_settings.
    assert "update user_settings" in body


def test_rollback_089_never_touches_positions():
    body = _strip_sql_comments(_ROLLBACK_089.read_text(encoding="utf-8"))
    assert "user_settings" in body
    assert not re.search(r"\b(update|delete|insert|alter|drop)\b[^;]*\bpositions\b", body)
