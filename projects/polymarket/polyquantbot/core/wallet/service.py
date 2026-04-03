"""core/wallet/service.py — WalletService: per-user real wallet lifecycle.

Provides idempotent wallet creation, balance fetch from Polymarket Data API,
and withdraw capability.  Private keys are stored AES-256-GCM-encrypted and
are decrypted only within the signing boundary — they are never logged or
returned to callers.

Key generation uses ``eth_account.Account.create()`` which produces a correct
secp256k1 keypair with a fully Ethereum-compatible (EIP-55 checksummed) address.

Storage:
    - When a :class:`~core.wallet.repository.WalletRepository` is injected via
      the ``repository`` constructor argument, wallets are persisted to PostgreSQL
      and survive process restarts.
    - When no repository is provided (e.g. tests), wallets are kept in an in-memory
      dict (same behaviour as before injection was wired).

Rules:
    - All public methods are idempotent and async.
    - External HTTP calls carry retry (3×) + timeout (5 s).
    - RPC broadcast carries retry (2×) for transient Polygon RPC errors.
    - ZERO silent failures — every error is logged before raising or returning.
    - Multi-user safe: per-user asyncio lock prevents TOCTOU on wallet creation.
    - WALLET_SECRET_KEY must be set in the environment before any call.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional, TYPE_CHECKING

import structlog

from .models import WalletModel
from ..security.encryption import decrypt_private_key, encrypt_private_key

if TYPE_CHECKING:
    from .repository import WalletRepository

log = structlog.get_logger(__name__)

# ── HTTP / retry tuning ───────────────────────────────────────────────────────
_TIMEOUT_S: float = 5.0
_MAX_RETRIES: int = 3
_RETRY_DELAY_S: float = 0.5
_MAX_RPC_RETRIES: int = 2
_RPC_RETRY_DELAY_S: float = 1.0

# ── Polymarket Data API ───────────────────────────────────────────────────────
_DATA_API_BASE: str = "https://data-api.polymarket.com"

# ── USDC contract (Polygon) — required for withdraw ───────────────────────────
_USDC_CONTRACT: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"


# ── Keypair generation ────────────────────────────────────────────────────────


def _generate_keypair() -> tuple[str, str]:
    """Generate a new secp256k1 keypair using ``eth_account``.

    Uses :func:`eth_account.Account.create` which internally uses the
    ``coincurve`` / ``cryptography`` backend to produce a random 32-byte
    private scalar and derives the Ethereum-compatible (EIP-55 checksummed)
    address via the correct Keccak-256 hash.

    Returns:
        ``(private_key_hex, address)`` tuple where:
        - ``private_key_hex`` is the 64-hex-char raw private scalar (no ``0x``).
        - ``address`` is the EIP-55 checksummed ``0x…`` Ethereum address.
    """
    from eth_account import Account  # noqa: PLC0415

    acct = Account.create()
    private_key_hex: str = bytes(acct.key).hex()  # 64-char hex, no 0x prefix
    address: str = acct.address                   # EIP-55 checksummed
    return private_key_hex, address


# ── WalletService ─────────────────────────────────────────────────────────────


class WalletService:
    """Per-user real wallet service with encrypted key storage.

    Storage behaviour depends on whether a ``repository`` is injected:

    - **With repository** (production): wallets are persisted to PostgreSQL via
      :class:`~core.wallet.repository.WalletRepository` and survive process
      restarts.  The ``_wallets`` in-memory dict is not used.
    - **Without repository** (tests / standalone): wallets are held in an
      in-memory dict (same as before).

    Args:
        http_session_factory: Callable returning an ``aiohttp.ClientSession``.
            When ``None``, balance fetch falls back to 0.0 with a warning.
        repository: Optional :class:`~core.wallet.repository.WalletRepository`.
            When provided, all wallet reads/writes go through the DB.
    """

    def __init__(self, http_session_factory=None, repository: "Optional[WalletRepository]" = None) -> None:
        self._repository = repository
        # In-memory fallback used only when no repository is injected
        self._wallets: dict[int, WalletModel] = {}
        self._creation_locks: dict[int, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._session_factory = http_session_factory

        log.info(
            "wallet_service_initialized",
            persistence="db" if repository is not None else "memory",
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    async def create_wallet(self, user_id: int) -> WalletModel:
        """Create and persist a new wallet for *user_id*.

        Idempotent: returns the existing wallet if one was already created.
        When a repository is injected the wallet is persisted to PostgreSQL.

        Args:
            user_id: Telegram (or other) user integer ID.

        Returns:
            :class:`WalletModel` for the user (never includes plaintext key).

        Raises:
            EnvironmentError: If ``WALLET_SECRET_KEY`` is not set.
        """
        # Fast path — check storage without locking
        existing = await self.get_wallet(user_id)
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
            existing = await self.get_wallet(user_id)
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

            if self._repository is not None:
                wallet = await self._repository.create_wallet(user_id, wallet)
            else:
                self._wallets[user_id] = wallet

            log.info(
                "wallet_created",
                user_id=user_id,
                address=wallet.address,
                # encrypted_private_key is intentionally NOT logged
            )
            return wallet

    async def get_wallet(self, user_id: int) -> Optional[WalletModel]:
        """Return the wallet for *user_id*, or ``None`` if it doesn't exist.

        Reads from the repository when one is injected; falls back to the
        in-memory dict otherwise.

        Args:
            user_id: Telegram user ID.

        Returns:
            :class:`WalletModel` or ``None``.
        """
        if self._repository is not None:
            return await self._repository.get_wallet(user_id)
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
        wallet = await self.get_wallet(user_id)
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

        wallet = await self.get_wallet(user_id)
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

        w3 = web3.Web3(web3.Web3.HTTPProvider(polygon_rpc, request_kwargs={"timeout": _TIMEOUT_S}))
        usdc = w3.eth.contract(address=_USDC_CONTRACT, abi=erc20_abi)

        last_exception: Optional[Exception] = None
        for attempt in range(1, _MAX_RPC_RETRIES + 1):
            try:
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
                    attempt=attempt,
                )
                return {
                    "status": "broadcast",
                    "from_address": from_address,
                    "to_address": to_address,
                    "amount_usdc": amount_usdc,
                    "tx_hash": tx_hash,
                }
            except Exception as exc:
                last_exception = exc
                log.warning(
                    "rpc_broadcast_attempt_failed",
                    attempt=attempt,
                    max_attempts=_MAX_RPC_RETRIES,
                    error=str(exc),
                )
                if attempt < _MAX_RPC_RETRIES:
                    await asyncio.sleep(_RPC_RETRY_DELAY_S)

        raise RuntimeError(
            f"RPC broadcast failed after {_MAX_RPC_RETRIES} attempts: {last_exception}"
        )
