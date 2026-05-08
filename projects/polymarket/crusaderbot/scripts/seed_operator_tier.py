"""Tier 2 operator seeder for CrusaderBot.

Reads ``ADMIN_USER_IDS`` from the environment (comma-separated Telegram
user ids) and ensures each id has a row in ``users`` with
``access_tier >= 2``. Tier 2 is the "Community / operator" gate that
unlocks the operator-side surfaces of the bot (``/dashboard``,
``/positions``, ``/setup``).

The script is idempotent: re-running it on a database that already has
the operators seeded is a no-op. Existing rows have ``access_tier``
raised to 2 only when the current value is below 2 (we never *demote*
an existing operator — a Tier 4 operator stays Tier 4). Missing rows
are inserted with sensible defaults (auto_trade_on=FALSE, paused=FALSE,
no wallet — the operator must run /start once to provision a wallet).

The seeder is wired into the Fly release_command so it runs on every
deploy. In the Fly image the package installs as top-level
``crusaderbot``, so the production invocation is::

    python -m crusaderbot.scripts.seed_operator_tier

In the development repo the package lives under
``projects/polymarket/crusaderbot/`` and pytest's ``conftest.py`` adds
the repo root to ``sys.path``, so the equivalent local invocation is::

    ADMIN_USER_IDS=123456,789012 \
    python -m projects.polymarket.crusaderbot.scripts.seed_operator_tier

Process exit code
-----------------
The CLI entry point (``main``) ALWAYS exits 0 so Fly's release_command
never aborts the deploy. Fly fails any release whose hook returns a
non-zero code, but every failure mode of this seeder is recoverable
without rolling the release back:

* Missing ``ADMIN_USER_IDS`` — the operator simply hasn't supplied the
  secret yet; the bot still runs, /kill / /resume still work, and the
  next deploy after the secret is set will pick the operators up.
* Missing ``DATABASE_URL`` — the app itself cannot start without it
  and will surface the failure through /health, not the seeder.
* DB error — transient connectivity, OR (on the very first deploy)
  the schema does not exist yet because ``run_migrations()`` runs in
  the app lifespan AFTER the release_command. The seeder logs the
  error and the operator can re-run it after the bot is up. A future
  enhancement is to gate the seed on a "migrations applied" probe.

Internal status codes (returned by ``_run`` for tests + programmatic
callers, but always wrapped to exit 0 by ``main``):
    0  seed applied (or already in place — no-op)
    2  ADMIN_USER_IDS unset / empty / unparseable
    3  DATABASE_URL missing
    4  database error

Audit
-----
Every successful insert or tier-raise emits one row to ``audit.log``
(actor_role=``operator``, action=``operator_tier_seed``, payload contains
the affected telegram_user_id and the previous + new tier values). The
audit write is best-effort: a failure to write audit MUST NOT block
deploy completion.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Iterable

import asyncpg

logger = logging.getLogger("crusaderbot.scripts.seed_operator_tier")

OPERATOR_TIER: int = 2
AUDIT_ACTOR_ROLE: str = "operator"
AUDIT_ACTION: str = "operator_tier_seed"


def _parse_ids(raw: str | None) -> list[int]:
    """Parse the comma-separated ``ADMIN_USER_IDS`` env value.

    Whitespace-tolerant. Silently drops empty tokens. Tokens that do
    not parse as int are logged at WARNING and skipped — a typo in one
    id must not block the rest of the operators from being seeded.
    """
    if not raw:
        return []
    out: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.append(int(token))
        except ValueError:
            logger.warning(
                "seed_operator_tier: skipping unparseable id %r in ADMIN_USER_IDS",
                token,
            )
    return out


async def _seed_one(
    conn: asyncpg.Connection, telegram_user_id: int,
) -> tuple[str, int | None, int]:
    """Ensure one operator row exists at >= Tier 2.

    Returns a tuple ``(action, prev_tier, new_tier)`` where ``action``
    is one of ``inserted`` / ``raised`` / ``noop``. ``prev_tier`` is
    ``None`` for inserted rows.
    """
    row = await conn.fetchrow(
        "SELECT id, access_tier FROM users WHERE telegram_user_id=$1",
        telegram_user_id,
    )
    if row is None:
        await conn.execute(
            "INSERT INTO users (telegram_user_id, access_tier, "
            "auto_trade_on, paused) VALUES ($1, $2, FALSE, FALSE) "
            "ON CONFLICT (telegram_user_id) DO NOTHING",
            telegram_user_id, OPERATOR_TIER,
        )
        # user_settings row is created lazily on first /dashboard read
        # via users.get_settings_for(); we keep this script narrow.
        return ("inserted", None, OPERATOR_TIER)

    prev = int(row["access_tier"])
    if prev >= OPERATOR_TIER:
        return ("noop", prev, prev)

    await conn.execute(
        "UPDATE users SET access_tier=$2 WHERE id=$1",
        row["id"], OPERATOR_TIER,
    )
    return ("raised", prev, OPERATOR_TIER)


async def _write_audit(
    conn: asyncpg.Connection,
    *,
    telegram_user_id: int,
    action: str,
    prev_tier: int | None,
    new_tier: int,
) -> None:
    """Best-effort audit write — never blocks the seeder.

    The INSERT runs inside a NESTED ``conn.transaction()`` so an audit
    failure (missing ``audit`` schema on first deploy, permissions
    drift, etc.) rolls back ONLY the savepoint and leaves the outer
    seed transaction healthy. asyncpg implements nested transactions
    as savepoints — without this, a failed INSERT would put the
    surrounding transaction into an aborted state and PostgreSQL would
    reject every subsequent statement with ``current transaction is
    aborted``, undoing the operator-tier seed for every later id in
    the batch.
    """
    payload = {
        "telegram_user_id": telegram_user_id,
        "action": action,
        "prev_tier": prev_tier,
        "new_tier": new_tier,
        "source": "scripts.seed_operator_tier",
    }
    try:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO audit.log (actor_role, action, payload) "
                "VALUES ($1, $2, $3::jsonb)",
                AUDIT_ACTOR_ROLE, AUDIT_ACTION, json.dumps(payload),
            )
    except Exception as exc:  # noqa: BLE001 — audit must never break seeding
        logger.warning("audit write failed for tg=%s: %s", telegram_user_id, exc)


async def seed(
    dsn: str, telegram_user_ids: Iterable[int],
) -> dict[str, int]:
    """Apply the seed and return per-action counts.

    The work runs in a single transaction so a partial DB outage cannot
    leave half the operators upgraded. Audit rows are written inside
    the same transaction immediately after each user update.
    """
    counts = {"inserted": 0, "raised": 0, "noop": 0}
    conn = await asyncpg.connect(dsn=dsn)
    try:
        async with conn.transaction():
            for tg_id in telegram_user_ids:
                action, prev, new = await _seed_one(conn, tg_id)
                counts[action] += 1
                if action != "noop":
                    await _write_audit(
                        conn,
                        telegram_user_id=tg_id,
                        action=action,
                        prev_tier=prev,
                        new_tier=new,
                    )
                logger.info(
                    "seed_operator_tier tg=%s action=%s prev=%s new=%s",
                    tg_id, action, prev, new,
                )
    finally:
        await conn.close()
    return counts


async def _run() -> int:
    raw = os.environ.get("ADMIN_USER_IDS")
    ids = _parse_ids(raw)
    if not ids:
        logger.warning(
            "seed_operator_tier: ADMIN_USER_IDS unset or empty — nothing to seed",
        )
        return 2

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        logger.error("seed_operator_tier: DATABASE_URL is required")
        return 3

    try:
        counts = await seed(dsn, ids)
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("seed_operator_tier: DB error: %s", exc)
        return 4

    logger.info(
        "seed_operator_tier complete: inserted=%(inserted)s "
        "raised=%(raised)s noop=%(noop)s total=%(total)s",
        {**counts, "total": sum(counts.values())},
    )
    return 0


def main() -> int:
    """CLI entry point — always exits 0 so Fly's release_command does not
    abort the deploy. The inner status code is logged for diagnostics.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    inner_rc = asyncio.run(_run())
    if inner_rc != 0:
        logger.warning(
            "seed_operator_tier finished with internal status %d but "
            "exiting 0 so Fly release_command does not abort the deploy",
            inner_rc,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
