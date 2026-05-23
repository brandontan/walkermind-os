"""lib.strategies package — algorithmic strategy classes + name-based loader.

``get_strategy`` is imported by ensemble.py (``from . import get_strategy``)
to build its sub-strategies. It loads a sibling strategy module by name and
returns an instance of the Strategy subclass whose ``name`` matches.

Importing the sibling module as a package submodule (rather than by file path)
is what allows each strategy's ``from ..strategy_base import ...`` relative
import to resolve.
"""
from __future__ import annotations

import importlib

from ..strategy_base import Strategy


def get_strategy(name: str) -> Strategy:
    """Return an instance of the lib strategy whose ``.name`` == ``name``.

    Raises ValueError if the module cannot be imported or no matching Strategy
    subclass is found. ensemble.py catches ValueError, so failures degrade to
    "sub-strategy skipped" rather than crashing the ensemble scan.
    """
    try:
        module = importlib.import_module(f".{name}", __name__)
    except ImportError as exc:
        raise ValueError(f"strategy module not importable: {name!r} ({exc})") from exc

    for obj in vars(module).values():
        if (
            isinstance(obj, type)
            and issubclass(obj, Strategy)
            and obj is not Strategy
            and getattr(obj, "name", None) == name
        ):
            return obj()

    raise ValueError(f"no Strategy subclass named {name!r} in lib.strategies.{name}")


__all__ = ["get_strategy"]
