"""Bridge deposit STATUS poller — safe, non-crediting groundwork (#1805).

Owner decision (2026-06-13): "Document precise blocker + safe groundwork."
Native Polygon USDC/USDT deposits cannot be safely credited as tradeable
balance today — the live order path funds from USDC.e (master sweep + the
``deposits``-table-bound ``get_live_balance`` ledger filter), while Bridge
delivers *pUSD* to a Polymarket wallet, and there is no proven
pUSD <-> order-funder path. Crediting a pUSD settlement as spendable balance
would be unsafe fake-enablement.

This poller therefore NEVER credits balance. When enabled
(``BRIDGE_DEPOSIT_POLLER_ENABLED``, default OFF) it:

  1. loads each user's persisted Bridge EVM deposit address;
  2. reads terminal Bridge ``COMPLETED`` pUSD settlements via the adapter
     (mocked in tests; live only when the flag is on);
  3. persists each to ``bridge_deposit_events`` flagged ``MANUAL_REVIEW`` with
     ``credited_deposit_id = NULL`` (preserving the raw Bridge ``COMPLETED``
     payload), so operators have an auditable queue;
  4. emits exactly one honest, deduped web notification telling the user the
     bridged deposit was *received but is pending review and not yet tradeable*.

Hard invariants (pinned by tests):
  * no write to ``deposits`` / ``ledger`` / ``wallets``; ``get_live_balance`` is
    never touched;
  * no sweep, no order, no live-guard flag read or flip;
  * fail-closed per user on Bridge outage (logged, never raised);
  * idempotent: the ``bridge_deposit_events`` tx_hash unique index + the
    ``persist_user_alert_once`` dedup index make replays a no-op.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from uuid import UUID

import structlog

from ...config import get_settings
from ...database import get_pool
from ...integrations import polymarket_bridge as bridge
from ...webtrader.backend.notification_prefs import persist_user_alert_once

log = structlog.get_logger(__name__)

# Internal disposition for a Bridge-COMPLETED pUSD settlement that this bot
# cannot auto-credit yet. Operators query ``bridge_deposit_events`` by this
# status to find settlements awaiting manual reconciliation.
MANUAL_REVIEW_STATUS = "MANUAL_REVIEW"
MANUAL_REVIEW_REASON = (
    "Bridge COMPLETED pUSD settlement — native-token auto-credit disabled "
    "pending enablement (USDC.e/get_live_balance-bound accounting, no proven "
    "pUSD<->order-funder path). Operator must reconcile manually; balance NOT "
    "credited."
)


@dataclass(frozen=True)
class PollResult:
    """Counts from one poll pass — for observability and tests."""

    users_polled: int = 0
    settlements_seen: int = 0
    manual_review_recorded: int = 0
    notifications_sent: int = 0
    errors: int = 0


async def _load_bridge_addresses(conn) -> list[tuple[UUID, str]]:
    """Every user with a persisted Bridge EVM deposit address."""
    rows = await conn.fetch(
        """
        SELECT user_id, evm_address
          FROM bridge_deposit_addresses
         WHERE evm_address IS NOT NULL
        """
    )
    return [(r["user_id"], r["evm_address"]) for r in rows]


def _normalized_usdc(tx: bridge.BridgeTransaction) -> Optional[Decimal]:
    """Display-only normalized amount (NEVER a credit). pUSD/USDC/USDT are all
    6-decimals on Polygon; default to 6 when the status payload omits it."""
    if tx.from_amount_base_unit is None:
        return None
    try:
        decimals = int(tx.raw.get("fromTokenDecimals") or 6)
        return bridge.base_units_to_decimal(tx.from_amount_base_unit, decimals)
    except (ValueError, TypeError, ArithmeticError):
        return None


async def _record_manual_review(
    conn,
    *,
    user_id: UUID,
    address: str,
    tx: bridge.BridgeTransaction,
    normalized: Optional[Decimal],
) -> bool:
    """Persist a COMPLETED pUSD settlement as MANUAL_REVIEW (not credited).

    Idempotent via the ``uq_bridge_deposit_events_tx_hash`` unique index:
    ON CONFLICT refreshes disposition/timestamps but never credits. Returns
    True only when this call first transitioned the row INTO manual review
    (so the web notification fires exactly once per settlement).
    """
    import json as _json

    row = await conn.fetchrow(
        """
        INSERT INTO bridge_deposit_events (
            user_id, bridge_address, from_chain_id, from_token_address,
            from_amount_base_unit, to_chain_id, to_token_address,
            status, tx_hash, normalized_amount_usdc, raw,
            completed_at, manual_review_reason
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, NOW(), $12
        )
        ON CONFLICT (tx_hash) WHERE tx_hash IS NOT NULL DO UPDATE SET
            status = EXCLUDED.status,
            normalized_amount_usdc = EXCLUDED.normalized_amount_usdc,
            raw = EXCLUDED.raw,
            updated_at = NOW(),
            manual_review_reason = EXCLUDED.manual_review_reason
        RETURNING (xmax = 0) AS inserted, credited_deposit_id
        """,
        user_id,
        address,
        str(tx.from_chain_id if tx.from_chain_id is not None else ""),
        str(tx.from_token_address or ""),
        str(tx.from_amount_base_unit or ""),
        str(tx.to_chain_id if tx.to_chain_id is not None else ""),
        str(tx.to_token_address or ""),
        MANUAL_REVIEW_STATUS,
        tx.tx_hash,
        normalized,
        _json.dumps(dict(tx.raw)),
        MANUAL_REVIEW_REASON,
    )
    # Defensive: a row that was somehow already credited must never re-notify.
    if row is None:
        return False
    if row["credited_deposit_id"] is not None:
        return False
    return bool(row["inserted"])


async def run_once() -> PollResult:
    """One safe poll pass. No crediting, no sweep, no order, no guard flip."""
    settings = get_settings()
    if not bool(getattr(settings, "BRIDGE_DEPOSIT_POLLER_ENABLED", False)):
        # Dormant by default — never makes a live Bridge call until enabled.
        return PollResult()

    users_polled = 0
    settlements_seen = 0
    manual_review_recorded = 0
    notifications_sent = 0
    errors = 0

    pool = get_pool()
    async with pool.acquire() as conn:
        addresses = await _load_bridge_addresses(conn)

    for user_id, address in addresses:
        users_polled += 1
        try:
            transactions = await bridge.get_status(address)
        except Exception as exc:
            # Fail closed per user — a Bridge outage must never raise into the
            # scheduler or stall other users.
            log.warning(
                "bridge_status_poller: get_status failed (fail-closed)",
                user_id=str(user_id), err=str(exc),
            )
            errors += 1
            continue

        for tx in bridge.completed_pusd_settlements(transactions):
            settlements_seen += 1
            if not tx.tx_hash:
                # No tx_hash -> cannot dedup safely; skip until Bridge assigns one.
                continue
            normalized = _normalized_usdc(tx)
            try:
                pool = get_pool()
                async with pool.acquire() as conn:
                    first_seen = await _record_manual_review(
                        conn, user_id=user_id, address=address,
                        tx=tx, normalized=normalized,
                    )
                if first_seen:
                    manual_review_recorded += 1
            except Exception as exc:
                log.warning(
                    "bridge_status_poller: persist failed",
                    user_id=str(user_id), tx_hash=tx.tx_hash, err=str(exc),
                )
                errors += 1
                continue

            if not first_seen:
                continue

            amount_txt = (
                f"~${float(normalized):.2f} " if normalized is not None else ""
            )
            alert_id = await persist_user_alert_once(
                user_id=user_id,
                alert_key="system_status",
                title="Bridge deposit received",
                body=(
                    f"Your bridged deposit {amount_txt}settled as pUSD on "
                    "Polygon and was received. It is pending review and is "
                    "NOT yet available for trading."
                ),
                severity="warning",
                alert_kind="bridge_deposit_received",
                dedup_key=f"bridge:{tx.tx_hash}:received",
                metadata={
                    "tx_hash": tx.tx_hash,
                    "from_token_address": tx.from_token_address,
                    "to_token_address": tx.to_token_address,
                    "normalized_amount_usdc": (
                        str(normalized) if normalized is not None else None
                    ),
                    "disposition": "manual_review_not_credited",
                },
            )
            if alert_id is not None:
                notifications_sent += 1

    if settlements_seen or errors:
        log.info(
            "bridge_status_poller.run_once",
            users_polled=users_polled,
            settlements_seen=settlements_seen,
            manual_review_recorded=manual_review_recorded,
            notifications_sent=notifications_sent,
            errors=errors,
        )
    return PollResult(
        users_polled=users_polled,
        settlements_seen=settlements_seen,
        manual_review_recorded=manual_review_recorded,
        notifications_sent=notifications_sent,
        errors=errors,
    )
