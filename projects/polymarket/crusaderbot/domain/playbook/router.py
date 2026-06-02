"""PLAYBOOK router — precedence-claim strategy selection.

Mirrors the SMART STRIKE ``_CANDLE_AUTO_RULE_ORDER`` pattern: modules are
evaluated in a fixed precedence order (highest-conviction / most discrete edge
first) and the **first module to claim a market wins**. A market is claimed by
at most one module per scan, so no two modules can open competing exposure on
the same event-side (dedup-by-design). The risk gate downstream still enforces
its own dedup + exposure caps.

Precedence (see ``docs/blueprint/playbook.md`` §4):
    1. injury_alpha   (feed-dependent, V2 — stub no-claim in Phase-1)
    2. sharp_money    (native formula, source live in V2 — stub no-claim)
    3. closing_edge   (native MVP — WIRED in Phase-1)
    4. public_fade    (feed-dependent, V2 — stub no-claim)
"""
from __future__ import annotations

from dataclasses import dataclass

from .modules import (
    ClosingEdgeModule,
    InjuryAlphaModule,
    MarketSnapshot,
    ModuleDecision,
    PlaybookModule,
    PublicFadeModule,
    SharpMoneyModule,
)
from .signals import SignalBundle

# Default module precedence — highest-conviction edge first.
DEFAULT_MODULE_ORDER: tuple[str, ...] = (
    "injury_alpha",
    "sharp_money",
    "closing_edge",
    "public_fade",
)


@dataclass(frozen=True)
class RouteResult:
    """Outcome of routing one market.

    ``routed`` is True when a module claimed the market. ``module`` and
    ``decision`` describe the winner; when nothing claimed, ``routed=False``
    and ``reason`` explains why (every module's no-claim reason is preserved in
    ``skipped`` for observability).
    """

    routed: bool
    module: str | None = None
    decision: ModuleDecision | None = None
    reason: str = ""
    skipped: tuple[tuple[str, str], ...] = ()


class PlaybookRouter:
    """Walks the module precedence order and returns the first claim.

    Construct with the default module set, or inject a custom ordered list
    (e.g. for tests or to disable a module). Stateless across calls.
    """

    def __init__(self, modules: list[PlaybookModule] | None = None) -> None:
        if modules is None:
            modules = [
                InjuryAlphaModule(),
                SharpMoneyModule(),
                ClosingEdgeModule(),
                PublicFadeModule(),
            ]
        # Order by DEFAULT_MODULE_ORDER, then append any extras deterministically.
        rank = {name: i for i, name in enumerate(DEFAULT_MODULE_ORDER)}
        self._modules: list[PlaybookModule] = sorted(
            modules, key=lambda m: rank.get(m.name, len(rank))
        )

    @property
    def module_names(self) -> tuple[str, ...]:
        """Ordered module names this router will evaluate."""
        return tuple(m.name for m in self._modules)

    def route(self, snapshot: MarketSnapshot, bundle: SignalBundle) -> RouteResult:
        """Evaluate modules in precedence order; first claim wins."""
        skipped: list[tuple[str, str]] = []
        for module in self._modules:
            decision = module.evaluate(snapshot, bundle)
            if decision.claimed:
                return RouteResult(
                    routed=True,
                    module=module.name,
                    decision=decision,
                    reason="claimed",
                    skipped=tuple(skipped),
                )
            skipped.append((module.name, decision.reasoning or "no_claim"))
        return RouteResult(
            routed=False,
            reason="no_module_claimed",
            skipped=tuple(skipped),
        )


__all__ = [
    "PlaybookRouter",
    "RouteResult",
    "DEFAULT_MODULE_ORDER",
]
