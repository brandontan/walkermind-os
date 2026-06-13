"""Behaviour pins for #1819 — withdrawal-request-debited-but-not-received-blocker.

Owner production evidence: WebTrader shows a `-$9.00` withdrawal-request debit to
`0x5E5b93e4...` but the funds never arrived at the destination wallet. R00T
verdict: the capital-safety architecture is sound (atomic debit + balance lock +
overdraft guard + idempotent on-chain submit + PreflightError-refund + dedup),
but the user has no honest signal that the withdrawal is QUEUED — the only web
notification fires on ``status='completed'``, which can never happen when
``EXECUTION_PATH_VALIDATED=False`` makes ``_attempt_onchain_transfer`` a silent
no-op.

This file pins the fix:

1. ``create_withdrawal_request`` emits a deduped ``withdrawal_requested`` web
   alert at request time. The dedup key uses the withdrawal id so a replay can
   never double-notify, and the body honestly explains the funds are reserved
   and not yet sent.
2. The confirmed-only alert (``withdrawal_confirmed``) is unchanged — it must
   stay gated behind status='completed' (no regression of the #1808 invariant).
3. ``find_stuck_withdrawals`` exposes pending/approved/processing rows with NO
   tx_hash that are older than N hours — the operator visibility the issue
   demands. It is READ-ONLY (no ledger/wallets mutation, no on-chain call).
4. ``/wallet/ledger`` joins ``withdrawals`` so the activity feed can render an
   accurate lifecycle badge — the LedgerEntry schema carries
   ``withdrawal_status`` + ``withdrawal_tx_hash`` for type='withdraw' rows.
5. The frontend WalletPage maps the raw status to a user-honest badge
   (``Queued`` when approved-without-tx_hash, etc.) — the exact case the
   owner hit.

Hermetic: no DB, no broker, no network. Inspection + a small async harness
patches the pool and notification writer.
"""
from __future__ import annotations

import asyncio
import inspect
import pathlib
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from projects.polymarket.crusaderbot.wallet import withdrawals
from projects.polymarket.crusaderbot.webtrader.backend import schemas

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. Request-time web alert: source inspection.
# ---------------------------------------------------------------------------

def test_request_time_web_alert_fires_with_pending_copy() -> None:
    """create_withdrawal_request must emit a deduped 'withdrawal_requested' alert
    so the user is told funds are reserved (NOT sent) immediately at request
    time. The previous gap left the user with only the 'withdrawal_confirmed'
    alert, which never fires when EXECUTION_PATH_VALIDATED=False makes the
    on-chain submit a silent no-op."""
    src = inspect.getsource(withdrawals.create_withdrawal_request)
    assert 'alert_kind="withdrawal_requested"' in src
    assert 'dedup_key=f"withdrawal:{row[\'id\']}:requested"' in src
    # Honest copy must explicitly distinguish reserve from send.
    assert "reserved" in src
    assert "pending review" in src
    # Idempotent against retries: persist_user_alert_once is the writer.
    assert "persist_user_alert_once" in src


def test_confirmed_alert_still_gated_on_completion_only() -> None:
    """#1808 invariant must not regress: the 'withdrawal_confirmed' alert only
    fires once the on-chain receipt has been observed (status='completed' +
    tx_hash set + persisted in the RETURNING clause)."""
    src = inspect.getsource(withdrawals._attempt_onchain_transfer)
    assert 'alert_kind="withdrawal_confirmed"' in src
    assert 'dedup_key=f"withdrawal:{completed[\'id\']}:completed"' in src
    assert "status = 'completed'" in src
    # The confirmed alert remains the ONLY one inside _attempt_onchain_transfer
    # (count the call site, not the import).
    assert src.count("await persist_user_alert_once(") == 1


def test_two_distinct_dedup_namespaces_for_requested_and_confirmed() -> None:
    """The 'requested' and 'confirmed' alerts use distinct dedup namespaces
    (...:requested vs ...:completed) so the partial-unique index on
    (user_id, alert_kind, dedup_key) can let BOTH fire for the same
    withdrawal id without collision. Source-pin the two distinct strings."""
    req_src = inspect.getsource(withdrawals.create_withdrawal_request)
    cmp_src = inspect.getsource(withdrawals._attempt_onchain_transfer)
    # The dedup-key strings themselves (in f-string form) live ONLY in the
    # function that owns the alert — comments and docstrings explaining the
    # split mention both terms in either source, so pin the f-string forms.
    req_key = 'dedup_key=f"withdrawal:{row[\'id\']}:requested"'
    cmp_key = 'dedup_key=f"withdrawal:{completed[\'id\']}:completed"'
    assert req_key in req_src
    assert cmp_key in cmp_src
    assert req_key not in cmp_src
    assert cmp_key not in req_src


# ---------------------------------------------------------------------------
# 2. Request-time web alert: end-to-end behaviour (hermetic).
# ---------------------------------------------------------------------------

class _Tx:
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False


class _Conn:
    """Minimal asyncpg-conn stand-in for create_withdrawal_request."""

    def __init__(self, *, balance: Decimal = Decimal("100"),
                 withdrawal_id: UUID | None = None,
                 user_id: UUID | None = None) -> None:
        self._balance = balance
        self._wid = withdrawal_id or uuid4()
        self._uid = user_id or uuid4()
        self.debit_called: list[dict] = []

    async def fetchval(self, sql: str, *args):
        if "balance_usdc FROM wallets" in sql:
            return self._balance
        if "value FROM system_settings" in sql:
            return None  # falls through to default 'manual'
        return None

    async def fetchrow(self, sql: str, *args):
        if "INSERT INTO withdrawals" in sql:
            return {
                "id": self._wid,
                "user_id": self._uid,
                "amount_usdc": args[1],
                "destination_address": args[2],
                "status": args[3],
                "approval_mode": args[4],
                "lifecycle_state": args[5],
            }
        if "SELECT value FROM system_settings" in sql:
            return None
        return None

    async def execute(self, sql: str, *args) -> str:
        return "OK"

    def transaction(self) -> _Tx:
        return _Tx()


class _Acq:
    def __init__(self, conn: _Conn): self._c = conn
    async def __aenter__(self): return self._c
    async def __aexit__(self, *exc): return False


class _Pool:
    def __init__(self, conn: _Conn): self._c = conn
    def acquire(self) -> _Acq: return _Acq(self._c)


def _patches(conn: _Conn, captured_alerts: list[dict], *, mode: str = "manual"):
    async def _alert(**kw):
        captured_alerts.append(kw)
        return "alert-id"

    async def _mode_lookup():
        return mode

    pool = _Pool(conn)
    return [
        patch.object(withdrawals, "get_pool", lambda: pool),
        patch.object(withdrawals, "get_approval_mode", _mode_lookup),
        # debit_in_conn is patched so we don't need a real ledger table.
        patch.object(withdrawals, "debit_in_conn", AsyncMock()),
        # persist_user_alert_once lives in a different module — patch where it
        # is *imported* (inside create_withdrawal_request's late import).
        patch(
            "projects.polymarket.crusaderbot.webtrader.backend."
            "notification_prefs.persist_user_alert_once",
            new=_alert,
        ),
    ]


def test_create_withdrawal_emits_pending_alert_in_manual_mode() -> None:
    """Manual-approval mode: the row stays at status='pending' and the
    pending-state alert fires exactly once with honest copy."""
    captured: list[dict] = []
    user = uuid4()
    wid = uuid4()
    conn = _Conn(balance=Decimal("100"), withdrawal_id=wid, user_id=user)
    patches = _patches(conn, captured, mode="manual")
    for p in patches:
        p.start()
    try:
        result = _run(withdrawals.create_withdrawal_request(
            user_id=user,
            amount_usdc=Decimal("9.00"),
            destination_address="0x5E5b93e400000000000000000000000000000000",
        ))
    finally:
        for p in patches:
            p.stop()

    assert result["status"] == "pending"
    assert len(captured) == 1
    a = captured[0]
    assert a["alert_kind"] == "withdrawal_requested"
    assert a["dedup_key"] == f"withdrawal:{wid}:requested"
    # Honest copy: clearly distinguishes reserve from send.
    assert "$9.00" in a["body"]
    assert "reserved" in a["body"]
    # Surfaces enough context for an audit trail.
    assert a["metadata"]["withdrawal_id"] == str(wid)
    assert a["metadata"]["amount_usdc"] == 9.0
    assert a["metadata"]["destination_address"].startswith("0x5E5b93e4")


def test_create_withdrawal_alert_failure_does_not_undo_debit() -> None:
    """Defense-in-depth: a failure to write the pending alert must NEVER
    revert the committed ledger debit. The alert path is wrapped in a try/
    except and logs a warning. ``debit_in_conn`` was already awaited inside
    the committed transaction by the time the alert is attempted."""
    captured: list[dict] = []
    conn = _Conn(balance=Decimal("100"))

    pool = _Pool(conn)

    async def _raising_alert(**kw):
        raise RuntimeError("alert writer offline")

    async def _mode_lookup():
        return "manual"

    debit_mock = AsyncMock()
    patches = [
        patch.object(withdrawals, "get_pool", lambda: pool),
        patch.object(withdrawals, "get_approval_mode", _mode_lookup),
        patch.object(withdrawals, "debit_in_conn", debit_mock),
        patch(
            "projects.polymarket.crusaderbot.webtrader.backend."
            "notification_prefs.persist_user_alert_once",
            new=_raising_alert,
        ),
    ]
    for p in patches:
        p.start()
    try:
        result = _run(withdrawals.create_withdrawal_request(
            user_id=uuid4(),
            amount_usdc=Decimal("9.00"),
            destination_address="0xdead000000000000000000000000000000000000",
        ))
    finally:
        for p in patches:
            p.stop()

    # The withdrawal still resolved + the ledger debit was attempted before
    # the alert raised: capital safety beats notification fidelity.
    assert result["status"] == "pending"
    debit_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# 3. find_stuck_withdrawals: operator visibility.
# ---------------------------------------------------------------------------

def test_find_stuck_withdrawals_scopes_to_unsent_rows() -> None:
    """The query must surface ONLY rows that are still in a non-terminal state
    (pending/approved/processing), have NO tx_hash, and are older than the
    requested window. ``completed`` / ``failed`` / ``rejected`` rows must
    never appear in the operator queue."""
    src = inspect.getsource(withdrawals.find_stuck_withdrawals)
    # Scope: non-terminal statuses, no tx_hash, age filter.
    assert "IN ('pending', 'approved', 'processing')" in src
    assert "tx_hash IS NULL" in src
    assert "make_interval(hours =>" in src
    # Read-only: no UPDATE / INSERT / DELETE.
    body = src.split('"""', 2)[-1]
    for verb in ("UPDATE ", "INSERT ", "DELETE ", "DROP ", "ALTER ", "TRUNCATE "):
        assert verb not in body
    # Returns ordered oldest-first so the operator can triage by age.
    assert "ORDER BY w.created_at ASC" in src


def test_find_stuck_withdrawals_executes_select_only(capsys) -> None:
    """Behaviour: a hermetic invocation runs exactly one SELECT and never
    mutates the DB."""
    captured_sql: list[str] = []

    class _RecordingConn:
        async def fetch(self, sql: str, *args):
            captured_sql.append(sql)
            return []

    class _RecordingPool:
        def acquire(self):
            class _Ctx:
                async def __aenter__(self_inner): return _RecordingConn()
                async def __aexit__(self_inner, *exc): return False
            return _Ctx()

    with patch.object(withdrawals, "get_pool", lambda: _RecordingPool()):
        rows = _run(withdrawals.find_stuck_withdrawals(older_than_hours=12))

    assert rows == []
    assert len(captured_sql) == 1
    sql = captured_sql[0]
    assert sql.strip().upper().startswith("SELECT") or sql.lstrip().startswith("SELECT") \
        or "SELECT" in sql.split("\n")[1]


# ---------------------------------------------------------------------------
# 4. /wallet/ledger JOINs withdrawals + schema surfaces the badge fields.
# ---------------------------------------------------------------------------

def test_wallet_ledger_endpoint_joins_withdrawals_table() -> None:
    """The activity feed query must LEFT JOIN withdrawals on l.ref_id so a
    'withdraw' ledger row carries its lifecycle status to the UI. Without this
    the frontend can only show a bare debit line — the exact opacity that hid
    the owner's queued withdrawal."""
    router_src = (_ROOT / "webtrader/backend/router.py").read_text(encoding="utf-8")
    # Pin the JOIN shape and the two new selected columns.
    assert "LEFT JOIN withdrawals" in router_src
    assert "ON l.type = 'withdraw' AND l.ref_id = w.id" in router_src
    assert "w.status AS withdrawal_status" in router_src
    assert "w.tx_hash AS withdrawal_tx_hash" in router_src


def test_get_wallet_initial_ledger_recent_also_joins_withdrawals() -> None:
    """Codex P2 #1821: WalletPage.load() refreshes the activity feed from
    ``api.getWallet().ledger_recent`` (the /wallet endpoint), NOT the
    paginated /wallet/ledger. If only the paginated endpoint carries the
    JOIN, the first 20 rows — including the just-created queued withdrawal —
    render as bare debits until the user scrolls. Mirror the JOIN in /wallet
    so the badge is honest from the first paint."""
    router_src = (_ROOT / "webtrader/backend/router.py").read_text(encoding="utf-8")
    # Take only the get_wallet() function body so we don't false-pass on the
    # paginated /wallet/ledger endpoint that already has the JOIN.
    start = router_src.index("@router.get(\"/wallet\", response_model=WalletInfo)")
    end = router_src.index("@router.get(\"/wallet/ledger\"", start)
    body = router_src[start:end]
    assert "LEFT JOIN withdrawals" in body
    assert "ON l.type = 'withdraw' AND l.ref_id = w.id" in body
    assert "w.status AS withdrawal_status" in body
    assert "withdrawal_status=r[\"withdrawal_status\"]" in body
    assert "withdrawal_tx_hash=r[\"withdrawal_tx_hash\"]" in body


def test_ledger_entry_schema_carries_withdrawal_badge_fields() -> None:
    fields = schemas.LedgerEntry.model_fields
    assert "withdrawal_status" in fields
    assert "withdrawal_tx_hash" in fields
    # Both optional so existing non-withdrawal rows remain unchanged on the wire.
    assert fields["withdrawal_status"].is_required() is False
    assert fields["withdrawal_tx_hash"].is_required() is False


def test_frontend_wallet_renders_honest_badge_for_queued_withdrawal() -> None:
    """When ``withdrawals.status == 'approved'`` and ``tx_hash`` is NULL (the
    owner's case: EXECUTION_PATH_VALIDATED=False so the on-chain submit was a
    silent no-op), the WalletPage must render 'Queued' — NOT 'Sending' or
    'Confirmed'. Pin the mapping function so a future refactor cannot quietly
    drop the queued-state honesty."""
    src = (_ROOT / "webtrader/frontend/src/pages/WalletPage.tsx").read_text(
        encoding="utf-8",
    )
    assert "withdrawalBadge" in src
    # The honest mapping rows the owner case depends on.
    assert '"pending"' in src
    assert '"approved"' in src
    assert "Queued" in src
    assert "Sending" in src
    assert "Confirmed" in src
    assert "Failed (manual review)" in src
    assert "Rejected (refunded)" in src


# ---------------------------------------------------------------------------
# 5. Architectural invariants the lane preserved (regression guard).
# ---------------------------------------------------------------------------

def test_ledger_debit_remains_atomic_with_withdrawal_insert() -> None:
    """Capital safety invariant: the ledger debit must remain inside the same
    DB transaction as the INSERT INTO withdrawals row. If either fails the
    user's balance is unchanged. Pin the structural shape."""
    src = inspect.getsource(withdrawals.create_withdrawal_request)
    # The transaction wrapper is present and the debit is awaited inside it.
    assert "async with conn.transaction()" in src
    assert "INSERT INTO withdrawals" in src
    assert "debit_in_conn(" in src
    # The pending alert is emitted AFTER the transaction commits — never inside
    # it (an alert outage must never roll back the debit).
    insert_idx = src.index("INSERT INTO withdrawals")
    alert_idx = src.index('alert_kind="withdrawal_requested"')
    assert alert_idx > insert_idx


def test_requested_alert_fires_before_auto_settlement() -> None:
    """Codex P2 #1821: in 'auto' approval mode the inline ``_settle_withdrawal``
    call can complete the withdrawal in-process (status='completed' +
    'withdrawal_confirmed' alert). Firing 'withdrawal_requested' AFTER that
    would deliver a "pending review" notification AFTER a terminal confirmed
    one — a wrong-order lifecycle narrative. Pin the ordering: the requested
    alert site must appear BEFORE the ``_settle_withdrawal`` call site so the
    user always sees requested → confirmed/failed/refunded in lifecycle order.
    """
    src = inspect.getsource(withdrawals.create_withdrawal_request)
    alert_idx = src.index('alert_kind="withdrawal_requested"')
    settle_idx = src.index("_settle_withdrawal(row[\"id\"]")
    assert alert_idx < settle_idx, (
        "withdrawal_requested alert must fire BEFORE _settle_withdrawal so "
        "the lifecycle order requested -> confirmed/failed is preserved"
    )


def test_requested_alert_uses_asyncpg_record_safe_metadata_lookup() -> None:
    """Gemini HIGH #1821: ``row`` is an ``asyncpg.Record`` at runtime, which
    does NOT implement ``.get()``. Calling ``row.get('lifecycle_state')``
    would AttributeError, be swallowed by the outer try/except, and silently
    kill the entire pending-state alert in production. Use ``key in row`` +
    ``row[key]`` which both dict and asyncpg.Record support."""
    src = inspect.getsource(withdrawals.create_withdrawal_request)
    # The dangerous Record-incompatible pattern is gone.
    assert 'row.get("lifecycle_state")' not in src
    # The safe Record-compatible pattern is in.
    assert '"lifecycle_state" in row' in src
    assert 'row["lifecycle_state"]' in src


def test_preflight_failure_still_refunds_ledger() -> None:
    """#1819 lane MUST NOT regress the preflight-refund pathway: a transfer
    that fails BEFORE broadcast still credits the ledger back so the user is
    made whole automatically. Source-pin the refund branch."""
    src = inspect.getsource(withdrawals._settle_withdrawal)
    assert "PreflightError" in src
    assert "credit_in_conn" in src
    assert "T_ADJUSTMENT" in src
    assert "tx_hash IS NULL" in src


def test_overdraft_guard_remains_in_request() -> None:
    """Multi-user safety: the request must still FOR-UPDATE-lock the wallet
    row + reject when the balance can't cover the amount."""
    src = inspect.getsource(withdrawals.create_withdrawal_request)
    assert "FOR UPDATE" in src
    assert "Insufficient balance" in src
