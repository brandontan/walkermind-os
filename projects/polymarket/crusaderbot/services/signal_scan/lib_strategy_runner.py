"""Adapter: run lib/strategies/ classes and emit domain SignalCandidates.

lib/strategies/ are standalone algorithmic classes that operate on raw market
dicts and emit lib.Signal objects. This module normalises Gamma API market data
to the format those classes expect and converts their output to
domain.strategy.types.SignalCandidate for downstream risk gating.

IMPORTANT: lib/strategies/ classes are NEVER modified here. This adapter
adapts the surrounding data, not the strategies themselves.
"""
from __future__ import annotations

import importlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from ...domain.strategy.types import SignalCandidate

logger = logging.getLogger(__name__)

# The vendored lib/ package lives inside the crusaderbot package
# (projects/polymarket/crusaderbot/lib). Resolve the crusaderbot package root
# from this module's __package__ so the import works in dev
# (projects.polymarket.crusaderbot.*) and prod (crusaderbot.*) without any
# file-path or sys.path manipulation. Loading lib strategies as real
# subpackages is REQUIRED: the strategy modules use package-relative imports
# (from ..strategy_base import ...) that cannot resolve under file-path loading.
_PKG_ROOT = (__package__ or "").rsplit(".services.", 1)[0]
_LIB_PKG = f"{_PKG_ROOT}.lib" if _PKG_ROOT else "lib"

# Strategies that are enabled for execution. whale_tracking is deferred because
# it requires an external prob.trade API that may not be reachable.
ENABLED_STRATEGIES: tuple[str, ...] = (
    "trend_breakout",
    "momentum",
    "value_investor",
    "expiration_timing",
    "pair_arb",
    "ensemble",
)

# whale_tracking is deferred but still part of the preset system — when it does
# produce signals they will be filtered per-user by the preset map.
DEFERRED_STRATEGIES: tuple[str, ...] = ("whale_tracking",)


# Module-level cache: strategy name → strategy instance.
# Strategy classes are loaded once per process (module loading + class
# instantiation is expensive). initialize() is still called per invocation so
# per-user strategy_params are applied correctly before each scan.
# Thread safety: run_lib_strategy is called via run_in_executor in a
# sequential await loop — no two calls overlap, so the shared instance is
# not accessed concurrently.
_strategy_instances: dict[str, Any] = {}


def _load_strategy(name: str) -> Any:
    """Import a lib strategy as a package submodule and instantiate it.

    Loaded as ``{_LIB_PKG}.strategies.{name}`` (a real subpackage) so the
    strategy module's relative imports (``from ..strategy_base import ...``,
    ``from . import get_strategy``) resolve. Raises ImportError if no matching
    Strategy subclass is present, or propagates the underlying ImportError if
    the module itself cannot be imported.
    """
    module = importlib.import_module(f"{_LIB_PKG}.strategies.{name}")
    base = importlib.import_module(f"{_LIB_PKG}.strategy_base")
    strategy_cls = base.Strategy

    for attr_name in dir(module):
        obj = getattr(module, attr_name)
        try:
            if (
                isinstance(obj, type)
                and issubclass(obj, strategy_cls)
                and obj is not strategy_cls
                and getattr(obj, "name", None) == name
            ):
                return obj()
        except TypeError:
            pass

    raise ImportError(
        f"No Strategy subclass with name={name!r} found in "
        f"{_LIB_PKG}.strategies.{name}"
    )


def _parse_outcome_prices(market: dict) -> tuple[float | None, float | None]:
    """Extract (yes_price, no_price) from a Gamma API market dict."""
    outcomes = market.get("outcomePrices") or market.get("outcome_prices") or []
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            outcomes = []
    yes_p = float(outcomes[0]) if outcomes and outcomes[0] is not None else None
    no_p = float(outcomes[1]) if len(outcomes) > 1 and outcomes[1] is not None else None
    return yes_p, no_p


def _normalize_market(gamma: dict) -> dict:
    """Convert a Gamma API market dict to the format lib strategies expect.

    lib/strategy_base.py helpers use:
      - m["condition_id"]           (Gamma: "conditionId")
      - m["tokens"]["token1|2"]["price"]  (Gamma: outcomePrices list or tokens list)
      - m["priceChange"]["oneDay"]  (Gamma: "oneDayPriceChange" float, often absent)
      - m["liquidity"]              (Gamma: "liquidity" float/str)
      - m["volume_24hr"]            (Gamma: "volume24hr" or "volumeNum")
      - m["active"], m["accepting_orders"], m["closed"]
    """
    yes_p, no_p = _parse_outcome_prices(gamma)

    # If Gamma tokens list is present prefer its price field
    tokens_list: list = gamma.get("tokens") or []
    if tokens_list and isinstance(tokens_list[0], dict):
        t1_price = tokens_list[0].get("price")
        if t1_price is not None:
            yes_p = float(t1_price)
    if len(tokens_list) > 1 and isinstance(tokens_list[1], dict):
        t2_price = tokens_list[1].get("price")
        if t2_price is not None:
            no_p = float(t2_price)

    tokens_dict: dict[str, dict] = {}
    if yes_p is not None:
        tokens_dict["token1"] = {"price": yes_p}
    if no_p is not None:
        tokens_dict["token2"] = {"price": no_p}

    # 24h price change — Gamma may return this as oneDayPriceChange (float)
    one_day_change: float | None = None
    raw_change = (
        gamma.get("oneDayPriceChange")
        or gamma.get("price_change_24h")
        or gamma.get("priceChange1d")
    )
    if raw_change is not None:
        try:
            one_day_change = float(raw_change)
        except (TypeError, ValueError):
            pass

    liquidity_raw = gamma.get("liquidity", 0)
    try:
        liquidity = float(liquidity_raw or 0)
    except (TypeError, ValueError):
        liquidity = 0.0

    volume_raw = (
        gamma.get("volume24hr")
        or gamma.get("volume_24hr")
        or gamma.get("volumeNum")
        or 0
    )
    try:
        volume_24hr = float(volume_raw or 0)
    except (TypeError, ValueError):
        volume_24hr = 0.0

    return {
        # snake_case id expected by lib strategies
        "condition_id": gamma.get("conditionId") or gamma.get("condition_id") or "",
        # status flags
        "active": bool(gamma.get("active", False)),
        "accepting_orders": bool(
            gamma.get("acceptingOrders", gamma.get("accepting_orders", False))
        ),
        "closed": bool(gamma.get("closed", False)),
        # pricing
        "tokens": tokens_dict,
        "priceChange": {"oneDay": one_day_change},
        # liquidity / volume
        "liquidity": liquidity,
        "volume_24hr": volume_24hr,
        # pass through all original fields so strategies that access non-standard
        # keys (e.g. whale_tracking accessing prob.trade specific fields) still work
        **{k: v for k, v in gamma.items() if k not in (
            "condition_id", "active", "accepting_orders", "closed",
            "tokens", "priceChange", "liquidity", "volume_24hr",
        )},
    }


def _convert_signal(lib_signal: Any, strategy_name: str, now: datetime) -> SignalCandidate | None:
    """Convert a lib.Signal to a domain SignalCandidate.

    Returns None if the signal cannot be converted (e.g. missing condition_id,
    invalid side, out-of-range confidence).
    """
    market_id: str = getattr(lib_signal, "market", "") or ""
    if not market_id:
        return None

    outcome: str = getattr(lib_signal, "outcome", "Yes") or "Yes"
    side = "YES" if outcome.lower().startswith("y") else "NO"

    confidence: float = float(getattr(lib_signal, "confidence", 0.5) or 0.5)
    confidence = max(0.0, min(1.0, confidence))

    amount: float = float(getattr(lib_signal, "amount", 5.0) or 5.0)
    amount = max(0.0, amount)

    price: float | None = getattr(lib_signal, "price", None)
    reason: str = getattr(lib_signal, "reason", "") or ""

    try:
        return SignalCandidate(
            market_id=market_id,
            condition_id=market_id,
            side=side,
            confidence=confidence,
            suggested_size_usdc=amount,
            strategy_name=strategy_name,
            signal_ts=now,
            metadata={"reason": reason, "price": price},
        )
    except (ValueError, TypeError) as exc:
        logger.debug("lib_signal_convert_failed strategy=%s error=%s", strategy_name, exc)
        return None


def run_lib_strategy(
    name: str,
    markets: list[dict],
    config: dict | None = None,
) -> list[SignalCandidate]:
    """Run one lib strategy synchronously and return converted SignalCandidates.

    Never raises — returns empty list on any failure. Warnings are emitted so
    operators can diagnose unreachable external APIs (whale_tracking / prob.trade).
    """
    now = datetime.now(tz=timezone.utc)
    config = config or {}

    if name not in _strategy_instances:
        try:
            _strategy_instances[name] = _load_strategy(name)
        except Exception as exc:
            logger.warning(
                "lib_strategy_load_failed strategy=%s error=%s — "
                "no signals will be generated for this preset this tick",
                name, exc,
            )
            return []
    strategy = _strategy_instances[name]

    try:
        strategy.initialize(config.get("strategy_params", {}))
    except Exception as exc:
        logger.warning("lib_strategy_init_failed strategy=%s error=%s", name, exc)
        return []

    normalized = [_normalize_market(m) for m in markets]

    try:
        lib_signals = strategy.scan(markets=normalized, positions=[], balance=100.0)
    except Exception as exc:
        # whale_tracking will fail if prob.trade API is unreachable.
        # This is expected in paper-mode environments without external access.
        logger.warning(
            "lib_strategy_scan_failed strategy=%s error=%s — "
            "external API may be unreachable; returning empty signal list",
            name, exc,
        )
        return []

    candidates: list[SignalCandidate] = []
    for sig in lib_signals or []:
        cand = _convert_signal(sig, name, now)
        if cand is not None:
            candidates.append(cand)

    if candidates:
        logger.info("lib_strategy_signals strategy=%s count=%d", name, len(candidates))
    else:
        logger.debug("lib_strategy_no_signals strategy=%s", name)

    return candidates


__all__ = [
    "run_lib_strategy",
    "ENABLED_STRATEGIES",
    "DEFERRED_STRATEGIES",
]
