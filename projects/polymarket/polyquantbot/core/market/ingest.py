"""core.market.ingest — Safe market ingestion with structured parse warnings.

Wraps :func:`core.market.parser.parse_market` over a list of raw market
dicts returned by the Gamma REST API and emits structured log warnings for
every market that fails validation.

Usage::

    from core.market.ingest import ingest_markets

    valid = ingest_markets(raw_markets)
    # → list of normalised dicts; invalid markets silently skipped after logging
"""
from __future__ import annotations

from typing import Any

import structlog

from .parser import parse_market

log = structlog.get_logger()


def ingest_markets(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse and validate a list of raw Gamma API market dicts.

    Each market is passed through :func:`parse_market`.  Markets that fail
    parsing are logged as structured warnings and excluded from the result;
    they never cause the calling pipeline to crash.

    Args:
        markets: List of raw market dicts as returned by
                 :func:`core.market.market_client.get_active_markets`.

    Returns:
        List of merged dicts — original fields **plus** the normalised keys
        ``market_id``, ``p_market``, ``prices``, ``outcomes``, and
        ``token_ids`` — for every market that passes validation.  Guaranteed
        to never raise.
    """
    total = len(markets)
    valid: list[dict[str, Any]] = []
    skipped = 0

    for market in markets:
        parsed = parse_market(market)
        if parsed is None:
            skipped += 1
            continue
        # Merge: original fields first so normalised keys always win
        valid.append({**market, **parsed})

    if skipped:
        log.warning(
            "markets_skipped_invalid",
            total=total,
            valid=len(valid),
            skipped=skipped,
        )
    else:
        log.debug("markets_ingested", total=total, valid=len(valid))

    return valid
