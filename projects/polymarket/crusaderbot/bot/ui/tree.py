"""Flat Markdown message helpers for the MVP v1 Telegram surface.

Box-drawing characters (│ ├── └──) do not render reliably across Telegram
clients (notably Android system fonts), producing the "berantakan" tree
output seen in production. All major bot messages therefore render through
these helpers in a flat, mobile-safe Markdown layout (WARP-67):

    *Section Header*
    Key: Value
    Key: Value

Section headers are bold (`*...*`), key/value pairs are plain single lines,
and blocks are separated by a single blank line after the title. Output is
sent with ``parse_mode="Markdown"`` (see bot.handlers.mvp._send).

ASCII fallback glyphs are retained for any caller that still references them,
but the renderers no longer emit Unicode box-drawing characters.

Status glyphs are fixed (blueprint 4.4):

    🟢 Running     🔴 Stopped     🟡 Paused
    ⚪ Not Set     🔵 Syncing
    📝 Paper Trading            💸 Live Trading
    🔒 Locked
"""
from __future__ import annotations

from typing import Iterable, Sequence

# Telegram-safe ASCII fallbacks (no Unicode box-drawing characters).
BAR = "|"
BRANCH = "|-"
LAST = "`-"

STATUS_RUNNING = "🟢 Running"
STATUS_STOPPED = "🔴 Stopped"
STATUS_PAUSED = "🟡 Paused"
STATUS_NOT_SET = "⚪ Not Set"
STATUS_SYNCING = "🔵 Syncing"
PAPER = "📝 Paper Trading"
LIVE = "💸 Live Trading"
LOCKED = "🔒 Locked"

# Telegram Markdown (v1) reserved characters that must be escaped inside any
# dynamic string (market titles, wallet addresses, user names).
_MD_SPECIAL = ("_", "*", "`", "[")


def md_escape(text: str) -> str:
    """Escape Telegram Markdown (v1) reserved characters in dynamic text.

    Applied to every label/value rendered through these helpers so that
    user- or market-supplied strings cannot break message formatting.
    """
    out = str(text)
    for ch in _MD_SPECIAL:
        out = out.replace(ch, f"\\{ch}")
    return out


def pnl(amount: float, currency: str = "$") -> str:
    """Format a signed PnL number with the directional arrow glyph.

    Examples:
        >>> pnl(2.4)
        '📈 +$2.40'
        >>> pnl(-0.8)
        '📉 -$0.80'
        >>> pnl(0)
        '＝ $0.00'
    """
    if amount > 0:
        return f"📈 +{currency}{amount:.2f}"
    if amount < 0:
        return f"📉 -{currency}{abs(amount):.2f}"
    return f"＝ {currency}0.00"


def title(text: str) -> str:
    """Return the bold title line for a screen."""
    return f"*{md_escape(text)}*"


def leaf(label: str, value: str, last: bool = False) -> str:
    """Return a single `Label: Value` line (flat format).

    The ``last`` flag is accepted for call-site compatibility but no longer
    affects rendering.
    """
    return f"{md_escape(label)}: {md_escape(value)}"


def section(label: str, rows: Sequence[tuple[str, str]], last: bool = False) -> str:
    """Return a bold-headed section block with flat `Key: Value` rows.

    Renders as:

        *label*
        row1.label: row1.value
        rowN.label: rowN.value
    """
    lines: list[str] = [f"*{md_escape(label)}*"]
    for sub_label, sub_value in rows:
        lines.append(f"{md_escape(sub_label)}: {md_escape(sub_value)}")
    return "\n".join(lines)


def nested(label: str, lines: Iterable[str], last: bool = False) -> str:
    """Return a bold-headed section whose body is a bullet list.

    Renders as:

        *label*
        • line1
        • lineN
    """
    out: list[str] = [f"*{md_escape(label)}*"]
    for line in lines:
        out.append(f"• {md_escape(line)}")
    return "\n".join(out)


def join_blocks(blocks: Iterable[str], spacer: str = "\n") -> str:
    """Join section blocks: blank line after the title, single newline after.

    The first block is treated as the screen title and is followed by one
    blank line; all subsequent blocks are joined by a single newline.
    """
    parts = [b for b in blocks if b]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return parts[0] + "\n\n" + "\n".join(parts[1:])
