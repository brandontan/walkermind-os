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


# ── R00T finishing-pass pins (PR #1795 CMD hardening items) ──────────────────

_FRONTEND = __import__("pathlib").Path(__file__).resolve().parents[1] / "webtrader" / "frontend" / "src"


def test_watch_deposits_propagates_token_decimals_into_scan():
    """The scanner must decode amounts with the ENABLED asset's decimals, not
    a hardcoded default — pin the kwarg through watch_deposits and the
    explicit is-None fallback in polygon (decimals=0 is a valid ERC-20 value
    and must not silently fall back)."""
    from projects.polymarket.crusaderbot.integrations import polygon
    src = inspect.getsource(scheduler.watch_deposits)
    assert "token_address=deposit_asset.token_contract" in src
    assert "token_decimals=deposit_asset.decimals" in src
    poly_src = inspect.getsource(polygon.scan_usdc_transfers)
    assert "token_decimals is None" in poly_src
    assert "token_decimals or" not in poly_src


def test_confirm_uses_explicit_none_check_for_normalized_amount():
    """Capital path: `normalized or raw` would silently fall back on a
    legitimate zero — pin the explicit None check."""
    src = inspect.getsource(scheduler._confirm_ready_deposits)
    assert "is None" in src
    assert 'd["normalized_amount_usdc"] or' not in src


def test_confirm_credits_zero_normalized_amount_not_raw(monkeypatch):
    """Behavior: a ready row with normalized_amount_usdc=0 must credit 0,
    NOT fall back to the raw token amount."""
    import asyncio
    import uuid as _uuid
    from decimal import Decimal as _D
    from unittest.mock import AsyncMock, patch

    row = {
        "id": _uuid.uuid4(), "user_id": _uuid.uuid4(), "tx_hash": "0xz",
        "amount_usdc": _D("100.0"), "block_number": 10,
        "token_symbol": "USDC.e", "network": "Polygon", "chain_id": 137,
        "normalized_amount_usdc": _D("0"),
    }

    class _Tx:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class _Conn:
        def transaction(self): return _Tx()
        async def fetch(self, sql, *a): return [row]
        async def fetchrow(self, sql, *a):
            if "status='confirmed'" in sql:
                return {"id": row["id"]}
            if "telegram_user_id" in sql:
                return {"telegram_user_id": 1}
            return None

    class _Acq:
        async def __aenter__(self): return _Conn()
        async def __aexit__(self, *a): return False

    class _Pool:
        def acquire(self): return _Acq()

    credit = AsyncMock()
    with patch.object(scheduler, "get_pool", lambda: _Pool()), \
         patch.object(scheduler.ledger, "credit_in_conn", credit), \
         patch.object(scheduler.audit, "write", AsyncMock()):
        asyncio.run(scheduler._confirm_ready_deposits(head=100, depth=32))

    credit.assert_awaited_once()
    assert credit.await_args.args[2] == _D("0"), (
        "zero normalized amount silently fell back to the raw token amount"
    )


def test_record_pending_rejects_mismatched_token_transfer():
    """A transfer whose token_address differs from the enabled asset must
    never be inserted as a deposit (no unsupported-asset crediting)."""
    import asyncio
    import uuid as _uuid
    from types import SimpleNamespace as _NS
    from unittest.mock import patch

    asset = _NS(token_symbol="USDC.e",
                token_contract="0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
                network="Polygon", chain_id=137, decimals=6)
    t = {"tx_hash": "0xbad", "log_index": 0, "amount": 9.0,
         "block_number": 5, "removed": False,
         "token_address": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"}
    with patch.object(scheduler, "primary_deposit_asset", lambda: asset):
        with pytest.raises(ValueError):
            asyncio.run(scheduler._record_pending_deposit(_uuid.uuid4(), t))


def test_migration_099_adds_asset_audit_columns():
    """Migration renumbered 098->099 (098 = ledger.archived on main)."""
    import pathlib
    migrations = pathlib.Path(__file__).resolve().parents[1] / "migrations"
    assert not (migrations / "098_deposit_asset_audit.sql").exists()
    sql = (migrations / "099_deposit_asset_audit.sql").read_text(encoding="utf-8")
    for col in ("token_symbol", "token_address", "network", "chain_id",
                "token_decimals", "normalized_amount_usdc"):
        assert col in sql
    assert "ADD COLUMN IF NOT EXISTS" in sql  # idempotent
    # 098 on main stays the paper-session ledger.archived migration.
    assert (migrations / "098_ledger_archived.sql").exists()


def test_deposit_modal_copy_writes_raw_address_only():
    """COPY contract (CMD blocker 4): wallets/exchanges paste this straight
    into a send form — the button must copy ONLY the raw address, never an
    instruction sentence."""
    src = (_FRONTEND / "components" / "DepositModal.tsx").read_text(encoding="utf-8")
    assert "writeText(selectedAddress)" in src
    assert "ta.value = selectedAddress" in src
    assert "Deposit ${selected.token_label}" not in src, (
        "copy regressed to an instruction sentence instead of the raw address"
    )


def test_deposit_modal_disabled_assets_not_selectable_no_qr():
    """Disabled options: native disabled attr (not keyboard-selectable), no
    QR/address output, and the API attaches no address to them."""
    src = (_FRONTEND / "components" / "DepositModal.tsx").read_text(encoding="utf-8")
    assert "disabled={!option.enabled}" in src
    # Address resolves to "" for a disabled selection -> QR/copy gated off.
    assert 'selected?.enabled ? (selected.deposit_address ?? address) : ""' in src
    assert "option.deposit_address ?? (option.enabled ? address : null)" in src


def test_deposit_modal_uses_token_and_polygon_chain_dropdowns():
    """#1796 selector UX: Polymarket-style token dropdown + Polygon-only
    chain dropdown, not a static token-card list. Disabled tokens remain visible
    as unavailable options but cannot be selected/copyable."""
    src = (_FRONTEND / "components" / "DepositModal.tsx").read_text(encoding="utf-8")
    assert 'aria-label="Deposit token selector"' in src
    assert 'aria-label="Deposit chain selector"' in src
    assert 'const selectableChains = useMemo(() => ["Polygon"], [])' in src
    assert 'option.network === selectedChain && option.chain_id === 137' in src
    assert "disabled={!option.enabled}" in src
    assert "Polygon is the only enabled network scope" in src


def test_deposit_modal_no_static_card_selector_buttons():
    """#1796 regression pin: selector flow must not fall back to the old
    clickable card-list layout for token selection."""
    src = (_FRONTEND / "components" / "DepositModal.tsx").read_text(encoding="utf-8")
    assert 'aria-label="Deposit token and network options"' not in src
    assert "onClick={() => setSelectedId(option.id)}" not in src


def test_deposit_modal_selection_invariant_local_to_selected_chain():
    """R00T hardening (PR #1798): the `selected` fallback must stay within the
    chosen chain's tokenOptions — never fall back to an enabled option on a
    different chain. Pins the chain-local fallback chain."""
    src = (_FRONTEND / "components" / "DepositModal.tsx").read_text(encoding="utf-8")
    assert "tokenOptions.find((option) => option.id === selectedId) ??" in src
    assert "tokenOptions.find((option) => option.enabled) ??" in src
    assert "tokenOptions[0];" in src
    # The old cross-chain fallback (firstEnabled across ALL options) is gone
    # from the `selected` resolution.
    assert "=== selectedId) ?? firstEnabled ?? tokenOptions[0]" not in src


def test_deposit_modal_disabled_token_select_cannot_change_selection():
    """A disabled <option> cannot be chosen, and the onChange guard ignores any
    non-enabled value — so QR/address/copy can never render for a disabled
    token even via programmatic select."""
    src = (_FRONTEND / "components" / "DepositModal.tsx").read_text(encoding="utf-8")
    # onChange only commits an enabled token.
    assert "if (next?.enabled) setSelectedId(next.id);" in src
    # Disabled <option> attribute present on the token dropdown.
    assert "disabled={!option.enabled}" in src
