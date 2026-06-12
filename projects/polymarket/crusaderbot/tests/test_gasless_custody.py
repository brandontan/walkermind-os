"""Gasless custody cutover lane (WARP/root-gasless-custody) — owner-authorized
2026-06-12 (AskUserQuestion: "Build gasless custody lane").

Pins:
1. Relayer credential aliasing — the operator's POLYMARKET_BUILDER_* Fly
   secrets populate the relayer's POLY_BUILDER_* fields (one Builder
   Program credential set, two consumers).
2. Custody-aware deposit address — safe mode surfaces the user's Polymarket
   Safe (the gasless sweep/payout wallet); EOA mode is byte-unchanged; an
   unbackfilled safe falls back to the EOA, never blank.
3. The admin Backfill button also populates wallets.safe_address (pure local
   CREATE2 — no network, no funds).
4. Boot validation logs the custody posture and flags CUSTODY_MODE='safe'
   without a configured relayer as a problem.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from projects.polymarket.crusaderbot.config import Settings
from projects.polymarket.crusaderbot.main import _validate_live_execution_readiness
from projects.polymarket.crusaderbot.wallet import custody

_ROOT = Path(__file__).parents[1]

_BASE_ENV = dict(
    TELEGRAM_BOT_TOKEN="tok",
    OPERATOR_CHAT_ID="1",
    DATABASE_URL="postgresql://x",
    WALLET_HD_SEED="seed",
    WALLET_ENCRYPTION_KEY="k",
    POLYGON_RPC_URL="https://rpc",
)


# ── 1. relayer credential aliasing ───────────────────────────────────────────


def test_polymarket_builder_secrets_populate_relayer_fields(monkeypatch):
    for k, v in _BASE_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("POLYMARKET_BUILDER_API_KEY", "bk-key")
    monkeypatch.setenv("POLYMARKET_BUILDER_API_SECRET", "bk-secret")
    monkeypatch.setenv("POLYMARKET_BUILDER_PASSPHRASE", "bk-pass")
    s = Settings()
    assert s.POLY_BUILDER_API_KEY == "bk-key"
    assert s.POLY_BUILDER_SECRET == "bk-secret"
    assert s.POLY_BUILDER_PASSPHRASE == "bk-pass"


def test_alias_chain_covers_short_secret_spelling(monkeypatch):
    # POLYMARKET_BUILDER_SECRET → _API_SECRET (existing alias) → POLY_BUILDER_SECRET
    for k, v in _BASE_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("POLYMARKET_BUILDER_API_KEY", "bk-key")
    monkeypatch.setenv("POLYMARKET_BUILDER_SECRET", "bk-secret-short")
    monkeypatch.setenv("POLYMARKET_BUILDER_PASSPHRASE", "bk-pass")
    s = Settings()
    assert s.POLY_BUILDER_SECRET == "bk-secret-short"


def test_canonical_relayer_fields_win_over_alias(monkeypatch):
    for k, v in _BASE_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("POLYMARKET_BUILDER_API_KEY", "from-alias")
    monkeypatch.setenv("POLY_BUILDER_API_KEY", "canonical")
    s = Settings()
    assert s.POLY_BUILDER_API_KEY == "canonical"


# ── 2. custody-aware deposit address ─────────────────────────────────────────


def _row(eoa="0x" + "aa" * 20, safe=None):
    return {"deposit_address": eoa, "safe_address": safe}


def test_eoa_mode_shows_eoa(monkeypatch):
    monkeypatch.setattr(
        custody, "get_settings", lambda: SimpleNamespace(CUSTODY_MODE="eoa"),
    )
    assert custody.effective_deposit_address(_row(safe="0x" + "bb" * 20)) \
        == "0x" + "aa" * 20


def test_safe_mode_shows_safe(monkeypatch):
    monkeypatch.setattr(
        custody, "get_settings", lambda: SimpleNamespace(CUSTODY_MODE="safe"),
    )
    assert custody.effective_deposit_address(_row(safe="0x" + "bb" * 20)) \
        == "0x" + "bb" * 20


def test_safe_mode_unbackfilled_falls_back_to_eoa(monkeypatch):
    monkeypatch.setattr(
        custody, "get_settings", lambda: SimpleNamespace(CUSTODY_MODE="safe"),
    )
    assert custody.effective_deposit_address(_row(safe=None)) == "0x" + "aa" * 20


def test_missing_row_renders_placeholder(monkeypatch):
    monkeypatch.setattr(
        custody, "get_settings", lambda: SimpleNamespace(CUSTODY_MODE="safe"),
    )
    assert custody.effective_deposit_address(None) == "(not set)"


def test_wallet_surfaces_use_the_helper():
    """Both user-facing deposit-address surfaces must route through the
    custody-aware helper — a raw deposit_address read on either would tell
    safe-mode users to deposit to the wrong wallet."""
    tg = (_ROOT / "bot" / "handlers" / "wallet.py").read_text(encoding="utf-8")
    assert tg.count("effective_deposit_address(w)") == 3
    assert 'w["deposit_address"] if w else' not in tg
    web = (_ROOT / "webtrader" / "backend" / "router.py").read_text(encoding="utf-8")
    assert "deposit_address=effective_deposit_address(w_row)" in web


# ── 3. admin backfill also fills safe addresses ──────────────────────────────


def test_admin_backfill_runs_safe_backfill_too():
    src = (_ROOT / "webtrader" / "backend" / "router.py").read_text(encoding="utf-8")
    assert "backfill_safe_addresses" in src
    assert '"safes": safes' in src


# ── 4. boot validation custody posture ───────────────────────────────────────


class _FakeConn:
    async def fetchval(self, *a):
        return 0


class _FakePool:
    def acquire(self):
        conn = _FakeConn()

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


def _boot_settings(**overrides):
    base = dict(
        USE_RUST_SIDECAR=False,
        RUST_SIDECAR_PATH="",
        USE_PER_USER_EXECUTION=False,
        ENABLE_LIVE_TRADING=False,
        AUTO_REDEEM_ENABLED=False,
        CUSTODY_MODE="eoa",
        SWEEP_ONCHAIN_ENABLED=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_safe_mode_without_relayer_is_a_boot_problem():
    from projects.polymarket.crusaderbot.integrations import builder_relayer
    with patch.object(builder_relayer, "is_relayer_configured", return_value=False):
        problems = asyncio.run(_validate_live_execution_readiness(
            _boot_settings(CUSTODY_MODE="safe"), _FakePool(),
        ))
    assert any("CUSTODY_MODE='safe'" in p for p in problems)


def test_eoa_mode_reports_no_custody_problem():
    from projects.polymarket.crusaderbot.integrations import builder_relayer
    with patch.object(builder_relayer, "is_relayer_configured", return_value=False):
        problems = asyncio.run(_validate_live_execution_readiness(
            _boot_settings(), _FakePool(),
        ))
    assert problems == []


def test_safe_mode_with_relayer_is_clean():
    from projects.polymarket.crusaderbot.integrations import builder_relayer
    with patch.object(builder_relayer, "is_relayer_configured", return_value=True), \
         patch.object(builder_relayer, "make_relayer_client",
                      side_effect=RuntimeError("no sdk in test")):
        problems = asyncio.run(_validate_live_execution_readiness(
            _boot_settings(CUSTODY_MODE="safe"), _FakePool(),
        ))
    # master-safe derive failure is evidence-only — never a problem/blocker
    assert problems == []
