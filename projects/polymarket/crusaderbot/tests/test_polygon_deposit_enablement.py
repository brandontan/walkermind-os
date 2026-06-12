"""Polygon native-USDC / USDT deposit enablement audit (#1800).

Verdict (code truth): neither native Polygon USDC nor Polygon USDT can be
safely enabled end-to-end in this lane — the custody sweep
(polygon_usdc.sweep_usdc_to_master) is hard-bound to settings.USDC_POLYGON
(USDC.e) and no USDC/USDT -> USDC.e conversion path exists, so they cannot
become tradeable live balance. Both stay disabled with an explicit reason; the
capability matrix makes that auditable. These tests pin: no fake-enablement, no
QR/address/credit/sweep for disabled tokens, USDC.e intact, audit truth, and
the user-facing modal no longer renders the capability-card list.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from projects.polymarket.crusaderbot.wallet import deposit_assets


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    fake = SimpleNamespace(
        USDC_POLYGON="0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
        USDC_NATIVE_POLYGON="0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
        USDC_DECIMALS=6,
        MIN_DEPOSIT_USDC=50.0,
    )
    monkeypatch.setattr(deposit_assets, "get_settings", lambda: fake)


def _by_id():
    return {a.id: a for a in deposit_assets.supported_deposit_assets()}


# ── capability matrix is honest ──────────────────────────────────────────────

def test_only_usdce_is_enabled_end_to_end():
    enabled = {a.id for a in deposit_assets.enabled_deposit_assets()}
    assert enabled == {"polygon-usdc-e"}


def test_usdce_full_capability_matrix():
    a = _by_id()["polygon-usdc-e"]
    assert a.enabled and a.detectable and a.creditable and a.sweepable and a.reconcilable


def test_native_usdc_detect_only_never_creditable_or_sweepable():
    a = _by_id()["polygon-usdc-native"]
    assert a.enabled is False
    assert a.detectable is True          # wrong-token alert lane can see it
    assert a.creditable is False         # not Polymarket collateral
    assert a.sweepable is False          # sweep is USDC.e-contract-bound
    assert a.reconcilable is False
    assert a.convertible is False        # no USDC -> USDC.e conversion
    assert a.disabled_reason and "conversion" in a.disabled_reason.lower()


def test_usdt_fully_disabled_with_conversion_blocker():
    a = _by_id()["polygon-usdt"]
    assert a.enabled is False
    assert not any((a.detectable, a.creditable, a.sweepable, a.reconcilable, a.convertible))
    assert a.disabled_reason and "usdt" in a.disabled_reason.lower()
    assert a.unavailable_reason and "conversion" in a.unavailable_reason.lower()


def test_enabled_requires_full_matrix_not_just_enabled_flag():
    """A future stray enabled=True without the capabilities cannot fake-enable:
    enabled_deposit_assets requires detectable+creditable+sweepable+reconcilable."""
    src = inspect.getsource(deposit_assets.enabled_deposit_assets)
    for cap in ("detectable", "creditable", "sweepable", "reconcilable"):
        assert f"asset.{cap}" in src


# ── disabled tokens cannot credit / sweep / render an address ────────────────

def test_require_enabled_rejects_native_usdc_and_usdt():
    for asset_id in ("polygon-usdc-native", "polygon-usdt"):
        with pytest.raises(ValueError):
            deposit_assets.require_enabled_deposit_asset(asset_id)


def test_primary_asset_is_usdce_only():
    assert deposit_assets.primary_deposit_asset().id == "polygon-usdc-e"
    assert deposit_assets.primary_deposit_asset().token_symbol == "USDC.e"


def test_api_options_attach_address_only_to_enabled():
    opts = deposit_assets.asset_api_options("0x" + "11" * 20)
    for o in opts:
        if o["enabled"]:
            assert o["deposit_address"] == "0x" + "11" * 20
        else:
            assert o["deposit_address"] is None  # no QR/address for disabled


def test_api_options_expose_capability_matrix_and_reason():
    opts = {o["id"]: o for o in deposit_assets.asset_api_options("0x" + "11" * 20)}
    nat = opts["polygon-usdc-native"]
    for cap in ("detectable", "creditable", "sweepable", "reconcilable", "convertible"):
        assert cap in nat
    assert nat["disabled_reason"]
    assert nat["unavailable_reason"]  # both reason fields kept in sync


# ── audit truth: original token/network/amount preserved, sweep USDC.e-bound ─

def test_sweep_path_is_usdce_contract_bound():
    """The custody sweep only ever transfers settings.USDC_POLYGON (USDC.e) —
    proving native USDC / USDT cannot be swept by it (the enablement blocker)."""
    from projects.polymarket.crusaderbot.integrations import polygon_usdc
    src = inspect.getsource(polygon_usdc.sweep_usdc_to_master)
    assert "settings.USDC_POLYGON" in src
    # there is no per-token-address parameter on the sweep
    assert "token_address" not in inspect.signature(
        polygon_usdc.sweep_usdc_to_master
    ).parameters


def test_reorg_revert_debits_normalized_amount_not_raw():
    from projects.polymarket.crusaderbot import scheduler
    src = inspect.getsource(scheduler._revert_deposit)
    # explicit is-None fallback -> debits the normalized credited amount.
    assert "normalized_amount_usdc" in src
    assert 'dep["amount_usdc"] if normalized is None else normalized' in src
    assert "debit_in_conn" in src


def test_deposit_records_preserve_original_asset_audit_fields():
    from projects.polymarket.crusaderbot import scheduler
    src = inspect.getsource(scheduler._record_pending_deposit)
    for field in ("token_symbol", "token_address", "network", "chain_id",
                  "token_decimals", "normalized_amount_usdc"):
        assert field in src


# ── frontend (CMD scope update): no capability-card list ─────────────────────

_MODAL = (
    Path(deposit_assets.__file__).resolve().parents[1]
    / "webtrader" / "frontend" / "src" / "components" / "DepositModal.tsx"
)


def test_modal_removed_capability_card_list():
    src = _MODAL.read_text(encoding="utf-8")
    # the stacked per-token capability cards are gone
    assert 'aria-label="Polygon token support status"' not in src
    assert "SUPPORTED" not in src or "Supported" in src  # no all-caps card badge loop
    # replaced by a compact selected-token status
    assert 'aria-label="Selected token status"' in src


def test_modal_keeps_dropdowns_qr_and_raw_copy():
    src = _MODAL.read_text(encoding="utf-8")
    assert 'aria-label="Deposit token selector"' in src
    assert 'aria-label="Deposit chain selector"' in src
    assert "QRCodeSVG" in src
    # COPY contract: raw address only (preserved from #1795/#1798).
    assert "writeText(selectedAddress)" in src
    assert "Deposit ${selected.token_label}" not in src


def test_modal_disabled_token_gates_off_qr_address_copy():
    src = _MODAL.read_text(encoding="utf-8")
    # selectedAddress is "" for a disabled selection -> QR/address/copy branch off.
    assert 'selected?.enabled ? (selected.deposit_address ?? address) : ""' in src
    assert "selectorDisabled" in src
    # concise selected-token warnings kept.
    assert "Send only" in src


# ── invariant: $5 LIVE Auto-Trade gate unchanged ────────────────────────────

def test_five_dollar_live_gate_unchanged():
    from projects.polymarket.crusaderbot.domain.activation import live_mode
    assert live_mode.MIN_LIVE_AUTOTRADE_BALANCE_USDC == 5
