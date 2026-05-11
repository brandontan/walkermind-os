"""Portfolio chart generation — server-side PNG via matplotlib (Agg backend).

Derives daily balance from the ledger table (cumulative running sum).
No external price feeds — historical balances only.

Public API:
    generate_portfolio_chart(user_id, days) -> bytes | None

Returns PNG bytes on success or None when no ledger data exists for the
requested range (caller emits a text fallback in that case).
"""
from __future__ import annotations

import io
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

logger = logging.getLogger(__name__)

_JAKARTA_OFFSET = timezone(timedelta(hours=7))
_CHART_STYLE = {
    "line_color": "#4CAF50",
    "fill_alpha": 0.18,
    "bg_color": "#1a1a2e",
    "grid_color": "#2a2a4a",
    "text_color": "#e0e0e0",
    "figsize": (9, 4.5),
    "dpi": 120,
}


def _today_jakarta() -> date:
    return datetime.now(_JAKARTA_OFFSET).date()


async def _fetch_daily_balance_series(
    user_id: UUID,
    cutoff_date: date | None,
) -> list[tuple[date, Decimal]]:
    """Return (day, cumulative_balance) pairs ordered oldest→newest.

    Strategy: sum all ledger entries grouped by day (full history), compute
    a running cumulative sum, then filter to >= cutoff_date.  The cumulative
    sum of the ledger IS the wallet balance because balance starts at 0 and
    every credit/debit flows through the ledger.
    """
    from ..database import get_pool

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                date_trunc('day', created_at AT TIME ZONE 'Asia/Jakarta')::date AS day,
                SUM(amount_usdc) AS daily_net
            FROM ledger
            WHERE user_id = $1
            GROUP BY 1
            ORDER BY 1
            """,
            user_id,
        )

    if not rows:
        return []

    running = Decimal(0)
    anchor_balance = Decimal(0)  # last cumulative balance before the window
    had_pre_window_rows = False
    series: list[tuple[date, Decimal]] = []
    for row in rows:
        running += Decimal(str(row["daily_net"] or 0))
        day: date = row["day"]
        if cutoff_date is None or day >= cutoff_date:
            series.append((day, running))
        else:
            # Keep updating anchor so it holds the balance at window start.
            anchor_balance = running
            had_pre_window_rows = True

    # Carry-forward: inject the pre-window balance as the opening anchor so
    # the chart always starts at cutoff_date with the correct balance.
    #
    # Case A — no in-window entries: flat line at the carry-forward balance.
    # Case B — in-window entries exist but start after cutoff_date: prepend
    #   the anchor so lows/highs reflect the full selected period, not just
    #   the sub-range from the first transaction.
    # Uses had_pre_window_rows (not anchor_balance != 0) so accounts whose
    # history nets to exactly $0 still receive carry-forward rather than
    # a false empty-state fallback.
    if had_pre_window_rows and cutoff_date is not None:
        if not series:
            today = _today_jakarta()
            series = [(cutoff_date, anchor_balance), (today, anchor_balance)]
        elif series[0][0] > cutoff_date:
            series.insert(0, (cutoff_date, anchor_balance))

    return series


def _generate_png(
    series: list[tuple[date, Decimal]],
    days_label: str,
) -> bytes:
    """Render the balance series to a PNG and return raw bytes."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    dates = [s[0] for s in series]
    balances = [float(s[1]) for s in series]

    fig, ax = plt.subplots(figsize=_CHART_STYLE["figsize"], dpi=_CHART_STYLE["dpi"])
    fig.patch.set_facecolor(_CHART_STYLE["bg_color"])
    ax.set_facecolor(_CHART_STYLE["bg_color"])

    ax.plot(dates, balances, color=_CHART_STYLE["line_color"], linewidth=2, zorder=3)
    ax.fill_between(
        dates, balances,
        alpha=_CHART_STYLE["fill_alpha"],
        color=_CHART_STYLE["line_color"],
        zorder=2,
    )

    ax.set_title(
        f"PORTFOLIO — {days_label}",
        color=_CHART_STYLE["text_color"],
        fontsize=13,
        pad=10,
    )
    ax.set_xlabel("Date", color=_CHART_STYLE["text_color"], fontsize=9)
    ax.set_ylabel("Balance (USD)", color=_CHART_STYLE["text_color"], fontsize=9)

    ax.tick_params(colors=_CHART_STYLE["text_color"], labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor(_CHART_STYLE["grid_color"])

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=8))
    fig.autofmt_xdate(rotation=30, ha="right")

    ax.grid(True, color=_CHART_STYLE["grid_color"], linestyle="--",
            linewidth=0.5, alpha=0.7, zorder=1)

    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda x, _: f"${x:,.2f}")
    )

    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _compute_stats(
    series: list[tuple[date, Decimal]],
) -> tuple[Decimal, Decimal, Decimal]:
    """Return (peak, low, now) from the balance series."""
    if not series:
        return Decimal(0), Decimal(0), Decimal(0)
    balances = [s[1] for s in series]
    return max(balances), min(balances), balances[-1]


async def generate_portfolio_chart(
    user_id: UUID,
    days: int | None = 7,
) -> tuple[bytes, Decimal, Decimal, Decimal] | None:
    """Generate a portfolio balance chart PNG.

    Args:
        user_id: The user's UUID.
        days: Window size in calendar days (7, 30) or None for all-time.

    Returns:
        (png_bytes, peak, low, now) or None when no ledger data exists.
    """
    today = _today_jakarta()
    cutoff: date | None = None
    if days is not None:
        cutoff = today - timedelta(days=days - 1)

    series = await _fetch_daily_balance_series(user_id, cutoff)
    if not series:
        return None

    days_label = f"{days} DAYS" if days is not None else "ALL TIME"
    try:
        png = _generate_png(series, days_label)
    except Exception as exc:
        logger.error("portfolio chart render failed user=%s: %s", user_id, exc)
        return None

    peak, low, now = _compute_stats(series)
    return png, peak, low, now
