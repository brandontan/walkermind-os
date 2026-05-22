"""HTML message helpers for the MVP v1 Telegram surface (V5 premium terminal).

WARP-71 switches the MVP surface from Markdown to Telegram **HTML** parse mode
("Bloomberg-lite terminal in your pocket"). HTML lets us use ``<pre>`` blocks
for numerical data so columns align monospaced on every client, plus ``<b>``
headers, ``<code>`` inline values and ``<i>`` call-to-action prompts.

Layout vocabulary:

    <b>Section Header</b>
    ├── Key: <code>Value</code>
    └── Key: <code>Value</code>

    <pre>
    Label    Value
    Label    Value
    </pre>

Heavy divider ``DIV`` (━ × 32) separates major sections; ``LIGHT_DIV`` (┄ × 16)
is the lighter in-card separator. Output is sent with ``parse_mode="HTML"``
(see bot.handlers.mvp._send).

Status glyphs are fixed (blueprint 4.4):

    🟢 Running     🔴 Stopped     🟡 Paused
    ⚪ Not Set     🔵 Syncing
    📝 Paper Trading            💸 Live Trading
    🔒 Locked
"""
from __future__ import annotations

from typing import Iterable, Sequence

# Telegram-safe ASCII fallbacks (retained for any caller that references them).
BAR = "|"
BRANCH = "|-"
LAST = "`-"

# HTML-mode dividers (WARP-71).
DIV = "━" * 32
LIGHT_DIV = "┄" * 16

# Backwards-compatible aliases (pre-WARP-71 callers) → heavy section divider.
DIVIDER = DIV
CARD_DIVIDER = DIV

STATUS_RUNNING = "🟢 Running"
STATUS_STOPPED = "🔴 Stopped"
STATUS_PAUSED = "🟡 Paused"
STATUS_NOT_SET = "⚪ Not Set"
STATUS_SYNCING = "🔵 Syncing"
PAPER = "📝 Paper Trading"
LIVE = "💸 Live Trading"
LOCKED = "🔒 Locked"


def html_escape(text: str) -> str:
    """Escape the three HTML-reserved characters Telegram HTML mode requires.

    Applied to every label/value rendered through these helpers so that
    user- or market-supplied strings cannot break message formatting.
    Order matters: ``&`` must be escaped first.
    """
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# Backwards-compatible alias (pre-WARP-71 callers escaped Markdown via md_escape).
md_escape = html_escape


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
    return f"<b>{html_escape(text)}</b>"


def leaf(label: str, value: str, last: bool = False) -> str:
    """Return a single tree row: ``├── Label: <code>Value</code>``.

    ``last`` selects the └── terminator glyph for the final row in a group.
    """
    sep = "└──" if last else "├──"
    return f"{sep} {html_escape(label)}: <code>{html_escape(value)}</code>"


def section(label: str, rows: Sequence[tuple[str, str]], last: bool = False) -> str:
    """Return a bold-headed section with indented tree rows.

    Renders as:

        <b>label</b>
          ├── row1.label: <code>row1.value</code>
          └── rowN.label: <code>rowN.value</code>
    """
    lines: list[str] = [f"<b>{html_escape(label)}</b>"]
    total = len(rows)
    for idx, (sub_label, sub_value) in enumerate(rows):
        sep = "└──" if idx == total - 1 else "├──"
        lines.append(f"  {sep} {html_escape(sub_label)}: <code>{html_escape(sub_value)}</code>")
    return "\n".join(lines)


def pre_block(rows: Sequence[tuple[str, str]]) -> str:
    """Return a monospaced ``<pre>`` block with left-aligned labels.

    Used for any group of 2+ numerical values so columns align on every
    Telegram client. Returns an empty string for an empty input.
    """
    if not rows:
        return ""
    max_label = max(len(str(r[0])) for r in rows)
    lines = ["<pre>"]
    for label, value in rows:
        lines.append(f"{html_escape(str(label)):<{max_label}}  {html_escape(str(value))}")
    lines.append("</pre>")
    return "\n".join(lines)


def nested(label: str, lines: Iterable[str], last: bool = False) -> str:
    """Return a bold-headed section whose body is a bullet list.

    Renders as:

        <b>label</b>
        • line1
        • lineN
    """
    out: list[str] = [f"<b>{html_escape(label)}</b>"]
    for line in lines:
        out.append(f"• {html_escape(line)}")
    return "\n".join(out)


def divider() -> str:
    """Return the heavy section divider string."""
    return DIV


def cta(text: str) -> str:
    """Return italic call-to-action text."""
    return f"<i>{html_escape(text)}</i>"


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
