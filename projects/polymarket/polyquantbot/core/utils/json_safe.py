"""core.utils.json_safe — Safe JSON deserialization utility.

Handles the Gamma API pattern where array fields such as ``outcomePrices``,
``outcomes``, and ``clobTokenIds`` are delivered as JSON-encoded strings
(e.g. ``"[\\"0.545\\", \\"0.455\\"]"``) rather than native Python lists.

Usage::

    from core.utils.json_safe import safe_json_load

    prices = safe_json_load(market.get("outcomePrices"))
    # → [0.545, 0.455] if value was "[\"0.545\", \"0.455\"]"
    # → [0.545, 0.455] if value was already a list
    # → None            if value was None, malformed, or an unexpected type
"""
from __future__ import annotations

import json
from typing import Any


def safe_json_load(value: Any) -> Any:
    """Deserialize *value* to a Python object, handling both pre-parsed and
    JSON-encoded-string forms.

    Args:
        value: Any value.  If it is a ``str`` the function attempts
               ``json.loads``; any other type is returned unchanged; ``None``
               is returned as-is.

    Returns:
        The parsed Python object, the original value (if already parsed), or
        ``None`` if *value* is ``None`` or parsing fails.

    Examples::

        safe_json_load("[\"0.5\", \"0.5\"]")  # → ["0.5", "0.5"]
        safe_json_load(["0.5", "0.5"])         # → ["0.5", "0.5"]
        safe_json_load(None)                   # → None
        safe_json_load("[broken")              # → None
        safe_json_load(42)                     # → 42
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return None
    return value
