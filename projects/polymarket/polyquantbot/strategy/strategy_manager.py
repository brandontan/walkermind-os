"""Strategy — StrategyStateManager: in-memory strategy toggle state with Redis persistence.

Manages which trading strategies are active/inactive.  Persists state to Redis
(with a memory-only fallback) and restores it on startup.

Default state (all enabled)::

    {
        "ev_momentum":    True,
        "mean_reversion": True,
        "liquidity_edge": True,
    }

Failsafe:
    If every strategy is disabled the manager auto-enables all to prevent
    zero-alpha scenarios.

Usage::

    manager = StrategyStateManager()
    await manager.load(redis_client)   # restore from Redis

    manager.toggle("ev_momentum")
    active = manager.get_active()      # ["mean_reversion", "liquidity_edge"]
    state  = manager.get_state()       # {"ev_momentum": False, ...}

    await manager.save(redis_client)   # persist to Redis
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from ..infra.redis_client import RedisClient

log = structlog.get_logger(__name__)

_REDIS_KEY = "polyquantbot:strategy_state"

# ── Canonical strategy names ───────────────────────────────────────────────────

KNOWN_STRATEGIES: List[str] = ["ev_momentum", "mean_reversion", "liquidity_edge"]

_DEFAULT_STATE: Dict[str, bool] = {name: True for name in KNOWN_STRATEGIES}


class StrategyStateManager:
    """Manages per-strategy toggle state with Redis persistence.

    Thread-safety: designed for single asyncio event loop.  Protect shared
    state with an asyncio.Lock for concurrent toggle operations.

    Args:
        initial_state: Optional override for initial toggle state dict.
            Unrecognised strategy names in the override are ignored.
            Missing names default to True (enabled).
    """

    def __init__(
        self,
        initial_state: Optional[Dict[str, bool]] = None,
    ) -> None:
        # Start with all enabled then apply any caller overrides
        self._state: Dict[str, bool] = dict(_DEFAULT_STATE)
        if initial_state:
            for name in KNOWN_STRATEGIES:
                if name in initial_state:
                    self._state[name] = bool(initial_state[name])
        self._lock: asyncio.Lock = asyncio.Lock()

    # ── Public read API ────────────────────────────────────────────────────────

    def get_state(self) -> Dict[str, bool]:
        """Return a copy of the current strategy toggle state.

        Returns:
            Dict mapping strategy name → enabled bool.
        """
        return dict(self._state)

    def get_active(self) -> List[str]:
        """Return names of all currently enabled strategies.

        Returns:
            List of strategy names where state is True.
        """
        return [name for name, enabled in self._state.items() if enabled]

    def is_active(self, strategy: str) -> bool:
        """Return True if *strategy* is currently enabled.

        Unknown strategy names return False.

        Args:
            strategy: Strategy name to query.

        Returns:
            True if enabled, False if disabled or unknown.
        """
        return self._state.get(strategy, False)

    # ── Public mutate API ──────────────────────────────────────────────────────

    def toggle(self, strategy: str) -> bool:
        """Toggle a strategy on or off.

        If disabling the last active strategy the toggle is rejected and all
        strategies are re-enabled to prevent zero-alpha scenarios.

        Args:
            strategy: Name of the strategy to toggle.

        Returns:
            New boolean state of the strategy (True = enabled).

        Raises:
            ValueError: If *strategy* is not in KNOWN_STRATEGIES.
        """
        if strategy not in KNOWN_STRATEGIES:
            log.warning(
                "strategy_toggle_unknown",
                strategy=strategy,
                known=KNOWN_STRATEGIES,
            )
            raise ValueError(f"Unknown strategy: {strategy!r}")

        new_state = not self._state[strategy]
        self._state[strategy] = new_state

        # Failsafe: if no strategy is now active, re-enable all
        if not any(self._state.values()):
            log.warning(
                "strategy_all_disabled_fallback",
                reason="no active strategy — auto-enabling all",
            )
            self._state = dict(_DEFAULT_STATE)
            new_state = True  # report final state as enabled (all restored)

        log.info(
            "strategy_toggled",
            strategy=strategy,
            new_state=new_state,
            active_strategies=self.get_active(),
        )
        return new_state

    # ── Persistence ────────────────────────────────────────────────────────────

    async def load(self, redis: Optional["RedisClient"] = None) -> None:
        """Load strategy state from Redis.

        Falls back silently to the current in-memory state on any Redis error.

        Args:
            redis: Connected RedisClient.  If None, skip Redis and use defaults.
        """
        if redis is None:
            log.info(
                "strategy_state_loaded",
                source="memory_default",
                state=self.get_state(),
            )
            return

        try:
            # RedisClient exposes _get_json/_set_json as the generic persistence
            # primitives for arbitrary keys — this pattern is used throughout the
            # codebase (e.g. multi_strategy_metrics.py) for custom key namespaces.
            data: Optional[Any] = await asyncio.wait_for(
                redis._get_json(_REDIS_KEY), timeout=3.0
            )
        except Exception as exc:
            log.warning(
                "strategy_state_load_redis_error",
                error=str(exc),
                fallback="memory_default",
            )
            data = None

        if data and isinstance(data, dict):
            for name in KNOWN_STRATEGIES:
                if name in data:
                    self._state[name] = bool(data[name])

            # Failsafe: if Redis persisted an all-false state, restore defaults
            if not any(self._state.values()):
                log.warning(
                    "strategy_state_load_all_false_fallback",
                    reason="all strategies disabled in Redis — restoring defaults",
                )
                self._state = dict(_DEFAULT_STATE)

            log.info(
                "strategy_state_loaded",
                source="redis",
                state=self.get_state(),
            )
        else:
            log.info(
                "strategy_state_loaded",
                source="memory_default",
                state=self.get_state(),
            )

    async def save(self, redis: Optional["RedisClient"] = None) -> bool:
        """Persist current strategy state to Redis.

        Args:
            redis: Connected RedisClient.  If None, log warning and return False.

        Returns:
            True on success, False on failure or when redis is None.
        """
        if redis is None:
            log.warning("strategy_state_save_no_redis", reason="redis client not provided")
            return False

        try:
            # See note above: _set_json is the standard generic persistence
            # primitive used across the codebase for custom key namespaces.
            ok: bool = await asyncio.wait_for(
                redis._set_json(_REDIS_KEY, self.get_state()), timeout=3.0
            )
        except Exception as exc:
            log.warning("strategy_state_save_redis_error", error=str(exc))
            return False

        if ok:
            log.info("strategy_state_saved", state=self.get_state())
        else:
            log.warning("strategy_state_save_failed")
        return ok
