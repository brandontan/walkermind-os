"""Lane 1C demo data seeder.

Populates the CrusaderBot database with a self-contained demo dataset
behind the ``is_demo`` flag introduced by migration 014. The script is
operator-executed (NEVER wired to startup) and refuses to run unless
``DEMO_SEED_ALLOW=1`` is set. Re-running the script is a no-op once the
demo dataset is fully in place; partial states are completed via ON
CONFLICT DO NOTHING upserts on deterministic IDs.

Seed contents
-------------
* 12 demo markets (id prefix ``demo-market-``) - is_demo=TRUE so cleanup
  removes them without touching real Polymarket markets.
* 2 demo signal feeds (operator_id = Boss UUID resolved from
  OPERATOR_CHAT_ID): "Polymarket Politics Watcher" (conservative) +
  "Polymarket Sports Edge" (moderate).
* 2 demo users with telegram_user_id = -1 and -2 (negative IDs are
  outside Telegram's positive-only ID space, so no real account can
  collide). Tier 3 (FUNDED) so /signals + /pnl render. auto_trade_on
  remains FALSE - no execution loop will pick these users up.
* Demo wallets per user with paper balance_usdc = 10000.00 and
  obviously-fake deposit addresses (``0xDEMO...``). hd_index uses the
  999_999_xxx range so it cannot collide with the live HD counter.
* Subscriptions: demo user 1 -> Feed 1 only; demo user 2 -> both feeds.
* 10 signal_publications spread across the last 12 hours with
  confidence scores 0.55-0.85 stored in payload.confidence.
* 7 days of paper-trade history (~58% win rate, weighted toward recent
  days). Each closed position gets a matching ledger ``trade_close`` row
  so daily_pnl() returns a non-trivial number for today.

Run
---
    DEMO_SEED_ALLOW=1 python -m projects.polymarket.crusaderbot.scripts.seed_demo_data

Exit codes
----------
    0  seed applied (or already present, no-op)
    2  guard env var missing
    3  prerequisite missing (migration not applied / no boss user)
    4  database error
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import asyncpg

logger = logging.getLogger("crusaderbot.demo.seed")

DEMO_NS = uuid.UUID("00000000-0000-0000-0000-000000000d10")  # stable namespace

DEMO_USER_TELEGRAM_IDS = (-1, -2)
DEMO_WALLET_ADDRESSES = (
    "0xDEMO00000000000000000000000000000000001",
    "0xDEMO00000000000000000000000000000000002",
)
DEMO_HD_INDICES = (999_999_001, 999_999_002)
DEMO_PAPER_BALANCE = Decimal("10000.00")

FEED_SPECS = (
    {
        "slug": "demo-politics-watcher",
        "name": "Polymarket Politics Watcher",
        "description": "Conservative political markets — long-horizon edge.",
        "risk_profile_hint": "conservative",
    },
    {
        "slug": "demo-sports-edge",
        "name": "Polymarket Sports Edge",
        "description": "Moderate-aggression sports props with tight TP/SL.",
        "risk_profile_hint": "moderate",
    },
)

# Markets cover politics/sports/crypto/macro so /signals catalog reads
# realistic across both feeds. Prices kept inside (0.05, 0.95) to stay
# within typical Polymarket microstructure.
DEMO_MARKETS: tuple[dict[str, Any], ...] = tuple(
    {
        "id": f"demo-market-{i:03d}",
        "slug": f"demo-market-{i:03d}",
        "question": q,
        "category": cat,
        "yes_price": yes,
        "no_price": round(1.0 - yes, 4),
        "yes_token_id": f"demo-yes-{i:03d}",
        "no_token_id": f"demo-no-{i:03d}",
        "liquidity_usdc": 75_000.00 + i * 1500,
    }
    for i, (q, cat, yes) in enumerate(
        [
            ("Will the next US election turnout exceed 65%?", "politics", 0.41),
            ("Will the Senate flip in the 2026 midterms?", "politics", 0.38),
            ("Will a third-party candidate poll above 8% in Q3?", "politics", 0.27),
            ("Will Lakers reach the 2026 NBA Finals?", "sports", 0.22),
            ("Will Real Madrid win the UCL final?", "sports", 0.46),
            ("Will Verstappen win the F1 drivers' championship?", "sports", 0.61),
            ("Will BTC close above $80k by month end?", "crypto", 0.54),
            ("Will ETH/BTC ratio break 0.06 this quarter?", "crypto", 0.34),
            ("Will US CPI print below 3.0% next release?", "macro", 0.49),
            ("Will Fed cut rates at the next FOMC?", "macro", 0.31),
            ("Will Brent crude average below $70 this month?", "macro", 0.43),
            ("Will the AI bill pass the House this session?", "politics", 0.29),
        ],
        start=1,
    )
)


def _det_uuid(label: str) -> uuid.UUID:
    """Stable UUID derived from the demo namespace + ``label``.

    Reused on every seed run so ON CONFLICT DO NOTHING upserts make the
    script truly idempotent. Never use these IDs for production data.
    """
    return uuid.uuid5(DEMO_NS, label)


async def _ensure_is_demo_columns(conn: asyncpg.Connection) -> None:
    rows = await conn.fetch(
        """
        SELECT table_name
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND column_name = 'is_demo'
        """
    )
    have = {r["table_name"] for r in rows}
    required = {
        "users",
        "wallets",
        "user_settings",
        "signal_feeds",
        "signal_publications",
        "user_signal_subscriptions",
        "markets",
        "orders",
        "positions",
        "ledger",
    }
    missing = required - have
    if missing:
        raise RuntimeError(
            "is_demo column missing on tables: "
            + ", ".join(sorted(missing))
            + ". Run migration 014_add_is_demo_flag.sql first.",
        )


async def _resolve_boss_user_id(conn: asyncpg.Connection) -> uuid.UUID:
    raw = (os.environ.get("OPERATOR_CHAT_ID") or "").strip()
    if not raw:
        raise RuntimeError("OPERATOR_CHAT_ID env var is required to resolve Boss UUID.")
    try:
        boss_telegram_id = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"OPERATOR_CHAT_ID must be int, got {raw!r}") from exc
    row = await conn.fetchrow(
        "SELECT id FROM users WHERE telegram_user_id=$1",
        boss_telegram_id,
    )
    if row is None:
        raise RuntimeError(
            f"Boss user (telegram_user_id={boss_telegram_id}) not found. "
            "Have the operator run /start once before seeding.",
        )
    return row["id"]


async def _upsert_demo_markets(conn: asyncpg.Connection) -> int:
    inserted = 0
    for m in DEMO_MARKETS:
        result = await conn.execute(
            """
            INSERT INTO markets (id, slug, question, category, status,
                                 yes_price, no_price, yes_token_id, no_token_id,
                                 liquidity_usdc, resolved, is_demo)
            VALUES ($1, $2, $3, $4, 'active', $5, $6, $7, $8, $9, FALSE, TRUE)
            ON CONFLICT (id) DO NOTHING
            """,
            m["id"], m["slug"], m["question"], m["category"],
            m["yes_price"], m["no_price"], m["yes_token_id"], m["no_token_id"],
            m["liquidity_usdc"],
        )
        if result.endswith(" 1"):
            inserted += 1
    return inserted


async def _upsert_demo_users(conn: asyncpg.Connection) -> list[uuid.UUID]:
    user_ids: list[uuid.UUID] = []
    for i, tg_id in enumerate(DEMO_USER_TELEGRAM_IDS, start=1):
        det_id = _det_uuid(f"user:{tg_id}")
        await conn.execute(
            """
            INSERT INTO users (id, telegram_user_id, username, access_tier,
                               auto_trade_on, paused, is_demo)
            VALUES ($1, $2, $3, 3, FALSE, FALSE, TRUE)
            ON CONFLICT (telegram_user_id) DO NOTHING
            """,
            det_id, tg_id, f"demo_user_{i}",
        )
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE telegram_user_id=$1", tg_id,
        )
        user_ids.append(row["id"])
    return user_ids


async def _upsert_demo_wallets(
    conn: asyncpg.Connection, user_ids: list[uuid.UUID],
) -> None:
    for user_id, addr, hd_idx in zip(
        user_ids, DEMO_WALLET_ADDRESSES, DEMO_HD_INDICES,
    ):
        await conn.execute(
            """
            INSERT INTO wallets (user_id, deposit_address, hd_index,
                                 encrypted_key, balance_usdc, is_demo)
            VALUES ($1, $2, $3, 'DEMO_NO_KEY', $4, TRUE)
            ON CONFLICT (user_id) DO NOTHING
            """,
            user_id, addr, hd_idx, DEMO_PAPER_BALANCE,
        )
        await conn.execute(
            """
            INSERT INTO user_settings (user_id, risk_profile, strategy_types,
                                       trading_mode, is_demo)
            VALUES ($1, 'balanced', ARRAY['signal_following'], 'paper', TRUE)
            ON CONFLICT (user_id) DO NOTHING
            """,
            user_id,
        )


async def _upsert_demo_feeds(
    conn: asyncpg.Connection, operator_id: uuid.UUID,
) -> dict[str, uuid.UUID]:
    feed_ids: dict[str, uuid.UUID] = {}
    for spec in FEED_SPECS:
        det_id = _det_uuid(f"feed:{spec['slug']}")
        await conn.execute(
            """
            INSERT INTO signal_feeds (id, name, slug, operator_id, status,
                                      description, subscriber_count, is_demo)
            VALUES ($1, $2, $3, $4, 'active', $5, 0, TRUE)
            ON CONFLICT (slug) DO NOTHING
            """,
            det_id, spec["name"], spec["slug"], operator_id, spec["description"],
        )
        row = await conn.fetchrow(
            "SELECT id FROM signal_feeds WHERE slug=$1", spec["slug"],
        )
        feed_ids[spec["slug"]] = row["id"]
    return feed_ids


async def _seed_subscriptions(
    conn: asyncpg.Connection,
    user_ids: list[uuid.UUID],
    feed_ids: dict[str, uuid.UUID],
) -> None:
    politics = feed_ids["demo-politics-watcher"]
    sports = feed_ids["demo-sports-edge"]
    pairs = (
        (user_ids[0], politics),
        (user_ids[1], politics),
        (user_ids[1], sports),
    )
    for uid, fid in pairs:
        existing = await conn.fetchval(
            """
            SELECT 1 FROM user_signal_subscriptions
             WHERE user_id=$1 AND feed_id=$2 AND unsubscribed_at IS NULL
             LIMIT 1
            """,
            uid, fid,
        )
        if existing:
            continue
        await conn.execute(
            """
            INSERT INTO user_signal_subscriptions (id, user_id, feed_id,
                                                    is_demo)
            VALUES ($1, $2, $3, TRUE)
            """,
            _det_uuid(f"sub:{uid}:{fid}"), uid, fid,
        )
    # Subscriber count reflects active subs (matches what /signals catalog renders).
    for fid in {politics, sports}:
        await conn.execute(
            """
            UPDATE signal_feeds SET subscriber_count = (
                SELECT COUNT(*) FROM user_signal_subscriptions
                 WHERE feed_id=$1 AND unsubscribed_at IS NULL
            ) WHERE id=$1
            """,
            fid,
        )


async def _seed_publications(
    conn: asyncpg.Connection, feed_ids: dict[str, uuid.UUID],
) -> int:
    rng = random.Random(0xC2D5)  # deterministic spread across the last 12h
    now = datetime.now(timezone.utc)
    plan = []
    feed_slugs = list(feed_ids.keys())
    for i in range(10):
        slug = feed_slugs[i % len(feed_slugs)]
        market = DEMO_MARKETS[i % len(DEMO_MARKETS)]
        side = "yes" if i % 2 == 0 else "no"
        target = market["yes_price"] if side == "yes" else market["no_price"]
        confidence = round(0.55 + (i * 0.03) + rng.random() * 0.05, 3)
        confidence = min(0.85, max(0.55, confidence))
        published_at = now - timedelta(minutes=int((i + 1) * 65))
        plan.append((slug, market["id"], side, float(target), confidence, published_at))

    inserted = 0
    for slug, market_id, side, target_price, confidence, published_at in plan:
        det_id = _det_uuid(f"pub:{slug}:{market_id}:{side}")
        result = await conn.execute(
            """
            INSERT INTO signal_publications (id, feed_id, market_id, side,
                                              target_price, signal_type, payload,
                                              exit_signal, published_at,
                                              is_demo)
            VALUES ($1, $2, $3, $4, $5, 'entry', $6::jsonb, FALSE, $7, TRUE)
            ON CONFLICT (id) DO NOTHING
            """,
            det_id, feed_ids[slug], market_id, side, target_price,
            f'{{"confidence": {confidence}, "demo": true}}',
            published_at,
        )
        if result.endswith(" 1"):
            inserted += 1
    return inserted


async def _seed_paper_history(
    conn: asyncpg.Connection, user_ids: list[uuid.UUID],
) -> tuple[int, int, int]:
    """Insert ~7 days of paper-trade orders/positions/ledger rows.

    Distribution: 18 trades total, weighted (3, 3, 4, 4, 6, 8, 10) per
    day from oldest to today; ~58% win rate. Realistic position sizes
    in the $80-$240 range against the demo markets. All rows tagged
    is_demo=TRUE; mode='paper' so they cannot accidentally hit a live
    code path.
    """
    rng = random.Random(0x7E5D)
    now = datetime.now(timezone.utc)
    weights = [2, 3, 3, 4, 5, 7, 10]  # day -6 .. day 0 (today)
    plan: list[tuple[uuid.UUID, str, str, float, float, datetime, datetime, float]] = []
    seq = 0
    for day_offset, count in enumerate(weights):
        day = (now - timedelta(days=6 - day_offset)).replace(
            hour=14, minute=30, second=0, microsecond=0,
        )
        for _ in range(count):
            user_id = user_ids[seq % len(user_ids)]
            market = DEMO_MARKETS[seq % len(DEMO_MARKETS)]
            side = "yes" if seq % 2 == 0 else "no"
            entry = market["yes_price"] if side == "yes" else market["no_price"]
            entry = round(max(0.10, min(0.90, entry + rng.uniform(-0.03, 0.03))), 4)
            size = round(rng.uniform(80.0, 240.0), 2)
            opened_at = day + timedelta(minutes=rng.randint(0, 540))
            closed_at = opened_at + timedelta(minutes=rng.randint(45, 360))
            win = rng.random() < 0.58
            move = rng.uniform(0.04, 0.12)
            exit_price = entry + move if (win == (side == "yes")) else entry - move
            exit_price = round(max(0.05, min(0.95, exit_price)), 4)
            plan.append(
                (user_id, market["id"], side, entry, size, opened_at, closed_at,
                 exit_price),
            )
            seq += 1

    orders_inserted = 0
    positions_inserted = 0
    ledger_inserted = 0
    for idx, (user_id, market_id, side, entry, size, opened_at, closed_at,
              exit_price) in enumerate(plan):
        det_order = _det_uuid(f"order:{user_id}:{idx}")
        det_pos = _det_uuid(f"pos:{user_id}:{idx}")
        idem_key = f"demo-order-{user_id}-{idx}"
        order_res = await conn.execute(
            """
            INSERT INTO orders (id, user_id, market_id, side, size_usdc, price,
                                mode, status, idempotency_key, strategy_type,
                                created_at, is_demo)
            VALUES ($1, $2, $3, $4, $5, $6, 'paper', 'filled', $7,
                    'signal_following', $8, TRUE)
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            det_order, user_id, market_id, side, size, entry, idem_key, opened_at,
        )
        if order_res.endswith(" 1"):
            orders_inserted += 1

        # PnL: paper trade close where we exit at ``exit_price``. Sign
        # depends on side: long YES profits when price rises; long NO
        # profits when price falls.
        if side == "yes":
            pnl = round((exit_price - entry) / entry * size, 2)
        else:
            pnl = round((entry - exit_price) / entry * size, 2)

        pos_res = await conn.execute(
            """
            INSERT INTO positions (id, user_id, market_id, order_id, side,
                                    size_usdc, entry_price, current_price,
                                    mode, status, exit_reason, pnl_usdc,
                                    opened_at, closed_at, is_demo)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'paper', 'closed', $9,
                    $10, $11, $12, TRUE)
            ON CONFLICT (id) DO NOTHING
            """,
            det_pos, user_id, market_id, det_order, side, size, entry,
            exit_price, "tp" if pnl > 0 else "sl", pnl, opened_at, closed_at,
        )
        if pos_res.endswith(" 1"):
            positions_inserted += 1

        # ledger: trade_close so wallet.ledger.daily_pnl picks it up. The
        # ref_id points at the position; note tags it for debugging. We
        # do NOT touch wallets.balance_usdc here - the demo wallet stays
        # at $10k as a stable display value.
        ledger_res = await conn.execute(
            """
            INSERT INTO ledger (id, user_id, type, amount_usdc, ref_id, note,
                                 created_at, is_demo)
            VALUES ($1, $2, 'trade_close', $3, $4, 'demo paper close', $5, TRUE)
            ON CONFLICT (id) DO NOTHING
            """,
            _det_uuid(f"ledger:{user_id}:{idx}"), user_id, pnl, det_pos,
            closed_at,
        )
        if ledger_res.endswith(" 1"):
            ledger_inserted += 1

    return orders_inserted, positions_inserted, ledger_inserted


async def _run() -> int:
    if os.environ.get("DEMO_SEED_ALLOW") != "1":
        logger.error(
            "DEMO_SEED_ALLOW=1 is required to run the demo seeder. Refusing.",
        )
        return 2

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        logger.error("DATABASE_URL env var is required.")
        return 3

    try:
        conn = await asyncpg.connect(dsn=dsn)
    except Exception as exc:  # noqa: BLE001 - boundary
        logger.error("DB connect failed: %s", exc)
        return 4

    try:
        await _ensure_is_demo_columns(conn)
        boss_id = await _resolve_boss_user_id(conn)
        async with conn.transaction():
            mkts = await _upsert_demo_markets(conn)
            user_ids = await _upsert_demo_users(conn)
            await _upsert_demo_wallets(conn, user_ids)
            feed_ids = await _upsert_demo_feeds(conn, boss_id)
            await _seed_subscriptions(conn, user_ids, feed_ids)
            pubs = await _seed_publications(conn, feed_ids)
            orders, positions, ledger_rows = await _seed_paper_history(
                conn, user_ids,
            )
        logger.info(
            "Demo seed complete: markets=%s feeds=%s users=%s pubs=%s "
            "orders=%s positions=%s ledger=%s",
            mkts, len(feed_ids), len(user_ids), pubs, orders, positions,
            ledger_rows,
        )
    except RuntimeError as exc:
        logger.error("Pre-flight failed: %s", exc)
        return 3
    except Exception as exc:  # noqa: BLE001 - boundary
        logger.exception("Seed failed: %s", exc)
        return 4
    finally:
        await conn.close()
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
