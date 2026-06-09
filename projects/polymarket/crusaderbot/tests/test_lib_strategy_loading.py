"""Regression: lib strategy roster is empty after WARP/R00T cleanup.

The cosmetic lib/strategies/* modules (ensemble, momentum, trend_breakout,
value_investor, expiration_timing, pair_arb, whale_tracking, and so on) were
archived because none of them had a user-facing preset path. This test pins
the empty roster so that anyone re-introducing a lib strategy must also wire
it through ENABLED_STRATEGIES / a preset / the admin toggle deliberately.

The original F-HIGH-2 regression coverage (file-path loading vs subpackage
loading) is no longer reachable — there are no lib strategies to load — so
the test reduces to a sentinel: the moment a name returns, this test fails
loudly and the operator can refresh the contract.
"""
from __future__ import annotations

from projects.polymarket.crusaderbot.services.signal_scan.lib_strategy_runner import (
    DEFERRED_STRATEGIES,
    ENABLED_STRATEGIES,
)


def test_lib_strategy_roster_is_empty() -> None:
    """ENABLED_STRATEGIES / DEFERRED_STRATEGIES are empty post-cleanup.

    A future strategy gets added back here only via the documented path:
    implement → wire preset → seed strategies row → append to _ADMIN_STRATEGIES
    → append name to one of these tuples.
    """
    assert ENABLED_STRATEGIES == ()
    assert DEFERRED_STRATEGIES == ()
