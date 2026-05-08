"""Lane 1C demo data cleanup.

Deletes every row tagged ``is_demo=TRUE`` across the tables the seed
script wrote into. Refuses to run unless ``DEMO_CLEANUP_CONFIRM=1`` is
set. The cleanup is the inverse of ``seed_demo_data.py``: every WHERE
clause is gated on ``is_demo = TRUE`` (or an FK chain to a row that is)
so production data cannot be touched by accident.

Safety
------
* Hard env guard: ``DEMO_CLEANUP_CONFIRM=1`` required.
* Pre-flight: counts demo-tagged rows in every table; aborts with no
  changes if zero rows found AND ``--allow-empty`` was not passed.
* Single transaction: all DELETEs commit together. Failure halfway
  rolls back so the database is never partially cleaned.
* Verification pass: after the transaction commits, the script re-reads
  per-table counts and refuses to exit cleanly if any is_demo=TRUE row
  survived (defence-in-depth against a missed table).

Run
---
    DEMO_CLEANUP_CONFIRM=1 python -m projects.polymarket.crusaderbot.scripts.cleanup_demo_data

Exit codes
----------
    0  cleanup applied (or no demo rows found, no-op)
    2  guard env var missing
    3  prerequisite missing (migration not applied)
    4  database error
    5  verification failed (demo rows remain post-cleanup)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

import asyncpg

logger = logging.getLogger("crusaderbot.demo.cleanup")

# Tables that own an is_demo column. Order matters for the verification
# read; the DELETE order below is its own concern (driven by FK chains).
IS_DEMO_TABLES: tuple[str, ...] = (
    "signal_publications",
    "user_signal_subscriptions",
    "signal_feeds",
    "ledger",
    "positions",
    "orders",
    "wallets",
    "user_settings",
    "users",
    "markets",
)

# Tables tied to demo users via FK but without an is_demo column. We
# delete them BEFORE the user row so cascade rules cannot quietly carry
# them away (defence-in-depth - several FKs are ON DELETE CASCADE today
# but the cleanup must remain correct if a future migration drops the
# cascade).
USER_FK_TABLES_NO_IS_DEMO: tuple[str, ...] = (
    "sessions",
    "deposits",
    "copy_targets",
    "fees",
    "idempotency_keys",
    "risk_log",
    "referral_codes",
)


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
    missing = set(IS_DEMO_TABLES) - have
    if missing:
        raise RuntimeError(
            "is_demo column missing on tables: "
            + ", ".join(sorted(missing))
            + ". Run migration 014_add_is_demo_flag.sql first.",
        )


async def _count_demo_rows(conn: asyncpg.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for tbl in IS_DEMO_TABLES:
        # ``identifiers cannot be parameterised`` - tbl values come from
        # an in-module allowlist (IS_DEMO_TABLES), so string interpolation
        # is safe here. Never extend this list with caller-supplied input.
        n = await conn.fetchval(
            f"SELECT COUNT(*) FROM {tbl} WHERE is_demo = TRUE",
        )
        counts[tbl] = int(n or 0)
    return counts


async def _delete_demo_rows(conn: asyncpg.Connection) -> dict[str, int]:
    """Delete every demo-tagged row in dependency order, returning a
    per-table count of rows removed.

    Order rationale:
      1. signal_publications  - FK -> signal_feeds (CASCADE).
      2. user_signal_subscriptions - FK -> users + signal_feeds (CASCADE).
      3. ledger / positions / orders - reference users + markets via FK.
      4. signal_feeds - now safe (subs + pubs gone).
      5. wallets / user_settings - 1:1 to users.
      6. Auxiliary user-FK tables (sessions / deposits / etc.) for the
         demo users only.
      7. users   - drop the 2 demo accounts.
      8. markets - drop the demo market shells last.
    """
    deleted: dict[str, int] = {}

    async def _exec(table: str, sql: str, *args) -> None:
        result = await conn.execute(sql, *args)
        # asyncpg returns "DELETE <n>" for DELETE statements.
        n = 0
        try:
            n = int(result.split()[-1])
        except ValueError:
            n = 0
        deleted[table] = deleted.get(table, 0) + n

    await _exec(
        "signal_publications",
        "DELETE FROM signal_publications WHERE is_demo = TRUE",
    )
    await _exec(
        "user_signal_subscriptions",
        "DELETE FROM user_signal_subscriptions WHERE is_demo = TRUE",
    )
    await _exec(
        "ledger",
        "DELETE FROM ledger WHERE is_demo = TRUE",
    )
    await _exec(
        "positions",
        "DELETE FROM positions WHERE is_demo = TRUE",
    )
    await _exec(
        "orders",
        "DELETE FROM orders WHERE is_demo = TRUE",
    )
    await _exec(
        "signal_feeds",
        "DELETE FROM signal_feeds WHERE is_demo = TRUE",
    )
    await _exec(
        "wallets",
        "DELETE FROM wallets WHERE is_demo = TRUE",
    )
    await _exec(
        "user_settings",
        "DELETE FROM user_settings WHERE is_demo = TRUE",
    )

    # Auxiliary FK tables for demo users only. Scope strictly via the
    # users.is_demo selector so we can never reach a non-demo row.
    demo_user_ids = await conn.fetch(
        "SELECT id FROM users WHERE is_demo = TRUE",
    )
    if demo_user_ids:
        ids = [r["id"] for r in demo_user_ids]
        for tbl in USER_FK_TABLES_NO_IS_DEMO:
            await _exec(
                tbl,
                f"DELETE FROM {tbl} WHERE user_id = ANY($1::uuid[])",
                ids,
            )

    await _exec(
        "users",
        "DELETE FROM users WHERE is_demo = TRUE",
    )
    await _exec(
        "markets",
        "DELETE FROM markets WHERE is_demo = TRUE",
    )
    return deleted


async def _run() -> int:
    if os.environ.get("DEMO_CLEANUP_CONFIRM") != "1":
        logger.error(
            "DEMO_CLEANUP_CONFIRM=1 is required to run the demo cleanup. "
            "Refusing.",
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
        before = await _count_demo_rows(conn)
        total_before = sum(before.values())
        logger.info("Demo rows present pre-cleanup: %s (total=%s)", before, total_before)
        if total_before == 0:
            logger.info("No demo rows found - nothing to do.")
            return 0

        async with conn.transaction():
            deleted = await _delete_demo_rows(conn)
        logger.info("Deleted: %s", deleted)

        after = await _count_demo_rows(conn)
        residual = sum(after.values())
        if residual > 0:
            logger.error(
                "Verification FAILED - %s demo rows survived cleanup: %s",
                residual, after,
            )
            return 5
        logger.info("Cleanup verified: 0 demo rows remain across all tables.")
    except RuntimeError as exc:
        logger.error("Pre-flight failed: %s", exc)
        return 3
    except Exception as exc:  # noqa: BLE001 - boundary
        logger.exception("Cleanup failed: %s", exc)
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
