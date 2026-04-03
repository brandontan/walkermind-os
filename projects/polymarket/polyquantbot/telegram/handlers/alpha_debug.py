"""Alpha debug handler — returns (text, keyboard) for the /alpha debug screen.

Shows real-time alpha model diagnostics:

  - Most-recent p_model, p_market, edge, and confidence score (S)
  - Average edge across all evaluated ticks
  - Edge distribution (zero / weak / moderate / strong buckets)
  - Signal success rate (fraction of ticks that generated a real signal)
  - Zero-edge count (spam guard proxy)

``AlphaMetrics`` is injected at bot startup via :func:`set_alpha_metrics`.
When no instance is injected the handler returns a safe "not available" message.

Return type: tuple[str, InlineKeyboard]
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import structlog

from ..ui.keyboard import build_status_menu

if TYPE_CHECKING:
    from ...monitoring.alpha_metrics import AlphaMetrics

log = structlog.get_logger(__name__)

# Module-level service reference — injected at bot startup
_alpha_metrics: Optional["AlphaMetrics"] = None


def set_alpha_metrics(metrics: "AlphaMetrics") -> None:
    """Inject the AlphaMetrics instance.

    Args:
        metrics: Live AlphaMetrics accumulator from the signal pipeline.
    """
    global _alpha_metrics  # noqa: PLW0603
    _alpha_metrics = metrics
    log.info("alpha_debug_handler_metrics_injected")


async def handle_alpha_debug() -> tuple[str, list]:
    """Return alpha model debug diagnostics screen.

    Combines per-tick AlphaMetrics data to produce a concise debug view
    showing recent p_model / p_market / edge / S and aggregate statistics.

    Returns:
        ``(screen_text, keyboard)`` tuple.
    """
    if _alpha_metrics is None:
        log.warning("alpha_debug_handler_no_metrics")
        text = (
            "🔬 *ALPHA DEBUG*\n\n"
            "⚠️ Alpha metrics not available.\n"
            "Pipeline may not have started yet."
        )
        return text, build_status_menu()

    try:
        snap = _alpha_metrics.snapshot()
    except Exception as exc:
        log.error("alpha_debug_handler_snapshot_error", error=str(exc))
        text = "🔬 *ALPHA DEBUG*\n\n❌ Failed to read alpha metrics."
        return text, build_status_menu()

    # ── Last tick values ───────────────────────────────────────────────────────
    if snap.last_edge is not None:
        last_section = (
            f"*Last Tick*\n"
            f"  p\\_model:  `{snap.last_p_model:.4f}`\n"
            f"  p\\_market: `{snap.last_p_market:.4f}`\n"
            f"  edge:      `{snap.last_edge:+.4f}`\n"
            f"  S score:   `{snap.last_confidence:.4f}`\n"
        )
    else:
        last_section = "*Last Tick*\n  `— no data yet —`\n"

    # ── Aggregate statistics ───────────────────────────────────────────────────
    total = snap.total_ticks
    if total > 0:
        zero_pct = 100.0 * snap.zero_edge_count / total
        weak_pct = 100.0 * snap.weak_edge_count / total
        mod_pct = 100.0 * snap.moderate_edge_count / total
        str_pct = 100.0 * snap.strong_edge_count / total
        dist_section = (
            f"*Edge Distribution* (n={total})\n"
            f"  zero/neg:  `{snap.zero_edge_count}` ({zero_pct:.1f}%)\n"
            f"  weak <2%:  `{snap.weak_edge_count}` ({weak_pct:.1f}%)\n"
            f"  mod 2–5%:  `{snap.moderate_edge_count}` ({mod_pct:.1f}%)\n"
            f"  strong >5%:`{snap.strong_edge_count}` ({str_pct:.1f}%)\n"
        )
        avg_section = (
            f"*Averages*\n"
            f"  avg edge:      `{snap.avg_edge:+.4f}`\n"
            f"  avg pos edge:  `{snap.avg_positive_edge:.4f}`\n"
            f"  success rate:  `{snap.signal_success_rate:.1%}`\n"
            f"  signals:       `{snap.signals_generated}`\n"
        )
    else:
        dist_section = "*Edge Distribution*\n  `— no ticks evaluated yet —`\n"
        avg_section = ""

    text = (
        "🔬 *ALPHA DEBUG*\n\n"
        + last_section
        + "\n"
        + dist_section
        + "\n"
        + avg_section
    )

    log.info(
        "alpha_debug_handler_response",
        total_ticks=total,
        avg_edge=round(snap.avg_edge, 4),
        signals_generated=snap.signals_generated,
        signal_success_rate=round(snap.signal_success_rate, 4),
    )

    return text, build_status_menu()
