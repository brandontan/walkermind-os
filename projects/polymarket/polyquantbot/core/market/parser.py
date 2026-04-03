"""core.market.parser — Full market data parser for raw Gamma API payloads.

Handles the Gamma API pattern where ``outcomePrices``, ``outcomes``, and
``clobTokenIds`` are delivered as JSON-encoded strings instead of native
Python lists.

Public API::

    from core.market.parser import parse_market

    result = parse_market(raw_market_dict)
    # → {
    #     "market_id": "0xabc...",
    #     "p_market": 0.545,
    #     "prices":   [0.545, 0.455],
    #     "outcomes": ["Yes", "No"],
    #     "token_ids": ["id1", "id2"],
    #   }
    # → None if parsing fails or data is invalid / incomplete

Input shape (raw Gamma API)::

    {
        "outcomePrices": "[\"0.545\", \"0.455\"]",
        "outcomes":      "[\"Yes\", \"No\"]",
        "clobTokenIds":  "[\"id1\", \"id2\"]",
        "id":            "0xabc123...",
        ...
    }

Output shape::

    {
        "market_id":  str,
        "p_market":   float,   # first outcome probability
        "prices":     list[float],
        "outcomes":   list[str],
        "token_ids":  list[str],
    }
"""
from __future__ import annotations

from typing import Any

import structlog

from ..utils.json_safe import safe_json_load
from ..logging.logger import log_invalid_market, log_market_parse_warning

log = structlog.get_logger()


def parse_market(market: dict[str, Any]) -> dict[str, Any] | None:
    """Parse and validate a raw Gamma API market dict.

    Handles JSON-encoded string fields (``outcomePrices``, ``outcomes``,
    ``clobTokenIds``) and converts price strings to floats.

    Args:
        market: Raw market dict as returned by the Gamma REST API.  Also
                accepts pre-normalised dicts (e.g. from tests) that already
                contain ``market_id`` / ``p_market`` keys.

    Returns:
        A normalised dict with keys ``market_id``, ``p_market``, ``prices``,
        ``outcomes``, and ``token_ids`` when extraction succeeds and the data
        passes validation; ``None`` otherwise.

    Failure handling:
        - Any exception during parsing is caught and logged as a structured
          warning; the function never raises.
        - Malformed JSON strings yield ``None`` from :func:`safe_json_load`
          and the market is skipped.
        - Non-numeric price values log a warning and cause the market to be
          skipped.
        - Arrays shorter than 2 elements are rejected.
        - ``None``, dict, int, or other unexpected types inside array fields
          are handled gracefully.
    """
    try:
        # ── Market ID ─────────────────────────────────────────────────────────
        market_id: str | None = (
            market.get("id")
            or market.get("conditionId")
            or market.get("market_id")
        )
        if not market_id:
            log_invalid_market(None, reason="missing_market_id")
            return None
        market_id = str(market_id)

        # ── outcomePrices — may be JSON-encoded string or native list ─────────
        raw_prices = safe_json_load(
            market.get("outcomePrices") or market.get("prices")
        )

        # Fall back to scalar p_market for pre-normalised dicts
        if raw_prices is None:
            raw_p = market.get("p_market")
            if raw_p is None:
                log_invalid_market(market_id, reason="missing_prices", field="outcomePrices")
                return None
            try:
                p_market = float(raw_p)
            except (TypeError, ValueError) as exc:
                log_market_parse_warning(market_id, str(exc), field="p_market")
                return None
            if not (0.0 < p_market < 1.0):
                log_invalid_market(
                    market_id, reason="price_out_of_range", field="p_market",
                    value=p_market,
                )
                return None
            return {
                "market_id": market_id,
                "p_market": p_market,
                "prices": [p_market],
                "outcomes": [],
                "token_ids": [],
            }

        if not isinstance(raw_prices, list):
            log_invalid_market(
                market_id, reason="prices_not_list", field="outcomePrices",
                type=type(raw_prices).__name__,
            )
            return None

        if len(raw_prices) < 2:
            log_invalid_market(
                market_id, reason="array_too_short", field="outcomePrices",
                length=len(raw_prices),
            )
            return None

        # Convert each price string → float
        prices: list[float] = []
        for i, val in enumerate(raw_prices):
            try:
                prices.append(float(val))
            except (TypeError, ValueError) as exc:
                log_market_parse_warning(
                    market_id, str(exc),
                    field="outcomePrices", index=i, raw_value=repr(val),
                )
                return None

        p_market = prices[0]
        if not (0.0 < p_market < 1.0):
            log_invalid_market(
                market_id, reason="price_out_of_range", field="outcomePrices",
                value=p_market,
            )
            return None

        # ── outcomes ──────────────────────────────────────────────────────────
        raw_outcomes = safe_json_load(market.get("outcomes"))
        outcomes: list[str]
        if isinstance(raw_outcomes, list):
            outcomes = [str(o) for o in raw_outcomes]
        else:
            outcomes = []

        # ── clobTokenIds ──────────────────────────────────────────────────────
        raw_token_ids = safe_json_load(market.get("clobTokenIds"))
        token_ids: list[str]
        if isinstance(raw_token_ids, list):
            token_ids = [str(t) for t in raw_token_ids]
        else:
            token_ids = []

        return {
            "market_id": market_id,
            "p_market": p_market,
            "prices": prices,
            "outcomes": outcomes,
            "token_ids": token_ids,
        }

    except Exception as exc:  # noqa: BLE001
        market_id_fallback: str | None = (
            market.get("id")  # type: ignore[assignment]
            or market.get("conditionId")
            or market.get("market_id")
        )
        log_market_parse_warning(str(market_id_fallback), str(exc))
        return None
