"""Telegram HTML message helpers — MVP v1 premium terminal (WARP-73).

Format rules for Telegram HTML parse mode:
- <b>bold</b> for headers and section titles
- <code>value</code> for inline values
- <pre>aligned block</pre> for 2+ numerical values
- <i>text</i> for CTA prompts
- · (middle dot) as row separator — clean on all mobile clients
- ────────────────── (em-dash line) as section divider — safe unicode
- NO ━━━ heavy bars as standalone lines (Telegram renders as <hr>)
- NO ├── └── box chars (look bad on mobile fonts)
"""
from __future__ import annotations

from typing import Iterable, Sequence

# Safe divider — em-dash repeated, renders cleanly as inline unicode
DIV = "─" * 28        # ────────────────────────────── (28 light box)
LIGHT_DIV = "· · · · ·"  # · · · · ·

# Backwards-compatible aliases
DIVIDER = DIV
CARD_DIVIDER = DIV

# Status constants
STATUS_RUNNING  = "🟢 Running"
STATUS_STOPPED  = "🔴 Stopped"
STATUS_PAUSED   = "🟡 Paused"
STATUS_NOT_SET  = "⚪ Not Set"
STATUS_SYNCING  = "🔵 Syncing"
PAPER           = "📝 Paper Trading"
LIVE            = "💸 Live Trading"
LOCKED          = "🔒 Locked"


def html_escape(text: str) -> str:
    """Escape HTML-reserved chars for Telegram HTML parse mode."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

# Backwards-compatible alias
md_escape = html_escape


def pnl(amount: float, currency: str = "$") -> str:
    if amount > 0:
        return f"+{currency}{amount:.2f}"
    if amount < 0:
        return f"-{currency}{abs(amount):.2f}"
    return f"={currency}0.00"


def title(text: str) -> str:
    """Bold screen title."""
    return f"<b>{html_escape(text)}</b>"


def leaf(label: str, value: str, last: bool = False) -> str:
    """Single key·value row."""
    return f"{html_escape(label)}: <code>{html_escape(value)}</code>"


def section(label: str, rows: Sequence[tuple[str, str]], last: bool = False) -> str:
    """Bold section header + indented key·value rows."""
    lines: list[str] = [f"<b>{html_escape(label)}</b>"]
    for sub_label, sub_value in rows:
        lines.append(f"  · {html_escape(sub_label)}: <code>{html_escape(sub_value)}</code>")
    return "\n".join(lines)


def pre_block(rows: Sequence[tuple[str, str]]) -> str:
    """Monospaced <pre> block for aligned numerical data."""
    if not rows:
        return ""
    max_label = max(len(str(r[0])) for r in rows)
    lines = ["<pre>"]
    for label, value in rows:
        lines.append(f"{html_escape(str(label)):<{max_label}}  {html_escape(str(value))}")
    lines.append("</pre>")
    return "\n".join(lines)


def nested(label: str, lines_iter: Iterable[str], last: bool = False) -> str:
    """Bold header + bullet list."""
    out: list[str] = [f"<b>{html_escape(label)}</b>"]
    for line in lines_iter:
        out.append(f"  • {html_escape(line)}")
    return "\n".join(out)


def divider() -> str:
    return DIV


def cta(text: str) -> str:
    return f"<i>{html_escape(text)}</i>"


def join_blocks(blocks: Iterable[str], spacer: str = "\n") -> str:
    parts = [b for b in blocks if b]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return parts[0] + "\n\n" + "\n".join(parts[1:])
