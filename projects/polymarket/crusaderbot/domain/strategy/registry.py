"""StrategyRegistry — the boundary that loads, validates, and routes strategies.

Foundation-only. The registry knows nothing about execution, risk, or signal
loops. It exposes a singleton entry-point so the auto-trade scheduler and
Telegram config UI share one consistent strategy catalog per process.
"""

from __future__ import annotations

import re
import threading
from typing import Any

from .base import BaseStrategy
from .types import VALID_RISK_PROFILES

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,49}$")


class StrategyRegistry:
    """Process-wide strategy catalog.

    Use `StrategyRegistry.instance()` rather than constructing directly. The
    underlying singleton is created once per process and returns the same
    instance to every caller, including across threads.
    """

    _singleton: "StrategyRegistry | None" = None
    _singleton_lock = threading.Lock()

    def __init__(self) -> None:
        self._strategies: dict[str, BaseStrategy] = {}

    @classmethod
    def instance(cls) -> "StrategyRegistry":
        """Return the process-wide registry singleton."""
        if cls._singleton is None:
            with cls._singleton_lock:
                if cls._singleton is None:
                    cls._singleton = cls()
        return cls._singleton

    @classmethod
    def _reset_for_tests(cls) -> None:
        """Test-only hook: drop the singleton so each test starts clean.

        Production code MUST NOT call this. Kept as an underscore-prefixed
        classmethod so the test suite can isolate registry state without
        spinning up a new process.
        """
        with cls._singleton_lock:
            cls._singleton = None

    def register(self, strategy: BaseStrategy) -> None:
        """Add a strategy to the registry.

        Validates:
            - `strategy` is a `BaseStrategy` instance (concrete subclass).
            - `name` matches `[a-z][a-z0-9_]{1,49}`.
            - `version` is semver-like ("MAJOR.MINOR.PATCH" with optional
              pre-release / build suffix).
            - `risk_profile_compatibility` is a non-empty subset of
              {conservative, balanced, aggressive}.
            - `name` is not already registered.

        Raises:
            TypeError: argument is not a `BaseStrategy`.
            ValueError: any validation rule above fails, or duplicate name.
        """
        if not isinstance(strategy, BaseStrategy):
            raise TypeError(
                "StrategyRegistry.register requires a BaseStrategy instance, "
                f"got {type(strategy).__name__}"
            )

        name = strategy.name
        version = strategy.version
        compat = strategy.risk_profile_compatibility

        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise ValueError(
                "BaseStrategy.name must match [a-z][a-z0-9_]{1,49}, "
                f"got {name!r}"
            )
        if not isinstance(version, str) or not _SEMVER_RE.match(version):
            raise ValueError(
                "BaseStrategy.version must be semver-like 'MAJOR.MINOR.PATCH', "
                f"got {version!r}"
            )
        if not isinstance(compat, list) or not compat:
            raise ValueError(
                "BaseStrategy.risk_profile_compatibility must be a non-empty "
                f"list, got {compat!r}"
            )
        invalid = [p for p in compat if p not in VALID_RISK_PROFILES]
        if invalid:
            raise ValueError(
                "BaseStrategy.risk_profile_compatibility entries must be in "
                f"{VALID_RISK_PROFILES}, got invalid {invalid!r}"
            )
        if name in self._strategies:
            raise ValueError(
                f"Strategy {name!r} is already registered "
                f"(existing version={self._strategies[name].version!r})"
            )

        self._strategies[name] = strategy

    def get(self, name: str) -> BaseStrategy:
        """Return the registered strategy by name.

        Raises:
            KeyError: no strategy with that name is registered.
        """
        if name not in self._strategies:
            raise KeyError(f"Strategy {name!r} is not registered")
        return self._strategies[name]

    def list_available(self) -> list[dict[str, Any]]:
        """Return a serializable catalog of registered strategies.

        Each entry: ``{"name", "version", "risk_profile_compatibility"}``.
        Sorted by name for deterministic output.
        """
        return [
            {
                "name": s.name,
                "version": s.version,
                "risk_profile_compatibility": list(s.risk_profile_compatibility),
            }
            for s in sorted(self._strategies.values(), key=lambda s: s.name)
        ]

    def get_compatible(self, risk_profile: str) -> list[BaseStrategy]:
        """Return strategies compatible with the given user risk profile.

        Raises:
            ValueError: ``risk_profile`` is not one of the canonical values.
        """
        if risk_profile not in VALID_RISK_PROFILES:
            raise ValueError(
                f"risk_profile must be one of {VALID_RISK_PROFILES}, "
                f"got {risk_profile!r}"
            )
        return [
            s
            for s in sorted(self._strategies.values(), key=lambda s: s.name)
            if risk_profile in s.risk_profile_compatibility
        ]


def bootstrap_default_strategies(
    registry: "StrategyRegistry | None" = None,
) -> "StrategyRegistry":
    """Register every built-in strategy onto ``registry`` (singleton by default).

    Idempotent: a name that is already registered is silently skipped so the
    function is safe to call from `main.py` lifespan on every boot, and from
    tests after `_reset_for_tests()`. The duplicate detection goes through
    the public `get(name)` API rather than reaching into `_strategies` so
    the bootstrap respects the registry boundary. Imports happen inside the
    function to avoid an import-time cycle between `registry` and
    `strategies/`.
    """
    reg = registry if registry is not None else StrategyRegistry.instance()
    from .strategies import CopyTradeStrategy, MomentumReversalStrategy, SignalFollowingStrategy

    for cls in (CopyTradeStrategy, MomentumReversalStrategy, SignalFollowingStrategy):
        try:
            reg.get(cls.name)
        except KeyError:
            reg.register(cls())
    return reg


__all__ = ["StrategyRegistry", "bootstrap_default_strategies"]
