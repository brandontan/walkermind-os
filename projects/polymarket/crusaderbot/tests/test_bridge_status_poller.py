"""Behaviour pins for the #1805 safe, non-crediting Bridge status poller.

Owner decision: "Document precise blocker + safe groundwork." The poller must
observe terminal Bridge COMPLETED pUSD settlements and route them to operator
manual review + an honest web notification, but must NEVER credit tradeable
balance (native USDC/USDT stay disabled for crediting).

Hermetic: no real DB, no network, no Telegram. A fake asyncpg pool/conn drives
the persistence surface; the Bridge adapter and the web-alert writer are
patched.
"""
from __future__ import annotations

import asyncio
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from projects.polymarket.crusaderbot.integrations import polymarket_bridge as bridge
from projects.polymarket.crusaderbot.services.bridge import status_poller

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _run(coro):
    return asyncio.run(coro)


def _completed_pusd_tx(*, tx_hash: str | None = "0xabc", amount: str = "5000000",
                       from_token: str | None = None) -> bridge.BridgeTransaction:
    return bridge.BridgeTransaction(
        from_chain_id=137,
        from_token_address=from_token or bridge.NATIVE_USDC_POLYGON,
        from_amount_base_unit=amount,
        to_chain_id=137,
        to_token_address=bridge.PUSD_POLYGON,
        status="COMPLETED",
        tx_hash=tx_hash,
        created_time_ms=1,
        raw={"fromTokenDecimals": 6, "status": "COMPLETED", "txHash": tx_hash},
    )


class _FakeConn:
    """Minimal asyncpg-conn stand-in. ``_seen`` tracks tx_hashes so a replayed
    settlement reports inserted=False (mirrors ON CONFLICT DO UPDATE). A tx_hash
    in ``_credited`` models an already-credited row: the ON CONFLICT ... WHERE
    credited_deposit_id IS NULL guard skips it, so RETURNING yields no row."""

    def __init__(self, addresses: list[tuple], seen: set, credited: set | None = None):
        self._addresses = addresses
        self._seen = seen
        self._credited = credited or set()

    async def fetch(self, sql: str, *args):
        # _load_bridge_addresses
        return [{"user_id": uid, "evm_address": addr} for uid, addr in self._addresses]

    async def fetchrow(self, sql: str, *args):
        # _record_manual_review: args[8] is tx_hash
        tx_hash = args[8]
        if tx_hash in self._credited:
            # WHERE credited_deposit_id IS NULL skipped the update -> no row.
            return None
        inserted = tx_hash not in self._seen
        self._seen.add(tx_hash)
        return {"inserted": inserted, "credited_deposit_id": None}


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


def _patches(*, enabled: bool, addresses: list[tuple], get_status, captured_alerts,
             seen: set | None = None, credited: set | None = None):
    conn = _FakeConn(addresses, seen if seen is not None else set(), credited)
    pool = _FakePool(conn)

    async def _alert(**kw):
        captured_alerts.append(kw)
        return "alert-id"

    return [
        patch.object(status_poller, "get_settings",
                     lambda: SimpleNamespace(BRIDGE_DEPOSIT_POLLER_ENABLED=enabled)),
        patch.object(status_poller, "get_pool", lambda: pool),
        patch.object(status_poller.bridge, "get_status", get_status),
        patch.object(status_poller, "persist_user_alert_once", _alert),
    ]


# ---------------------------------------------------------------------------
# Dormant by default — no live Bridge call when the flag is off.
# ---------------------------------------------------------------------------

def test_poller_dormant_when_flag_off():
    alerts: list[dict] = []
    get_status = AsyncMock(return_value=(_completed_pusd_tx(),))
    patches = _patches(enabled=False, addresses=[(uuid4(), "0xdead")],
                       get_status=get_status, captured_alerts=alerts)
    for p in patches:
        p.start()
    try:
        result = _run(status_poller.run_once())
    finally:
        for p in patches:
            p.stop()

    assert result == status_poller.PollResult()
    get_status.assert_not_called()
    assert alerts == []


# ---------------------------------------------------------------------------
# COMPLETED pUSD settlement -> manual review + honest notification, NOT credited.
# ---------------------------------------------------------------------------

def test_completed_settlement_manual_review_and_honest_notification():
    alerts: list[dict] = []
    user = uuid4()
    get_status = AsyncMock(return_value=(_completed_pusd_tx(tx_hash="0xc0ffee"),))
    patches = _patches(enabled=True, addresses=[(user, "0xbridge")],
                       get_status=get_status, captured_alerts=alerts)
    for p in patches:
        p.start()
    try:
        result = _run(status_poller.run_once())
    finally:
        for p in patches:
            p.stop()

    assert result.users_polled == 1
    assert result.settlements_seen == 1
    assert result.manual_review_recorded == 1
    assert result.notifications_sent == 1
    assert result.errors == 0
    # Exactly one honest web notification — never claims funds are available.
    assert len(alerts) == 1
    a = alerts[0]
    assert a["alert_kind"] == "bridge_deposit_received"
    assert a["dedup_key"] == "bridge:0xc0ffee:received"
    assert "NOT yet available" in a["body"]
    assert a["metadata"]["disposition"] == "manual_review_not_credited"
    # Display amount is normalized for the copy but is NOT a credit
    # (5_000_000 base units / 10**6 = Decimal("5")).
    assert a["metadata"]["normalized_amount_usdc"] == "5"


# ---------------------------------------------------------------------------
# Idempotent — a replayed settlement does not re-notify.
# ---------------------------------------------------------------------------

def test_replayed_settlement_does_not_double_notify():
    alerts: list[dict] = []
    seen: set = set()
    user = uuid4()
    get_status = AsyncMock(return_value=(_completed_pusd_tx(tx_hash="0xdup"),))

    # First pass records + notifies.
    p1 = _patches(enabled=True, addresses=[(user, "0xb")], get_status=get_status,
                  captured_alerts=alerts, seen=seen)
    for p in p1:
        p.start()
    try:
        r1 = _run(status_poller.run_once())
    finally:
        for p in p1:
            p.stop()

    # Second pass (same shared ``seen``) must be a no-op for notifications.
    p2 = _patches(enabled=True, addresses=[(user, "0xb")], get_status=get_status,
                  captured_alerts=alerts, seen=seen)
    for p in p2:
        p.start()
    try:
        r2 = _run(status_poller.run_once())
    finally:
        for p in p2:
            p.stop()

    assert r1.notifications_sent == 1
    assert r2.manual_review_recorded == 0
    assert r2.notifications_sent == 0
    assert len(alerts) == 1


# ---------------------------------------------------------------------------
# Non-COMPLETED / non-pUSD settlements are ignored; no-tx_hash skipped.
# ---------------------------------------------------------------------------

def test_non_completed_and_non_pusd_ignored():
    alerts: list[dict] = []
    processing = bridge.BridgeTransaction(
        from_chain_id=137, from_token_address=bridge.NATIVE_USDC_POLYGON,
        from_amount_base_unit="1000000", to_chain_id=137,
        to_token_address=bridge.PUSD_POLYGON, status="PROCESSING",
        tx_hash="0x1", created_time_ms=1, raw={},
    )
    completed_non_pusd = bridge.BridgeTransaction(
        from_chain_id=137, from_token_address=bridge.NATIVE_USDC_POLYGON,
        from_amount_base_unit="1000000", to_chain_id=137,
        to_token_address=bridge.USDCE_POLYGON, status="COMPLETED",
        tx_hash="0x2", created_time_ms=1, raw={},
    )
    get_status = AsyncMock(return_value=(processing, completed_non_pusd))
    patches = _patches(enabled=True, addresses=[(uuid4(), "0xb")],
                       get_status=get_status, captured_alerts=alerts)
    for p in patches:
        p.start()
    try:
        result = _run(status_poller.run_once())
    finally:
        for p in patches:
            p.stop()

    assert result.settlements_seen == 0
    assert result.notifications_sent == 0
    assert alerts == []


def test_already_credited_event_not_overwritten_or_notified():
    """If a row was ever credited (credited_deposit_id set), the ON CONFLICT
    guard skips it -> no manual-review overwrite, no notification (Gemini fix)."""
    alerts: list[dict] = []
    get_status = AsyncMock(return_value=(_completed_pusd_tx(tx_hash="0xcredited"),))
    patches = _patches(enabled=True, addresses=[(uuid4(), "0xb")],
                       get_status=get_status, captured_alerts=alerts,
                       credited={"0xcredited"})
    for p in patches:
        p.start()
    try:
        result = _run(status_poller.run_once())
    finally:
        for p in patches:
            p.stop()

    assert result.settlements_seen == 1
    assert result.manual_review_recorded == 0
    assert result.notifications_sent == 0
    assert alerts == []


def test_completed_settlement_without_tx_hash_skipped():
    alerts: list[dict] = []
    get_status = AsyncMock(return_value=(_completed_pusd_tx(tx_hash=None),))
    patches = _patches(enabled=True, addresses=[(uuid4(), "0xb")],
                       get_status=get_status, captured_alerts=alerts)
    for p in patches:
        p.start()
    try:
        result = _run(status_poller.run_once())
    finally:
        for p in patches:
            p.stop()

    assert result.settlements_seen == 1
    assert result.manual_review_recorded == 0
    assert result.notifications_sent == 0
    assert alerts == []


# ---------------------------------------------------------------------------
# Bridge outage fails closed per user — others still processed, never raises.
# ---------------------------------------------------------------------------

def test_bridge_outage_fails_closed_per_user():
    alerts: list[dict] = []
    user_a, user_b = uuid4(), uuid4()

    async def _get_status(address):
        if address == "0xa":
            raise RuntimeError("bridge 503")
        return (_completed_pusd_tx(tx_hash="0xbb"),)

    patches = _patches(enabled=True, addresses=[(user_a, "0xa"), (user_b, "0xb")],
                       get_status=_get_status, captured_alerts=alerts)
    for p in patches:
        p.start()
    try:
        result = _run(status_poller.run_once())
    finally:
        for p in patches:
            p.stop()

    assert result.users_polled == 2
    assert result.errors == 1
    # User B's settlement still recorded + notified despite user A's outage.
    assert result.manual_review_recorded == 1
    assert result.notifications_sent == 1
    assert len(alerts) == 1


# ---------------------------------------------------------------------------
# Hard safety pins — the poller must NEVER credit tradeable balance.
# ---------------------------------------------------------------------------

def test_poller_source_never_credits_or_sweeps():
    """The poller must never touch a crediting/sweep/guard call. Strip the module
    docstring first (it legitimately *names* these terms to explain the blocker);
    the check is against executable code only."""
    raw = (_ROOT / "services/bridge/status_poller.py").read_text(encoding="utf-8")
    # Drop the leading module docstring (between the first pair of triple quotes).
    body = raw.split('"""', 2)[-1]
    for forbidden in (
        "credit_in_conn(", "ledger.credit", "ledger.debit", "debit_in_conn(",
        "INSERT INTO deposits", "INSERT INTO ledger", "get_live_balance(",
        "sweep_usdc_to_master(", "UPDATE wallets",
        "USE_REAL_CLOB", "ENABLE_LIVE_TRADING", "assert_live_guards",
    ):
        assert forbidden not in body, f"poller must not reference {forbidden!r}"
    # No wallet/ledger/custody import either — the module's import surface is
    # config + database + bridge adapter + the web-alert writer only.
    assert "import ledger" not in body
    assert "polygon_usdc" not in body
    # Disposition is explicit and non-crediting.
    assert "MANUAL_REVIEW" in body
    assert "manual_review_not_credited" in body


def test_scheduler_registers_poller_only_under_flag():
    src = (_ROOT / "scheduler.py").read_text(encoding="utf-8")
    assert "BRIDGE_DEPOSIT_POLLER_ENABLED" in src
    assert "bridge_status_poller.run_once" in src
    assert "bridge_deposit_status_poll" in src


def test_poll_interval_is_validated_strictly_positive():
    """APScheduler needs a strictly-positive cadence — config must fail fast on a
    0/negative interval (Gemini fix)."""
    src = (_ROOT / "config.py").read_text(encoding="utf-8")
    assert "BRIDGE_DEPOSIT_POLL_INTERVAL_SECONDS" in src
    # The field is covered by the strictly-positive interval validator.
    validator_block = src.split("def validate_live_reconcile_intervals", 1)[0]
    assert "BRIDGE_DEPOSIT_POLL_INTERVAL_SECONDS" in validator_block.rsplit(
        "@field_validator", 1
    )[-1]


def test_poller_uses_one_connection_per_user():
    """Persist all of a user's settlements under a single pooled connection
    (Gemini fix) — no per-transaction acquire churn."""
    src = (_ROOT / "services/bridge/status_poller.py").read_text(encoding="utf-8")
    body = src.split('"""', 2)[-1]
    # The conflict guard preserves already-credited rows.
    assert "credited_deposit_id IS NULL" in body
    # Settlements are collected then notified after the connection is released.
    assert "to_notify" in body


def test_native_usdc_usdt_remain_disabled_for_crediting():
    """This safe-groundwork lane must NOT flip native USDC/USDT to enabled. The
    enable gate is ``is_fully_enabled`` (all capability flags true), and the
    poller never credits — so the deposit-asset definitions must keep native
    USDC + USDT disabled. Source pin (avoids constructing full Settings)."""
    src = (_ROOT / "wallet/deposit_assets.py").read_text(encoding="utf-8")

    def _block(id_marker: str) -> str:
        start = src.index(id_marker)
        rest = src[start + 1:]
        end = start + 1 + rest.index("DepositAsset(") if "DepositAsset(" in rest else len(src)
        return src[start:end]

    native = _block('id="polygon-usdc-native"')
    usdt = _block('id="polygon-usdt"')
    assert "enabled=False" in native
    assert "creditable=False" in native
    assert "enabled=False" in usdt
    # USDC.e (the only enabled deposit asset) stays enabled + creditable.
    usdce = _block("id=_PRIMARY_DEPOSIT_ASSET_ID")
    assert "enabled=True" in usdce
    assert "creditable=True" in usdce
