"""Polygon USDC deposit watcher (Alchemy WebSocket, eth_subscribe logs).

Architecture
------------
A single asyncio background task subscribes via Alchemy WebSocket to all
USDC `Transfer` events on Polygon. Incoming logs are filtered in-process
against the in-memory map of `deposit_address -> (user_id, telegram_user_id)`
loaded from the `wallets` + `users` tables. Confirmed transfers are written
to the existing `deposits` table (UNIQUE(tx_hash) gives idempotency), credited
to the user's sub-account ledger, and surfaced via Telegram notification.
The user's `access_tier` is bumped to Tier 3 on first balance >= MIN_DEPOSIT_USDC.

Reconnect with exponential backoff is mandatory — the WS is the only data
source for deposit detection; a silent disconnect would leave users uncredited.

Paper-mode: the watcher reads on-chain events but does not initiate any
on-chain action. Sweeping deposits to the hot pool is deferred to a later lane.
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Optional
from uuid import UUID

import asyncpg
import structlog
import websockets
from telegram.ext import Application

from ..config import Settings
from . import ledger
from .user_service import bump_tier

log = structlog.get_logger(__name__)

# Tier promoted on first confirmed deposit >= MIN_DEPOSIT_USDC.
TIER_FUNDED = 3
TIER_FUNDED_LABEL = "Tier 3 — Funded beta"

# keccak256("Transfer(address,address,uint256)")
USDC_TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)
USDC_DECIMALS = 6
USDC_DECIMAL_FACTOR = Decimal(10) ** USDC_DECIMALS

# Reconnect / refresh cadence.
INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 60.0
ADDRESS_REFRESH_SECONDS = 60.0


def _topic_to_address(topic_hex: str) -> str:
    """Decode an EVM `address` from a 32-byte log topic to lowercase 0x-prefixed hex."""
    if not topic_hex.startswith("0x") or len(topic_hex) != 66:
        raise ValueError(f"invalid topic: {topic_hex!r}")
    return "0x" + topic_hex[-40:].lower()


def _parse_amount_usdc(data_hex: str) -> Decimal:
    """Decode a uint256 USDC `value` from log `data`, scaled by 1e-6."""
    if not data_hex.startswith("0x"):
        raise ValueError(f"invalid log data: {data_hex!r}")
    raw = int(data_hex, 16)
    return Decimal(raw) / USDC_DECIMAL_FACTOR


class DepositWatcher:
    """Subscribes to USDC `Transfer` logs and credits matching deposits.

    One instance per process. Lifecycle: `start()` schedules the background
    task; `stop()` cancels it and waits for clean exit.
    """

    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        bot_app: Application,
        config: Settings,
    ) -> None:
        self._pool = pool
        self._bot_app = bot_app
        self._config = config
        self._task: Optional[asyncio.Task[None]] = None
        self._stop_event = asyncio.Event()
        # address (lowercase 0x-hex) -> (user_id, telegram_user_id)
        self._address_map: dict[str, tuple[UUID, int]] = {}
        self._address_map_lock = asyncio.Lock()
        self._last_refresh_ts: float = 0.0
        self._sub_id: Optional[str] = None

    # ---- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        await self._refresh_address_map()
        self._task = asyncio.create_task(
            self._run(), name="deposit_watcher"
        )
        log.info(
            "deposit_watcher.started",
            ws_url_host=self._ws_host(),
            usdc_contract=self._config.USDC_CONTRACT_ADDRESS,
            min_deposit_usdc=self._config.MIN_DEPOSIT_USDC,
            tracked_addresses=len(self._address_map),
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None
        log.info("deposit_watcher.stopped")

    def _ws_host(self) -> str:
        # Strip subscription path/key from logs to avoid leaking the API key.
        url = self._config.ALCHEMY_POLYGON_WS_URL
        try:
            return url.split("/v2/", 1)[0]
        except Exception:
            return "<unparseable>"

    # ---- address registry ------------------------------------------------

    async def _refresh_address_map(self) -> None:
        """Reload the deposit_address -> (user_id, telegram_user_id) map."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT w.user_id, w.deposit_address, u.telegram_user_id "
                "FROM wallets w JOIN users u ON u.id = w.user_id"
            )
        new_map: dict[str, tuple[UUID, int]] = {
            row["deposit_address"].lower(): (
                row["user_id"], row["telegram_user_id"]
            )
            for row in rows
        }
        async with self._address_map_lock:
            self._address_map = new_map
        loop = asyncio.get_event_loop()
        self._last_refresh_ts = loop.time()
        log.info("deposit_watcher.addresses_refreshed",
                 tracked_addresses=len(new_map))

    async def _maybe_refresh_addresses(self) -> None:
        loop = asyncio.get_event_loop()
        if loop.time() - self._last_refresh_ts >= ADDRESS_REFRESH_SECONDS:
            await self._refresh_address_map()

    async def _lookup(self, address: str) -> Optional[tuple[UUID, int]]:
        async with self._address_map_lock:
            return self._address_map.get(address)

    # ---- main loop -------------------------------------------------------

    async def _run(self) -> None:
        backoff = INITIAL_BACKOFF_SECONDS
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(
                    self._config.ALCHEMY_POLYGON_WS_URL,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                ) as ws:
                    await self._subscribe(ws)
                    backoff = INITIAL_BACKOFF_SECONDS
                    log.info("deposit_watcher.connected",
                             host=self._ws_host(),
                             sub_id=self._sub_id)
                    await self._consume(ws)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning(
                    "deposit_watcher.disconnected",
                    error=str(exc),
                    error_type=type(exc).__name__,
                    backoff_seconds=backoff,
                )
            self._sub_id = None
            if self._stop_event.is_set():
                return
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=backoff
                )
                return
            except asyncio.TimeoutError:
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    async def _subscribe(self, ws: "websockets.WebSocketClientProtocol") -> None:
        sub_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": [
                "logs",
                {
                    "address": self._config.USDC_CONTRACT_ADDRESS,
                    # topics[0] = Transfer; topics[1] = from (any); topics[2] = to (any).
                    # We filter `to` in-process against the address map so newly
                    # provisioned wallets are picked up by refresh, no resub.
                    "topics": [USDC_TRANSFER_TOPIC],
                },
            ],
        }
        await ws.send(json.dumps(sub_req))
        # Subscription handshake — first message is the {result: sub_id} ack.
        # We tolerate the ack arriving interleaved with an early notification
        # by scanning until we see a frame carrying `result`.
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            if "result" in msg and msg.get("id") == 1:
                self._sub_id = msg["result"]
                return
            if "error" in msg:
                raise RuntimeError(
                    f"eth_subscribe failed: {msg['error']}"
                )
            # An unexpected notification before ack — drop it; resubscribe will
            # re-deliver via the chain head if the WS truly skipped frames.

    async def _consume(self, ws: "websockets.WebSocketClientProtocol") -> None:
        while not self._stop_event.is_set():
            raw = await ws.recv()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError as exc:
                log.warning("deposit_watcher.bad_json",
                            error=str(exc), preview=raw[:200])
                continue
            if msg.get("method") != "eth_subscription":
                # Ignore non-subscription frames (heartbeats, ack echoes).
                continue
            params = msg.get("params") or {}
            if params.get("subscription") != self._sub_id:
                continue
            log_obj = params.get("result")
            if not isinstance(log_obj, dict):
                continue
            try:
                await self._handle_log(log_obj)
            except Exception as exc:
                # Per-event isolation: a single bad log MUST NOT kill the loop.
                log.error(
                    "deposit_watcher.handle_log_failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                    tx_hash=log_obj.get("transactionHash"),
                )

            await self._maybe_refresh_addresses()

    # ---- credit path -----------------------------------------------------

    async def _handle_log(self, log_obj: dict) -> None:
        # Reorg gate: chain reorganizations re-emit affected logs with
        # `removed: true`. We refuse to credit those — reversing an already-
        # credited deposit on reorg is a deferred enhancement (a confirmation-
        # delay model is the cleaner long-term fix and is out of R4 scope).
        if log_obj.get("removed") is True:
            log.warning(
                "deposit_watcher.removed_log_skipped",
                tx_hash=log_obj.get("transactionHash"),
                log_index=log_obj.get("logIndex"),
                block_number=log_obj.get("blockNumber"),
            )
            return

        topics = log_obj.get("topics") or []
        if len(topics) < 3 or topics[0].lower() != USDC_TRANSFER_TOPIC:
            return
        try:
            to_addr = _topic_to_address(topics[2])
        except ValueError as exc:
            log.warning("deposit_watcher.bad_topic", error=str(exc))
            return

        match = await self._lookup(to_addr)
        if match is None:
            return

        user_id, telegram_user_id = match
        try:
            amount = _parse_amount_usdc(log_obj.get("data", "0x0"))
        except ValueError as exc:
            log.warning("deposit_watcher.bad_amount", error=str(exc),
                        tx_hash=log_obj.get("transactionHash"))
            return
        if amount <= 0:
            return

        tx_hash = log_obj.get("transactionHash")
        if not isinstance(tx_hash, str):
            log.warning("deposit_watcher.missing_tx_hash", log=log_obj)
            return

        log_index_hex = log_obj.get("logIndex")
        try:
            log_index = int(log_index_hex, 16) if log_index_hex is not None else None
        except (TypeError, ValueError):
            log_index = None
        if log_index is None:
            # Without a logIndex we cannot dedupe two Transfer events emitted
            # by the same EVM tx — refuse rather than silently collapse them.
            log.warning("deposit_watcher.missing_log_index",
                        tx_hash=tx_hash)
            return

        block_number_hex = log_obj.get("blockNumber")
        block_number: Optional[int]
        try:
            block_number = int(block_number_hex, 16) if block_number_hex else None
        except (TypeError, ValueError):
            block_number = None

        await self._credit_deposit(
            user_id=user_id,
            telegram_user_id=telegram_user_id,
            tx_hash=tx_hash,
            log_index=log_index,
            amount=amount,
            block_number=block_number,
        )

    async def _credit_deposit(
        self,
        *,
        user_id: UUID,
        telegram_user_id: int,
        tx_hash: str,
        log_index: int,
        amount: Decimal,
        block_number: Optional[int],
    ) -> None:
        """Atomic deposit insert + sub-account ensure + ledger credit, then
        out-of-band tier bump + Telegram notification.

        Idempotency is enforced by `UNIQUE (tx_hash, log_index)` on the
        `deposits` table — a single EVM tx can emit multiple Transfer events
        distinguished by `log_index`, and the previous tx_hash-only key
        silently collapsed them into one credit. The deposit row insert,
        sub-account upsert, and ledger entry insert all run inside one DB
        transaction so a partial-success window cannot leave a deposit
        recorded with no matching ledger credit (which would then be skipped
        forever by ON CONFLICT on retry).
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                deposit_row = await conn.fetchrow(
                    "INSERT INTO deposits "
                    "(user_id, tx_hash, log_index, amount_usdc, block_number, "
                    " confirmed_at) "
                    "VALUES ($1, $2, $3, $4, $5, NOW()) "
                    "ON CONFLICT (tx_hash, log_index) DO NOTHING RETURNING id",
                    user_id, tx_hash, log_index, amount, block_number,
                )
                if deposit_row is None:
                    log.info(
                        "deposit_watcher.duplicate_skipped",
                        tx_hash=tx_hash,
                        log_index=log_index,
                        user_id=str(user_id),
                    )
                    return
                deposit_id: UUID = deposit_row["id"]

                sub_row = await conn.fetchrow(
                    "INSERT INTO sub_accounts (user_id) VALUES ($1) "
                    "ON CONFLICT (user_id) DO NOTHING RETURNING id",
                    user_id,
                )
                if sub_row is not None:
                    sub_account_id: UUID = sub_row["id"]
                else:
                    sub_account_id = await conn.fetchval(
                        "SELECT id FROM sub_accounts WHERE user_id=$1",
                        user_id,
                    )
                    if sub_account_id is None:
                        # Should be unreachable: ON CONFLICT means a row
                        # exists. Raise to roll back the transaction so the
                        # deposit row is not orphaned.
                        raise RuntimeError(
                            f"sub_account upsert returned no row for "
                            f"user_id={user_id}"
                        )

                await conn.execute(
                    "INSERT INTO ledger_entries "
                    "(sub_account_id, type, amount_usdc, ref_id) "
                    "VALUES ($1, $2, $3, $4)",
                    sub_account_id,
                    ledger.ENTRY_TYPE_DEPOSIT,
                    amount,
                    deposit_id,
                )

        log.info(
            "deposit_watcher.deposit_credited",
            deposit_id=str(deposit_id),
            user_id=str(user_id),
            tx_hash=tx_hash,
            log_index=log_index,
            amount=str(amount),
            block_number=block_number,
        )

        # Out of transaction:
        #  - bump_tier opens its own transaction (SELECT FOR UPDATE +
        #    UPDATE + audit INSERT) — composing into the deposit txn would
        #    extend lock scope unnecessarily.
        #  - notify is best-effort and must not roll back a confirmed credit.
        balance = await ledger.get_balance(self._pool, user_id)
        promoted = await self._maybe_promote_tier(
            user_id=user_id, balance=balance,
        )
        await self._notify_user(
            telegram_user_id=telegram_user_id,
            amount=amount,
            balance=balance,
            promoted=promoted,
        )

    async def _maybe_promote_tier(
        self, *, user_id: UUID, balance: Decimal,
    ) -> bool:
        """If balance >= MIN_DEPOSIT_USDC and current tier < 3, bump to 3."""
        threshold = Decimal(str(self._config.MIN_DEPOSIT_USDC))
        if balance < threshold:
            return False
        async with self._pool.acquire() as conn:
            current_tier = await conn.fetchval(
                "SELECT access_tier FROM users WHERE id=$1", user_id,
            )
        if current_tier is None:
            log.warning("deposit_watcher.user_missing_for_tier_bump",
                        user_id=str(user_id))
            return False
        if current_tier >= TIER_FUNDED:
            return False
        try:
            await bump_tier(
                self._pool,
                user_id=user_id,
                new_tier=TIER_FUNDED,
                actor_role="deposit_watcher",
            )
        except Exception as exc:
            log.error(
                "deposit_watcher.tier_bump_failed",
                user_id=str(user_id),
                error=str(exc),
            )
            return False
        return True

    async def _notify_user(
        self,
        *,
        telegram_user_id: int,
        amount: Decimal,
        balance: Decimal,
        promoted: bool,
    ) -> None:
        tier_line = (
            f"Access tier: {TIER_FUNDED_LABEL}"
            if promoted
            else "Access tier: unchanged"
        )
        text = (
            f"💰 Deposit confirmed: +${amount:.2f} USDC\n"
            f"Your balance: ${balance:.2f} USDC\n"
            f"{tier_line}"
        )
        try:
            await self._bot_app.bot.send_message(
                chat_id=telegram_user_id, text=text,
            )
        except Exception as exc:
            log.warning(
                "deposit_watcher.notify_failed",
                telegram_user_id=telegram_user_id,
                error=str(exc),
            )
