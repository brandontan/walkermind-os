"""On-chain USDC transfer from the master (hot-pool) wallet.

Live capital-exit path for withdrawals. Signs and broadcasts an ERC-20
``transfer`` from the master wallet that holds consolidated user funds.

Safety posture (mirrors integrations/polymarket.py:submit_live_redemption):
  * Hard-gated behind EXECUTION_PATH_VALIDATED — raises before any signing
    when the guard is false, so paper mode can never move real capital.
  * Pre-flight balance check: refuses if the hot pool lacks the USDC or the
    native MATIC needed to pay gas.
  * Gas-price ceiling: refuses above INSTANT_REDEEM_GAS_GWEI_MAX so a fee
    spike cannot drain the pool on gas.
  * Every failure raises (never silently swallowed); the caller records the
    outcome against the withdrawal row.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from web3 import AsyncWeb3

from ..config import get_settings
from .polygon import _get_w3, gas_price_gwei, get_native_balance, get_usdc_balance, nonce_lock

logger = logging.getLogger(__name__)


class PreflightError(RuntimeError):
    """Transfer refused *before* anything was broadcast on-chain.

    Signals to the caller that NO capital moved (activation guard, gas
    ceiling, or insufficient hot-pool balance), so the ledger debit is safe
    to refund. Distinct from a post-broadcast failure, which is ambiguous
    and must be reconciled out-of-band rather than auto-refunded.
    """


# ERC-20 transfer + balanceOf. Kept local to the write path so the read-only
# module (polygon.py) stays free of state-changing ABI. balanceOf is needed to
# sweep a wallet's *entire* USDC balance without float rounding.
ERC20_ABI: list[dict[str, Any]] = [
    {
        "constant": False,
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# A bridged-USDC transfer on Polygon costs well under this; the buffer covers
# gas-accounting variance without risking an out-of-gas revert.
_TRANSFER_GAS_LIMIT = 120_000
# Native MATIC transfer (sweep gas top-up) is a fixed 21k-gas send.
_MATIC_TRANSFER_GAS = 21_000
# Minimum native MATIC the hot pool must hold to cover one transfer's gas.
_MIN_GAS_MATIC = 0.05


async def transfer_usdc(to: str, amount_usdc: Decimal) -> dict[str, Any]:
    """Send ``amount_usdc`` USDC from the master wallet to ``to`` on Polygon.

    Returns ``{tx_hash, gas_used, status}`` on a confirmed (status==1) transfer.
    Raises PreflightError when refused before broadcast (guard / gas ceiling /
    insufficient balance — no capital moved, safe to refund). Raises plain
    RuntimeError on a post-broadcast revert (ambiguous — reconcile, do not
    auto-refund). Raising keeps the caller's status bookkeeping unambiguous.
    """
    settings = get_settings()
    if not settings.EXECUTION_PATH_VALIDATED:
        raise PreflightError(
            "transfer_usdc blocked: EXECUTION_PATH_VALIDATED=false"
        )
    if amount_usdc <= 0:
        raise PreflightError(f"transfer_usdc: non-positive amount {amount_usdc}")

    from ..wallet.vault import master_wallet

    w3 = _get_w3()
    src, pk = master_wallet()
    src_cs = AsyncWeb3.to_checksum_address(src)
    to_cs = AsyncWeb3.to_checksum_address(to)
    usdc_cs = AsyncWeb3.to_checksum_address(settings.USDC_POLYGON)

    # Pre-flight 1: gas-price ceiling (reuse the redeem worker's guard value).
    gwei = await gas_price_gwei()
    if gwei > settings.INSTANT_REDEEM_GAS_GWEI_MAX:
        raise PreflightError(
            f"transfer_usdc blocked: gas {gwei:.1f} gwei exceeds ceiling "
            f"{settings.INSTANT_REDEEM_GAS_GWEI_MAX:.1f}"
        )

    # Pre-flight 2: hot pool holds enough USDC and enough MATIC for gas.
    usdc_bal = await get_usdc_balance(src_cs)
    if Decimal(str(usdc_bal)) < amount_usdc:
        raise PreflightError(
            f"transfer_usdc blocked: hot-pool USDC {usdc_bal} < requested "
            f"{amount_usdc}"
        )
    matic_bal = await get_native_balance(src_cs)
    if matic_bal < _MIN_GAS_MATIC:
        raise PreflightError(
            f"transfer_usdc blocked: hot-pool MATIC {matic_bal} < minimum "
            f"{_MIN_GAS_MATIC} for gas"
        )

    raw_amount = int(amount_usdc * (10 ** settings.USDC_DECIMALS))
    usdc = w3.eth.contract(address=usdc_cs, abi=ERC20_ABI)
    # Serialize nonce read → sign → broadcast so a concurrent master-wallet send
    # can't reuse this nonce; "pending" tag counts in-mempool txs too.
    async with nonce_lock(src_cs):
        nonce = await w3.eth.get_transaction_count(src_cs, "pending")
        gas_price = await w3.eth.gas_price
        tx = await usdc.functions.transfer(to_cs, raw_amount).build_transaction({
            "from": src_cs,
            "nonce": nonce,
            "gas": _TRANSFER_GAS_LIMIT,
            "gasPrice": gas_price,
            "chainId": 137,
        })
        signed = w3.eth.account.sign_transaction(tx, private_key=pk)
        raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        tx_hash = await w3.eth.send_raw_transaction(raw)
    receipt = await w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    status = int(receipt["status"])
    if status != 1:
        raise RuntimeError(
            f"USDC transfer reverted (tx={tx_hash.hex()}, to={to_cs}, "
            f"amount={amount_usdc})"
        )
    logger.info(
        "transfer_usdc_confirmed tx=%s to=%s amount=%s gas_used=%s",
        tx_hash.hex(), to_cs, amount_usdc, int(receipt["gasUsed"]),
    )
    return {
        "tx_hash": tx_hash.hex(),
        "gas_used": int(receipt["gasUsed"]),
        "status": status,
    }


async def _send_native_matic(to_cs: str, amount_matic: float) -> str:
    """Send native MATIC from the master wallet to ``to_cs`` (sweep gas top-up).

    Raises PreflightError if the master pool can't cover the top-up plus its own
    send gas; raises RuntimeError on revert. Waits for confirmation so the
    recipient can spend the gas immediately afterwards.
    """
    from ..wallet.vault import master_wallet
    w3 = _get_w3()
    master_addr, master_pk = master_wallet()
    master_cs = AsyncWeb3.to_checksum_address(master_addr)

    master_matic = await get_native_balance(master_cs)
    if master_matic < amount_matic + _MIN_GAS_MATIC:
        raise PreflightError(
            f"gas top-up blocked: master MATIC {master_matic} < needed "
            f"{amount_matic + _MIN_GAS_MATIC}"
        )

    value = w3.to_wei(Decimal(str(amount_matic)), "ether")
    async with nonce_lock(master_cs):
        nonce = await w3.eth.get_transaction_count(master_cs, "pending")
        gas_price = await w3.eth.gas_price
        tx = {
            "from": master_cs, "to": to_cs, "value": value, "nonce": nonce,
            "gas": _MATIC_TRANSFER_GAS, "gasPrice": gas_price, "chainId": 137,
        }
        signed = w3.eth.account.sign_transaction(tx, private_key=master_pk)
        raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        tx_hash = await w3.eth.send_raw_transaction(raw)
    receipt = await w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    if int(receipt["status"]) != 1:
        raise RuntimeError(f"gas top-up reverted (tx={tx_hash.hex()}, to={to_cs})")
    logger.info("gas_topup_confirmed to=%s matic=%s tx=%s",
                to_cs, amount_matic, tx_hash.hex())
    return tx_hash.hex()


async def sweep_usdc_to_master(from_address: str, from_pk: str) -> dict[str, Any]:
    """Sweep a user deposit wallet's entire USDC balance into the master pool.

    Double-gated: requires EXECUTION_PATH_VALIDATED AND SWEEP_ONCHAIN_ENABLED —
    raises PreflightError otherwise (no capital moves). Skips dust below
    SWEEP_MIN_USDC. Tops the wallet up with MATIC from the master if it lacks
    gas (bridged-USDC deposit wallets hold no native token), then signs the
    USDC transfer with the wallet's own key. Raises on revert; the caller marks
    the user's deposits swept only after this returns a confirmed tx.
    """
    settings = get_settings()
    if not (settings.EXECUTION_PATH_VALIDATED and settings.SWEEP_ONCHAIN_ENABLED):
        raise PreflightError(
            "sweep_usdc_to_master blocked: EXECUTION_PATH_VALIDATED + "
            "SWEEP_ONCHAIN_ENABLED both required"
        )

    from ..wallet.vault import master_wallet
    w3 = _get_w3()
    master_addr, _ = master_wallet()
    master_cs = AsyncWeb3.to_checksum_address(master_addr)
    src_cs = AsyncWeb3.to_checksum_address(from_address)
    usdc_cs = AsyncWeb3.to_checksum_address(settings.USDC_POLYGON)
    usdc = w3.eth.contract(address=usdc_cs, abi=ERC20_ABI)

    raw_balance = int(await usdc.functions.balanceOf(src_cs).call())
    amount = Decimal(raw_balance) / (10 ** settings.USDC_DECIMALS)
    if amount < Decimal(str(settings.SWEEP_MIN_USDC)):
        logger.info("sweep_skip_dust from=%s usdc=%s", src_cs, amount)
        return {"skipped": True, "reason": "dust", "amount_usdc": str(amount)}

    gwei = await gas_price_gwei()
    if gwei > settings.INSTANT_REDEEM_GAS_GWEI_MAX:
        raise PreflightError(
            f"sweep blocked: gas {gwei:.1f} gwei exceeds ceiling "
            f"{settings.INSTANT_REDEEM_GAS_GWEI_MAX:.1f}"
        )

    # Ensure the wallet can pay for one transfer; top up from master if not.
    matic_bal = await get_native_balance(src_cs)
    topup = 0.0
    if matic_bal < settings.SWEEP_GAS_TOPUP_MATIC:
        topup = settings.SWEEP_GAS_TOPUP_MATIC - matic_bal
        await _send_native_matic(to_cs=src_cs, amount_matic=topup)

    async with nonce_lock(src_cs):
        nonce = await w3.eth.get_transaction_count(src_cs, "pending")
        gas_price = await w3.eth.gas_price
        tx = await usdc.functions.transfer(master_cs, raw_balance).build_transaction({
            "from": src_cs, "nonce": nonce, "gas": _TRANSFER_GAS_LIMIT,
            "gasPrice": gas_price, "chainId": 137,
        })
        signed = w3.eth.account.sign_transaction(tx, private_key=from_pk)
        raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        tx_hash = await w3.eth.send_raw_transaction(raw)
    receipt = await w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    status = int(receipt["status"])
    if status != 1:
        raise RuntimeError(
            f"sweep transfer reverted (tx={tx_hash.hex()}, from={src_cs})"
        )
    logger.info(
        "sweep_confirmed from=%s amount=%s gas_topup_matic=%s tx=%s",
        src_cs, amount, topup, tx_hash.hex(),
    )
    return {
        "tx_hash": tx_hash.hex(),
        "amount_usdc": str(amount),
        "gas_used": int(receipt["gasUsed"]),
        "gas_topup_matic": topup,
        "status": status,
    }
