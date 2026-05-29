"""WARP•R00T audit Lane 5 — pre-LIVE money-path hardening.

All items are LIVE-gated (EXECUTION_PATH_VALIDATED off in prod) so they do not
touch paper. Covered:
- L1 nonce lock + 'pending' block tag on every master/user on-chain send.
- L2 gas-price ceiling on submit_live_redemption (parity with transfer/sweep).
- L3 signal_scan SELECTs live_capital_cap_usdc (else gate step 15 rejects all
     live trades from the auto-scan path).
- L4a _passes_live_guards also requires USE_REAL_CLOB.
- L4b gate Kelly validation bound aligned to (0, 0.25].

Hermetic: source inspection + a tiny functional check on the guard predicate.
"""
from __future__ import annotations

import inspect
import pathlib
import types

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _src(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


# ── L1: nonce lock helper ─────────────────────────────────────────────────────

def test_nonce_lock_is_per_address_case_insensitive():
    from projects.polymarket.crusaderbot.integrations import polygon
    a1 = polygon.nonce_lock("0xABCdef")
    a2 = polygon.nonce_lock("0xabcDEF")  # same address, different case
    b = polygon.nonce_lock("0x0000000000000000000000000000000000000001")
    assert a1 is a2, "same address must share one lock"
    assert a1 is not b, "distinct addresses must get distinct locks"


def test_all_onchain_sends_use_pending_tag_and_lock():
    usdc = _src("integrations/polygon_usdc.py")
    poly = _src("integrations/polymarket.py")
    # No raw latest-tag nonce reads remain on the send paths.
    assert "get_transaction_count(src_cs)" not in usdc
    assert "get_transaction_count(master_cs)" not in usdc
    assert "get_transaction_count(addr_cs)" not in poly
    # Every send path now uses the pending tag + serializes behind nonce_lock.
    assert 'get_transaction_count(src_cs, "pending")' in usdc
    assert 'get_transaction_count(master_cs, "pending")' in usdc
    assert 'get_transaction_count(addr_cs, "pending")' in poly
    assert usdc.count("nonce_lock(") >= 3 and "nonce_lock(" in poly


# ── L2: redemption gas ceiling ────────────────────────────────────────────────

def test_submit_live_redemption_has_gas_ceiling():
    from projects.polymarket.crusaderbot.integrations import polymarket
    src = inspect.getsource(polymarket.submit_live_redemption)
    assert "INSTANT_REDEEM_GAS_GWEI_MAX" in src
    assert "gas_price_gwei()" in src


# ── L3: signal_scan selects the live cap ──────────────────────────────────────

def test_signal_scan_selects_live_capital_cap():
    src = _src("services/signal_scan/signal_scan_job.py")
    assert "live_capital_cap_usdc" in src
    assert "AS live_capital_cap_usdc" in src, "must be SELECTed so gate step 15 sees the real cap"


# ── L4a: live guards require USE_REAL_CLOB ─────────────────────────────────────

def test_passes_live_guards_requires_use_real_clob():
    from projects.polymarket.crusaderbot.domain.risk import gate

    def _settings(use_real_clob: bool):
        return types.SimpleNamespace(
            ENABLE_LIVE_TRADING=True, EXECUTION_PATH_VALIDATED=True,
            CAPITAL_MODE_CONFIRMED=True, RISK_CONTROLS_VALIDATED=True,
            SECURITY_HARDENING_VALIDATED=True, USE_REAL_CLOB=use_real_clob,
        )
    ctx = types.SimpleNamespace(role="admin", trading_mode="live")
    assert gate._passes_live_guards(ctx, _settings(True)) is True
    assert gate._passes_live_guards(ctx, _settings(False)) is False


# ── L4b: Kelly validation bound ───────────────────────────────────────────────

def test_gate_kelly_bound_is_quarter():
    src = _src("domain/risk/gate.py")
    assert "0 < K.KELLY_FRACTION <= 0.25" in src
    assert "0 < K.KELLY_FRACTION <= 0.5" not in src
