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
# When a Transfer log misses the in-memory address map, force one refresh —
# but at most this often, to bound DB load if the chain spams unrelated
# transfers to the watched USDC contract.
ADDRESS_MISS_REFRESH_DEBOUNCE_SECONDS = 5.0


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
        self._last_miss_refresh_ts: float = 0.0
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

    async def _refresh_on_miss(self) -> None:
        """Force an address-map refresh when a Transfer hits an unknown `to`.

        The 60s periodic refresh leaves a window where a freshly provisioned
        wallet's first deposit can hit before the map sees it; eth_subscribe
        will not replay that log, so silently dropping it is a permanent
        missed credit. We refresh on miss but debounce so unrelated transfers
        in busy blocks cannot pin the DB.
        """
        loop = asyncio.get_event_loop()
        now = loop.time()
        if now - self._last_miss_refresh_ts < ADDRESS_MISS_REFRESH_DEBOUNCE_SECONDS:
            return
        self._last_miss_refresh_ts = now
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
                    pre_ack = await self._subscribe(ws)
                    backoff = INITIAL_BACKOFF_SECONDS
                    log.info("deposit_watcher.connected",
                             host=self._ws_host(),
                             sub_id=self._sub_id,
                             pre_ack_buffered=len(pre_ack))
                    for log_obj in pre_ack:
                        try:
                            await self._handle_log(log_obj)
                        except Exception as exc:
                            log.error(
                                "deposit_watcher.pre_ack_replay_failed",
                                error=str(exc),
                                error_type=type(exc).__name__,
                                tx_hash=log_obj.get("transactionHash"),
                            )
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

    async def _subscribe(
        self, ws: "websockets.WebSocketClientProtocol"
    ) -> list[dict]:
        """Send eth_subscribe and wait for the subscription ack.

        Returns any log frames that arrived before the ack (pre-ack buffer).
        On high-frequency chains like Polygon, a Transfer event can legally
        arrive in the same read-loop iteration as the subscribe request — the
        old code dropped those frames silently. Callers must replay the
        returned frames through `_handle_log` before entering `_consume`.
        """
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
        pre_ack_buffer: list[dict] = []
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            if "result" in msg and msg.get("id") == 1:
                self._sub_id = msg["result"]
                return pre_ack_buffer
            if "error" in msg:
                raise RuntimeError(
                    f"eth_subscribe failed: {msg['error']}"
                )
            # Notification arrived before the ack — buffer it for post-subscribe
            # replay so no deposit event is silently dropped.
            if msg.get("method") == "eth_subscription":
                params = msg.get("params") or {}
                log_obj = params.get("result")
                if isinstance(log_obj, dict):
                    pre_ack_buffer.append(log_obj)
                    log.info(
                        "deposit_watcher.pre_ack_log_buffered",
                        tx_hash=log_obj.get("transactionHash"),
                        buffered_count=len(pre_ack_buffer),
                    )

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
            log.debug(
                "deposit_watcher.reorg_skip",
                tx_hash=log_obj.get("transactionHash"),
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
            # Unknown `to` — could be a brand-new wallet provisioned since the
            # last periodic refresh. Force a debounced refresh and re-check
            # before discarding, otherwise we permanently lose first-deposit
            # credits during the 60s refresh window.
            await self._refresh_on_miss()
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

        log_index_hex = log_obj.get("logIndex", "0x0")
        try:
            log_index = int(log_index_hex, 16)
        except (TypeError, ValueError):
            log_index = 0

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
        """Atomic deposit insert + ledger credit + tier bump, then best-effort
        Telegram notification.

        Idempotency is enforced by `UNIQUE (tx_hash, log_index)` on the
        `deposits` table — a single EVM tx can emit multiple Transfer events
        distinguished by `log_index`, and the previous tx_hash-only key
        silently collapsed them into one credit.

        The deposit row insert, sub-account upsert, ledger entry insert, and
        tier bump all run inside one DB transaction. A partial-success window
        is unacceptable: a deposit recorded without its ledger credit would
        be skipped forever by ON CONFLICT on retry, and a credit recorded
        without its tier bump would leave a funded user stuck below the
        Tier 3 gate. Failure of any step rolls back all of them.
        """
        deposit_id: Optional[UUID] = None
        promoted = False
        balance = Decimal("0")

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
                deposit_id = deposit_row["id"]

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
                        raise RuntimeError(
                            f"sub_account upsert returned no row for "
                            f"user_id={user_id}"
                        )

                await ledger.credit(
                    self._pool,
                    sub_account_id,
                    amount,
                    deposit_id,
                    type=ledger.ENTRY_TYPE_DEPOSIT,
                    conn=conn,
                )

                balance = await ledger.get_balance(
                    self._pool, user_id, conn=conn,
                )
                threshold = Decimal(str(self._config.MIN_DEPOSIT_USDC))
                if balance >= threshold:
                    current_tier = await conn.fetchval(
                        "SELECT access_tier FROM users WHERE id=$1 "
                        "FOR UPDATE",
                        user_id,
                    )
                    if current_tier is None:
                        # Wallet matched in-process but the user row vanished
                        # — refuse to credit a ghost account.
                        raise RuntimeError(
                            f"user row missing for tier bump: {user_id}"
                        )
                    if current_tier < TIER_FUNDED:
                        await bump_tier(
                            self._pool,
                            user_id=user_id,
                            new_tier=TIER_FUNDED,
                            actor_role="deposit_watcher",
                            conn=conn,
                        )
                        promoted = True

        log.info(
            "deposit_watcher.deposit_credited",
            deposit_id=str(deposit_id),
            user_id=str(user_id),
            tx_hash=tx_hash,
            log_index=log_index,
            amount=str(amount),
            block_number=block_number,
            promoted=promoted,
            balance=str(balance),
        )

        # Notification is best-effort and intentionally outside the txn —
        # a Telegram outage must not roll back a confirmed credit.
        await self._notify_user(
            telegram_user_id=telegram_user_id,
            amount=amount,
            balance=balance,
            promoted=promoted,
        )

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
