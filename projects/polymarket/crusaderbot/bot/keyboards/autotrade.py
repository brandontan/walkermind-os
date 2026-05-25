"""Auto-trade keyboards — preset picker, confirm, status, controls.

KEY REDESIGN: Preset picker uses progressive disclosure by risk tier.
Instead of dumping 11 presets vertically, user first picks a risk tier
(Safe/Balanced/Advanced/Aggressive), then sees only presets in that tier.
Max 5 rows enforced at every level.

Screens:
  1. auto_home      — Quick Start / Configure / Status / Pause|Resume
  2. preset_tiers   — Risk tier picker (4 tiers, 1 back = 5 rows)
  3. preset_list    — Presets within chosen tier (max 4 + back = 5 rows)
  4. preset_confirm — Activate / Customize / Back+Home
  5. preset_status  — Edit / Switch / Pause|Resume / Stop / Home
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import BACK, HOME, back_home_row, build_kb, confirm_cancel_row
from ._constants import RISK_TIERS


# ── Screen 1: Auto-Trade Home ────────────────────────────────────

def auto_home_kb(
    *,
    running: bool = False,
    paused: bool = False,
) -> InlineKeyboardMarkup:
    """Top-level auto-trade screen. Max 3 rows + nav = 4 rows."""
    if running:
        action = InlineKeyboardButton("⏸ Pause", callback_data="auto:pause")
    elif paused:
        action = InlineKeyboardButton("▶ Resume", callback_data="auto:resume")
    else:
        action = InlineKeyboardButton("▶ Start", callback_data="auto:start")

    return build_kb(
        [
            [
                InlineKeyboardButton("🚀 Quick Start", callback_data="auto:quick_start"),
                InlineKeyboardButton("🛠 Configure",   callback_data="preset:tiers"),
            ],
            [
                InlineKeyboardButton("📊 Status", callback_data="auto:status"),
                action,
            ],
        ],
        nav=back_home_row("menu:home"),
    )


def quick_start_kb() -> InlineKeyboardMarkup:
    """Quick start — recommended preset or customize. 3 rows."""
    return build_kb(
        [
            [InlineKeyboardButton("✅ Start Recommended", callback_data="auto:start")],
            [InlineKeyboardButton("🛠 Choose Strategy",   callback_data="preset:tiers")],
        ],
        nav=[BACK],
    )


# ── Screen 2: Preset Picker (direct list — no tier indirection) ──
# Tier picker was removed: only close_sweep is visible, so showing a
# risk-tier selection step first added friction with no benefit.
# When more presets become visible, re-introduce tiers at that point.

def preset_tier_kb() -> InlineKeyboardMarkup:
    """Direct preset list — skips the tier step entirely.

    Renders all visible presets (from VISIBLE_PRESET_ORDER) as a flat
    list, max 4 presets + nav = 5 rows.
    """
    from ...domain.preset import list_presets
    from ...domain.preset.presets import RECOMMENDED_PRESET
    rows: list[list[InlineKeyboardButton]] = []
    for p in list_presets():
        label = f"{p.emoji} {p.name}"
        if p.key == RECOMMENDED_PRESET:
            label = f"{label} ⭐"
        if len(label) > 20:
            label = label[:19] + "…"
        rows.append([InlineKeyboardButton(label, callback_data=f"preset:pick:{p.key}")])
    rows.append(back_home_row("menu:autotrade"))
    return InlineKeyboardMarkup(rows)


# ── Screen 3: Presets within a tier ──────────────────────────────

def preset_list_kb(
    tier_key: str,
    preset_configs: dict,
    recommended_key: str = "signal_sniper",
) -> InlineKeyboardMarkup:
    """Step 2: show presets in chosen tier. Max 4 presets + nav = 5 rows.

    Args:
        tier_key: 'safe', 'balanced', 'advanced', 'aggressive'
        preset_configs: PRESET_CONFIG dict from bot.presets
        recommended_key: key of the recommended preset (gets ⭐)
    """
    tier_map = {
        "safe":       "🟢 Safe",
        "balanced":   "🟡 Balanced",
        "advanced":   "🟡 Advanced",
        "aggressive": "🔴 Aggressive",
    }
    tier_label = tier_map.get(tier_key, "")
    preset_keys = RISK_TIERS.get(tier_label, [])

    rows = []
    for key in preset_keys:
        cfg = preset_configs.get(key)
        if not cfg:
            continue
        name = cfg["name"]
        emoji = cfg["emoji"]
        label = f"{emoji} {name}"
        if key == recommended_key:
            label = f"{label} ⭐"
        # Truncate to MAX_LABEL_CHARS
        if len(label) > 20:
            label = label[:19] + "…"
        rows.append([InlineKeyboardButton(label, callback_data=f"preset:pick:{key}")])

    rows.append(back_home_row("preset:tiers"))
    return InlineKeyboardMarkup(rows)


# ── Screen 4: Preset Confirm ─────────────────────────────────────

def preset_confirm_kb(preset_key: str) -> InlineKeyboardMarkup:
    """Detail view: Start + Customize (2-col) + Back/Home nav. 2 rows."""
    return build_kb(
        [[
            InlineKeyboardButton("▶ Start Auto Trade",
                                 callback_data=f"preset:activate:{preset_key}"),
            InlineKeyboardButton("🛠 Customize",
                                 callback_data=f"preset:customize:{preset_key}"),
        ]],
        nav=back_home_row("preset:tiers"),
    )


# ── Screen 5: Active Preset Status ──────────────────────────────

def preset_status_kb(*, paused: bool = False) -> InlineKeyboardMarkup:
    """Running preset controls. Pause/Resume swaps. 3 rows + nav = 4."""
    pause_resume = (
        InlineKeyboardButton("▶ Resume", callback_data="preset:resume")
        if paused
        else InlineKeyboardButton("⏸ Pause", callback_data="preset:pause")
    )
    return build_kb(
        [
            [
                InlineKeyboardButton("🛠 Edit",   callback_data="preset:edit"),
                InlineKeyboardButton("🔄 Switch", callback_data="preset:switch"),
            ],
            [pause_resume, InlineKeyboardButton("🛑 Stop", callback_data="preset:stop")],
        ],
        nav=back_home_row("menu:home"),
    )


# ── Confirmations ────────────────────────────────────────────────

def preset_switch_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        confirm_cancel_row("preset:switch_yes", "preset:status",
                           "✅ Confirm Switch", "❌ Cancel"),
    ])


def preset_stop_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        confirm_cancel_row("preset:stop_yes", "preset:status",
                           "🛑 Yes, stop", "❌ Cancel"),
    ])


def pause_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        confirm_cancel_row("auto:pause:confirm", "nav:cancel",
                           "✅ Pause Bot", "❌ Cancel"),
    ])


def resume_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        confirm_cancel_row("auto:resume:confirm", "nav:cancel",
                           "✅ Resume Bot", "❌ Cancel"),
    ])


# ── Legacy p5 auto-trade surface (handlers/autotrade.py) ─────────────
# Callback data preserved exactly for the autotrade_callback parser
# (pattern ^(p5:(preset|confirm|active):|auto_trade:)).

def auto_trade_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Strategy Preset", callback_data="auto_trade:strategy")],
        [InlineKeyboardButton("⚖️ Risk Profile",    callback_data="auto_trade:risk")],
        [InlineKeyboardButton("⬅ Back",             callback_data="menu:dashboard")],
    ])


def preset_picker_p5_kb() -> InlineKeyboardMarkup:
    from ...domain.preset import RECOMMENDED_PRESET, list_presets
    rows: list[list[InlineKeyboardButton]] = []
    for p in list_presets():
        name = p.name if len(p.name) <= 20 else p.name[:20]
        label = f"{p.emoji} {name}"
        if p.key == RECOMMENDED_PRESET:
            label = f"{label} ⭐"
        rows.append([InlineKeyboardButton(label, callback_data=f"p5:preset:{p.key}")])
    rows.append([InlineKeyboardButton("⬅ Back", callback_data="auto_trade:back")])
    return InlineKeyboardMarkup(rows)


def preset_confirm_p5_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Activate",  callback_data="p5:confirm:activate"),
            InlineKeyboardButton("✏️ Customize", callback_data="p5:confirm:customize"),
        ],
        [InlineKeyboardButton("⬅ Back",          callback_data="p5:confirm:back")],
    ])


def preset_active_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Edit Config",   callback_data="p5:active:edit"),
            InlineKeyboardButton("🔄 Switch Preset", callback_data="p5:active:switch"),
        ],
        [
            InlineKeyboardButton("⏸ Pause", callback_data="p5:active:pause"),
            InlineKeyboardButton("🛑 Stop",  callback_data="p5:active:stop"),
        ],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:dashboard")],
    ])
