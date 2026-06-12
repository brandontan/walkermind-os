"""Multi-asset deposit selector safety tests (#1793)."""
from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from projects.polymarket.crusaderbot import scheduler
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


def test_token_and_network_are_separate_in_supported_asset_model():
    asset = deposit_assets.primary_deposit_asset()

    assert asset.token_symbol == "USDC.e"
    assert asset.network == "Polygon"
    assert asset.chain_id == 137
    assert asset.token_symbol != asset.network
    assert asset.token_contract


def test_only_end_to_end_supported_asset_is_selectable():
    options = deposit_assets.supported_deposit_assets()
    enabled = deposit_assets.enabled_deposit_assets()

    assert {asset.id for asset in enabled} == {"polygon-usdc-e"}
    assert all(
        asset.backend_supported
        and asset.watcher_supported
        and asset.bridge_custody_supported
        for asset in enabled
    )
    unavailable = {asset.id: asset for asset in options if not asset.enabled}
    assert "polygon-usdc-native" in unavailable
    assert "polygon-usdt" in unavailable
    assert unavailable["polygon-usdc-native"].watcher_supported is False
    assert unavailable["polygon-usdt"].bridge_custody_supported is False


@pytest.mark.parametrize("asset_id", ["polygon-usdc-native", "polygon-usdt", "base-usdc"])
def test_unsupported_pairs_cannot_be_required_for_deposit_instruction(asset_id: str):
    with pytest.raises(ValueError):
        deposit_assets.require_enabled_deposit_asset(asset_id)


def test_api_options_do_not_attach_address_to_unavailable_assets():
    options = deposit_assets.asset_api_options("0x" + "11" * 20)

    enabled = [option for option in options if option["enabled"]]
    disabled = [option for option in options if not option["enabled"]]
    assert enabled and enabled[0]["deposit_address"] == "0x" + "11" * 20
    assert disabled and all(option["deposit_address"] is None for option in disabled)


def test_scheduler_records_original_asset_and_normalized_credit_truth():
    src = inspect.getsource(scheduler._record_pending_deposit)
    confirm_src = inspect.getsource(scheduler._confirm_ready_deposits)

    assert "token_symbol" in src
    assert "token_address" in src
    assert "network" in src
    assert "chain_id" in src
    assert "normalized_amount_usdc" in src
    assert "normalized_amount_usdc" in confirm_src
    assert "ledger.credit_in_conn" in confirm_src


def test_wrong_token_path_remains_credit_neutral():
    src = inspect.getsource(scheduler._record_wrong_token_deposit)

    assert "wrong_token_deposits" in src
    assert "ledger.credit" not in src
    assert "balance_usdc" not in src
