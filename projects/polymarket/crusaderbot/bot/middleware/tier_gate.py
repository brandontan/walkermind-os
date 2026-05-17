"""Tier gate — deprecated. Paper is open to all users. Kept for import compat."""
from __future__ import annotations

from typing import Callable


def require_tier(min_tier: int) -> Callable:  # noqa: ARG001
    def decorator(handler: Callable) -> Callable:
        return handler
    return decorator
