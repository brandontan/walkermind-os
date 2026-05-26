"""Withdrawal request management.

Paper-only: requests are recorded and ledger-debited on submission.
No on-chain transfer until EXECUTION_PATH_VALIDATED guard is activated.

Approval modes (system_settings key 'withdrawal_approval_mode'):
  'manual' — admin must explicitly approve/reject each request
  'auto'   — auto-approved on submission (ledger already debited at request time)

On-chain transfer lifecycle:
  create_withdrawal_request() → DB row + ledger debit (always)
  approve_withdrawal()        → DB row 'approved' + _attempt_onchain_transfer()
  _attempt_onchain_transfer() → no-op when EXECUTION_PATH_VALIDATED=False
                                NotImplementedError when True (until wired)
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional
from uuid import UUID

from ..database import get_pool
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
    """
    mode = await get_approval_mode()
    initial_status = "approved" if mode == "auto" else "pending"

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO withdrawals (user_id, amount_usdc, destination_address,
                                         status, approval_mode)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
                """,
                user_id, amount_usdc, destination_address, initial_status, mode,
            )
            await debit_in_conn(
                conn, user_id, amount_usdc, T_WITHDRAW,
                ref_id=row["id"],
                note=f"withdrawal request to {destination_address[:10]}…",
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
) -> None:
    """Attempt to send USDC on-chain for an approved withdrawal.

    Paper-safe: exits immediately when EXECUTION_PATH_VALIDATED=False.

    Live path: not yet wired — raises NotImplementedError until
    integrations/polygon_usdc.py:transfer_usdc() is implemented and
    master hot-pool signing credentials are available.

    Safety: called AFTER the DB approval row is committed. A failed
    transfer does NOT undo the approval — debit is permanent; admin
    handles out-of-band reconciliation. All outcomes are logged.
    """
    from ..config import get_settings
    s = get_settings()
    if not s.EXECUTION_PATH_VALIDATED:
        logger.info(
            "withdrawal_onchain_deferred EXECUTION_PATH_VALIDATED=false "
            "withdrawal_id=%s destination=%s amount=%s",
            withdrawal_id, destination_address, amount_usdc,
        )
        return
    # Live signing path — wire here when hot-pool infrastructure is ready:
    #
    #   from ..integrations.polygon_usdc import transfer_usdc
    #   tx_hash = await transfer_usdc(
    #       to=destination_address,
    #       amount_usdc=amount_usdc,
    #   )
    #   from .. import audit
    #   await audit.write(
    #       actor_role="bot", action="withdrawal_onchain_sent",
    #       payload={"withdrawal_id": str(withdrawal_id),
    #                "destination": destination_address,
    #                "amount_usdc": str(amount_usdc),
    #                "tx_hash": tx_hash},
    #   )
    raise NotImplementedError(
        "On-chain USDC transfer requires live signing infrastructure. "
        "Implement integrations/polygon_usdc.py:transfer_usdc() and "
        "uncomment the live path above when EXECUTION_PATH_VALIDATED."
    )


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
                   processed_at = NOW()
             WHERE id = $1 AND status = 'pending'
            RETURNING *
            """,
            withdrawal_id, admin_notes,
        )
    if row is None:
        raise ValueError(f"Withdrawal {withdrawal_id} not found or not pending")
    w = dict(row)
    # Fire on-chain transfer (paper: deferred; live: NotImplementedError until wired)
    try:
        await _attempt_onchain_transfer(
            withdrawal_id=w["id"],
            destination_address=w["destination_address"],
            amount_usdc=w["amount_usdc"],
        )
    except NotImplementedError as exc:
        logger.error(
            "withdrawal_onchain_not_wired withdrawal_id=%s: %s", withdrawal_id, exc
        )
    except Exception as exc:
        logger.error(
            "withdrawal_onchain_transfer_failed withdrawal_id=%s error=%s",
            withdrawal_id, exc,
        )
    return w


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
                       processed_at = NOW()
                 WHERE id = $1 AND status = 'pending'
                RETURNING *
                """,
                withdrawal_id, admin_notes,
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
