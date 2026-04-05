"""Rule-based insight engine — translates raw metrics into human explanations."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Insight:
    explanation: str
    edge: str          # "Low" | "Medium" | "High"
    trend: str         # "bullish" | "bearish" | "neutral"
    decision: str


def generate_insight(
    pnl: float = 0.0,
    exposure: float = 0.0,
    drawdown: float = 0.0,
    position_count: int = 0,
) -> Insight:
    """Evaluate current state and return a human-readable Insight.

    Rules (evaluated in priority order):
    1. No active position  → waiting message
    2. High drawdown       → risk warning
    3. Negative PnL        → slight drawdown message
    4. Positive PnL        → performing well
    5. Low exposure        → capital idle
    6. Fallback            → neutral holding
    """
    # ── 1. No position ────────────────────────────────────────────────────────
    if position_count == 0:
        return Insight(
            explanation="No active trades — waiting for high-probability setup",
            edge="Low",
            trend="neutral",
            decision="waiting for opportunity",
        )

    # ── 2. High drawdown (>= 5%) ──────────────────────────────────────────────
    if drawdown >= 0.05:
        return Insight(
            explanation=f"Drawdown at {drawdown:.1%} — monitoring risk closely",
            edge="Low",
            trend="bearish",
            decision="hold, risk elevated",
        )

    # ── 3. Negative PnL ───────────────────────────────────────────────────────
    if pnl < 0:
        return Insight(
            explanation="Slight drawdown, still within normal range",
            edge="Medium",
            trend="neutral",
            decision="hold, within tolerance",
        )

    # ── 4. Positive PnL ───────────────────────────────────────────────────────
    if pnl > 0:
        edge = "High" if pnl > 50 else "Medium"
        return Insight(
            explanation="Position performing well, maintaining exposure",
            edge=edge,
            trend="bullish",
            decision="hold, position profitable",
        )

    # ── 5. Low exposure (no PnL yet, capital mostly idle) ─────────────────────
    if exposure < 0.1:
        return Insight(
            explanation="Capital mostly idle, ready to deploy",
            edge="Low",
            trend="neutral",
            decision="scanning for entry",
        )

    # ── 6. Fallback ───────────────────────────────────────────────────────────
    return Insight(
        explanation="Position open, monitoring market conditions",
        edge="Medium",
        trend="neutral",
        decision="holding position",
    )
