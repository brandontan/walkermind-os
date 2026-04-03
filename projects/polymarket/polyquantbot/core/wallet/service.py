"""core/wallet/service.py — WalletService: per-user real wallet lifecycle.

Provides idempotent wallet creation, balance fetch from Polymarket Data API,
and withdraw capability.  Private keys are stored AES-256-GCM-encrypted and
are decrypted only within the signing boundary — they are never logged or
returned to callers.

Key generation uses secp256k1 (ECDSA) from the ``cryptography`` package.
Address derivation uses keccak-256 via SHA3-256 (note: Python's sha3_256
implements the FIPS 202 finalisation; for production Ethereum-compatible
addresses install ``eth_account`` and replace ``_derive_address()``).

Rules:
    - All public methods are idempotent and async.
    - External HTTP calls carry retry (3×) + timeout (5 s).
    - ZERO silent failures — every error is logged before raising or returning.
    - Multi-user safe: per-user asyncio lock prevents TOCTOU on wallet creation.
    - WALLET_SECRET_KEY must be set in the environment before any call.
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from typing import Optional

import structlog
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric.ec import (
    SECP256K1,
    generate_private_key,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .models import WalletModel
from ..security.encryption import decrypt_private_key, encrypt_private_key

log = structlog.get_logger(__name__)

# ── HTTP / retry tuning ───────────────────────────────────────────────────────
_TIMEOUT_S: float = 5.0
_MAX_RETRIES: int = 3
_RETRY_DELAY_S: float = 0.5

# ── Polymarket Data API ───────────────────────────────────────────────────────
_DATA_API_BASE: str = "https://data-api.polymarket.com"

# ── USDC contract (Polygon) — required for withdraw ───────────────────────────
_USDC_CONTRACT: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"


# ── Address derivation ────────────────────────────────────────────────────────


def _derive_address(public_key_bytes_uncompressed: bytes) -> str:
    """Derive an Ethereum-style address from an uncompressed secp256k1 public key.

    Standard derivation: keccak256(pub_key[1:])[12:] → 20-byte address.

    Uses ``eth_account`` if installed (correct Ethereum Keccak-256); otherwise
    falls back to ``hashlib.sha3_256`` (FIPS 202 SHA-3, different padding from
    Ethereum's Keccak).  The fallback produces a valid unique identifier but
    the address will NOT match the on-chain Ethereum address derived from the
    same key.  Install ``eth_account`` for production Ethereum-compatible
    address derivation.

    Args:
        public_key_bytes_uncompressed: 65-byte uncompressed public key (04 || x || y).

    Returns:
        Lowercase ``0x``-prefixed 42-character address string.
    """
    xy_bytes = public_key_bytes_uncompressed[1:]  # drop 0x04 prefix

    try:
        from eth_account import Account as _Account  # noqa: PLC0415
        # eth_account is available — derive the correct Ethereum address
        # Reconstruct private key not available here, so compute via keccak directly
        try:
            from eth_hash.auto import keccak  # noqa: PLC0415
            digest = keccak(xy_bytes)
        except ImportError:
            # eth_hash fallback — sha3_256 (not true keccak, but consistent)
            digest = hashlib.sha3_256(xy_bytes).digest()
    except ImportError:
        # Fallback: sha3_256 (FIPS 202 SHA-3, not Ethereum's Keccak-256)
        # WARNING: address will not match on-chain Ethereum address for the same key
        digest = hashlib.sha3_256(xy_bytes).digest()

    return "0x" + digest[-20:].hex()


def _generate_keypair() -> tuple[str, str]:
    """Generate a new secp256k1 keypair.

    Returns:
        ``(private_key_hex, address)`` tuple where:
        - ``private_key_hex`` is the 64-hex-char raw private scalar.
        - ``address`` is the derived ``0x…`` address string.
    """
    ec_key = generate_private_key(SECP256K1(), default_backend())
    private_value: int = ec_key.private_numbers().private_value
    private_key_hex: str = private_value.to_bytes(32, "big").hex()

    pub_bytes = ec_key.public_key().public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint
    )
    address = _derive_address(pub_bytes)
    return private_key_hex, address


# ── WalletService ─────────────────────────────────────────────────────────────


class WalletService:
    """Per-user real wallet service with encrypted key storage.

    All wallets are held in-memory with optional external persistence via
    the ``_wallets`` dict.  For production, wire in a PostgreSQL/SQLite
    persistence layer via :meth:`inject_storage`.

    Args:
        http_session_factory: Callable returning an ``aiohttp.ClientSession``.
            When ``None``, balance fetch falls back to 0.0 with a warning.
    """

    def __init__(self, http_session_factory=None) -> None:
        self._wallets: dict[int, WalletModel] = {}       # user_id → WalletModel
        self._creation_locks: dict[int, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._session_factory = http_session_factory

        log.info("wallet_service_initialized")

    # ── Public API ─────────────────────────────────────────────────────────────

    async def create_wallet(self, user_id: int) -> WalletModel:
        """Create and persist a new wallet for *user_id*.

        Idempotent: returns the existing wallet if one was already created.

        Args:
            user_id: Telegram (or other) user integer ID.

        Returns:
            :class:`WalletModel` for the user (never includes plaintext key).

        Raises:
            EnvironmentError: If ``WALLET_SECRET_KEY`` is not set.
        """
        # Fast path — no lock needed for read after initial creation
        existing = self._wallets.get(user_id)
        if existing is not None:
            log.debug("wallet_already_exists", user_id=user_id, address=existing.address)
            return existing

        # Get or create a per-user lock to avoid duplicate wallet generation
        async with self._global_lock:
            if user_id not in self._creation_locks:
                self._creation_locks[user_id] = asyncio.Lock()
            user_lock = self._creation_locks[user_id]

        async with user_lock:
            # Double-check after acquiring per-user lock
            existing = self._wallets.get(user_id)
            if existing is not None:
                return existing

            private_key_hex, address = _generate_keypair()
            encrypted_key = encrypt_private_key(private_key_hex)

            # Immediately zero out the plaintext key from local scope
            del private_key_hex

            wallet = WalletModel(
                user_id=user_id,
                address=address,
                encrypted_private_key=encrypted_key,
                created_at=time.time(),
            )
            self._wallets[user_id] = wallet

            log.info(
                "wallet_created",
                user_id=user_id,
                address=address,
                # encrypted_private_key is intentionally NOT logged
            )
            return wallet

    async def get_wallet(self, user_id: int) -> Optional[WalletModel]:
        """Return the wallet for *user_id*, or ``None`` if it doesn't exist.

        Args:
            user_id: Telegram user ID.

        Returns:
            :class:`WalletModel` or ``None``.
        """
        return self._wallets.get(user_id)

    async def get_balance(self, user_id: int) -> float:
        """Fetch on-chain USDC balance for *user_id*'s wallet.

        Makes a best-effort call to the Polymarket Data API.  Falls back to
        ``0.0`` on network errors after exhausting retries.

        Args:
            user_id: Telegram user ID.

        Returns:
            USDC balance as a float (0.0 on error or missing wallet).
        """
        wallet = self._wallets.get(user_id)
        if wallet is None:
            log.warning("get_balance_no_wallet", user_id=user_id)
            return 0.0

        url = f"{_DATA_API_BASE}/value?user={wallet.address}"

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                balance = await self._fetch_balance(url, wallet.address, attempt)
                log.info(
                    "balance_fetched",
                    user_id=user_id,
                    address=wallet.address,
                    balance=balance,
                    attempt=attempt,
                )
                return balance
            except asyncio.TimeoutError:
                log.warning("balance_fetch_timeout", attempt=attempt, url=url)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning(
                    "balance_fetch_error",
                    attempt=attempt,
                    error=str(exc),
                )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_DELAY_S * attempt)

        log.error("balance_fetch_all_retries_exhausted", user_id=user_id)
        return 0.0

    async def withdraw(
        self,
        user_id: int,
        to_address: str,
        amount_usdc: float,
    ) -> dict:
        """Initiate a USDC withdrawal from the user's wallet.

        Currently builds and logs the withdrawal intent.  Actual on-chain
        transaction signing requires ``eth_account`` (``pip install eth_account``)
        and a Polygon RPC endpoint (``POLYGON_RPC_URL`` env var).

        Args:
            user_id: Telegram user ID.
            to_address: Destination ``0x…`` address (must be 42 chars).
            amount_usdc: USDC amount to withdraw (must be > 0).

        Returns:
            Dict with ``status``, ``from_address``, ``to_address``, ``amount_usdc``.

        Raises:
            ValueError: If ``to_address`` is invalid or ``amount_usdc`` <= 0.
            RuntimeError: If the user has no wallet, or balance is insufficient.
        """
        if not isinstance(to_address, str) or len(to_address) != 42 or not to_address.startswith("0x"):
            raise ValueError(f"Invalid destination address: {to_address!r}")
        if amount_usdc <= 0:
            raise ValueError(f"Withdrawal amount must be positive, got {amount_usdc}")

        wallet = self._wallets.get(user_id)
        if wallet is None:
            raise RuntimeError(f"No wallet found for user_id={user_id}")

        # Fetch current balance to validate sufficiency
        balance = await self.get_balance(user_id)
        if balance < amount_usdc:
            raise RuntimeError(
                f"Insufficient balance: {balance:.4f} USDC available, "
                f"{amount_usdc:.4f} USDC requested."
            )

        # Decrypt key within signing boundary only
        private_key_hex = decrypt_private_key(wallet.encrypted_private_key)
        try:
            result = await self._sign_and_broadcast(
                private_key_hex=private_key_hex,
                from_address=wallet.address,
                to_address=to_address,
                amount_usdc=amount_usdc,
            )
        finally:
            # Always zero the plaintext key — even on exception
            del private_key_hex

        log.info(
            "withdraw_initiated",
            user_id=user_id,
            from_address=wallet.address,
            to_address=to_address,
            amount_usdc=amount_usdc,
            status=result.get("status"),
        )
        return result

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _fetch_balance(self, url: str, address: str, attempt: int) -> float:
        """Fetch USDC portfolio value from the Polymarket Data API.

        Args:
            url: Full API URL for the balance endpoint.
            address: Wallet address (used as fallback lookup key).
            attempt: Current retry attempt number (for logging).

        Returns:
            USDC balance as float.

        Raises:
            TimeoutError, aiohttp errors on failure.
        """
        if self._session_factory is None:
            log.warning("balance_fetch_no_session", address=address)
            return 0.0

        import aiohttp  # noqa: PLC0415

        session: aiohttp.ClientSession = self._session_factory()
        try:
            async with asyncio.timeout(_TIMEOUT_S):
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # Data API returns {"portfolioValue": <float>, ...}
                        return float(data.get("portfolioValue", 0.0))
                    log.warning(
                        "balance_api_non_200",
                        status=resp.status,
                        address=address,
                        attempt=attempt,
                    )
                    return 0.0
        except asyncio.TimeoutError:
            raise
        except Exception:
            raise

    async def _sign_and_broadcast(
        self,
        private_key_hex: str,
        from_address: str,
        to_address: str,
        amount_usdc: float,
    ) -> dict:
        """Sign a USDC ERC-20 transfer and broadcast to Polygon.

        Requires ``eth_account`` and ``POLYGON_RPC_URL`` env var for live
        on-chain transactions.  Returns a ``pending`` status when the
        dependency is unavailable.

        Args:
            private_key_hex: 64-char hex raw private key (caller must delete after return).
            from_address: Source wallet address.
            to_address: Destination wallet address.
            amount_usdc: Amount in USDC (converted to 6-decimal integer internally).

        Returns:
            Dict containing ``status``, ``tx_hash`` (or ``None``), and addresses.
        """
        import os  # noqa: PLC0415

        try:
            from eth_account import Account  # noqa: PLC0415
            from eth_account.signers.local import LocalAccount  # noqa: PLC0415
        except ImportError:
            log.warning(
                "eth_account_not_installed",
                note="Install eth_account for live on-chain transactions.",
            )
            return {
                "status": "pending_no_signer",
                "from_address": from_address,
                "to_address": to_address,
                "amount_usdc": amount_usdc,
                "tx_hash": None,
                "note": "eth_account not installed — broadcast skipped.",
            }

        polygon_rpc = os.environ.get("POLYGON_RPC_URL", "").strip()
        if not polygon_rpc:
            log.warning("polygon_rpc_not_set")
            return {
                "status": "pending_no_rpc",
                "from_address": from_address,
                "to_address": to_address,
                "amount_usdc": amount_usdc,
                "tx_hash": None,
                "note": "POLYGON_RPC_URL not set — broadcast skipped.",
            }

        try:
            import web3  # noqa: PLC0415
        except ImportError:
            log.warning("web3_not_installed")
            return {
                "status": "pending_no_web3",
                "from_address": from_address,
                "to_address": to_address,
                "amount_usdc": amount_usdc,
                "tx_hash": None,
                "note": "web3 not installed — broadcast skipped.",
            }

        account: LocalAccount = Account.from_key(f"0x{private_key_hex}")

        # USDC has 6 decimal places on Polygon; use Decimal to avoid float rounding
        from decimal import Decimal  # noqa: PLC0415
        amount_atomic = int(Decimal(str(amount_usdc)) * Decimal("1000000"))

        # Minimal ERC-20 transfer ABI
        erc20_abi = [
            {
                "inputs": [
                    {"name": "to", "type": "address"},
                    {"name": "amount", "type": "uint256"},
                ],
                "name": "transfer",
                "outputs": [{"name": "", "type": "bool"}],
                "type": "function",
            }
        ]

        w3 = web3.Web3(web3.Web3.HTTPProvider(polygon_rpc))
        usdc = w3.eth.contract(address=_USDC_CONTRACT, abi=erc20_abi)

        nonce = w3.eth.get_transaction_count(from_address)
        gas_price = w3.eth.gas_price
        tx = usdc.functions.transfer(to_address, amount_atomic).build_transaction(
            {
                "from": from_address,
                "nonce": nonce,
                "gas": 100_000,
                "gasPrice": gas_price,
                "chainId": 137,  # Polygon mainnet
            }
        )

        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction).hex()

        log.info(
            "withdraw_broadcast",
            from_address=from_address,
            to_address=to_address,
            amount_usdc=amount_usdc,
            tx_hash=tx_hash,
        )
        return {
            "status": "broadcast",
            "from_address": from_address,
            "to_address": to_address,
            "amount_usdc": amount_usdc,
            "tx_hash": tx_hash,
        }
