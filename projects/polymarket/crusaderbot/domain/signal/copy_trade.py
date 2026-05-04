"""Copy-trade strategy: mirror trades from configured target wallets."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from ...database import get_pool
from ...integrations.polymarket import get_user_activity
from .base import BaseStrategy, SignalCandidate

logger = logging.getLogger(__name__)


class CopyTradeStrategy(BaseStrategy):
    name = "copy_trade"

    async def scan(self, user: dict, settings: dict) -> list[SignalCandidate]:
        pool = get_pool()
        async with pool.acquire() as conn:
            targets = await conn.fetch(
                "SELECT id, wallet_address, scale_factor, last_seen_tx "
                "FROM copy_targets WHERE user_id=$1 AND enabled=TRUE",
                user["id"],
            )
        if not targets:
            return []

        out: list[SignalCandidate] = []
        capital_pct = Decimal(str(settings.get("capital_alloc_pct") or 0.5))
        balance = Decimal(str(user.get("balance_usdc") or 0))
        budget = balance * capital_pct

        for t in targets:
            try:
                trades = await get_user_activity(t["wallet_address"], limit=10)
            except Exception as exc:
                logger.warning("copy_trade scan err for %s: %s",
                               t["wallet_address"], exc)
                continue
            new_last_tx = t["last_seen_tx"]
            for trade in trades:
                tx = trade.get("transactionHash") or trade.get("tx_hash")
                if t["last_seen_tx"] and tx == t["last_seen_tx"]:
                    break  # caught up
                market_id = (trade.get("market") or trade.get("conditionId")
                             or trade.get("market_id"))
                side = (trade.get("outcome") or trade.get("side") or "yes").lower()
                if side not in ("yes", "no"):
                    side = "yes" if side in ("buy", "long") else "no"
                price = float(trade.get("price") or 0.5)
                size_raw = float(trade.get("size") or trade.get("usdcSize") or 0)
                if not market_id or size_raw <= 0:
                    continue
                scale = Decimal(str(t["scale_factor"]))
                size_usdc = min(Decimal(str(size_raw)) * scale, budget)
                if size_usdc <= 0:
                    continue
                out.append(SignalCandidate(
                    market_id=str(market_id),
                    side=side,
                    size_usdc=size_usdc,
                    price=price,
                    edge_bps=None,
                    strategy_type=self.name,
                    signal_ts=datetime.now(timezone.utc),
                    extra={"target": t["wallet_address"], "src_tx": tx},
                ))
                if new_last_tx is None or new_last_tx == t["last_seen_tx"]:
                    new_last_tx = tx

            if new_last_tx and new_last_tx != t["last_seen_tx"]:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE copy_targets SET last_seen_tx=$1 WHERE id=$2",
                        new_last_tx, t["id"],
                    )
        return out
