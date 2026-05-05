"""Copy-trade size scaling.

Pure-arithmetic helper used by `CopyTradeStrategy.scan` to translate a leader
trade's USDC notional into a user-bankroll-relative position size. No I/O,
no DB, no broker interaction.

Invariant: the returned value is either a positive USDC amount that satisfies
both the proportional rule and the per-user position cap, or `0.0`. A return
of `0.0` is the strategy's "skip this signal" sentinel — the caller MUST NOT
emit a SignalCandidate from it.
"""
from __future__ import annotations

MIN_TRADE_SIZE_USDC: float = 1.0


def scale_size(
    leader_size: float,
    leader_bankroll: float,
    user_available: float,
    max_position_pct: float,
) -> float:
    """Return a USDC notional sized to the user's bankroll, or `0.0` to skip.

    Algorithm (matches WARP🔹CMD spec for P3b):
        1. proportional      = (user_available / leader_bankroll) * leader_size
        2. position_cap      = user_available * max_position_pct
        3. capped            = min(proportional, position_cap)
        4. floor             = capped if capped >= MIN_TRADE_SIZE_USDC else 0.0

    Skip (return 0.0) when:
        * any input is non-positive (degenerate inputs are not an error —
          they are a clean "no signal" signal)
        * the user has < $1 of room to deploy after the cap
        * `max_position_pct` is outside (0, 1] — the caller's UserContext
          contract enforces this, but we treat anything outside the open
          interval as "skip" for defence in depth
    """
    if leader_size <= 0.0:
        return 0.0
    if leader_bankroll <= 0.0:
        return 0.0
    if user_available <= 0.0:
        return 0.0
    if max_position_pct <= 0.0 or max_position_pct > 1.0:
        return 0.0

    proportional = (user_available / leader_bankroll) * leader_size
    position_cap = user_available * max_position_pct
    capped = min(proportional, position_cap)

    if capped < MIN_TRADE_SIZE_USDC:
        return 0.0
    return capped


__all__ = ["scale_size", "MIN_TRADE_SIZE_USDC"]
