"""Custody-mode dispatcher + SafeCustody capital paths (chunks 3+4/4).

Routes the two capital-movement primitives — withdrawal payout and deposit
sweep — to the active custody implementation:

  CUSTODY_MODE='eoa'   → integrations.polygon_usdc (master-funded gas top-up,
                         the merged-and-shipped EOA paths)
  CUSTODY_MODE='safe'  → SafeCustody below (Polymarket Safe proxies + Builder
                         relayer, gasless)

The dispatcher is triple-gated for 'safe' mode: ``EXECUTION_PATH_VALIDATED``
AND ``USE_BUILDER_RELAYER`` AND every builder credential set. With any flag
or credential missing while ``CUSTODY_MODE='safe'`` the dispatcher raises
``BuilderRelayerUnavailable`` rather than silently falling back to EOA — a
flipped custody mode without the relayer wired is operator misconfiguration,
not a runtime decision.

Paper / current production posture is unchanged: ``CUSTODY_MODE`` defaults to
``'eoa'`` (config.py:151) so the dispatcher routes to the existing EOA paths
on every call until an operator flips it.
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

from .. import config as _config
from ..integrations import polygon_usdc
from ..integrations.builder_relayer import (
    BuilderRelayerUnavailable,
    is_relayer_configured,
    make_relayer_client,
)
from ..integrations.polygon import _get_w3, get_usdc_balance


def get_settings():
    """Indirection through the config module so test patches of
    ``projects.polymarket.crusaderbot.config.get_settings`` propagate. The
    rest of the codebase uses the same pattern (lazy resolution at call
    time) — see wallet/withdrawals.py and scheduler.py.
    """
    return _config.get_settings()

logger = logging.getLogger(__name__)


# ── dispatcher ──────────────────────────────────────────────────────────────

def _ensure_safe_mode_wired() -> None:
    """Raise loudly if CUSTODY_MODE='safe' but the relayer isn't fully wired.

    Loud failure (no silent fallback to EOA) — the operator must be aware
    that flipping CUSTODY_MODE requires the Builder Program credentials.
    """
    if not is_relayer_configured():
        raise BuilderRelayerUnavailable(
            "CUSTODY_MODE='safe' requires USE_BUILDER_RELAYER=true and the "
            "POLY_BUILDER_API_KEY / SECRET / PASSPHRASE secrets to be set"
        )


async def transfer_usdc(to: str, amount_usdc: Decimal) -> dict[str, Any]:
    """Withdrawal payout dispatcher. Returns the underlying call's dict.

    Routes to ``polygon_usdc.transfer_usdc`` in EOA mode (the merged C1 path)
    or ``SafeCustody.transfer_usdc`` in Safe mode (gasless via relayer).
    """
    if get_settings().CUSTODY_MODE == "safe":
        _ensure_safe_mode_wired()
        return await SafeCustody.transfer_usdc(to, amount_usdc)
    return await polygon_usdc.transfer_usdc(to, amount_usdc)


async def sweep_usdc_to_master(
    from_address: str, from_pk: str,
) -> dict[str, Any]:
    """Deposit-sweep dispatcher. Returns the underlying call's dict.

    Routes to ``polygon_usdc.sweep_usdc_to_master`` in EOA mode (master-funded
    gas top-up) or ``SafeCustody.sweep_usdc_to_master`` in Safe mode (gasless
    relayer pays for the user-Safe → master-Safe transfer).
    """
    if get_settings().CUSTODY_MODE == "safe":
        _ensure_safe_mode_wired()
        return await SafeCustody.sweep_usdc_to_master(from_address, from_pk)
    return await polygon_usdc.sweep_usdc_to_master(from_address, from_pk)


# ── SafeCustody: gasless capital paths via the Polymarket relayer ───────────

# Re-exported so callers writing `from .custody import PreflightError` get one
# typed error surface regardless of which custody backend handled the call.
PreflightError = polygon_usdc.PreflightError


class SafeCustody:
    """Capital ops routed through Polymarket Safe proxies + Builder relayer.

    Every method here is double-gated:
      1. ``EXECUTION_PATH_VALIDATED`` — same activation guard as the EOA paths.
      2. ``is_relayer_configured()`` — Builder creds + USE_BUILDER_RELAYER true.

    Both raise typed errors (PreflightError / BuilderRelayerUnavailable) — no
    silent fallback. The relayer SDK is sync; we wrap the two blocking calls
    (``execute`` and ``response.wait``) in ``asyncio.to_thread`` so the bot's
    asyncio event loop is never blocked.
    """

    @staticmethod
    async def transfer_usdc(to: str, amount_usdc: Decimal) -> dict[str, Any]:
        """Master Safe → ``to`` USDC payout for an approved withdrawal.

        Gasless: the relayer pays Polygon gas; the master Safe spends only
        USDC. Hot-pool USDC sufficiency is checked against the *Safe*
        balance, not the master EOA's.
        """
        settings = get_settings()
        if not settings.EXECUTION_PATH_VALIDATED:
            raise PreflightError(
                "SafeCustody.transfer_usdc blocked: EXECUTION_PATH_VALIDATED=false"
            )
        if amount_usdc <= 0:
            raise PreflightError(
                f"SafeCustody.transfer_usdc: non-positive amount {amount_usdc}"
            )
        if not is_relayer_configured():
            raise BuilderRelayerUnavailable(
                "SafeCustody.transfer_usdc: relayer not configured"
            )

        from .vault import master_wallet
        _, master_pk = master_wallet()
        client = make_relayer_client(master_pk)
        master_safe = client.get_expected_safe()

        bal = await get_usdc_balance(master_safe)
        if Decimal(str(bal)) < amount_usdc:
            raise PreflightError(
                f"SafeCustody.transfer_usdc blocked: hot-pool Safe USDC {bal} "
                f"< requested {amount_usdc}"
            )

        result = await _execute_usdc_transfer(
            client, to=to, amount_usdc=amount_usdc,
            metadata="withdrawal payout",
        )
        logger.info(
            "safe_transfer_usdc_confirmed master_safe=%s to=%s amount=%s tx=%s",
            master_safe, to, amount_usdc, result["tx_hash"],
        )
        return result

    @staticmethod
    async def sweep_usdc_to_master(
        from_address: str, from_pk: str,
    ) -> dict[str, Any]:
        """User Safe → master Safe USDC sweep, gaslessly via the relayer.

        ``from_address`` is informational — the actual source Safe is the
        deterministic one for ``from_pk``. ``from_pk`` is the user's HD
        signer key (controls their Safe via the Polymarket factory).
        """
        settings = get_settings()
        if not (settings.EXECUTION_PATH_VALIDATED and settings.SWEEP_ONCHAIN_ENABLED):
            raise PreflightError(
                "SafeCustody.sweep_usdc_to_master blocked: "
                "EXECUTION_PATH_VALIDATED + SWEEP_ONCHAIN_ENABLED both required"
            )
        if not from_pk:
            raise PreflightError("SafeCustody.sweep: empty signer key")
        if not is_relayer_configured():
            raise BuilderRelayerUnavailable(
                "SafeCustody.sweep_usdc_to_master: relayer not configured"
            )

        # Master Safe address — derived once from the master signer; this is
        # the destination for every user-Safe sweep.
        from .vault import master_wallet
        _, master_pk = master_wallet()
        master_client = make_relayer_client(master_pk)
        master_safe = master_client.get_expected_safe()

        # User Safe sweeps from itself; sign with the user's HD key.
        user_client = make_relayer_client(from_pk)
        user_safe = user_client.get_expected_safe()

        raw_balance = await _read_usdc_raw_balance(user_safe)
        amount = Decimal(raw_balance) / (10 ** settings.USDC_DECIMALS)
        if amount < Decimal(str(settings.SWEEP_MIN_USDC)):
            logger.info(
                "safe_sweep_skip_dust user_safe=%s usdc=%s", user_safe, amount,
            )
            return {"skipped": True, "reason": "dust", "amount_usdc": str(amount)}

        result = await _execute_usdc_transfer(
            user_client, to=master_safe, amount_usdc=amount,
            metadata="deposit sweep",
        )
        logger.info(
            "safe_sweep_confirmed from_safe=%s to_master_safe=%s amount=%s tx=%s",
            user_safe, master_safe, amount, result["tx_hash"],
        )
        result["amount_usdc"] = str(amount)
        return result


# ── helpers (private) ───────────────────────────────────────────────────────

async def _execute_usdc_transfer(
    client: Any, to: str, amount_usdc: Decimal, metadata: str,
) -> dict[str, Any]:
    """Build, submit, and wait on a USDC transfer SafeTransaction.

    Wraps the two blocking SDK calls (``execute`` + ``response.wait``) in
    ``asyncio.to_thread`` so they never stall the event loop. Raises on
    non-terminal results — every confirmed transaction returns a tx_hash.
    """
    try:
        from py_builder_relayer_client.models import OperationType, SafeTransaction
    except Exception as exc:
        raise BuilderRelayerUnavailable(
            f"py-builder-relayer-client unavailable: {exc}"
        ) from exc

    from web3 import AsyncWeb3
    from ..integrations.polygon_usdc import ERC20_ABI
    settings = get_settings()
    w3 = _get_w3()
    usdc_cs = AsyncWeb3.to_checksum_address(settings.USDC_POLYGON)
    to_cs = AsyncWeb3.to_checksum_address(to)
    raw = int(amount_usdc * (10 ** settings.USDC_DECIMALS))
    usdc = w3.eth.contract(address=usdc_cs, abi=ERC20_ABI)
    data = usdc.encode_abi(abi_element_identifier="transfer", args=[to_cs, raw])

    tx = SafeTransaction(
        to=usdc_cs, operation=OperationType.Call, data=data, value="0",
    )
    response = await asyncio.to_thread(client.execute, [tx], metadata)
    final = await asyncio.to_thread(response.wait)
    if final is None:
        raise RuntimeError(
            f"relayer transfer did not reach a terminal state "
            f"(tx_id={response.transaction_id})"
        )
    return {
        "tx_hash": response.transaction_hash,
        "tx_id": response.transaction_id,
        "amount_usdc": str(amount_usdc),
        "status": 1,
    }


async def _read_usdc_raw_balance(address: str) -> int:
    """On-chain raw USDC balance (integer base units) for an address.

    Goes via the read-path contract in polygon_usdc.ERC20_ABI to keep the
    write module's ABI authoritative.
    """
    from web3 import AsyncWeb3
    from ..integrations.polygon_usdc import ERC20_ABI
    settings = get_settings()
    w3 = _get_w3()
    usdc = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(settings.USDC_POLYGON),
        abi=ERC20_ABI,
    )
    raw = await usdc.functions.balanceOf(
        AsyncWeb3.to_checksum_address(address)
    ).call()
    return int(raw)
