"""Withdrawal request management.

    Requests are recorded and ledger-debited on submission — that debit is the
    available-balance lock. Paper/default mode stops at the approved/pending row;
    guarded live mode submits on-chain and tracks confirmation.
No on-chain transfer until EXECUTION_PATH_VALIDATED guard is activated.

Approval modes (system_settings key 'withdrawal_approval_mode'):
  'manual' — admin must explicitly approve/reject each request
  'auto'   — auto-approved on submission (ledger already debited at request time)

On-chain transfer lifecycle:
  create_withdrawal_request() → DB row + ledger debit (always); in 'auto'
                                approval mode it also fires settlement inline
  approve_withdrawal()        → DB row 'approved' → _settle_withdrawal()
  _settle_withdrawal()        → runs the transfer; on PreflightError refunds
                                the ledger (no capital moved); on a
                                post-broadcast error marks 'failed' (reconcile)
  _attempt_onchain_transfer() → no-op when EXECUTION_PATH_VALIDATED=False;
                                live USDC transfer + status settlement when True
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional
from uuid import UUID

from ..database import get_pool
from ..wallet import ledger
from ..wallet.ledger import T_WITHDRAW, debit_in_conn

logger = logging.getLogger(__name__)

MIN_WITHDRAWAL_USDC = Decimal("5")


async def get_approval_mode() -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM system_settings WHERE key = 'withdrawal_approval_mode'"
        )
    return (row["value"] if row else "manual")


async def set_approval_mode(mode: str) -> None:
    if mode not in ("auto", "manual"):
        raise ValueError(f"Invalid approval mode: {mode!r}")
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO system_settings (key, value) VALUES ($1, $2) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            "withdrawal_approval_mode", mode,
        )


async def create_withdrawal_request(
    user_id: UUID,
    amount_usdc: Decimal,
    destination_address: str,
) -> dict:
    """Submit a withdrawal request and immediately debit the ledger.

    The debit is atomic with the withdrawal row insert — if either fails
    the transaction rolls back and the user's balance is unchanged.

    Overdraft guard (multi-user money-safety invariant): the wallet row is
    locked ``FOR UPDATE`` and the request is refused with ValueError if the
    balance can't cover it. This is the single chokepoint both surfaces
    (WebTrader API + Telegram bot) route through, so no caller — present or
    future — can drive ``balance_usdc`` negative and spend the pooled custody
    funds of other users. The row lock serializes concurrent requests so two
    in-flight withdrawals cannot both pass the check and double-spend.
    """
    mode = await get_approval_mode()
    initial_status = "approved" if mode == "auto" else "pending"

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            balance = await conn.fetchval(
                "SELECT balance_usdc FROM wallets WHERE user_id = $1 FOR UPDATE",
                user_id,
            )
            if balance is None:
                raise ValueError("Wallet not found")
            if Decimal(str(balance)) < amount_usdc:
                raise ValueError(
                    f"Insufficient balance: have ${Decimal(str(balance)):.2f}, "
                    f"requested ${amount_usdc:.2f}"
                )
            row = await conn.fetchrow(
                """
                INSERT INTO withdrawals (user_id, amount_usdc, destination_address,
                                         status, approval_mode, lifecycle_state)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING *
                """,
                user_id, amount_usdc, destination_address, initial_status, mode,
                ledger.L_WITHDRAW_PENDING,
            )
            await debit_in_conn(
                conn, user_id, amount_usdc, T_WITHDRAW,
                ref_id=row["id"],
                note=f"withdrawal request to {destination_address[:10]}…",
            )
    # Honest pending-state web notification (#1819). The ledger debit is an
    # available-balance lock (NOT a final transfer), and the on-chain transfer
    # only fires once an operator approves AND every guard
    # (EXECUTION_PATH_VALIDATED) is on. Without this alert the user only ever
    # sees the "withdrawal_confirmed" alert, which can never fire if the
    # guard is off — so the user is left guessing whether their funds are
    # safe. Emit ONCE per withdrawal_id, deduped by ``withdrawal:<id>:requested``
    # via migration 101's unique index. Best-effort: failures here NEVER undo
    # the committed ledger debit (persist_user_alert_once swallows its own
    # errors per its contract).
    #
    # Ordering note (Codex P2 #1821): emit BEFORE the auto-mode inline
    # ``_settle_withdrawal`` call. In ``auto`` approval mode with
    # EXECUTION_PATH_VALIDATED=True the settle path can complete the
    # withdrawal in this same call (status='completed' + a
    # 'withdrawal_confirmed' alert). Sending the "pending review" copy AFTER a
    # confirmed terminal state would mis-narrate the lifecycle. Firing
    # requested → (then) settle/confirmed preserves correct order — the two
    # alerts use distinct dedup keys (``:requested`` vs ``:completed``) so
    # they can co-exist for the same withdrawal id without colliding on the
    # migration-101 partial-unique index.
    #
    # asyncpg interop note (Gemini HIGH #1821): ``row`` here is an
    # ``asyncpg.Record`` which supports ``key in row`` + ``row[key]`` but
    # NOT ``row.get(...)`` — using ``.get`` would AttributeError at runtime,
    # be swallowed by the outer try/except, and silently kill the alert.
    try:
        from ..webtrader.backend.notification_prefs import persist_user_alert_once
        _lifecycle = (
            row["lifecycle_state"]
            if "lifecycle_state" in row
            else None
        ) or ledger.L_WITHDRAW_PENDING
        await persist_user_alert_once(
            user_id=row["user_id"],
            alert_key="system_status",
            title="Withdrawal request received",
            body=(
                f"Your ${float(amount_usdc):.2f} USDC withdrawal to "
                f"{destination_address[:10]}… is pending review. Funds are "
                f"reserved; they will be sent on-chain once approved and "
                f"confirmed. You will get a separate notification when the "
                f"on-chain transfer confirms."
            ),
            severity="info",
            alert_kind="withdrawal_requested",
            dedup_key=f"withdrawal:{row['id']}:requested",
            metadata={
                "withdrawal_id": str(row["id"]),
                "amount_usdc": float(amount_usdc),
                "destination_address": destination_address,
                "status": row["status"],
                "lifecycle_state": _lifecycle,
            },
        )
    except Exception as exc:
        # Defense in depth: persist_user_alert_once already swallows its own
        # errors, but a future regression must not undo the committed debit.
        logger.warning(
            "withdrawal_requested_alert_failed withdrawal_id=%s err=%s",
            row["id"], exc,
        )

    # Auto-approval mode skips the admin approve step, so the on-chain
    # settlement (deferred no-op in paper) must fire here instead — otherwise
    # an auto-approved live withdrawal would be debited but never sent. Fired
    # AFTER the requested-alert so the user sees: requested → (then) the
    # appropriate terminal alert (confirmed / failed / refunded) in order.
    if initial_status == "approved":
        await _settle_withdrawal(row["id"], destination_address, amount_usdc)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM withdrawals WHERE id = $1", row["id"]
            )
    return dict(row)


async def get_pending_withdrawals(limit: int = 50) -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT w.*, u.telegram_id, u.username
            FROM withdrawals w
            JOIN users u ON u.id = w.user_id
            WHERE w.status = 'pending'
            ORDER BY w.created_at ASC
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


async def find_stuck_withdrawals(
    older_than_hours: int = 24,
    limit: int = 100,
) -> list[dict]:
    """Operator visibility for withdrawals deferred or stuck on-chain (#1819).

    Returns rows whose status is ``pending`` / ``approved`` / ``processing``
    AND that are older than ``older_than_hours`` AND have NO ``tx_hash``.
    That set covers exactly the cases this lane fixed visibility for:

      * ``pending`` — waiting for admin approval (manual mode) for too long;
      * ``approved`` — guard off (``EXECUTION_PATH_VALIDATED=False``) so
        ``_attempt_onchain_transfer`` is a silent no-op and the row never
        broadcasts. This was the primary scenario behind the owner report;
      * ``processing`` — on-chain submit attempted but tx_hash never landed
        (network outage / nonce race / wait-for-receipt timeout).

    Rows with a tx_hash are excluded: at that point the on-chain explorer is
    the source of truth, and ``status`` will move to ``completed`` or
    ``failed`` once the receipt is observed.

    Read-only: NO ledger or wallets mutation, NO on-chain call, NO live-guard
    flag read or flip. The amount returned is for operator dashboards only —
    NEVER as a balance credit. Address truncation matches the rest of the
    admin surface so the panel can render without leaking full PII.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT w.id,
                   w.user_id,
                   w.amount_usdc,
                   w.destination_address,
                   w.status,
                   w.lifecycle_state,
                   w.approval_mode,
                   w.created_at,
                   w.submitted_at,
                   w.onchain_error
              FROM withdrawals w
             WHERE w.status IN ('pending', 'approved', 'processing')
               AND w.tx_hash IS NULL
               AND w.created_at < NOW() - make_interval(hours => $1)
             ORDER BY w.created_at ASC
             LIMIT $2
            """,
            int(older_than_hours), int(limit),
        )
    return [dict(r) for r in rows]


async def get_user_withdrawals(user_id: UUID, limit: int = 10) -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM withdrawals
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id, limit,
        )
    return [dict(r) for r in rows]


async def _attempt_onchain_transfer(
    withdrawal_id: UUID,
    destination_address: str,
    amount_usdc: Decimal,
) -> Optional[dict]:
    """Send USDC on-chain for an approved withdrawal and settle its status.

    Paper-safe: exits immediately when EXECUTION_PATH_VALIDATED=False (the
    row stays 'approved'; no capital moves).

    Live path: marks the row 'processing', broadcasts the transfer via
    integrations.polygon_usdc.transfer_usdc(), then on confirmation marks it
    'completed' and records tx_hash. Raises on any failure so the caller can
    mark the row 'failed' with the error.

    Idempotency: a row that already has a tx_hash is never re-sent — only
    pending rows reach approval (approve_withdrawal gates on status='pending'),
    and the tx_hash column carries a partial-unique index as a backstop.

    Safety: called AFTER the DB approval row is committed. The ledger debit is
    permanent regardless of transfer outcome; a 'failed' row is reconciled
    out-of-band by an operator. All outcomes are logged.
    """
    from ..config import get_settings
    s = get_settings()
    if not s.EXECUTION_PATH_VALIDATED:
        logger.info(
            "withdrawal_onchain_deferred EXECUTION_PATH_VALIDATED=false "
            "withdrawal_id=%s destination=%s amount=%s",
            withdrawal_id, destination_address, amount_usdc,
        )
        return None

    pool = get_pool()
    async with pool.acquire() as conn:
        existing_tx = await conn.fetchval(
            "SELECT tx_hash FROM withdrawals WHERE id = $1", withdrawal_id
        )
    if existing_tx:
        logger.warning(
            "withdrawal_onchain_already_sent withdrawal_id=%s tx_hash=%s",
            withdrawal_id, existing_tx,
        )
        return {"tx_hash": existing_tx, "status": 1, "skipped": True}

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE withdrawals SET status = 'processing', lifecycle_state = $2, "
            "submitted_at = COALESCE(submitted_at, NOW()) "
            "WHERE id = $1 AND status = 'approved'",
            withdrawal_id, ledger.L_CONFIRMING,
        )

    # Custody-mode dispatcher: EOA → polygon_usdc.transfer_usdc (master-funded);
    # Safe → SafeCustody.transfer_usdc (gasless via Polymarket relayer). Default
    # CUSTODY_MODE='eoa' keeps the merged C1 path unchanged.
    from ..wallet.custody import transfer_usdc
    result = await transfer_usdc(to=destination_address, amount_usdc=amount_usdc)

    async with pool.acquire() as conn:
        completed = await conn.fetchrow(
            "UPDATE withdrawals SET status = 'completed', tx_hash = $2, "
            "processed_at = NOW(), confirmed_at = NOW(), lifecycle_state = $3 "
            "WHERE id = $1 "
            "RETURNING user_id, id, amount_usdc, destination_address, tx_hash",
            withdrawal_id, result["tx_hash"], ledger.L_SWEPT,
        )
    if completed is not None:
        from ..webtrader.backend.notification_prefs import persist_user_alert_once
        await persist_user_alert_once(
            user_id=completed["user_id"],
            alert_key="system_status",
            title="Withdrawal confirmed",
            body=f"${float(completed['amount_usdc']):.2f} withdrawal is complete.",
            severity="info",
            alert_kind="withdrawal_confirmed",
            dedup_key=f"withdrawal:{completed['id']}:completed",
            metadata={
                "withdrawal_id": str(completed["id"]),
                "tx_hash": completed["tx_hash"],
                "amount_usdc": float(completed["amount_usdc"]),
                "destination_address": completed["destination_address"],
                "status": "completed",
            },
        )
    from .. import audit
    await audit.write(
        actor_role="bot", action="withdrawal_onchain_sent",
        payload={"withdrawal_id": str(withdrawal_id),
                 "destination": destination_address,
                 "amount_usdc": str(amount_usdc),
                 "tx_hash": result["tx_hash"],
                 "gas_used": result.get("gas_used")},
    )
    return result


async def approve_withdrawal(
    withdrawal_id: UUID,
    admin_notes: Optional[str] = None,
) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE withdrawals
               SET status = 'approved',
                   admin_notes = $2,
                   lifecycle_state = $3,
                   processed_at = NOW()
             WHERE id = $1 AND status = 'pending'
            RETURNING *
            """,
            withdrawal_id, admin_notes, ledger.L_WITHDRAW_PENDING,
        )
    if row is None:
        raise ValueError(f"Withdrawal {withdrawal_id} not found or not pending")
    w = dict(row)
    await _settle_withdrawal(
        w["id"], w["destination_address"], w["amount_usdc"]
    )
    return w


async def _settle_withdrawal(
    withdrawal_id: UUID,
    destination_address: str,
    amount_usdc: Decimal,
) -> None:
    """Fire the on-chain transfer for an approved row and handle failure.

    Paper (guard OFF): no-op, row stays 'approved'.
    Live success: row already marked 'completed' by _attempt_onchain_transfer.
    Live failure:
      * PreflightError (no capital moved) → 'failed' + refund the ledger debit.
      * any other error (post-broadcast, ambiguous) → 'failed', NO refund;
        an operator reconciles out-of-band.
    """
    from ..integrations.polygon_usdc import PreflightError
    pool = get_pool()
    try:
        await _attempt_onchain_transfer(
            withdrawal_id=withdrawal_id,
            destination_address=destination_address,
            amount_usdc=amount_usdc,
        )
    except PreflightError as exc:
        logger.error(
            "withdrawal_onchain_preflight_failed withdrawal_id=%s error=%s "
            "(refunding ledger — no capital moved)", withdrawal_id, exc,
        )
        from ..wallet.ledger import credit_in_conn, T_ADJUSTMENT
        async with pool.acquire() as conn:
            async with conn.transaction():
                updated = await conn.fetchrow(
                    "UPDATE withdrawals SET status = 'failed', onchain_error = $2, "
                    "lifecycle_state = $3 "
                    "WHERE id = $1 AND status IN ('approved', 'processing') "
                    "AND tx_hash IS NULL RETURNING user_id",
                    withdrawal_id, str(exc)[:500], ledger.L_FAILED,
                )
                if updated is not None:
                    await credit_in_conn(
                        conn, updated["user_id"], amount_usdc, T_ADJUSTMENT,
                        ref_id=withdrawal_id,
                        note=f"refund: withdrawal {str(withdrawal_id)[:8]} preflight-failed",
                    )
    except Exception as exc:
        logger.error(
            "withdrawal_onchain_transfer_failed withdrawal_id=%s error=%s "
            "(NOT refunded — operator reconciliation required)",
            withdrawal_id, exc,
        )
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE withdrawals SET status = 'failed', onchain_error = $2, "
                "lifecycle_state = $3 "
                "WHERE id = $1 AND status IN ('approved', 'processing')",
                withdrawal_id, str(exc)[:500], ledger.L_MANUAL_REVIEW,
            )


async def reject_withdrawal(
    withdrawal_id: UUID,
    admin_notes: Optional[str] = None,
) -> dict:
    """Reject and refund the ledger debit."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                UPDATE withdrawals
                   SET status = 'rejected',
                       admin_notes = $2,
                       lifecycle_state = $3,
                       processed_at = NOW()
                 WHERE id = $1 AND status = 'pending'
                RETURNING *
                """,
                withdrawal_id, admin_notes, ledger.L_FAILED,
            )
            if row is None:
                raise ValueError(f"Withdrawal {withdrawal_id} not found or not pending")
            # Refund: re-credit the debited amount
            from ..wallet.ledger import credit_in_conn, T_ADJUSTMENT
            await credit_in_conn(
                conn, row["user_id"], row["amount_usdc"], T_ADJUSTMENT,
                ref_id=row["id"],
                note=f"refund: withdrawal {str(withdrawal_id)[:8]} rejected",
            )
    return dict(row)
