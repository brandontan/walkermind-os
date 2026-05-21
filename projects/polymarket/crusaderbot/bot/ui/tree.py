"""Hierarchy tree terminal-UI helpers for the MVP v1 Telegram surface.

All major bot messages must render through these helpers so the visual
language stays consistent across screens (blueprint section 4).

Tree characters are fixed:

    │     vertical bar
    ├──   middle branch
    └──   last branch

Status glyphs are fixed (blueprint 4.4):

    🟢 Running     🔴 Stopped     🟡 Paused
    ⚪ Not Set     🔵 Syncing
    📝 Paper Trading            💸 Live Trading
    🔒 Locked
"""
from __future__ import annotations

from typing import Iterable, Sequence

BAR = "│"
BRANCH = "├──"
LAST = "└──"

STATUS_RUNNING = "🟢 Running"
STATUS_STOPPED = "🔴 Stopped"
STATUS_PAUSED = "🟡 Paused"
STATUS_NOT_SET = "⚪ Not Set"
STATUS_SYNCING = "🔵 Syncing"
PAPER = "📝 Paper Trading"
LIVE = "💸 Live Trading"
LOCKED = "🔒 Locked"


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
    """Return the title line for a tree-format screen.

    The spacer `│` that the blueprint puts between the title and the first
    section is inserted by :func:`join_blocks`, so this returns just the title.
    """
    return text


def leaf(label: str, value: str, last: bool = False) -> str:
    """Return a single-line section: `├── label` + indented `└── value`.

    Renders as:

        ├── label
        │   └── value
    """
    head_char = LAST if last else BRANCH
    cont_bar = " " if last else BAR
    return f"{head_char} {label}\n{cont_bar}   {LAST} {value}"


def section(label: str, rows: Sequence[tuple[str, str]], last: bool = False) -> str:
    """Return a multi-row section block.

    rows: sequence of (label, value) pairs rendered as nested leaves.

    Renders as:

        ├── label
        │   ├── row1.label
        │   │   └── row1.value
        │   └── rowN.label
        │       └── rowN.value
    """
    head_char = LAST if last else BRANCH
    cont_bar = " " if last else BAR
    lines: list[str] = [f"{head_char} {label}"]
    for idx, (sub_label, sub_value) in enumerate(rows):
        sub_last = idx == len(rows) - 1
        sub_head = LAST if sub_last else BRANCH
        sub_cont = " " if sub_last else BAR
        lines.append(f"{cont_bar}   {sub_head} {sub_label}")
        lines.append(f"{cont_bar}   {sub_cont}   {LAST} {sub_value}")
    return "\n".join(lines)


def nested(label: str, lines: Iterable[str], last: bool = False) -> str:
    """Return a section whose body is a bullet list (each line under a leaf).

    Renders as:

        ├── label
        │   ├── line1
        │   └── lineN
    """
    head_char = LAST if last else BRANCH
    cont_bar = " " if last else BAR
    body = list(lines)
    out: list[str] = [f"{head_char} {label}"]
    for idx, line in enumerate(body):
        sub_last = idx == len(body) - 1
        sub_head = LAST if sub_last else BRANCH
        out.append(f"{cont_bar}   {sub_head} {line}")
    return "\n".join(out)


def join_blocks(blocks: Iterable[str], spacer: str = f"\n{BAR}\n") -> str:
    """Join section blocks with the standard blank-tree spacer."""
    parts = [b for b in blocks if b]
    return spacer.join(parts)
